"""Media layer and 2D replay: read-only, deterministic, consistent with the box score."""
import json
import tempfile
import unittest

from hs.game import media as M
from hs.game import replay as RP
from hs.game.dayloop import sim_until
from hs.game.events import emit
from hs.sim.engine import Skill
from hs.ui import api

from test_game import make_db
from test_sim import ENV


def _snapshot(c):
    return [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("games", "game_events", "league_events", "inbox", "contracts", "player_game_stats")]


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        _, cls.c, cls.me = make_db(cls.tmp.name)
        sim_until(cls.c, ENV, Skill(), days=20)
        cls.gid = cls.c.execute("SELECT game_id FROM games WHERE played=1 AND (home_team_id=? OR away_team_id=?) "
                                "ORDER BY game_date DESC LIMIT 1", (cls.me, cls.me)).fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_recap_matches_the_box_score(self):
        r = M.recap(self.c, self.gid)
        g = self.c.execute("SELECT * FROM games WHERE game_id=?", (self.gid,)).fetchone()
        reg_goals = len([x for x in r["goals"]])
        self.assertEqual(reg_goals + (1 if g["went_to_ot"] == 2 else 0), g["home_goals"] + g["away_goals"])
        self.assertTrue(r["headline"])
        self.assertLessEqual(len(r["stars"]), 3)
        winner = r["home"] if g["home_goals"] > g["away_goals"] else r["away"]
        win_club = M._club(self.c, g["home_team_id"] if winner == r["home"] else g["away_team_id"])
        self.assertIn(win_club, r["headline"] + r["lede"])
        self.assertEqual(M.recap(self.c, self.gid), r)                      # deterministic

    def test_everything_is_read_only(self):
        before = _snapshot(self.c)
        M.recap(self.c, self.gid)
        M.recent_recaps(self.c)
        M.headlines(self.c, None, 20)
        M.social(self.c, 20)
        M.power_rankings(self.c)
        RP.build(self.c, self.gid)
        api.news_view(self.c, "league")
        api.game_view(self.c, self.gid)
        self.assertEqual(_snapshot(self.c), before)

    def test_power_rankings_cover_every_club_once(self):
        pr = M.power_rankings(self.c)
        self.assertEqual(len({r["team"] for r in pr}), len(pr))
        self.assertEqual([r["rank"] for r in pr], list(range(1, len(pr) + 1)))
        self.assertEqual(sum(r["mine"] for r in pr), 1)

    def test_headlines_and_posts_from_events(self):
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? LIMIT 1", (self.me,)).fetchone()[0]
        day = self.c.execute("SELECT current_date FROM game_state").fetchone()[0]
        emit(self.c, "TRADE_REQUEST", day, "X asks for a trade", team_id=self.me, player_id=pid, importance=3)
        emit(self.c, "PLAYER_INJURED", day, "X injured, out about 40 day(s)", team_id=self.me, player_id=pid,
             importance=2, days=40)
        heads = M.headlines(self.c, self.me, 10)
        tags = {h["tag"] for h in heads}
        self.assertIn("trade", tags)
        self.assertIn("injury", tags)
        accounts = {p["account"] for p in M.social(self.c, 40)}
        self.assertIn(M.INSIDER, accounts)
        self.assertTrue(any(a.endswith("Faithful") for a in accounts))

    def test_replay_places_events_on_the_rink(self):
        rp = RP.build(self.c, self.gid)
        self.assertEqual(rp["final"], list(self.c.execute("SELECT home_goals, away_goals FROM games WHERE game_id=?",
                                                          (self.gid,)).fetchone()))
        shots = [e for e in rp["events"] if e["type"] in ("goal", "shot", "miss", "block")]
        self.assertTrue(shots)
        for e in shots:
            self.assertLessEqual(abs(e["x"]), 100)
            self.assertLessEqual(abs(e["y"]), 42.5)
            self.assertEqual((e["x"] > 0), (e["net"] > 0), "shots come from the attacking half")
        # home attacks +x in the 1st and the other way in the 2nd
        for e in shots:
            if e["period"] in (1, 2):
                sign = 1 if (e["team"] == "home") == (e["period"] == 1) else -1
                self.assertEqual(e["net"], sign * RP.NET_X)
        good = [e for e in shots if e.get("xg") and e["xg"] > 0.15]
        poor = [e for e in shots if e.get("xg") and e["xg"] < 0.05]
        if good and poor:                                                      # better chances come from closer in
            d = lambda e: ((e["net"] - e["x"]) ** 2 + e["y"] ** 2) ** 0.5
            self.assertLess(sum(map(d, good)) / len(good), sum(map(d, poor)) / len(poor))
        self.assertEqual(RP.build(self.c, self.gid), rp)                      # same game, same replay


if __name__ == "__main__":
    unittest.main()
