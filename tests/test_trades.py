"""AI-to-AI trades on the fictional example pack."""
import datetime
import json
import random
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import roster as R
from hs.game import trades as T
from hs.game.state import connect

from test_game import make_db

DAY = "2026-10-15"


class TradesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.conn, self.me = make_db(self.tmp.name)
        self.addCleanup(self.conn.close)

    def market(self):
        m = T.Market(self.conn, DAY)
        m.posture = {t: ("seller" if i % 2 else "contender") for i, t in enumerate(m.all_teams)}
        return m

    def run_until_trade(self, tries=200, m=None):
        rng = random.Random(3)
        for _ in range(tries):
            m = m or self.market()
            t = T.attempt(self.conn, DAY, rng, m, deadline_rush=True)
            if t:
                return t
        return None

    def test_deadline_is_first_friday_of_march(self):
        d = T.deadline(self.conn)
        self.assertEqual((d.month, d.weekday()), (3, 4))
        self.assertLessEqual(d.day, 7)
        self.assertEqual(d.year, K.season_year(self.conn) + 1)

    def test_trade_is_legal_and_recorded(self):
        before = {r[0]: r[1] for r in self.conn.execute("SELECT player_id, team_id FROM players")}
        text = self.run_until_trade()
        self.assertIsNotNone(text, "no AI trade happened")
        e = self.conn.execute("SELECT * FROM league_events WHERE event_type='TRADE_COMPLETED'").fetchone()
        buyer, seller, target = e["team_id"], e["other_team_id"], e["player_id"]
        self.assertNotIn(self.me, (buyer, seller))
        self.assertEqual(self.conn.execute("SELECT team_id FROM players WHERE player_id=?", (target,)).fetchone()[0],
                         buyer)
        self.assertEqual(before[target], seller)
        payload = json.loads(e["payload"])
        for pid in payload["players_out"]:
            self.assertEqual(self.conn.execute("SELECT team_id FROM players WHERE player_id=?",
                                               (pid,)).fetchone()[0], seller)
        for y, rnd, orig in payload["picks"]:
            self.assertEqual(T.pick_owner(self.conn, y, rnd, orig), seller)
        mn, mx = R.limits(self.conn)
        for t in (buyer, seller):
            self.assertTrue(mn <= len(R.roster(self.conn, t)) <= mx)
            room = K.cap_room(self.conn, t, K.season_year(self.conn))
            self.assertTrue(room is None or room >= 0)
        # the user's roster is untouched
        mine = {r[0] for r in self.conn.execute("SELECT player_id FROM players WHERE team_id=?", (self.me,))}
        self.assertEqual(mine, {p for p, t in before.items() if t == self.me})

    def test_contenders_do_not_sell_and_no_one_is_flipped(self):
        m = self.market()
        for _ in range(5):
            self.run_until_trade(60, m)
        rows = self.conn.execute("SELECT other_team_id, player_id FROM league_events WHERE "
                                 "event_type='TRADE_COMPLETED'").fetchall()
        self.assertTrue(rows)
        for seller, pid in rows:
            self.assertNotEqual(m.posture[seller], "contender")
        moved = [r[0] for r in self.conn.execute("SELECT player_id FROM league_events WHERE "
                                                  "event_type='PLAYER_TRADED'")]
        self.assertEqual(len(moved), len(set(moved)), "a player was traded twice in one season")

    def test_no_trades_after_the_deadline(self):
        after = (T.deadline(self.conn) + datetime.timedelta(days=1)).isoformat()
        self.assertEqual(T.ai_day(self.conn, after, random.Random(1)), [])

    def test_trade_request_gets_shopped_and_cleared(self):
        c = self.conn
        m = self.market()
        contender = next(t for t in m.teams if m.posture[t] == "contender")
        pid = sorted(((m.values[r["player_id"]], r["player_id"]) for r in R.roster(c, contender)
                      if r["position"] != "G"), reverse=True)[2][1]          # a core player (third-best skater)
        c.execute("UPDATE morale SET trade_request=1 WHERE player_id=?", (pid,))
        text = T.shop_request(self.market(), pid, random.Random(5), DAY)
        self.assertIsNotNone(text)
        self.assertNotEqual(c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                            contender, "the player who asked out was never moved")
        self.assertEqual(c.execute("SELECT trade_request FROM morale WHERE player_id=?", (pid,)).fetchone()[0], 0)
        e = c.execute("SELECT payload FROM league_events WHERE event_type='TRADE_COMPLETED' AND player_id=?",
                      (pid,)).fetchone()
        self.assertTrue(json.loads(e[0])["requested"])

    def test_deterministic(self):
        a = self.run_until_trade()
        tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp2.cleanup)
        db2, c2, _ = make_db(tmp2.name)
        self.addCleanup(c2.close)
        self.conn, saved = c2, self.conn
        try:
            b = self.run_until_trade()
        finally:
            self.conn = saved
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
