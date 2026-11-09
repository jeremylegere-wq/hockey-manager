"""v44: the leagues around the NHL play real seasons (schedules, standings, playoffs, champions, the Memorial Cup),
import and over-age limits, champions for leagues simulated a season at a time, the database's extra leagues."""
import random
import tempfile
import unittest

from hs.game import leagues as L
from hs.game import world as Wd

from test_world import small_world


class RealLeagueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.conn, cls.me = small_world(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_full_year(self):
        c = self.conn
        real = L.leagues(c)
        self.assertEqual({a for a, _ in real.values()}, {"AHL", "OHL", "SHL", "NCAA"})
        self.assertGreater(L.ensure_season(c), 0)
        self.assertTrue(L.active(c))
        year = L._season_year(c)
        for lid, (abbr, rules) in real.items():
            clubs = [x["team_id"] for x in L._clubs(c, lid)]
            per = [c.execute("SELECT COUNT(*) FROM lg_games WHERE league_id=? AND (home=? OR away=?)", (lid, t, t)).fetchone()[0]
                   for t in clubs]
            target = min(rules["games"], 12 * (len(clubs) - 1))
            self.assertTrue(all(abs(p - rules["games"]) <= max(8, 0.2 * rules["games"]) or p >= target * 0.8 for p in per), (abbr, per))
            days = [r[0] for r in c.execute("SELECT day FROM lg_games WHERE league_id=? ORDER BY day", (lid,))]
            end = L._date(year, rules["end"]).isoformat()
            self.assertGreater(days[-1], L._date(year, rules["start"]).isoformat())
            import datetime
            self.assertLessEqual(days[-1], (datetime.date.fromisoformat(end) + datetime.timedelta(days=31)).isoformat())
        L.finish_year(c)
        done = c.execute("SELECT league_id, champion FROM lg_seasons WHERE season=? AND league_id>0", (year,)).fetchall()
        self.assertEqual(len(done), 4)
        self.assertTrue(all(r[1] for r in done))
        for lid in real:
            tbl = L.standings(c, lid, year)
            self.assertEqual(sum(r["w"] for r in tbl), sum(r["l"] + r["otl"] for r in tbl))   # a winner and a loser a game
            self.assertTrue(all(r["gp"] > 0 for r in tbl))
        lines = c.execute("SELECT COUNT(*), SUM(g), SUM(a) FROM skater_season_stats WHERE season_start_year=? AND source='league'",
                          (year,)).fetchone()
        self.assertGreater(lines[0], 100)
        self.assertGreater(lines[2], lines[1])                        # more assists than goals
        self.assertTrue(c.execute("SELECT 1 FROM league_events WHERE event_type='LEAGUE_CHAMPION'").fetchone())
        v = L.world_leagues_view(c, next(iter(real)))
        self.assertEqual(v["mode"], "games")
        self.assertTrue(v["standings"] and v["champions"] and v["rules"])
        # the season-at-a-time sim leaves leagues that played their games alone
        sid = c.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
        before = c.execute("SELECT COUNT(*) FROM skater_season_stats WHERE season_start_year=? AND source IS NULL", (year,)).fetchone()[0]
        c.execute("DELETE FROM pack_info WHERE key=?", (f"lower_stats_{year}",))
        Wd.lower_league_season(c, sid)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM skater_season_stats WHERE season_start_year=? AND source IS NULL",
                                   (year,)).fetchone()[0], before)
        c.rollback()


class UnitTests(unittest.TestCase):
    def test_pair_counts(self):
        rng = random.Random(1)
        clubs = [dict(team_id=i, division=("A" if i < 7 else "B"), conference="") for i in range(14)]
        cnt = L._pair_counts(clubs, 52, rng)
        per = [sum(v for (i, j), v in cnt.items() if k in (i, j)) for k in range(14)]
        self.assertTrue(all(48 <= p <= 56 for p in per), per)
        many = [dict(team_id=i, division=f"C{i % 6}", conference="") for i in range(60)]
        cnt = L._pair_counts(many, 36, rng)
        per = [sum(v for (i, j), v in cnt.items() if k in (i, j)) for k in range(60)]
        self.assertTrue(all(30 <= p <= 40 for p in per), (min(per), max(per)))

    def test_play_and_points(self):
        rng = random.Random(2)
        rows = lambda base: [dict(player_id=k, position="C" if k % 3 else "D", **{a: base for a in Wd.ALL_ATTRS}) for k in range(18)] + \
            [dict(player_id=100, position="G", **{a: base for a in Wd.ALL_ATTRS})]
        strong, weak = L.Club(1, rows(14), 10), L.Club(2, rows(8), 10)
        res = [L.play(rng, strong, weak, 3.0, 10) for _ in range(400)]
        wins = sum(1 for h, a, ot in res if h > a)
        self.assertGreater(wins, 240)
        ties = [L.play(rng, weak, weak, 3.0, 10, ties=True) for _ in range(400)]
        self.assertTrue(any(ot == 3 for _, _, ot in ties))
        self.assertTrue(all(h != a for h, a, ot in res))

    def test_rules_text(self):
        from hs.leaguedata.league_rules import RULES
        t = L.rules_text("NL", RULES["NL"], {})
        self.assertTrue(any("play-in" in x for x in t))
        self.assertTrue(any("imports" in x for x in t))
        t = L.rules_text(None, None, dict(games=52, kind="europe", age_max=40))
        self.assertTrue(any("season at a time" in x for x in t))

    def test_class_leagues(self):
        from hs.worldgen import class_leagues
        rng = random.Random(3)
        firsts = [class_leagues("SWE", 17, rng)[0] for _ in range(200)]
        self.assertGreater(firsts.count("J20"), 100)
        self.assertIn("SHL", firsts)

    def test_database_leagues_listed(self):
        from hs.adapters.db_export import DB_LEAGUES
        self.assertEqual(len(DB_LEAGUES), 23)
        self.assertEqual(len({a for a, _ in DB_LEAGUES.values()}), 23)


class LimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.conn, cls.me = small_world(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_imports_and_overage(self):
        import datetime
        c = self.conn
        lim = L.Limits(c, datetime.date(2026, 9, 15))
        ohl = next(lid for lid, (a, _) in L.leagues(c).items() if a == "OHL")
        club = c.execute("SELECT team_id FROM teams WHERE league_id=? LIMIT 1", (ohl,)).fetchone()[0]
        lim.imports[club] = 2
        self.assertFalse(lim.ok(club, "SWE", 18, "C"))
        self.assertTrue(lim.ok(club, "CAN", 18, "C"))
        lim.imports[club] = 0
        self.assertFalse(lim.ok(club, "SWE", 18, "G"))                # no import goalies in the CHL
        lim.over[club] = 3
        self.assertFalse(lim.ok(club, "CAN", 20, "D"))
        self.assertTrue(lim.ok(club, "CAN", 19, "D"))

    def test_season_sim_champions(self):
        c = self.conn
        sid = c.execute("SELECT season_id, start_year FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
        L.ensure_tables(c)
        c.execute("DELETE FROM lg_games")
        c.execute("DELETE FROM pack_info WHERE key=?", (f"lower_stats_{sid[1]}",))
        Wd.lower_league_season(c, sid[0])
        n = c.execute("SELECT COUNT(*) FROM lg_seasons WHERE season=? AND phase='done' AND champion IS NOT NULL", (sid[1],)).fetchone()[0]
        self.assertGreaterEqual(n, 3)
        c.rollback()


if __name__ == "__main__":
    unittest.main()
