"""v51: international hockey - the calendar, selection rules, tournaments, the ranking, medals, the Triple Gold Club."""
import json
import tempfile
import unittest

from hs.game import international as I
from hs.game.state import get_state, user_team

from test_world import small_world


class CalendarTests(unittest.TestCase):
    def test_calendar(self):
        self.assertEqual([k for k, _, _ in I.calendar(2026)], ["wjc", "worlds"])
        self.assertEqual([k for k, _, _ in I.calendar(2027)], ["wjc", "worldcup", "worlds"])
        self.assertEqual([k for k, _, _ in I.calendar(2029)], ["wjc", "olympics", "worlds"])
        self.assertIsNone(I.schedule_break(2026))
        self.assertEqual(I.schedule_break(2029)["start"], "2030-02-06")

    def test_place_points(self):
        self.assertEqual(I.PLACE_POINTS[1], 1200)
        self.assertEqual(I.PLACE_POINTS[4], 1140)
        self.assertEqual(I.PLACE_POINTS[5], 1100)


class TournamentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = small_world(tmp.name)
        self.addCleanup(self.c.close)
        I.ensure_tables(self.c)
        # give the world a few more nations
        rows = self.c.execute("SELECT player_id FROM players WHERE status IN ('active','prospect') ORDER BY player_id").fetchall()
        nats = ["CAN", "USA", "SWE", "FIN", "CZE", "SUI", "GER", "SVK", "LAT", "DEN", "RUS"]
        for k, (pid,) in enumerate(rows):
            self.c.execute("UPDATE players SET nationality=? WHERE player_id=?", (nats[k % len(nats)], pid))

    def test_worlds_and_bans(self):
        c = self.c
        tid = I.select(c, "worlds", 2026, "2027-05-08")
        nations = {r[0] for r in c.execute("SELECT DISTINCT nation FROM intl_rosters WHERE tid=?", (tid,))}
        self.assertNotIn("RUS", nations)
        self.assertGreaterEqual(len(nations), 8)
        per = [r[0] for r in c.execute("SELECT COUNT(*) FROM intl_rosters WHERE tid=? GROUP BY nation", (tid,))]
        self.assertTrue(all(n <= 25 for n in per))
        lines = I.play(c, tid, "2027-05-24")
        self.assertTrue(lines and "win the" in lines[0])
        t = c.execute("SELECT places, status FROM intl_tournaments WHERE tid=?", (tid,)).fetchone()
        places = json.loads(t[0])
        self.assertEqual(t[1], "done")
        self.assertEqual(len(places), len(nations))
        self.assertEqual(I.play(c, tid, "2027-05-24"), [])       # once
        self.assertTrue(c.execute("SELECT COUNT(*) FROM intl_stats WHERE tid=?", (tid,)).fetchone()[0] > 50)
        # the ranking now counts it
        rk = dict(I.ranking(c, 2027))
        self.assertGreater(rk[places[0]], 0)
        # readmitted
        I.set_banned(c, True)
        self.assertEqual(I.banned(c), ())

    def test_wjc_ages(self):
        c = self.c
        tid = I.select(c, "wjc", 2026, "2026-12-26")
        old = c.execute("SELECT COUNT(*) FROM intl_rosters r JOIN players p USING (player_id) WHERE r.tid=? AND "
                        "CAST(substr(p.birth_date, 1, 4) AS INTEGER) < 2007", (tid,)).fetchone()[0]
        self.assertEqual(old, 0)
        nhl = c.execute("SELECT COUNT(*) FROM intl_rosters r JOIN players p USING (player_id) WHERE r.tid=? AND p.status='active' AND "
                        "p.club_id IN (SELECT team_id FROM teams WHERE league_id=1)", (tid,)).fetchone()[0]
        self.assertEqual(nhl, 0)
        I.play(c, tid, "2027-01-05")

    def test_daily_and_view(self):
        c = self.c
        self.assertEqual(I.daily(c, "2026-12-20"), [])
        I.daily(c, "2026-12-26")
        self.assertTrue(c.execute("SELECT 1 FROM intl_tournaments WHERE kind='wjc' AND status='selected'").fetchone())
        lines = I.daily(c, "2027-01-05")
        self.assertTrue(lines)
        v = I.view(c)
        self.assertTrue(v["tournaments"] and v["ranking"])
        d = I.view(c, v["tournaments"][0]["tid"])["detail"]
        self.assertEqual(len(d["places"]), len(d["rosters"]))

    def test_triple_gold(self):
        c = self.c
        from hs.game.history import ensure_tables
        ensure_tables(c)
        pid, team = c.execute("SELECT player_id, team_id FROM players WHERE team_id IS NOT NULL AND status='active' AND nationality='CAN' LIMIT 1").fetchone()
        for kind, season in (("olympics", 2029), ("worlds", 2029)):
            c.execute("INSERT INTO intl_tournaments (kind, season, name, status, places) VALUES (?,?,?,'done',?)", (kind, season, kind, json.dumps(["CAN", "USA"])))
            tid = c.execute("SELECT MAX(tid) FROM intl_tournaments").fetchone()[0]
            c.execute("INSERT INTO intl_rosters VALUES (?,?,?,?)", (tid, "CAN", pid, team))
        c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp) VALUES (?,2028,?,1,'RS',80)", (pid, team))
        c.execute("INSERT OR REPLACE INTO team_seasons (season_start_year, team_id, league_id, playoff_round) VALUES (2028,?,1,5)", (team,))
        I._triple_gold(c, "2030-05-30")
        self.assertTrue(c.execute("SELECT 1 FROM intl_tgc WHERE player_id=?", (pid,)).fetchone())


if __name__ == "__main__":
    unittest.main()
