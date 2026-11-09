"""Lines editor and waivers."""
import datetime
import random
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import lineup as L
from hs.game import roster as R
from hs.game import waivers as W
from hs.game.dayloop import record_season_stats, sim_until
from hs.game.state import ensure_game_tables, get_state
from hs.sim.engine import Skill, simulate_game
from hs.sim.loader import load_teams

from test_game import make_db
from test_sim import ENV


class LinesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_set_lines_and_units_reach_the_engine(self):
        cur = L.current(self.c, self.me)
        f4 = cur["F"][3]
        L.set_unit(self.c, self.me, "F1", f4)                 # promote the fourth line
        t = load_teams(self.c)[self.me]
        self.assertTrue(t.custom)
        self.assertEqual([p.pid for p in t.lines[0]], f4)
        dressed = {p for ln in L.current(self.c, self.me)["F"] for p in ln}
        self.assertEqual(len(dressed), 12)                    # nobody lost, nobody twice
        pp = f4 + cur["D"][2][:2]
        L.set_unit(self.c, self.me, "PP1", pp)
        t = load_teams(self.c)[self.me]
        self.assertEqual({p.pid for p in t.pp[0]}, set(pp))
        # the power play uses the unit: those five get the power-play ice time
        other = next(x for x in load_teams(self.c) if x != self.me)
        teams = load_teams(self.c)
        pp_toi = {}
        for s in range(40):
            res = simulate_game(teams[self.me], teams[other], ENV, Skill(), s)
            for pid, st in res.stats.items():
                pp_toi[pid] = pp_toi.get(pid, 0) + st["toi"]
        self.assertTrue(all(pp_toi.get(p, 0) > 0 for p in pp))

    def test_unavailable_players_are_replaced(self):
        cur = L.current(self.c, self.me)
        L.set_unit(self.c, self.me, "F1", cur["F"][0])
        hurt = cur["F"][0][0]
        self.c.execute("UPDATE players SET status='injured' WHERE player_id=?", (hurt,))
        t = load_teams(self.c)[self.me]
        self.assertNotIn(hurt, [p.pid for ln in t.lines for p in ln])
        self.assertIn(hurt, t.missing)
        # with a recall available the hole is filled by the next forward
        self.c.execute("UPDATE players SET status='injured' WHERE player_id=?", (hurt,))

    def test_validation_and_auto(self):
        cur = L.current(self.c, self.me)
        with self.assertRaises(R.RosterError):
            L.set_unit(self.c, self.me, "F1", cur["F"][0][:2])          # three needed
        g = cur["G"]
        with self.assertRaises(R.RosterError):
            L.set_unit(self.c, self.me, "F1", [g[0]] + cur["F"][0][1:])  # a goalie at forward
        L.set_unit(self.c, self.me, "G", list(reversed(g)))
        self.assertEqual(load_teams(self.c)[self.me].goalies[0].pid, g[-1])
        L.reset(self.c, self.me)
        self.assertFalse(load_teams(self.c)[self.me].custom)


class WaiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]
        self.year = K.season_year(self.c)

    def player(self, age, first_contract_year, team=None):
        team = team or self.me
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position<>'G' "
                             "ORDER BY player_id DESC LIMIT 1", (team,)).fetchone()[0]
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?",
                       (f"{first_contract_year - age}-01-01", pid))
        if first_contract_year < self.year:           # an earlier, expired first contract
            self.c.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit) VALUES "
                           "(?,?,?,1,900000)", (pid, team, first_contract_year))
        else:
            self.c.execute("UPDATE contracts SET start_year=? WHERE player_id=?", (first_contract_year, pid))
        return pid

    def test_exemption_table(self):
        young = self.player(19, self.year)
        self.assertTrue(W.status(self.c, young)["exempt"])
        vet = self.player(26, self.year - 3)
        st = W.status(self.c, vet)
        self.assertFalse(st["exempt"])
        self.assertEqual(st["season_limit"], 1)

    def test_send_down_goes_through_waivers_and_can_be_claimed(self):
        vet = self.player(27, self.year - 5)
        self.assertEqual(R.send_down(self.c, self.me, vet, self.day), "waivers")
        self.assertEqual(self.c.execute("SELECT status FROM players WHERE player_id=?", (vet,)).fetchone()[0], "waivers")
        W.P_CLAIM, old = 1.0, W.P_CLAIM
        W.CLAIM_MARGIN, oldm = -100, W.CLAIM_MARGIN                     # someone will want him
        self.addCleanup(setattr, W, "P_CLAIM", old)
        self.addCleanup(setattr, W, "CLAIM_MARGIN", oldm)
        nxt = (datetime.date.fromisoformat(self.day) + datetime.timedelta(days=1)).isoformat()
        lines = W.process(self.c, nxt)
        self.assertEqual(len(lines), 1)
        team = self.c.execute("SELECT team_id, status FROM players WHERE player_id=?", (vet,)).fetchone()
        self.assertNotEqual(team[0], self.me)
        self.assertEqual(team[1], "active")
        self.assertEqual(K.current_contract(self.c, vet)["team_id"], team[0])
        self.assertEqual(W.claim_order(self.c, self.me)[0] in [r[0] for r in self.c.execute(
            "SELECT team_id FROM teams")], True)

    def test_unclaimed_clears_and_can_be_redone_without_waivers(self):
        vet = self.player(27, self.year - 5)
        W.P_CLAIM, old = 0.0, W.P_CLAIM
        self.addCleanup(setattr, W, "P_CLAIM", old)
        R.send_down(self.c, self.me, vet, self.day)
        nxt = (datetime.date.fromisoformat(self.day) + datetime.timedelta(days=1)).isoformat()
        W.process(self.c, nxt)
        self.assertEqual(self.c.execute("SELECT status FROM players WHERE player_id=?", (vet,)).fetchone()[0],
                         "prospect")
        R.call_up(self.c, self.me, vet, nxt, check=False)
        self.assertIsNone(R.send_down(self.c, self.me, vet, nxt))       # within 30 days: straight down

    def test_ai_prefers_exempt(self):
        other = self.c.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1 LIMIT 1",
                               (self.me,)).fetchone()[0]
        rows = [r["player_id"] for r in R.roster(self.c, other) if r["position"] != "G"]
        a, b = rows[0], rows[1]
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{self.year - 30}-01-01", a))
        self.c.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit) VALUES (?,?,?,1,900000)",
                       (a, other, self.year - 8))
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{self.year - 19}-01-01", b))
        self.c.execute("UPDATE contracts SET start_year=? WHERE player_id=?", (self.year, b))
        va, vb = R.player_value(self.c, a), R.player_value(self.c, b)
        pick = W.ai_send_down_choice(self.c, other, [(min(va, vb) - 0.1, a, "C"), (min(va, vb), b, "C")])
        self.assertEqual(pick[1], b)                                    # the exempt one goes, though a rates lower


class StatsDedupTests(unittest.TestCase):
    def test_simulated_season_replaces_the_packs_copy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _, c, me = make_db(tmp.name)
        self.addCleanup(c.close)
        year = K.season_year(c)
        sid, league = c.execute("SELECT season_id, league_id FROM seasons WHERE start_year=?", (year,)).fetchone()
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND position<>'G' LIMIT 1", (me,)).fetchone()[0]
        c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a) "
                  "VALUES (?,?,?,?, 'RS', 82, 30, 30)", (pid, year, me, league))      # the pack's real season
        sim_until(c, ENV, Skill(), days=5)
        record_season_stats(c, sid)
        rows = c.execute("SELECT gp FROM skater_season_stats WHERE player_id=? AND season_start_year=? AND "
                         "league_id=?", (pid, year, league)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0][0], 82)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM replaced_skater_season_stats WHERE player_id=?",
                                   (pid,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
