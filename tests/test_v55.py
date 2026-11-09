"""v55: tactical roles: fit, execution and effects, assignment rules, the engine hooks, the loader's penalty
neutrality, AI clubs, the CLI."""
import io
import json
import tempfile
import unittest

from hs.game import troles as TR
from hs.game.cli import CLI
from hs.sim.engine import Player, Team, simulate_game, Skill
from hs.sim.loader import load_teams

from test_game import make_db
from test_sim import ENV


class RoleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = make_db(tmp.name)
        self.addCleanup(self.c.close)
        TR.ensure_table(self.c)

    def _skaters(self, team, pos):
        return [r[0] for r in self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position" +
                                             ("='D'" if pos == "D" else " IN ('C','LW','RW')"), (team,))]

    def test_fit_scale(self):
        c = self.c
        fs = [f for pid in self._skaters(self.me, "F") for f in [TR.fits(c, pid).get("shadow")] if f is not None]
        self.assertTrue(fs and all(0 <= f <= 100 for f in fs))
        allf = []
        for (pid,) in c.execute("SELECT player_id FROM players WHERE status='active' AND position='D' AND team_id IS NOT NULL").fetchall():
            f = TR.fits(c, pid).get("shutdown")
            if f is not None:
                allf.append(f)
        self.assertAlmostEqual(sum(allf) / len(allf), 50, delta=8)
        self.assertNotIn("shutdown", TR.fits(c, self._skaters(self.me, "F")[0]))
        self.assertEqual(TR.execution(50), 1.0)
        self.assertAlmostEqual(TR.execution(75), 1.4)

    def test_effects_scale_upside_not_cost(self):
        lo, _ = TR.effects("shutdown", 30)
        hi, _ = TR.effects("shutdown", 80)
        self.assertLess(hi["ev"]["allow"], lo["ev"]["allow"])        # more suppression with a better fit
        self.assertEqual(hi["ev"]["att"], lo["ev"]["att"])            # the same cost
        fx, extra = TR.effects("trigger", 70)
        self.assertEqual(set(fx), {"pp"})
        self.assertEqual(fx["pp"]["shoot"], 1.8)
        fx, _ = TR.effects("pk_specialist", 60)
        self.assertLess(fx["sh"]["allow"], 1.0)
        self.assertLess(fx["ev"]["att"], 1.0)
        self.assertTrue(TR.effects("enforcer", 60)[1]["protect"])

    def test_assignment_rules(self):
        c, me = self.c, self.me
        f, d = self._skaters(me, "F"), self._skaters(me, "D")
        with self.assertRaises(ValueError):
            TR.set_role(c, me, f[0], "shutdown")                        # a defence role
        with self.assertRaises(ValueError):
            TR.set_role(c, me, f[0], "goon")
        other = c.execute("SELECT player_id FROM players WHERE team_id<>? AND status='active' AND position='C' LIMIT 1", (me,)).fetchone()[0]
        with self.assertRaises(ValueError):
            TR.set_role(c, me, other, "shadow")
        TR.set_role(c, me, f[0], "shadow")
        TR.set_role(c, me, f[1], "shadow")
        with self.assertRaises(ValueError):
            TR.set_role(c, me, f[2], "shadow")                          # two at most
        TR.set_role(c, me, f[0], "none")
        self.assertNotIn(f[0], TR.team_roles(c, me))
        out = TR.suggest(c, me)
        self.assertTrue(all(fit >= TR.SUGGEST_FIT for _, fit in out.values()))
        roles = [r for r, _ in out.values()]
        self.assertTrue(all(roles.count(r) <= (2 if r == "pk_specialist" else 1) for r in roles))
        self.assertEqual(set(TR.team_roles(c, me)), set(out))

    def test_loader_and_neutral_penalties(self):
        c, me = self.c, self.me
        TR.ai_assign(c)
        TR.suggest(c, me)
        teams = load_teams(c)
        with_role = [p for t in teams.values() for p in t.skaters if p.rfx]
        self.assertTrue(with_role)
        norms = {round(t.role_pen, 6) for t in teams.values()}
        self.assertEqual(len(norms), 1)                                 # one league factor
        # a traded player leaves his role behind
        pid = next(iter(TR.team_roles(c, me)))
        other = c.execute("SELECT team_id FROM teams WHERE team_id<>? LIMIT 1", (me,)).fetchone()[0]
        c.execute("UPDATE players SET team_id=? WHERE player_id=?", (other, pid))
        self.assertNotIn(pid, TR.engine_roles(c))

    def test_engine_hooks(self):
        def team(tid, fx=None):
            ps = [Player(tid * 100 + i, "C" if i < 4 else "LW" if i < 12 else "D", toi=100 - i) for i in range(18)]
            ps += [Player(tid * 100 + 50, "G", toi=1, gp=10), Player(tid * 100 + 51, "G", toi=0, gp=1)]
            if fx:
                for p in ps:
                    if p.pos != "G":
                        p.rfx = fx
            return Team(tid, str(tid), ps)
        env = json.load(open(ENV)) if isinstance(ENV, str) else ENV
        base = sum(simulate_game(team(1), team(2), env, Skill(), s, events=False).team[0]["att"] for s in range(40))
        more = sum(simulate_game(team(1, {"ev": {"att": 1.5}}), team(2), env, Skill(), s, events=False).team[0]["att"] for s in range(40))
        self.assertGreater(more, base * 1.2)
        pens = sum(simulate_game(team(1), team(2, {"ev": {"draw": 2.0}}), env, Skill(), s, events=False).team[0]["pens"] for s in range(60))
        pens0 = sum(simulate_game(team(1), team(2), env, Skill(), s, events=False).team[0]["pens"] for s in range(60))
        self.assertGreater(pens, pens0)

    def test_cli(self):
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV if not isinstance(ENV, str) else json.load(open(ENV)), out=out)
        self.addCleanup(cli.conn.close)
        for line in ("troles info", "troles suggest", "troles"):
            cli.onecmd(line)
            self.assertEqual(cli.status_code, 0, out.getvalue())
        self.assertIn("Shadow", out.getvalue())
        cli.onecmd("troles nobody-at-all shadow")
        self.assertEqual(cli.status_code, 1)


if __name__ == "__main__":
    unittest.main()
