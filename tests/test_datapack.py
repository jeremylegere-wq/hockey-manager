import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hs.datapack import PackError, load_pack, validate
from hs.ingest import build_db
from hs.tools.make_example_pack import generate


def errors(pack_dir):
    return [i for i in validate(load_pack(pack_dir)) if i.level == "error"]


def rewrite(path, fn):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
        cols = list(rows[0].keys())
    fn(rows)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class DataPackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = Path(self.tmp.name) / "pack"
        generate(self.pack)

    def tearDown(self):
        self.tmp.cleanup()

    def test_example_pack_is_valid(self):
        self.assertEqual(errors(self.pack), [])

    def test_rating_out_of_range_is_rejected(self):
        rewrite(self.pack / "attributes.csv", lambda rows: rows[0].update(shot_accuracy="25"))
        self.assertTrue(any("outside 1-20" in e.message for e in errors(self.pack)))

    def test_dangling_team_is_rejected(self):
        rewrite(self.pack / "players.csv", lambda rows: rows[0].update(team_id="999"))
        self.assertTrue(any("unknown team_id" in e.message for e in errors(self.pack)))

    def test_missing_goalie_attribute_is_rejected(self):
        def blank_goalie(rows):
            g = next(r for r in rows if r["glove"] != "")
            g["glove"] = ""
        rewrite(self.pack / "attributes.csv", blank_goalie)
        self.assertTrue(any("glove" in e.message for e in errors(self.pack)))

    def test_bad_position_is_rejected(self):
        rewrite(self.pack / "players.csv", lambda rows: rows[0].update(position="X"))
        self.assertTrue(any("position" in e.message for e in errors(self.pack)))

    def test_ingest_builds_database_and_refuses_invalid_pack(self):
        db = Path(self.tmp.name) / "g.db"
        counts = build_db(self.pack, db)
        self.assertEqual(counts["teams"], 8)
        self.assertEqual(counts["players"], 184)   # 160 rostered + 24 free agents
        self.assertEqual(counts["player_attributes"], 184)
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("select count(*) from players where position='G'").fetchone()[0], 20)
        with self.assertRaises(FileExistsError):
            build_db(self.pack, db)  # cannot overwrite without force
        build_db(self.pack, db, overwrite=True)  # force works
        rewrite(self.pack / "players.csv", lambda rows: rows[0].update(team_id="999"))
        with self.assertRaises(PackError):
            build_db(self.pack, Path(self.tmp.name) / "bad.db")
        self.assertFalse((Path(self.tmp.name) / "bad.db").exists())  # nothing half-imported


if __name__ == "__main__":
    unittest.main()
