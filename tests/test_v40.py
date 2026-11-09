"""v40: player development through the season (monthly steps, factors, mentors, training intensity, the summer's
share, the report)."""
import datetime
import json
import tempfile
import unittest

from hs.game import development as DV
from hs.game import roster as R
from hs.game.state import get_state

from test_game import make_db


class DevTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]
        y = int(self.day[:4])
        self.tick = f"{y}-12-01"

    def ages(self):
        on = datetime.date.fromisoformat(self.day)
        out = {}
        for r in self.c.execute("SELECT player_id, birth_date, team_id, status FROM players WHERE team_id=?", (self.me,)):
            b = datetime.date.fromisoformat(r[1])
            out[r[0]] = (on.year - b.year - ((on.month, on.day) < (b.month, b.day)), r[3])
        return out

    def test_monthly_step(self):
        n, _ = DV.monthly(self.c, self.tick)
        self.assertGreater(n, 0)
        rows = self.c.execute("SELECT delta, factors FROM dev_log WHERE kind='month'").fetchall()
        self.assertEqual(len(rows), n)
        self.assertGreater(sum(r[0] for r in rows) / n, 0)               # growing players grow
        f = json.loads(rows[0][1])
        self.assertIn("character", f)
        self.assertEqual(self.c.execute("SELECT MAX(steps) FROM dev_plan").fetchone()[0], 1)
        n2, _ = DV.monthly(self.c, self.tick)                              # the same day again: plans do not reset
        self.assertEqual(self.c.execute("SELECT MAX(steps) FROM dev_plan").fetchone()[0], 2)

    def test_is_tick(self):
        self.assertTrue(DV.is_tick(self.c, self.tick))
        self.assertFalse(DV.is_tick(self.c, self.tick.replace("-01", "-02")))

    def test_intensity(self):
        self.assertEqual(DV.intensity(self.c, self.me), "normal")
        DV.set_intensity(self.c, self.me, "hard")
        self.assertGreater(DV.injury_factor(self.c, self.me), 1.0)
        with self.assertRaises(ValueError):
            DV.set_intensity(self.c, self.me, "brutal")

    def test_mentor_rules(self):
        ages = self.ages()
        kid = next((p for p, (a, s) in ages.items() if a <= 23), None)
        vet = next((p for p, (a, s) in ages.items() if a >= 27 and s in ("active", "injured")), None)
        if kid is None or vet is None:
            self.skipTest("fixture lacks a kid or a veteran")
        DV.ensure_tables(self.c)
        from hs.game import people as P
        P.ensure_tables(self.c)
        self.c.execute("INSERT OR IGNORE INTO personality (player_id) VALUES (?)", (vet,))
        self.c.execute("UPDATE personality SET professionalism=17, ego=8 WHERE player_id=?", (vet,))
        self.c.execute("INSERT OR IGNORE INTO personality (player_id) VALUES (?)", (kid,))
        self.c.execute("UPDATE personality SET professionalism=8 WHERE player_id=?", (kid,))
        DV.assign_mentor(self.c, self.me, kid, vet, self.day)
        self.assertEqual(DV.mentor_of(self.c, kid), vet)
        with self.assertRaises(ValueError):                               # the veteran cannot be mentored
            DV.assign_mentor(self.c, self.me, vet, kid, self.day)
        DV.monthly(self.c, self.tick)
        row = self.c.execute("SELECT factors FROM dev_log WHERE player_id=?", (kid,)).fetchone()
        if row:                                                            # (he grows this year)
            self.assertEqual(json.loads(row[0]).get("mentor"), DV.MENTOR_F_TOP)
        ctx = DV._context(self.c, self.day)
        self.assertEqual(ctx["mentors"].get(kid), vet)
        self.c.execute("UPDATE personality SET professionalism=5 WHERE player_id=?", (vet,))
        with self.assertRaises(ValueError):
            DV.assign_mentor(self.c, self.me, kid, vet, self.day)

    def test_level_factor(self):
        DV.ensure_tables(self.c)
        ctx = DV._context(self.c, self.day)
        from hs.game import world as W
        rows = W.load_attrs(self.c, "p.team_id=?", (self.me,))
        pid, r = next(iter(rows.items()))
        f = DV.factors(self.c, pid, r, 22, self.day, self.tick, ctx)
        self.assertIn(f["level"], DV.LEVEL.values())
        self.assertTrue(DV.CLAMP[0] <= DV.product(f) <= DV.CLAMP[1])

    def test_summer_share_and_decline(self):
        DV.monthly(self.c, self.tick)
        ctx = DV._context(self.c, self.day)
        from hs.game import world as W
        from hs.game import contracts as K
        rows = W.load_attrs(self.c)
        y = K.season_year(self.c)
        pid = self.c.execute("SELECT player_id FROM dev_plan WHERE steps>0 LIMIT 1").fetchone()[0]
        m = DV.summer_multiplier(self.c, pid, rows[pid], 21, 0.3, y, ctx)
        self.assertLess(m, 1.0 / (1 - DV.IN_SEASON_SHARE / 6 * 6) )
        from hs.game import people as P
        P.ensure_tables(self.c)
        self.c.execute("INSERT OR IGNORE INTO personality (player_id) VALUES (?)", (pid,))
        self.c.execute("UPDATE personality SET professionalism=18 WHERE player_id=?", (pid,))
        self.assertLess(DV.summer_multiplier(self.c, pid, rows[pid], 34, -0.3, y, ctx), 1.0)

    def test_report_for_your_club(self):
        DV.monthly(self.c, self.tick)
        self.assertTrue(self.c.execute("SELECT 1 FROM inbox WHERE subject LIKE 'Development report%'").fetchone())

    def test_views(self):
        DV.monthly(self.c, self.tick)
        from hs.ui import api
        v = api.development_view(self.c)
        self.assertIn("intensity", v)
        self.assertTrue(any(p.get("dev") for p in v["players"]))
        pid = next(p["player_id"] for p in v["players"] if p.get("dev"))
        self.assertIn("log", api.devlog_view(self.c, pid))


