import io
import json
import tempfile
import unittest
from pathlib import Path

from hs.game import arbitration as A
from hs.game import contracts as K
from hs.game import offseason as O
from hs.game import roster as R
from hs.game.cli import CLI
from hs.game.dayloop import sim_until
from hs.game.state import get_state
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV


def set_contract_rules(conn, **kw):
    rules = json.loads(conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()[0])
    rules.setdefault("contracts", {}).update(kw)
    conn.execute("UPDATE pack_info SET value=? WHERE key='rules'", (json.dumps(rules),))


def full_offseason(conn):
    sim_until(conn, ENV, Skill(), to_end=True)
    lines = []
    while K.season_state(conn) != "regular_season":
        lines += O.advance(conn, ENV, Skill())
    return lines


class ContractRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.conn, self.me = make_db(self.tmp.name)
        self.addCleanup(self.conn.close)

    def test_qualifying_offer_tiers(self):
        self.assertEqual(K.qualifying_offer(self.conn, 1_000_000), 1_100_000)
        self.assertEqual(K.qualifying_offer(self.conn, 1_500_000), 1_575_000)
        self.assertEqual(K.qualifying_offer(self.conn, 2_000_000), 2_000_000)
        self.assertEqual(K.qualifying_offer(self.conn, 500_000), 850_000)      # never below the minimum

    def test_every_rostered_player_has_a_contract_and_market_is_bounded(self):
        rows = self.conn.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL").fetchall()
        self.assertTrue(all(K.current_contract(self.conn, r[0]) for r in rows))
        values = K.league_values(self.conn)
        cr = K.crules(self.conn)
        asks = sorted((R.player_value(self.conn, r[0]), K.market_aav(self.conn, r[0], values)) for r in rows)
        self.assertTrue(all(cr["min_salary"] <= a <= 0.13 * cr["cap_ceiling"] + 5000 for _, a in asks))
        self.assertGreaterEqual(asks[-1][1], asks[0][1])

    def test_generated_contracts_respect_the_cap(self):
        self.conn.execute("DELETE FROM contracts")
        made = K.generate_contracts(self.conn, 3)
        self.assertGreater(made, 100)
        cap = K.crules(self.conn)["cap_ceiling"]
        for (t,) in self.conn.execute("SELECT team_id FROM teams").fetchall():
            self.assertLessEqual(K.payroll(self.conn, t), cap)

    def test_cap_blocks_signing_and_none_disables_it(self):
        set_contract_rules(self.conn, cap_ceiling=K.payroll(self.conn, self.me) + 900_000)
        fa = R.free_agents(self.conn)[0][1]
        with self.assertRaises(K.CapError):
            R.sign_free_agent(self.conn, self.me, fa, "2026-10-01", aav=2_000_000, years=1)
        set_contract_rules(self.conn, cap_ceiling=None)
        R.sign_free_agent(self.conn, self.me, fa, "2026-10-01", aav=2_000_000, years=1)
        self.assertEqual(self.conn.execute("SELECT team_id FROM players WHERE player_id=?", (fa,)).fetchone()[0], self.me)

    def test_buyout_share_and_spread(self):
        pid = self.conn.execute("SELECT player_id FROM players WHERE team_id=? ORDER BY player_id", (self.me,)).fetchone()[0]
        self.conn.execute("DELETE FROM contracts WHERE player_id=?", (pid,))
        self.conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit) VALUES (?,?,?,?,?)",
                          (pid, self.me, 2026, 2, 3_000_000))
        self.conn.execute("UPDATE players SET birth_date='1990-01-01' WHERE player_id=?", (pid,))   # 36: 2/3
        cost = K.buyout(self.conn, self.me, pid, "2026-10-01")
        self.assertEqual(cost, 4_000_000)
        charges = self.conn.execute("SELECT season_start_year, amount FROM cap_charges WHERE player_id=?", (pid,)).fetchall()
        self.assertEqual([c[0] for c in charges], [2026, 2027, 2028, 2029])
        self.assertEqual(sum(c[1] for c in charges), 4_000_000)
        self.assertIsNone(K.current_contract(self.conn, pid))

    def test_retention_moves_cap_and_is_limited(self):
        other = self.conn.execute("SELECT team_id FROM teams WHERE team_id<>? ORDER BY team_id", (self.me,)).fetchone()[0]
        a = self.conn.execute("SELECT player_id FROM players WHERE team_id=? AND position='C'", (self.me,)).fetchone()[0]
        b = self.conn.execute("SELECT player_id FROM players WHERE team_id=? AND position='C'", (other,)).fetchone()[0]
        hit_a = K.current_contract(self.conn, a)["cap_hit"]
        before_me, before_other = K.payroll(self.conn, self.me), K.payroll(self.conn, other)
        with self.assertRaises(R.RosterError):
            R.trade(self.conn, self.me, [a], other, [b], "2026-10-01", retain={a: 0.6})
        R.trade(self.conn, self.me, [a], other, [b], "2026-10-01", retain={a: 0.5})
        hit_b = K.current_contract(self.conn, b)["cap_hit"]
        self.assertAlmostEqual(K.payroll(self.conn, self.me), before_me - hit_a + hit_b + round(hit_a * 0.5), delta=2)
        self.assertAlmostEqual(K.payroll(self.conn, other), before_other + hit_a - hit_b - round(hit_a * 0.5), delta=2)
        ok_more, why = R.evaluate_trade(self.conn, self.me, [b], other, [a], {})
        self.assertIsInstance(ok_more, bool)

    def test_rights_status_by_age(self):
        pid = self.conn.execute("SELECT player_id FROM players WHERE team_id=?", (self.me,)).fetchone()[0]
        self.conn.execute("UPDATE players SET birth_date='2004-03-01' WHERE player_id=?", (pid,))
        self.assertEqual(K.rights_status(self.conn, pid, 2026), "RFA")
        self.conn.execute("UPDATE players SET birth_date='1998-03-01' WHERE player_id=?", (pid,))
        self.assertEqual(K.rights_status(self.conn, pid, 2026), "UFA")

    def test_arbitration_award_bounds_and_walkaway(self):
        pid = self.conn.execute("SELECT player_id FROM players WHERE team_id=?", (self.me,)).fetchone()[0]
        sub = A.submissions(self.conn, pid, 3_000_000, 3_000_000, "player")
        self.assertGreaterEqual(sub["offer"], 3_000_000)
        self.assertGreaterEqual(sub["ask"], sub["offer"])
        amt = A.award(self.conn, pid, sub, 7, 2026)
        self.assertTrue(sub["offer"] <= amt <= sub["ask"])
        club = A.submissions(self.conn, pid, 6_000_000, 6_000_000, "club")
        self.assertGreaterEqual(club["offer"], 0.85 * 6_000_000)
        self.assertTrue(A.can_walk_away(self.conn, 5_000_000, "player"))
        self.assertFalse(A.can_walk_away(self.conn, 5_000_000, "club"))
        self.assertFalse(A.can_walk_away(self.conn, 1_000_000, "player"))


class OffseasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_full_offseason_into_a_second_season(self):
        _, conn, me = make_db(self.tmp.name)
        lines = full_offseason(conn)
        self.assertTrue(any("free agency" in l.lower() for l in lines))
        self.assertEqual(K.season_year(conn), 2027)
        first = conn.execute("SELECT MIN(game_date) FROM games WHERE played=0").fetchone()[0]
        self.assertTrue(first.startswith("2027-10"))
        self.assertTrue(conn.execute("SELECT 1 FROM skater_season_stats WHERE season_start_year=2026").fetchone())
        cap = K.crules(conn)["cap_ceiling"]
        for (t,) in conn.execute("SELECT team_id FROM teams").fetchall():
            self.assertLessEqual(K.payroll(conn, t), cap * 1.02)        # emergency signings may nudge past
            # the test world is closed (eight clubs, no lower leagues): when nobody is left to sign, a club can be one
            # short at a position, and the engine plays a spare skater there. What must hold: every club can dress.
            c_ = R.counts(conn, t)
            if t != me:                                                   # your club is yours to fill
                self.assertGreaterEqual(c_["F"] + c_["D"], 18, t)
                self.assertGreaterEqual(c_["G"], 1, t)
        outcomes = {r[0] for r in conn.execute("SELECT outcome FROM offseason_rights")}
        self.assertNotIn(None, outcomes)
        sim_until(conn, ENV, Skill(), me, days=10, to_end=True)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM games WHERE played=1 AND game_date>='2027-10-01'").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            O.advance(conn, ENV, Skill())                                # not during the season
        conn.close()

    def test_offseason_is_deterministic(self):
        dumps = []
        for name in ("a.db", "b.db"):
            _, conn, _ = make_db(self.tmp.name, name)
            full_offseason(conn)
            dumps.append([tuple(r)[1:] for r in conn.execute("SELECT * FROM contracts ORDER BY contract_id")]
                         + [tuple(r) for r in conn.execute("SELECT * FROM offseason_rights ORDER BY player_id")])
            conn.close()
        self.assertEqual(dumps[0], dumps[1])

    def test_user_decisions_through_the_cli(self):
        db, conn, me = make_db(self.tmp.name)
        sim_until(conn, ENV, Skill(), to_end=True)
        conn.close()
        buf = io.StringIO()
        cli = CLI(db, ENV, out=buf)
        cli.onecmd("offseason")          # draft (no world in the example pack: retirements only)
        cli.onecmd("offseason")          # rights
        mine = O.rights_rows(cli.conn, me)
        rfa = next((r for r in mine if r["status"] == "RFA"), None)
        ufa = next((r for r in mine if r["status"] == "UFA"), None)
        if rfa:
            cli.onecmd(f"decline {rfa['player_id']}")
        if ufa:
            ask = K.asking(cli.conn, ufa["player_id"], "UFA")
            cli.onecmd(f"extend {ufa['player_id']} {ask} 2")
        for c in ["rights", "cap next", "contracts", "offseason", "fa", "offseason", "offseason", "offseason",
                  "offseason", "status"]:
            cli.onecmd(c)
        out = buf.getvalue()
        self.assertEqual(cli.status_code, 0, out)
        self.assertEqual(K.season_state(cli.conn), "regular_season")
        if ufa:
            c = K.current_contract(cli.conn, ufa["player_id"], 2027)
            self.assertIsNotNone(c)
            self.assertEqual(c["years"], 2)
        if rfa:
            self.assertEqual(cli.conn.execute("SELECT outcome FROM offseason_rights WHERE player_id=?",
                                              (rfa["player_id"],)).fetchone()[0], "free agent")
        cli.conn.close()


if __name__ == "__main__":
    unittest.main()
