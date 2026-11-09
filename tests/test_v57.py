"""v57: a new arena: the quote and the owner's approval, construction and financing month by month, the opening,
the loan, the accounts (depreciation over thirty years, loan interest, financing on the cash statement)."""
import io
import tempfile
import unittest

from hs.game import accounts as AC
from hs.game import arena as AR
from hs.game import finance as FN
from hs.game.cli import CLI
from hs.game.state import get_state

from test_game import make_db
from test_sim import ENV


class ArenaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = make_db(tmp.name)
        self.addCleanup(self.c.close)
        FN.setup(self.c)
        self.c.execute("UPDATE club_finance SET arena_quality=60 WHERE team_id=?", (self.me,))
        self.c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state', 'free_agency')")

    def test_quote_and_refusals(self):
        c, me = self.c, self.me
        q = AR.quote(c, me, 18000, 90)
        self.assertEqual(q["cost"], round(18000 * AR.SEAT_COST))
        self.assertAlmostEqual(q["owner_share"] + q["loan"], q["cost"], delta=2)
        self.assertFalse(AR.quote(c, me, 30000, 90)["ok"])
        c.execute("UPDATE club_finance SET arena_quality=85 WHERE team_id=?", (me,))
        self.assertIn("Renovate", AR.quote(c, me, 18000, 90)["why"])
        c.execute("UPDATE club_finance SET arena_quality=60 WHERE team_id=?", (me,))
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state', 'regular_season')")
        with self.assertRaises(ValueError):
            AR.propose(c, me, 18000, 90)

    def test_build_open_and_books(self):
        c, me = self.c, self.me
        q = AR.propose(c, me, 18000, 90, "2026-07-10")
        self.assertTrue(q["ok"])
        with self.assertRaises(ValueError):
            AR.propose(c, me, 18000, 90)                                  # once
        cash0 = FN.profile(c, me)["cash"]
        post = lambda t, d, cat, amt, det: FN._post(c, t, d, cat, amt, det)
        for m in range(8, 13):
            AR.monthly(c, f"2026-{m:02d}-01", post)
        p = c.execute("SELECT * FROM arena_projects WHERE team_id=?", (me,)).fetchone()
        self.assertEqual(p["months_paid"], 5)
        # cash moves by capex + owner + loan: nets to zero during construction
        self.assertAlmostEqual(FN.profile(c, me)["cash"], cash0, delta=10)
        # accounts: the capital is depreciated over thirty years; financing is not revenue
        r = AC.pnl(c, me, 2026, "year", "total", "none", 3)
        rev = next(x for x in r["rows"] if x["code"] == "4000")["vals"][0]
        dep = next((x for x in r["rows"] if x["code"] == "6520"), None)
        self.assertIsNotNone(dep)
        self.assertAlmostEqual(dep["vals"][0], -p["cost"] / 24 / 360 * (10 + 9 + 8 + 7 + 6), delta=50)   # paid Aug-Dec, to June
        self.assertLess(rev, p["loan"] * 5 / 24)                            # the loan is not in revenue
        cs = AC.cash_statement(c, me, 2026)
        self.assertAlmostEqual(cs["financing"], p["loan"] * 5 / 24, delta=10)
        self.assertAlmostEqual(cs["opening"] + cs["operating"] + cs["capital"] + cs["owner"] + cs["financing"], cs["closing"], delta=5)
        # opening: two seasons on
        c.execute("UPDATE arena_projects SET opens_season=? WHERE team_id=?", (2026, me))
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state', 'preseason')")
        self.assertIn(me, AR.on_preseason(c, "2026-09-20"))
        f = FN.profile(c, me)
        self.assertEqual((f["capacity"], f["arena_quality"]), (18000, 90))
        self.assertGreater(AR.novelty(c, me), 0)
        loan = c.execute("SELECT * FROM arena_loans WHERE team_id=?", (me,)).fetchone()
        self.assertAlmostEqual(loan["balance"], p["loan"] * 5 / 24, delta=10)
        AR.monthly(c, "2026-10-01", post)
        self.assertLess(c.execute("SELECT balance FROM arena_loans WHERE team_id=?", (me,)).fetchone()[0], loan["balance"])
        j = AC.journal(c, me, 2026, "7130", "year")
        self.assertEqual(j["count"], 1)

    def test_cli(self):
        self.c.commit()
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        for line in ("arena quote 18000 90", "arena status"):
            cli.onecmd(line)
            self.assertEqual(cli.status_code, 0, out.getvalue())
        self.assertIn("Quote", out.getvalue())


if __name__ == "__main__":
    unittest.main()
