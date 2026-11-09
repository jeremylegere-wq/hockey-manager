"""v38: the native ratings model (ratings -> engine attributes, back-fill, anchoring on ability, development, edits) and
the database-export import, on a synthetic export of invented players and clubs (no real data)."""
import csv
import json
import random
import tempfile
import unittest
from pathlib import Path

from hs.adapters import db_export as EX
from hs.attributes import (ALL_ATTRS, NATIVE_ATTRS, RATING_COLS, derive, fit_ability, primary_position, ratings_from_engine)
from hs.game import ratings as RT
from hs.game.state import connect, new_game
from hs.ingest import build_db
from hs.worldgen import overall_of

from test_world import small_world

DIVS = {"Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
        "Metropolitan": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
        "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG"],
        "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"]}


def _w(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def fake_export(root, per_club=30):
    """Invented clubs and players in the shape of the exporter's CSVs."""
    rng = random.Random(3)
    root = Path(root)
    clubs, cid = [], 1
    for div, abbrs in DIVS.items():
        for ab in abbrs:
            clubs.append({"club_id": cid, "Long name": f"Test {ab}", "NameShort": f"Town {ab}", "NickName": "Testers", "Abbreviation": ab,
                          "Division": "National Hockey League", "DetailedDivision": f"National Hockey League {div} Division",
                          "MaxAttendance": 18000 + cid * 10, "MarketSize": 12, "Reputation": 8000, "YearFounded": 1970, "HomeCity": "town:xx:yyy",
                          "Arena": "test arena:yyy", "Rivals1": f"Test {abbrs[(abbrs.index(ab) + 1) % 8]}", "Rivals2": "", "Rivals3": ""})
            cid += 1
    clubs.append({"club_id": 900, "Long name": "Junior Testers", "Abbreviation": "JTS", "Division": "Ontario Hockey League"})
    clubs.append({"club_id": 901, "Long name": "Laval Rocket", "Abbreviation": "LAV", "Division": "American Hockey League"})
    profiles, staff, rights = [], [], []
    pid = 0
    for c in clubs:
        n = per_club if c["Division"] == "National Hockey League" else 12
        for k in range(n):
            pos = ["G", "G", "G", "LD", "RD", "LD", "RD", "LD", "RD", "LD"][k] if k < 10 else rng.choice(["C", "LW", "RW", "C"])
            ca = max(40, min(200, int(rng.gauss(140 if c["club_id"] < 900 else 80, 20))))
            r = {a: max(1, min(20, int(rng.gauss(ca / 12, 2.5)))) for a in NATIVE_ATTRS}
            for gk in ("blocker", "glove", "rebounds", "recovery", "reflexes"):
                r[gk] = r[gk] if pos == "G" else 1
            posr = {"position_goalie": 20 if pos == "G" else 1, "position_left_defence": 20 if pos == "LD" else 1,
                    "position_right_defence": 20 if pos == "RD" else 1, "position_left_wing": 20 if pos == "LW" else 5,
                    "position_centre": 20 if pos == "C" else 5, "position_right_wing": 20 if pos == "RW" else 5}
            year = 1990 + rng.randint(0, 17) if c["club_id"] < 900 else 2007
            profiles.append(dict(player_id=pid, first_name=f"First{pid}", last_name=f"Last{pid}", date_of_birth=f"{1 + pid % 27}.{1 + pid % 12}.{year}",
                                 current_ability=ca, potential_ability=-15 if k == 11 else min(200, ca + 10), height_cm=185, weight_kg=88,
                                 handedness_label="Left", offensive_role_rating=12, defensive_role_rating=11, **posr, **r))
            nhl = c["club_id"] < 900
            staff.append(dict(player_data_ref=pid, staff_info_id=pid, forename=f"First{pid}", surname=f"Last{pid}", primary_nationality_code="CAN",
                              playing_for_ref=c["club_id"], contracted_club_ref=c["club_id"] if nhl else -1,
                              annual_salary_raw=rng.choice([0, 900000, 2500000, 9000000]) if nhl else 0, club_contract_expiry_year_raw=2027,
                              club_contract_expiry_day_raw=181, first_nhl_contract_year_raw=2020, job_for_club_label="Player", year_of_birth=year,
                              ambition=rng.randint(5, 20), loyalty=rng.randint(5, 20), adaptability=10, determination=15, pressure=12,
                              professionalism=14, sportsmanship=12, temperament=11))
            if not nhl and k < 3:
                rights.append(dict(league_name="National Hockey League", club_id=1 + k, staff_info_id=pid))
            pid += 1
    staff.append(dict(player_data_ref=-1, staff_name="Coach Invented", job_for_club_label="Head Coach", contracted_club_ref=1, year_of_birth=1970))
    staff.append(dict(player_data_ref=-1, staff_name="Gm Invented", job_for_club_label="General Manager", contracted_club_ref=2, year_of_birth=1965))
    clubs[0]["Capt: Name"], clubs[0]["Capt: DOB"] = profiles[12]["first_name"] + " " + profiles[12]["last_name"], profiles[12]["date_of_birth"]
    _w(root / "plain_english_exports/m298/players_hockey_profiles_m298.csv", profiles)
    _w(root / "plain_english_exports/m297/staff_normalized.csv", staff)
    _w(root / "exports/lookup/clubs_lookup.csv", clubs)
    _w(root / "plain_english_exports/m297/player_rights_normalized.csv", rights)
    return root


class ModelTests(unittest.TestCase):
    def test_derive_backfill_round_trip(self):
        eng = {a: 12 for a in ALL_ATTRS}
        rt = ratings_from_engine(eng, "C", overall=12.0, potential=13.0)
        self.assertEqual(set(RATING_COLS) - set(rt), set())
        back = derive(rt, "C")
        self.assertTrue(all(abs(back[a] - 12) <= 1 for a in eng if a not in ("goalie_positioning",) and back[a] != ""))
        self.assertEqual(primary_position(rt), "C")
        self.assertEqual(primary_position(ratings_from_engine(eng, "G")), "G")

    def test_anchoring_on_ability(self):
        rt = {a: 14 for a in NATIVE_ATTRS}
        ca = fit_ability({"S": [100 + i for i in range(40)], "G": [100 + i for i in range(40)]})
        lo = derive(dict(rt, current_ability=100), "C", None, ca)
        hi = derive(dict(rt, current_ability=139), "C", None, ca)
        self.assertGreater(overall_of(hi, "C"), overall_of(lo, "C") + 1.0)


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        fake_export(root / "export")
        cls.stats = EX.build(root / "export", root / "pack")
        cls.db = root / "world.db"
        build_db(root / "pack", cls.db)
        cls.game = root / "game.db"
        cls.game.write_bytes(cls.db.read_bytes())
        new_game(str(cls.game), "BOS", 3)
        cls.c = connect(str(cls.game))

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_pack(self):
        s = self.stats
        self.assertEqual(s["club_profiles"], 32)
        self.assertGreater(s["contracts"], 32 * 20)
        self.assertEqual(s["draft_rights"], 6)
        self.assertEqual(s["staff"], 2)
        rules = json.loads((Path(self.tmp.name) / "pack/rules.json").read_text())
        self.assertIn("engine", rules)
        self.assertEqual(rules["world"]["top_league_id"], "1")

    def test_world(self):
        c = self.c
        n = c.execute("SELECT COUNT(*) FROM players p JOIN teams t ON t.team_id=p.team_id WHERE t.league_id=1 AND p.status='active'").fetchone()[0]
        self.assertEqual(n, 32 * 23)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM player_ratings").fetchone()[0], c.execute("SELECT COUNT(*) FROM players").fetchone()[0])
        self.assertTrue(c.execute("SELECT 1 FROM pack_info WHERE key='engine_scale'").fetchone())
        self.assertEqual(c.execute("SELECT name, nickname FROM teams WHERE abbr='TBL'").fetchone()[1], "Lightning")
        cap = c.execute("SELECT parent_team_id FROM teams WHERE name='Laval Rocket'").fetchone()[0]
        self.assertEqual(cap, 18)                                         # MTL's affiliate
        self.assertTrue(c.execute("SELECT player_id FROM leadership WHERE team_id=4 AND role='C'").fetchone())

    def test_engine_scale_and_anchoring(self):
        import statistics as st
        rows = self.c.execute("SELECT a.*, p.position pos, r.current_ability ca FROM players p JOIN teams t ON t.team_id=p.team_id JOIN "
                              "player_attributes a USING (player_id) JOIN player_ratings r USING (player_id) WHERE t.league_id=1 AND "
                              "p.status='active' AND p.position<>'G'").fetchall()
        ov = [overall_of(dict(r), r["pos"]) for r in rows]
        self.assertAlmostEqual(st.mean(ov), 10.49, delta=0.15)
        self.assertAlmostEqual(st.pstdev(ov), 0.86, delta=0.15)
        self.assertGreater(st.correlation(ov, [r["ca"] for r in rows]), 0.95)

    def test_edit_moves_engine_and_ability(self):
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=4 AND position='C' AND status='active' LIMIT 1").fetchone()[0]
        before = RT.of(self.c, pid)
        e0 = dict(self.c.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone())
        RT.set_ratings(self.c, pid, {"stickhandling": 20, "deking": 20, "movement": 20, "anticipation": 20})
        after = RT.of(self.c, pid)
        e1 = dict(self.c.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone())
        self.assertGreaterEqual(after["current_ability"], before["current_ability"])
        self.assertGreaterEqual(e1["puck_control"], e0["puck_control"])
        with self.assertRaises(ValueError):
            RT.set_ratings(self.c, pid, {"nonsense": 3})

    def test_staff_and_gm_names(self):
        from hs.game import staff, org
        staff.setup(self.c)
        self.assertTrue(self.c.execute("SELECT 1 FROM staff WHERE name='Coach Invented' AND role='HC'").fetchone())
        org.setup(self.c, "2025-10-01")
        self.assertEqual(self.c.execute("SELECT gm_name FROM board WHERE team_id=5").fetchone()[0], "Gm Invented")


class LegacyWorldTests(unittest.TestCase):
    def test_backfill_and_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = small_world(tmp)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM player_ratings").fetchone()[0], c.execute("SELECT COUNT(*) FROM player_attributes").fetchone()[0])
            self.assertFalse(c.execute("SELECT 1 FROM pack_info WHERE key='engine_scale'").fetchone())
            from hs.game import world as Wd
            pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' LIMIT 1", (me,)).fetchone()[0]
            Wd.develop(c, "2026-08-01")
            r = RT.of(c, pid)
            self.assertIsNotNone(r["current_ability"])
            c.close()


if __name__ == "__main__":
    unittest.main()


class RegisterTests(unittest.TestCase):
    """The register items of v38: the start-up flow, the inbox, the screens' new data."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.c, cls.me = small_world(cls.tmp.name)
        from hs.game import welcome
        from hs.game.state import get_state
        cls.day = get_state(cls.c)[0]
        welcome.start_career(cls.c, cls.day)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_welcome_and_briefing(self):
        subs = [r[0] for r in self.c.execute("SELECT subject FROM inbox ORDER BY msg_id")]
        self.assertTrue(any(s.startswith("Welcome to the") for s in subs))
        self.assertTrue(any(s.startswith("Club briefing") for s in subs))
        self.assertIn("Your introductory press conference", subs)
        snd = self.c.execute("SELECT sender, actions FROM inbox WHERE subject LIKE 'Welcome to the%'").fetchone()
        self.assertTrue(snd[0].endswith("Owner"))
        self.assertIn("#board", snd[1])

    def test_intro_press_conference_weighs_the_promise(self):
        from hs.game import press, welcome
        p = [x for x in press.pending(self.c) if x["kind"] == "introduction"]
        self.assertTrue(p)
        qs = json.loads(p[0]["questions"])
        exp = json.loads(p[0]["context"])["expected"]
        far = "rebuild" if welcome.STANCES.index(exp) >= 2 else "contend"
        ch = [next((k for k, a in enumerate(q["answers"]) if a.get("stance") == far), 0) for q in qs]
        c0 = self.c.execute("SELECT confidence FROM board WHERE team_id=?", (self.me,)).fetchone()[0]
        out = press.answer(self.c, p[0]["press_id"], ch)
        self.assertTrue(any("Introductory press conference" in l for l in out["lines"]))
        self.assertLess(self.c.execute("SELECT confidence FROM board WHERE team_id=?", (self.me,)).fetchone()[0], c0)
        self.assertEqual(self.c.execute("SELECT kind FROM board_history ORDER BY rowid DESC LIMIT 1").fetchone()[0], "introduction")
        self.assertEqual(welcome.stance_effect("playoffs", "playoffs"), 4.0)

    def test_inbox_actions_flags_archive(self):
        from hs.game.state import add_message
        from hs.ui import api
        add_message(self.c, self.day, "Trade offer from XYZ", "They offer a pick. `accept 7` or `decline 7`.")
        v = api.inbox_view(self.c)
        m = next(x for x in v["messages"] if x["subject"] == "Trade offer from XYZ")
        self.assertEqual([a["cmd"] for a in m["actions"]], ["accept 7", "decline 7"])
        self.assertEqual(m["folder"], "trades")
        self.c.execute("UPDATE inbox SET flagged=1 WHERE msg_id=?", (m["msg_id"],))
        self.assertEqual(len(api.inbox_view(self.c, "flagged")["messages"]), 1)
        self.c.execute("UPDATE inbox SET archived=1 WHERE msg_id=?", (m["msg_id"],))
        self.assertFalse(any(x["msg_id"] == m["msg_id"] for x in api.inbox_view(self.c)["messages"]))
        self.assertTrue(any(x["msg_id"] == m["msg_id"] for x in api.inbox_view(self.c, "archived")["messages"]))
        owner = next(x for x in api.inbox_view(self.c)["messages"] if x["subject"].startswith("Welcome to the"))
        self.assertEqual(owner["folder"], "board")

    def test_screens_data(self):
        from hs.ui import api, screens
        d = screens.depth_chart(self.c)
        self.assertEqual(d["order"], ["G", "D", "LW", "C", "RW"])
        self.assertTrue(all(len(r["cells"]) == 7 for r in d["pick_grid"]))
        self.assertTrue(all(c["own"] for r in d["pick_grid"] for c in r["cells"]))
        c = api.contracts_view(self.c)
        self.assertEqual(len(c["grid_seasons"]), 5)
        self.assertTrue(all(len(g["cells"]) == 5 for g in c["grid"]))
        other = self.c.execute("SELECT team_id FROM teams WHERE league_id=1 AND team_id<>? LIMIT 1", (self.me,)).fetchone()[0]
        th = screens.transactions_hub(self.c, "upcoming", other)
        self.assertTrue(all(r["team_id"] == other for r in th["rows"]))
        lg = api.prospects_view(self.c, scope="league")
        self.assertTrue(lg["league"] and lg["rows"])
        self.assertFalse(any(r["potential"] is not None and r["known"] in ("D", "E") for r in lg["rows"]))
        pv = api.prospects_view(self.c, team=other)
        self.assertFalse(pv["mine"])
        self.assertEqual(set(screens.sim_leaders(self.c)), {"points", "goals", "goalies"})

    def test_captain_number(self):
        from hs.game import captaincy as CP
        cap = self.c.execute("SELECT player_id FROM leadership WHERE team_id=? AND role='C'", (self.me,)).fetchone()
        if not cap:
            self.skipTest("no captain")
        n, longest = CP.captain_number(self.c, self.me, cap[0])
        self.assertEqual(n, 1)
        self.c.execute("INSERT OR REPLACE INTO pack_info VALUES ('captains_before', ?)",
                       (json.dumps({self.c.execute("SELECT abbr FROM teams WHERE team_id=?", (self.me,)).fetchone()[0]: 31}),))
        self.assertEqual(CP.captain_number(self.c, self.me, cap[0])[0], 32)
