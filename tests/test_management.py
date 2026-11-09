"""Acceptance scenarios from the GM-simulator spec (section 11), on the fictional example pack."""
import datetime
import io
import json
import random
import statistics
import tempfile
import unittest

from hs.game import draft as D
from hs.game import offseason as O
from hs.game import org
from hs.game import people as P
from hs.game import staff as S
from hs.game.cli import CLI
from hs.game.dayloop import sim_until
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV

DAY = "2026-11-02"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.conn, self.me = make_db(self.tmp.name)
        self.addCleanup(self.conn.close)
        self.other = self.conn.execute("SELECT team_id FROM teams WHERE team_id<>? ORDER BY team_id",
                                       (self.me,)).fetchone()[0]
        self.season_id = self.conn.execute("SELECT season_id FROM seasons").fetchone()[0]

    def set_objectives(self, t, rows, patience=5):
        c = self.conn
        c.execute("UPDATE owners SET patience=? WHERE team_id=?", (patience, t))
        c.execute("DELETE FROM objectives WHERE team_id=?", (t,))
        for cat, code, target, imp in rows:
            c.execute("INSERT INTO objectives (team_id, season_start_year, category, code, description, target, "
                      "importance, deadline_season) VALUES (?,2026,?,?,?,?,?,2026)", (t, cat, code, code, target, imp))

    def review(self, results, young=5):
        real_results, real_young = org.season_results, org.young_games
        org.season_results = lambda conn, sid: results
        org.young_games = lambda conn, t, sid: young
        try:
            return org.season_review(self.conn, "2027-04-20", self.season_id)
        finally:
            org.season_results, org.young_games = real_results, real_young


class BoardTests(Base):
    def test_rebuilding_club_finishing_last_can_stay_in_good_standing(self):
        t = self.other
        self.set_objectives(t, [("competitive", "not_bottom", 3, "preferred"), ("financial", "payroll", 200e6, "required"),
                                ("development", "young_games", 4, "required")])
        before = self.conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]
        self.review({t: dict(points=50, round=0, from_bottom=1, gap=30)})
        after = self.conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]
        self.assertGreaterEqual(after, before - 2)
        self.assertGreaterEqual(after, 50)

    def test_contender_missing_the_playoffs_loses_confidence(self):
        t = self.other
        self.set_objectives(t, [("competitive", "playoff_round", 3, "required"), ("financial", "payroll", 200e6, "preferred"),
                                ("development", "young_games", 2, "preferred")], patience=4)
        before = self.conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]
        self.review({t: dict(points=80, round=0, from_bottom=5, gap=3)})
        after = self.conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]
        self.assertLess(after, before - 5)
        reasons = json.loads(self.conn.execute("SELECT reasons FROM board_history WHERE team_id=? ORDER BY rowid DESC",
                                               (t,)).fetchone()[0])
        self.assertTrue(any("missed" in r for r in reasons))          # explained, not opaque

    def test_repeated_failure_gets_the_user_warned_then_fired(self):
        c, me = self.conn, self.me
        self.set_objectives(me, [("competitive", "playoff_round", 1, "required")], patience=2)
        c.execute("UPDATE board SET confidence=30 WHERE team_id=?", (me,))
        fail = {me: dict(points=40, round=0, from_bottom=1, gap=40)}
        self.review(fail)
        self.assertEqual(c.execute("SELECT warnings FROM board WHERE team_id=?", (me,)).fetchone()[0], 1)
        self.set_objectives(me, [("competitive", "playoff_round", 1, "required")], patience=2)
        self.review(fail)
        self.assertEqual(c.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone()[0], "fired")
        self.assertIn(me, org.vacancies(c))
        org.take_job(c, me, "2027-05-01")                              # rehired elsewhere (here: same club, a vacancy)
        self.assertIsNone(c.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone())

    def test_ai_gm_is_fired_after_a_collapse(self):
        t = self.other
        self.set_objectives(t, [("competitive", "playoff_round", 3, "required")], patience=2)
        self.conn.execute("UPDATE board SET confidence=20 WHERE team_id=?", (t,))
        self.review({t: dict(points=40, round=0, from_bottom=1, gap=40)})
        self.assertTrue(self.conn.execute("SELECT 1 FROM league_events WHERE event_type='GM_FIRED' AND team_id=?",
                                          (t,)).fetchone())


