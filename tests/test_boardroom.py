"""The boardroom: trigger score, ultimatums, leaks by vocalness, directives, the coach as scapegoat."""
import datetime
import json
import tempfile
import unittest

from hs.game import boardroom as BR
from hs.game import org
from hs.game import staff as S
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, c, cls.me = make_db(cls.tmp.name)
        sid = c.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
        BR.ensure_tables(c)
        for _ in range(40):                                    # enough games for the board to act (sim stops early
            if BR._record(c, cls.me, sid)[0] >= 25:            # whenever the user is needed)
                break
            sim_until(c, ENV, Skill(), days=10)
        c.commit()
        c.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from hs.game.state import connect
        self.c = connect(self.db)
        self.addCleanup(self.c.close)
        self.addCleanup(self.c.rollback)
        BR.ensure_tables(self.c)
        self.day = get_state(self.c)[0]
        self.sid = self.c.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
        self.other = self.c.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1 ORDER BY team_id",
                                    (self.me,)).fetchone()[0]

    def owner(self, t, **kw):
        sets = ", ".join(f"{k}=?" for k in kw)
        self.c.execute(f"UPDATE owners SET {sets} WHERE team_id=?", (*kw.values(), t))
        return BR.owner(self.c, t)

    def conf(self, t, value, weeks_ago=None):
        if weeks_ago is not None:
            then = (datetime.date.fromisoformat(self.day) - datetime.timedelta(days=7 * weeks_ago)).isoformat()
            self.c.execute("INSERT INTO board_history VALUES (?,?,?,?,?,?)", (t, then, "test", weeks_ago, 0, "[]"))
        self.c.execute("UPDATE board SET confidence=? WHERE team_id=?", (value, t))


class TriggerTests(Base):
    def test_formula(self):
        o = self.owner(self.me, patience=2, vocalness=0.9)
        self.c.execute("INSERT INTO board_history VALUES (?,?,?,?,?,?)", (self.me, "2000-01-01", "test", 60, 0, "[]"))
        self.conf(self.me, 60, weeks_ago=5)
        self.c.execute("UPDATE board_history SET confidence=60 WHERE team_id=? AND kind='test'", (self.me,))
        self.conf(self.me, 40)
        tr = BR.trigger(self.c, self.me, self.day, self.sid)
        v = -0.20
        expect = 0.40 + v * (1.1 - 0.2) - tr["pressure"] * 0.9
        self.assertAlmostEqual(tr["velocity"], v, places=2)
        self.assertAlmostEqual(tr["T"], expect, places=2)
        # a patient owner weighs the same slide far less
        self.owner(self.me, patience=9)
        self.assertGreater(BR.trigger(self.c, self.me, self.day, self.sid)["T"], tr["T"])

    def test_pressure_follows_market_and_form(self):
        p = BR.pressure(self.c, self.me, self.sid)
        self.assertTrue(0 < p <= 0.40)


