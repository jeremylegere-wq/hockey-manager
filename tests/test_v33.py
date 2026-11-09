"""v33, phase B: the twelve tactical settings (fit, execution, break-even, counters, league neutrality), preferences
in the engine (goalie pulls, the hook, line matching, ice time), overtime units, tendencies, chemistry and roles."""
import statistics
import tempfile
import unittest

from hs.game import chemistry as CH
from hs.game import lineup as L
from hs.game import roles as RL
from hs.game import tactics as TC
from hs.game.state import get_state
from hs.sim.engine import Skill, simulate_game
from hs.sim.loader import load_teams

from test_game import make_db
from test_sim import ENV


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]


class TacticsModelTests(Base):
    def test_every_option_breaks_even_at_average(self):
        for k, (_, _, _, opts) in TC.SETTINGS.items():
            for o, (_, _, fx) in opts.items():
                if fx and TC.BALANCE[(k, o)] < 3.0:
                    self.assertAlmostEqual(TC.expected_value(TC.option_multipliers(k, o, 1.0)), 0.0, places=4, msg=(k, o))
                    self.assertGreater(TC.expected_value(TC.option_multipliers(k, o, 1.3)), 0, (k, o))

    def test_presets_and_settings(self):
        TC.set_system(self.c, self.me, "heavy forecheck")
        s = TC.settings_of(self.c, self.me)
        self.assertEqual(s["forecheck"], "aggressive")
        self.assertEqual(TC.system_of(self.c, self.me), "heavy forecheck")
        TC.set_setting(self.c, self.me, "pp_setup", "umbrella")
        self.assertEqual(TC.settings_of(self.c, self.me)["pp_setup"], "umbrella")
        self.assertEqual(TC.settings_of(self.c, self.me)["forecheck"], "aggressive")     # the rest kept
        with self.assertRaises(Exception):
            TC.set_setting(self.c, self.me, "forecheck", "nonsense")
        TC.set_pref(self.c, self.me, "goalie_hook", "never")
        self.assertEqual(TC.prefs_of(self.c, self.me)["goalie_hook"], "never")

    def test_engine_effects_are_league_neutral(self):
        TC.ai_choose(self.c)
        TC.set_system(self.c, self.me, "defensive structure")
        fx = TC.engine_effects(self.c)
        for k in TC.KEYS:
            self.assertAlmostEqual(statistics.fmean(m[k] for m in fx.values()), 1.0, places=9, msg=k)

    def test_counters(self):
        a = dict(TC.DEFAULTS, breakout="stretch")
        self.assertGreater(TC.counters(a, dict(TC.DEFAULTS, forecheck="aggressive"))["att"], 1)
        self.assertLess(TC.counters(a, dict(TC.DEFAULTS, forecheck="passive"))["att"], 1)
        self.assertEqual(TC.counters(TC.DEFAULTS, TC.DEFAULTS), dict(att=1.0, qual=1.0, pp_att=1.0, pp_qual=1.0))
        sc = TC.scout_opponent(self.c, self.me, self.other)
        self.assertIn("tips", sc)


class EnginePrefsTests(Base):
    def _games(self, n=150):
        teams = load_teams(self.c)
        h, a = teams[self.me], teams[self.other]
        return [simulate_game(h, a, ENV, Skill(), s) for s in range(n)]

    def test_never_pull_means_no_extra_attacker(self):
        TC.ai_choose(self.c)
        for t in (self.me, self.other):
            TC.set_pref(self.c, t, "pull_down1", "never")
            TC.set_pref(self.c, t, "pull_down2", "never")
        self.assertEqual(sum(r.team[0]["en_goals"] + r.team[1]["en_goals"] for r in self._games()), 0)

    def test_the_hook(self):
        TC.set_pref(self.c, self.me, "goalie_hook", "after 3 goals")
        teams = load_teams(self.c)
        g = [p.pid for p in teams[self.me].goalies]
        if len(g) < 2:
            self.skipTest("one goalie")
        used = set()
        for r in self._games(200):
            used |= {pid for pid, s in r.stats.items() if s["team"] == 0 and pid in g and s["toi"]}
        self.assertEqual(len(used), 2)                  # the backup came in at some point


class LineupExtrasTests(Base):
    def test_ot_units_and_tendencies(self):
        cur = L.current(self.c, self.me)
        f1, d1 = cur["F"][0], cur["D"][0]
        L.set_unit(self.c, self.me, "OT31", [f1[0], f1[1], d1[0]])
        self.assertEqual(L.saved(self.c, self.me)["OT3"][0], [f1[0], f1[1], d1[0]])
        L.set_tendency(self.c, self.me, f1[1], "shoot first")
        teams = load_teams(self.c)
        p = teams[self.me].by_id[f1[1]]
        self.assertGreater(p.shoot_w, 1)
        self.assertEqual(len(teams[self.me].ot3), 1)
        L.set_tendency(self.c, self.me, f1[1], "normal")
        self.assertNotIn(str(f1[1]), L.saved(self.c, self.me).get("tend", {}))


class ChemistryAndRolesTests(Base):
    def test_chemistry_builds(self):
        teams = load_teams(self.c)
        day = get_state(self.c)[0]
        for _ in range(CH.FULL):
            CH.record(self.c, teams[self.me], day)
        CH.record(self.c, teams[self.other], day)
        ch = CH.load(self.c, day)
        self.assertGreater(max(ch[self.me].values()), max(ch[self.other].values()))
        v = CH.team_view(self.c, teams[self.me], day)
        self.assertEqual(v[0]["chemistry"], 100)

    def test_roles(self):
        r = RL.team_roles(self.c, self.me)
        self.assertTrue(r)
        for x in r.values():
            self.assertTrue(0 <= x["fit"] <= 100)
        a = {k: 10 for k in ("shot_accuracy", "shot_power", "offensive_awareness", "passing", "puck_control", "strength", "net_presence",
                             "hitting", "defensive_awareness", "positioning", "stick_checking", "faceoffs", "checking", "endurance",
                             "determination", "toughness", "aggression")}
        a.update(shot_accuracy=17, shot_power=16)
        self.assertEqual(RL.major_role(a, "LW")[0], "Sniper")


if __name__ == "__main__":
    unittest.main()
