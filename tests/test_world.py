import datetime
import random
import sqlite3
import statistics
import tempfile
import unittest
from pathlib import Path

from hs.datapack import load_pack, validate
from hs.game import draft as D
from hs.game import offseason as O
from hs.game import roster as R
from hs.game import world as Wd
from hs.game.dayloop import sim_until
from hs.game.state import connect, new_game
from hs.ingest import build_db
from hs.leaguedata.world_2025_26 import NAMES
from hs.sim.engine import Skill
from hs.tools.build_world import build
from hs.tools.make_example_pack import generate
from hs.worldgen import age_mean_offset, apply_change, gen_player, overall_of, yearly_change

from test_sim import ENV


def cohort_curve(n=800, pos="C", seed=3):
    rng = random.Random(seed)
    people = []
    for _ in range(n):
        _, a, prof = gen_player(rng, NAMES, "CAN", pos, 16, 2025, 7.6 + age_mean_offset(16, "junior"))
        people.append([a, prof])
    means = {}
    for age in range(16, 41):
        ovs = [overall_of(p[0], pos) for p in people]
        means[age] = (statistics.mean(ovs), sum(o >= 9.6 for o in ovs) / len(ovs))
        for p, ov in zip(people, ovs):
            p[0] = apply_change(p[0], pos, yearly_change(age, ov, p[1], rng), rng, age)
    return means


class AgeingCurveTests(unittest.TestCase):
    def test_shape_matches_the_brief(self):
        m = cohort_curve()
        self.assertLess(m[18][0], m[21][0])                 # growing through junior
        self.assertLess(m[21][0], m[25][0])                 # still growing to the mid-20s peak
        self.assertAlmostEqual(m[25][0], m[29][0], delta=0.15)   # plateau
        self.assertGreater(m[29][0] - m[34][0], 0.2)        # decline from about 30
        self.assertGreater(m[34][0] - m[39][0], 2 * (m[29][0] - m[34][0]) * 0.8)   # steeper 35-40
        self.assertLess(m[18][1], 0.05)                     # few are NHL calibre at 18
        self.assertTrue(0.05 < m[25][1] < 0.35)             # a minority of juniors ever get there

    def test_goalies_peak_later(self):
        sk, g = cohort_curve(pos="C"), cohort_curve(pos="G")
        self.assertGreater(g[33][0] - g[27][0], sk[33][0] - sk[27][0])


def small_world(tmp):
    base = Path(tmp) / "base"
    generate(base)
    world = Path(tmp) / "world"
    build(base, world, seed=2, nhl_roster=20, only=["AHL", "OHL", "SHL", "NCAA"], clubs_per_league=8)
    db = str(Path(tmp) / "w.db")
    build_db(world, db, overwrite=True)
    new_game(db, "NLT", 4)
    conn = connect(db)
    return db, conn, conn.execute("SELECT team_id FROM teams WHERE abbr='NLT'").fetchone()[0]


