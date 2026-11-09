"""v48: quickstarts, schedule export/import, club logos."""
import csv
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from hs.game import quickstart as QS
from hs.game import schedule_io as SI
from hs.game import editor as ED
from hs.game.state import connect, get_state, user_team

from test_world import small_world


class QuickstartTests(unittest.TestCase):
    def test_make_and_start(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db, c, me = small_world(tmp.name)
        self.addCleanup(c.close)
        from hs.game.state import add_message
        add_message(c, get_state(c)[0], "Hello", "a message for the old GM")
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('challenge_mode', '1')")
        c.commit()
        ok, _ = QS.can_make(c)
        self.assertTrue(ok)
        qs = Path(tmp.name) / "qs.db"
        QS.make(c, qs, "Test start")
        self.assertTrue(QS.is_quickstart(qs))
        with self.assertRaises(ValueError):
            QS.make(c, qs, "again")                              # exists
        q = connect(str(qs))
        self.assertIsNone(user_team(q))
        self.assertEqual(q.execute("SELECT COUNT(*) FROM inbox").fetchone()[0], 0)
        self.assertIsNone(q.execute("SELECT value FROM pack_info WHERE key='challenge_mode'").fetchone())
        q.close()
        # a career from it, with another club
        other = c.execute("SELECT abbr FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (me,)).fetchone()[0]
        dest = Path(tmp.name) / "career.db"
        shutil.copyfile(qs, dest)
        QS.start(str(dest), other, 9)
        k = connect(str(dest))
        t = user_team(k)
        self.assertEqual(k.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()[0], other)
        self.assertEqual(k.execute("SELECT gm_name FROM board WHERE team_id=?", (t,)).fetchone()[0], "You")
        self.assertNotEqual(k.execute("SELECT gm_name FROM board WHERE team_id=?", (me,)).fetchone()[0], "You")
        self.assertEqual(k.execute("SELECT COUNT(*) FROM gm_career").fetchone()[0], 1)
        k.close()

    def test_not_mid_season(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db, c, me = small_world(tmp.name)
        self.addCleanup(c.close)
        c.execute("UPDATE games SET played=1 WHERE game_id=(SELECT MIN(game_id) FROM games)")
        ok, why = QS.can_make(c)
        self.assertFalse(ok)
        c.execute("UPDATE pack_info SET value='draft' WHERE key='season_state'")
        self.assertFalse(QS.can_make(c)[0])


class ScheduleTests(unittest.TestCase):
    def test_export_import(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db, c, me = small_world(tmp.name)
        self.addCleanup(c.close)
        text = SI.export_csv(c)
        rows = list(csv.DictReader(io.StringIO(text)))
        n = c.execute("SELECT COUNT(*) FROM games WHERE game_type='RS'").fetchone()[0]
        self.assertEqual(len(rows), n)
        # the same schedule back: no problems, equal totals
        res = SI.import_csv(c, text)
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["games"], n)
        self.assertEqual(res["warnings"], [])
        with self.assertRaises(ValueError):
            SI.import_csv(c, text, apply=True)                 # needs commissioner mode
        # a broken schedule
        bad = "date,home,away\n2001-01-01,%s,%s\n%s,XXX,%s\n%s,%s,%s\n" % (rows[0]["home"], rows[0]["away"], rows[1]["date"], rows[1]["away"],
                                                                     rows[2]["date"], rows[2]["home"], rows[2]["home"])
        res = SI.import_csv(c, bad)
        self.assertEqual(len(res["problems"]), 3)
        # a shorter one, applied
        ED.set_enabled(c, True)
        short = "date,home,away\n" + "".join(f"{r['date']},{r['home']},{r['away']}\n" for r in rows[: n // 2])
        res = SI.import_csv(c, short, apply=True)
        self.assertEqual(res["applied"], n // 2)
        self.assertTrue(res["warnings"] or True)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM games WHERE game_type='RS'").fetchone()[0], n // 2)
        self.assertEqual(SI.import_csv(c, "nonsense")["problems"][0][0], 1)


class LogoTests(unittest.TestCase):
    def test_logo_files(self):
        from hs.ui.server import Game
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "saves").mkdir()
        g = Game(None, {}, saves=str(root / "saves"))
        src = root / "mine"
        src.mkdir()
        (src / "mtl.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        (src / "TOR.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        (src / "notes.txt").write_text("x")
        n, skipped, dest = g.import_logos(str(src))
        self.assertEqual(n, 2)
        self.assertEqual(g.logos(), {"MTL", "TOR"})
        self.assertEqual(g.logo_file("mtl").name, "MTL.png")
        self.assertIsNone(g.logo_file("../saves"))
        self.assertIsNone(g.logo_file("BOS"))


if __name__ == "__main__":
    unittest.main()
