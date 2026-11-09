"""v37, phase F: the calendar. Rivalries, exhibitions (pre-season, prospects tournaments, all-star weekend), the Hall
of Fame, GM scores and achievements."""
import json
import tempfile
import unittest

from hs.game import exhibitions as EX
from hs.game import legacy as LG
from hs.game import rivalry as RV
from hs.game.state import get_state
from hs.league.season import db_rules
from hs.sim.engine import skill_for

from test_world import small_world
from test_game import ENV


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = small_world(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]
        self.skill = skill_for(db_rules(self.c))


class RivalryTests(Base):
    def test_bases_and_levels(self):
        RV.ensure(self.c)
        t = self.c.execute("SELECT team_id, division FROM teams WHERE league_id=1 ORDER BY team_id").fetchall()
        same = next(b for b in t[1:] if b[1] == t[0][1])
        self.assertEqual(RV.points(self.c, t[0][0], same[0]), 22.0)
        self.assertEqual(RV.level_name(55), "rivalry")
        self.assertEqual(RV.level_name(90), "bitter")
        self.assertEqual(RV.level_name(10), "none")

    def test_meetings_heat_and_summer_cools(self):
        RV.ensure(self.c)
        a, b = [r[0] for r in self.c.execute("SELECT team_id FROM teams WHERE league_id=1 ORDER BY team_id LIMIT 2")]
        p0 = RV.points(self.c, a, b)
        RV._add(self.c, a, b, 40)
        self.assertAlmostEqual(RV.points(self.c, a, b), p0 + 40)
        sid = self.c.execute("SELECT MAX(season_id) FROM seasons").fetchone()[0]
        RV.season_end(self.c, sid)
        self.assertAlmostEqual(RV.points(self.c, a, b), p0 + 30, places=3)       # a quarter of the way back
        self.assertTrue(RV.is_big(RV.all_points(self.c), a, b) == (p0 + 30 >= RV.BIG))

    def test_pack_rivalries_seed(self):
        ab = [r[0] for r in self.c.execute("SELECT abbr FROM teams WHERE league_id=1 ORDER BY team_id LIMIT 2")]
        self.c.execute("INSERT OR REPLACE INTO pack_info VALUES ('rivalries', ?)", (json.dumps([[ab[0], ab[1], 40]]),))
        RV.ensure(self.c)
        ids = [r[0] for r in self.c.execute("SELECT team_id FROM teams WHERE abbr IN (?,?)", ab)]
        self.assertGreaterEqual(RV.points(self.c, *ids), 40)


class ExhibitionTests(Base):
    def test_options(self):
        self.assertEqual(EX.options(self.c)["allstar"], "conference")
        EX.set_option(self.c, "allstar", "world")
        self.assertEqual(EX.options(self.c)["allstar"], "world")
        with self.assertRaises(ValueError):
            EX.set_option(self.c, "allstar", "nonsense")
        with self.assertRaises(ValueError):
            EX.set_option(self.c, "preseason_games", 99)

    def test_preseason_does_not_touch_the_season(self):
        before = (self.c.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0],
                  self.c.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0])
        EX.play_preseason(self.c, ENV, self.skill)
        n = self.c.execute("SELECT COUNT(*) FROM exhibitions WHERE kind='PS'").fetchone()[0]
        clubs = self.c.execute("SELECT COUNT(*) FROM teams WHERE league_id=1").fetchone()[0]
        self.assertEqual(n, clubs // 2 * 6)
        after = (self.c.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0],
                 self.c.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0])
        self.assertEqual(before, after)
        first = self.c.execute("SELECT MIN(game_date) FROM games WHERE game_type='RS'").fetchone()[0]
        self.assertLess(self.c.execute("SELECT MAX(day) FROM exhibitions WHERE kind='PS'").fetchone()[0], first)
        self.assertEqual(EX.play_preseason(self.c, ENV, self.skill), [])                # once a season
        self.assertTrue(self.c.execute("SELECT 1 FROM inbox WHERE subject='Camp report'").fetchone())

    def test_prospects_tournaments(self):
        out = EX.prospects_tournaments(self.c, ENV, self.skill, self.day[:4] + "-09-15")
        self.assertTrue(out)
        finals = self.c.execute("SELECT notes FROM exhibitions WHERE kind='PROSPECTS' AND round='Final'").fetchall()
        self.assertEqual(len(finals), len(out))
        ages = self.c.execute("SELECT p.birth_date FROM exhibition_stats s JOIN exhibitions e USING (ex_id) JOIN players p USING (player_id) "
                              "WHERE e.kind='PROSPECTS'").fetchall()
        self.assertTrue(all(int(self.day[:4]) - int(b[0][:4]) <= 23 for b in ages))

    def test_allstar_weekend(self):
        sel = EX.select_allstars(self.c)
        self.assertEqual([len(s) for s in sel["players"]], [20, 20])
        clubs = {sel["info"][p]["team"] for s in sel["players"] for p in s}
        self.assertEqual(clubs, {r[0] for r in self.c.execute("SELECT team_id FROM teams WHERE league_id=1")})
        txt = EX.run_allstar(self.c, ENV, self.skill, self.day)
        self.assertTrue(txt)
        v = EX.allstar_view(self.c)
        self.assertIsNotNone(v["mvp"])
        self.assertEqual(set(v["skills"]), set(EX.SKILLS))
        for fmt in ("draft", "world"):
            s = EX.select_allstars(self.c, fmt)
            self.assertEqual(len(set(s["players"][0]) & set(s["players"][1])), 0)

    def test_no_allstar_in_an_olympic_year(self):
        r = json.loads(self.c.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()[0])
        year = EX._season(self.c)
        r.setdefault("season", {})["breaks"] = [{"name": "Olympic break", "start": f"{year + 1}-02-06", "end": f"{year + 1}-02-22"}]
        self.c.execute("UPDATE pack_info SET value=? WHERE key='rules'", (json.dumps(r),))
        self.assertIsNone(EX.allstar_date(self.c))


class LegacyTests(Base):
    def test_hof_score_and_vote(self):
        self.assertGreater(LG._support(95), 0.8)
        self.assertLess(LG._support(65), 0.15)
        LG.ensure_tables(self.c)
        year = LG._year(self.c) + 1
        pids = [r[0] for r in self.c.execute("SELECT player_id FROM players LIMIT 3")]
        self.c.executemany("INSERT INTO hof_ballot (year, player_id, score) VALUES (?,?,?)", [(year, p, 120.0) for p in pids])
        LG.vote(self.c, pids[:2])
        with self.assertRaises(ValueError):
            LG.vote(self.c, pids * 2 + [99999999])
        lines = LG.election(self.c, self.day)
        self.assertEqual(len(lines), 3)                          # overwhelming cases go in
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM hall_of_fame").fetchone()[0], 3)

    def test_gm_score(self):
        self.assertEqual(LG.gm_season_score(0.6, 5, True), 10 + 20 + 10 + 8)
        self.assertEqual(LG.gm_season_score(0.45, 0), -5)

    def test_achievements_view(self):
        v = LG.achievements_view(self.c)
        self.assertEqual(v["total"], len(LG.ACHIEVEMENTS))
        self.assertEqual(v["earned"], 0)


if __name__ == "__main__":
    unittest.main()