class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.conn, cls.me = small_world(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_world_pack_is_valid_and_affiliated(self):
        issues = validate(load_pack(Path(self.tmp.name) / "world"))
        self.assertEqual([i for i in issues if i.level == "error"], [])
        meta = Wd.world_meta(self.conn)
        self.assertEqual({m["abbr"] for m in meta.values()}, {"AHL", "OHL", "SHL", "NCAA"})
        for (t,) in self.conn.execute("SELECT team_id FROM teams WHERE league_id=1"):
            self.assertIsNotNone(R.affiliate(self.conn, t))
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM draft_rights").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM players p LEFT JOIN player_dev d USING (player_id) "
                                           "WHERE p.status<>'retired' AND d.player_id IS NULL").fetchone()[0], 0)

    def test_send_down_and_recall_move_the_club(self):
        pid = self.conn.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position='C'",
                                (self.me,)).fetchone()[0]
        R.send_down(self.conn, self.me, pid, "2026-10-01")
        self.assertEqual(self.conn.execute("SELECT club_id FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                         R.affiliate(self.conn, self.me))
        R.call_up(self.conn, self.me, pid, "2026-10-01", check=False)
        self.assertEqual(self.conn.execute("SELECT club_id FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                         self.me)
        self.conn.rollback()

    def test_club_players_are_not_free_agents(self):
        fas = {pid for _, pid, _ in R.free_agents(self.conn)}
        clubbed = {r[0] for r in self.conn.execute("SELECT player_id FROM players WHERE club_id IS NOT NULL")}
        self.assertFalse(fas & clubbed)


class WorldSeasonTests(unittest.TestCase):
    def test_season_draft_and_summer(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, conn, me = small_world(tmp)
            sim_until(conn, ENV, Skill(), to_end=True)
            year = Wd.season_year(conn)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM skater_season_stats WHERE season_start_year=? AND "
                                            "league_id<>1", (year,)).fetchone()[0], 100)
            lines = O.advance(conn, ENV, Skill())                         # draft
            self.assertEqual(Wd.season_year(conn), year)
            picks = conn.execute("SELECT COUNT(*) FROM draft_picks WHERE draft_year=?", (year + 1,)).fetchone()[0]
            self.assertEqual(picks, 7 * 8)
            on_clock = any("on the clock" in l for l in lines)
            if on_clock:
                best = D.board(conn, me, 5)[0][0]
                D.user_pick(conn, best, "2027-06-26")
                self.assertEqual(conn.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (best,)).fetchone()[0], me)
            while Wd.season_year(conn) == year:
                O.advance(conn, ENV, Skill())
            made = conn.execute("SELECT COUNT(*) FROM draft_picks WHERE player_id IS NOT NULL").fetchone()[0]
            self.assertGreater(made, 40)
            # every non-NHL club is back at full strength, and the NHL clubs can dress a lineup
            meta = Wd.world_meta(conn)
            sizes = Wd.club_rosters(conn)
            for t, lid in Wd.club_league(conn).items():
                if lid in meta:
                    self.assertGreaterEqual(sizes.get(t, 0), meta[lid]["roster"])
            for (t,) in conn.execute("SELECT team_id FROM teams WHERE league_id=1"):
                self.assertEqual(R.shortages(conn, t), [] if t != me else R.shortages(conn, t))
            self.assertTrue(conn.execute("SELECT 1 FROM attribute_history WHERE season_start_year=?", (year,)).fetchone())
            sim_until(conn, ENV, Skill(), me, days=5, to_end=True)
            conn.close()


class CareerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.conn, self.me = small_world(self.tmp.name)
        self.addCleanup(self.conn.close)

    def test_washed_up_veteran_usually_retires_but_journeyman_plays_on(self):
        c = self.conn
        year = Wd.season_year(c)
        vets, journeymen = [], []
        for k in range(40):
            for kind, store in (("vet", vets), ("jm", journeymen)):
                cur = c.execute("INSERT INTO players (first_name, last_name, birth_date, position, status) VALUES "
                                "('A','B','1993-01-01','C','active')")
                pid = cur.lastrowid
                c.execute("INSERT INTO player_attributes (player_id, offensive_awareness, passing, puck_control, "
                          "shot_accuracy, positioning, defensive_awareness, hitting) VALUES (?,9,9,9,9,9,9,9)", (pid,))
                if kind == "vet":
                    c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, league_id, split, gp) "
                              "VALUES (?, 2015, 1, 'RS', 600)", (pid,))
                store.append(pid)
        out = dict(Wd.retirements(c, f"{year + 1}-06-26"))
        self.assertGreater(sum(p in out for p in vets), sum(p in out for p in journeymen) + 10)

    def test_development_by_age(self):
        c = self.conn
        rows = Wd.load_attrs(c)
        young = [p for p, r in rows.items() if Wd.age_on(r["birth_date"], datetime.date(2026, 9, 15)) in (18, 19)]
        before = {p: Wd.overall(rows[p]) for p in young}
        Wd.develop(c, "2027-09-15")
        after = Wd.load_attrs(c)
        self.assertGreater(statistics.mean(Wd.overall(after[p]) - before[p] for p in young), 0.1)

    def test_placement_and_fill(self):
        c = self.conn
        meta = Wd.world_meta(c)
        ahl = next(l for l, m in meta.items() if m["abbr"] == "AHL")
        club = c.execute("SELECT team_id FROM teams WHERE league_id=?", (ahl,)).fetchone()[0]
        moved = [r[0] for r in c.execute("SELECT player_id FROM players WHERE club_id=? AND team_id IS NULL LIMIT 3",
                                         (club,))]
        c.executemany("UPDATE players SET club_id=NULL WHERE player_id=?", [(p,) for p in moved])
        placed, _ = Wd.place_unattached(c, "2027-09-15")
        self.assertGreaterEqual(placed, 1)
        Wd.fill_clubs(c, "2027-09-15")
        sizes = Wd.club_rosters(c)
        for t, lid in Wd.club_league(c).items():
            if lid in meta:
                self.assertGreaterEqual(sizes.get(t, 0), meta[lid]["roster"])


class MigrationTests(unittest.TestCase):
    def test_old_save_gets_new_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "old.db"
            conn = sqlite3.connect(db)
            conn.executescript("CREATE TABLE teams (team_id INTEGER PRIMARY KEY, league_id INTEGER);"
                               "CREATE TABLE players (player_id INTEGER PRIMARY KEY, team_id INTEGER, status TEXT);"
                               "INSERT INTO players VALUES (1, 5, 'active');")
            conn.commit()
            conn.close()
            conn = connect(str(db))
            self.assertEqual(conn.execute("SELECT club_id FROM players WHERE player_id=1").fetchone()[0], 5)
            self.assertTrue(conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_rights'").fetchone())
            conn.close()


if __name__ == "__main__":
    unittest.main()
