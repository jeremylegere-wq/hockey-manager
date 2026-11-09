"""Draft-floor trading: the pick value chart, pick swaps, moving up and consolidation."""
import random
import tempfile
import unittest

from hs.game import draft as D
from hs.game import draft_floor as F

from test_game import make_db


class ChartTests(unittest.TestCase):
    def test_anchors_and_shape(self):
        self.assertEqual(F.chart(1), 1000)
        self.assertAlmostEqual(F.chart(32), 300, delta=1)
        self.assertAlmostEqual(F.chart(224), 12, delta=1)
        vals = [F.chart(n) for n in range(1, 225)]
        self.assertTrue(all(a >= b for a, b in zip(vals, vals[1:])))
        # three 5th-rounders buy about one 3rd-rounder (the consolidation rule in the brief)
        self.assertAlmostEqual(sum(F.chart(n) for n in (140, 145, 150)) / F.chart(80), 1.0, delta=0.25)
        self.assertLess(F.future_value(1), F.chart(16))                # future picks carry a discount

    def test_live_board_multiplier(self):
        self.assertEqual(F.live_multiplier(0), 1.0)
        self.assertAlmostEqual(F.live_multiplier(5), 1.25)
        self.assertAlmostEqual(F.live_multiplier(40), 1.5)


class FloorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        D.ensure_tables(self.c)
        self.year = D.draft_year(self.c)
        self.teams = [r[0] for r in self.c.execute("SELECT team_id FROM teams WHERE league_id=1 ORDER BY team_id")]
        n = len(self.teams)
        rows = []
        for rnd in range(7):
            for k, t in enumerate(self.teams):
                rows.append((self.year, rnd * n + k + 1, rnd + 1, t, None, None))
        self.c.executemany("INSERT INTO draft_picks VALUES (?,?,?,?,?,?)", rows)
        self.other = next(t for t in self.teams if t != self.me)

    def owner(self, n):
        return self.c.execute("SELECT team_id FROM draft_picks WHERE draft_year=? AND overall=?",
                              (self.year, n)).fetchone()[0]

    def test_pickswap_needs_chart_value(self):
        mine = [r[0] for r in self.c.execute("SELECT overall FROM draft_picks WHERE draft_year=? AND team_id=? "
                                             "ORDER BY overall", (self.year, self.me))]
        theirs = [r[0] for r in self.c.execute("SELECT overall FROM draft_picks WHERE draft_year=? AND team_id=? "
                                               "ORDER BY overall", (self.year, self.other))]
        with self.assertRaises(ValueError):                           # a late pick for an early one: no
            F.pickswap(self.c, self.year, self.me, self.other, [mine[-1]], [theirs[0]], "2027-06-26")
        msg = F.pickswap(self.c, self.year, self.me, self.other, [mine[0], mine[1]], [theirs[1]], "2027-06-26")
        self.assertIn("Done", msg)
        self.assertEqual(self.owner(theirs[1]), self.me)
        self.assertEqual(self.owner(mine[0]), self.other)
        with self.assertRaises(ValueError):                           # you cannot trade what you no longer own
            F.pickswap(self.c, self.year, self.me, self.other, [mine[0]], [theirs[2]], "2027-06-26")

    def test_consolidation_bundles_late_picks(self):
        rich = self.teams[-1] if self.teams[-1] != self.me else self.teams[-2]
        # give the rich club four extra late picks
        late = [r[0] for r in self.c.execute("SELECT overall FROM draft_picks WHERE draft_year=? AND round>=5 AND "
                                             "team_id NOT IN (?,?) ORDER BY overall DESC LIMIT 4",
                                             (self.year, rich, self.me))]
        for n in late:
            self.c.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (rich, self.year, n))
        # the partner pool needs clubs with few picks: thin out two clubs
        for t in [t for t in self.teams if t not in (rich, self.me)][:2]:
            self.c.execute("DELETE FROM draft_picks WHERE draft_year=? AND team_id=? AND round=7", (self.year, t))
        before = self.c.execute("SELECT COUNT(*) FROM draft_picks WHERE draft_year=? AND team_id=?",
                                (self.year, rich)).fetchone()[0]
        lines = F.consolidate(self.c, self.year, "2027-06-26")
        after = self.c.execute("SELECT COUNT(*) FROM draft_picks WHERE draft_year=? AND team_id=?",
                               (self.year, rich)).fetchone()[0]
        if before > F.CONSOLIDATE_AT:
            self.assertTrue(lines)
            self.assertEqual(after, before - 2)

    def test_move_up_when_the_buyer_loves_a_player_and_the_seller_does_not_care(self):
        pool = [dict(pid=900000 + i, cur=9.0, age=18, goalie=False, pos="C", nat="CAN", height=183,
                     expected_slot=i + 1) for i in range(40)]
        seller, buyer = self.owner(2), self.owner(4)
        if self.me in (seller, buyer):
            self.skipTest("user club in the way")

        class Board:
            def __init__(self):
                self.views, self.need = {}, {}

            def proj(self, t):
                if t == buyer:                                       # one player stands out for the buyer
                    return "balanced", {x["pid"]: (12.0 if x["pid"] == 900000 else 10.0) for x in pool}
                return "balanced", {x["pid"]: 10.0 for x in pool}    # everyone else sees a flat board
        theirs = [r[0] for r in self.c.execute("SELECT overall FROM draft_picks WHERE draft_year=? AND team_id=?",
                                                (self.year, buyer))]
        text = F.try_move_up(self.c, self.year, 2, seller, Board(), pool, "2027-06-26", random.Random(0))
        self.assertIsNotNone(text)
        self.assertEqual(self.owner(2), buyer)
        self.assertTrue(any(self.owner(n) == seller for n in theirs))      # the seller got the buyer's pick(s)
        # a flat board for the buyer too: nobody moves
        self.c.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=2", (seller, self.year))

        class Flat:
            views, need = {}, {}

            def proj(self, t):
                return "balanced", {x["pid"]: 10.0 for x in pool}
        self.assertIsNone(F.try_move_up(self.c, self.year, 2, seller, Flat(), pool, "2027-06-26", random.Random(0)))


if __name__ == "__main__":
    unittest.main()
