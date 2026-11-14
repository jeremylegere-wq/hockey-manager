"""v60: every league in the world has a season to play, leagues can be switched between game-by-game and
season-at-a-time, and the day is faster without changing a result."""
import math
import sqlite3
import tempfile
import unittest

from hs import perf
from hs.game import leagues as LG
from hs.game.dayloop import sim_until
from hs.leaguedata.league_rules import APPROXIMATE, COUNTRY, RULES
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class RulesTests(unittest.TestCase):
    def test_every_league_has_a_complete_format(self):
        self.assertGreaterEqual(len(RULES), 36)
        for abbr, r in RULES.items():
            for k in ("games", "points", "ot", "gpg", "start", "end", "trophy", "playoffs"):
                self.assertIn(k, r, abbr)
            self.assertIn(r["points"], ("2pt", "3pt"), abbr)
            self.assertTrue(2.2 <= r["gpg"] <= 4.0, abbr)
            po = r["playoffs"]
            self.assertIn(po["kind"], ("europe", "conference", "division", "ncaa", "top"), abbr)
            if po["kind"] == "top":
                n = po["teams"]
                self.assertEqual(n & (n - 1), 0, abbr)                      # a power of two
                self.assertEqual(len(po["best"]), int(math.log2(n)), abbr)  # a series length for every round
                self.assertTrue(all(b % 2 == 1 for b in po["best"]), abbr)
            self.assertIn(abbr, COUNTRY, abbr)
        self.assertTrue(APPROXIMATE <= set(RULES))
        self.assertEqual(len(set(RULES) - APPROXIMATE), 26)                 # v61: all but the ten in APPROXIMATE are from the leagues


