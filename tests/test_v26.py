"""v26: contract talks, the sim centre job, save slots, wild-card standings, the inbox and news archive views,
analytics, three-team trade evaluation through the UI API."""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from hs.game import negotiation as N
from hs.game import contracts as K
from hs.game.state import connect, get_state
from hs.ui import analytics as AN
from hs.ui import api
from hs.ui.saves import Saves
from hs.ui.server import Game

from test_game import make_db
from test_sim import ENV


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, c, cls.me = make_db(cls.tmp.name)
        c.close()
        cls.game = Game(cls.db, ENV)
        cls.game.command("sim week")
        cls.c = cls.game.cli.conn

    @classmethod
    def tearDownClass(cls):
        cls.game.cli.conn.close()
        cls.tmp.cleanup()


class TalksTests(Base):
    def _expiring(self):
        year = K.season_year(self.c)
        r = self.c.execute("SELECT p.player_id FROM players p JOIN contracts k USING (player_id) WHERE p.team_id=? AND "
                           "p.status='active' AND k.start_year+k.years-1=? AND p.player_id NOT IN (SELECT player_id FROM "
                           "contracts WHERE start_year>?) ORDER BY p.player_id", (self.me, year, year)).fetchall()
        for (pid,) in r:
            v = N.view(self.c, pid)
            if not v.get("blocked"):
                return pid
        self.skipTest("no expiring player who can be extended")

    def test_open_counter_and_agree(self):
        pid = self._expiring()
        v = N.open_talks(self.c, pid)
        self.assertTrue(v["open"])
        self.assertEqual(v["agent"], N.agent_of(pid))                     # the same agent every time
        pref = v["pref_years"]
        ask = v["asks"][pref]
        out, v2 = N.offer(self.c, pid, int(ask * 0.6), pref)               # far too low: insulted, no movement
        self.assertEqual(out, "counter")
        self.assertEqual(v2["patience"], v["patience"] - 2)
        self.assertLess(v2["mood"], v["mood"])
        out, v3 = N.offer(self.c, pid, int(v2["asks"][pref]) + 5000, pref)  # his ask: agreed and signed
        self.assertEqual(out, "agreed")
        c = K.last_contract(self.c, pid)
        self.assertEqual(c["years"], pref)
        self.assertGreater(c["start_year"], K.season_year(self.c) - 1)
        self.c.rollback()

    def test_patience_runs_out(self):
        pid = self._expiring()
        N.open_talks(self.c, pid)
        out = None
        for _ in range(8):
            out, v = N.offer(self.c, pid, K.crules(self.c)["min_salary"], 1)
            if out == "broken":
                break
        self.assertEqual(out, "broken")
        self.assertIsNotNone(v["cooldown_until"])
        from hs.game.roster import RosterError
        with self.assertRaises(RosterError):
            N.open_talks(self.c, pid)
        self.c.rollback()

    def test_never_below_the_signing_rules(self):
        pid = self._expiring()
        from hs.game import offseason as O
        v = N.open_talks(self.c, pid)
        for y in range(1, v["max_term"] + 1):
            fl, base = N.floor(self.c, pid, "extend", y, True, True)
            self.assertGreaterEqual(fl, 0.95 * O.extension_floor(self.c, pid, y))
        self.c.rollback()

    def test_cli_commands(self):
        pid = self._expiring()
        r = self.game.command(f"negotiate {pid}")
        self.assertTrue(r["ok"], r)
        self.assertIn("agent", r["output"])
        r = self.game.command(f"endtalks {pid}")
        self.assertTrue(r["ok"], r)


