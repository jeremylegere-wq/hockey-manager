"""v0.62: approved-list no-trade clauses (#11), the trade screen's needs tab and the free-agent centre's transfer
summary (#9), the staff index, alumni, draft surprises and demographics reports (#16), and locked line slots (#5)."""
import random
import tempfile
import unittest

from hs.game import clauses as CL
from hs.game import contracts as K
from hs.game import editor as ED
from hs.game import gm_trades as GT
from hs.game import negotiation as N
from hs.game import roster as R
from hs.game import trades as T
from hs.game.state import get_state

from test_game import make_db


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        GT.ensure_tables(self.c)
        self.day = get_state(self.c)[0]

    def a_player(self, team=None):
        return next(r["player_id"] for r in R.roster(self.c, team or self.me) if r["status"] == "active")


class ApprovedListTests(Base):
    def setUp(self):
        super().setUp()
        self.m = T.Market(self.c, self.day)                   # generates clauses and the clubs' competitive state
        self.pid = self.a_player()
        k = K.current_contract(self.c, self.pid)
        CL.set_clause(self.c, self.pid, k["contract_id"], "MNTC_A", 3, k["start_year"], k["start_year"] + k["years"] - 1)
        CL.refresh_lists(self.c, self.m.S)

    def test_he_names_the_clubs_he_rates_best(self):
        cl = CL.of(self.c, self.pid)
        self.assertEqual(len(cl["allowed"]), 3)
        self.assertIsNone(cl["blocked"])
        self.assertNotIn(self.me, cl["allowed"])
        others = sorted((t for t in self.m.S if t != self.me), key=lambda t: -self.m.S[t])
        avg_list = sum(self.m.S[t] for t in cl["allowed"]) / 3
        avg_all = sum(self.m.S[t] for t in others) / len(others)
        self.assertGreater(avg_list, avg_all)                 # contenders, with some noise of his own
        self.assertIn("approved", cl["label"])
        self.assertTrue(cl["short"].endswith("OK"))

    def test_trade_off_the_list_needs_a_waiver(self):
        cl = CL.of(self.c, self.pid)
        ok = cl["allowed"][0]
        off = next(t for t in self.m.S if t != self.me and t not in cl["allowed"])
        self.assertIsNone(CL.check(self.c, self.pid, ok, 0.5, 0.5, 0.75, 0.75))
        why = CL.check(self.c, self.pid, off, 0.5, 0.5, 0.75, 0.75)
        self.assertIn("approved list", why)
        self.assertIsNone(CL.check(self.c, self.pid, off, 0.2, 0.9, 0.5, 0.75))    # clearly better for him: he waives
        self.assertIsNone(CL.check(self.c, self.pid, off, 0.5, 0.5, 0.75, 0.75, requested=True))

    def test_roster_trade_respects_it(self):
        cl = CL.of(self.c, self.pid)
        off = next(t for t in self.m.S if t != self.me and t not in cl["allowed"])
        self.assertIsNotNone(CL.consent(self.c, self.pid, self.me, off, requested=False) or
                             CL.check(self.c, self.pid, off, 0.5, 0.5, 0.75, 0.75))

    def test_ai_never_moves_him_off_the_list(self):
        from hs.game.trades import _clause_ok
        cl = CL.of(self.c, self.pid)
        off = [t for t in self.m.S if t != self.me and t not in cl["allowed"]]
        refused = [t for t in off if _clause_ok(self.m, self.pid, self.me, t)]
        allowed = [t for t in cl["allowed"] if _clause_ok(self.m, self.pid, self.me, t) is None]
        self.assertEqual(len(allowed), 3)
        self.assertTrue(refused)                              # most clubs off the list are refused

    def test_friction_between_list_and_full(self):
        from hs.game import trade_model as TM
        self.assertGreater(self.m.friction(self.pid, self.me), 0)
        self.assertTrue(TM.F_MNTC < (TM.F_MNTC + TM.F_NTC) / 2 < TM.F_NTC)


