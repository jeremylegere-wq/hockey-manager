"""Contract valuation (surplus value) and the free-agency auction."""
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import free_agency as FA
from hs.game import offseason as O
from hs.game import valuation as V
from hs.game.dayloop import sim_until
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.m = V.market(self.c)

    def players(self):
        rows = self.c.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL AND status='active' AND "
                              "position<>'G'").fetchall()
        return sorted((self.m.values.value(r[0]), r[0]) for r in rows)

    def test_prices_are_in_a_sane_range(self):
        self.assertTrue(2_000_000 < self.m.cost_per_win < 10_000_000, self.m.cost_per_win)
        self.assertGreater(self.m.cpw(self.m.year + 3), self.m.cpw(self.m.year))   # grows with the cap

    def test_better_players_are_worth_more_and_age_costs_value(self):
        ps = self.players()
        low, high = ps[len(ps) // 10][1], ps[-1][1]
        self.assertGreater(V.fair_aav(self.c, high, 3), V.fair_aav(self.c, low, 3))
        # the same player on a long deal is worth less a year once he is older
        self.c.execute("UPDATE players SET birth_date='1991-01-01' WHERE player_id=?", (high,))
        V._CACHE.clear()
        old_short, old_long = V.fair_aav(self.c, high, 2), V.fair_aav(self.c, high, 6)
        self.assertGreater(old_short, old_long)

    def test_grades_and_risk(self):
        ps = self.players()
        star = ps[-1][1]
        cheap = V.evaluate(self.c, star, K.crules(self.c)["min_salary"], 3, self.m.year)
        dear = V.evaluate(self.c, ps[len(ps) // 4][1], 9_000_000, 7, self.m.year)
        self.assertEqual(cheap["grade"], "A")
        self.assertGreater(cheap["p_positive"], 0.9)
        self.assertIn(dear["grade"], ("D", "F"))
        self.assertLess(dear["p_positive"], 0.2)
        self.assertEqual(V.grade(0)[0], "C")
        self.assertEqual(V.grade(-20_000_000)[0], "F")

    def test_market_terms(self):
        self.assertEqual(FA.wanted_term(1, 28, 7), 7)
        self.assertEqual(FA.wanted_term(1, 33, 7), 3)
        self.assertLessEqual(FA.wanted_term(3, 33, 7), 2)
        self.assertGreater(FA.ask_mult(1, 0), 1.15)
        self.assertLess(FA.ask_mult(1, 48), 0.6)                   # the day-two cliff
        self.assertGreater(FA.utility(5e6, 4, 33), FA.utility(5e6, 4, 25))   # older players prize security


class AuctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.c, cls.me = make_db(cls.tmp.name)
        sim_until(cls.c, ENV, Skill(), to_end=True)
        while K.season_state(cls.c) != "rights":
            O.advance(cls.c, ENV, Skill())
        cls.upcoming = FA.upcoming(cls.c)
        cls.target = next((x for x in cls.upcoming if x["team_id"] != cls.me), None)
        if cls.target:
            cr = K.crules(cls.c)
            FA.register_offer(cls.c, cls.me, cls.target["pid"],
                              int(min(cls.target["peak_ask"] * 1.8, cr["max_salary_pct"] * cr["cap_ceiling"])),
                              cls.target["years"], "2027-06-29")
        cls.lines = O.advance(cls.c, ENV, Skill())             # rights -> free agency (the auction)
        cls.year = K.signing_year(cls.c)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_market_opened_and_logged(self):
        self.assertTrue(any("Free agency opened" in l for l in self.lines), self.lines)
        rows = FA.fa_report(self.c, self.year)
        self.assertTrue(rows)
        hours = [r["hour"] for r in rows]
        self.assertEqual(hours, sorted(hours))

    def test_generous_user_offer_wins_at_noon(self):
        if not self.target:
            self.skipTest("no upcoming free agent")
        c = K.current_contract(self.c, self.target["pid"], self.year)
        self.assertIsNotNone(c)
        self.assertEqual(c["team_id"], self.me)

    def test_no_club_over_the_cap_or_the_contract_limit(self):
        cap = K.crules(self.c)["cap_ceiling"]
        for (t,) in self.c.execute("SELECT team_id FROM teams WHERE league_id=1"):
            if t == self.me:
                continue
            self.assertLessEqual(K.payroll(self.c, t, self.year), cap * 1.02)
            self.assertLessEqual(K.contract_count(self.c, t, self.year), K.crules(self.c)["max_contracts"])

    def test_leftovers_ask_less(self):
        for r in self.c.execute("SELECT ask, fair FROM fa_market WHERE season=?", (self.year,)):
            self.assertLessEqual(r[0], max(r[1] * 0.65, K.crules(self.c)["min_salary"]))


if __name__ == "__main__":
    unittest.main()
