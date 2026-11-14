"""v61: the 2D game draws no offside (issue #24). The engine does not record offsides, so every zone entry the replay
draws has to be onside: the puck in before any attacker, at even strength, on the power play and three-on-three."""
import datetime
import sqlite3
import tempfile
import unittest
from unittest import mock

from hs.game.dayloop import sim_until
from hs.sim import ice2d, ice_plan as IP
from hs.sim.engine import Skill

from test_game import make_db
from test_sim import ENV

BLUE = ice2d.BLUE


def offside_entries(tr):
    """Read from the frames alone (not the engine's own counter): each time a carried puck comes all the way into a
    side's attacking zone, is a team-mate of the carrier already all the way in? A man on his way to the bench in a
    change is not in the play (he leaves the frames within a few seconds), so he does not count."""
    side_of = {k: p["side"] for k, p in enumerate(tr["players"]) if p["pos"] != "G"}
    inside = {0: False, 1: False}
    bad = []
    last = None
    frames = tr["frames"]
    present = [set(f[6::5]) for f in frames]
    for j, f in enumerate(frames):
        t = f[0] / 10.0
        per = min(int(t // 1200) + 1, 4)
        if per != last or f[1] & 2:                                   # a new period or a cut: nothing carries over
            last = per
            inside = {s: f[2] / 10.0 * IP.attack_dir(s, per) > BLUE for s in (0, 1)}
            continue
        mode = f[4] // 10
        px = f[2] / 10.0
        ents = {f[i]: f[i + 1] / 10.0 for i in range(6, len(f), 5)}
        for side in (0, 1):
            pu = px * IP.attack_dir(side, per)
            was = inside[side]
            if pu > BLUE + 0.5 + ice2d.PUCK_R:
                inside[side] = True
            elif pu < BLUE - 0.5 - ice2d.PUCK_R:
                inside[side] = False
            if was or not inside[side] or not (f[1] & 1) or mode != 0:
                continue
            c = f[5]
            if side_of.get(c) != side:
                continue
            for k, x in ents.items():
                if k != c and side_of.get(k) == side and x * IP.attack_dir(side, per) > BLUE + ice2d.ONSIDE + 0.5:
                    if all(k in present[i] for i in range(j, min(j + 40, len(frames)))):
                        bad.append((t, k))
    return bad


class OnsideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.c, cls.me = make_db(cls.tmp.name)
        sim_until(cls.c, ENV, Skill(), days=6)
        reg = [r[0] for r in cls.c.execute("SELECT game_id FROM games WHERE played=1 ORDER BY game_id LIMIT 4")]
        ot = [r[0] for r in cls.c.execute("SELECT game_id FROM games WHERE played=1 AND went_to_ot>=1 ORDER BY game_id LIMIT 2")]
        cls.gids = list(dict.fromkeys(reg + ot))
        cls.tracks = {g: ice2d.track(cls.c, g) for g in cls.gids}

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_the_engine_draws_no_offside(self):
        for gid, tr in self.tracks.items():
            self.assertEqual(tr["check"]["offside"], 0, gid)

    def test_frames_show_no_offside(self):
        for gid, tr in self.tracks.items():
            self.assertEqual(offside_entries(tr), [], gid)

    def test_the_blue_line_belongs_to_the_zone_the_puck_is_in(self):
        g, _ = ice2d.build(self.c, self.gids[0])
        g.mode = "play"
        d = g.dir(0)
        for x, want in ((BLUE + 2.0, True), (BLUE, True), (BLUE - 0.3, True), (BLUE - 2.0, False), (BLUE, False)):
            g.pk.x, g.pk.y = x * d, 0.0
            g.inzone[0] = g.zone(0)
            self.assertEqual(g.inzone[0], want, x)

    def test_no_pass_into_the_zone_while_a_man_is_in_ahead_of_it(self):
        g, _ = ice2d.build(self.c, self.gids[0])
        g.mode = "play"
        a, b = [p for p in g.pl.values() if p.side == 0 and p.grp != "G"][:2]
        g.sk[0] = [a, b]
        d = g.dir(0)
        g.pk.x, g.pk.y = (BLUE - 15.0) * d, 0.0
        g.inzone[0] = False
        a.x, b.x = (BLUE - 16.0) * d, (BLUE + 12.0) * d
        self.assertTrue(g.offside_risk(a, b))                           # b is in ahead of the puck
        b.x = (BLUE - 4.0) * d
        self.assertFalse(g.offside_risk(a, b))                          # onside: the pass can go
        g.pk.x = (BLUE + 10.0) * d
        g.inzone[0] = True
        a.x, b.x = (BLUE + 11.0) * d, (BLUE - 6.0) * d
        self.assertTrue(g.offside_risk(a, b))                           # it would leave the zone and come back


if __name__ == "__main__":
    unittest.main()


class LeagueFormatTests(unittest.TestCase):
    """v61: the leagues' real formats. On the fictional world, with a few leagues given other leagues' formats and a
    second tier made from KHL clubs, so every new structure is played: the Czech wild-card round, the Swiss play-in
    on aggregate goals, the Alps' second phase and picks, the EIHL's two-game quarterfinals and Final Four, and
    promotion and relegation between the SHL and HockeyAllsvenskan."""

    @classmethod
    def setUpClass(cls):
        import copy
        from pathlib import Path
        from hs.game import leagues as LG
        from hs.game.state import connect
        from hs.leaguedata import league_rules as LR
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        cls.LG = LG
        cls.saved = copy.deepcopy(LR.RULES)
        cls.addClassCleanup(lambda: (LR.RULES.clear(), LR.RULES.update(cls.saved)))
        for r in LR.RULES.values():                           # short seasons: the formats are what is tested
            r["games"] = min(r["games"], 16)
        LR.RULES["LIIGA"]["playoffs"] = copy.deepcopy(LR.RULES["ALPS"]["playoffs"])
        LR.RULES["DEL"]["playoffs"] = copy.deepcopy(LR.RULES["EIHL"]["playoffs"])
        LR.RULES["DEL"]["rs_title"] = "DEL regular-season title"
        cls.tmp = tempfile.TemporaryDirectory()
        world = make_mock_world.build(Path(cls.tmp.name) / "world.db", 3)
        Saves(Path(cls.tmp.name) / "saves", world).new_game("T", "PHM", 1)
        cls.c = c = connect(str(Path(cls.tmp.name) / "saves" / "T.db"))
        khl = c.execute("SELECT league_id FROM leagues WHERE abbr='KHL'").fetchone()[0]
        c.execute("INSERT INTO leagues (league_id, name, abbr, level) VALUES (9001, 'Swedish HockeyAllsvenskan', 'ALLSV', 3)")
        c.execute("UPDATE teams SET league_id=9001 WHERE team_id IN (SELECT team_id FROM teams WHERE league_id=? ORDER BY team_id LIMIT 12)", (khl,))
        cls.ids = {abbr: lid for lid, (abbr, _) in LG.leagues(c).items()}
        cls.year = LG._season_year(c)
        LG.ensure_season(c)
        LG.finish_year(c)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def series(self, abbr, label=None):
        q = "SELECT * FROM lg_series WHERE league_id=? AND season=? AND kind<>'bye'" + (" AND label=?" if label else "") + " ORDER BY round, idx"
        return self.c.execute(q, (self.ids[abbr], self.year) + ((label,) if label else ())).fetchall()

    def test_every_league_crowns_a_champion(self):
        for abbr, lid in self.ids.items():
            row = self.c.execute("SELECT phase, champion FROM lg_seasons WHERE league_id=? AND season=?", (lid, self.year)).fetchone()
            self.assertEqual(row[0], "done", abbr)
            self.assertIsNotNone(row[1], abbr)

    def test_czech_wild_card_round(self):
        wc = self.series("ELH", "wild-card round")
        self.assertEqual(sorted((r["seed_a"], r["seed_b"]) for r in wc), [(5, 12), (6, 11), (7, 10), (8, 9)])
        self.assertTrue(all(r["best_of"] == 5 for r in wc))

    def test_swiss_play_in_on_aggregate_goals(self):
        pi = self.series("NL", "play-in")
        self.assertEqual(len(pi), 3)
        for r in pi:
            self.assertEqual(r["kind"], "leg2")
            self.assertEqual(r["games"], 2)
            self.assertEqual(r["winner"], r["a"] if r["pts_a"] > r["pts_b"] else r["b"])
            goals = self.c.execute("SELECT home, hg, ag FROM lg_games WHERE series_id=?", (r["series_id"],)).fetchall()
            agg_a = sum(hg if h == r["a"] else ag for h, hg, ag in goals)
            self.assertEqual(agg_a, r["pts_a"])

    def test_alps_second_phase_and_picks(self):
        lid = self.ids["LIIGA"]
        groups = self.LG.group_tables(self.c, lid, self.year)
        self.assertEqual(list(groups), ["Master Round", "Qualification Round A", "Qualification Round B"])
        self.assertEqual([r["bonus"] for r in groups["Master Round"]].count(4), 1)
        self.assertTrue(all(r["gp"] == 8 for r in groups["Master Round"]))      # five clubs, each other twice
        self.assertEqual(len(self.series("LIIGA", "pre-playoffs")), 3)
        qf = self.series("LIIGA", "quarterfinals")
        self.assertEqual(len(qf), 4)
        master = [r["team_id"] for r in groups["Master Round"]]
        self.assertEqual({r["a"] for r in qf}, set(master[:4]))                 # the top four of the Master Round host

    def test_two_game_quarterfinals_final_four_and_bronze(self):
        qf = self.series("DEL", "quarterfinals")
        self.assertTrue(all(r["kind"] == "leg2" and r["games"] == 2 for r in qf))
        sf, final, bronze = self.series("DEL", "semifinals"), self.series("DEL", "final"), self.series("DEL", "bronze")
        self.assertTrue(all(r["best_of"] == 1 and r["games"] == 1 for r in sf + final + bronze))
        self.assertEqual(len(bronze), 1)
        losers = {r["a"] if r["winner"] == r["b"] else r["b"] for r in sf}
        self.assertEqual({bronze[0]["a"], bronze[0]["b"]}, losers)
        champ, runner = self.c.execute("SELECT champion, runner_up FROM lg_seasons WHERE league_id=? AND season=?",
                                       (self.ids["DEL"], self.year)).fetchone()
        self.assertEqual({champ, runner}, {final[0]["a"], final[0]["b"]})       # the bronze game is not the final
        self.assertTrue(self.c.execute("SELECT 1 FROM league_events WHERE summary LIKE '%DEL regular-season title%'").fetchone())

    def test_promotion_and_relegation(self):
        LG, c = self.LG, self.c
        shl, allsv = self.ids["SHL"], self.ids["ALLSV"]
        table = LG.standings(c, shl, self.year)
        po = c.execute("SELECT * FROM lg_series WHERE league_id=? AND season=?", (LG.PROREL_BASE - shl, self.year)).fetchall()
        self.assertEqual(len(po), 1)
        self.assertEqual((po[0]["a"], po[0]["b"], po[0]["best_of"]), (table[-2]["team_id"], table[-1]["team_id"], 7))
        loser = po[0]["a"] if po[0]["winner"] == po[0]["b"] else po[0]["b"]
        champ = c.execute("SELECT champion FROM lg_seasons WHERE league_id=? AND season=?", (allsv, self.year)).fetchone()[0]
        moves = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT team_id, from_lid, to_lid, up FROM lg_moves WHERE season=?", (self.year,))}
        self.assertEqual(moves, {champ: (allsv, shl, 1), loser: (shl, allsv, 0)})
        self.assertEqual(c.execute("SELECT league_id FROM teams WHERE team_id=?", (loser,)).fetchone()[0], shl)   # not yet
        LG.ensure_season(c, self.year + 1)
        self.assertEqual(c.execute("SELECT league_id FROM teams WHERE team_id=?", (loser,)).fetchone()[0], allsv)
        self.assertEqual(c.execute("SELECT league_id FROM teams WHERE team_id=?", (champ,)).fetchone()[0], shl)
        played = lambda t, lid: c.execute("SELECT COUNT(*) FROM lg_games WHERE (home=? OR away=?) AND season=? AND league_id=?",
                                          (t, t, self.year + 1, lid)).fetchone()[0]
        self.assertGreater(played(champ, shl), 0)
        self.assertGreater(played(loser, allsv), 0)
        old = {r["team_id"] for r in LG.standings(c, shl, self.year)}           # last season's table keeps its clubs
        self.assertIn(loser, old)
        self.assertNotIn(champ, old)
        view = LG.world_leagues_view(c, allsv, self.year)
        self.assertEqual(len(view["moves"]), 2)
        self.assertTrue(view["prorel"])

    def test_rules_in_words(self):
        txt = " ".join(self.LG.rules_text("ELH", self.saved["ELH"], {}))
        self.assertIn("5-12 in a wild-card round", txt)
        self.assertIn("Master Round", " ".join(self.LG.rules_text("ALPS", self.saved["ALPS"], {})))
        self.assertIn("aggregate goals", " ".join(self.LG.rules_text("EIHL", self.saved["EIHL"], {})))
        self.assertIn("goes up to the SHL", " ".join(self.LG.rules_text("ALLSV", self.saved["ALLSV"], {})))


class VeteranBonusTests(unittest.TestCase):
    """v61: one-year deals for 35+ and injured veterans can carry performance bonuses (CBA 50.2(b)(i))."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.c, cls.me = make_db(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def free_agent(self, age):
        from hs.game import contracts as K
        import datetime
        season = K.signing_year(self.c)
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id IS NULL AND status IN ('active','free_agent') AND position<>'G' "
                             "AND player_id NOT IN (SELECT player_id FROM vet_bonus) ORDER BY player_id LIMIT 1"
                             if self.c.execute("SELECT 1 FROM sqlite_master WHERE name='vet_bonus'").fetchone() else
                             "SELECT player_id FROM players WHERE team_id IS NULL AND status IN ('active','free_agent') AND position<>'G' "
                             "ORDER BY player_id LIMIT 1").fetchone()[0]
        born = datetime.date(season - age, 3, 1).isoformat()
        self.c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (born, pid))
        return pid, season

    def test_who_is_eligible(self):
        from hs.game import vetbonus as VB
        pid, season = self.free_agent(36)
        self.assertEqual(VB.eligible(self.c, pid, 1, season), "35+")
        self.assertIsNone(VB.eligible(self.c, pid, 2, season))                  # one-year deals only
        young, _ = self.free_agent(30)
        self.assertIsNone(VB.eligible(self.c, young, 1, season))

    def test_bonuses_buy_a_lower_cap_hit_and_are_earned_at_season_end(self):
        from hs.game import negotiation as N, vetbonus as VB, contracts as K
        pid, season = self.free_agent(37)
        v = N.open_talks(self.c, pid)
        self.assertEqual(v["perf"]["kind"], "35+")
        ask = v["asks"][1] if 1 in v["asks"] else v["asks"]["1"]
        base = max(K.crules(self.c)["min_salary"], int(ask * 0.6 / 5000) * 5000)
        perf = int((ask - base) / VB.PERF_VALUE * 1.1 / 5000) * 5000 + 5000
        out, _ = N.offer(self.c, pid, base, 1, perf=perf)
        self.assertEqual(out, "agreed")
        c = K.last_contract(self.c, pid)
        self.assertEqual(c["cap_hit"], base)                                    # the bonus is not in the cap hit
        b = VB.of_contract(self.c, c["contract_id"])
        self.assertEqual((b["kind"], b["max"], b["earned"]), ("35+", perf, None))
        earned = VB.season_end(self.c, c["start_year"])                        # no games: nothing earned
        self.assertEqual(earned, {})
        self.assertEqual(VB.of_contract(self.c, c["contract_id"])["parts"], "0000")

    def test_no_bonuses_for_others_or_past_the_cushion(self):
        from hs.game import negotiation as N, roster as R, vetbonus as VB, contracts as K
        young, _ = self.free_agent(28)
        N.open_talks(self.c, young)
        with self.assertRaises(R.RosterError):
            N.offer(self.c, young, 1_000_000, 1, perf=500_000)
        pid, _ = self.free_agent(36)
        N.open_talks(self.c, pid)
        with self.assertRaises(R.RosterError):
            N.offer(self.c, pid, 1_000_000, 1, perf=3_100_000)                 # more than 75% of the deal in bonuses
        cap, season = K.crules(self.c)["cap_ceiling"], K.signing_year(self.c)
        room = cap * (1 + VB.CUSHION) - K.payroll(self.c, self.me, season) - VB.pending(self.c, self.me, season)
        VB.check_cushion(self.c, self.me, int(room) - 1000)                    # inside the cushion
        with self.assertRaises(R.RosterError):
            VB.check_cushion(self.c, self.me, int(room) + 1000)                # past it


class TradeNeedsTabTests(unittest.TestCase):
    """v61: the trade screen's needs tab reads the same picture the trade AI uses."""

    def test_needs_tab(self):
        from hs.ui import api
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = make_db(tmp)
            other = c.execute("SELECT team_id FROM teams WHERE league_id=(SELECT league_id FROM teams WHERE team_id=?) AND team_id<>? "
                              "ORDER BY team_id LIMIT 1", (me, me)).fetchone()[0]
            v = api.trade_view(c, other)
            n = v["needs_tab"]
            self.assertEqual(set(n["them"]["groups"]), {"F", "D", "G"})
            for g in "FDG":
                self.assertEqual(n["them"]["groups"][g]["need"], v["needs"][g])  # the same scores the AI uses
            self.assertIn(n["them"]["posture"], ("contender", "middle", "seller"))
            for f in n["fits"]:
                self.assertGreaterEqual(n["them"]["groups"][f["group"]]["need"], 15)
            mine = {r[0] for r in c.execute("SELECT player_id FROM players WHERE team_id=?", (other,))}
            self.assertTrue(all(x["player_id"] in mine and x["friction"] < 60 for x in n["gettable"]))
            c.close()


class EuropeanClubTests(unittest.TestCase):
    """v61: running a club in a European league: contracts, transfers, loans, offers, the window, the summer."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from hs.game import europe as EU
        from hs.game.state import connect
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        cls.EU = EU
        cls.tmp = tempfile.TemporaryDirectory()
        world = make_mock_world.build(Path(cls.tmp.name) / "world.db", 3)
        Saves(Path(cls.tmp.name) / "saves", world).new_game("T", "PHM", 1)
        cls.c = c = connect(str(Path(cls.tmp.name) / "saves" / "T.db"))
        cls.day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
        cls.club = next(x for x in EU.clubs_to_run(c) if x["league"] == "SHL")["team_id"]
        EU.start(c, cls.club, cls.day)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.c.execute('UPDATE game_state SET "current_date"=?', (self.day,))

    def test_the_career(self):
        from hs.game.state import user_team
        from hs.game import gm
        c = self.c
        self.assertIsNone(user_team(c))                                        # the NHL seat is empty
        self.assertTrue(gm.unemployed(c))                                      # so NHL jobs are open to you
        self.assertEqual(self.EU.club(c), self.club)
        n = c.execute("SELECT COUNT(*) FROM players WHERE club_id=? AND team_id IS NULL", (self.club,)).fetchone()[0]
        self.assertEqual(c.execute("SELECT COUNT(*) FROM eu_contracts WHERE club_id=?", (self.club,)).fetchone()[0], n)
        v = self.EU.view(c)
        self.assertTrue(v["active"])
        self.assertGreater(v["budget"]["wage_budget"], v["wage_bill"])

    def test_free_agent_and_transfer(self):
        EU, c = self.EU, self.c
        free = EU.market(c, free_only=True, limit=5)
        if free:
            p = free[0]
            ok, _ = EU.bid(c, p["player_id"], 0, p["ask"], 1)
            self.assertTrue(ok)
            self.assertEqual(c.execute("SELECT club_id FROM players WHERE player_id=?", (p["player_id"],)).fetchone()[0], self.club)
        v = EU.view(c)
        room = v["budget"]["wage_budget"] - v["wage_bill"]
        bought = [x for x in EU.market(c, limit=5000) if x["fee"] and x["fee"] < v["budget"]["transfer_budget"] and x["league"] != "KHL"
                  and x["ask"] < room]
        x = bought[-1]
        ok, note = EU.bid(c, x["player_id"], int(x["fee"] * 0.5), x["ask"], 2)
        self.assertFalse(ok)                                                    # half the fee: no
        ok, note = EU.bid(c, x["player_id"], x["fee"], int(x["ask"] * 0.5), 2)
        self.assertFalse(ok)                                                    # his terms: no
        seller = x["club_id"]
        before = EU._budget(c, self.club)["transfer_budget"]
        ok, note = EU.bid(c, x["player_id"], x["fee"], x["ask"], 2)
        if ok:
            self.assertEqual(EU._budget(c, self.club)["transfer_budget"], before - x["fee"])
            self.assertEqual(EU.contract(c, x["player_id"])["club_id"], self.club)
        else:
            self.assertIn("best players", note)                                 # a club may keep its stars

    def test_loan_and_return(self):
        EU, c = self.EU, self.c
        v = EU.view(c)
        room = v["budget"]["wage_budget"] - v["wage_bill"]
        x = next(x for x in EU.market(c, limit=5000) if x["loanable"] and x["age"] <= 23 and x["wage"] * 0.6 < room)
        ok, _ = EU.loan(c, x["player_id"], 0.3)
        self.assertFalse(ok)                                                    # they want half of his wage at least
        ok, _ = EU.loan(c, x["player_id"], 0.6, until=self.day[:4] + "-12-31")
        self.assertTrue(ok)
        self.assertEqual(c.execute("SELECT club_id FROM players WHERE player_id=?", (x["player_id"],)).fetchone()[0], self.club)
        EU.daily(c, f"{int(self.day[:4]) + 1}-01-02")                          # the loan is over
        self.assertEqual(c.execute("SELECT club_id FROM players WHERE player_id=?", (x["player_id"],)).fetchone()[0], x["club_id"])

    def test_window(self):
        EU, c = self.EU, self.c
        self.assertTrue(EU.window_open("2026-07-01") and EU.window_open("2027-02-15"))
        self.assertFalse(EU.window_open("2027-02-16") or EU.window_open("2027-06-30"))
        c.execute('UPDATE game_state SET "current_date"=?', (f"{int(self.day[:4]) + 1}-03-01",))
        x = EU.market(c, free_only=True, limit=1) or EU.market(c, limit=1)
        with self.assertRaises(ValueError):
            EU.bid(c, x[0]["player_id"], x[0]["fee"], x[0]["ask"], 1)

    def test_offers_for_your_players(self):
        EU, c = self.EU, self.c
        d = datetime.date.fromisoformat(self.day)
        made = []
        for k in range(120):                                                    # about one offer every three weeks
            made += EU.ai_offers(c, (d + datetime.timedelta(days=k % 90)).isoformat()) if (d + datetime.timedelta(days=k % 90)).month != 3 else []
            if made:
                break
        self.assertTrue(made)
        o = c.execute("SELECT * FROM eu_offers WHERE from_club=? AND status='open' ORDER BY offer_id DESC", (self.club,)).fetchone()
        c.execute("UPDATE eu_offers SET day=? WHERE offer_id=?", (self.day, o["offer_id"]))
        before = EU._budget(c, self.club)["transfer_budget"]
        EU.respond(c, o["offer_id"], True, self.day)
        self.assertEqual(c.execute("SELECT club_id FROM players WHERE player_id=?", (o["player_id"],)).fetchone()[0], o["to_club"])
        self.assertEqual(EU._budget(c, self.club)["transfer_budget"], before + o["fee"])

    def test_summer_and_academy(self):
        EU, c = self.EU, self.c
        y = EU.season_year(c)
        mine = c.execute("SELECT player_id FROM eu_contracts WHERE club_id=? AND loan_from IS NULL LIMIT 2", (self.club,)).fetchall()
        c.execute("UPDATE eu_contracts SET until=? WHERE player_id IN (?,?)", (y, mine[0][0], mine[1][0]))
        ok, _ = EU.renew(c, mine[1][0], EU.renew_ask(c, mine[1][0]), 2)
        self.assertTrue(ok)
        prev = c.execute("SELECT value FROM pack_info WHERE key='season_state'").fetchone()
        c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state', 'free_agency')")   # 1 July
        EU.summer(c, f"{y + 1}-07-01")
        if prev:
            c.execute("UPDATE pack_info SET value=? WHERE key='season_state'", (prev[0],))
        else:
            c.execute("DELETE FROM pack_info WHERE key='season_state'")
        self.assertIsNone(c.execute("SELECT club_id FROM players WHERE player_id=?", (mine[0][0],)).fetchone()[0])  # out of contract
        self.assertEqual(c.execute("SELECT club_id FROM players WHERE player_id=?", (mine[1][0],)).fetchone()[0], self.club)
        n = c.execute("SELECT COUNT(*) FROM players WHERE club_id=?", (self.club,)).fetchone()[0]
        EU.academy(c, f"{y + 1}-09-15")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM players WHERE club_id=?", (self.club,)).fetchone()[0], n + EU.ACADEMY)

    def test_an_nhl_career_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = make_db(tmp)
            from hs.game import europe as EU
            self.assertFalse(EU.active(c))
            self.assertEqual(EU.daily(c, "2026-10-10"), [])
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='eu_contracts'").fetchone())
            c.close()


class EuropeanClubMoreTests(unittest.TestCase):
    """v61: your lineup and tactics, the board (objectives, review, the sack), European openings, the rest of Europe's
    window business and NHL clubs signing your players."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from hs.game import europe as EU
        from hs.game.state import connect
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        cls.EU = EU
        cls.tmp = tempfile.TemporaryDirectory()
        world = make_mock_world.build(Path(cls.tmp.name) / "world.db", 5)
        Saves(Path(cls.tmp.name) / "saves", world).new_game("T", "PHM", 1)
        cls.c = c = connect(str(Path(cls.tmp.name) / "saves" / "T.db"))
        cls.day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
        cls.club = next(x for x in EU.clubs_to_run(c) if x["league"] == "NL")["team_id"]
        EU.start(c, cls.club, cls.day)

    @classmethod
    def tearDownClass(cls):
        cls.c.close()
        cls.tmp.cleanup()

    def test_lineup_and_tactic_reach_the_results_model(self):
        # v61: the club you run is picked on the game's own Lines, Tactics and Lineups screens
        from hs.game import leagues as LG, lineup as L, lineups as LUP, tactics as TC, eu_lineup as EL
        c, me = self.c, self.EU.club(self.c) or self.club
        if self.EU.club(c) is None:
            return
        cur = L.current(c, me)
        self.assertTrue(cur and len(cur["F"]) == 4 and len(cur["D"]) == 3)
        dressed = {p for ln in cur["F"] for p in ln}
        spare = c.execute("SELECT player_id FROM players WHERE club_id=? AND team_id IS NULL AND status='active' AND position IN ('C','LW','RW') "
                          f"AND player_id NOT IN ({','.join(map(str, dressed))})", (me,)).fetchone()
        g1, g2 = cur["G"][:2]
        L.set_unit(c, me, "G", [g2, g1])                                       # the backup starts
        if spare:
            out = cur["F"][0][0]
            L.set_unit(c, me, "F1", [spare[0]] + cur["F"][0][1:])              # a scratch on line 1
        TC.ensure_table(c)
        TC.set_setting(c, me, "forecheck", "aggressive") if "forecheck" in TC.SETTINGS and "aggressive" in TC.SETTINGS["forecheck"][3] else None
        LUP.set_goalie_rule(c, me, "every_game")
        clubs, _ = LG._load_clubs(c, [me])
        cl = clubs[me]
        self.assertEqual(cl.goalies[0][1], g2)
        if spare:
            self.assertIn(spare[0], [p for _, p in cl.fwd])
            self.assertNotIn(out, [p for _, p in cl.fwd])
        self.assertEqual(cl.starter, 0.92)
        gf, ga = EL.effects(c, me)
        self.assertTrue(0.85 <= gf <= 1.15 and 0.85 <= ga <= 1.15)
        L.reset(c, me)
        LUP.set_goalie_rule(c, me, "usual")
        clubs, _ = LG._load_clubs(c, [me])
        self.assertEqual(clubs[me].starter, 0.70)

    def test_board_review_and_the_sack(self):
        from hs.game import eu_board as EB, leagues as LG, gm
        c, me = self.c, self.club
        b = EB.board(c)
        self.assertTrue(1 <= b["target"] <= 14)
        lid = c.execute("SELECT league_id FROM teams WHERE team_id=?", (me,)).fetchone()[0]
        LG.ensure_season(c)
        LG.finish_year(c)                                                       # the league season is played out
        c.execute("UPDATE eu_board SET confidence=10, target=1, reviewed=0 WHERE club_id=?", (me,))
        place, _ = EB._place(c, me)
        champ = c.execute("SELECT champion FROM lg_seasons WHERE league_id=? AND season=?", (lid, self.EU.season_year(c))).fetchone()[0]
        EB.review(c, "2027-05-01")
        if champ == me:
            self.assertEqual(self.EU.club(c), me)                               # champions are not sacked
            return
        self.assertIsNone(self.EU.club(c))                                      # sacked
        self.assertTrue(gm.unemployed(c))
        self.assertFalse(EB.free_choice(c))                                     # now you apply
        with self.assertRaises(ValueError):
            self.EU.start(c, me, "2027-05-01")
        self.assertIn(me, EB.vacancies(c))
        other = next(x["team_id"] for x in self.EU.clubs_to_run(c) if x["team_id"] != me)
        c.execute("INSERT OR REPLACE INTO eu_vacancy VALUES (?, '2027-05-01')", (other,))
        c.execute("UPDATE gm_extra SET data=json_set(data, '$.reputation', 99)") if c.execute(
            "SELECT 1 FROM sqlite_master WHERE name='gm_extra'").fetchone() else None
        from hs.game.gm import change_reputation
        change_reputation(c, 100)
        self.assertTrue(EB.apply(c, other, "2027-06-01"))                       # a big name gets the job
        self.assertEqual(self.EU.club(c), other)
        with self.assertRaises(ValueError):
            EB.apply(c, other, "2027-06-02")

    def test_window_business(self):
        from hs.game import eu_world as EW
        c = self.c
        moved = 0
        d = datetime.date(int(self.day[:4]) + 1, 7, 6)                          # Mondays in July
        while d.weekday() != 0:
            d += datetime.timedelta(days=1)
        for k in range(3):
            moved += len(c.execute("SELECT 1 FROM transactions WHERE txn_type='transfer'").fetchall()) * 0
            EW.window_moves(c, (d + datetime.timedelta(days=7 * k)).isoformat())
        n = c.execute("SELECT COUNT(*) FROM transactions WHERE txn_type='transfer' AND txn_date>=?", (d.isoformat(),)).fetchone()[0]
        self.assertGreater(n, 0)
        mine = self.EU.club(c)
        self.assertFalse(c.execute("SELECT 1 FROM transactions WHERE txn_type='transfer' AND txn_date>=? AND (to_team_id=? OR from_team_id=?)",
                                   (d.isoformat(), mine, mine)).fetchone())
        self.assertEqual(EW.window_moves(c, f"{int(self.day[:4]) + 1}-03-02"), [])   # the window is shut

    def test_nhl_signings(self):
        from hs.game import eu_world as EW
        c = self.c
        me = self.EU.club(c)
        if me is None:
            return
        bar = EW.nhl_threshold(c)
        young = c.execute("SELECT p.player_id FROM players p JOIN eu_contracts e USING (player_id) WHERE p.club_id=? AND "
                          "e.loan_from IS NULL AND p.team_id IS NULL AND p.position<>'G' LIMIT 6", (me,)).fetchall()
        for (pid,) in young:                                                    # make them NHL-ready
            c.execute("UPDATE player_attributes SET " + ", ".join(f"{k}=20" for k in
                      __import__("hs.worldgen", fromlist=["x"]).SKATER_KEYS) + " WHERE player_id=?", (pid,))
            c.execute("UPDATE players SET birth_date=? WHERE player_id=?", (f"{int(self.day[:4]) - 21}-01-01", pid))
        before = self.EU._budget(c, me)["transfer_budget"]
        lines = EW.nhl_signings(c, f"{int(self.day[:4]) + 1}-07-01")
        gone = c.execute(f"SELECT COUNT(*) FROM players WHERE team_id IS NOT NULL AND player_id IN ({','.join(str(p) for (p,) in young)})").fetchone()[0]
        self.assertGreater(gone, 0)
        khl = self.EU._meta_of_club(c, me)[0].get("abbr") == "KHL"              # the KHL has no transfer agreement
        self.assertEqual(self.EU._budget(c, me)["transfer_budget"], before + (0 if khl else gone * EW.NHL_FEE))


class FromTestingTests(unittest.TestCase):
    """v61, from Jeremy's testing: the sim centre follows a European coach's league; the club that fired you is not
    an opening for you (NHL or European) for a year."""

    def test_the_nhl_club_that_fired_you(self):
        from hs.game import gm, org
        with tempfile.TemporaryDirectory() as tmp:
            db, c, me = make_db(tmp)
            day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
            gm.lose_job(c, day, "fired")
            c.execute("UPDATE board SET vacancy=1 WHERE team_id=?", (me,))
            self.assertIn(me, org.vacancies(c))
            self.assertNotIn(me, [j["team_id"] for j in gm.job_market(c)["jobs"]])
            with self.assertRaises(ValueError):
                gm.apply_job(c, me, day)
            later = (datetime.date.fromisoformat(day) + datetime.timedelta(days=400)).isoformat()
            self.assertIsNone(gm.fired_from(c, later))                          # a year on, they would talk
            c.close()

    def test_the_sim_centre_follows_your_league(self):
        from pathlib import Path
        from types import SimpleNamespace
        from hs.game import europe as EU, eu_board as EB, leagues as LG
        from hs.game.state import connect
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        from hs.ui.simjob import eu_day_entry
        with tempfile.TemporaryDirectory() as tmp:
            world = make_mock_world.build(Path(tmp) / "world.db", 2)
            Saves(Path(tmp) / "saves", world).new_game("T", "PHM", 1)
            c = connect(str(Path(tmp) / "saves" / "T.db"))
            day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
            club = next(x for x in EU.clubs_to_run(c) if x["league"] == "NL")["team_id"]
            EU.start(c, club, day)
            LG.day(c, day)
            lid = c.execute("SELECT league_id FROM teams WHERE team_id=?", (club,)).fetchone()[0]
            gday = c.execute("SELECT day FROM lg_games WHERE league_id=? AND played=1 AND (home=? OR away=?) ORDER BY day DESC LIMIT 1",
                             (lid, club, club)).fetchone()[0]
            e = eu_day_entry(c, SimpleNamespace(day=gday, season_finished=False), club)
            clubs = {r[0] for r in c.execute("SELECT abbr FROM teams WHERE league_id=?", (lid,))}
            self.assertTrue(e["scores"])
            self.assertTrue(all(g["home"] in clubs and g["away"] in clubs for g in e["scores"]))   # only his league
            self.assertTrue(e["mine"] and e["mine"]["simple"])
            self.assertIn(club, (e["mine"]["home_id"], e["mine"]["away_id"]))
            self.assertTrue(any(r["mine"] for r in e["standings"]["groups"][0]["sections"][0]["rows"]))
            # sacked: that club is not an opening for you
            c.execute("UPDATE eu_board SET confidence=5, reviewed=0 WHERE club_id=?", (club,))
            c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('eu_sacked', ?)", (f"{club}:{day}",))
            c.execute("INSERT OR REPLACE INTO eu_vacancy VALUES (?,?)", (club, day))
            EU.leave(c)
            self.assertNotIn(club, [j["team_id"] for j in EB.jobs(c)["jobs"]])
            with self.assertRaises(ValueError):
                EB.apply(c, club, day)
            c.close()

    def test_a_new_game_can_start_at_a_european_club(self):
        from pathlib import Path
        from hs.game import europe as EU, gm
        from hs.game.state import connect
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        with tempfile.TemporaryDirectory() as tmp:
            world = make_mock_world.build(Path(tmp) / "world.db", 2)
            s = Saves(Path(tmp) / "saves", world)
            nl = next(l for l in s.leagues() if l["abbr"] == "NL")
            self.assertTrue(nl["europe"] and nl["playable"])
            self.assertFalse(next(l for l in s.leagues() if (l["level"] or 1) == 1)["europe"])
            clubs = s.eu_teams(nl["league_id"])
            self.assertTrue(clubs and all("strength" in x and x["outlook"] for x in clubs))
            self.assertEqual(s.eu_teams(next(l for l in s.leagues() if (l["level"] or 1) == 1)["league_id"]), [])
            club = clubs[-1]["team_id"]
            s.new_game("E", "PHM", 1, profile=dict(name="Test", unemployed=True, eu_club=club))
            c = connect(str(Path(tmp) / "saves" / "E.db"))
            self.assertEqual(EU.club(c), club)
            self.assertTrue(gm.unemployed(c))                                 # no NHL seat
            subjects = [r[0] for r in c.execute("SELECT subject FROM inbox")]
            self.assertTrue(any(x.startswith("Welcome to") for x in subjects))
            self.assertNotIn("Looking for work", subjects)
            import datetime                                                   # the day before his league opens
            day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
            self.assertEqual(day, (datetime.date.fromisoformat(EU.opening_day(c, club)) - datetime.timedelta(days=1)).isoformat())
            self.assertIsNotNone(c.execute("SELECT 1 FROM eu_board WHERE club_id=?", (club,)).fetchone())
            c.close()


class EuropeanLoanTests(unittest.TestCase):
    def test_ai_clubs_lend_young_players_down_within_their_system(self):
        import datetime
        from pathlib import Path
        from hs.game import europe as EU, eu_world as EW
        from hs.game.state import connect
        from hs.game.world import world_meta, age_on
        from hs.tools import make_mock_world
        from hs.ui.saves import Saves
        with tempfile.TemporaryDirectory() as tmp:
            world = make_mock_world.build(Path(tmp) / "world.db", 2)
            Saves(Path(tmp) / "saves", world).new_game("T", "PHM", 1)
            c = connect(str(Path(tmp) / "saves" / "T.db"))
            day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
            me = next(x for x in EU.clubs_to_run(c) if x["league"] == "SHL")["team_id"]
            EU.start(c, me, day)
            # the mock world has only top leagues: play the Liiga and the DEL as the SHL's and ELH's second tiers
            patch = mock.patch.dict(EW.TOP_COUNTRY, {"LIIGA": "SWE", "DEL": "CZE"})
            patch.start()
            self.addCleanup(patch.stop)
            d = datetime.date(EU.season_year(c), 8, 3)
            self.assertEqual(EW.window_loans(c, (d + datetime.timedelta(days=1)).isoformat()), [])   # Mondays only
            while d < datetime.date(EU.season_year(c) + 1, 2, 16):
                EW.window_loans(c, d.isoformat())
                d += datetime.timedelta(days=7)
            meta = world_meta(c)
            lo = {t: l for t, l in c.execute("SELECT team_id, league_id FROM teams")}
            loans = c.execute("SELECT c.player_id, c.club_id, c.loan_from, p.birth_date, p.club_id FROM eu_contracts c "
                              "JOIN players p USING (player_id) WHERE c.loan_from IS NOT NULL").fetchall()
            self.assertTrue(loans)
            on = datetime.date(EU.season_year(c), 9, 15)
            for pid, to, frm, birth, now in loans:
                self.assertEqual(to, now)
                self.assertNotIn(me, (to, frm))                                   # your club is left alone
                self.assertLessEqual(age_on(birth, on), 22)
                a, b = meta[lo[frm]], meta[lo[to]]
                self.assertGreater(a["mean"], b["mean"])                          # down, never up
                self.assertEqual(EW.country(a) == "RUS", EW.country(b) == "RUS")  # Russia keeps to itself
            EU.daily(c, EU.season_end(c)[:4] + "-05-02")                         # the season is over: home they go
            self.assertEqual(c.execute("SELECT COUNT(*) FROM eu_contracts WHERE loan_from IS NOT NULL").fetchone()[0], 0)
            c.close()


class CurrencyAndRussianTests(unittest.TestCase):
    STATIC = __import__("pathlib").Path(__file__).resolve().parent.parent / "hs" / "ui" / "static"

    def test_the_display_currency_is_a_setting(self):
        import re
        from hs.ui import settings as ST
        self.assertEqual(ST._clean({})["currency"], "USD")
        self.assertEqual(ST._clean({"currency": "RUB"})["currency"], "RUB")
        self.assertEqual(ST._clean({"currency": "XYZ"})["currency"], "USD")              # unknown codes are dropped
        app = (self.STATIC / "app.js").read_text(encoding="utf8")
        table = re.search(r"per_eur: \{([^}]*)\}", app).group(1)
        codes = set(re.findall(r"\b([A-Z]{3}):", table))
        self.assertEqual(codes, set(ST.CHOICES["currency"]))                            # every choice has a rate
        self.assertNotIn('"$" +', app)                                                   # money goes through money()

    def test_the_russian_interface_loads_and_is_russian(self):
        import json
        import re
        html = (self.STATIC / "index.html").read_text(encoding="utf8")
        self.assertLess(html.index("v59.js"), html.index("ru.js"))
        self.assertLess(html.index("ru.js"), html.index("v61.js"))                       # the boot line is last
        self.assertIn("bootApp()", (self.STATIC / "v61.js").read_text(encoding="utf8"))
        src = (self.STATIC / "ru.js").read_text(encoding="utf8")
        pairs = re.findall(r'^  ("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),?$', src, re.M)
        self.assertGreater(len(pairs), 1300)
        ru = {json.loads(k): json.loads(v) for k, v in pairs}
        latin = [k for k, v in ru.items() if not re.search("[А-Яа-яЁё]", v) and v not in ("Français (Québec)", "EBITDA", "+/-")]
        self.assertEqual(latin, [])                                                      # every entry is in Russian
        for k in ("File", "Lineup", "Power play", "Waivers", "Currency"):
            self.assertIn(k, ru)
        self.assertIn('"Русский"', (self.STATIC / "v39.js").read_text(encoding="utf8"))


class EuropeanEngineGameTests(unittest.TestCase):
    def test_your_clubs_games_are_played_by_the_engine_and_replayable(self):
        import datetime
        from pathlib import Path
        from hs.game import europe as EU, eu_match as EM, leagues as LG
        from hs.game.state import connect
        from hs.sim import ice2d
        from hs.tools import make_mock_world
        from hs.ui import api
        from hs.ui.saves import Saves
        from hs.ui.screens import sim_leaders
        from hs.ui.simjob import eu_day_entry
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            world = make_mock_world.build(Path(tmp) / "world.db", 2)
            Saves(Path(tmp) / "saves", world).new_game("T", "PHM", 1)
            c = connect(str(Path(tmp) / "saves" / "T.db"))
            day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
            club = next(x for x in EU.clubs_to_run(c) if x["league"] == "NL")["team_id"]
            EU.start(c, club, day)
            nhl_before = c.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0]
            later = (datetime.date.fromisoformat(day) + datetime.timedelta(days=12)).isoformat()
            LG.day(c, later, 1, ENV, Skill())
            lid = c.execute("SELECT league_id FROM teams WHERE team_id=?", (club,)).fetchone()[0]
            mine = c.execute("SELECT game_id, hg, ag FROM lg_games WHERE league_id=? AND played=1 AND (home=? OR away=?)",
                             (lid, club, club)).fetchall()
            self.assertTrue(mine)
            for gid_lg, hg, ag in mine:                                       # every one of them went to the engine
                gid = EM.of_lg_game(c, gid_lg)
                self.assertIsNotNone(gid)
                m = c.execute("SELECT hg, ag FROM eu_match WHERE match_id=?", (gid - EM.EU_BASE,)).fetchone()
                self.assertEqual((m[0], m[1]), (hg, ag))
            others = c.execute("SELECT COUNT(*) FROM lg_games WHERE league_id=? AND played=1 AND home<>? AND away<>?",
                               (lid, club, club)).fetchone()[0]
            self.assertEqual(c.execute("SELECT COUNT(*) FROM eu_match").fetchone()[0], len(mine))   # nobody else's
            self.assertGreater(others, 0)
            gid = EM.of_lg_game(c, mine[0][0])
            with EM.shadow(c, gid):
                v = api.game_view(c, gid)
                self.assertEqual(sorted([v["recap"]["home_goals"], v["recap"]["away_goals"]]), sorted(mine[0][1:]))
                tr = ice2d.track(c, gid)
                self.assertTrue(tr["frames"])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_temp_master").fetchone()[0], 0)    # the view is gone
            self.assertEqual(c.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0], nhl_before)  # NHL untouched
            st = c.execute("SELECT SUM(gp) FROM skater_season_stats WHERE team_id=? AND source='league'", (club,)).fetchone()[0]
            self.assertGreater(st or 0, 0)                                    # his players' lines reach the league's stats
            # the sim centre: the full card, linked to the game page; the leaders are the league's
            gday = c.execute("SELECT day FROM lg_games WHERE game_id=?", (mine[0][0],)).fetchone()[0]
            e = eu_day_entry(c, SimpleNamespace(day=gday, season_finished=False), club)
            self.assertEqual(e["mine"]["game_id"], gid)
            self.assertFalse(e["mine"].get("simple"))
            self.assertIn(f"#game/{gid}", [x["href"] for x in e["scores"]])
            c.execute("UPDATE manager SET team_id=NULL")
            lead = sim_leaders(c)
            ab = {r[0] for r in c.execute("SELECT abbr FROM teams WHERE league_id=?", (lid,))}
            self.assertTrue(lead["points"])
            self.assertTrue(all(r["team"] in ab for r in lead["points"] + lead["goals"]))
            c.close()


