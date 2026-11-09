"""v30: the defects batch. Trade rumours, the star-trade limits, KHL and NCAA signings, the media's weekly outcomes and
their reach into the engine, the draft rankings and pick deals, the buyout window, goalie letters, the 2D game."""
import datetime
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import draft as D
from hs.game import press as P
from hs.game import rumours as RU
from hs.game import trades as T
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV
from test_world import small_world


class V30Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]
        self.other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]

    def mine(self, n=4, pos="C"):
        return [r[0] for r in self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position<>'G' AND status='active' "
                                             "LIMIT ?", (self.me, n))]


class RumourTests(V30Base):
    def test_repeat_shopping_leaks_and_hurts(self):
        pid = self.mine(1)[0]
        before = self.c.execute("SELECT trust_mgmt FROM morale WHERE player_id=?", (pid,)).fetchone()
        for k in range(8):                                   # the leak chance climbs 25%, 40%, 55%...: it gets out
            RU.offer_rejected(self.c, self.me, self.other, [pid], (datetime.date.fromisoformat(self.day) + datetime.timedelta(days=k)).isoformat())
        times, leaks = self.c.execute("SELECT times, leaks FROM shopped WHERE player_id=?", (pid,)).fetchone()
        self.assertEqual(times, 8)
        self.assertGreater(leaks, 0)
        self.assertTrue(self.c.execute("SELECT 1 FROM league_events WHERE event_type='RUMOUR' AND player_id=?", (pid,)).fetchone())
        if before:
            after = self.c.execute("SELECT trust_mgmt FROM morale WHERE player_id=?", (pid,)).fetchone()
            self.assertLess(after[0], before[0])

    def test_room_notices(self):
        RU.ensure_tables(self.c)
        for pid in self.mine(3):
            self.c.execute("INSERT INTO shopped VALUES (?,?,1,1,?)", (pid, self.me, self.day))
        RU._room(self.c, self.me, self.day)
        self.assertTrue(self.c.execute("SELECT 1 FROM inbox WHERE subject='The room has noticed'").fetchone())


class StarTradeTests(V30Base):
    def test_star_cap(self):
        y = K.season_year(self.c)
        for k in range(T.STAR_TRADES_MAX):
            self.c.execute("INSERT INTO league_events (event_date, season_start_year, event_type, summary, payload) VALUES "
                           "(?,?, 'TRADE_COMPLETED', 'x', '{\"star\": true}')", (self.day, y))
        self.assertEqual(T.star_trades_this_season(self.c), T.STAR_TRADES_MAX)

    def test_constants(self):
        self.assertLess(T.STAR_P, T.STAR_P_RUSH)              # more at the deadline than in October
        self.assertLess(T.P_THREE_TEAM, 0.1)                  # three-team deals stay rare


class WorldBase(V30Base):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = small_world(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]


class SigningTests(WorldBase):
    def _prospect(self, league_abbr):
        r = self.c.execute("SELECT p.player_id FROM players p JOIN teams t ON t.team_id=p.club_id JOIN leagues l ON l.league_id=t.league_id "
                           "WHERE (l.abbr=? OR ?='any') AND l.abbr<>'NHL' AND p.team_id IS NULL AND p.player_id IN (SELECT player_id FROM prospect_info) "
                           "AND p.player_id NOT IN (SELECT player_id FROM contracts) LIMIT 1",
                           (league_abbr, league_abbr)).fetchone()
        if r is None:
            self.skipTest(f"no {league_abbr} player in the test world")
        D.ensure_tables(self.c)
        self.c.execute("INSERT OR REPLACE INTO draft_rights VALUES (?,?,?,?,?)", (r[0], self.me, K.season_year(self.c), 20, K.season_year(self.c) + 3))
        return r[0]

    def test_khl_needs_buyout_offer(self):
        pid = self._prospect("any")                          # any pick, put under a KHL contract
        self.c.execute("UPDATE prospect_info SET khl_until=? WHERE player_id=?", (K.season_year(self.c) + 2, pid))
        with self.assertRaisesRegex(ValueError, "KHL"):
            D.sign_elc(self.c, pid, self.me, self.day)
        try:
            D.sign_elc(self.c, pid, self.me, self.day, khl_buyout=True)
        except ValueError as e:
            self.assertIn("KHL", str(e))
        with self.assertRaisesRegex(ValueError, "already answered|under contract"):
            D.sign_elc(self.c, pid, self.me, self.day, khl_buyout=True)   # one ask a month

    def test_ncaa_waits_for_his_season(self):
        pid = self._prospect("NCAA")
        if K.season_state(self.c) not in ("regular_season", "playoffs"):
            self.skipTest("not in season")
        with self.assertRaisesRegex(ValueError, "college season"):
            D.sign_elc(self.c, pid, self.me, "2025-11-10")


