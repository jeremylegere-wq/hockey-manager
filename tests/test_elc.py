"""Entry-level contracts (bonuses, slide rule), college picks refusing to sign, offer-sheet failures, the
arbitrator's box-score lens."""
import datetime
import tempfile
import unittest

from hs.game import arbitration as A
from hs.game import contracts as K
from hs.game import draft as D
from hs.game import elc as E
from hs.game import offer_sheets as OS
from hs.game import roster as R
from hs.game.state import get_state

from test_game import make_db
from test_world import small_world


def _birth_for_age(year, age):
    return f"{year - age}-03-01"


class ElcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        E.ensure_tables(self.c)
        self.year = K.season_year(self.c)
        self.league = self.c.execute("SELECT league_id FROM seasons WHERE start_year=?", (self.year,)).fetchone()[0]

    def _elc(self, pos, age, perf=E.PERF_MAX):
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position LIKE ? LIMIT 1",
                             (self.me, pos + "%")).fetchone()[0]
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (_birth_for_age(self.year, age), pid))
        self.c.execute("DELETE FROM contracts WHERE player_id=?", (pid,))
        self.c.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type) VALUES "
                       "(?,?,?,3,950000,'entry_level')", (pid, self.me, self.year))
        E.record(self.c, pid, self.year, 95_000, perf, "")
        self.c.execute("DELETE FROM skater_season_stats WHERE player_id=? AND season_start_year=?", (pid, self.year))
        return pid

    def _stats(self, pid, gp, g, a, toi=0):
        self.c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, "
                       "g, a, toi_sec) VALUES (?,?,?,?, 'RS', ?,?,?,?)", (pid, self.year, self.me, self.league, gp, g,
                                                                         a, toi))

    def test_negotiation_by_slot(self):
        top = [E.negotiate(self.c, 1, 3, 1_000_000, 3, rng=__import__("random").Random(i)) for i in range(50)]
        late = [E.negotiate(self.c, 1, 150, 800_000, 3, rng=__import__("random").Random(i)) for i in range(50)]
        self.assertTrue(all(p == E.PERF_MAX for _, p, _ in top))
        self.assertTrue(all(p == 0 for _, p, _ in late))
        self.assertGreater(sum(b for b, _, _ in top), sum(b for b, _, _ in late))
        self.assertTrue(all(b <= 100_000 for b, _, _ in top))               # at most 10% of pay

    def test_performance_bonus_earned_in_parts(self):
        pid = self._elc("C", 21)
        self._stats(pid, 82, 24, 30)                           # 20 goals yes, 35 assists no, 60 points no, 0.66/gp no
        E.season_end(self.c, self.year, "2026-04-20")
        earned = self.c.execute("SELECT earned FROM elc_bonus_log WHERE player_id=?", (pid,)).fetchone()[0]
        self.assertEqual(earned, E.PERF_MAX // 4)

    def test_slide_rule(self):
        pid = self._elc("C", 18)
        self._stats(pid, 6, 0, 1)
        E.season_end(self.c, self.year, "2026-04-20")
        c = self.c.execute("SELECT start_year FROM contracts WHERE player_id=?", (pid,)).fetchone()[0]
        self.assertEqual(c, self.year + 1)
        self.assertEqual(self.c.execute("SELECT slides FROM elc_terms WHERE player_id=?", (pid,)).fetchone()[0], 1)
        # a 21-year-old does not slide however little he plays
        pid2 = self._elc("D", 21)
        self._stats(pid2, 3, 0, 0)
        E.season_end(self.c, self.year, "2026-04-21")
        self.assertEqual(self.c.execute("SELECT start_year FROM contracts WHERE player_id=?", (pid2,)).fetchone()[0],
                         self.year)

    def test_bonus_overage_when_over_the_cap(self):
        pid = self._elc("C", 21)
        self._stats(pid, 82, 30, 45)                           # all four parts
        cap = K.crules(self.c)["cap_ceiling"]
        room = cap - K.payroll(self.c, self.me, self.year)
        self.c.execute("UPDATE contracts SET cap_hit=cap_hit+? WHERE player_id=?", (max(0, room - 100_000), pid))
        E.season_end(self.c, self.year, "2026-04-20")
        ch = self.c.execute("SELECT amount FROM cap_charges WHERE team_id=? AND season_start_year=? AND "
                            "reason='bonus overage'", (self.me, self.year + 1)).fetchone()
        self.assertIsNotNone(ch)
        self.assertLessEqual(ch[0], E.PERF_MAX)


class CollegeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = small_world(self.tmp.name)
        self.addCleanup(self.c.close)

    def _college_pick(self):
        return self.c.execute("SELECT d.* FROM draft_rights d JOIN players p USING (player_id) JOIN teams t ON "
                              "t.team_id=p.club_id WHERE t.league_id IN (SELECT league_id FROM teams t2 WHERE "
                              "t2.team_id=p.club_id) ORDER BY d.overall_pick").fetchall()

    def test_refusal_probability_rises_with_congestion_and_falls_with_slot(self):
        rows = [r for r in self.c.execute("SELECT * FROM draft_rights").fetchall()
                if E.leverage(self.c, r["player_id"]) == "college"]
        self.assertTrue(rows, "small world should have college picks")
        r = rows[0]
        p_hi, _ = E.refusal_probability(self.c, r["team_id"], r["player_id"], 200)
        p_lo, _ = E.refusal_probability(self.c, r["team_id"], r["player_id"], 1)
        self.assertGreater(p_hi, p_lo)
        self.assertTrue(0 < p_lo < p_hi < 1)

    def test_refusing_pick_walks_or_has_rights_traded(self):
        rows = [r for r in self.c.execute("SELECT * FROM draft_rights").fetchall()
                if E.leverage(self.c, r["player_id"]) == "college"]
        r = rows[0]
        E.B0, old = 10.0, E.B0                                   # force a refusal
        self.addCleanup(setattr, E, "B0", old)
        day = get_state(self.c)[0]
        done, lines = E.college_refusals(self.c, [r], day, lambda _: True)
        self.assertEqual(done, {r["player_id"]})
        now = self.c.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (r["player_id"],)).fetchone()
        if now is None:                                          # walked: in the free-agent pool
            p = self.c.execute("SELECT team_id, club_id FROM players WHERE player_id=?", (r["player_id"],)).fetchone()
            self.assertEqual((p[0], p[1]), (None, None))
        else:                                                    # rights traded and signed elsewhere
            self.assertNotEqual(now[0], r["team_id"])
            self.assertIsNotNone(K.current_contract(self.c, r["player_id"], K.signing_year(self.c)))


class OfferSheetFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def _target(self):
        return self.c.execute("SELECT player_id, team_id, cap_hit FROM contracts WHERE team_id<>? AND start_year<=? "
                              "AND start_year+years>? ORDER BY cap_hit DESC LIMIT 1",
                              (self.me, K.signing_year(self.c), K.signing_year(self.c))).fetchone()

    def test_stars_are_matched_almost_always(self):
        t = self._target()
        orig = OS._star
        OS._star = lambda *a: True
        self.addCleanup(setattr, OS, "_star", orig)
        room = OS._owner_room
        OS._owner_room = lambda *a: 50_000_000
        self.addCleanup(setattr, OS, "_owner_room", room)
        import random
        ok = sum(OS.owner_matches(self.c, t["team_id"], t["player_id"], 9_000_000, 5, random.Random(i))[0]
                 for i in range(40))
        self.assertGreaterEqual(ok, 33)

    def test_owner_clears_room_to_match(self):
        t = self._target()
        orig, room = OS._star, OS._owner_room
        OS._star = lambda *a: True
        OS.STAR_MATCH, sm = 1.0, OS.STAR_MATCH
        self.addCleanup(setattr, OS, "STAR_MATCH", sm)
        self.addCleanup(setattr, OS, "_star", orig)
        OS._owner_room = lambda *a: 7_000_000
        self.addCleanup(setattr, OS, "_owner_room", room)
        import random
        matched, why, cleared = OS.owner_matches(self.c, t["team_id"], t["player_id"], 9_000_000, 5, random.Random(1))
        if cleared is not None:                                  # a lesser contract went out to make room
            self.assertTrue(matched)
            self.assertNotEqual(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (cleared,)).fetchone()[0],
                                t["team_id"])
        else:
            self.assertFalse(matched)
            self.assertIn("cap", why)


class HearingLensTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_points_beat_play_driving(self):
        year = K.season_year(self.c)
        league = self.c.execute("SELECT league_id FROM seasons WHERE start_year=?", (year,)).fetchone()[0]
        two = [r[0] for r in self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position='C' LIMIT 2",
                                            (self.me,))]
        a, b = two
        attrs = self.c.execute("SELECT * FROM player_attributes WHERE player_id=?", (a,)).fetchone()
        cols = [k for k in attrs.keys() if k != "player_id"]
        self.c.execute(f"UPDATE player_attributes SET {', '.join(c + '=?' for c in cols)} WHERE player_id=?",
                       [attrs[k] for k in cols] + [b])
        self.c.execute("DELETE FROM skater_season_stats WHERE season_start_year>=?", (year - 1,))
        others = [r[0] for r in self.c.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL AND position "
                                               "IN ('C','LW','RW') AND player_id NOT IN (?,?) LIMIT 30", (a, b))]
        for k, pid in enumerate(others):
            self.c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, "
                           "gp, g, a, toi_sec) VALUES (?,?,NULL,?, 'RS', 82, ?, ?, 90000)", (pid, year, league,
                                                                                            5 + k % 20, 8 + k % 25))
        for pid, g, ast in ((a, 30, 40), (b, 6, 12)):
            self.c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, "
                           "gp, g, a, toi_sec) VALUES (?,?,?,?, 'RS', 82, ?, ?, 90000)", (pid, year, self.me, league,
                                                                                         g, ast))
        ctx = A.market_context(self.c)
        self.assertGreater(A.hearing_value(self.c, a, ctx), A.hearing_value(self.c, b, ctx))
