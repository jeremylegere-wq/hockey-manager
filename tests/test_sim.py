import sqlite3
import tempfile
import unittest
from pathlib import Path

from hs.attributes import ALL_ATTRS
from hs.ingest import build_db
from hs.sim.engine import Player, Skill, Team, simulate_game
from hs.sim.loader import load_teams, write_result
from hs.tools.make_example_pack import generate

# Synthetic round-number environment (own values, plausible NHL shape) so tests need no third-party data.
STATE = dict(att60=56.0, blocked_frac=0.28, missed_frac=0.35, sh_pct=0.095, sh_pct_regular=0.088, rebound_att_per_sog=0.12,
             rebound_frac_of_attempts=0.057, rebound_sh_pct=0.2, d_attempt_share=0.35)
ENV = {"ev": dict(STATE), "pp": dict(STATE, att60=99.0, sh_pct=0.14, sh_pct_regular=0.13, d_attempt_share=0.21),
       "sh": dict(STATE, att60=14.0, sh_pct=0.09, sh_pct_regular=0.085, d_attempt_share=0.24),
       "game": dict(penalties_per_game_both_teams=6.9, primary_assists_per_goal=0.94, secondary_assists_per_goal=0.75)}


def team(tid, rating, seed_pid=0):
    a = {k: rating for k in ALL_ATTRS}
    pl = [Player.from_attrs(seed_pid + i, pos, a, toi=1000 - i)
          for i, pos in enumerate(["C"] * 4 + ["LW"] * 4 + ["RW"] * 4 + ["D"] * 6 + ["G"] * 2)]
    return Team(tid, f"T{tid}", pl)


class SimTests(unittest.TestCase):
    def test_same_seed_same_game(self):
        h, a = team(1, 10), team(2, 10, 100)
        r1, r2 = simulate_game(h, a, ENV, Skill(), 42), simulate_game(h, a, ENV, Skill(), 42)
        self.assertEqual((r1.goals, r1.events), (r2.goals, r2.events))
        self.assertNotEqual(r1.events, simulate_game(h, a, ENV, Skill(), 43).events)

    def test_scoring_is_in_a_sane_range(self):
        h, a = team(1, 10), team(2, 10, 100)
        goals = [sum(simulate_game(h, a, ENV, Skill(), s, events=False).goals) for s in range(300)]
        self.assertTrue(4.5 < sum(goals) / len(goals) < 7.0, sum(goals) / len(goals))

    def test_better_team_wins_more_but_not_always(self):
        strong, weak = team(1, 11.0), team(2, 10.0, 100)  # one rating point better at everything
        wins = sum(simulate_game(strong, weak, ENV, Skill(), s, events=False).goals[0] >
                   simulate_game(strong, weak, ENV, Skill(), s, events=False).goals[1] for s in range(400))
        self.assertTrue(0.6 < wins / 400 < 0.95, wins / 400)

    def test_result_is_stored_and_replayable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack, db = Path(tmp) / "p", Path(tmp) / "g.db"
            generate(pack)
            build_db(pack, db)
            con = sqlite3.connect(db)
            teams = load_teams(con)
            self.assertEqual(len(teams), 8)
            season = con.execute("SELECT season_id FROM seasons").fetchone()[0]
            con.execute("INSERT INTO games (game_id, season_id, game_date, home_team_id, away_team_id) VALUES (1, ?, '2026-10-10', 1, 2)", (season,))
            res = simulate_game(teams[1], teams[2], ENV, Skill(), 99)
            write_result(con, 1, 1, 2, res, 99, teams)
            con.commit()
            row = tuple(con.execute("SELECT home_goals, away_goals, played, seed FROM games WHERE game_id=1").fetchone())
            self.assertEqual(row, (res.goals[0], res.goals[1], 1, 99))
            self.assertEqual(con.execute("SELECT COUNT(*) FROM game_events WHERE game_id=1").fetchone()[0], len(res.events))
            self.assertEqual(con.execute("SELECT SUM(goals) FROM player_game_stats WHERE game_id=1").fetchone()[0] or 0,
                             sum(1 for e in res.events if e[2] == "goal"))
            again = simulate_game(teams[1], teams[2], ENV, Skill(), row[3])  # replay from the stored seed
            self.assertEqual(again.events, res.events)


if __name__ == "__main__":
    unittest.main()