class MediaTests(V30Base):
    def test_outcomes_and_engine_form(self):
        P.media_state(self.c, self.me)
        self.c.execute("UPDATE media_state SET controversy=90, fan_sentiment=80 WHERE team_id=?", (self.me,))
        heads = P.weekly_outcomes(self.c, self.day, self.me)
        self.assertTrue(any("soap opera" in h for h in heads))
        self.assertEqual(P.weekly_outcomes(self.c, self.day, self.me), [])          # a cooldown, not every week
        f = P.engine_form(self.c)
        form, home = f[self.me]
        self.assertAlmostEqual(form, 0.97)
        self.assertGreater(home, 1)
        others = [v for t, v in f.items() if t != self.me]
        self.assertTrue(all(v == (1.0, 1.0) for v in others) or not others)


class DraftTests(WorldBase):
    def test_rankings_and_deals(self):
        D.ensure_tables(self.c)
        year = D.draft_year(self.c)
        r = D.rankings(self.c, year)
        if not r:
            self.skipTest("no draft class in the test world")
        x = next(iter(r.values()))
        for k in ("csb", "csb_list", "media", "consensus", "range"):
            self.assertIn(k, x)
        self.assertEqual(sorted(v["consensus"] for v in r.values()), list(range(1, len(r) + 1)))
        self.assertEqual(D.rankings(self.c, year), r)                              # fixed once computed
        teams = [t[0] for t in self.c.execute("SELECT team_id FROM teams WHERE league_id=1 ORDER BY team_id")]
        teams.remove(self.me)
        order = [self.me] + teams
        rows = [(year, rnd * len(order) + k + 1, rnd + 1, t, None, None) for rnd in range(7) for k, t in enumerate(order)]
        self.c.executemany("INSERT INTO draft_picks VALUES (?,?,?,?,?,?)", rows)
        d = D.pick_deals(self.c)
        self.assertIsNone(d["buy"])                                                # we are on the clock
        self.assertTrue(d["down"])
        for o in d["down"]:
            self.assertGreaterEqual(o["value_in"], o["value_out"])
            self.assertEqual(o["give"], [1])


class BuyoutTests(V30Base):
    def test_window(self):
        pid = self.c.execute("SELECT player_id FROM contracts WHERE team_id=? AND start_year<=? LIMIT 1",
                             (self.me, K.signing_year(self.c))).fetchone()[0]
        self.assertIn("15 June", K.buyout_check(self.c, pid, self.day))           # mid-season: refused
        self.c.execute("UPDATE players SET status='injured' WHERE player_id=?", (pid,))
        self.assertIn("injured", K.buyout_check(self.c, pid, self.day))


class GoalieLetterTests(V30Base):
    def test_goalie_cannot_be_captain(self):
        from hs.game import people
        g = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position='G' LIMIT 1", (self.me,)).fetchone()[0]
        with self.assertRaisesRegex(ValueError, "oalie"):
            people.set_captain(self.c, self.me, g, self.day)


class Rink2DTests(V30Base):
    def test_track(self):
        from hs.sim import rink2d
        sim_until(self.c, ENV, Skill(), days=1)
        gid = self.c.execute("SELECT game_id FROM games WHERE played=1 LIMIT 1").fetchone()[0]
        tr = rink2d.track(self.c, gid)
        self.assertGreater(len(tr["frames"]), 3000)
        self.assertTrue(all(len(f) == 27 for f in tr["frames"][:200]))
        xs = [f[2] for f in tr["frames"] if f[2] is not None]
        self.assertTrue(all(-100 <= x <= 100 for x in xs))
        goals = [m for m in tr["marks"] if m["type"] == "goal"]
        g, so = self.c.execute("SELECT home_goals + away_goals, went_to_ot FROM games WHERE game_id=?", (gid,)).fetchone()
        self.assertEqual(len(goals), g - (1 if so == 2 else 0))        # a shootout's winner counts but is not a goal event
        self.assertTrue(tr["rosters"] and tr["players"])


if __name__ == "__main__":
    unittest.main()