class ApprovedListSourcesTests(Base):
    def test_roll_writes_some_approved_lists(self):
        rng = random.Random(1)
        kinds = [CL.roll(rng, 6_000_000, 4, 30) for _ in range(4000)]
        kinds = [k for k in kinds if k]
        mntc = sum(1 for k, _ in kinds if k == "MNTC")
        ok = [n for k, n in kinds if k == "MNTC_A"]
        self.assertTrue(ok and mntc)
        self.assertTrue(0.2 < len(ok) / (len(ok) + mntc) < 0.4)
        self.assertTrue(all(8 <= n <= 12 for n in ok))

    def test_talks_and_editor(self):
        self.assertIn("mntc_ok", N.CLAUSE_LEVEL)
        self.assertLess(N.CLAUSE_LEVEL["mntc"], N.CLAUSE_LEVEL["mntc_ok"])
        self.assertLess(N.CLAUSE_LEVEL["mntc_ok"], N.CLAUSE_LEVEL["ntc"])
        self.assertIn("approved", N.CLAUSE_TEXT["mntc_ok"])
        self.assertEqual(ED.clean(self.c, "clause", "MNTC_A:9"), ("MNTC_A", 9))
        self.assertEqual(ED.clean(self.c, "clause", "M-NTC-A"), ("MNTC_A", 8))
        self.assertEqual(ED.clean(self.c, "clause", "MNTC:12"), ("MNTC", 12))

    def test_player_contract_shows_the_list(self):
        from hs.ui import api
        pid = self.a_player()
        k = K.current_contract(self.c, pid)
        CL.set_clause(self.c, pid, k["contract_id"], "MNTC_A", 2, k["start_year"], k["start_year"] + k["years"] - 1)
        T.Market(self.c, self.day)                            # names the list
        d = api._contract_dict(self.c, pid, K.season_year(self.c))
        self.assertIn("traded only to", d["clause"])


class TransferSummaryTests(Base):
    def test_moves_and_club_lines(self):
        from hs.ui import screens as SC
        other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]
        a, b = self.a_player(), self.a_player(other)
        day = self.day
        self.c.executemany("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES (?,?,?,?,?,?)",
                           [(day, "trade", a, self.me, other, "traded"), (day, "release", b, other, None, "became a free agent (UFA)"),
                            (day, "draft", b, None, other, "drafted")])                  # a draft pick is not a transfer
        rows, clubs, start, end = SC.transfer_summary(self.c, since=day)
        mine = [r for r in rows if r["team_id"] == self.me]
        theirs = [r for r in rows if r["team_id"] == other]
        self.assertEqual([(r["dir"], r["how"], r["other"]) for r in mine], [("out", "trade", mine[0]["other"])])
        self.assertEqual(sorted((r["dir"], r["how"]) for r in theirs), [("in", "trade"), ("out", "left as a free agent")])
        line = next(c for c in clubs if c["team_id"] == other)
        self.assertEqual((line["ins"], line["outs"]), (1, 1))
        self.assertEqual(line["net_cap"], line["cap_in"] - line["cap_out"])
        hub = SC.transactions_hub(self.c, "summary", team=other)
        self.assertEqual([c["team_id"] for c in hub["clubs_summary"]], [other])

    def test_window_starts_after_the_season(self):
        from hs.ui import screens as SC
        start, end = SC.summary_window(self.c)
        self.assertLessEqual(start, end)


class StaffIndexTests(Base):
    def test_every_staff_member_with_moves(self):
        from hs.game import staff as S
        from hs.ui import screens as SC
        S.ensure_tables(self.c)
        if not self.c.execute("SELECT COUNT(*) FROM staff").fetchone()[0]:
            S.setup(self.c)
        d = SC.staff_index(self.c)
        self.assertEqual(len(d["rows"]), self.c.execute("SELECT COUNT(*) FROM staff").fetchone()[0])
        self.assertEqual(d["rows"][0]["role"], "HC")                          # head coaches first
        free = self.c.execute("SELECT staff_id, role FROM staff WHERE team_id IS NULL LIMIT 1").fetchone()
        if free is None:
            S.refill_market(self.c)
            free = self.c.execute("SELECT staff_id, role FROM staff WHERE team_id IS NULL LIMIT 1").fetchone()
        t = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]
        old = S.members(self.c, t, free["role"])[0]
        S.dismiss(self.c, t, old["staff_id"], self.day)
        S.hire(self.c, t, free["staff_id"], self.day)
        rows = {r["staff_id"]: r for r in SC.staff_index(self.c, free["role"])["rows"]}
        self.assertEqual([m["what"] for m in rows[free["staff_id"]]["moves"]], ["hired"])
        self.assertEqual([m["what"] for m in rows[old["staff_id"]]["moves"]], ["let go"] if free["role"] != "HC" else ["fired"])
        self.assertTrue(all(r["role"] == free["role"] for r in rows.values()))
        avail = SC.staff_index(self.c, team=0)["rows"]
        self.assertTrue(avail and all(r["team_id"] is None for r in avail))


