import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from hs.ingest import build_db
from hs.league import standings
from hs.league.playoffs import _bracket_order
from hs.league.rules import check_rules, merged, opponent_counts
from hs.league.schedule import build_schedule, schedule_stats, season_days
from hs.leaguedata import nhl_2025_26 as nhl
from hs.tools.make_example_pack import generate


def nhl_teams():
    return [dict(team_id=i + 1, conference=c, division=d) for i, (c, d) in
            enumerate(sorted((v[2], v[3]) for v in nhl.TEAMS.values()))]


class RulesTests(unittest.TestCase):
    def test_nhl_structure_is_82_games_for_everyone(self):
        teams, rules = nhl_teams(), merged(nhl.RULES)
        self.assertEqual(len(teams), 32)
        self.assertEqual(check_rules(rules, teams), [])
        per = Counter()
        for (a, b), g in opponent_counts(teams, rules).items():
            per[a] += g
            per[b] += g
        self.assertEqual(set(per.values()), {82})

    def test_bad_rules_are_reported(self):
        teams = nhl_teams()
        bad = merged(dict(nhl.RULES, schedule=dict(nhl.RULES["schedule"], games_per_team=84)))
        self.assertTrue(any("games_per_team" in p for p in check_rules(bad, teams)))
        bad = merged(dict(nhl.RULES, tiebreakers=["luck"]))
        self.assertTrue(any("tiebreaker" in p for p in check_rules(bad, teams)))
        self.assertTrue(any("conference and division" in p for p in check_rules(merged(nhl.RULES), [dict(team_id=1)])))


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.teams, cls.rules = nhl_teams(), merged(nhl.RULES)
        cls.sched = build_schedule(cls.teams, cls.rules, seed=5)

    def test_every_team_plays_82_and_41_at_home(self):
        st = schedule_stats(self.sched)
        self.assertEqual(len(self.sched), 1312)
        for t in st["teams"]:
            self.assertEqual((t["games"], t["home"]), (82, 41))

    def test_opponent_counts_match_rules(self):
        want = opponent_counts(self.teams, self.rules)
        got = Counter(tuple(sorted((h, a))) for _, h, a in self.sched)
        self.assertEqual(dict(got), want)

    def test_one_game_per_team_per_day_inside_the_season_and_not_in_the_break(self):
        days = set(season_days(self.rules))
        seen = set()
        for d, h, a in self.sched:
            self.assertIn(d, days)
            for t in (h, a):
                self.assertNotIn((d, t), seen)
                seen.add((d, t))
        self.assertFalse(any(date(2026, 2, 6) <= d <= date(2026, 2, 24) for d, _, _ in self.sched))

    def test_runs_of_home_or_away_games_stay_short(self):
        st = schedule_stats(self.sched)["teams"]
        self.assertLessEqual(max(max(t["longest_home"], t["longest_away"]) for t in st), 7)

    def test_same_seed_same_schedule(self):
        self.assertEqual(build_schedule(self.teams, self.rules, seed=5), self.sched)


class StandingsTests(unittest.TestCase):
    def test_tiebreakers_in_order(self):
        rules = merged(nhl.RULES)
        rec = {1: dict(gp=4, w=2, l=2, otl=0, rw=2, row=2, gf=8, ga=8),
               2: dict(gp=4, w=2, l=2, otl=0, rw=1, row=2, gf=9, ga=8),
               3: dict(gp=4, w=3, l=0, otl=1, rw=3, row=3, gf=5, ga=5)}
        self.assertEqual(standings.rank(rec, {}, rules), [3, 1, 2])   # points, then regulation wins

    def test_bracket_order(self):
        self.assertEqual(_bracket_order(8), [0, 7, 3, 4, 1, 6, 2, 5])


class SeasonTests(unittest.TestCase):
    def test_small_league_plays_a_season_and_playoffs(self):
        from hs.league.season import main
        STATE = dict(att60=56.0, blocked_frac=0.28, missed_frac=0.35, sh_pct=0.095, sh_pct_regular=0.088,
                     rebound_att_per_sog=0.12, rebound_frac_of_attempts=0.057, rebound_sh_pct=0.2, d_attempt_share=0.35)
        env = {"ev": dict(STATE), "pp": dict(STATE, att60=99.0, sh_pct=0.14, sh_pct_regular=0.13, d_attempt_share=0.21),
               "sh": dict(STATE, att60=14.0, sh_pct=0.09, sh_pct_regular=0.085, d_attempt_share=0.24),
               "game": dict(penalties_per_game_both_teams=6.9, primary_assists_per_goal=0.94, secondary_assists_per_goal=0.75)}
        with tempfile.TemporaryDirectory() as tmp:
            pack, db, envf = Path(tmp) / "p", Path(tmp) / "g.db", Path(tmp) / "env.json"
            generate(pack)
            build_db(pack, db)
            envf.write_text(json.dumps(env))
            main([str(db), str(envf), "--seed", "3"])
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM games WHERE game_type='RS' AND played=1").fetchone()[0], 224)
            self.assertGreater(con.execute("SELECT COUNT(*) FROM games WHERE game_type='PO'").fetchone()[0], 5)
            rec, _ = standings.table(con)
            self.assertEqual({r["gp"] for r in rec.values()}, {56})
            self.assertEqual(sum(r["w"] for r in rec.values()), 224)
            self.assertEqual(con.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone() is not None, True)


if __name__ == "__main__":
    unittest.main()
