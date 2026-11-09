"""v45: expansion - announcing a club, the club coming into being, protection lists, the expansion draft, the entry
draft slot, and schedules for a league with uneven divisions."""
import tempfile
import unittest
from collections import Counter

from hs.game import expansion as XP
from hs.game import roster as R
from hs.game.state import get_state
from hs.league.rules import opponent_counts

from test_world import small_world


def _teams(sizes):
    out, i = [], 1
    for (c, d), n in sizes.items():
        for _ in range(n):
            out.append(dict(team_id=i, conference=c, division=d))
            i += 1
    return out


RULES = {"schedule": {"games_per_team": 84, "same_division": {"games": 4, "reduced_games": 4, "reduced_opponents_per_team": 0},
                      "same_conference": {"games": 3}, "other_conference": {"games": 2}}}


class ScheduleBalanceTests(unittest.TestCase):
    def test_uneven_divisions_still_play_84(self):
        for sizes in ((9, 8, 8, 8), (9, 9, 8, 8), (9, 9, 9, 8), (10, 9, 9, 8)):
            T = _teams(dict(zip([("E", "A"), ("E", "M"), ("W", "C"), ("W", "P")], sizes)))
            c = opponent_counts(T, RULES)
            tot = Counter()
            for (a, b), g in c.items():
                tot[a] += g
                tot[b] += g
            self.assertEqual(set(tot.values()), {84}, sizes)
            self.assertGreaterEqual(min(c.values()), 1)            # everyone still meets everyone

    def test_even_divisions_unchanged(self):
        T = _teams({("E", "A"): 8, ("E", "M"): 8, ("W", "C"): 8, ("W", "P"): 8})
        c = opponent_counts(T, RULES)
        self.assertEqual(Counter(c.values()), Counter({2: 256, 3: 128, 4: 112}))


class ExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.conn, cls.me = small_world(cls.tmp.name)
        c = cls.conn
        cls.day = get_state(c)[0]
        cls.year = XP._season(c)
        # a season's games on file, so players meet the exposure rules
        top = c.execute("SELECT league_id FROM teams WHERE team_id=?", (cls.me,)).fetchone()[0]
        for pid, tid, pos in c.execute("SELECT player_id, team_id, position FROM players WHERE team_id IN (%s) AND status='active'"
                                       % ",".join(map(str, XP._top(c)))).fetchall():
            t = "goalie_season_stats" if pos == "G" else "skater_season_stats"
            c.execute(f"INSERT INTO {t} (player_id, season_start_year, team_id, league_id, split, gp) VALUES (?,?,?,?, 'RS', 60)",
                      (pid, cls.year, tid, top))
            c.execute(f"INSERT INTO {t} (player_id, season_start_year, team_id, league_id, split, gp) VALUES (?,?,?,?, 'RS', 60)",
                      (pid, cls.year - 1, tid, top))
            c.execute(f"INSERT INTO {t} (player_id, season_start_year, team_id, league_id, split, gp) VALUES (?,?,?,?, 'RS', 60)",
                      (pid, cls.year - 2, tid, top))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_1_announce_validates(self):
        c = self.conn
        taken = c.execute("SELECT abbr FROM teams WHERE team_id=?", (self.me,)).fetchone()[0]
        with self.assertRaises(ValueError):
            XP.announce(c, self.day, "Somewhere", "Things", taken)
        with self.assertRaises(ValueError):
            XP.announce(c, self.day, "", "Things", "SMW")
        n = len(XP._top(c))
        eid = XP.announce(c, self.day, "Houston", "Wildcatters", "HOU", by_user=True)
        self.assertTrue(eid)
        with self.assertRaises(ValueError):                        # one at a time
            XP.announce(c, self.day, "Austin", "Lonestars", "AUS")
        e = XP.pending(c)
        self.assertEqual((e["status"], e["first_season"]), ("announced", self.year + 1))
        self.assertEqual(len(XP._top(c)), n)                       # nothing exists until the season ends

    def test_2_club_comes_into_being(self):
        c = self.conn
        n = len(XP._top(c))
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state','finished')")
        XP.season_over(c, self.day)
        e = XP.pending(c)
        self.assertEqual(e["status"], "protecting")
        self.assertEqual(len(XP._top(c)), n + 1)
        tid = e["team_id"]
        self.assertIsNotNone(R.affiliate(c, tid))
        self.assertTrue(c.execute("SELECT 1 FROM board WHERE team_id=?", (tid,)).fetchone())
        self.assertTrue(c.execute("SELECT 1 FROM club_finance WHERE team_id=?", (tid,)).fetchone())
        self.assertTrue(c.execute("SELECT 1 FROM staff WHERE team_id=?", (tid,)).fetchone())
        # every other club has a protection list
        for t in XP._top(c):
            if t != tid:
                self.assertIsNotNone(XP.protection(c, t), t)

    def test_3_protection_rules(self):
        c = self.conn
        pl = XP.pool(c, self.me)
        scheme, pids = XP.auto_protect(c, self.me, pl)
        self.assertIn(scheme, XP.PROTECT_SCHEMES)
        g = Counter(pl[p]["group"] for p in pids)
        if scheme == "7-3-1":
            self.assertLessEqual((g["F"], g["D"]), (7, 3))
        else:
            self.assertLessEqual(g["F"] + g["D"], 8)
        self.assertLessEqual(g["G"], 1)
        self.assertEqual(XP.validate(c, self.me, scheme, pids, pl), [])
        skaters = [p for p in pl if pl[p]["group"] != "G" and pl[p]["eligible"]][:9]
        if len(skaters) == 9:
            self.assertTrue(XP.validate(c, self.me, "8-1", skaters, pl))   # nine skaters is too many
        self.assertTrue(all(pl[p]["eligible"] or pl[p]["nmc"] for p in pids))
        XP.set_protection(c, self.me, scheme, pids)
        self.assertTrue(XP.protection(c, self.me)["by_user"])
        exp = {x["player_id"] for x in XP.exposed(c, self.me)}
        self.assertFalse(exp & set(pids))
        self.assertFalse(any(pl[p]["exempt"] for p in exp))

    def test_4_draft(self):
        c = self.conn
        e = XP.pending(c)
        tid = e["team_id"]
        before = {t: len(R.roster(c, t)) + len(R.prospects(c, t)) for t in XP._top(c)}
        prot = {t: set(XP.protection(c, t)["players"]) for t in XP._top(c) if t != tid}
        XP.run_draft(c, self.day)
        picks = c.execute("SELECT from_team, player_id FROM expansion_picks WHERE exp_id=?", (e["exp_id"],)).fetchall()
        froms = [r[0] for r in picks]
        self.assertEqual(len(froms), len(set(froms)))              # at most one from each club
        self.assertGreaterEqual(len(froms), len(XP._top(c)) - 2)
        for t, pid in picks:
            self.assertEqual(c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0], tid)
            self.assertNotIn(pid, prot[t])
        self.assertEqual(XP.pending(c), None)
        self.assertEqual(c.execute("SELECT status FROM expansion WHERE exp_id=?", (e["exp_id"],)).fetchone()[0], "drafted")
        self.assertTrue(c.execute("SELECT 1 FROM league_events WHERE event_type='EXPANSION_PICK'").fetchone())
        self.assertGreater(len(R.roster(c, tid)) + len(R.prospects(c, tid)), 10)
        self.assertTrue(XP.view(c)["last_draft"]["picks"])
        # the new club drafts third-worst in the entry draft
        from hs.game import draft as D
        self.assertIn(tid, XP.draft_slot_teams(c, D.draft_year(c)))

    def test_5_announce_off_mode(self):
        c = self.conn
        XP.set_mode(c, "off")
        self.assertEqual(XP.mode(c), "off")
        with self.assertRaises(ValueError):
            XP.set_mode(c, "always")