if __name__ == "__main__":
    unittest.main()


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        from hs.game import editor as ED
        self.ED = ED

    def test_needs_commissioner_mode(self):
        pid = R.roster(self.c, self.me)[0]["player_id"]
        with self.assertRaises(ValueError):
            self.ED.edit_player(self.c, pid, {"passing": 15})
        self.ED.set_enabled(self.c, True)
        self.assertTrue(self.ED.edited(self.c))
        done = self.ED.edit_player(self.c, pid, {"passing": 15, "first_name": "Testy", "professionalism": 18})
        self.assertIn("passing", done)
        from hs.game import ratings as RT
        self.assertEqual(RT.of(self.c, pid)["passing"], 15)
        self.assertEqual(self.c.execute("SELECT first_name FROM players WHERE player_id=?", (pid,)).fetchone()[0], "Testy")
        with self.assertRaises(ValueError):
            self.ED.edit_player(self.c, pid, {"passing": 25})
        with self.assertRaises(ValueError):
            self.ED.edit_player(self.c, pid, {"position": "X"})

    def test_contract_clause_and_move(self):
        self.ED.set_enabled(self.c, True)
        from hs.game import contracts as K
        from hs.game import clauses as CL
        pid = next(r["player_id"] for r in R.roster(self.c, self.me) if K.current_contract(self.c, r["player_id"]))
        y = K.season_year(self.c)
        self.ED.edit_player(self.c, pid, {"cap_hit": "4.5m", "contract_end": y + 3, "clause": "MNTC:12"})
        c = K.current_contract(self.c, pid)
        self.assertEqual(c["cap_hit"], 4_500_000)
        self.assertEqual(c["start_year"] + c["years"] - 1, y + 3)
        self.assertEqual(CL.of(self.c, pid)["list_size"], 12)
        other = self.c.execute("SELECT abbr, team_id FROM teams WHERE team_id<>? AND league_id=1", (self.me,)).fetchone()
        self.ED.edit_player(self.c, pid, {"team": other[0]})
        self.assertEqual(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0], other[1])
        self.ED.edit_player(self.c, pid, {"team": "FA"})
        self.assertIsNone(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0])

    def test_export_import_round_trip(self):
        import csv
        import io
        text = self.ED.export_players(self.c, "mine")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertTrue(rows)
        self.ED.set_enabled(self.c, True)
        # unchanged file: no changes
        res = self.ED.import_players(self.c, text)
        self.assertEqual(res["changes"], [])
        self.assertEqual(res["matched"], len(rows))
        # change one rating, add one bad row and one new player
        rows[0]["passing"] = str(min(20, int(rows[0]["passing"] or 10) + 2) if rows[0]["passing"] else 12)
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()) + ["Mystery"])
        w.writeheader()
        w.writerow({**rows[0], "Mystery": "x"})
        w.writerow({"player_id": "99999999"})
        w.writerow({"first_name": "New", "last_name": "Guy", "birth_date": "2004-05-06", "position": "C", "team": "FA", "passing": "14"})
        prev = self.ED.import_players(self.c, out.getvalue())
        self.assertEqual(len(prev["errors"]), 1)
        self.assertEqual(prev["created"], 1)
        self.assertIn("Mystery", prev["unknown_columns"])
        self.assertFalse(self.c.execute("SELECT 1 FROM players WHERE first_name='New' AND last_name='Guy'").fetchone())   # preview only
        res = self.ED.import_players(self.c, out.getvalue(), apply=True)
        self.assertTrue(res["applied"])
        self.assertTrue(self.c.execute("SELECT 1 FROM players WHERE first_name='New' AND last_name='Guy'").fetchone())

    def test_aliases(self):
        self.assertEqual(self.ED._header("CA"), "current_ability")
        self.assertEqual(self.ED._header("Surname"), "last_name")
        self.assertEqual(self.ED._header("DOB"), "birth_date")
        self.assertEqual(self.ED._money("7.5"), 7_500_000)
        self.assertEqual(self.ED._money("$950,000"), 950_000)
