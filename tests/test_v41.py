"""v41: the dual ledger (cap vs cash), conditional picks, career history, past drafts."""
import tempfile
import unittest

from hs.game import contracts as K
from hs.game import ledger as LG
from hs.game import roster as R

from test_game import make_db


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_schedule_sums_to_cap(self):
        for cap, yrs in ((8_250_000, 7), (5_000_000, 4), (900_000, 2), (11_000_000, 8)):
            for st in LG.STRUCTURES:
                s = LG.schedule(cap, yrs, st)
                self.assertEqual(len(s), yrs)
                self.assertEqual(sum(a + b for a, b in s), cap * yrs, (cap, yrs, st))
        front = LG.schedule(8_000_000, 6, "front")
        self.assertGreater(front[0][0], front[-1][0])
        bonus = LG.schedule(8_000_000, 6, "bonus")
        self.assertAlmostEqual(bonus[0][1] / (bonus[0][0] + bonus[0][1]), 0.40, places=2)
        self.assertTrue(all(b == 0 for _, b in LG.schedule(5_000_000, 6, "front")))

    def test_defaults(self):
        self.assertEqual(LG.default_structure(950_000, 3, "entry_level"), "flat")
        self.assertEqual(LG.default_structure(5_000_000, 5), "front")
        self.assertEqual(LG.default_structure(9_000_000, 7), "bonus")
        self.assertEqual(LG.default_structure(9_000_000, 2), "flat")

    def test_cash_vs_cap(self):
        y = K.season_year(self.c)
        LG.ensure_all(self.c)
        n = self.c.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
        self.assertEqual(self.c.execute("SELECT COUNT(DISTINCT contract_id) FROM contract_years").fetchone()[0], n)
        cash = LG.cash(self.c, self.me, y)
        self.assertEqual(cash, LG.cash(self.c, self.me, y, "salary") + LG.cash(self.c, self.me, y, "bonus"))
        # over a whole contract, cash equals cap hit x years
        cid = self.c.execute("SELECT contract_id FROM contracts WHERE years>=4 ORDER BY cap_hit DESC LIMIT 1").fetchone()[0]
        c = self.c.execute("SELECT cap_hit, years FROM contracts WHERE contract_id=?", (cid,)).fetchone()
        self.assertEqual(sum(x["cash"] for x in LG.years_of(self.c, cid)), c[0] * c[1])

    def test_structure_written_and_read(self):
        cid = self.c.execute("SELECT contract_id FROM contracts WHERE years>=3 LIMIT 1").fetchone()[0]
        LG.write(self.c, cid, "bonus")
        st = LG.structure_of(self.c, cid)
        self.assertIn(st, ("bonus", "front"))       # small deals get no bonus share: then it reads front
        LG.write(self.c, cid, "flat")
        self.assertEqual(LG.structure_of(self.c, cid), "flat")

    def test_buyout_keeps_bonuses(self):
        y = K.signing_year(self.c)
        r = self.c.execute("SELECT c.contract_id, c.player_id, c.team_id, c.cap_hit, c.start_year, c.years FROM contracts c "
                           "WHERE c.start_year<=? AND c.start_year+c.years-1>=?+2 ORDER BY c.cap_hit DESC LIMIT 1", (y, y)).fetchone()
        if r is None:
            self.skipTest("no long contract in the fixture")
        cid, pid, team, cap = r[0], r[1], r[2], r[3]
        LG.write(self.c, cid, "bonus")
        sched = {x["season"]: x for x in LG.years_of(self.c, cid)}
        rem = [sched[s] for s in range(max(y, r[4]), r[4] + r[5])]
        total = K.buyout(self.c, team, pid, f"{y}-06-20")
        sal = sum(x["salary"] for x in rem)
        bon = sum(x["bonus"] for x in rem)
        self.assertGreater(bon, 0)
        self.assertAlmostEqual(total - bon, sal * (1 / 3 if total - bon < sal * 0.5 else 2 / 3), delta=len(rem) * 2)
        charges = self.c.execute("SELECT season_start_year, amount FROM cap_charges WHERE player_id=? ORDER BY 1", (pid,)).fetchall()
        self.assertEqual(len(charges), 2 * len(rem))
        cash = self.c.execute("SELECT season, amount FROM buyout_cash WHERE player_id=? ORDER BY 1", (pid,)).fetchall()
        self.assertAlmostEqual(sum(a for _, a in cash), total, delta=4 * len(rem))
        # the first season of the old term: bonus paid, cash above the cap charge
        self.assertGreater(cash[0][1], 0)

    def test_talks_offer_structures(self):
        from hs.game import negotiation as N
        self.assertLess(LG.TALKS_DISCOUNT["flat"], LG.TALKS_DISCOUNT["front"])
        self.assertLess(LG.TALKS_DISCOUNT["front"], LG.TALKS_DISCOUNT["bonus"])
        self.assertTrue(hasattr(N, "offer"))


