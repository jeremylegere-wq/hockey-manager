"""The local web UI: every JSON view answers, and actions run through the same CLI rules."""
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from hs.ui.server import Game, VIEWS, make_handler

from test_game import make_db
from test_sim import ENV


class UITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, conn, cls.me = make_db(cls.tmp.name)
        cls.pid = conn.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position<>'G' "
                               "ORDER BY player_id LIMIT 1", (cls.me,)).fetchone()[0]
        conn.close()
        cls.game = Game(cls.db, ENV)
        cls.other = cls.game.cli.conn.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1 LIMIT 1",
                                              (cls.me,)).fetchone()[0]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.game))
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.game.cli.conn.close()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as r:
            return r.status, r.read()

    def post(self, line):
        req = urllib.request.Request(self.url + "/api/command", data=json.dumps(dict(line=line)).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_static_files(self):
        for path in ("/", "/app.js", "/replay.js", "/style.css", "/classic.js", "/classic.css"):
            code, body = self.get(path)
            self.assertEqual(code, 200)
            self.assertTrue(body)
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/../server.py")

    def test_every_view_answers_from_handler_threads(self):
        self.game.command("sim day")
        gid = self.game.cli.conn.execute("SELECT game_id FROM games WHERE played=1 LIMIT 1").fetchone()[0]
        params = {"player": f"?id={self.pid}", "roster": "?system=1", "history": "?scope=league", "inbox": "?all=1",
                  "game": f"?id={gid}", "track": f"?id={gid}", "news": "?scope=league", "trade": f"?team={self.other}",
                  "tradeeval": f"?team={self.other}&give=&get=", "tradeask": f"?team={self.other}&get=",
                  "tradeeval3": f"?a={self.other}&b={self.other}&legs=", "card": f"?id={self.pid}",
                  "negotiation": f"?id={self.pid}", "standings2": "?mode=division", "inbox2": "?folder=unread",
                  "newsfeed": "?kind=trades", "analytics": "?tab=team", "team": f"?id={self.other}",
                  "playerx": f"?id={self.pid}", "captaincy": f"?c={self.pid}", "search": "?q=an", "teaminfo": f"?id={self.other}", "playermarks": f"?id={self.pid}", "people": f"?id={self.pid}", "devchart": f"?id={self.pid}", "exbox": "?id=0", "devlog": f"?id={self.pid}", "article": f"?id={self.game.cli.conn.execute('SELECT MAX(event_id) FROM league_events').fetchone()[0]}"}
        for name in VIEWS:
            code, body = self.get(f"/api/{name}{params.get(name, '')}")
            self.assertEqual(code, 200, name)
            json.loads(body)
        state = json.loads(self.get("/api/state")[1])
        self.assertTrue(state["started"])
        self.assertEqual(state["team_id"], self.me)

    def test_actions_go_through_the_cli(self):
        before = json.loads(self.get("/api/state")[1])["date"]
        r = self.post("sim day")
        self.assertTrue(r["ok"], r)
        self.assertNotEqual(json.loads(self.get("/api/state")[1])["date"], before)
        bad = self.post("frobnicate")
        self.assertFalse(bad["ok"])
        self.assertIn("Unknown command", bad["output"])
        err = self.post("recall 999999999")
        self.assertFalse(err["ok"])


if __name__ == "__main__":
    unittest.main()
