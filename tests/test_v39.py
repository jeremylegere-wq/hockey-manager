"""v39: the friction trade market (value scale, picks, packages, need, friction, clauses, protection, the router's
kinds), contract talks with clauses and pitches, tryouts, and the third register's fixes."""
import json
import random
import tempfile
import unittest
from pathlib import Path

from hs.game import clauses as CL
from hs.game import contracts as K
from hs.game import gm_trades as GT
from hs.game import negotiation as N
from hs.game import roster as R
from hs.game import trade_model as TM
from hs.game import trades as T
from hs.game.state import get_state, user_team

from test_game import make_db


class ScaleTests(unittest.TestCase):
    def test_value_above_replacement(self):
        self.assertEqual(R.trade_value(R.REPLACEMENT), 0.0)
        self.assertAlmostEqual(R.trade_value(50), R.TV50)
        self.assertLess(R.trade_value(46.8), 8)                     # a fringe NHLer: a late pick
        self.assertGreater(R.trade_value(56), 150)                  # a top player: more than a mid 1st

    def test_pick_curve(self):
        v = [TM.pick_curve(p) for p in (1, 16, 32, 48, 80, 208)]
        self.assertEqual(v, sorted(v, reverse=True))
        self.assertTrue(200 < v[0] < 280 and 75 < v[1] < 95 and 3 < v[5] < 6)
        this = T.pick_value(16, 32, 2027, 2027, 1)
        self.assertLess(T.pick_value(16, 32, 2028, 2027, 1), this)  # later drafts are discounted
        # a weak club's future 1st carries the lottery
        self.assertGreater(T.pick_value(1, 32, 2028, 2027, 1, s_owner=0.0), T.pick_value(1, 32, 2028, 2027, 1, s_owner=1.0))

    def test_protection_lowers_value(self):
        full = TM.pick_value(3, 32, 2027, 2027, 1)
        prot = TM.protected_value(3, 32, 2027, 2027, 1, 10)
        self.assertLess(prot, full)
        self.assertGreater(TM.protected_value(28, 32, 2027, 2027, 1, 3), 0.95 * TM.pick_value(28, 32, 2027, 2027, 1))

    def test_package_decay(self):
        self.assertAlmostEqual(TM.package_value([50, 50, 50, 50]), 50 + 40 + 32 + 25.6)
        self.assertLess(TM.package_value([50, 50, 50, 50]), TM.package_value([150]) + 50)

    def test_certainty(self):
        self.assertEqual(T.certainty(18, 40, 60), 1.0)
        self.assertLess(T.certainty(23, 40, 60), T.certainty(20, 40, 60))
        self.assertEqual(T.certainty(23, 60, 60), 1.0)              # reached his potential: no bust risk


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        GT.ensure_tables(self.c)
        self.day = get_state(self.c)[0]
        self.m = T.Market(self.c, self.day)

    def test_needs_and_friction(self):
        m = self.m
        for t in m.all_teams:
            for g in "FDG":
                self.assertTrue(0 <= m.needs[t][g] <= 100)
        vals = sorted(((v, p) for p, v in m.values.items() if m.group_of.get(p) == "F"), reverse=True)
        top, low = vals[0][1], vals[-1][1]
        self.assertGreater(m.friction(top), m.friction(low))
        self.assertLessEqual(m.friction(top), TM.F_MAX)
        self.assertLessEqual(m.friction(low), TM.F_A + TM.F_MNTC)          # at most a letter or a list

    def test_clauses_generated_and_consent(self):
        n = self.c.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]
        nhl = self.c.execute("SELECT COUNT(*) FROM contracts c JOIN teams t USING (team_id) WHERE t.league_id=1").fetchone()[0]
        self.assertLess(n, nhl * 0.5)
        # a full no-trade clause blocks a move that does nothing for him
        pid = next(r["player_id"] for r in R.roster(self.c, self.me) if r["status"] == "active")
        k = K.current_contract(self.c, pid)
        CL.set_clause(self.c, pid, k["contract_id"], "NTC", 0, k["start_year"], k["start_year"] + k["years"] - 1)
        other = next(t for t in self.m.all_teams if t != self.me)
        self.assertIsNotNone(CL.check(self.c, pid, other, 0.5, 0.5, 0.75, 0.75))
        self.assertIsNone(CL.check(self.c, pid, other, 0.2, 0.9, 0.5, 0.75))       # a contender and a bigger role
        self.assertIsNone(CL.check(self.c, pid, other, 0.5, 0.5, 0.75, 0.75, requested=True))
        # a modified list blocks only the clubs on it
        CL.set_clause(self.c, pid, k["contract_id"], "MNTC", 1, k["start_year"], k["start_year"] + k["years"] - 1)
        CL.refresh_lists(self.c, self.m.S)
        blocked = CL.of(self.c, pid)["blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertIsNotNone(CL.check(self.c, pid, blocked[0], 0.5, 1.0, 0.5, 1.0))
        free = next(t for t in self.m.all_teams if t not in blocked and t != self.me)
        self.assertIsNone(CL.check(self.c, pid, free, 0.5, 0.5, 0.5, 0.5))

    def test_router_kinds(self):
        rng = random.Random(4)
        made = []
        for kind in ("minor", "depth", "swap"):
            for _ in range(12):
                t = T.INTENTS[kind](self.m, rng, self.day)
                if t:
                    made.append(kind)
        for _ in range(12):
            if T.attempt(self.c, self.day, rng, self.m):
                made.append("roster")
        kinds = {json.loads(r[0] or "{}").get("kind") for r in self.c.execute(
            "SELECT payload FROM league_events WHERE event_type='TRADE_COMPLETED'")}
        self.assertTrue(made)
        self.assertTrue(kinds <= {"minor", "depth", "roster", "swap"})
        self.assertNotIn(self.me, {r[0] for r in self.c.execute("SELECT team_id FROM league_events WHERE "
                                                                 "event_type='TRADE_COMPLETED'")})

    def test_phase_and_mix(self):
        for ph, mix in T.MIX.items():
            self.assertAlmostEqual(sum(mix.values()), 1.0, places=6)
        self.assertGreater(T.ATTEMPTS["deadline"], T.ATTEMPTS["rush"])
        self.assertGreater(T.ATTEMPTS["rush"], T.ATTEMPTS["mid"])

    def test_protected_pick_in_a_user_trade(self):
        other = next(t for t in self.m.all_teams if t != self.me)
        y = T.tradeable_years(self.c)[0]
        plain = ("pick", (y, 1, self.me))
        prot = GT.parse_pick(self.c, f"{y} 1st top10", self.me)
        self.assertEqual(prot, ("pick", (y, 1, self.me), 10))
        self.assertEqual(GT.parse_key(GT.asset_key(prot)), prot)
        a = GT.evaluate(self.c, self.me, other, [plain], [], self.day, self.m)["receive"]
        b = GT.evaluate(self.c, self.me, other, [prot], [], self.day, self.m)["receive"]
        self.assertLessEqual(b, a)
        theirs = [r["player_id"] for r in R.roster(self.c, other) if r["status"] == "active"]
        cheap = min(theirs, key=lambda p: self.m.values[p])
        ev = GT.evaluate(self.c, self.me, other, [prot], [("player", cheap)], self.day, self.m)
        if ev["accept"]:
            GT.execute(self.c, self.me, other, [prot], [("player", cheap)], self.day)
            self.assertEqual(T.protection(self.c, y, 1, self.me), 10)

    def test_retention_costs(self):
        pid = max((r["player_id"] for r in R.roster(self.c, self.me)), key=lambda p: (K.current_contract(self.c, p) or {"cap_hit": 0})["cap_hit"])
        self.assertGreater(TM.retention_value(self.c, self.me, pid, 0.5, self.day), 0)
        self.assertEqual(TM.retention_value(self.c, self.me, pid, 0, self.day), 0)


class TalksAndCampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_clause_factor(self):
        self.assertLess(N.clause_factor("ntc", 2), 1.0)
        self.assertGreater(N.clause_factor("none", 2), 1.0)
        self.assertLess(N.clause_factor("nmc", 2), N.clause_factor("ntc", 2))
        self.assertEqual(N.clause_factor("none", 0), 1.0)
        self.assertLess(N.clause_factor("mntc", 1), N.clause_factor("mntc_late", 1))

    def test_concessions_are_gradual(self):
        fa = R.free_agents(self.c)
        pid = next(p for v, p, pos in fa if v > 45)
        v = N.open_talks(self.c, pid)
        y = v["pref_years"]
        before = v["asks"][y]
        out, v2 = N.offer(self.c, pid, int(before * 0.9), y)
        if out == "counter":
            agent = N.agent_of(pid)["style"]
            self.assertGreaterEqual(v2["asks"][y], before * (1 - N.MAX_STEP[agent]) - 1)

    def test_pitch_once(self):
        fa = R.free_agents(self.c)
        pid = fa[0][1]
        N.open_talks(self.c, pid)
        text, v = N.pitch(self.c, pid, "winning")
        self.assertTrue(text)
        self.assertTrue(any(p["used"] for p in v["pitches"] if p["key"] == "winning"))
        with self.assertRaises(R.RosterError):
            N.pitch(self.c, pid, "winning")

    def test_tryout(self):
        from hs.game import pto as PTO
        pid = R.free_agents(self.c)[0][1]
        with self.assertRaises(R.RosterError):                  # not in camp season
            PTO.invite(self.c, pid)
        self.c.execute("UPDATE pack_info SET value='preseason' WHERE key='season_state'")
        if K.season_state(self.c) != "preseason":
            self.skipTest("season state not stored in pack_info in this fixture")
        PTO.invite(self.c, pid)
        self.assertNotIn(pid, [p for v, p, pos in R.free_agents(self.c)])     # spoken for
        lines = PTO.camp_reports(self.c, get_state(self.c)[0])
        self.assertTrue(lines and "best" in lines[0])
        self.assertTrue(self.c.execute("SELECT 1 FROM inbox WHERE subject LIKE 'Camp report%'").fetchone())

    def test_short_roster_signs_at_minimum(self):
        me = self.me
        g = [r for r in R.roster(self.c, me) if r["position"] == "G"]
        for r in g:
            self.c.execute("UPDATE players SET team_id=NULL, club_id=NULL WHERE player_id=?", (r["player_id"],))
        self.c.execute("UPDATE players SET status='retired' WHERE team_id=? AND status='prospect' AND position='G'", (me,))
        added = R.ensure_dressable(self.c, me, get_state(self.c)[0])
        self.assertTrue(added)
        self.assertTrue(self.c.execute("SELECT 1 FROM inbox WHERE subject='Emergency signing'").fetchone())


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_help_lists_commands(self):
        import io
        from hs.game.cli import CLI
        from test_sim import ENV
        cli = CLI(self.db, env=ENV, out=io.StringIO())
        cli.onecmd("help")
        out = cli.out.getvalue()
        self.assertIn("Commands", out)
        self.assertIn("trade", out)
        cli.conn.close()

    def test_unread_excludes_archived(self):
        from hs.game.state import add_message, _inbox_columns
        from hs.ui import api
        add_message(self.c, get_state(self.c)[0], "One", "x")
        add_message(self.c, get_state(self.c)[0], "Two", "y")
        _inbox_columns(self.c)
        n = api._unread(self.c)
        self.c.execute("UPDATE inbox SET archived=1 WHERE subject='Two'")
        self.assertEqual(api._unread(self.c), n - 1)

    def test_extension_resolves_contract_concern(self):
        from hs.game import people as P
        P.ensure_tables(self.c)
        pid = next(r["player_id"] for r in R.roster(self.c, self.me))
        day = get_state(self.c)[0]
        self.c.execute("INSERT INTO concerns (player_id, team_id, topic, raised_on, detail, expires_on) VALUES (?,?,?,?,?,?)",
                       (pid, self.me, "contract", day, "wants to know", "2099-01-01"))
        y = K.season_year(self.c)
        K.sign_contract(self.c, pid, self.me, 3, 2_000_000, day, start_year=y + 5, resign=True, check=False, detail="extended")
        self.assertEqual(self.c.execute("SELECT status FROM concerns WHERE player_id=?", (pid,)).fetchone()[0], "resolved")

    def test_press_uses_nicknames(self):
        from hs.game import press
        t = self.me
        opp = self.c.execute("SELECT abbr, nickname, name FROM teams WHERE team_id<>? AND league_id=1", (t,)).fetchone()
        qs = press._questions(self.c, t, "postgame", dict(gf=4, ga=1, opp=opp[0], rivalry=True), random.Random(1))
        text = " ".join(q["text"] for q in qs)
        self.assertNotIn(f" {opp[0]}.", text)
        self.assertIn(opp[1] or opp[2], text)


if __name__ == "__main__":
    unittest.main()