class StaffTests(Base):
    def test_poor_scouts_misjudge_prospects_more(self):
        from hs.game import scouting as SC
        c = self.conn
        c.execute("UPDATE staff SET evaluation=3 WHERE team_id=? AND role IN ('SCOUT','SCOUT_DIR')", (self.me,))
        c.execute("UPDATE staff SET evaluation=18 WHERE team_id=? AND role IN ('SCOUT','SCOUT_DIR')", (self.other,))
        c.execute("UPDATE staff SET style='balanced' WHERE role='SCOUT_DIR'")
        rows = c.execute("SELECT p.player_id, p.position, p.nationality, p.height_cm FROM players p "
                         "WHERE p.status='active' ORDER BY player_id LIMIT 150").fetchall()
        lens = {t: SC.Lens(c, t, 2027) for t in (self.me, self.other)}

        def err(t):
            out = []
            for r in rows:
                seen = lens[t].view(r[0], 10.0, 18, r[1] == "G", r[2], r[3])
                shared = SC.project(10.0, 18, r[1] == "G", SC.exposure_of(c, r[0], r[2]),
                                    random.Random(f"{lens[t].seed}-2027-scout-common-{r[0]}").gauss(0, 1), 0.0, 0.0,
                                    "balanced", r[3], 0)
                out.append(abs(seen - shared))
            return statistics.mean(out)
        self.assertGreater(err(self.me), err(self.other) * 1.5)

    def test_medical_and_development_staff_matter(self):
        c = self.conn
        c.execute("UPDATE staff SET medical=18 WHERE team_id=? AND role='MED'", (self.me,))
        c.execute("UPDATE staff SET medical=4 WHERE team_id=? AND role='MED'", (self.other,))
        self.assertLess(S.injury_multiplier(c, self.me), 1.0)
        self.assertGreater(S.injury_multiplier(c, self.other), 1.0)
        c.execute("UPDATE staff SET development=18 WHERE team_id=?", (self.me,))
        c.execute("UPDATE staff SET development=4 WHERE team_id=?", (self.other,))
        self.assertGreater(S.development_multiplier(c, self.me), S.development_multiplier(c, self.other))

    def test_hire_and_dismiss(self):
        c = self.conn
        hc = S.head_coach(c, self.me)
        with self.assertRaises(ValueError):
            S.hire(c, self.me, c.execute("SELECT staff_id FROM staff WHERE team_id IS NULL AND role='HC'").fetchone()[0],
                   DAY)                                              # one head coach at a time
        S.dismiss(c, self.me, hc["staff_id"], DAY)
        new = c.execute("SELECT staff_id FROM staff WHERE team_id IS NULL AND role='HC' AND staff_id<>?",
                        (hc["staff_id"],)).fetchone()[0]
        S.hire(c, self.me, new, DAY)
        self.assertEqual(S.head_coach(c, self.me)["staff_id"], new)
        self.assertTrue(c.execute("SELECT 1 FROM league_events WHERE event_type='COACH_FIRED'").fetchone())


