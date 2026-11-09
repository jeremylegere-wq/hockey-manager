"""v35, phase D: hidden attributes (stable, centred, scouted), special abilities, game ratings, rust and playing hurt,
the morale log, harmony (cliques, clashes, incidents) and mutual termination."""
import io
import statistics
import tempfile
import unittest

from hs.game import harmony as HM
from hs.game import hidden as HD
from hs.game import people as PE
from hs.game import welfare as W
from hs.game.cli import CLI
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill
from hs.sim.loader import game_ratings, load_teams

from test_game import make_db
from test_sim import ENV


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]

    def skater(self):
        return self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position<>'G' AND status='active' LIMIT 1", (self.me,)).fetchone()[0]


class HiddenTests(Base):
    def test_stable_and_centred(self):
        self.assertEqual(HD._gen(123), HD._gen(123))
        allh = HD.all_of(self.c)
        for k in HD.HIDDEN:
            self.assertAlmostEqual(statistics.fmean(h[k] for h in allh.values()), 10.5, delta=1.0)
        # the effects are neutral for an average player
        self.assertAlmostEqual(HD.injury_factor(10.5), 1.0)
        self.assertAlmostEqual(HD.temper_weight(10.5), 1.0)
        self.assertAlmostEqual(HD.big_games_fin(10.5), 0.0)
        self.assertAlmostEqual(HD.coach_factor(10.5), 1.0, places=2)

    def test_loader_carries_them(self):
        teams = load_teams(self.c)
        p = teams[self.me].skaters[0]
        h = HD.of(self.c, p.pid)
        self.assertAlmostEqual(p.cons_sd, HD.consistency_sd(h["consistency"]))

    def test_abilities_and_scouting(self):
        a = {"hitting": 18, "strength": 15}
        h = dict(HD._gen(1), injury_proneness=2, big_games=18)
        ab = HD.abilities(a, h, "D", None)
        self.assertIn("Big hitter", ab)
        self.assertIn("Playoff performer", ab)
        pid = self.skater()
        HD.fill(self.c)
        self.c.execute("UPDATE hidden SET big_games=19, greed=10 WHERE player_id=?", (pid,))
        self.assertIn("a big-game player", HD.scout_read(self.c, pid))


class RatingsAndRustTests(Base):
    def test_game_ratings(self):
        sim_until(self.c, ENV, Skill(), self.me, days=3)
        rows = self.c.execute("SELECT * FROM game_ratings").fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(1 <= r["overall"] <= 10 for r in rows))
        n = self.c.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]
        self.assertEqual(len(rows), n)

    def test_hurt_and_rust(self):
        pid = self.skater()
        d = __import__("datetime")
        today = d.date.fromisoformat(self.day)
        self.c.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)",
                       (pid, (today - d.timedelta(days=3)).isoformat(), (today + d.timedelta(days=10)).isoformat(), "10 day(s)"))
        self.c.execute("UPDATE players SET status='injured' WHERE player_id=?", (pid,))
        before = load_teams(self.c)[self.me]
        W.play_hurt(self.c, self.me, pid, self.day)
        hurt = load_teams(self.c)[self.me].by_id[pid]
        healthy = [p for p in before.skaters if p.pid == pid]
        self.assertTrue(hurt.gen < (healthy[0].gen if healthy else hurt.gen + 1))
        W.rest(self.c, self.me, pid, self.day)
        self.assertEqual(self.c.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()[0], "injured")
        with self.assertRaises(ValueError):
            W.rest(self.c, self.me, pid, self.day)


class RoomTests(Base):
    def test_morale_log_and_harmony(self):
        pid = self.skater()
        PE.log_event(self.c, pid, self.day, "role", -2.5, "scratched")
        self.assertEqual(PE.morale_history(self.c, pid)[0]["reason"], "scratched")
        roster = HM._roster(self.c, self.me)
        a, b = roster[0], roster[1]
        for x in (a, b):
            self.c.execute("UPDATE personality SET ego=18 WHERE player_id=?", (x["pid"],))
            self.c.execute("UPDATE hidden SET temperament=3 WHERE player_id=?", (x["pid"],))
        pairs = HM.clashes(self.c, self.me)
        self.assertIn((a["pid"], b["pid"]), pairs)
        HM.P_INCIDENT, old = 1.0, HM.P_INCIDENT
        try:
            HM.weekly(self.c, self.day)
        finally:
            HM.P_INCIDENT = old
        self.assertTrue(self.c.execute("SELECT 1 FROM incidents WHERE team_id=?", (self.me,)).fetchone())


class TerminationTests(Base):
    def test_terms_and_cli(self):
        pid = self.skater()
        self.c.execute("UPDATE players SET birth_date='1990-01-01' WHERE player_id=?", (pid,))
        self.c.execute("UPDATE morale SET role=20, trade_request=1 WHERE player_id=?", (pid,))
        self.c.execute("UPDATE personality SET loyalty=5 WHERE player_id=?", (pid,))
        self.c.execute("UPDATE contracts SET contract_type='standard' WHERE player_id=?", (pid,))
        self.c.commit()
        ok, pay, why = W.terms(self.c, pid)
        self.assertTrue(ok, why)
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        cli.onecmd(f"terminate {pid}")
        self.assertEqual(cli.status_code, 0, out.getvalue())
        self.assertIsNone(cli.conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0])
        cli.onecmd(f"terminate {pid}")
        self.assertEqual(cli.status_code, 1)


if __name__ == "__main__":
    unittest.main()
