"""Draft classes and the scouting engine: calibration, biases and the human element."""
import datetime
import random
import statistics
import tempfile
import unittest

from hs.game import draft as D
from hs.game import scouting as S
from hs.game import world as Wd
from hs.leaguedata.world_2025_26 import NAMES
from hs.tools import draft_lab as L
from hs.worldgen import CLASS_GOALIES, CLASS_SKATERS, gen_prospect, make_draft_class

from test_world import small_world


class ScoutingMathTests(unittest.TestCase):
    def test_traditional_scouts_mark_down_small_players_and_russians_more(self):
        small = S.bias("traditional", 172, "chl", 0, False) - S.bias("analytics", 172, "chl", 0, False)
        self.assertLess(small, -0.4)
        big = S.bias("traditional", 194, "chl", 0, False)
        self.assertGreater(big, 0.3)
        russia = S.bias("traditional", 183, "russia", 2, False) - S.bias("analytics", 183, "russia", 2, False)
        self.assertLess(russia, -0.4)
        self.assertEqual(S.bias("traditional", 183, "russia", 0, False), 0.0)   # no KHL contract, no discount

    def test_better_scouts_have_less_own_error(self):
        args = (10.0, 18, False, "chl", 0.0, 1.0)
        good = S.project(*args, 0.25, "balanced", 183, 0) - S.project(*args, 0.0, "balanced", 183, 0)
        poor = S.project(*args, 1.0, "balanced", 183, 0) - S.project(*args, 0.0, "balanced", 183, 0)
        self.assertGreater(poor, 3 * good)

    def test_europeans_and_goalies_are_harder_to_read(self):
        z = (1.0, 1.0, 0.75, "balanced", 183, 0)
        err = lambda exp, g: S.project(10, 18, g, exp, *z) - S.project(10, 18, g, exp, 0, 0, 0.75, "balanced", 183, 0)
        self.assertGreater(err("russia", False), err("chl", False))
        self.assertGreater(err("chl", True), err("chl", False))

    def test_round_logic(self):
        # need matters more in rounds 2-4 than in round 1
        self.assertGreater(S.pick_score(10, 9, 2, 1.0, "balanced", False) - S.pick_score(10, 9, 2, 0, "balanced", False),
                           S.pick_score(10, 9, 1, 1.0, "balanced", False) - S.pick_score(10, 9, 1, 0, "balanced", False))
        # goalies wait unless truly elite
        self.assertLess(S.pick_score(11.5, 9, 1, 0, "balanced", True), S.pick_score(11.5, 9, 1, 0, "balanced", False))
        self.assertEqual(S.pick_score(13.2, 9, 1, 0, "balanced", True), S.pick_score(13.2, 9, 1, 0, "balanced", False))
        # late rounds chase upside: a raw player beats a finished one with the same projection
        self.assertGreater(S.pick_score(9.5, 8.0, 6, 0, "balanced", False), S.pick_score(9.5, 9.3, 6, 0, "balanced", False))


class ClassCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = L.run(10, seed=11, verbose=False)

    def rate(self, rnd, f):
        xs = [x for x in self.rows if x["rnd"] == rnd]
        return L.pct(xs, f)

    def test_outcomes_fall_by_round_like_the_nhl(self):
        hundred = [self.rate(r, lambda x: x["games"] >= 100) for r in range(1, 6)]
        self.assertTrue(55 <= hundred[0] <= 85, hundred)            # real 68.8
        self.assertTrue(25 <= hundred[1] <= 55, hundred)            # real 38.2
        self.assertTrue(hundred[0] > hundred[1] > hundred[2] > hundred[4])
        five = self.rate(1, lambda x: x["games"] >= 500)
        self.assertTrue(30 <= five <= 60, five)                     # real 41.4

    def test_stars_per_class_and_where_they_come_from(self):
        elite = [x for x in self.rows if x["peak"] >= L.ELITE]
        per_class = len(elite) / 10
        self.assertTrue(4 <= per_class <= 10, per_class)            # real 5-8
        self.assertGreater(sum(1 for x in elite if x["rnd"] == 1) / len(elite), 0.6)   # real ~80%

    def test_small_players_slide_but_hit_more(self):
        drafted = [x for x in self.rows if x["rnd"] <= 7 and not x["goalie"]]
        small = [x for x in drafted if x["height"] <= 178]
        big = [x for x in drafted if x["height"] >= 190]
        self.assertGreater(statistics.mean(x["no"] for x in small), statistics.mean(x["no"] for x in big))
        hit = lambda xs: L.pct(xs, lambda x: x["games"] >= 100)
        self.assertGreater(hit(small), hit(big))

    def test_goalies_rarely_go_in_round_one(self):
        self.assertLessEqual(sum(1 for x in self.rows if x["goalie"] and x["rnd"] == 1) / 10, 2.5)


class WorldClassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.conn, self.me = small_world(self.tmp.name)
        self.addCleanup(self.conn.close)

    def test_world_starts_with_classes_and_adds_one_each_summer(self):
        c = self.conn
        have = c.execute("SELECT COUNT(*) FROM prospect_info").fetchone()[0]
        self.assertGreater(have, 0)
        added = Wd.create_draft_class(c, "2026-09-01")
        self.assertGreater(added, (CLASS_SKATERS + CLASS_GOALIES) * 0.5)
        self.assertEqual(Wd.create_draft_class(c, "2026-09-01"), 0)          # once a year
        year = Wd.season_year(c) + 1
        ages = [Wd.age_on(r[0], datetime.date(year, 9, 15)) for r in c.execute(
            "SELECT birth_date FROM players p JOIN prospect_info i USING (player_id) WHERE i.class_year=?",
            (year + 1,))]
        self.assertTrue(ages and all(a == 17 for a in ages))

    def test_board_shows_what_scouts_can_see(self):
        rows = D.board_rows(self.conn, self.me, 30)
        self.assertTrue(rows)
        r = rows[0]
        for k in ("proj", "grade", "height", "nat", "flags", "age"):
            self.assertIn(k, r)
        self.assertEqual([x["rank"] for x in rows], list(range(1, len(rows) + 1)))

    def test_khl_contract_blocks_the_elc_and_holds_the_rights(self):
        c = self.conn
        pid = c.execute("SELECT player_id FROM players WHERE team_id IS NULL AND status='active' ORDER BY player_id "
                        "LIMIT 1").fetchone()[0]
        year = D.draft_year(c)
        S.ensure_tables(c)
        c.execute("INSERT OR REPLACE INTO prospect_info VALUES (?,0,1,'two_way','russia',?,?)", (pid, year + 1, year))
        D.make_pick(c, year, 999, self.me, pid, f"{year}-06-26")
        exp = c.execute("SELECT expires_year FROM draft_rights WHERE player_id=?", (pid,)).fetchone()[0]
        self.assertGreaterEqual(exp, year + 3)
        c.execute('UPDATE game_state SET "current_date"=?', (f"{year}-07-01",))
        with self.assertRaises(ValueError):
            D.sign_elc(c, pid, self.me, f"{year}-07-01")

    def test_scouting_director_style_is_assigned(self):
        style = S.club_style(self.conn, self.me)
        self.assertIn(style, S.STYLES)


class GeneratorTests(unittest.TestCase):
    def test_class_shape(self):
        rng = random.Random(4)
        cls = make_draft_class(rng, NAMES, 2026)
        self.assertEqual(len(cls), CLASS_SKATERS + CLASS_GOALIES)
        heights = [p[0]["height_cm"] for p in cls if p[0]["position"] != "G"]
        self.assertTrue(180 <= statistics.mean(heights) <= 187)
        russians = [p for p in cls if p[0]["nationality"] == "RUS"]
        self.assertGreater(sum(1 for p in russians if p[3]["khl_years"]) / len(russians), 0.6)
        bloom = sum(1 for p in cls if p[3]["hidden_bloom"] > 0) / len(cls)
        self.assertTrue(0.05 < bloom < 0.2, bloom)

    def test_ceiling_is_hidden_from_current_ability(self):
        rng = random.Random(9)
        _, at, prof, info = gen_prospect(rng, NAMES, "CAN", "C", 17, 2026, quality=11.0)
        self.assertGreaterEqual(prof["potential"], 11.0)
        from hs.worldgen import overall_of
        self.assertLess(overall_of(at, "C"), 11.0)              # he has growing left to do


if __name__ == "__main__":
    unittest.main()
