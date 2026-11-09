"""v53: supplementary discipline (suspensions) and preset injuries and suspensions from a pack."""
import tempfile
import unittest

from hs.game import discipline as D
from hs.game import roster as R
from hs.game.state import get_state

from test_world import small_world


class DisciplineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = small_world(tmp.name)
        self.addCleanup(self.c.close)
        D.ensure_tables(self.c)

    def test_suspend_serve_and_lineups(self):
        c, me = self.c, self.me
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position<>'G' LIMIT 1", (me,)).fetchone()[0]
        D.suspend(c, pid, 2, "boarding", "2026-10-10", me)
        self.assertIn(pid, D.suspended(c))
        self.assertEqual(D.games_left(c, pid), 2)
        from hs.sim.loader import load_teams
        t = load_teams(c)[me]
        self.assertNotIn(pid, [p.pid for ln in t.lines for p in ln] + [p.pid for pr in t.pairs for p in pr])
        before = R.counts(c, me)
        # a game the same day does not count; the next two do
        D.after_games(c, "2026-10-10", [(999001, me, 1)])
        self.assertEqual(D.games_left(c, pid), 2)
        D.after_games(c, "2026-10-12", [(999002, me, 1)])
        D.after_games(c, "2026-10-14", [(999003, 1, me)])
        self.assertEqual(D.games_left(c, pid), 0)
        self.assertNotIn(pid, D.suspended(c))
        self.assertGreaterEqual(R.counts(c, me)["F"] + R.counts(c, me)["D"], before["F"] + before["D"])

    def test_appeal(self):
        c, me = self.c, self.me
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position<>'G' LIMIT 1", (me,)).fetchone()[0]
        D.suspend(c, pid, 3, "slashing", "2026-10-10", me)
        with self.assertRaises(ValueError):
            D.appeal(c, pid)                                   # under six games
        c.execute("UPDATE suspensions SET games=8, games_left=8 WHERE player_id=?", (pid,))
        msg = D.appeal(c, pid)
        self.assertTrue("upholds" in msg or "succeeds" in msg)
        with self.assertRaises(ValueError):
            D.appeal(c, pid)                                   # once

    def test_incidents_rate(self):
        c = self.c
        n = sum(1 for g in range(4000) if __import__("random").Random(f"7-incident-{g}").random() < D.P_INCIDENT)
        self.assertTrue(100 < n < 180)
        self.assertEqual(sum(p for _, p in D.LENGTHS).__round__(2), 1.0)

    def test_pack_presets(self):
        c = self.c
        a, b = [r[0] for r in c.execute("SELECT player_id FROM players WHERE status='active' AND team_id IS NOT NULL LIMIT 2")]
        n = D.load_pack(c, {"suspensions.csv": [dict(player_id=str(a), games="4", reason="carried over")],
                            "injuries.csv": [dict(player_id=str(b), days="20", description="knee")]}, 2026)
        self.assertEqual(n, 2)
        self.assertEqual(D.games_left(c, a), 4)
        self.assertEqual(c.execute("SELECT status FROM players WHERE player_id=?", (b,)).fetchone()[0], "injured")
        self.assertTrue(D.view(c)["active"])


if __name__ == "__main__":
    unittest.main()