class AlumniTests(Base):
    def test_players_who_played_for_the_club(self):
        from hs.game.dayloop import sim_until
        from hs.sim.engine import Skill
        from hs.ui import screens as SC
        from test_sim import ENV
        sim_until(self.c, ENV, Skill(), self.me, through_user_game=True)
        d = SC.alumni(self.c, self.me)
        self.assertTrue(d["rows"])
        self.assertTrue(all(r["gp"] + r["po_gp"] >= 1 for r in d["rows"]))
        gp = [r["gp"] for r in d["rows"]]
        self.assertEqual(gp, sorted(gp, reverse=True))
        # a player traded away stays an alumnus, now elsewhere
        pid = d["rows"][0]["player_id"]
        other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]
        self.c.execute("UPDATE players SET team_id=? WHERE player_id=?", (other, pid))
        row = next(r for r in SC.alumni(self.c, self.me)["rows"] if r["player_id"] == pid)
        self.assertFalse(row["current"])
        self.assertGreaterEqual(SC.alumni(self.c, self.me)["former"], 1)
        with self.assertRaises(ValueError):
            SC.alumni(self.c, 99999)


class CoachingPointsTests(Base):
    def setUp(self):
        super().setUp()
        from hs.game import staff as S
        S.ensure_tables(self.c)
        if not self.c.execute("SELECT COUNT(*) FROM staff WHERE team_id=?", (self.me,)).fetchone()[0]:
            S.setup(self.c)

    def test_points_follow_the_staff(self):
        from hs.game import training as TR
        pts = TR.category_points(self.c, self.me)
        self.assertEqual(set(pts), {"offence", "defence", "skating", "physical", "mental", "positioning", "reflexes"})
        self.assertTrue(all(1 <= v <= 20 for v in pts.values()))
        self.c.execute("UPDATE staff SET coaching=20 WHERE team_id=? AND role='GC'", (self.me,))
        self.assertEqual(TR.category_points(self.c, self.me)["reflexes"], 20)
        self.assertAlmostEqual(TR.boost(self.c, self.me, "reflexes"), 1.8)
        self.c.execute("UPDATE staff SET coaching=4 WHERE team_id=? AND role='GC'", (self.me,))
        self.assertAlmostEqual(TR.boost(self.c, self.me, "positioning"), 1.4)
        self.assertEqual(TR.boost(self.c, self.me, "balanced"), 1.6)
        self.assertEqual(TR.boost(self.c, None, "offence"), 1.6)

    def test_boost_moves_more_into_the_focus(self):
        import random as _r
        from hs.game import ratings as RT
        from hs.attributes import RATING_COLS
        keys = RT.DEVELOPS["S"]
        base = {k: 10 for k in RATING_COLS}
        foc = RT.focus_ratings(__import__("hs.game.training", fromlist=["x"]).FOCUS["offence"])
        lo = RT.develop(base, "C", 1.0, _r.Random(1), 21, foc, noise=0.0, boost=1.4)
        hi = RT.develop(base, "C", 1.0, _r.Random(1), 21, foc, noise=0.0, boost=1.8)
        gain = lambda d: sum(d[k] - 10 for k in foc if k in keys)
        self.assertGreaterEqual(gain(hi), gain(lo))

    def test_goalie_slots(self):
        from hs.game import training as TR
        goalies = [r[0] for r in self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position='G' AND "
                                                "status IN ('active','injured','prospect')", (self.me,))]
        self.assertGreaterEqual(len(goalies), 2)
        self.c.execute("UPDATE staff SET coaching=10 WHERE team_id=? AND role='GC'", (self.me,))
        self.assertEqual(TR.slot_count(self.c, self.me), 2)
        self.c.execute("UPDATE staff SET coaching=18 WHERE team_id=? AND role='GC'", (self.me,))
        self.assertEqual(TR.slot_count(self.c, self.me), 4)
        self.c.execute("UPDATE staff SET coaching=10 WHERE team_id=? AND role='GC'", (self.me,))
        chosen, auto = TR.goalie_slots(self.c, self.me)
        self.assertEqual(chosen, [])
        self.assertEqual(len(auto), min(2, len(goalies)))
        TR.set_goalie_slot(self.c, self.me, goalies[-1])
        chosen, auto = TR.goalie_slots(self.c, self.me)
        self.assertEqual(chosen, [goalies[-1]])
        self.assertNotIn(goalies[-1], auto)
        if len(goalies) > 2:
            TR.set_goalie_slot(self.c, self.me, goalies[0])
            with self.assertRaises(ValueError):
                TR.set_goalie_slot(self.c, self.me, next(g for g in goalies if g not in TR.goalie_slots(self.c, self.me)[0]))
        skater = self.a_player()
        with self.assertRaises(ValueError):
            TR.set_goalie_slot(self.c, self.me, skater)
        TR.set_goalie_slot(self.c, self.me, goalies[-1], on=False)
        self.assertNotIn(goalies[-1], TR.goalie_slots(self.c, self.me)[0])

    def test_slot_factor(self):
        from hs.game import training as TR
        from hs.game import contracts as K2
        g = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position='G' LIMIT 1", (self.me,)).fetchone()[0]
        y = K2.season_year(self.c)
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{y - 20}-03-01", g))
        TR.set_goalie_slot(self.c, self.me, g)
        self.c.execute("UPDATE staff SET coaching=20 WHERE team_id=? AND role='GC'", (self.me,))
        self.assertAlmostEqual(TR.goalie_slot_factor(self.c, self.me, g), 1.15)
        self.c.execute("UPDATE staff SET coaching=10 WHERE team_id=? AND role='GC'", (self.me,))
        self.assertAlmostEqual(TR.goalie_slot_factor(self.c, self.me, g), 1.06)
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{y - 30}-03-01", g))
        self.assertEqual(TR.goalie_slot_factor(self.c, self.me, g), 1.0)          # a veteran: no slot effect

    def test_development_view_has_both(self):
        from hs.ui import api
        d = api.development_view(self.c)
        self.assertEqual(len(d["coaching"]), 7)
        self.assertIn("n", d["goalie_slots"])


