"""v46: college hockey - eligibility (old rules and 5-in-5), recruiting, enrolment and graduation, paths for your
prospects, the college free-agent market."""
import datetime
import tempfile
import unittest

from hs.game import college as CO
from hs.game.state import get_state

from test_world import small_world


class EligibilityTests(unittest.TestCase):
    def test_old_rules(self):
        self.assertEqual(CO.allowed_seasons("2006-03-01", 2025), (4, "old"))      # 19 at enrolment
        self.assertEqual(CO.allowed_seasons("2004-03-01", 2026), (3, "old"))      # 22: one season lost

    def test_five_in_five(self):
        self.assertEqual(CO.clock_start("2009-03-01"), 2028)
        self.assertEqual(CO.clock_start("2009-09-01"), 2029)                       # turns 19 after the year began
        self.assertEqual(CO.allowed_seasons("2009-03-01", 2028), (5, "5in5"))      # enrols the year he turns 19
        self.assertEqual(CO.allowed_seasons("2009-03-01", 2027), (5, "5in5"))      # enrols early: the clock starts then
        self.assertEqual(CO.allowed_seasons("2007-03-01", 2028), (3, "5in5"))      # two junior years after 19
        self.assertEqual(CO.allowed_seasons("2002-03-01", 2028)[0], 0)             # too old


class CollegeWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.conn, cls.me = small_world(cls.tmp.name)
        CO.setup(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_1_setup(self):
        c = self.conn
        progs = CO.programs(c)
        self.assertTrue(progs)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM college_programs").fetchone()[0], len(progs))
        n = c.execute("SELECT COUNT(*) FROM players WHERE club_id IN (%s) AND status<>'retired'" % ",".join(map(str, progs))).fetchone()[0]
        self.assertEqual(c.execute("SELECT COUNT(*) FROM college_players WHERE status='enrolled'").fetchone()[0], n)
        for p in c.execute("SELECT prestige FROM college_programs"):
            self.assertTrue(5 <= p[0] <= 99)

    def test_2_recruiting(self):
        c = self.conn
        day = get_state(c)[0]
        n = CO.recruit_round(c, day)
        self.assertGreater(n, 0)
        pro = CO._pro(c)
        for pid, t, ey in c.execute("SELECT player_id, team_id, enroll_year FROM college_commits WHERE status='committed'"):
            self.assertNotIn(pid, pro)
            self.assertIn(t, CO.programs(c))
            self.assertIn(ey, (CO._next_season(c), CO._next_season(c) + 1))
        # no program is promised more players than it has room for next season
        st = CO._program_state(c, CO._next_season(c))
        self.assertTrue(all(v >= 0 for s in st.values() for v in s["open"].values()))
        v = CO.view(c)
        self.assertTrue(v["programs"] and v["commits"])

    def test_3_path(self):
        c = self.conn
        r = c.execute("SELECT player_id FROM players WHERE team_id IS NULL AND status='active' AND club_id IS NOT NULL LIMIT 1").fetchone()
        pid = r[0]
        c.execute("INSERT OR REPLACE INTO draft_rights VALUES (?,?,?,?,?)", (pid, self.me, 2025, 40, 2029))
        self.assertIn("junior", CO.set_path(c, pid, "junior"))
        self.assertFalse(CO.college_bound(c, pid, "USA", "USHL"))
        CO.set_path(c, pid, "college")
        self.assertTrue(CO.college_bound(c, pid, "SWE", "EUROPE"))
        other = c.execute("SELECT player_id FROM players WHERE team_id IS NULL AND status='active' AND player_id<>? AND "
                          "player_id NOT IN (SELECT player_id FROM draft_rights) LIMIT 1", (pid,)).fetchone()[0]
        with self.assertRaises(ValueError):
            CO.set_path(c, other, "college")
        CO.set_path(c, pid, "none")

    def test_4_summer(self):
        c = self.conn
        y = CO._season(c) + 1
        # one senior, one freshman
        senior, fresh = [r[0] for r in c.execute("SELECT player_id FROM college_players WHERE status='enrolled' LIMIT 2")]
        c.execute("UPDATE college_players SET enrolled=?, seasons=4 WHERE player_id=?", (y - 4, senior))
        c.execute("UPDATE college_players SET enrolled=?, seasons=4 WHERE player_id=?", (y - 1, fresh))
        commits = [r[0] for r in c.execute("SELECT player_id FROM college_commits WHERE status='committed' AND enroll_year=?", (y,))]
        lines = CO.summer(c, get_state(c)[0])
        self.assertTrue(lines and lines[0].startswith("College:"))
        self.assertEqual(c.execute("SELECT status FROM college_players WHERE player_id=?", (senior,)).fetchone()[0], "graduated")
        self.assertIsNone(c.execute("SELECT club_id FROM players WHERE player_id=?", (senior,)).fetchone()[0])
        self.assertEqual(c.execute("SELECT status FROM college_players WHERE player_id=?", (fresh,)).fetchone()[0], "enrolled")
        self.assertIn(senior, CO.no_college(c))
        enrolled = [p for p in commits if c.execute("SELECT status FROM college_commits WHERE player_id=?", (p,)).fetchone()[0] == "enrolled"]
        self.assertTrue(enrolled)
        for p in enrolled:
            club = c.execute("SELECT club_id FROM players WHERE player_id=?", (p,)).fetchone()[0]
            self.assertEqual(club, c.execute("SELECT team_id FROM college_players WHERE player_id=?", (p,)).fetchone()[0])
        self.assertEqual(CO.summer(c, get_state(c)[0]), [])          # once a summer

    def test_5_free_agents(self):
        c = self.conn
        y = CO._season(c)
        day = get_state(c)[0]
        lid = CO.ncaa_league(c)
        # make a strong, undrafted senior
        pid = c.execute("SELECT p.player_id FROM players p JOIN college_players cp USING (player_id) WHERE cp.status='enrolled' AND "
                        "p.player_id NOT IN (SELECT player_id FROM draft_rights) LIMIT 1").fetchone()[0]
        c.execute("UPDATE college_players SET enrolled=?, seasons=4 WHERE player_id=?", (y - 3, pid))
        c.execute("UPDATE player_attributes SET " + ", ".join(f"{k}=16" for k in ("speed", "shot_accuracy", "passing", "puck_control",
                  "offensive_awareness", "positioning", "defensive_awareness", "checking", "stick_checking", "strength", "reflexes",
                  "goalie_positioning", "glove", "blocker")) + " WHERE player_id=?", (pid,))
        CO.open_market(c, day, y)
        self.assertEqual(c.execute("SELECT status FROM college_fa WHERE player_id=?", (pid,)).fetchone()[0], "open")
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state','regular_season')")
        msg = CO.offer(c, pid, self.me, now=True, day=day)
        self.assertIn("decides by", msg)
        later = (datetime.date.fromisoformat(day) + datetime.timedelta(days=CO.CFA_DAYS + 1)).isoformat()
        CO._ai_offers(c, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat(), 1)
        CO.decide(c, later)
        r = c.execute("SELECT status, signed_team FROM college_fa WHERE player_id=?", (pid,)).fetchone()
        self.assertEqual(r[0], "signed")
        p = c.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
        self.assertEqual(p[0], r[1])
        self.assertTrue(c.execute("SELECT 1 FROM contracts WHERE player_id=? AND contract_type='entry_level'", (pid,)).fetchone())
        with self.assertRaises(ValueError):
            CO.offer(c, pid, self.me)


if __name__ == "__main__":
    unittest.main()


class DraftGoalieTests(unittest.TestCase):
    """v46: AI clubs no longer fill the draft with goalies (at most one a club, rarely in round one)."""

    def test_goalies_per_club(self):
        from collections import Counter
        from hs.game import draft as D
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db, c, me = small_world(tmp.name)
        self.addCleanup(c.close)
        y = D.draft_year(c)
        pool = D.eligible_rows(c, y)
        b = D._Board(c, y, pool)
        teams = [r[0] for r in c.execute("SELECT team_id FROM teams WHERE league_id=1")]
        per, avail, total = Counter(), list(pool), 0
        for rnd in range(1, 8):
            for t in teams:
                if not avail:
                    break
                x = b.choose(t, rnd, avail)
                avail.remove(x)
                per[t] += x["goalie"]
                total += 1
        self.assertLessEqual(max(per.values() or [0]), 1)
        self.assertLessEqual(sum(per.values()), max(2, total // 5))
