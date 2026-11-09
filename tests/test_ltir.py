"""Long-term injured reserve."""
import datetime
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import ltir as LT
from hs.game import roster as R
from hs.game.state import get_state

from test_game import make_db


class LtirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]
        self.cap = K.crules(self.c)["cap_ceiling"]

    def injure(self, days):
        row = self.c.execute("SELECT p.player_id, c.cap_hit FROM players p JOIN contracts c USING (player_id) WHERE "
                             "p.team_id=? AND p.status='active' AND p.position<>'G' ORDER BY c.cap_hit DESC LIMIT 1",
                             (self.me,)).fetchone()
        back = (datetime.date.fromisoformat(self.day) + datetime.timedelta(days=days)).isoformat()
        self.c.execute("UPDATE players SET status='injured' WHERE player_id=?", (row[0],))
        self.c.execute("INSERT INTO injuries (player_id, start_date, expected_return) VALUES (?,?,?)",
                       (row[0], self.day, back))
        return row[0], row[1]

    def test_eligibility(self):
        pid, _ = self.injure(10)
        self.assertFalse(LT.eligible(self.c, pid, self.day)[0])
        pid2, _ = self.injure(60)
        self.assertTrue(LT.eligible(self.c, pid2, self.day)[0], LT.eligible(self.c, pid2, self.day)[1])

    def test_ceiling_is_limit_plus_pool(self):
        pid, hit = self.injure(60)
        before = K.payroll(self.c, self.me)
        LT.place(self.c, pid, self.day)
        self.assertEqual(LT.ceiling(self.c, self.me), max(self.cap, min(self.cap, before) + hit))
        self.assertEqual(K.payroll(self.c, self.me), before)              # his cap hit still counts
        self.assertGreaterEqual(K.cap_room(self.c, self.me), hit - 1)     # room to replace him
        mn, mx = R.limits(self.c)
        self.assertNotIn(pid, [r["player_id"] for r in R.roster(self.c, self.me)])   # off the roster count

    def test_activation_needs_compliance_and_time(self):
        pid, hit = self.injure(40)
        LT.place(self.c, pid, self.day)
        with self.assertRaises(R.RosterError):
            LT.activate(self.c, pid, self.day)                             # not fit, too soon
        later = (datetime.date.fromisoformat(self.day) + datetime.timedelta(days=41)).isoformat()
        # spend the relief: add a cap charge that leaves the club over the cap once he returns
        self.c.execute("INSERT INTO cap_charges (team_id, season_start_year, amount, reason) VALUES (?,?,?,?)",
                       (self.me, K.season_year(self.c), self.cap - K.payroll(self.c, self.me) + 1, "test"))
        with self.assertRaises(R.RosterError):
            LT.activate(self.c, pid, later)
        self.c.execute("DELETE FROM cap_charges WHERE reason='test'")
        mn, mx = R.limits(self.c)
        while len(R.roster(self.c, self.me)) >= mx:
            R.send_down(self.c, self.me, R._lowest_healthy(self.c, self.me)[1], later, waive=False)
        LT.activate(self.c, pid, later)
        self.assertEqual(self.c.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()[0], "active")
        self.assertEqual(LT.ceiling(self.c, self.me), self.cap)            # limit resets
        self.assertEqual(LT.active(self.c, self.me), [])

    def test_season_end_clears(self):
        pid, _ = self.injure(200)
        LT.place(self.c, pid, self.day)
        LT.end_of_season(self.c, self.day)
        self.assertEqual(self.c.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()[0], "injured")
        self.assertEqual(LT.ceiling(self.c, self.me), self.cap)


if __name__ == "__main__":
    unittest.main()
