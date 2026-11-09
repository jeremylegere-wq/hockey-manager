"""Real-contract importer, tested with a synthetic CSV on the fictional pack (no third-party data)."""
import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hs.adapters import contracts_csv as CC
from hs.game import contracts as K

from test_game import make_db


class ParseTests(unittest.TestCase):
    def test_money_and_seasons(self):
        self.assertEqual(CC.money("$7,875,000"), 7_875_000)
        self.assertEqual(CC.money("7.875M"), 7_875_000)
        self.assertEqual(CC.money("875K"), 875_000)
        self.assertEqual(CC.money("7.875"), 7_875_000)
        self.assertIsNone(CC.money("-"))
        self.assertEqual(CC.season_of("2028-29", True), 2028)
        self.assertEqual(CC.season_of("2029 UFA", True), 2028)        # expires in the summer of 2029
        self.assertEqual(CC.season_of("2026", False), 2026)

    def test_loose_headers(self):
        col = CC.columns(["Player", "TEAM", "Cap Hit", "Expiry Status", "Length", "Clauses"])
        self.assertEqual(set(col), {"player", "team", "cap", "expiry", "length", "clause"})


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.conn, self.me = make_db(self.tmp.name)
        self.addCleanup(self.conn.close)
        c = self.conn
        self.rows = c.execute("SELECT p.player_id, p.first_name, p.last_name, t.abbr FROM players p JOIN teams t ON "
                              "t.team_id=p.team_id WHERE p.team_id=? AND (SELECT COUNT(*) FROM players q WHERE "
                              "q.first_name=p.first_name AND q.last_name=p.last_name)=1 ORDER BY p.player_id LIMIT 3",
                              (self.me,)).fetchall()
        self.season = K.season_year(c)
        path = Path(self.tmp.name) / "real.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Player", "Team", "Cap Hit", "Expiry", "Length", "Clause", "Type"])
            a, b, d = self.rows
            w.writerow([f"{a[1]} {a[2]}", a[3], "$7,875,000", f"{self.season + 3}-{str(self.season + 4)[2:]}", "8",
                        "M-NTC", ""])
            w.writerow([f"{b[2]}, {b[1]}", a[3], "0.975M", f"{self.season + 2} RFA", "3", "", "ELC"])
            w.writerow([f"{d[1]} {d[2]}", "", "1.2", str(self.season + 2), "", "", ""])
            w.writerow(["Nobody Real", "XXX", "$1,000,000", "2030", "2", "", ""])
        self.path = path
        self.conn.close()

    def run_cli(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            CC.main([str(self.path), "--db", self.db, *extra])
        return out.getvalue()

    def test_dry_run_reports_and_changes_nothing(self):
        from hs.game.state import connect
        before = connect(self.db).execute("SELECT COUNT(*), SUM(cap_hit) FROM contracts").fetchone()[:]
        text = self.run_cli("--dry-run")
        self.assertIn("matched 3", text)
        self.assertIn("unmatched 1", text)
        self.assertEqual(connect(self.db).execute("SELECT COUNT(*), SUM(cap_hit) FROM contracts").fetchone()[:], before)

    def test_contracts_replace_generated_ones(self):
        self.run_cli()
        from hs.game.state import connect
        c = connect(self.db)
        a, b, d = (r[0] for r in self.rows)
        ca = K.current_contract(c, a)
        self.assertEqual((ca["cap_hit"], ca["years"], ca["no_trade"]), (7_875_000, 8, 1))
        self.assertEqual(ca["start_year"] + ca["years"] - 1, self.season + 3)
        cb = K.current_contract(c, b)
        self.assertEqual((cb["cap_hit"], cb["contract_type"]), (975_000, "entry_level"))
        cd = K.current_contract(c, d)
        self.assertEqual(cd["cap_hit"], 1_200_000)
        self.assertEqual(cd["start_year"] + cd["years"] - 1, self.season + 1)   # through 2nd summer
        for pid in (a, b, d):
            n = c.execute("SELECT COUNT(*) FROM contracts WHERE player_id=? AND start_year+years>?",
                          (pid, self.season)).fetchone()[0]
            self.assertEqual(n, 1)


class MarketTests(unittest.TestCase):
    def test_market_prices_what_clubs_can_see(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _, c, me = make_db(tmp.name)
        self.addCleanup(c.close)
        values = K.league_values(c)
        self.assertIsInstance(values, K.MarketValues)
        self.assertEqual(len(values), len(values.of))
        pid = next(iter(values.of))
        self.assertGreaterEqual(K.market_aav(c, pid, values), K.crules(c)["min_salary"])
        self.assertIs(K.league_values(c), values)                     # cached for the day


if __name__ == "__main__":
    unittest.main()
