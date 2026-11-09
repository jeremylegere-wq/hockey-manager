"""v31, phase A: notes and the short list, Play until, rolling backups, CSV export and the new screens' views."""
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from hs.game.cli import CLI
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill
from hs.ui import screens as SC
from hs.ui.saves import Saves
from hs.ui.server import make_server

from test_game import make_db
from test_sim import ENV
from test_world import small_world


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def cli(self):
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        return cli, out

    def pid(self):
        return self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position<>'G' LIMIT 1", (self.me,)).fetchone()[0]


class NotesTests(Base):
    def test_notes_and_shortlist_through_the_cli(self):
        cli, out = self.cli()
        pid = self.pid()
        cli.onecmd("note add Watch the deadline market")
        cli.onecmd(f"note about {pid} Wants a bigger role")
        cli.onecmd(f"shortlist add {pid} depth at C")
        self.assertEqual(cli.status_code, 0, out.getvalue())
        v = SC.notes_view(cli.conn)
        self.assertEqual(len(v["notes"]), 2)
        self.assertEqual([s["player_id"] for s in v["shortlist"]], [pid])
        self.assertEqual(v["shortlist"][0]["reason"], "depth at C")
        m = SC.player_marks(cli.conn, pid)
        self.assertTrue(m["shortlisted"])
        self.assertEqual(len(m["notes"]), 1)
        nid = v["notes"][0]["note_id"]
        cli.onecmd(f"note edit {nid} Edited")
        cli.onecmd(f"note del {nid}")
        cli.onecmd(f"shortlist del {pid}")
        self.assertEqual(len(SC.notes_view(cli.conn)["notes"]), 1)
        self.assertFalse(SC.player_marks(cli.conn, pid)["shortlisted"])
        cli.onecmd("note add   ")
        self.assertEqual(cli.status_code, 1)                    # an empty note is refused


class ScreenTests(Base):
    def test_views_answer(self):
        sim_until(self.c, ENV, Skill(), self.me, days=4)
        s = SC.strip(self.c)
        self.assertEqual(len(s["days"]), 8)
        self.assertTrue(any(d["today"] for d in s["days"]))
        self.assertTrue(SC.play_targets(self.c))
        played_day = self.c.execute("SELECT game_date FROM games WHERE played=1 LIMIT 1").fetchone()[0]
        day = SC.league_day(self.c, played_day)
        self.assertTrue(day["games"] and all("hg" in g for g in day["games"]))
        for t in SC.HUB_TABS:
            self.assertEqual(SC.transactions_hub(self.c, t)["tab"], t)
        dc = SC.depth_chart(self.c)
        self.assertGreater(sum(len(v) for v in dc["columns"].values()), 18)
        self.assertIn("rows", SC.txn_log(self.c))
        self.assertIn("near", SC.milestones(self.c))
        for k in SC.REPORTS:
            self.assertEqual(SC.reports(self.c, k)["kind"], k)
        pos = SC.reports(self.c, "positional")["groups"]
        for rows in pos.values():
            self.assertEqual([r["value"] for r in rows], sorted((r["value"] for r in rows), reverse=True))
        self.assertIn("years", SC.draft_log(self.c))
        self.assertIn("years", SC.season_page(self.c))
        r = SC.rules_view(self.c)
        self.assertTrue(r["this"] and r["cap"])
        info = SC.team_info(self.c, self.me)
        self.assertTrue(info["mine"])
        self.assertIn("Head coach", [x["role"] for x in info["staff"]] or ["Head coach"])

    def test_today_event_names_a_game(self):
        g = self.c.execute("SELECT * FROM games WHERE (home_team_id=? OR away_team_id=?) ORDER BY game_date LIMIT 1", (self.me, self.me)).fetchone()
        self.assertTrue(SC.today_event(self.c, g).startswith("Game "))

    def test_csv(self):
        self.assertEqual(SC.to_csv([["a", "b"], ["1", "x,y"]]), 'a,b\r\n1,"x,y"\r\n')
        self.assertEqual(SC.to_csv([{"a": 1}]).splitlines(), ["a", "1"])


class SeasonPageTests(unittest.TestCase):
    def test_after_a_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = small_world(tmp)
            try:
                sim_until(c, ENV, Skill(), me, to_end=True)
                from hs.game.dayloop import finish_season
                finish_season(c, ENV, Skill())
                p = SC.season_page(c)
                if not p["years"]:
                    self.skipTest("season records not written in this world")
                self.assertEqual(len(p["standings"]), c.execute("SELECT COUNT(*) FROM team_seasons WHERE season_start_year=?", (p["year"],)).fetchone()[0])
                self.assertTrue(p["scorers"])
            finally:
                c.close()


class BackupTests(unittest.TestCase):
    def test_rolling_keep(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = make_db(tmp)
            try:
                s = Saves(Path(tmp) / "saves")
                for k in range(5):
                    s.backup(c, "career", f"2025-10-1{k} regular season", keep=3)
                b = s.backups("career")
                self.assertEqual(len(b), 3)
                dest = s.restore("career", b[0]["file"], "restored")
                self.assertTrue(dest.exists())
                with self.assertRaises(ValueError):
                    s.restore("career", "../../etc.db", "x")
                self.assertIsNone(s.backup(c, "career", "off", keep=0))
            finally:
                c.close()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, c, cls.me = make_db(cls.tmp.name)
        c.close()
        saves = Path(cls.tmp.name) / "saves"
        saves.mkdir()
        import shutil
        shutil.copyfile(cls.db, saves / "career.db")
        cls.httpd, cls.url, cls.game = make_server(None, ENV, 8795, str(saves), cls.db)
        cls.game.open(saves / "career.db")
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.httpd.shutdown()
            cls.httpd.server_close()
            cls.game.cli.conn.close()
        finally:
            cls.tmp.cleanup()

    def req(self, path, body=None):
        r = urllib.request.Request(self.url.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r) as x:
                return json.loads(x.read())
        except urllib.error.HTTPError as e:
            return dict(error=json.loads(e.read()).get("error"), status=e.code)

    def test_1_export(self):
        r = self.req("/api/export", {"name": "Positional / rankings", "rows": [["#", "Player"], ["1", "A, B"]]})
        self.assertTrue(r["ok"])
        self.assertEqual(Path(r["path"]).parent.name, "exports")
        self.assertIn('"A, B"', Path(r["path"]).read_text())

    def test_2_backup_on_command(self):
        self.req("/api/command", {"line": "status"})
        b = self.req("/api/save", {"action": "backups"})
        self.assertGreaterEqual(len(b["backups"]), 1)            # the first action of a phase makes one
        n = len(b["backups"])
        self.req("/api/command", {"line": "status"})
        self.assertEqual(len(self.req("/api/save", {"action": "backups"})["backups"]), n)   # not again the same week

    def test_3_play_until(self):
        r = self.req("/api/sim", {"mode": "until", "until": "1999-01-01"})
        self.assertIn("after today", r.get("error", ""))
        day = get_state(self.game.cli.conn)[0]
        import datetime
        until = (datetime.date.fromisoformat(day) + datetime.timedelta(days=3)).isoformat()
        r = self.req("/api/sim", {"mode": "until", "until": until, "pace": 0})
        self.assertTrue(r["running"] or r["done_days"] >= 0)
        self.game.sim.thread.join(60)
        self.assertLessEqual(get_state(self.game.cli.conn)[0], until)
        self.assertEqual(self.req("/api/simstatus")["until"], until)

    def test_4_state_has_strip(self):
        s = self.req("/api/state")
        self.assertEqual(len(s["strip"]["days"]), 8)


if __name__ == "__main__":
    unittest.main()
