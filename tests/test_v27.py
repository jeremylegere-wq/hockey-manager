"""v27: the record book (team seasons, awards), lower-league scoring, the press room, captaincy, the live draft room,
the free-agency war room, the GM profile and game setup."""
import json
import tempfile
import unittest

from hs.game import captaincy as CAP
from hs.game import draft as D
from hs.game import free_agency as FA
from hs.game import gm as GM
from hs.game import history as H
from hs.game import press as P
from hs.game import world as W
from hs.game.state import season_state
from hs.game.dayloop import sim_until
from hs.game.state import connect, get_state
from hs.ui import api
from hs.ui import stats as ST
from hs.ui.saves import Saves
from hs.ui.server import Game

from test_game import make_db
from hs.sim.engine import Skill
from test_sim import ENV


class Season(unittest.TestCase):
    """One full season, then the offseason phase by phase (shared by the tests below, which run in name order)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, c, cls.me = make_db(cls.tmp.name)
        sim_until(c, ENV, Skill(), to_end=True)
        c.commit()
        c.close()
        cls.game = Game(cls.db, ENV)                                 # the UI server's game: live draft and war room on
        cls.c = cls.game.cli.conn

    @classmethod
    def tearDownClass(cls):
        cls.game.cli.conn.close()
        cls.tmp.cleanup()

    def cmd(self, line):
        r = self.game.command(line)
        self.assertTrue(r["ok"], r["output"])
        return r["output"]

    def year(self):
        return self.c.execute("SELECT start_year FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]

    # ---- the record book
    def test_1_team_seasons_and_awards(self):
        y = self.year()
        n_top = self.c.execute("SELECT COUNT(*) FROM games WHERE game_type='RS' AND season_id=(SELECT MAX(season_id) FROM seasons)").fetchone()[0]
        self.assertGreater(n_top, 0)
        rows = self.c.execute("SELECT * FROM team_seasons WHERE season_start_year=?", (y,)).fetchall()
        self.assertTrue(rows)
        champs = [r for r in rows if r["playoff_round"] == 5]
        self.assertEqual(len(champs), 1)                              # one champion
        keys = {r["award"] for r in self.c.execute("SELECT award FROM awards WHERE season_start_year=?", (y,))}
        for k in ("art_ross", "hart", "vezina", "norris", "presidents", "conn_smythe"):
            self.assertIn(k, keys)
        h = ST.history(self.c)
        self.assertTrue(h["champions"])
        H.season_end(self.c, self.c.execute("SELECT MAX(season_id) FROM seasons").fetchone()[0], get_state(self.c)[0])
        self.assertEqual(len(self.c.execute("SELECT * FROM team_seasons WHERE season_start_year=?", (y,)).fetchall()), len(rows))

    def test_1_stats_hub_and_team_page(self):
        hub = ST.hub(self.c)
        self.assertTrue(hub["leaders"])
        pts = [x["p"] for x in hub["leaders"]["p"]["rows"]]
        self.assertEqual(pts, sorted(pts, reverse=True))
        self.assertTrue(hub["skaters"] and hub["goalies"])
        tp = ST.team_page(self.c, self.me, self.year())
        self.assertTrue(tp["skaters"])
        x = ST.player_extras(self.c, tp["skaters"][0]["player_id"])
        self.assertIn("career", x)

    def test_1_lower_league_scoring_is_sane(self):
        y = self.year()
        rows = self.c.execute("SELECT s.gp, s.g, s.a, l.abbr FROM skater_season_stats s JOIN leagues l USING (league_id) "
                              "WHERE s.season_start_year=? AND s.split='RS' AND COALESCE(l.level,1)>1 AND s.gp>=20", (y,)).fetchall()
        for r in rows:
            cap = 2.6 if r["abbr"] in ("OHL", "WHL", "QMJHL") else 2.2
            self.assertLessEqual((r["g"] + r["a"]) / r["gp"], cap, dict(r))
            self.assertLessEqual(r["g"] / r["gp"], 1.3, dict(r))
        self.assertTrue(W.LOWER_PPG)

    # ---- the press room
    def test_2_press_answer_and_expiry(self):
        day = get_state(self.c)[0]
        pid = P.schedule(self.c, "availability", day)
        ev = next(e for e in P.pending(self.c) if e["press_id"] == pid)
        qs = json.loads(ev["questions"])
        before = dict(P.media_state(self.c, self.me))
        out = P.answer(self.c, pid, [0] * len(qs))
        self.assertIn("totals", out)
        self.assertNotIn(pid, [e["press_id"] for e in P.pending(self.c)])
        after = dict(P.media_state(self.c, self.me))
        self.assertNotEqual(before, after)
        with self.assertRaises(ValueError):
            P.answer(self.c, pid, [0] * len(qs))                    # once only
        # a skipped one expires quietly (no board hit)
        pid2 = P.schedule(self.c, "availability", "2000-01-01")
        board = self.c.execute("SELECT confidence FROM board WHERE team_id=?", (self.me,)).fetchone()
        self.assertNotIn(pid2, [e["press_id"] for e in P.pending(self.c)])
        self.assertEqual(self.c.execute("SELECT status FROM press_events WHERE press_id=?", (pid2,)).fetchone()[0], "expired")
        self.assertEqual(board, self.c.execute("SELECT confidence FROM board WHERE team_id=?", (self.me,)).fetchone())
        self.c.commit()

    # ---- captaincy
    def test_3_captaincy_names_who_is_replaced(self):
        rk = CAP.room_ranking(self.c, self.me, get_state(self.c)[0])
        cur = {role: pid for pid, role in CAP.current(self.c, self.me).items() if role == "C"}
        new_c = next(p for p, _ in rk if p != cur.get("C"))
        alts = [p for p, _ in rk if p != new_c][:2]
        pv = CAP.preview(self.c, self.me, new_c, alts)
        if cur.get("C") and cur["C"] not in alts:
            self.assertTrue(any(x["player_id"] == cur["C"] and "loses the C" in x["change"] for x in pv["people"]))
        n_press = len(P.pending(self.c))
        CAP.apply(self.c, self.me, new_c, alts)
        self.assertEqual([p for p, r in CAP.current(self.c, self.me).items() if r == "C"], [new_c])
        self.assertTrue(self.c.execute("SELECT 1 FROM league_events WHERE event_type='CAPTAIN_CHANGED' AND team_id=?", (self.me,)).fetchone())
        self.assertGreater(len(P.pending(self.c)), n_press)       # the press want to talk about it
        with self.assertRaises(ValueError):
            CAP.apply(self.c, self.me, new_c, alts)                 # nothing changed
        self.c.commit()

    # ---- the offseason, live
    def test_4_live_draft_and_war_room(self):
        for _ in range(8):
            if season_state(self.c) == "draft":
                break
            self.cmd("offseason")
        self.assertEqual(season_state(self.c), "draft")
        self.assertTrue(D.live_draft(self.c))
        y = D.draft_year(self.c)
        made = lambda: self.c.execute("SELECT COUNT(*) FROM draft_selections WHERE draft_year=?", (y,)).fetchone()[0] \
            if self.c.execute("SELECT 1 FROM sqlite_master WHERE name='draft_selections'").fetchone() else None
        room = D.draft_room(self.c)
        self.assertIn("lottery", json.dumps(room, default=str).lower())
        before = api.draft_view(self.c)
        self.cmd("draftnext 3")
        after = api.draft_view(self.c)
        if before["started"] and not before["done"]:                  # (the example pack may carry no draft class)
            self.assertGreater(len(after["picks"]), len(before["picks"]))   # picks happen one by one, when asked
        for _ in range(6):
            if season_state(self.c) == "free_agency":
                break
            self.cmd("offseason")
        self.assertEqual(season_state(self.c), "free_agency")
        st = FA.live_state(self.c)
        self.assertIsNotNone(st)                                      # the war room is open, nothing signed yet
        wr = api.warroom_view(self.c)
        self.assertTrue(wr.get("open") or wr.get("running"))
        out = self.cmd("faround")
        self.assertIn("signed", out)
        self.cmd("offseason")                                         # leaving the phase runs the rest
        self.assertNotEqual(season_state(self.c), "free_agency")
        self.assertTrue(FA.live_state(self.c) is None or FA.live_state(self.c)["done"])


class SetupTests(unittest.TestCase):
    def test_new_game_with_a_gm_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpl, c, _ = make_db(tmp, name="template.db")
            c.close()
            # the template is a world with no game started: rebuild one
            from hs.ingest import build_db
            from pathlib import Path
            build_db(Path(tmp) / "pack", tpl, overwrite=True)
            s = Saves(Path(tmp) / "saves", tpl)
            self.assertTrue(any(l["playable"] for l in s.leagues()))
            abbr = s.teams()[0]["abbr"]
            self.assertIn(s.teams()[0]["outlook"], ("contender", "bubble", "rebuild"))
            p = s.new_game("Career one", abbr, 3, dict(name="Jeremy", nationality="CAN", background="analytics", age=41))
            c = connect(str(p))
            try:
                prof = GM.profile(c)
                self.assertEqual((prof["name"], prof["background"], prof["age"]), ("Jeremy", "analytics", 41))
                car = GM.career(c)
                self.assertEqual(len(car["stints"]), 1)
                self.assertEqual(car["stints"][0]["abbr"], abbr)
                with self.assertRaises(ValueError):
                    GM.create(c, "X", background="astrologer")
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()
