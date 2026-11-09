"""Offer sheets: compensation, validation, owner decisions, the user's match window."""
import json
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import offer_sheets as OS
from hs.game import offseason as O
from hs.game.dayloop import sim_until
from hs.game.trades import pick_owner
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class CompTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_table_and_basis(self):
        t = OS.comp_table(self.c)
        self.assertEqual(OS.compensation(self.c, t[0][0] - 1, 3), [])
        self.assertEqual(OS.compensation(self.c, t[2][0] - 1, 3), [2])
        self.assertEqual(OS.compensation(self.c, t[-2][0] + 1, 3), [1, 1, 1, 1])
        # AAV is total value over at most five years: an 8-year deal counts as more per year
        aav = t[3][0] - 10_000
        self.assertEqual(OS.compensation(self.c, aav, 5), [1, 3])
        self.assertEqual(OS.compensation(self.c, aav, 7), [1, 1, 2, 3])          # 7/5 x AAV: a tier higher

    def test_consecutive_firsts(self):
        picks = OS.comp_picks(self.c, self.me, [1, 1, 2, 3])
        firsts = sorted(y for y, r, o in picks if r == 1)
        self.assertEqual(firsts[1] - firsts[0], 1)
        self.assertTrue(all(o == self.me for _, _, o in picks))


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        OS.ai_offer_sheets, self._real = (lambda conn, day: []), OS.ai_offer_sheets     # keep the AI out of it
        self.addCleanup(setattr, OS, "ai_offer_sheets", self._real)
        sim_until(self.c, ENV, Skill(), to_end=True)
        while K.season_state(self.c) != "free_agency":
            O.advance(self.c, ENV, Skill())
        self.year = K.season_year(self.c)

    def rfa(self, mine):
        q = "team_id=?" if mine else "team_id<>?"
        sql = (f"SELECT * FROM offseason_rights WHERE season_start_year=? AND status='RFA' AND "
               f"COALESCE(qualified,1)=1 AND outcome IS NULL AND {q} ORDER BY prev_aav DESC")
        r = self.c.execute(sql, (self.year, self.me)).fetchone()
        if r is None and mine:                         # borrow one: make another club's RFA ours
            o = self.c.execute(sql.replace("team_id=?", "team_id<>?"), (self.year, self.me)).fetchone()
            if o is not None:
                self.c.execute("UPDATE offseason_rights SET team_id=? WHERE season_start_year=? AND player_id=?",
                               (self.me, self.year, o["player_id"]))
                self.c.execute("UPDATE players SET team_id=?, club_id=? WHERE player_id=?",
                               (self.me, self.me, o["player_id"]))
                r = self.c.execute(sql, (self.year, self.me)).fetchone()
        if r is None:
            self.skipTest("no qualified RFA available")
        return r

    def test_validation(self):
        mine = self.rfa(True)
        with self.assertRaises(ValueError):
            OS.make(self.c, self.me, mine["player_id"], 2_000_000, 3, K.today(self.c))      # own player
        theirs = self.rfa(False)
        with self.assertRaises(ValueError):
            OS.make(self.c, self.me, theirs["player_id"], 1_000_000, 9, K.today(self.c))    # term too long
        # without our own 1st, a 1st-round-compensation sheet is not allowed
        t = OS.comp_table(self.c)
        aav = t[3][0] - 1000
        for y, r, o in OS.comp_picks(self.c, self.me, OS.compensation(self.c, aav, 3)):
            self.c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                           (y, r, o, theirs["team_id"], "test"))
        with self.assertRaises(ValueError):
            OS.make(self.c, self.me, theirs["player_id"], aav, 3, K.today(self.c))

    def test_owner_who_cannot_fit_him_takes_the_picks(self):
        r = self.rfa(False)
        owner, pid = r["team_id"], r["player_id"]
        cap = K.crules(self.c)["cap_ceiling"]
        self.c.execute("INSERT INTO cap_charges (team_id, season_start_year, amount, reason) VALUES (?,?,?,?)",
                       (owner, K.signing_year(self.c), cap, "test squeeze"))
        aav = max(r["qo"] or 0, K.crules(self.c)["min_salary"]) + 1_000_000
        text = OS.make(self.c, self.me, pid, aav, 3, K.today(self.c))
        self.assertIn("take the picks", text)
        self.assertEqual(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                         self.me)
        for y, rnd, o in OS.comp_picks(self.c, self.me, OS.compensation(self.c, aav, 3)):
            self.assertEqual(pick_owner(self.c, y, rnd, o), owner)

    def test_user_matches_or_loses_him(self):
        r = self.rfa(True)
        other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>?", (self.me,)).fetchone()[0]
        self.c.execute("DELETE FROM draft_pick_owners WHERE original_team_id=?", (other,))   # owns its own picks
        pid = r["player_id"]
        aav = max(r["qo"] or 0, K.crules(self.c)["min_salary"]) + 500_000
        msg = OS.make(self.c, other, pid, aav, 2, K.today(self.c))
        self.assertIn("match", msg)
        self.assertEqual(OS.sheets(self.c)[-1]["status"], "pending")
        OS.match(self.c, self.me, pid, K.today(self.c))
        c = K.current_contract(self.c, pid, K.signing_year(self.c))
        self.assertEqual((c["team_id"], c["cap_hit"]), (self.me, aav))

    def test_unmatched_sheet_goes_through_at_the_arbitration_phase(self):
        r = self.rfa(True)
        other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>?", (self.me,)).fetchone()[0]
        self.c.execute("DELETE FROM draft_pick_owners WHERE original_team_id=?", (other,))   # owns its own picks
        pid = r["player_id"]
        aav = max(r["qo"] or 0, K.crules(self.c)["min_salary"]) + 500_000
        OS.make(self.c, other, pid, aav, 2, K.today(self.c))
        lines = O.advance(self.c, ENV, Skill())                     # -> arbitration
        self.assertTrue(any("did not match" in l for l in lines), lines)
        self.assertEqual(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0], other)
        self.assertEqual(json.loads(OS.sheets(self.c)[-1]["comp"]), OS.compensation(self.c, aav, 2))


if __name__ == "__main__":
    unittest.main()
