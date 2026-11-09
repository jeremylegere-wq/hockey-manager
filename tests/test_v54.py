"""v54: financial statements: the chart of accounts, the profit and loss report (periods, comparisons, levels), the
budget, depreciation and the cash statement, the board's quarterly finance reviews."""
import io
import tempfile
import unittest

from hs.game import accounts as AC
from hs.game import finance as FN
from hs.game.cli import CLI
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class StatementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, c, cls.me = make_db(cls.tmp.name)
        for _ in range(30):                                  # into November (the sim stops for events along the way)
            if get_state(c)[0] >= "2026-11-15":
                break
            sim_until(c, ENV, Skill(), cls.me, until_date="2026-11-15")
        c.commit()
        c.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from hs.game.state import connect
        self.c = connect(self.db)
        self.addCleanup(self.c.close)
        self.today = get_state(self.c)[0]
        self.fy = AC.fy_of(self.today)

    def test_accounts_and_calendar(self):
        self.assertEqual(AC.account_of("gate", "playoff game 5: 18,000 fans", 1), "4120")
        self.assertEqual(AC.account_of("gate", "game 5: 18,000 fans", 1), "4110")
        self.assertEqual(AC.account_of("payroll", "signing bonuses", -1), "5120")
        self.assertEqual(AC.account_of("sharing", "revenue sharing", -1), "6410")
        self.assertIsNone(AC.account_of("arena_capital", "renovations", -1))
        self.assertEqual(AC.fy_of("2027-06-30"), 2026)
        self.assertEqual(AC.fy_of("2027-07-01"), 2027)
        self.assertEqual(AC.fy_months(2026)[0], "2026-07")
        self.assertEqual(AC.fy_months(2026)[-1], "2027-06")
        self.assertEqual(AC.period_months(2026, "q2")[0], ["2026-10", "2026-11", "2026-12"])

    def test_report_ties_to_the_ledger(self):
        c, me = self.c, self.me
        r = AC.pnl(c, me, self.fy, "year", "total", "none", 3)
        net = next(x for x in r["rows"] if x["name"] == "Net profit")["vals"][0]
        lo, hi = f"{self.fy}-07-01", f"{self.fy + 1}-06-31"
        led = c.execute("SELECT SUM(amount) FROM finance_ledger WHERE team_id=? AND day>=? AND day<=? AND category NOT IN ('owner', "
                        "'arena_capital')", (me, lo, hi)).fetchone()[0]
        self.assertAlmostEqual(net, led, delta=2)
        self.assertAlmostEqual(net, AC.fy_result(c, me, self.fy)[2], delta=2)
        # sections are the sums of their accounts
        rev = next(x for x in r["rows"] if x["code"] == "4000")["vals"][0]
        accs = sum(x["vals"][0] for x in r["rows"] if x["kind"] == "account" and x["code"].startswith("4"))
        self.assertAlmostEqual(rev, accs, delta=10)
        # by month: the columns add up to the total
        m = AC.pnl(c, me, self.fy, "year", "monthly", "none", 1)
        self.assertEqual(len(m["columns"]), 13)
        for row in m["rows"]:
            self.assertAlmostEqual(sum(row["vals"][:-1]), row["vals"][-1], delta=13)
        # levels and comparisons
        self.assertTrue(all(x["level"] == 1 for x in AC.pnl(c, me, self.fy, "year", "total", "none", 1)["rows"]))
        b = AC.pnl(c, me, self.fy, "ytd", "total", "both", 2)
        self.assertEqual([x["kind"] for x in b["columns"]], ["act", "bud", "var", "pct", "pri", "var", "pct"])
        for row in b["rows"]:
            self.assertEqual(row["vals"][2], row["vals"][0] - row["vals"][1])
        self.assertEqual(b["budget"]["status"], "approved")

    def test_journal_drill_down(self):
        j = AC.journal(self.c, self.me, self.fy, "4100", "year")
        self.assertGreater(j["count"], 0)
        self.assertTrue(all(x["account"] in ("4110", "4120") for x in j["lines"]))
        r = AC.pnl(self.c, self.me, self.fy, "year", "total", "none", 2)
        self.assertAlmostEqual(j["total"], next(x for x in r["rows"] if x["code"] == "4100")["vals"][0], delta=2)
        with self.assertRaises(ValueError):
            AC.journal(self.c, self.me, self.fy, "9999")

    def test_budget(self):
        c, me = self.c, self.me
        AC.build_budget(c, me, self.fy)
        rows = c.execute("SELECT COUNT(DISTINCT month), SUM(amount) FROM finance_budget WHERE team_id=? AND fy=? AND account='4310'",
                         (me, self.fy)).fetchone()
        self.assertGreaterEqual(rows[0], 9)                     # October to June planned (the summer at actual)
        self.assertFalse(c.execute("SELECT 1 FROM finance_budget WHERE team_id=? AND fy=? AND account='4120'", (me, self.fy)).fetchone())
        gate = c.execute("SELECT SUM(amount) FROM finance_budget WHERE team_id=? AND fy=? AND account='4110'", (me, self.fy)).fetchone()[0]
        self.assertGreater(gate, 0)

    def test_depreciation_and_cash(self):
        c, me = self.c, self.me
        m = AC.fy_months(self.fy)
        c.execute("INSERT INTO finance_ledger (team_id, day, season, category, amount, detail) VALUES (?,?,?,?,?,?)",
                  (me, m[0] + "-15", self.fy, "arena_capital", -12_000_000, "renovations"))
        c.execute("UPDATE club_finance SET cash=cash-12000000 WHERE team_id=?", (me,))
        dep = AC._depreciation(c, me, m)
        self.assertEqual(dep[m[0]], 0)
        self.assertEqual(dep[m[1]], -100_000)
        cs = AC.cash_statement(c, me, self.fy)
        self.assertEqual(cs["capital"], -12_000_000)
        self.assertAlmostEqual(cs["opening"] + cs["operating"] + cs["capital"] + cs["owner"], cs["closing"], delta=2)
        self.assertAlmostEqual(cs["operating"], cs["net_profit"] + cs["depreciation"], delta=2)
        c.rollback()

    def test_board_review(self):
        c, me = self.c, self.me
        c.execute("UPDATE owners SET spend=3 WHERE team_id=?", (me,))
        AC.ensure_budget(c, me, self.fy)
        q = AC.quarter_of(self.today[:7])
        prev = q - 1 if q > 1 else 1
        upto = AC.fy_months(self.fy)[3 * prev - 1]
        c.execute("INSERT INTO finance_ledger (team_id, day, season, category, amount, detail) VALUES (?,?,?,?,?,?)",
                  (me, upto + "-02", self.fy, "admin", -30_000_000, "a large bill"))
        conf = c.execute("SELECT confidence FROM board WHERE team_id=?", (me,)).fetchone()[0]
        r = AC.quarterly_review(c, me, self.fy, prev, self.today)
        self.assertEqual(r["delta"], -4 if prev < 4 else 0)
        self.assertIn("not acceptable", r["comment"])
        self.assertAlmostEqual(c.execute("SELECT confidence FROM board WHERE team_id=?", (me,)).fetchone()[0], conf + r["delta"])
        self.assertTrue(c.execute("SELECT 1 FROM inbox WHERE subject LIKE '%finance report%' OR subject LIKE 'Annual report%'").fetchone())
        self.assertIsNone(AC.quarterly_review(c, me, self.fy, prev, self.today))     # once a quarter
        b = AC.board_pack(c, me)
        self.assertEqual(len(b["trend"]), 12)
        self.assertTrue(b["reports"])
        self.assertEqual(AC.board_delta(3, -6e6), -2)
        self.assertEqual(AC.board_delta(5, -6e6), 0)
        self.assertEqual(AC.board_delta(8, -25e6), -1)
        self.assertEqual(AC.board_delta(3, 6e6), 2)
        c.rollback()

    def test_season_close_uses_the_fiscal_year(self):
        c, me = self.c, self.me
        FN.season_close(c, self.fy, self.today)
        r = c.execute("SELECT profit FROM finance_season WHERE team_id=? AND season=?", (me, self.fy)).fetchone()
        self.assertAlmostEqual(r[0], AC.fy_result(c, me, self.fy)[2], delta=2)
        c.rollback()

    def test_cli(self):
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        for line in ("pnl", "pnl ytd both 2", "pnl journal 5110", "boardpack"):
            cli.onecmd(line)
            self.assertEqual(cli.status_code, 0, out.getvalue())
        self.assertIn("Net profit", out.getvalue())
        self.assertIn("Board pack", out.getvalue())


if __name__ == "__main__":
    unittest.main()
