"""v42: the v39 playtest register (shopping a player, outlooks from day one, goalie projections, past seasons,
no third-party game names in the code)."""
import datetime
import pathlib
import re
import tempfile
import unittest

from hs.game import roster as R
from hs.game.state import get_state

from test_game import make_db

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        from hs.game import shop as SH
        from hs.game import gm_trades as GT
        self.SH, self.GT = SH, GT
        self.day = get_state(self.c)[0]
        if not GT.window_open(self.c, self.day)[0]:
            self.skipTest("trade window closed in the fixture")

    def test_shop_staggers_calls(self):
        made = None
        for r in sorted(R.roster(self.c, self.me), key=lambda r: r["player_id"]):
            try:
                self.SH.shop(self.c, r["player_id"], self.day, seed=1)
            except R.RosterError:
                continue
            plan = self.c.execute("SELECT plan FROM shop WHERE player_id=?", (r["player_id"],)).fetchone()[0]
            if plan != "[]":
                made = r["player_id"]
                break
        if made is None:
            self.skipTest("no club wants anyone in the fixture")
        import json
        plan = json.loads(self.c.execute("SELECT plan FROM shop WHERE player_id=?", (made,)).fetchone()[0])
        self.assertLessEqual(len(plan), self.SH.MAX_CALLS)
        days = [p["day"] for p in plan]
        self.assertEqual(days, sorted(days))
        self.assertGreater(days[0], self.day)                     # nobody calls the same day
        self.assertEqual(len(set(days)), len(days))               # one call a day at most
        self.assertIn(made, self.GT.on_block(self.c))
        with self.assertRaises(R.RosterError):
            self.SH.shop(self.c, made, self.day)
        d = datetime.date.fromisoformat(self.day)
        for k in range(1, self.SH.SHOP_DAYS + 1):
            self.SH.daily(self.c, (d + datetime.timedelta(days=k)).isoformat(), 1)
        self.assertEqual(self.c.execute("SELECT status FROM shop WHERE player_id=?", (made,)).fetchone()[0], "done")

    def test_price_factor(self):
        import random
        rng = random.Random(1)
        self.assertLess(max(self.SH.price_factor(20, rng) for _ in range(50)), 0.81)
        self.assertGreater(min(self.SH.price_factor(80, rng) for _ in range(50)), 0.91)


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def test_outlook_from_day_one(self):
        from hs.game import trades as T
        m = T.Market(self.c, get_state(self.c)[0])
        self.assertGreater(len(set(m.outlook.values())), 1)          # not everyone "middle of the pack"

    def test_goalie_grades(self):
        from hs.game.scouting import grade
        self.assertEqual(grade(11.7, True), "starter")
        self.assertEqual(grade(10.9, True), "1B")
        self.assertEqual(grade(9.9, True), "3rd string")
        self.assertEqual(grade(11.7), "top-line / top-pair")

    def test_past_seasons(self):
        from hs.game import career as CR
        from hs.game import contracts as K
        p = self.c.execute("SELECT player_id, first_name, last_name, birth_date FROM players WHERE team_id=? AND "
                           "position<>'G' LIMIT 1", (self.me,)).fetchone()
        CR.set_prior(self.c, p[0], "m3", gp=300, seasons=4)
        y = K.season_year(self.c)
        lg = self.c.execute("SELECT name FROM leagues WHERE league_id=1").fetchone()[0]
        text = ("player,dob,season,league,team,gp,g,a,pim\n"
                f"{p[1]} {p[2]},{p[3]},{y - 2}-{(y - 1) % 100:02d},{lg},,82,20,30,10\n"
                f"{p[1]} {p[2]},{p[3]},{y - 1},{lg},,80,25,35,12\n"
                f"{p[1]} {p[2]},{p[3]},{y},{lg},,10,1,1,0\n"
                f"Nobody Here,,{y - 1},{lg},,5,0,0,0\n")
        prev = CR.import_seasons(self.c, text)
        self.assertEqual((prev["seasons"], len(prev["errors"])), (2, 2))
        CR.import_seasons(self.c, text, apply=True)
        self.assertIsNone(CR.prior(self.c, p[0]))                    # the games-only total gives way
        self.assertEqual(tuple(self.c.execute("SELECT SUM(gp), SUM(g) FROM skater_season_stats WHERE player_id=?",
                                        (p[0],)).fetchone()), (162, 45))
        CR.import_seasons(self.c, text, apply=True)                  # again: replaced, not doubled
        self.assertEqual(self.c.execute("SELECT SUM(gp) FROM skater_season_stats WHERE player_id=?", (p[0],)).fetchone()[0], 162)


class NamesTests(unittest.TestCase):
    def test_no_third_party_game_name_in_the_game(self):
        bad = re.compile("|".join([r"\bE" + "HM\\b", "East" + "side", "e" + "hm_", "_e" + "hm", "e" + r"hm\."]), re.I)
        hits = []
        for f in list((ROOT / "hs").rglob("*.py")) + list((ROOT / "hs").rglob("*.js")) + list((ROOT / "hs").rglob("*.html")) \
                + list((ROOT / "hs").rglob("*.css")) + list((ROOT / "docs").rglob("*.md")) + [ROOT / "README.md"]:
            if "vendor" in f.parts:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if bad.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{i}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()


