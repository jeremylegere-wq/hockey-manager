"""v47: challenge mode, challenges and the commissioner tools."""
import tempfile
import unittest

from hs.game import challenge as CH
from hs.game import commissioner as CM
from hs.game import editor as ED
from hs.game.state import get_state, user_team

from test_world import small_world


def _world(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    db, c, me = small_world(tmp.name)
    test.addCleanup(c.close)
    return c, me


def _season_result(c, team, rnd):
    from hs.game.history import ensure_tables
    ensure_tables(c)
    y = CH._season(c)
    c.execute("INSERT OR REPLACE INTO team_seasons (season_start_year, team_id, league_id, gp, w, l, otl, t, pts, gf, ga, div_rank, "
              "conf_rank, league_rank, playoff_round, playoff_text) VALUES (?,?,1,82,40,30,12,0,92,250,240,3,6,12,?, '')", (y, team, rnd))


class ChallengeModeTests(unittest.TestCase):
    def test_mode(self):
        c, me = _world(self)
        self.assertFalse(CH.mode_on(c))
        CH.check_sim(c, "season")                              # allowed outside challenge mode
        CH.set_mode(c, True)
        self.assertTrue(CH.mode_on(c))
        with self.assertRaises(ValueError):
            CH.set_mode(c, False)
        with self.assertRaises(ValueError):
            ED.set_enabled(c, True)
        with self.assertRaises(ValueError):
            CH.check_sim(c, "season")
        with self.assertRaises(ValueError):
            CH.check_sim(c, "to", 30)
        CH.check_sim(c, "to", 5)
        CH.check_sim(c, "week")
        c.execute("UPDATE pack_info SET value='draft' WHERE key='season_state'")
        CH.check_sim(c, "season")                              # the off-season is free

    def test_edited_save_cannot_turn_on(self):
        c, me = _world(self)
        ED.set_enabled(c, True)
        with self.assertRaises(ValueError):
            CH.set_mode(c, True)


class ChallengeTests(unittest.TestCase):
    def test_turnaround_won(self):
        c, me = _world(self)
        ok, _ = CH.can_start(c)
        self.assertTrue(ok)
        x = CH.start(c, "turnaround")
        self.assertEqual((x["status"], x["deadline"]), ("on", CH._season(c) + 1))
        with self.assertRaises(ValueError):
            CH.start(c, "rebuild")                             # one at a time
        _season_result(c, me, 1)
        CH.season_end(c, get_state(c)[0])
        self.assertEqual(CH.current(c)["status"], "won")
        self.assertEqual(CH.history(c)[0]["status"], "won")

    def test_win_now_deadline(self):
        c, me = _world(self)
        x = CH.start(c, "win_now")
        y = CH._season(c)
        _season_result(c, me, 3)
        CH.season_end(c, get_state(c)[0])
        self.assertEqual(CH.current(c)["status"], "on")
        # the deadline season ends without a title
        c.execute("UPDATE seasons SET start_year=start_year WHERE 0")
        cur = CH.current(c)
        cur["deadline"] = y
        CH._save(c, cur)
        CH.season_end(c, get_state(c)[0])
        self.assertEqual(CH.current(c)["status"], "lost")

    def test_lost_job(self):
        c, me = _world(self)
        CH.start(c, "rebuild")
        c.execute("UPDATE manager SET team_id=NULL WHERE id=1")
        CH.season_end(c, get_state(c)[0])
        self.assertEqual(CH.current(c)["status"], "lost")

    def test_cap_hell(self):
        c, me = _world(self)
        CH.start(c, "cap_hell")
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('rules', json_set(COALESCE((SELECT value FROM pack_info WHERE "
                  "key='rules'), '{}'), '$.contracts.cap_ceiling', 1000000))")
        CH.opening_night(c, get_state(c)[0])
        self.assertEqual(CH.current(c)["status"], "lost")

    def test_expansion(self):
        c, me = _world(self)
        x = CH.start(c, "expansion")
        from hs.game import expansion as XP
        e = XP.pending(c)
        self.assertTrue(e and e["user_gm"])
        self.assertEqual(e["abbr"], x["expansion_abbr"])

    def test_view(self):
        c, me = _world(self)
        v = CH.view(c)
        self.assertTrue(v["can_start"])
        self.assertEqual(len(v["challenges"]), len(CH.CHALLENGES))


class CommissionerTests(unittest.TestCase):
    def setUp(self):
        self.c, self.me = _world(self)
        from hs.schema import top_league_sql
        self.teams = [r[0] for r in self.c.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")
                      if r[0] != self.me]

    def test_needs_mode(self):
        with self.assertRaises(ValueError):
            CM.set_rule(self.c, "cap", "95m")

    def test_tools(self):
        c = self.c
        ED.set_enabled(c, True)
        a, b = self.teams[:2]
        pa = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' LIMIT 1", (a,)).fetchone()[0]
        pb = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' LIMIT 1", (b,)).fetchone()[0]
        CM.trade(c, a, [pa], b, [pb], force=True)
        self.assertEqual(c.execute("SELECT team_id FROM players WHERE player_id=?", (pa,)).fetchone()[0], b)
        self.assertEqual(c.execute("SELECT team_id FROM players WHERE player_id=?", (pb,)).fetchone()[0], a)
        from hs.game.draft import draft_year
        dy = draft_year(c)
        CM.trade(c, a, [], b, [], picks_a=[(dy, 1, a)], force=True)
        from hs.game import trades as T
        self.assertEqual(T.pick_owner(c, dy, 1, a), b)
        with self.assertRaises(ValueError):
            CM.trade(c, a, [pa], b, [], force=True)             # pa is no longer with a
        self.assertIn("new GM", CM.fire(c, a, "gm"))
        old_hc = c.execute("SELECT name FROM staff WHERE team_id=? AND role='HC'", (a,)).fetchone()
        self.assertIn("head coach", CM.fire(c, a, "coach"))
        new_hc = c.execute("SELECT name FROM staff WHERE team_id=? AND role='HC'", (a,)).fetchone()
        self.assertNotEqual(old_hc, new_hc)
        self.assertIn("out until", CM.injure(c, pb, 10))
        self.assertTrue(c.execute("SELECT 1 FROM injuries WHERE player_id=?", (pb,)).fetchone())
        CM.heal(c, pb)
        self.assertEqual(c.execute("SELECT status FROM players WHERE player_id=?", (pb,)).fetchone()[0], "active")
        CM.set_rule(c, "cap", "95m")
        self.assertEqual(CM.rules(c)["cap"], 95_000_000)
        with self.assertRaises(ValueError):
            CM.set_rule(c, "floor", "99m")                      # above the cap
        CM.set_rule(c, "deadline", "02-27")
        self.assertTrue(CM.rules(c)["deadline"].endswith("02-27"))
        with self.assertRaises(ValueError):
            CM.set_rule(c, "deadline", "07-01")
        CM.set_rule(c, "roster_max", 24)
        self.assertEqual(CM.rules(c)["roster_max"], 24)
        CM.takeover(c, b)
        self.assertEqual(user_team(c), b)
        v = CM.view(c, a, b)
        self.assertTrue(v["sides"]["a"]["players"] and v["log"])


if __name__ == "__main__":
    unittest.main()
