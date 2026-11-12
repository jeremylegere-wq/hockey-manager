"""v59: the rebuilt 2D game. The plan (retiming, strength, units) and the on-ice engine: it plays every stored event,
moves nobody faster than a skater can go, never moves the puck by hand, is deterministic, and reads old saves."""
import collections
import math
import sqlite3
import tempfile
import unittest

from hs.game import replay as RP
from hs.game.dayloop import sim_until
from hs.sim import ice2d, ice_plan as IP
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


class Ice2DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.c, cls.me = make_db(cls.tmp.name)
        sim_until(cls.c, ENV, Skill(), days=3)
        cls.gids = [r[0] for r in cls.c.execute("SELECT game_id FROM games WHERE played=1 ORDER BY game_id LIMIT 4")]
        cls.tracks = {g: ice2d.track(cls.c, g) for g in cls.gids}

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_plan_keeps_goals_and_orders_events(self):
        for gid in self.gids:
            evs = IP.load_events(self.c, gid, RP.build(self.c, gid))
            IP.retime(evs, 1200)
            live = [e for e in evs if e.t is not None and e.type != "goalie"]
            for a, b in zip(live, live[1:]):
                if a.per == b.per:
                    self.assertGreaterEqual(b.t, a.t)
                    if a.side != b.side and "penalty" not in (a.type, b.type) and a.type != "goal":
                        self.assertGreaterEqual(b.t - a.t, 1.5)            # the ice is 200 feet long
            moved = [e for e in live if e.type == "goal" and abs(e.t - e.official) > 3.0]
            self.assertLessEqual(len(moved), 1)

    def test_every_event_is_played(self):
        for gid, tr in self.tracks.items():
            want = dict(self.c.execute("SELECT event_type, COUNT(*) FROM game_events WHERE game_id=? GROUP BY 1", (gid,)).fetchall())
            got = collections.Counter(m["type"] for m in tr["marks"])
            for mark, ev in (("goal", "goal"), ("save", "shot"), ("miss", "miss"), ("block", "block"), ("penalty", "penalty"),
                             ("so_goal", "so_goal"), ("so_miss", "so_miss")):
                self.assertEqual(got[mark], want.get(ev, 0), (gid, mark))
            goals = [m for m in tr["marks"] if m["type"] == "goal"]
            h = sum(1 for m in goals if m["side"] == 0)
            hg, ag, ot = self.c.execute("SELECT home_goals, away_goals, went_to_ot FROM games WHERE game_id=?", (gid,)).fetchone()
            so = 1 if ot == 2 else 0
            self.assertEqual(len(goals), hg + ag - so)
            self.assertIn(h, (hg, hg - so))
            self.assertEqual(tr["check"]["missing"], 0)
            self.assertEqual(tr["check"]["late"], 0)
            self.assertLessEqual(tr["check"]["offspot"], 12)

    def test_the_scorer_takes_the_shot(self):
        tr = self.tracks[self.gids[0]]
        idx = {p["id"]: k for k, p in enumerate(tr["players"])}
        for m in [m for m in tr["marks"] if m["type"] == "goal"]:
            rel = [r for r in tr["marks"] if r["type"] == "release" and r["f"] <= m["f"]][-1]
            self.assertEqual(rel["pid"], m["pid"])
            f = tr["frames"][rel["f"] - 1]
            self.assertIn(idx[m["pid"]], f[6::5])                           # he is on the ice when it leaves his stick

    def test_nobody_teleports_and_the_puck_stays_on_the_ice(self):
        for gid, tr in self.tracks.items():
            fr, dt = tr["frames"], tr["dt"]
            self.assertGreater(len(fr), 15000)
            fast = 0
            for a, b in zip(fr, fr[1:]):
                self.assertLessEqual(abs(b[2]), 1000)
                self.assertLessEqual(abs(b[3]), 425 + 5)
                if b[1] & 2:
                    continue
                ea = {a[i]: (a[i + 1], a[i + 2]) for i in range(6, len(a), 5)}
                for i in range(6, len(b), 5):
                    if b[i] in ea:
                        v = math.hypot(b[i + 1] - ea[b[i]][0], b[i + 2] - ea[b[i]][1]) / 10 / dt
                        fast += v > 46
                self.assertLessEqual(math.hypot(b[2] - a[2], b[3] - a[3]) / 10 / dt, 160, gid)   # a hard shot is about 150 ft/s
            self.assertLessEqual(fast, 3, gid)

    def test_strength_shows_on_the_ice(self):
        tr = self.tracks[self.gids[0]]
        P = tr["players"]
        counts = []
        for f in tr["frames"][::25]:
            n = [0, 0]
            for i in range(6, len(f), 5):
                if f[i + 4] != ice2d.BOXED and P[f[i]]["pos"] != "G":
                    n[P[f[i]]["side"]] += 1
            counts += n
            self.assertLessEqual(max(n), 11)                                # a full change: five going off, five coming on
        counts.sort()
        self.assertEqual(counts[len(counts) // 2], 5)

    def test_deterministic(self):
        gid = self.gids[0]
        again = ice2d.track(self.c, gid)
        self.assertEqual(again["frames"][:4000], self.tracks[gid]["frames"][:4000])
        self.assertEqual(again["marks"], self.tracks[gid]["marks"])

    def test_reads_a_save_without_the_newer_columns(self):
        """A save from before jersey numbers and handedness: the roster query adapts to the columns that exist."""
        with tempfile.TemporaryDirectory() as tmp:
            old = sqlite3.connect(f"{tmp}/old.db")
            self.c.backup(old)
            old.row_factory = sqlite3.Row
            cols = {r[1] for r in old.execute("PRAGMA table_info(players)")}
            if "jersey_number" in cols:
                old.execute("ALTER TABLE players DROP COLUMN jersey_number")
            old.commit()
            tr = ice2d.track(old, self.gids[0])
            self.assertTrue(all(p["num"] is None for p in tr["players"]))
            self.assertEqual(len(tr["frames"]), len(self.tracks[self.gids[0]]["frames"]))
            old.close()

    def test_results_untouched(self):
        before = self.c.execute("SELECT COUNT(*), SUM(home_goals), SUM(away_goals) FROM games WHERE played=1").fetchone()
        n = self.c.total_changes
        ice2d.track(self.c, self.gids[1])
        self.assertEqual(self.c.total_changes, n)                           # the 2D game writes nothing
        self.assertEqual(tuple(before), tuple(self.c.execute("SELECT COUNT(*), SUM(home_goals), SUM(away_goals) FROM games WHERE played=1").fetchone()))


if __name__ == "__main__":
    unittest.main()
