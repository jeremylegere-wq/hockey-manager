"""v34, phase C: money. Profiles, the gate and attendance (fans, price, form), the months' books, budgets (neutral at
the defaults), the arena, the season's close with the owner's cut, and the board's finance objectives."""
import io
import tempfile
import unittest

from hs.game import finance as FN
from hs.game.cli import CLI
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        FN.setup(self.c)


class GateTests(Base):
    def test_profiles(self):
        for t in FN._top(self.c):
            f = FN.profile(self.c, t)
            self.assertTrue(14_500 <= f["capacity"] <= 21_500)
            self.assertTrue(1 <= f["market"] <= 10)

    def test_demand_follows_fans_and_price(self):
        f = FN.profile(self.c, self.me)
        base = FN.demand(self.c, self.me, f)
        dear = dict(f, price_upper=f["price_upper"] * 1.5)
        self.assertLess(FN.demand(self.c, self.me, dear)["upper"], base["upper"])
        self.assertLess(FN.demand(self.c, self.me, dear)["upper"] / base["upper"], FN.demand(self.c, self.me, dict(f, price_premium=f["price_premium"] * 1.5))["premium"] / base["premium"])
        from hs.game import press as P
        P.media_state(self.c, self.me)
        self.c.execute("UPDATE media_state SET fan_sentiment=90 WHERE team_id=?", (self.me,))
        self.assertGreater(FN.demand(self.c, self.me, f)["lower"], base["lower"])

    def test_a_season_of_books(self):
        sim_until(self.c, ENV, Skill(), self.me, days=40)
        n = self.c.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        home = self.c.execute("SELECT COUNT(*) FROM games WHERE played=1 AND game_type='RS'").fetchone()[0]
        self.assertEqual(n, home)
        for a in self.c.execute("SELECT * FROM attendance").fetchall():
            self.assertLessEqual(a["total"], a["capacity"])
        cats = {r[0] for r in self.c.execute("SELECT DISTINCT category FROM finance_ledger")}
        self.assertTrue({"gate", "concessions", "media", "sponsorship", "payroll", "staff", "arena", "travel"} <= cats, cats)
        host = self.c.execute("SELECT team_id FROM attendance LIMIT 1").fetchone()[0]
        v = FN.view(self.c, host)
        self.assertGreater(v["revenue"], 0)
        self.assertGreater(v["attendance"]["games"], 0)
        FN.season_close(self.c, FN._season(self.c), get_state(self.c)[0])
        r = self.c.execute("SELECT * FROM finance_season WHERE team_id=?", (self.me,)).fetchone()
        self.assertIsNotNone(r)
        self.assertTrue(self.c.execute("SELECT 1 FROM inbox WHERE subject='The season''s books'").fetchone())


class ChoicesTests(Base):
    def test_budgets_are_neutral_at_default(self):
        for t in FN._top(self.c):
            self.assertEqual(FN.scouting_effect(self.c, t), 1.0)
            self.assertEqual(FN.development_effect(self.c, t), 1.0)
            self.assertEqual(FN.marketing_drift(self.c, t), 0.0)
        FN.set_budget(self.c, self.me, "scouting", 9_000_000)
        self.assertLess(FN.scouting_effect(self.c, self.me), 1.0)
        with self.assertRaises(ValueError):
            FN.set_budget(self.c, self.me, "scouting", 100)

    def test_prices_and_arena_through_the_cli(self):
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        cli.onecmd("tickets upper 80")
        self.assertEqual(cli.status_code, 0, out.getvalue())
        self.assertEqual(FN.profile(cli.conn, self.me)["price_upper"], 80)
        cli.onecmd("tickets upper 5")
        self.assertEqual(cli.status_code, 1)
        cli.onecmd("arena improve 3")
        self.assertEqual(cli.status_code, 1)                  # in season: refused
        cli.onecmd("finances")
        self.assertIn("Market", out.getvalue())


if __name__ == "__main__":
    unittest.main()