class LockerRoomTests(Base):
    def concern(self, pid, topic="contract"):
        self.conn.execute("INSERT INTO concerns (player_id, team_id, topic, raised_on, detail, expires_on) VALUES "
                          "(?,?,?,?,?,?)", (pid, self.me, topic, DAY, "test concern", "2027-01-01"))

    def captain(self):
        return self.conn.execute("SELECT player_id FROM leadership WHERE team_id=? AND role='C'", (self.me,)).fetchone()[0]

    def trust(self, pid):
        return self.conn.execute("SELECT trust_mgmt FROM morale WHERE player_id=?", (pid,)).fetchone()[0]

    def test_captain_losing_ice_time_hurts_role_and_coach_trust(self):
        c = self.conn
        sim_until(c, ENV, Skill(), self.me, until_date="2026-11-10", to_end=True)
        cap = self.captain()
        pos = c.execute("SELECT position FROM players WHERE player_id=?", (cap,)).fetchone()[0]
        mate = c.execute("SELECT player_id FROM players WHERE team_id=? AND position=? AND player_id<>? AND "
                         "status='active'", (self.me, pos, cap)).fetchone()[0]
        c.execute("UPDATE personality SET role_tolerance=8, resilience=10 WHERE player_id IN (?,?)", (cap, mate))
        c.execute("UPDATE player_attributes SET passing=17, puck_control=16, offensive_awareness=16, stick_checking=15 "
                  "WHERE player_id=?", (cap,))           # a captain who expects to play
        c.execute("UPDATE morale SET role=65, trust_coach=60 WHERE player_id IN (?,?)", (cap, mate))
        before = dict(c.execute("SELECT * FROM morale WHERE player_id=?", (cap,)).fetchone())
        c.execute("UPDATE player_game_stats SET toi_sec=120 WHERE player_id=?", (cap,))   # buried on the bench
        c.execute("UPDATE player_game_stats SET toi_sec=1500 WHERE player_id=?", (mate,))  # the control plays a lot
        for d in ("2026-11-16", "2026-11-23", "2026-11-30", "2026-12-07"):
            P.weekly(c, d)
        after = dict(c.execute("SELECT * FROM morale WHERE player_id=?", (cap,)).fetchone())
        control = dict(c.execute("SELECT * FROM morale WHERE player_id=?", (mate,)).fetchone())
        self.assertLess(after["role"], before["role"] - 10)
        self.assertLess(after["trust_coach"], control["trust_coach"])
        self.assertLess(after["morale"], control["morale"])

    def test_breaking_a_promise_to_a_leader_spreads(self):
        c = self.conn
        cap = self.captain()
        mate = c.execute("SELECT player_id FROM players WHERE team_id=? AND player_id<>? AND status='active'",
                         (self.me, cap)).fetchone()[0]
        self.concern(cap)
        P.respond(c, self.me, cap, "promise", DAY)
        t_cap, t_mate = self.trust(cap), self.trust(mate)
        coh = c.execute("SELECT cohesion FROM team_room WHERE team_id=?", (self.me,)).fetchone()[0]
        P._promises(c, "2027-01-15")                                    # deadline passed, no extension
        self.assertEqual(c.execute("SELECT status FROM promises").fetchone()[0], "broken")
        self.assertLess(self.trust(cap), t_cap - 10)
        self.assertLess(self.trust(mate), t_mate)
        self.assertLess(c.execute("SELECT cohesion FROM team_room WHERE team_id=?", (self.me,)).fetchone()[0], coh)
        self.assertLess(P.credibility(c, self.me), 1.0)

    def test_keeping_a_promise_builds_trust(self):
        c = self.conn
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' ORDER BY player_id",
                        (self.me,)).fetchone()[0]
        c.execute("UPDATE contracts SET start_year=2025, years=2 WHERE player_id=?", (pid,))   # final year 2026
        self.concern(pid)
        P.respond(c, self.me, pid, "promise", DAY)
        t0 = self.trust(pid)
        from hs.game import contracts as K
        O.extend(c, pid, int(K.asking(c, pid, K.rights_status(c, pid, 2026)) * 1.1), 3, DAY)
        P._promises(c, "2026-11-09")
        self.assertEqual(c.execute("SELECT status FROM promises").fetchone()[0], "fulfilled")
        self.assertGreater(self.trust(pid), t0)

    def test_repeated_reassurance_loses_credibility(self):
        c = self.conn
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active'", (self.me,)).fetchone()[0]
        self.concern(pid, "role")
        changes = []
        for _ in range(3):
            t0 = self.trust(pid)
            P.respond(c, self.me, pid, "supportive", DAY)
            changes.append(self.trust(pid) - t0)
        self.assertGreater(changes[0], 0)
        self.assertLess(changes[2], 0)

    def test_same_words_land_differently_by_personality(self):
        c = self.conn
        pids = [r[0] for r in c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' LIMIT 2",
                                        (self.me,))]
        c.execute("UPDATE personality SET professionalism=17, ego=5 WHERE player_id=?", (pids[0],))
        c.execute("UPDATE personality SET professionalism=6, ego=17, resilience=5 WHERE player_id=?", (pids[1],))
        out = []
        for pid in pids:
            self.concern(pid, "role")
            t0 = self.trust(pid)
            P.respond(c, self.me, pid, "firm", DAY)
            out.append(self.trust(pid) - t0)
        self.assertGreater(out[0], 0)
        self.assertLess(out[1], -3)

    def test_miserable_impatient_player_requests_trade_and_refuses_extension(self):
        c = self.conn
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' ORDER BY player_id DESC",
                        (self.me,)).fetchone()[0]
        c.execute("UPDATE personality SET ambition=18, patience=2, resilience=2, role_tolerance=1, ego=18 "
                  "WHERE player_id=?", (pid,))
        c.execute("UPDATE morale SET role=5, team=10, contract=10, trust_mgmt=10, trust_coach=10, morale=9, "
                  "low_weeks=3 WHERE player_id=?", (pid,))
        sim_until(c, ENV, Skill(), self.me, until_date="2026-10-20", to_end=True)
        c.execute("UPDATE player_game_stats SET toi_sec=60 WHERE player_id=?", (pid,))
        P.weekly(c, "2026-10-26")
        self.assertEqual(c.execute("SELECT trade_request FROM morale WHERE player_id=?", (pid,)).fetchone()[0], 1)
        self.assertTrue(c.execute("SELECT 1 FROM league_events WHERE event_type='TRADE_REQUEST' AND player_id=?",
                                  (pid,)).fetchone())
        c.execute("UPDATE contracts SET start_year=2025, years=2 WHERE player_id=?", (pid,))
        from hs.game.roster import RosterError
        with self.assertRaises(RosterError):
            O.extend(c, pid, 9_000_000, 2, DAY)

    def test_cohesion_is_not_just_winning(self):
        c = self.conn
        sim_until(c, ENV, Skill(), self.me, until_date="2026-11-10", to_end=True)
        c.execute("UPDATE personality SET ego=17, professionalism=5 WHERE player_id IN (SELECT player_id FROM players "
                  "WHERE team_id=?)", (self.me,))
        c.execute("UPDATE morale SET role=20, contract=20, trust_mgmt=20, trust_coach=20, morale=25 WHERE player_id IN "
                  "(SELECT player_id FROM players WHERE team_id=?)", (self.me,))
        c.execute("UPDATE games SET home_goals=9, away_goals=0 WHERE home_team_id=? AND played=1", (self.me,))
        c.execute("UPDATE games SET away_goals=9, home_goals=0 WHERE away_team_id=? AND played=1", (self.me,))
        for d in ("2026-11-16", "2026-11-23", "2026-11-30"):
            P.weekly(c, d)
        self.assertLess(c.execute("SELECT cohesion FROM team_room WHERE team_id=?", (self.me,)).fetchone()[0], 45)


class HistoryAndDashboardTests(Base):
    def test_cli_management_commands(self):
        sim_until(self.conn, ENV, Skill(), self.me, until_date="2026-11-10", to_end=True)
        self.conn.commit()
        buf = io.StringIO()
        cli = CLI(self.db, ENV, out=buf)
        for cmd in ["dashboard", "board", "staff", "staffmarket HC", "lockerroom", "history", "history league",
                    "promises all", "jobs"]:
            cli.onecmd(cmd)
        self.assertEqual(cli.status_code, 0, buf.getvalue())
        out = buf.getvalue()
        for word in ("Board", "Locker room", "Head coach", "Atmosphere"):
            self.assertIn(word, out)
        cli.conn.close()

    def test_events_are_written_for_core_actions(self):
        c = self.conn
        sim_until(c, ENV, Skill(), self.me, to_end=True)
        types = {r[0] for r in c.execute("SELECT DISTINCT event_type FROM league_events")}
        for t in ("CHAMPIONSHIP", "BOARD_REVIEW", "OBJECTIVES_SET"):
            self.assertIn(t, types)


if __name__ == "__main__":
    unittest.main()
