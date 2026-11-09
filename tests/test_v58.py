"""v58: the public release: the fictional mock league and world, the first-run bootstrap, a career in the mock world."""
import json
import tempfile
import unittest
from pathlib import Path

from hs import bootstrap
from hs.datapack import load_pack, validate
from hs.tools import make_mock_league, make_mock_world
from hs.ui.saves import Saves

ROOT = Path(__file__).resolve().parent.parent


class MockWorldTests(unittest.TestCase):
    def test_mock_league_pack_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            n, p = make_mock_league.generate(Path(tmp) / "l", 3)
            self.assertEqual(n, 32)
            self.assertGreater(p, 800)
            issues = validate(load_pack(Path(tmp) / "l"))
            self.assertEqual([i for i in issues if "ERROR" in str(i).upper()], [])

    def test_world_is_fictional_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = make_mock_world.build(Path(tmp) / "a.db", 5)
            b = make_mock_world.build(Path(tmp) / "b.db", 5)
            import sqlite3
            ca, cb = sqlite3.connect(a), sqlite3.connect(b)
            q = "SELECT first_name, last_name, birth_date FROM players ORDER BY player_id LIMIT 50"
            self.assertEqual(ca.execute(q).fetchall(), cb.execute(q).fetchall())
            self.assertEqual(ca.execute("SELECT COUNT(*) FROM teams WHERE league_id=1").fetchone()[0], 32)
            names = " ".join(r[0] for r in ca.execute("SELECT name FROM teams"))
            for real in ("Boston", "Toronto", "Edmonton", "Providence", "Hershey"):
                self.assertNotIn(real, names)

    def test_bootstrap_builds_when_missing_and_career_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpl, env = bootstrap.resolve("auto", "auto", root=tmp)
            self.assertTrue(Path(tpl).exists())
            self.assertEqual(Path(tpl), Path(tmp) / "save" / "world.db")
            self.assertTrue(env.endswith("env_2025.json") or env.endswith("env_default.json"))
            s = Saves(Path(tmp) / "saves", tpl)
            self.assertEqual(len(s.worlds()), 1)
            s.new_game("Test", "PHM", 1)
            self.assertTrue((Path(tmp) / "saves" / "Test.db").exists())

    def test_shipped_environment_loads(self):
        env = json.load(open(ROOT / "data" / "env_default.json"))
        self.assertIn("game", env)
        self.assertGreater(env["game"]["goals_per_team_game"], 2)


if __name__ == "__main__":
    unittest.main()
