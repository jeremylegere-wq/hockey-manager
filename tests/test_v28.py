"""v28: the desktop shell (settings, app endpoints, the launcher's choices) and the new screens' views."""
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from hs import app as A
from hs.ui import api
from hs.ui import settings as SET
from hs.ui.server import make_server

from test_game import make_db
from test_sim import ENV


class SettingsTests(unittest.TestCase):
    def test_clean_clamps_and_drops(self):
        s = SET._clean({"ui_scale": 400, "units": "furlongs", "intro": 0, "nonsense": 1, "sim_pace": "x"})
        self.assertEqual(s["ui_scale"], 150)
        self.assertEqual(s["units"], "metric")
        self.assertIs(s["intro"], False)
        self.assertNotIn("nonsense", s)
        self.assertEqual(s["sim_pace"], SET.DEFAULTS["sim_pace"])

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            self.assertEqual(SET.load(p), SET.DEFAULTS)                 # no file: defaults
            SET.save(p, {"ui_scale": 125, "units": "imperial"})
            self.assertEqual((SET.load(p)["ui_scale"], SET.load(p)["units"]), (125, "imperial"))
            p.write_text("{broken")
            self.assertEqual(SET.load(p), SET.DEFAULTS)                 # a broken file never breaks the UI


class LauncherTests(unittest.TestCase):
    def test_choices(self):
        self.assertIn(A.webview_package()[0].split("[")[0], ("pywebview",))
        b = A.find_app_browser()
        self.assertTrue(b is None or Path(b).name)
        self.assertTrue(str(A.runtime_python()).startswith(str(A.RUNTIME)))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, c, cls.me = make_db(cls.tmp.name)
        c.close()
        saves = Path(cls.tmp.name) / "saves"
        cls.httpd, cls.url, cls.game = make_server(None, ENV, 8790, str(saves), cls.db)
        cls.game.open(cls.db)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.httpd.server_close()
            cls.game.cli.conn.close()
        finally:
            cls.tmp.cleanup()

    def req(self, path, body=None):
        r = urllib.request.Request(self.url.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r) as x:
            return json.loads(x.read())

    def test_1_settings_and_app(self):
        self.assertEqual(self.req("/api/settings")["ui_scale"], 100)
        self.assertEqual(self.req("/api/settings", {"ui_scale": 110})["ui_scale"], 110)
        self.assertTrue((self.game.saves.folder / "settings.json").exists())
        a = self.req("/api/app")
        self.assertFalse(a["desktop"])
        self.assertTrue(self.req("/api/title", {"title": "x"})["ok"])

    def test_2_new_views(self):
        c = self.game.cli.conn
        cal = api.calendar_view(c)
        n = c.execute("SELECT COUNT(*) FROM games WHERE season_id=(SELECT MAX(season_id) FROM seasons) AND (home_team_id=? OR away_team_id=?)",
                      (self.me, self.me)).fetchone()[0]
        self.assertEqual(len(cal["games"]), n)
        self.assertIn(cal["month"], cal["months"])
        fa = api.freeagents_view(c)
        self.assertIn("cap_room", fa)
        self.assertTrue(all(p["ask"] is None or p["ask"] > 0 for p in fa["players"]))
        pr = api.prospects_view(c)
        self.assertIn("rights", pr)
        dv = api.development_view(c)
        self.assertTrue(dv["players"])
        name = c.execute("SELECT last_name FROM players WHERE team_id=? LIMIT 1", (self.me,)).fetchone()[0]
        self.assertTrue(any(name in p["name"] for p in api.search_view(c, name)["players"]))
        self.assertEqual(api.search_view(c, "a"), dict(players=[], teams=[]))

    def test_3_quit_stops_a_plain_server(self):
        self.assertTrue(self.req("/api/quit", {})["ok"])
        import time
        for _ in range(50):
            time.sleep(0.1)
            try:
                urllib.request.urlopen(self.url + "api/app", timeout=0.3)
            except Exception:
                break
        else:
            self.fail("server still answering after quit")


if __name__ == "__main__":
    unittest.main()
