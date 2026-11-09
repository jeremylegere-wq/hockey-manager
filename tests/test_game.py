import io
import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hs.game import roster as R
from hs.game.cli import CLI, main as cli_main
from hs.game.dayloop import finish_season, remaining, sim_day, sim_until
from hs.game.injuries import BASE_PER_60, draw_days, roll_injuries
from hs.game.state import connect, get_state, new_game, season_state
from hs.ingest import build_db
from hs.sim.engine import Skill
from hs.tools.make_example_pack import generate

from test_sim import ENV


def make_db(tmp, name="g.db", team="NLT", seed=7):
    pack = Path(tmp) / "pack"
    if not pack.exists():
        generate(pack)
    db = str(Path(tmp) / name)
    build_db(pack, db, overwrite=True)
    new_game(db, team, seed)
    conn = connect(db)
    return db, conn, conn.execute("SELECT team_id FROM teams WHERE abbr=?", (team,)).fetchone()[0]


def dump(conn):
    g = [tuple(r) for r in conn.execute("SELECT game_id, game_date, home_team_id, away_team_id, home_goals, away_goals, "
                                        "went_to_ot, seed FROM games ORDER BY game_id")]
    t = [tuple(r)[1:] for r in conn.execute("SELECT * FROM transactions ORDER BY txn_id")]
    return g, t


class GameLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.skill = Skill()

    def test_new_game_sets_state_and_refuses_repeat(self):
        db, conn, me = make_db(self.tmp.name)
        first = conn.execute("SELECT MIN(game_date) FROM games").fetchone()[0]
        self.assertLess(get_state(conn)[0], first)
        self.assertEqual(get_state(conn)[1], 7)
        self.assertEqual(season_state(conn), "regular_season")
        with self.assertRaises(ValueError):
            new_game(db, "NLT", 1)

    def test_same_seed_same_commands_identical_db(self):
        a = make_db(self.tmp.name, "a.db")
        b = make_db(self.tmp.name, "b.db")
        for _, conn, me in (a, b):
            sim_until(conn, ENV, self.skill, me, days=40, to_end=True)
        self.assertEqual(dump(a[1]), dump(b[1]))
        self.assertTrue(any(r[4] is not None for r in dump(a[1])[0]))

    def test_sim_day_plays_only_that_date_then_next(self):
        _, conn, me = make_db(self.tmp.name)
        d1 = conn.execute("SELECT MIN(game_date) FROM games").fetchone()[0]
        s = sim_day(conn, ENV, self.skill, me)          # first call: the day before the first game
        self.assertEqual(s.day, get_state(conn)[0])
        n = conn.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0]
        self.assertEqual(n, len(s.results))
        self.assertTrue(all(r[0] for r in conn.execute("SELECT game_date <= ? FROM games WHERE played=1", (s.day,))))
        s2 = sim_day(conn, ENV, self.skill, me)
        self.assertGreater(s2.day, s.day)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM games WHERE played=1 AND game_date>?", (s2.day,)).fetchone()[0], 0)
        self.assertGreaterEqual(d1, s.day)

    def test_injured_player_sits_and_returns(self):
        _, conn, me = make_db(self.tmp.name)
        cur = get_state(conn)[0]
        pid = conn.execute("SELECT player_id FROM players WHERE team_id=? AND position='C' ORDER BY player_id", (me,)).fetchone()[0]
        conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (pid,))
        conn.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)",
                     (pid, cur, "2026-10-12", "test"))
        conn.commit()
        sim_until(conn, ENV, self.skill, me, until_date="2026-10-11", to_end=True)
        self.assertEqual(conn.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()[0], "injured")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM player_game_stats WHERE player_id=?", (pid,)).fetchone()[0], 0)
        sim_until(conn, ENV, self.skill, me, until_date="2026-10-12", to_end=True)
        self.assertEqual(conn.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()[0], "active")
        self.assertTrue(conn.execute("SELECT 1 FROM transactions WHERE txn_type='return' AND player_id=?", (pid,)).fetchone())

    def test_injury_rate_and_severity(self):
        _, conn, me = make_db(self.tmp.name)
        pids = [r[0] for r in conn.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL")]
        played = [(p, 1200) for p in pids] * 100          # 16000 player-games at 20 minutes
        out = roll_injuries(conn, "2026-10-01", played, random.Random(3))
        expect = len(played) * BASE_PER_60 * 20 / 60
        self.assertTrue(0.6 * expect < len(out) < 1.5 * expect, (len(out), expect))
        rng = random.Random(1)
        days = [draw_days(rng) for _ in range(20000)]
        self.assertAlmostEqual(sum(d <= 3 for d in days) / len(days), 0.45, delta=0.02)
        self.assertTrue(1 <= min(days) and max(days) <= 200)

    def test_goalie_shortage_signs_free_agent_and_limits_enforced(self):
        _, conn, me = make_db(self.tmp.name)
        day = get_state(conn)[0]
        g = [r[0] for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND position='G'", (me,))]
        conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (g[0],))
        self.assertEqual(R.shortages(conn, me), ["G"])
        signed = R.ensure_dressable(conn, me, day)
        self.assertEqual(len(signed), 1)
        self.assertEqual(R.shortages(conn, me), [])
        # fill the roster to the maximum, then one more must fail
        _, mx = R.limits(conn)
        fas = R.free_agents(conn)
        while len(R.roster(conn, me)) < mx:
            R.sign_free_agent(conn, me, fas.pop(0)[1], day)
        with self.assertRaises(R.RosterError):
            R.sign_free_agent(conn, me, fas.pop(0)[1], day)
        # release down to the minimum, then one more must fail
        mn, _ = R.limits(conn)
        while len(R.roster(conn, me)) > mn:
            victim = R._lowest_healthy(conn, me)
            R.release(conn, me, victim[1], day)
        with self.assertRaises(R.RosterError):
            R.release(conn, me, R._lowest_healthy(conn, me)[1], day)

    def test_no_free_agents_is_handled(self):
        _, conn, me = make_db(self.tmp.name)
        conn.execute("UPDATE players SET status='retired' WHERE team_id IS NULL")
        g = conn.execute("SELECT player_id FROM players WHERE team_id=? AND position='G'", (me,)).fetchone()[0]
        conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (g,))
        self.assertEqual(R.ensure_dressable(conn, me, "2026-10-01"), [])
        self.assertEqual(R.shortages(conn, me), ["G"])

    def test_trade_evaluation_and_execution(self):
        _, conn, me = make_db(self.tmp.name)
        other = conn.execute("SELECT team_id FROM teams WHERE team_id<>? ORDER BY team_id", (me,)).fetchone()[0]
        mine = sorted(((R.player_value(conn, r[0]), r[0]) for r in conn.execute(
            "SELECT player_id FROM players WHERE team_id=? AND position='C'", (me,))))
        theirs = sorted(((R.player_value(conn, r[0]), r[0]) for r in conn.execute(
            "SELECT player_id FROM players WHERE team_id=? AND position='C'", (other,))))
        worst_mine, best_theirs = mine[0], theirs[-1]
        ok, why = R.evaluate_trade(conn, me, [worst_mine[1]], other, [best_theirs[1]])
        self.assertFalse(ok, why)
        ok, why = R.evaluate_trade(conn, me, [mine[-1][1], mine[-2][1]], other, [theirs[0][1]])
        self.assertTrue(ok, why)
        R.trade(conn, me, [mine[-1][1]], other, [theirs[0][1]], "2026-10-01")
        self.assertEqual(conn.execute("SELECT team_id FROM players WHERE player_id=?", (mine[-1][1],)).fetchone()[0], other)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM transactions WHERE txn_type='trade'").fetchone()[0], 2)
        with self.assertRaises(R.RosterError):             # 2-for-0 would leave the other side over the maximum
            for _ in range(10):
                R.trade(conn, me, [mine[0][1]], other, [], "2026-10-01")
                mine = [m for m in mine[1:]]
        # convexity: two average players must not buy one clearly better player
        self.assertLess(2 * R.trade_value(50), R.trade_value(70))
        self.assertGreater(R.trade_value(90), R.trade_value(60) + R.trade_value(60))
        self.assertEqual(R.age_factor(26), 1.0)
        self.assertLess(R.age_factor(19), 1.0)
        self.assertLess(R.age_factor(36), R.age_factor(33))

    def test_season_finishes_once_and_is_idempotent(self):
        _, conn, me = make_db(self.tmp.name)
        sim_until(conn, ENV, self.skill, me, to_end=True)
        self.assertEqual(remaining(conn), 0)
        self.assertEqual(season_state(conn), "finished")
        po = conn.execute("SELECT COUNT(*) FROM games WHERE game_type='PO'").fetchone()[0]
        self.assertGreater(po, 0)
        self.assertIsNone(finish_season(conn, ENV, self.skill))
        sim_until(conn, ENV, self.skill, me, to_end=True)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM games WHERE game_type='PO'").fetchone()[0], po)
        self.assertTrue(conn.execute("SELECT 1 FROM inbox WHERE subject='Season over'").fetchone())

    def test_stops_for_user_needs_and_by_user_game(self):
        _, conn, me = make_db(self.tmp.name)
        res = sim_until(conn, ENV, self.skill, me, through_user_game=True)
        self.assertTrue(any(me in (r[1], r[2]) for r in res[-1].results))
        d = get_state(conn)[0]
        sim_until(conn, ENV, self.skill, me, days=5)
        self.assertGreater(get_state(conn)[0], d)

    def test_cli_scripted_run(self):
        db, conn, me = make_db(self.tmp.name)
        env = Path(self.tmp.name) / "env.json"
        env.write_text(json.dumps(ENV))
        conn.close()
        buf = io.StringIO()
        cli = CLI(db, ENV, out=buf)
        for c in ["status", "sim week", "standings", "schedule 2", "results 2", "roster goalies", "fa G", "lines",
                  "injuries", "inbox", "sim to 2026-11-15", "sim season", "playoffs"]:
            cli.onecmd(c)
        out = buf.getvalue()
        self.assertEqual(cli.status_code, 0, out)
        self.assertIn("GP", out)
        self.assertIn("Champion", out)
        cli.onecmd("sign nobody-with-this-name")
        self.assertEqual(cli.status_code, 1)
        self.assertEqual(cli_main([db, "--env", str(env), "-c", "standings"]), 0)


if __name__ == "__main__":
    unittest.main()