class DbHistoryTests(unittest.TestCase):
    """The database reader on a synthetic file (no third-party data in the repository)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)

    def build(self):
        import csv
        import struct
        from hs.adapters import db_history as H
        d = pathlib.Path(self.tmp.name)
        sk = self.c.execute("SELECT player_id, first_name, last_name FROM players WHERE team_id=? AND position<>'G' LIMIT 1",
                            (self.me,)).fetchone()
        gk = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position='G' LIMIT 1", (self.me,)).fetchone()
        team = self.c.execute("SELECT name, nickname, abbr FROM teams WHERE team_id=?", (self.me,)).fetchone()
        lg = self.c.execute("SELECT name FROM leagues WHERE league_id=1").fetchone()[0]
        exp = d / "export"
        exp.mkdir()
        with open(exp / "staff_normalized.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["staff_record_index", "forename", "surname", "player_data_ref"])
            w.writerow([500, sk[1], sk[2], sk[0] - 1])
            w.writerow([501, "G", "K", gk[0] - 1])
            w.writerow([502, "Gone", "Away", 99999998])
        with open(exp / "clubs_lookup.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["club_id", "Long name", "Abbreviation"])
            w.writerow([7, f"{team[0]} {team[1] or ''}".strip(), team[2]])
            w.writerow([8, "Somewhere Juniors", "SWJ"])
        with open(exp / "club_competitions_lookup.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["league_id", "Name", "Short Name"])
            w.writerow([0, "National Hockey League", "NHL"])
            w.writerow([9, "Some Junior League", "SJL"])
        from hs.adapters.db_export import DIVISIONS
        assert DIVISIONS["National Hockey League"] == "NHL"
        hist = []
        for k in range(60):                                   # padding rows the import ignores (unknown staff)
            hist.append(H.HIST.pack(k, 9000 + k, 8, 9, 2010, 0, 0, 0, 0, 0, 0, 10, 1, 1, 0, 0, 0, 0, 0))
        hist.append(H.HIST.pack(60, 500, 8, 9, 2018, 0, 0, 0, 0, 12, 5, 60, 30, 40, 0, 0, 0, 0, 0))
        hist.append(H.HIST.pack(61, 500, 7, 0, 2023, 0, 0, 0, 0, 20, -3, 82, 25, 35, 0, 0, 0, 0, 0))
        hist.append(H.HIST.pack(62, 500, 7, 0, 2023, 0, 0, 0, 0, 2, 1, 10, 3, 4, 0, 0, 0, 1, 0))      # playoffs
        hist.append(H.HIST.pack(63, 501, 7, 0, 2024, 3500, 120, 4, 1500, 0, 0, 60, 0, 0, 35, 18, 5, 0, 0))
        drafted = [H.DRAFT.pack(k, 3, 9000 + k, 8, b"\0" * 8, 2010, 5, 1) for k in range(60)]
        drafted.append(H.DRAFT.pack(60, 0, 500, 7, b"\0" * 8, 2016, 13, 1))
        drafted.append(H.DRAFT.pack(61, 0, 502, 7, b"\0" * 8, 2016, 40, 2))
        hdr = lambda tag, n: struct.pack("<HI", tag, n)
        blob = (b"junk" * 10 + hdr(12, 2) + b"\0" * 10 + hdr(13, len(hist)) + b"".join(hist) + hdr(14, 0)
                + hdr(24, len(drafted)) + b"".join(drafted) + hdr(25, 0))
        dbf = d / "database.db"
        dbf.write_bytes(blob)
        return dbf, exp, sk[0], gk[0]

    def test_reads_history_and_drafts(self):
        from hs.adapters import db_history as H
        from hs.game import career as CR
        dbf, exp, sk, gk = self.build()
        CR.set_prior(self.c, sk, "m3", gp=300, seasons=4)
        prev = H.load(self.c, dbf, exp, before=2026)
        self.assertEqual((prev["skater_lines"], prev["goalie_lines"], prev["draft_picks"]), (3, 1, 2))
        res = H.load(self.c, dbf, exp, apply=True, before=2026)
        self.assertTrue(res["applied"])
        rows = self.c.execute("SELECT season_start_year, team_id, league_id, split, gp, g, a, pim, plus_minus, club_name, "
                              "league_name FROM skater_season_stats WHERE player_id=? AND source='history' ORDER BY 1, 4 DESC",
                              (sk,)).fetchall()
        self.assertEqual(tuple(rows[0]), (2018, None, None, "RS", 60, 30, 40, 12, 5, "Somewhere Juniors", "SJL"))
        self.assertEqual(tuple(rows[1])[:9], (2023, self.me, 1, "RS", 82, 25, 35, 20, -3))
        self.assertEqual(rows[2]["split"], "PO")
        g = self.c.execute("SELECT gp, w, l, otl, so, ga, sa, toi_sec FROM goalie_season_stats WHERE player_id=?", (gk,)).fetchone()
        self.assertEqual(tuple(g), (60, 35, 18, 5, 4, 120, 1620, 3500 * 60))
        self.assertIsNone(CR.prior(self.c, sk))                      # real NHL seasons replace the games-only total
        picks = self.c.execute("SELECT draft_year, overall, round, team_id, player_id FROM draft_picks ORDER BY overall").fetchall()
        self.assertEqual([tuple(p) for p in picks], [(2016, 13, 1, self.me, sk), (2016, 40, 2, self.me, None)])
        self.assertEqual(self.c.execute("SELECT name FROM past_draft_names").fetchone()[0], "Gone Away")
        H.load(self.c, dbf, exp, apply=True, before=2026)             # again: replaced, not doubled
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM skater_season_stats WHERE source='history'").fetchone()[0], 3)
        from hs.ui import stats as ST
        x = ST.player_extras(self.c, sk)
        self.assertIn("Somewhere Juniors", [r["team"] for r in x["career"]])