if __name__ == "__main__":
    unittest.main()


class ConditionalPickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        from hs.game import trades as T
        from hs.game import gm_trades as GT
        from hs.game.draft import draft_year
        self.T, self.GT = T, GT
        T.ensure_tables(self.c)
        self.y = draft_year(self.c)
        self.other = self.c.execute("SELECT team_id FROM teams WHERE team_id<>? AND league_id=1", (self.me,)).fetchone()[0]

    def test_parse_and_value(self):
        a = self.GT.parse_pick(self.c, f"{self.y} 2nd if playoffs", self.me)
        self.assertEqual(self.T.parse_spec(a[2]), ("playoffs", self.me))
        self.assertEqual(self.GT.parse_key(self.GT.asset_key(a)), a)
        with self.assertRaises(ValueError):
            self.GT.parse_pick(self.c, f"{self.y} 1st if playoffs", self.me)      # nothing above a 1st
        from hs.game.state import get_state
        m = self.T.Market(self.c, get_state(self.c)[0])
        lo = self.T._asset_value(m, ("pick", a[1]), self.me, False)
        hi = self.T._asset_value(m, ("pick", (self.y, 1, self.me)), self.me, False)
        mid = self.T._asset_value(m, a, self.me, False)
        self.assertTrue(lo < mid < hi, (lo, mid, hi))
        self.assertIn("becomes a 1st", self.GT.describe(self.c, a, self.me))

    def test_encumbered_and_resolution(self):
        T = self.T
        self.c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (self.y, 2, self.me, self.other, "t"))
        T.set_condition(self.c, self.y, 2, self.me, self.me, "playoffs", self.me)
        self.assertTrue(T.encumbered(self.c, self.y, 1, self.me))
        teams = [r[0] for r in self.c.execute("SELECT team_id FROM teams WHERE league_id=1")]
        self.assertNotIn((self.y, 1, self.me), T.picks_owned(self.c, self.me, [self.y], teams))
        self.assertIn("becomes a 1st", T.pick_label(self.c, self.y, 2, self.me, self.other))
        lines = T.resolve_conditions(self.c, self.y, {self.me: 1}, "2026-06-20")
        self.assertTrue(lines and lines[0].startswith("Condition met"))
        self.assertEqual(T.pick_owner(self.c, self.y, 1, self.me), self.other)
        self.assertEqual(T.pick_owner(self.c, self.y, 2, self.me), self.me)
        self.assertFalse(T.encumbered(self.c, self.y, 1, self.me))

    def test_lapses(self):
        T = self.T
        self.c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (self.y, 3, self.me, self.other, "t"))
        T.set_condition(self.c, self.y, 3, self.me, self.me, "round2", self.me)
        lines = T.resolve_conditions(self.c, self.y, {self.me: 1}, "2026-06-20")
        self.assertIn("not met", lines[0])
        self.assertEqual(T.pick_owner(self.c, self.y, 2, self.me), self.me)
        self.assertEqual(T.pick_owner(self.c, self.y, 3, self.me), self.other)

    def test_p_condition(self):
        from hs.game import trade_model as TM
        self.assertGreater(TM.p_condition("playoffs", 3, 32, 16, 0.8), 0.95)
        self.assertLess(TM.p_condition("playoffs", 30, 32, 16, 0.8), 0.05)
        self.assertLess(TM.p_condition("round2", 3, 32, 16, 0.8), TM.p_condition("playoffs", 3, 32, 16, 0.8))


class CareerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        from hs.game import career as CR
        self.CR = CR
        self.p = self.c.execute("SELECT player_id, first_name, last_name, birth_date, position FROM players WHERE team_id=? "
                                "AND position<>'G' LIMIT 1", (self.me,)).fetchone()

    def m3(self, rows):
        import csv, io
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=["player_name", "date_of_birth", "career_nhl_games_raw", "career_nhl_seasons_raw"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return out.getvalue()

    def test_m3_import(self):
        y, m, d = self.p["birth_date"].split("-")
        text = self.m3([dict(player_name=f"{self.p['first_name']} {self.p['last_name']}", date_of_birth=f"{int(d)}.{int(m)}.{y}",
                             career_nhl_games_raw="612", career_nhl_seasons_raw="8"),
                        dict(player_name="Nobody Here", date_of_birth="1.1.1990", career_nhl_games_raw="10", career_nhl_seasons_raw="1"),
                        dict(player_name="No Games", date_of_birth="1.1.1990", career_nhl_games_raw="", career_nhl_seasons_raw="")])
        prev = self.CR.import_m3(self.c, text)
        self.assertEqual((prev["with_nhl"], prev["matched"]), (2, 1))
        self.assertIsNone(self.CR.prior(self.c, self.p["player_id"]))     # preview only
        self.CR.import_m3(self.c, text, apply=True)
        self.assertEqual(self.CR.prior(self.c, self.p["player_id"])["gp"], 612)
        from hs.game import waivers as WV
        self.assertGreaterEqual(WV.nhl_games(self.c, self.p["player_id"]), 612)
        from hs.game import world as W
        self.assertGreaterEqual(W.nhl_games(self.c).get(self.p["player_id"], 0), 612)
        with self.assertRaises(ValueError):
            self.CR.import_m3(self.c, "a,b\n1,2\n")

    def test_editor_columns_and_alltime(self):
        from hs.game import editor as ED
        ED.set_enabled(self.c, True)
        ED.edit_player(self.c, self.p["player_id"], {"career_gp": "900", "career_g": "350", "career_a": "400", "career_seasons": "12"})
        pr = self.CR.prior(self.c, self.p["player_id"])
        self.assertEqual((pr["gp"], pr["g"], pr["a"]), (900, 350, 400))
        text = ED.export_players(self.c, "mine")
        self.assertIn("career_gp", text.splitlines()[0])
        self.assertEqual(ED.import_players(self.c, text)["changes"], [])      # round trip unchanged
        top = self.CR.alltime_skaters(self.c, 1, 5)
        self.assertEqual(top[0]["player_id"], self.p["player_id"])
        from hs.game import legacy as LEG
        self.assertGreaterEqual(LEG.career(self.c, self.p["player_id"])["pts"], 750)
        from hs.ui import stats as ST
        h = ST.history(self.c)
        self.assertTrue(h["prior"])
        self.assertEqual(h["alltime"][0]["player_id"], self.p["player_id"])

    def test_past_drafts(self):
        from hs.game.draft import draft_year
        y = draft_year(self.c) - 3
        ab = self.c.execute("SELECT abbr FROM teams WHERE team_id=?", (self.me,)).fetchone()[0]
        text = ("year,round,pick,team,player,dob\n"
                f"{y},1,4,{ab},{self.p['first_name']} {self.p['last_name']},{self.p['birth_date']}\n"
                f"{y},1,5,{ab},Somebody Else,\n"
                f"{y},2,40,ZZZ,Bad Team,\n"
                f"{draft_year(self.c)},1,1,{ab},Too Soon,\n")
        prev = self.CR.import_drafts(self.c, text)
        self.assertEqual((prev["linked"], prev["named"], len(prev["errors"])), (1, 1, 2))
        self.CR.import_drafts(self.c, text, apply=True)
        from hs.ui import screens as SC
        log = SC.draft_log(self.c, y)
        self.assertEqual(log["year"], y)
        self.assertEqual([r["overall"] for r in log["rows"]], [4, 5])
        self.assertEqual(log["rows"][0]["player_id"], self.p["player_id"])
        self.assertIsNone(log["rows"][1]["player_id"])
        again = self.CR.import_drafts(self.c, text)
        self.assertEqual(again["skipped"], 2)
