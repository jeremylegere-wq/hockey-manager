"""User trades on the league's valuation: picks, counter-offers, AI offers, the block, the deadline."""
import random
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import gm_trades as GT
from hs.game import roster as R
from hs.game import trades as T
from hs.game.cli import CLI
from hs.game.state import get_state

from test_game import make_db
from test_sim import ENV


class GmTradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        GT.ensure_tables(self.c)
        self.day = get_state(self.c)[0]
        self.other = self.c.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1 ORDER BY team_id",
                                    (self.me,)).fetchone()[0]

    def players(self, team):
        return [r["player_id"] for r in R.roster(self.c, team) if r["status"] == "active"]

    def test_picks_parse_and_move(self):
        y = T.tradeable_years(self.c)[0]
        a = GT.parse_pick(self.c, f"{y} 1st", self.me)
        self.assertEqual(a, ("pick", (y, 1, self.me)))
        with self.assertRaises(ValueError):
            GT.parse_pick(self.c, f"{y} 1st", self.other) and GT.parse_pick(self.c, f"{y} 1st {self.c.execute('SELECT abbr FROM teams WHERE team_id=?', (self.me,)).fetchone()[0]}", self.other)
        their_pick = ("pick", (y, 2, self.other))
        GT.execute(self.c, self.me, self.other, [a], [their_pick], self.day)
        self.assertEqual(T.pick_owner(self.c, y, 1, self.me), self.other)
        self.assertEqual(T.pick_owner(self.c, y, 2, self.other), self.me)
        # a later trade can pass on a pick that came from elsewhere
        ab = self.c.execute("SELECT abbr FROM teams WHERE team_id=?", (self.other,)).fetchone()[0]
        self.assertEqual(GT.parse_pick(self.c, f"{y} 2nd {ab}", self.me), ("pick", (y, 2, self.other)))
        self.assertEqual(GT.parse_pick(self.c, f"{y} 2nd", self.me), ("pick", (y, 2, self.me)))

    def test_evaluation_is_the_league_view(self):
        m = T.Market(self.c, self.day)
        mine, theirs = self.players(self.me), self.players(self.other)
        best_theirs = max((p for p in theirs if p not in m.core[self.other]), key=lambda p: m.values[p])
        ev = GT.evaluate(self.c, self.me, self.other, [], [("player", best_theirs)], self.day, m)
        self.assertFalse(ev["accept"])                                         # nothing for something
        ev = GT.evaluate(self.c, self.me, self.other, [("player", p) for p in mine[:3]], [], self.day, m)
        self.assertTrue(ev["accept"])                                          # something for nothing
        core = next(iter(m.core[self.other]))
        # v39: the premium for a player is his friction (trade_model): 1.05 + friction/100
        ev = GT.evaluate(self.c, self.me, self.other, [], [("player", core)], self.day, m)
        self.assertAlmostEqual(ev["need_ratio"], round(GT.TM.ACCEPT + min(100.0, m.friction(core, self.other)) / 100, 3), places=3)

    def test_what_it_takes_is_accepted(self):
        m = T.Market(self.c, self.day)
        theirs = sorted((p for p in self.players(self.other) if p not in m.core[self.other]),
                        key=lambda p: m.values[p])
        target = ("player", theirs[len(theirs) // 2])
        pkg, why = GT.what_it_takes(self.c, self.me, self.other, [target], self.day)
        self.assertIsNotNone(pkg, why)
        self.assertLessEqual(len(pkg), 3)
        self.assertTrue(GT.evaluate(self.c, self.me, self.other, pkg, [target], self.day)["accept"])

    def test_ai_offer_accept_and_block(self):
        GT.P_OFFER, old = 1.0, GT.P_OFFER
        self.addCleanup(setattr, GT, "P_OFFER", old)
        from hs.game import roster as _R
        for p in sorted(self.players(self.me), key=lambda p: -_R.player_value(self.c, p))[4:14]:
            GT.block(self.c, p)                                # the middle of the roster, every position
        made = []
        for i in range(10):
            made += GT.ai_offers(self.c, self.day, random.Random(i))
            if made:
                break
        self.assertTrue(made)
        r = GT.open_offers(self.c)[0]
        they_give, they_get = GT.offer_assets(r)
        pid = they_get[0][1]
        GT.respond(self.c, r["offer_id"], True, self.day)
        self.assertEqual(self.c.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                         r["team_id"])
        self.assertNotIn(pid, GT.on_block(self.c))
        with self.assertRaises(R.RosterError):
            GT.respond(self.c, r["offer_id"], True, self.day)                  # no longer open

    def test_deadline_closes_trading(self):
        self.c.execute("UPDATE game_state SET current_date=?", (str(T.deadline(self.c).replace(day=28)) if
                                                                 T.deadline(self.c).day < 28 else "2099-01-01",))
        day = get_state(self.c)[0]
        ok, why = GT.window_open(self.c, day)
        self.assertFalse(ok)
        with self.assertRaises(R.RosterError):
            GT.execute(self.c, self.me, self.other, [("player", self.players(self.me)[0])], [], day)

    def test_cli_trade_with_picks(self):
        cli = CLI(self.db, ENV)
        self.addCleanup(cli.conn.close)
        y = T.tradeable_years(cli.conn)[0]
        ab = cli.conn.execute("SELECT abbr FROM teams WHERE team_id=?", (self.other,)).fetchone()[0]
        import io
        cli.out = io.StringIO()
        cli.onecmd(f"tradecheck {ab} give {y} 1st, {y} 2nd get {y} 7th")
        self.assertIn("would accept", cli.out.getvalue())
        cli.onecmd(f"trade {ab} give {y} 1st get {y} 7th")
        self.assertIn("Accepted", cli.out.getvalue())
        self.assertEqual(T.pick_owner(cli.conn, y, 1, self.me), self.other)


if __name__ == "__main__":
    unittest.main()
