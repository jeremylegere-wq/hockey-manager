"""Weak-class scarcity, RFA bridge/long-term deals, regret, buyouts and the reputation memory."""
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import free_agency as FA
from hs.game import regret as RG
from hs.game import rfa
from hs.game import roster as R
from hs.game import valuation as V
from hs.game.events import emit

from test_game import make_db


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.other = self.c.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1 ORDER BY team_id",
                                    (self.me,)).fetchone()[0]
        self.m = V.market(self.c)

    def skater(self, team, best=False):
        rows = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position<>'G'",
                              (team,)).fetchall()
        return sorted((self.m.values.value(r[0]), r[0]) for r in rows)[-1 if best else 0][1]


class ScarcityTests(Base):
    class Club:
        def __init__(self, room):
            self.room = room

        def spendable(self, _):
            return self.room

    def test_thin_class_triggers_inflation(self):
        pool = {1: dict(tier=1, fair=8_000_000, years=6), 2: dict(tier=2, fair=4_000_000, years=4)}
        supply = 8e6 * 6 + 4e6 * 4
        normal = {t: self.Club(supply * FA.SCARCITY_BASE * 0.8 / 10) for t in range(10)}
        s, k = FA.scarcity(self.c, pool, normal, self.m)
        self.assertAlmostEqual(s, FA.SCARCITY_BASE * 0.8)
        self.assertEqual(k, 0.0)
        flush = {t: self.Club(supply * FA.SCARCITY_BASE * 1.8 / 10) for t in range(10)}
        s, k = FA.scarcity(self.c, pool, flush, self.m)
        self.assertGreater(k, 0.5)


class RFATests(Base):
    def test_bridge_and_long_term_terms(self):
        pid = self.skater(self.me, best=True)
        years, aav = rfa.bridge_terms(self.c, pid, 900_000, self.m)
        self.assertEqual(years, 2)
        self.assertGreaterEqual(aav, 900_000)
        self.assertLessEqual(aav, V.fair_aav(self.c, pid, 2, self.m.year, self.m))      # a squeeze, not a raise
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{self.m.year - 23}-01-01", pid))
        years, aav, rfa_years = rfa.long_term_terms(self.c, pid, self.m)
        self.assertEqual(years, K.crules(self.c)["max_term_resign"])
        self.assertEqual(rfa_years, K.crules(self.c)["ufa_age"] - 23)
        fair = V.fair_aav(self.c, pid, years, self.m.year, self.m)
        self.assertTrue(0.85 * fair - 5000 <= aav <= 1.10 * fair + 5000)


class RegretTests(Base):
    def test_optimism_then_regret_then_untradeable(self):
        pid = self.skater(self.me)
        year = K.signing_year(self.c)
        self.c.execute("DELETE FROM contracts WHERE player_id=?", (pid,))
        K.sign_contract(self.c, pid, self.me, 6, 9_000_000, K.today(self.c), start_year=year, resign=False,
                        check=False)
        st = RG.status(self.c, pid)
        self.assertEqual(st["phase"], "optimism")
        self.assertEqual(st["regret"], 0.0)
        self.assertIn(st["grade"], ("D", "F"))
        # a year and a half later, and he was expected to be worth far more than he is
        self.c.execute("UPDATE contract_expect SET signed_on='2000-01-01', expected_value=expected_value*3 "
                       "WHERE player_id=?", (pid,))
        st = RG.status(self.c, pid)
        self.assertEqual(st["phase"], "realisation")
        self.assertGreater(st["regret"], 0)
        self.assertTrue(st["untradeable"])
        self.assertIn(pid, [r["player_id"] for r in RG.worst(self.c, 10)])

    def test_ai_buys_out_an_overpaid_depth_player_when_it_needs_room(self):
        pid = self.skater(self.other)
        year = K.signing_year(self.c)
        self.c.execute("DELETE FROM contracts WHERE player_id=?", (pid,))
        K.sign_contract(self.c, pid, self.other, 4, 7_000_000, K.today(self.c), start_year=year, resign=False,
                        check=False)
        cap = K.crules(self.c)["cap_ceiling"]
        filler = cap - K.payroll(self.c, self.other, year) - 1_000_000          # leave the club about $1M of room
        self.c.execute("INSERT INTO cap_charges (team_id, season_start_year, amount, reason) VALUES (?,?,?,?)",
                       (self.other, year, filler, "test"))
        lines = RG.ai_buyouts(self.c, K.today(self.c))
        self.assertTrue(any("buy out" in l for l in lines), lines)
        self.assertIsNone(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0])
        self.assertTrue(self.c.execute("SELECT 1 FROM cap_charges WHERE player_id=? AND reason='buyout'",
                                       (pid,)).fetchone())