class LeaguePlayTests(unittest.TestCase):
    """On the bundled fictional world, which has farm, junior, college and European leagues around the top one."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        cls.tmp = tempfile.TemporaryDirectory()
        world = make_mock_world.build(Path(cls.tmp.name) / "world.db", 3)
        Saves(Path(cls.tmp.name) / "saves", world).new_game("T", "PHM", 1)
        cls.path = str(Path(cls.tmp.name) / "saves" / "T.db")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from hs.game.state import connect
        self.c = connect(self.path)
        self.addCleanup(self.c.close)

    def today(self):
        return self.c.execute('SELECT "current_date" FROM game_state').fetchone()[0]

    def test_1_switch_a_league_off_and_on(self):
        sim_until(self.c, ENV, Skill(), days=12)
        every = LG.leagues(self.c, every=True)
        self.assertGreaterEqual(len(every), 10)
        year = LG._season_year(self.c)
        lid = next(l for l in every if self.c.execute("SELECT 1 FROM lg_games WHERE league_id=? AND season=? AND played=1", (l, year)).fetchone())
        count = lambda extra="": self.c.execute(f"SELECT COUNT(*) FROM lg_games WHERE league_id=? AND season=? {extra}", (lid, year)).fetchone()[0]
        lines = lambda: self.c.execute("SELECT COUNT(*) FROM skater_season_stats WHERE league_id=? AND season_start_year=? AND source='league'",
                                       (lid, year)).fetchone()[0]
        self.assertGreater(lines(), 0)
        self.assertIn("season at a time", LG.set_play(self.c, lid, False))
        self.assertNotIn(lid, LG.leagues(self.c))
        self.assertIn(lid, LG.leagues(self.c, every=True))
        self.assertEqual((count(), lines()), (0, 0))                        # what it played this season is taken back
        self.assertFalse(next(x for x in LG.selection(self.c) if x["league_id"] == lid)["play"])
        sim_until(self.c, ENV, Skill(), days=2)
        self.assertEqual(count(), 0)                                        # off: nothing is scheduled or played
        LG.set_play(self.c, lid, True)
        sim_until(self.c, ENV, Skill(), days=2)
        self.assertGreater(count("AND played=1"), 0)                        # on: scheduled again...
        self.assertEqual(count(f"AND played=0 AND day<='{self.today()}'"), 0)   # ...and caught up to today
        self.assertGreater(lines(), 0)
        self.c.commit()

    def test_0_schedules_reach_their_count_and_share_home_games(self):
        clubs = [dict(team_id=k, division="", conference="") for k in range(36)]
        import random
        for games in (28, 44, 58):
            counts = LG._pair_counts(clubs, games, random.Random(games), fill=True)
            per = [sum(v for (i, j), v in counts.items() if k in (i, j)) for k in range(36)]
            self.assertEqual(set(per), {games})                             # part of a round is added to hit the count
        LG.ensure_season(self.c)
        self.c.commit()
        year = LG._season_year(self.c)
        for lid in LG.leagues(self.c):
            rows = self.c.execute("SELECT t, COUNT(*), SUM(h) FROM (SELECT home t, 1 h FROM lg_games WHERE league_id=? AND season=? AND stage='RS' "
                                  "UNION ALL SELECT away, 0 FROM lg_games WHERE league_id=? AND season=? AND stage='RS') GROUP BY t",
                                  (lid, year, lid, year)).fetchall()
            self.assertTrue(rows)
            for t, n, h in rows:
                self.assertLessEqual(abs(2 * h - n), 3, (lid, t, n, h))     # home and away within a game or two of each other

    def test_2_top_format_plays_to_a_champion(self):
        import datetime
        every = LG.leagues(self.c, every=True)
        lid, (abbr, rules) = max(every.items(), key=lambda kv: self.c.execute("SELECT COUNT(*) FROM teams WHERE league_id=?", (kv[0],)).fetchone()[0])
        old = dict(RULES[abbr])
        d0 = datetime.date.fromisoformat(self.today())
        mmdd = lambda k: (d0 + datetime.timedelta(days=k)).strftime("%m-%d")
        RULES[abbr].update(games=2, start=mmdd(1), end=mmdd(6), playoffs=dict(kind="top", teams=8, best=[1, 1, 3]))
        try:
            LG.set_play(self.c, lid, False)                                 # drop its schedule, then make the short one
            LG.set_play(self.c, lid, True)
            row = None
            for k in range(1, 60):
                LG.day(self.c, (d0 + datetime.timedelta(days=k)).isoformat())
                row = self.c.execute("SELECT phase, champion, runner_up FROM lg_seasons WHERE league_id=? ORDER BY season DESC", (lid,)).fetchone()
                if row and row[0] == "done":
                    break
            self.assertEqual(row[0], "done")
            self.assertIsNotNone(row[1])
            sr = self.c.execute("SELECT round, COUNT(*), MAX(best_of), MIN(label) FROM lg_series WHERE league_id=? AND kind<>'bye' "
                                "GROUP BY round ORDER BY round", (lid,)).fetchall()
            self.assertEqual([(r[1], r[2]) for r in sr], [(4, 1), (2, 1), (1, 3)])      # quarterfinals, semifinals, final
            self.assertEqual([r[3] for r in sr], ["quarterfinals", "semifinals", "final"])
            self.c.rollback()
        finally:
            RULES[abbr].clear()
            RULES[abbr].update(old)


class PerfTests(unittest.TestCase):
    def test_memo_only_lives_while_simulating_and_until_a_write(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE t (x)")
        self.assertIsNot(perf.memo(c, "a"), perf.memo(c, "a"))              # not simulating: never cached
        with perf.simulating(c):
            d = perf.memo(c, "a")
            d["k"] = 1
            self.assertIs(perf.memo(c, "a"), d)
            self.assertEqual(perf.memo(c, "b"), {})
            c.execute("INSERT INTO t VALUES (1)")
            self.assertEqual(perf.memo(c, "a"), {})                         # a write: the cache is gone
            other = sqlite3.connect(":memory:")
            self.assertIsNot(perf.memo(other, "a"), perf.memo(other, "a"))  # another connection is not simulating
        self.assertIsNot(perf.memo(c, "a"), perf.memo(c, "a"))

    def test_values_are_the_same_with_and_without_the_cache(self):
        from hs.game import roster as R
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = make_db(tmp)
            pids = [r[0] for r in c.execute("SELECT player_id FROM players WHERE team_id=? LIMIT 12", (me,))]
            plain = [R.player_value(c, p) for p in pids]
            with perf.simulating(c):
                self.assertEqual([R.player_value(c, p) for p in pids], plain)
                self.assertEqual([R.player_value(c, p) for p in pids], plain)
                first = [tuple(r) for r in R.roster(c, me)]
                self.assertEqual([tuple(r) for r in R.roster(c, me)], first)
                self.assertIsNot(R.roster(c, me), R.roster(c, me))                # callers get their own list
                c.execute("UPDATE players SET birth_date='1990-01-01' WHERE player_id=?", (pids[0],))
                self.assertNotEqual(R.player_value(c, pids[0]), plain[0])   # the write is seen at once
            ix = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertTrue({"ix_players_team", "ix_players_club"} <= ix)
            c.close()


if __name__ == "__main__":
    unittest.main()