class MediaProfileTests(Base):
    def test_coverage_follows_the_market(self):
        from hs.game import finance as FN
        from hs.game import media_profile as MP
        FN.setup(self.c)
        self.c.execute("UPDATE club_finance SET market=10 WHERE team_id=?", (self.me,))
        self.assertEqual(MP.coverage(self.c, self.me), 5)
        self.assertEqual(MP.postgame_chance(self.c, self.me), 1 / 4)
        self.assertEqual(MP.base_pressure(self.c, self.me), 50)
        self.c.execute("UPDATE club_finance SET market=1 WHERE team_id=?", (self.me,))
        self.assertEqual(MP.coverage(self.c, self.me), 1)
        self.assertEqual(MP.base_pressure(self.c, self.me), 30)
        self.assertIn(MP.attitude(self.c, self.me), MP.ATTITUDE_BASE)
        self.assertEqual(MP.attitude(self.c, self.me), MP.attitude(self.c, self.me))      # fixed for the save

    def test_focus_players(self):
        from hs.game import media_profile as MP
        from hs.game.roster import player_value
        f = MP.focus_players(self.c, self.me)
        kinds = [k for _, k in f]
        self.assertEqual(kinds[0], "star")
        self.assertEqual(len({p for p, _ in f}), len(f))
        star = f[0][0]
        roster = [r[0] for r in self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')", (self.me,))]
        self.assertEqual(player_value(self.c, star), max(player_value(self.c, p) for p in roster))
        self.assertEqual(MP.focus_players(self.c, self.me), f)                       # kept for the season
        other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]
        self.c.execute("UPDATE players SET team_id=? WHERE player_id=?", (other, star))
        again = MP.focus_players(self.c, self.me)
        self.assertNotIn(star, [p for p, _ in again])
        from hs.game import press
        self.assertEqual(press._top_players(self.c, self.me)[0], again[0][0])         # questions go to them first

    def test_press_view_has_the_profile(self):
        from hs.game import press
        v = press.view(self.c)
        self.assertIn("coverage", v["profile"])
        self.assertTrue(v["profile"]["focus"])


if __name__ == "__main__":
    unittest.main()