class ReputationTests(Base):
    def test_flipping_a_new_signing_is_remembered(self):
        pid = self.skater(self.other)
        season = K.season_year(self.c)
        emit(self.c, "PLAYER_SIGNED", f"{season}-07-01", "X signed as free agent: Y", team_id=self.other,
             player_id=pid)
        self.assertEqual(FA.quick_trades(self.c, self.other, season), 0)
        emit(self.c, "PLAYER_TRADED", f"{season}-11-01", "Y traded", team_id=self.other, other_team_id=self.me,
             player_id=pid)
        self.assertEqual(FA.quick_trades(self.c, self.other, season), 1)


if __name__ == "__main__":
    unittest.main()


class OverpaidRfaTests(Base):
    """v20: an RFA whose qualifying offer is above his value must not take it every summer forever."""

    def row(self, pid, team, qo, arb=1):
        return dict(player_id=pid, team_id=team, status="RFA", qualified=1, outcome=None, arb_elected_by=None,
                    qo=qo, prev_aav=qo, arb_eligible=arb)

    def test_term_beats_a_year_at_the_qo(self):
        pid = self.skater(self.other, best=True)
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{self.m.year - 23}-01-01", pid))
        fair5 = V.fair_aav(self.c, pid, 5, self.m.year, self.m)
        qo = int(fair5 * 1.25)                               # paid 25% more than he is worth
        deal = rfa.security_deal(self.c, pid, qo, self.m)
        self.assertIsNotNone(deal)
        years, aav = deal
        self.assertGreaterEqual(years, 2)
        self.assertLess(aav, qo)                             # the club saves money...
        self.assertGreaterEqual(aav * years ** 0.15, qo)     # ...and he is at least as happy as with the QO
        self.assertLessEqual(aav, rfa.CLUB_PAY_MAX * V.fair_aav(self.c, pid, years, self.m.year, self.m) + 5000)

    def test_ai_club_signs_term_or_goes_to_arbitration(self):
        pid = self.skater(self.other, best=True)
        ask = K.asking(self.c, pid, "RFA")
        done, elected = [], []
        finish = lambda r, aav, years, outcome: done.append((aav, years, outcome))
        terms, arbs = rfa.ai_overpaid(self.c, "2026-07-05", [self.row(pid, self.other, int(ask * 1.3))], finish,
                                      lambda r: elected.append(r["player_id"]))
        self.assertEqual(terms + arbs, 1)
        if done:
            self.assertGreater(done[0][1], 1)
        # far too overpaid for any term to work: club arbitration
        done.clear()
        terms, arbs = rfa.ai_overpaid(self.c, "2026-07-05", [self.row(pid, self.other, int(ask * 3))], finish,
                                      lambda r: elected.append(r["player_id"]))
        self.assertEqual((terms, arbs), (0, 1))
        # a player worth his QO is left alone (normal path)
        terms, arbs = rfa.ai_overpaid(self.c, "2026-07-05", [self.row(pid, self.other, int(ask * 0.8))], finish,
                                      lambda r: None)
        self.assertEqual((terms, arbs), (0, 0))
