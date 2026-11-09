"""v52: lineups (priority lists) and the goalie rule."""
import datetime
import json
import tempfile
import unittest

from hs.game import lineups as LUP
from hs.game import roster as R
from hs.game.state import get_state

from test_world import small_world


class LineupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = small_world(tmp.name)
        self.addCleanup(self.c.close)

    def test_lists_build_lines(self):
        c, me = self.c, self.me
        LUP.set_enabled(c, me, True)
        v = LUP.get(c, me)
        self.assertTrue(v["enabled"] and v["lists"]["C"] and v["lists"]["G"])
        lu = LUP.build(c, me)
        f = [p for ln in lu["F"] for p in ln if p]
        d = [p for pr in lu["D"] for p in pr if p]
        self.assertEqual(len(f), len(set(f)))
        self.assertEqual(len(f + d), len(set(f + d)))
        self.assertEqual(len(lu["F"]), 4)
        # the top centre on the list centres line one; injure him and the next one does
        top = v["lists"]["C"][0]
        self.assertEqual(lu["F"][0][0], top)
        c.execute("UPDATE players SET status='injured' WHERE player_id=?", (top,))
        lu2 = LUP.build(c, me)
        self.assertNotIn(top, [p for ln in lu2["F"] for p in ln])
        self.assertEqual(lu2["F"][0][0], v["lists"]["C"][1])

    def test_reorder_and_validation(self):
        c, me = self.c, self.me
        LUP.set_enabled(c, me, True)
        cs = LUP.get(c, me)["lists"]["C"]
        LUP.set_list(c, me, "C", list(reversed(cs)))
        self.assertEqual(LUP.build(c, me)["F"][0][0], cs[-1])
        g = LUP.get(c, me)["lists"]["G"][0]
        with self.assertRaises(ValueError):
            LUP.set_list(c, me, "C", [g])
        with self.assertRaises(ValueError):
            LUP.set_list(c, me, "XX", [])
        with self.assertRaises(ValueError):
            LUP.set_goalie_rule(c, me, "sometimes")

    def test_goalie_rules(self):
        c, me = self.c, self.me
        LUP.set_enabled(c, me, True)
        gl = LUP.get(c, me)["lists"]["G"]
        if len(gl) < 2:
            self.skipTest("one goalie")
        LUP.set_goalie_rule(c, me, "every_game")
        lu = LUP.build(c, me, "2026-11-02")
        self.assertTrue(lu["G_force"])
        self.assertEqual(lu["G"][0], gl[0])
        LUP.set_goalie_rule(c, me, "back_to_back")
        gid = c.execute("SELECT game_id FROM games WHERE home_team_id=? OR away_team_id=? ORDER BY game_date LIMIT 1", (me, me)).fetchone()[0]
        c.execute("UPDATE games SET game_date='2026-11-01', played=1 WHERE game_id=?", (gid,))
        self.assertEqual(LUP.build(c, me, "2026-11-02")["G"][0], gl[1])
        self.assertEqual(LUP.build(c, me, "2026-11-05")["G"][0], gl[0])

    def test_before_games_saves_lines(self):
        c, me = self.c, self.me
        day = c.execute("SELECT MIN(game_date) FROM games WHERE played=0 AND (home_team_id=? OR away_team_id=?)", (me, me)).fetchone()[0]
        self.assertIsNone(LUP.before_games(c, day))           # off
        LUP.set_enabled(c, me, True)
        lu = LUP.before_games(c, day)
        self.assertTrue(lu)
        saved = json.loads(c.execute("SELECT data FROM lineups WHERE team_id=?", (me,)).fetchone()[0])
        self.assertEqual(saved["F"], lu["F"])
        from hs.sim.loader import load_teams
        t = load_teams(c)[me]
        self.assertEqual([p.pid for p in t.lines[0]], [p for p in lu["F"][0] if p])


if __name__ == "__main__":
    unittest.main()