if __name__ == "__main__":
    unittest.main()


class LegacyScoreTests(unittest.TestCase):
    """The Career Legacy Score and the Hall of Fame queue (hs/game/legacy_score.py)."""

    def test_pvl_and_tiers(self):
        from hs.game import legacy_score as LS
        v, peak, rest = LS.pvl([2.5] * 7)
        self.assertAlmostEqual(v, 175.0)
        v2, _, _ = LS.pvl([1.0] * 15)                  # fifteen average seasons: 7x10 + 8x3
        self.assertAlmostEqual(v2, 94.0)
        self.assertGreater(v, v2)                       # the peak beats the accumulator
        self.assertEqual(LS.tier(451), "Inner Circle")
        self.assertEqual(LS.tier(350), "First Ballot")
        self.assertEqual(LS.tier(250), "Hall of Fame")
        self.assertEqual(LS.tier(180), "Hall of Very Good")
        self.assertEqual(LS.tier(179.9), "")

    def test_order_and_votes(self):
        from hs.game import legacy_score as LS
        c = [dict(player_id=1, cls=300, years_on_ballot=1), dict(player_id=2, cls=300, years_on_ballot=4),
             dict(player_id=3, cls=290, years_on_ballot=1), dict(player_id=4, cls=260, years_on_ballot=1)]
        self.assertEqual([x["player_id"] for x in LS.order(c)], [2, 1, 3, 4])      # a tie: longer on the ballot first
        self.assertEqual([x["player_id"] for x in LS.order(c, [3])], [3, 2, 1, 4])  # backed, within 15 points
        self.assertEqual([x["player_id"] for x in LS.order(c, [4])][:3], [2, 1, 3])  # 40 points back: no help

    def test_season_values_and_queue(self):
        from hs.game import legacy as LG
        from hs.game import legacy_score as LS
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db, c, me = small_world(tmp.name)
        self.addCleanup(c.close)
        lg = LS._top(c)
        fw = [r[0] for r in c.execute("SELECT player_id FROM players WHERE position IN ('C','LW','RW') LIMIT 400")]
        star, avg = fw[0], fw[1]
        # twelve seasons ending in 2015: 380 ordinary forwards at 30 points, one star at 90, one at exactly the average
        for y in range(2004, 2016):
            for k, pid in enumerate(fw[2:]):
                c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a, club_name) "
                          "VALUES (?,?,NULL,?, 'RS', 82, 12, 18, ?)", (pid, y, lg, f"club {k % 32}"))
            c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a) VALUES (?,?,NULL,?,'RS',82,45,45)", (star, y, lg))  # noqa
            c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a) VALUES (?,?,NULL,?,'RS',82,12,18)", (avg, y, lg))
        sv = LS.season_values(c)
        self.assertAlmostEqual(sv[avg][2010], 1.0, delta=0.05)
        self.assertGreater(sv[star][2010], 2.5)
        c.execute("UPDATE players SET status='retired' WHERE player_id IN (?,?)", (star, avg))
        s = LS.score(c, star, sv[star])
        self.assertIn(("500 goals", 20), s["items"])
        self.assertIn(("1,000 points", 20), s["items"])
        self.assertGreaterEqual(s["cls"], 250)
        # retired after 2015-16: eligible from 2019 (three years), on the ballot until 2028
        self.assertFalse([x for x in LS.candidates(c, 2018) if x["player_id"] == star])
        got = [x for x in LS.candidates(c, 2019) if x["player_id"] == star]
        self.assertTrue(got and got[0]["years_on_ballot"] == 1)
        self.assertTrue([x for x in LS.candidates(c, 2028) if x["player_id"] == star])
        self.assertFalse([x for x in LS.candidates(c, 2029) if x["player_id"] == star])
        self.assertFalse([x for x in LS.candidates(c, 2019) if x["player_id"] == avg])   # below 250
        v = LG.legacy_view(c, star)
        self.assertEqual(v["cls"], s["cls"])