class UltimatumTests(Base):
    def test_ultimatum_issued_then_fired(self):
        self.owner(self.me, patience=2, vocalness=0.9, involvement=8, archetype="The Impatient Tyrant",
                   name="Victor Ashcombe")
        self.conf(self.me, 15)
        BR.evaluate(self.c, self.me, self.day, self.sid)
        u = BR.open_ultimatum(self.c, self.me)
        self.assertIsNotNone(u)
        self.assertEqual(u["games"], 3)
        self.assertEqual(u["points_needed"], 4)                         # ceil(2 x 3 x 0.60)
        msg = self.c.execute("SELECT body FROM inbox WHERE subject LIKE 'URGENT%' ORDER BY msg_id DESC").fetchone()[0]
        self.assertIn("Victor Ashcombe", msg)
        self.assertIn("exactly 3 games", msg)
        leak = self.c.execute("SELECT summary, payload FROM league_events WHERE event_type='RUMOUR' AND team_id=? "
                              "ORDER BY event_id DESC", (self.me,)).fetchone()
        self.assertIn("3-game window", leak[0])                        # vocal owner: specific
        self.assertTrue(json.loads(leak[1])["specific"])
        # three games, no points
        real = BR._record
        BR._record = lambda conn, t, sid: (u["gp_at_issue"] + 3, u["pts_at_issue"]) if t == self.me else real(conn, t, sid)
        self.addCleanup(setattr, BR, "_record", real)
        BR.daily(self.c, self.day)
        self.assertEqual(self.c.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone()[0], "fired")
        self.assertIn(self.me, org.vacancies(self.c))

    def test_meeting_it_lifts_the_warning(self):
        self.owner(self.me, patience=5, vocalness=0.5)
        self.conf(self.me, 10)
        BR.evaluate(self.c, self.me, self.day, self.sid)
        u = BR.open_ultimatum(self.c, self.me)
        self.assertEqual(u["games"], 5)
        real = BR._record
        BR._record = lambda conn, t, sid: (u["gp_at_issue"] + 4, u["pts_at_issue"] + u["points_needed"]) \
            if t == self.me else real(conn, t, sid)
        self.addCleanup(setattr, BR, "_record", real)
        before = BR._conf(self.c, self.me)
        BR.daily(self.c, self.day)
        self.assertIsNone(BR.open_ultimatum(self.c, self.me))
        self.assertGreater(BR._conf(self.c, self.me), before)
        self.assertEqual(self.c.execute("SELECT warnings FROM board WHERE team_id=?", (self.me,)).fetchone()[0], 0)

    def test_silent_owner_fires_without_warning_to_the_media(self):
        t = self.other
        self.owner(t, patience=2, vocalness=0.1, involvement=1)
        self.conf(t, 5)
        BR.evaluate(self.c, t, self.day, self.sid)
        self.assertFalse(self.c.execute("SELECT 1 FROM league_events WHERE event_type='RUMOUR' AND team_id=?",
                                        (t,)).fetchone())
        u = BR.open_ultimatum(self.c, t)
        self.assertIsNotNone(u)
        real = BR._record
        BR._record = lambda conn, tt, sid: (u["gp_at_issue"] + 5, u["pts_at_issue"]) if tt == t else real(conn, tt, sid)
        self.addCleanup(setattr, BR, "_record", real)
        self.c.execute("DELETE FROM staff WHERE team_id=? AND role='HC'", (t,))      # no coach to sacrifice
        BR.daily(self.c, self.day)
        ev = self.c.execute("SELECT summary, payload FROM league_events WHERE event_type='GM_FIRED' AND team_id=? "
                            "ORDER BY event_id DESC", (t,)).fetchone()
        self.assertTrue(ev[0].startswith("Stunner"))
        self.assertTrue(json.loads(ev[1])["surprise"])

    def test_ai_fires_the_coach_first(self):
        t = self.other
        self.owner(t, patience=2, vocalness=0.5, involvement=8)
        hc = S.head_coach(self.c, t)
        self.assertIsNotNone(hc)
        self.c.execute("DELETE FROM league_events WHERE event_type='STAFF_HIRED' AND staff_id=?", (hc["staff_id"],))
        self.conf(t, 20)
        out = BR.evaluate(self.c, t, self.day, self.sid)
        self.assertTrue(any("head coach" in x for x in out))
        self.assertNotEqual(S.head_coach(self.c, t)["staff_id"], hc["staff_id"])

    def test_user_firing_the_coach_buys_three_games(self):
        self.owner(self.me, patience=2, vocalness=0.5)
        self.conf(self.me, 10)
        BR.evaluate(self.c, self.me, self.day, self.sid)
        u = BR.open_ultimatum(self.c, self.me)
        hc = S.head_coach(self.c, self.me)
        S.dismiss(self.c, self.me, hc["staff_id"], self.day)
        self.assertEqual(BR.open_ultimatum(self.c, self.me)["games"], u["games"] + 3)
        S.dismiss(self.c, self.me, S.members(self.c, self.me, "AC")[0]["staff_id"], self.day)   # only the head coach
        self.assertEqual(BR.open_ultimatum(self.c, self.me)["games"], u["games"] + 3)


class DirectiveTests(Base):
    def test_failed_directive_costs_by_traits_and_reevaluates(self):
        self.owner(self.me, patience=2, involvement=10, vocalness=0.5)
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? LIMIT 1", (self.me,)).fetchone()[0]
        self.c.execute("DELETE FROM directives")
        self.c.execute("INSERT INTO directives (team_id, season, code, description, target, issued, deadline) VALUES "
                       "(?,?,?,?,?,?,?)", (self.me, org.season_year(self.c), "move_veteran", "Move his contract",
                                           json.dumps(dict(player_id=pid)), self.day, self.day))
        self.conf(self.me, 30)
        before = BR._conf(self.c, self.me)
        BR.daily(self.c, self.day)
        expected = BR.DIRECTIVE_LOSS * (1.2 - 0.2) * (1 + 10 / 20)
        self.assertAlmostEqual(before - BR._conf(self.c, self.me), expected, places=1)
        self.assertEqual(self.c.execute("SELECT status FROM directives").fetchone()[0], "failed")
        self.assertIsNotNone(BR.open_ultimatum(self.c, self.me))       # the drop brought the ultimatum at once

    def test_met_directive(self):
        self.owner(self.me, patience=5, involvement=5)
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? LIMIT 1", (self.me,)).fetchone()[0]
        self.c.execute("DELETE FROM directives")
        self.c.execute("INSERT INTO directives (team_id, season, code, description, target, issued, deadline) VALUES "
                       "(?,?,?,?,?,?,?)", (self.me, org.season_year(self.c), "move_veteran", "Move his contract",
                                           json.dumps(dict(player_id=pid)), self.day, "2099-01-01"))
        self.c.execute("UPDATE players SET team_id=? WHERE player_id=?", (self.other, pid))
        BR.daily(self.c, self.day)
        self.assertEqual(self.c.execute("SELECT status FROM directives").fetchone()[0], "met")


if __name__ == "__main__":
    unittest.main()