class ViewTests(Base):
    def test_standings_wildcard_and_marks(self):
        d = api.standings_full(self.c, "wildcard")
        teams = [r for g in d["groups"] for s in g["sections"] for r in s["rows"]]
        self.assertEqual(len({r["team_id"] for r in teams}), len(teams))
        for r in teams:
            self.assertIn(r["clinch"], ("", "x", "y", "z", "p", "e"))
            self.assertRegex(r["l10"], r"^\d+-\d+-\d+$")
        dv = api.standings_full(self.c, "division")
        self.assertTrue(all(s["cut"] in (None, d["per_division"]) for g in dv["groups"] for s in g["sections"]))

    def test_inbox_folders_add_up(self):
        if not self.c.execute("SELECT 1 FROM inbox").fetchone():      # a quiet week: give the inbox one message
            from hs.game.state import add_message, get_state
            add_message(self.c, get_state(self.c)[0], "Scouting report", "A quiet week.")
            self.c.commit()
        d = api.inbox_view(self.c)
        counts = {f["key"]: f["count"] for f in d["folders"]}
        self.assertEqual(counts["all"], sum(v for k, v in counts.items() if k not in ("all", "unread")))
        mid = d["messages"][0]["msg_id"]
        self.game.command(f"read {mid}")
        self.assertEqual(self.c.execute("SELECT read FROM inbox WHERE msg_id=?", (mid,)).fetchone()[0], 1)
        self.game.command(f"read {mid} unread")
        self.assertEqual(self.c.execute("SELECT read FROM inbox WHERE msg_id=?", (mid,)).fetchone()[0], 0)

    def test_news_history_pages(self):
        a = api.news_history(self.c, "signings", "league", None, 0)
        self.assertLessEqual(len(a["items"]), 40)
        if a["total"] > 40:
            b = api.news_history(self.c, "signings", "league", None, 40)
            self.assertNotEqual(a["items"][0], b["items"][0])

    def test_analytics(self):
        rows = AN.team_table(self.c)
        self.assertTrue(rows)
        tot = sum(r["gp"] for r in rows)
        self.assertGreater(tot, 0)
        self.assertAlmostEqual(sum(r["cf"] for r in rows), sum(r["ca"] for r in rows))
        odds = AN.playoff_odds(self.c, sims=200)
        self.assertTrue(all(0 <= r["playoffs"] <= 100 for r in odds["rows"]))
        for tab in ("teams", "team", "players", "contracts"):
            AN.view(self.c, tab)

    def test_card_and_three_team_eval(self):
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? LIMIT 1", (self.me,)).fetchone()[0]
        self.assertEqual(api.player_card(self.c, pid)["player_id"], pid)
        a, b = [r[0] for r in self.c.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1 ORDER BY team_id "
                                             "LIMIT 2", (self.me,))]
        mine = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' ORDER BY player_id DESC "
                              "LIMIT 1", (self.me,)).fetchone()[0]
        pa = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' ORDER BY player_id DESC "
                            "LIMIT 1", (a,)).fetchone()[0]
        pb = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' ORDER BY player_id DESC "
                            "LIMIT 1", (b,)).fetchone()[0]
        e = api.trade_eval3(self.c, a, b, f"player:{mine}>{a},player:{pa}>{b},player:{pb}>me")
        self.assertEqual(set(e["clubs"]), {str(a), str(b)})


class SimJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, c, self.me = make_db(self.tmp.name)
        c.close()
        self.game = Game(self.db, ENV)
        self.addCleanup(lambda: self.game.cli.conn.close())

    def wait(self):
        for _ in range(600):
            if not self.game.sim.running:
                return
            time.sleep(0.05)
        self.fail("sim did not finish")

    def test_week_runs_day_by_day(self):
        before = get_state(self.game.cli.conn)[0]
        self.game.sim.start("week", pace=0)
        self.assertFalse(self.game.command("sim day")["ok"])      # no commands while it runs
        self.wait()
        st = self.game.sim.status(0)
        self.assertIsNone(st["error"])
        self.assertGreaterEqual(len(st["feed"]), 1)
        self.assertLessEqual(st["done_days"], 7)
        self.assertNotEqual(get_state(self.game.cli.conn)[0], before)
        d = st["feed"][-1]
        self.assertIn("scores", d)
        if any(x["mine"] for x in d["scores"]):
            self.assertIsNotNone(d["mine"])
        self.assertEqual(self.game.sim.status(st["next"])["feed"], [])

    def test_stop(self):
        self.game.sim.start("season", pace=0.05)
        time.sleep(0.6)
        self.game.sim.stop()
        self.wait()
        st = self.game.sim.status(0)
        self.assertTrue(st["stopped"])
        self.assertFalse(st["finished"])
        self.assertEqual(K.season_state(self.game.cli.conn), "regular_season")


class SavesTests(unittest.TestCase):
    def test_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            from hs.ingest import build_db
            from hs.tools.make_example_pack import generate
            pack = Path(tmp) / "pack"
            generate(pack)
            tpl = Path(tmp) / "template.db"
            build_db(pack, str(tpl), overwrite=True)
            g = Game(None, ENV, saves=Path(tmp) / "saves", template=tpl)
            self.assertFalse(g.view("state", {})["loaded"])
            team = g.saves.teams()[0]["abbr"]
            g.save_action(dict(action="new", team=team, name="First"))
            self.assertEqual(g.view("state", {})["abbr"], team)
            g.command("sim day")
            g.save_action(dict(action="saveas", name="Copy"))
            names = {s["name"] for s in g.saves_list()["saves"]}
            self.assertEqual(names, {"First", "Copy"})
            with self.assertRaises(ValueError):
                g.save_action(dict(action="delete", name="First"))      # it is open
            g.save_action(dict(action="load", name="Copy"))
            g.save_action(dict(action="rename", name="First", to="Original"))
            g.save_action(dict(action="delete", name="Original"))
            self.assertEqual({s["name"] for s in g.saves_list()["saves"]}, {"Copy"})
            self.assertEqual(g.saves.path("../escape").parent, (Path(tmp) / "saves").resolve())   # names are cleaned
            with self.assertRaises(ValueError):
                g.saves.path("///")
            g.save_action(dict(action="close"))
            self.assertFalse(g.view("state", {})["loaded"])


if __name__ == "__main__":
    unittest.main()
