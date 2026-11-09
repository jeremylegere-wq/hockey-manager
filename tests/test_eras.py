"""Rule eras: overtime format, ties, points, the 84-game schedule from 2026-27."""
import json
import random
import tempfile
import unittest

from hs.game import media as M
from hs.league import standings as ST
from hs.league.eras import describe, for_season
from hs.league.rules import check_rules, merged
from hs.league.schedule import build_schedule
from hs.leaguedata import nhl_2025_26 as nhl
from hs.sim.engine import Skill, simulate_game
from hs.sim.loader import load_teams

from test_game import make_db
from test_sim import ENV

NHL = merged(nhl.RULES)


def nhl_teams():
    return [dict(team_id=i, abbr=ab, conference=v[2], division=v[3]) for i, (ab, v) in enumerate(sorted(nhl.TEAMS.items()))]


class EraRuleTests(unittest.TestCase):
    def test_nhl_history(self):
        self.assertEqual(for_season(NHL, 1975)["overtime"]["format"], "none")
        r90 = for_season(NHL, 1990)
        self.assertEqual((r90["overtime"]["format"], r90["overtime"]["shootout"], r90["points"]["ot_loss"]), ("5v5", False, 0))
        r01 = for_season(NHL, 2001)
        self.assertEqual((r01["overtime"]["format"], r01["overtime"]["shootout"], r01["points"]["ot_loss"]), ("4v4", False, 1))
        self.assertTrue(for_season(NHL, 2010)["overtime"]["shootout"])
        self.assertEqual(for_season(NHL, 2025)["overtime"]["format"], "3v3")
        self.assertEqual(for_season(NHL, 2025)["schedule"]["games_per_team"], 82)
        self.assertEqual(for_season(NHL, 2026)["schedule"]["games_per_team"], 84)
        self.assertEqual(for_season(NHL, 2026)["playoffs"], NHL["playoffs"])       # untouched keys survive
        self.assertIn("84 games", describe(NHL, 2030))

    def test_custom_eras_and_no_preset(self):
        plain = dict(NHL)
        plain.pop("era_preset")
        self.assertEqual(for_season(plain, 2030)["schedule"]["games_per_team"], 82)
        custom = dict(plain, eras=[{"from": 2027, "overtime": {"format": "4v4"}}])
        self.assertEqual(for_season(custom, 2026)["overtime"]["format"], "3v3")
        r = for_season(custom, 2027)
        self.assertEqual((r["overtime"]["format"], r["overtime"]["minutes"]), ("4v4", 5))   # deep merge
        self.assertEqual(check_rules(dict(r, overtime={"format": "2v2"}), nhl_teams())[-1][:23], "unknown overtime format")

    def test_84_game_schedule(self):
        teams = nhl_teams()
        r = for_season(NHL, 2026)
        r["season"] = dict(r["season"], start="2026-10-07", end="2027-04-16", breaks=[])
        self.assertEqual(check_rules(r, teams), [])
        sched = build_schedule(teams, r, seed=3)
        per = {}
        for _, h, a in sched:
            per[h] = per.get(h, 0) + 1
            per[a] = per.get(a, 0) + 1
        self.assertEqual(set(per.values()), {84})
        div = {t["team_id"]: (t["conference"], t["division"]) for t in teams}
        pair = {}
        for _, h, a in sched:
            if div[h] == div[a]:
                k = tuple(sorted((h, a)))
                pair[k] = pair.get(k, 0) + 1
        self.assertEqual(set(pair.values()), {4})                     # four against every division rival


class TieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        _, cls.c, cls.me = make_db(cls.tmp.name)
        cls.teams = load_teams(cls.c)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def _run(self, ot, n=400):
        ids = sorted(self.teams)
        rng = random.Random(5)
        out = []
        for _ in range(n):
            h, a = rng.sample(ids, 2)
            out.append(simulate_game(self.teams[h], self.teams[a], ENV, Skill(), rng.getrandbits(40), events=False,
                                     overtime=ot))
        return out

    def test_overtime_formats(self):
        none = self._run({"format": "none", "minutes": 0, "shootout": False})
        self.assertTrue(any(r.tie for r in none))
        self.assertTrue(all(r.goals[0] == r.goals[1] for r in none if r.tie))
        self.assertFalse(any(r.went_to_ot for r in none))
        old = self._run({"format": "4v4", "minutes": 5, "shootout": False})
        ties = [r for r in old if r.tie]
        decided = [r for r in old if r.went_to_ot and not r.tie]
        self.assertTrue(ties and decided)
        self.assertFalse(any(r.shootout for r in old))
        modern = self._run({"format": "3v3", "minutes": 5, "shootout": True})
        self.assertFalse(any(r.tie for r in modern))
        # the default is the modern game: same results as before overtime became a rule
        same = self._run(None, 60)
        again = self._run({"format": "3v3", "minutes": 5, "shootout": True}, 60)
        self.assertEqual([r.goals for r in same], [r.goals for r in again])

    def test_ties_in_standings_and_media(self):
        rows = [(1, 2, 3, 3, 1), (2, 1, 2, 1, 0), (1, 2, 2, 2, 0)]      # tie after OT, regulation win, tie
        rec, h2h = ST._fill(rows, ST.defaultdict(lambda: dict(gp=0, w=0, l=0, otl=0, t=0, rw=0, row=0, gf=0, ga=0)),
                            ST.defaultdict(lambda: [0, 0]))
        self.assertEqual((rec[1]["t"], rec[1]["l"], rec[2]["w"], rec[2]["t"]), (2, 1, 1, 2))
        pts = for_season(NHL, 1990)["points"]
        self.assertEqual(ST.points(rec[1], pts), 2)
        self.assertEqual(ST.points(rec[2], pts), 4)
        # a tied game reads as a tie in the recap
        gid = self.c.execute("SELECT MIN(game_id) FROM games").fetchone()[0]
        self.c.execute("UPDATE games SET played=1, home_goals=2, away_goals=2, went_to_ot=1, seed=1 WHERE game_id=?",
                       (gid,))
        r = M.recap(self.c, gid)
        self.assertTrue("tie" in r["headline"].lower() or "draw" in r["headline"].lower()
                        or "no winner" in r["headline"].lower())
        self.c.rollback()


if __name__ == "__main__":
    unittest.main()