class EuropeanLeagueScreensTests(unittest.TestCase):
    def test_the_league_screens_follow_your_european_league(self):
        import datetime
        from pathlib import Path
        from hs.game import europe as EU, leagues as LG
        from hs.game.state import connect
        from hs.tools import make_mock_world
        from hs.ui import api, stats as ST
        from hs.ui.saves import Saves
        with tempfile.TemporaryDirectory() as tmp:
            world = make_mock_world.build(Path(tmp) / "world.db", 2)
            Saves(Path(tmp) / "saves", world).new_game("T", "PHM", 1)
            c = connect(str(Path(tmp) / "saves" / "T.db"))
            day = c.execute('SELECT "current_date" FROM game_state').fetchone()[0]
            club = next(x for x in EU.clubs_to_run(c) if x["league"] == "NL")["team_id"]
            EU.start(c, club, day)
            LG.day(c, (datetime.date.fromisoformat(day) + datetime.timedelta(days=12)).isoformat(), 1, ENV, Skill())
            lid = c.execute("SELECT league_id FROM teams WHERE team_id=?", (club,)).fetchone()[0]
            f = api.focus_leagues(c)
            self.assertEqual(f["mine"], lid)
            self.assertEqual([l["league_id"] for l in f["leagues"]][:2], [f["nhl"], lid])     # the NHL, then yours
            self.assertEqual(api.state(c)["eu_club"]["league_id"], lid)
            sch = api.schedule(c)
            self.assertTrue(sch["europe"] and sch["results"] and sch["upcoming"])
            self.assertTrue(all(g["game_id"] for g in sch["results"]))                        # each with its page
            cal = api.calendar_view(c)
            self.assertTrue(any(e["label"] == "Transfer window closes" for e in cal["events"]))
            self.assertEqual(len(cal["games"]), c.execute("SELECT COUNT(*) FROM lg_games WHERE home=? OR away=?", (club, club)).fetchone()[0])
            n = api.news_view(c, "league")
            self.assertTrue(n["recaps"] and n["power"])
            self.assertEqual({r["team"] for r in n["power"]}, {r[0] for r in c.execute("SELECT abbr FROM teams WHERE league_id=?", (lid,))})
            hub = ST.hub(c, None, lid)
            self.assertTrue(any(r["mine"] for r in hub["skaters"]))                           # your players are marked
            self.assertTrue(ST.team_page(c, club)["mine"])
            c.close()
