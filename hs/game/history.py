"""The record book (docs/STATS.md): what each season leaves behind once its playoffs are over.

At the end of every simulated NHL season (hs.game.dayloop.finish_season calls season_end):
  * goalie decisions: the goalie with the most ice time for a club in a game gets the win, loss or overtime loss,
    and a shutout when he allowed nothing; folded into goalie_season_stats (W, L, OTL, SO, GS)
  * playoff stats: every playoff box score folded into skater/goalie_season_stats with split 'PO'
  * team_seasons: each club's final record, its place in division, conference and league, and how its playoffs
    ended (missed, first round ... lost the final, champion)
  * awards (AWARDS below): voted on numbers the game records. Names are the NHL's (kept for personal use; see
    docs/DATAPACK_SPEC.md on publishing)
Idempotent per season. The live season's equivalents are worked out on the fly by hs.ui.stats.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

from .events import emit, player_name, team_abbr
from .state import add_message, user_team

AWARDS = {
    "art_ross": ("Art Ross Trophy", "most points"),
    "richard": ("Maurice Richard Trophy", "most goals"),
    "hart": ("Hart Trophy", "most valuable player"),
    "vezina": ("Vezina Trophy", "best goaltender"),
    "norris": ("Norris Trophy", "best defenceman"),
    "calder": ("Calder Trophy", "best rookie"),
    "conn_smythe": ("Conn Smythe Trophy", "playoff MVP"),
    "selke": ("Frank J. Selke Trophy", "best defensive forward"),
    "allstar_c": ("First All-Star Team", "centre"), "allstar_lw": ("First All-Star Team", "left wing"),
    "allstar_rw": ("First All-Star Team", "right wing"), "allstar_d1": ("First All-Star Team", "defence"),
    "allstar_d2": ("First All-Star Team", "defence"), "allstar_g": ("First All-Star Team", "goal"),
    "presidents": ("Presidents' Trophy", "best regular-season record"),
    "hobey": ("Hobey Baker Award", "best college player"),
    "jack_adams": ("Jack Adams Award", "coach of the year"),
    "gm_year": ("Jim Gregory General Manager of the Year Award", "general manager of the year"),
}
# who decides each one (shown on awards night and in the awards message)
VOTERS = {"art_ross": "the scoring race", "richard": "the goal race", "presidents": "the standings",
          "hart": "the Professional Hockey Writers' Association", "norris": "the Professional Hockey Writers' Association",
          "calder": "the Professional Hockey Writers' Association", "conn_smythe": "the Professional Hockey Writers' Association",
          "vezina": "the league's general managers", "gm_year": "the league's general managers and a media panel",
          "jack_adams": "the NHL Broadcasters' Association", "hobey": "the Hobey Baker Memorial Award Foundation", "selke": "the Professional Hockey Writers' Association",
          **{k: "the Professional Hockey Writers' Association" for k in ("allstar_c", "allstar_lw", "allstar_rw", "allstar_d1",
                                                                         "allstar_d2", "allstar_g")}}
ROUND_WORDS = {0: "missed the playoffs", 1: "lost in the first round", 2: "lost in the second round",
               3: "lost in the conference final", 4: "lost in the final", 5: "won the championship"}


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS team_seasons (season_start_year INTEGER, team_id INTEGER, league_id INTEGER, "
                 "gp INTEGER, w INTEGER, l INTEGER, otl INTEGER, t INTEGER, pts INTEGER, gf INTEGER, ga INTEGER, "
                 "div_rank INTEGER, conf_rank INTEGER, league_rank INTEGER, playoff_round INTEGER, playoff_text TEXT, "
                 "PRIMARY KEY (season_start_year, team_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS awards (season_start_year INTEGER, award TEXT, player_id INTEGER, "
                 "team_id INTEGER, staff_id INTEGER, detail TEXT, PRIMARY KEY (season_start_year, award))")


def goalie_decisions(conn, season_id, game_type="RS"):
    """{goalie: dict(gs, w, l, otl, so)} for a season's games."""
    games = {g[0]: g for g in conn.execute(
        "SELECT game_id, home_team_id, away_team_id, home_goals, away_goals, went_to_ot FROM games WHERE season_id=? "
        "AND game_type=? AND played=1", (season_id, game_type))}
    best = {}
    for r in conn.execute("SELECT s.game_id, s.team_id, s.player_id, s.toi_sec, s.shots_against, s.saves FROM "
                          "player_game_stats s JOIN players p USING (player_id) JOIN games g USING (game_id) WHERE "
                          "g.season_id=? AND g.game_type=? AND p.position='G'", (season_id, game_type)):
        k = (r[0], r[1])
        if k not in best or (r[3] or 0) > best[k][1]:
            best[k] = (r[2], r[3] or 0)
    out = defaultdict(lambda: dict(gs=0, w=0, l=0, otl=0, so=0))
    for (gid, team), (pid, _) in best.items():
        g = games.get(gid)
        if g is None:
            continue
        home = team == g[1]
        gf, ga = (g[3], g[4]) if home else (g[4], g[3])
        d = out[pid]
        d["gs"] += 1
        if gf > ga:
            d["w"] += 1
        elif g[5]:
            d["otl"] += 1
        else:
            d["l"] += 1
        if ga == 0:
            d["so"] += 1
    return dict(out)


def _fold_playoffs(conn, season_id, year, league):
    rows = conn.execute(
        "SELECT s.player_id, s.team_id, p.position, COUNT(*) gp, SUM(s.goals) g, SUM(s.assists) a, SUM(s.shots) sog, "
        "SUM(s.toi_sec) toi, SUM(s.saves) sv, SUM(s.shots_against) sa FROM player_game_stats s JOIN games g USING "
        "(game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND g.game_type='PO' GROUP BY s.player_id, "
        "s.team_id", (season_id,)).fetchall()
    dec = goalie_decisions(conn, season_id, "PO")
    for r in rows:
        if r["position"] == "G":
            d = dec.get(r["player_id"], {})
            conn.execute("INSERT INTO goalie_season_stats (player_id, season_start_year, team_id, league_id, split, gp, gs, "
                         "toi_sec, w, l, otl, so, ga, sa) VALUES (?,?,?,?, 'PO', ?,?,?,?,?,?,?,?,?)",
                         (r["player_id"], year, r["team_id"], league, r["gp"], d.get("gs", 0), r["toi"], d.get("w", 0),
                          d.get("l", 0), d.get("otl", 0), d.get("so", 0), (r["sa"] or 0) - (r["sv"] or 0), r["sa"]))
        else:
            conn.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a, "
                         "sog, toi_sec) VALUES (?,?,?,?, 'PO', ?,?,?,?,?)",
                         (r["player_id"], year, r["team_id"], league, r["gp"], r["g"], r["a"], r["sog"], r["toi"]))


def _playoff_rounds(conn, season_id):
    """{team: furthest round reached (1-4) and 5 for the champion}."""
    series = defaultdict(lambda: defaultdict(int))
    teams_in = defaultdict(set)
    for g in conn.execute("SELECT series_id, home_team_id, away_team_id, home_goals, away_goals FROM games WHERE "
                          "season_id=? AND game_type='PO' AND played=1", (season_id,)):
        w = g[1] if g[3] > g[4] else g[2]
        series[g[0]][w] += 1
        teams_in[g[0]] |= {g[1], g[2]}
    reached = {}
    for sid, teams in teams_in.items():
        rnd = 4 if sid == "Final" else 3 if sid.startswith("Conference") else 2 if sid.startswith("R2") else \
            int(sid[1]) if sid[:1] == "R" and sid[1:2].isdigit() else 1
        for t in teams:
            reached[t] = max(reached.get(t, 0), rnd)
        if sid == "Final":
            w = max(series[sid], key=series[sid].get)
            reached[w] = 5
    return reached


def _team_seasons(conn, season_id, year, league):
    from ..league import standings as st
    from ..league.season import db_rules, team_rows
    rules = db_rules(conn)
    rec, h2h = st.table(conn, season_id)
    order = st.rank(rec, h2h, rules)
    info = {t["team_id"]: t for t in team_rows(conn)}
    reached = _playoff_rounds(conn, season_id)
    conf_pos, div_pos = defaultdict(int), defaultdict(int)
    out = {}
    for i, t in enumerate(order):
        r = rec[t]
        conf_pos[info[t]["conference"]] += 1
        div_pos[(info[t]["conference"], info[t]["division"])] += 1
        rnd = reached.get(t, 0)
        out[t] = rnd
        conn.execute("INSERT OR REPLACE INTO team_seasons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (year, t, league, r["gp"], r["w"], r["l"], r["otl"], r.get("t", 0), st.points(r, rules["points"]),
                      r["gf"], r["ga"], div_pos[(info[t]["conference"], info[t]["division"])],
                      conf_pos[info[t]["conference"]], i + 1, rnd, ROUND_WORDS[rnd]))
    return order, out


def _award(conn, year, key, day, player_id=None, team_id=None, staff_id=None, detail=""):
    conn.execute("INSERT OR REPLACE INTO awards VALUES (?,?,?,?,?,?)", (year, key, player_id, team_id, staff_id, detail))
    name = AWARDS[key][0]
    who = player_name(conn, player_id) if player_id else (team_abbr(conn, team_id) if team_id else "")
    if staff_id:
        r = conn.execute("SELECT name FROM staff WHERE staff_id=?", (staff_id,)).fetchone()
        who = r[0] if r else who
    if key.startswith("allstar_"):
        name = f"a First All-Star Team place ({AWARDS[key][1]})"
    emit(conn, "AWARD_WON", day, f"{who} wins {'the ' if not key.startswith('allstar_') else ''}{name} ({detail})", team_id=team_id, player_id=player_id,
         importance=3 if key in ("hart", "conn_smythe", "presidents") else 1 if key.startswith("allstar_") else 2, award=key, season=year)
    return who


def _awards(conn, season_id, year, order, day):
    from . import world as W
    rows = conn.execute(
        "SELECT s.player_id, s.team_id, p.position, p.birth_date, COUNT(*) gp, SUM(s.goals) g, SUM(s.assists) a, "
        "SUM(s.toi_sec) toi, SUM(s.saves) sv, SUM(s.shots_against) sa FROM player_game_stats s JOIN games g USING "
        "(game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND g.game_type='RS' GROUP BY s.player_id",
        (season_id,)).fetchall()
    sk = [dict(r) for r in rows if r["position"] != "G" and r["gp"] >= 20]
    gl = [dict(r) for r in rows if r["position"] == "G" and r["gp"] >= 25]
    if not sk:
        return []
    for x in sk:
        x["p"] = (x["g"] or 0) + (x["a"] or 0)
    won = []
    top = max(sk, key=lambda x: (x["p"], x["g"]))
    won.append(("art_ross", _award(conn, year, "art_ross", day, top["player_id"], top["team_id"], detail=f"{top['p']} points")))
    top = max(sk, key=lambda x: (x["g"], x["p"]))
    won.append(("richard", _award(conn, year, "richard", day, top["player_id"], top["team_id"], detail=f"{top['g']} goals")))
    # Hart: points a game, weighted towards players on good teams (the voters' habit)
    rank = {t: i for i, t in enumerate(order)}
    n = max(1, len(order))
    hart = max(sk, key=lambda x: x["p"] / x["gp"] * 82 * (1.15 - 0.3 * rank.get(x["team_id"], n) / n))
    won.append(("hart", _award(conn, year, "hart", day, hart["player_id"], hart["team_id"],
                               detail=f"{hart['p']} points in {hart['gp']} games")))
    d = [x for x in sk if x["position"] == "D"]
    if d:
        nor = max(d, key=lambda x: x["p"] / x["gp"] * 82 + 2.0 * (x["toi"] or 0) / x["gp"] / 60)
        won.append(("norris", _award(conn, year, "norris", day, nor["player_id"], nor["team_id"],
                                     detail=f"{nor['p']} points, {round((nor['toi'] or 0) / nor['gp'] / 60, 1)} minutes a game")))
    if gl:
        xg = {r[0]: (r[1] or 0) for r in conn.execute(
            "SELECT e.opp_player_id, SUM(e.xg) FROM game_events e JOIN games g USING (game_id) WHERE g.season_id=? AND "
            "g.game_type='RS' AND e.event_type IN ('shot','goal') GROUP BY 1", (season_id,))}
        for x in gl:
            x["gsax"] = xg.get(x["player_id"], 0) - ((x["sa"] or 0) - (x["sv"] or 0))
        vez = max(gl, key=lambda x: x["gsax"])
        won.append(("vezina", _award(conn, year, "vezina", day, vez["player_id"], vez["team_id"],
                                     detail=f"{(vez['sv'] or 0) / max(1, vez['sa'] or 0):.3f} save %, {vez['gsax']:+.1f} goals saved above expected")))
    # Calder: no more than 25 NHL games in any earlier season, and 25 or younger
    prior = {r[0] for r in conn.execute("SELECT player_id FROM skater_season_stats WHERE league_id=1 AND split='RS' AND "
                                        "season_start_year<? AND gp>25", (year,))}
    rookies = [x for x in sk if x["player_id"] not in prior and W.age_on(x["birth_date"], __import__("datetime").date(year, 9, 15)) <= 25]
    if rookies:
        cal = max(rookies, key=lambda x: (x["p"] / x["gp"] * 82, x["p"]))
        won.append(("calder", _award(conn, year, "calder", day, cal["player_id"], cal["team_id"],
                                     detail=f"{cal['p']} points in {cal['gp']} games")))
    # Conn Smythe: the champion's best playoff performer (points, or a goalie's saves above average)
    champ = next((t for t, r in _playoff_rounds(conn, season_id).items() if r == 5), None)
    if champ:
        po = conn.execute("SELECT s.player_id, p.position, SUM(s.goals)+SUM(s.assists) pts, SUM(s.saves) sv, "
                          "SUM(s.shots_against) sa FROM player_game_stats s JOIN games g USING (game_id) JOIN players p "
                          "USING (player_id) WHERE g.season_id=? AND g.game_type='PO' AND s.team_id=? GROUP BY 1",
                          (season_id, champ)).fetchall()
        if po:
            def score(r):
                if r["position"] == "G":
                    return ((r["sv"] or 0) - 0.905 * (r["sa"] or 0)) * 0.9 if r["sa"] else 0
                return r["pts"] or 0
            cs = max(po, key=score)
            det = (f"{(cs['sv'] or 0) / max(1, cs['sa'] or 0):.3f} save % in the playoffs" if cs["position"] == "G"
                   else f"{cs['pts']} playoff points")
            won.append(("conn_smythe", _award(conn, year, "conn_smythe", day, cs["player_id"], champ, detail=det)))
    # v45: the Selke (defensive skill and the minutes to use it, on a club that keeps the puck out, with a nod to points)
    # and the First All-Star Team (the Hart's measure by position, the Norris's for defence, the Vezina's in goal)
    attrs = {r[0]: r[1:] for r in conn.execute("SELECT player_id, defensive_awareness, positioning, stick_checking, faceoffs FROM "
                                               "player_attributes")}
    ga = {}
    for r in conn.execute("SELECT CASE WHEN s.team_id=g.home_team_id THEN g.home_team_id ELSE g.away_team_id END t, "
                          "SUM(CASE WHEN s.team_id=g.home_team_id THEN g.away_goals ELSE g.home_goals END), COUNT(*) FROM "
                          "(SELECT DISTINCT game_id, team_id FROM player_game_stats) s JOIN games g USING (game_id) WHERE "
                          "g.season_id=? AND g.game_type='RS' GROUP BY 1", (season_id,)):
        ga[r[0]] = r[1] / r[2] if r[2] else 3.0
    lg_ga = sum(ga.values()) / len(ga) if ga else 3.0
    fw = [x for x in sk if x["position"] != "D" and x["gp"] >= 50]
    if fw:
        def selke(x):
            a = attrs.get(x["player_id"]) or (10, 10, 10, 10)
            skill = (a[0] * 0.4 + a[1] * 0.3 + a[2] * 0.2 + (a[3] if x["position"] == "C" else a[2]) * 0.1)
            mins = (x["toi"] or 0) / x["gp"] / 60
            return skill * mins * (lg_ga / ga.get(x["team_id"], lg_ga)) + 0.15 * x["p"] / x["gp"] * 82
        sel = max(fw, key=selke)
        won.append(("selke", _award(conn, year, "selke", day, sel["player_id"], sel["team_id"],
                                    detail=f"{round((sel['toi'] or 0) / sel['gp'] / 60, 1)} minutes a game, {sel['p']} points")))
    star = lambda x: x["p"] / x["gp"] * 82 * (1.15 - 0.3 * rank.get(x["team_id"], n) / n) * min(1.0, x["gp"] / 60)
    taken = set()
    for key, posn in (("allstar_c", "C"), ("allstar_lw", "LW"), ("allstar_rw", "RW")):
        pool = [x for x in sk if x["position"] == posn and x["gp"] >= 40 and x["player_id"] not in taken]
        if pool:
            b = max(pool, key=star)
            taken.add(b["player_id"])
            _award(conn, year, key, day, b["player_id"], b["team_id"], detail=f"{b['p']} points")
    nscore = lambda x: (x["p"] / x["gp"] * 82 + 2.0 * (x["toi"] or 0) / x["gp"] / 60) * min(1.0, x["gp"] / 60)
    for key, b in zip(("allstar_d1", "allstar_d2"), sorted([x for x in sk if x["position"] == "D" and x["gp"] >= 40], key=nscore, reverse=True)[:2]):
        _award(conn, year, key, day, b["player_id"], b["team_id"], detail=f"{b['p']} points")
    if gl:
        b = max(gl, key=lambda x: x["gsax"])
        _award(conn, year, "allstar_g", day, b["player_id"], b["team_id"], detail=f"{(b['sv'] or 0) / max(1, b['sa'] or 0):.3f} save %")
    from ..league import standings as st
    from ..league.season import db_rules
    rec, _ = st.table(conn, season_id)
    pts = db_rules(conn)["points"]
    won.append(("presidents", _award(conn, year, "presidents", day, team_id=order[0],
                                     detail=f"{st.points(rec[order[0]], pts)} points")))
    # Jack Adams: the head coach whose club beat its expected finish (last season's points) by the most
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        last = {r[0]: r[1] for r in conn.execute("SELECT team_id, pts FROM team_seasons WHERE season_start_year=?",
                                                 (year - 1,))}
        best, gain = None, None
        for t in order:
            now = st.points(rec[t], pts)
            g = now - last.get(t, now - 0)
            if last and (gain is None or g > gain):
                best, gain = t, g
        if best is None:
            best = order[0]
        hc = conn.execute("SELECT staff_id FROM staff WHERE team_id=? AND role='HC'", (best,)).fetchone()
        if hc:
            won.append(("jack_adams", _award(conn, year, "jack_adams", day, team_id=best, staff_id=hc[0],
                                             detail=f"{st.points(rec[best], pts)} points" + (f", {gain:+d} on last season" if last else ""))))
    # GM of the year (the GMs vote): improvement on last season plus playoff success
    last = {r[0]: r[1] for r in conn.execute("SELECT team_id, pts FROM team_seasons WHERE season_start_year=?", (year - 1,))}
    rounds = _playoff_rounds(conn, season_id)
    gm_score = lambda t: (st.points(rec[t], pts) - last.get(t, st.points(rec[t], pts))) + 6 * rounds.get(t, 0) + st.points(rec[t], pts) / 20
    gm_t = max(order, key=gm_score)
    me = user_team(conn)
    gm_name = None
    if gm_t == me:
        r = conn.execute("SELECT name FROM gm_profile WHERE id=1").fetchone() if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='gm_profile'").fetchone() else None
        gm_name = r[0] if r else "You"
    det = (f"{gm_name}: " if gm_name else "") + f"{st.points(rec[gm_t], pts)} points" + (
        f", {st.points(rec[gm_t], pts) - last[gm_t]:+d} on last season" if gm_t in last else "") + (
        f", {ROUND_WORDS[rounds[gm_t]]}" if rounds.get(gm_t) else "")
    won.append(("gm_year", _award(conn, year, "gm_year", day, team_id=gm_t, detail=det)))
    return won


def awards_message(conn, year):
    """The awards night message: one line per trophy, who decided it, and why."""
    lines = []
    for key, (name, what) in AWARDS.items():
        r = conn.execute("SELECT * FROM awards WHERE season_start_year=? AND award=?", (year, key)).fetchone()
        if r is None:
            continue
        who = player_name(conn, r["player_id"]) if r["player_id"] else ""
        if r["staff_id"]:
            x = conn.execute("SELECT name FROM staff WHERE staff_id=?", (r["staff_id"],)).fetchone()
            who = x[0] if x else who
        club = team_abbr(conn, r["team_id"]) if r["team_id"] else ""
        who = f"{who} ({club})" if who and club else (who or club)
        lines.append(f"- {name} ({what}): {who}. {r['detail'] or ''} [{VOTERS.get(key, '')}]")
    return lines


def season_end(conn, season_id, day):
    ensure_tables(conn)
    year, league = conn.execute("SELECT start_year, league_id FROM seasons WHERE season_id=?", (season_id,)).fetchone()
    key = f"history_{year}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return []
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    for pid, d in goalie_decisions(conn, season_id).items():
        conn.execute("UPDATE goalie_season_stats SET gs=?, w=?, l=?, otl=?, so=? WHERE player_id=? AND season_start_year=? "
                     "AND league_id=? AND split='RS'", (d["gs"], d["w"], d["l"], d["otl"], d["so"], pid, year, league))
    _fold_playoffs(conn, season_id, year, league)
    order, reached = _team_seasons(conn, season_id, year, league)
    won = _awards(conn, season_id, year, order, day)
    me = user_team(conn)
    if me is not None and won:
        add_message(conn, day, "League awards", f"The {year}-{(year + 1) % 100:02d} NHL awards.\n" + "\n".join(awards_message(conn, year))
                    + "\nThe full ceremony is on the Awards Night screen (League > Awards Night).")
        r = reached.get(me)
        if r is not None:
            add_message(conn, day, "Season summary", season_summary(conn, me, year, r))
    return won


def backfill(conn):
    """Record book for NHL seasons simulated before v27 (once per season; needs their box scores)."""
    ensure_tables(conn)
    from .world import top_league_id
    try:
        top = top_league_id(conn)
    except Exception:
        top = 1
    done = []
    if repair_lower(conn):
        conn.commit()
    for sid, year, end in conn.execute("SELECT season_id, start_year, end_date FROM seasons WHERE league_id=? ORDER BY "
                                       "start_year", (top,)).fetchall():
        if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (f"history_{year}",)).fetchone():
            continue
        if not conn.execute("SELECT 1 FROM games WHERE season_id=? AND game_type='PO' AND played=1", (sid,)).fetchone():
            continue
        if not conn.execute("SELECT 1 FROM pack_info WHERE key=?", (f"stats_recorded_{year}",)).fetchone():
            continue
        day = end or f"{year + 1}-06-20"
        conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (f"history_{year}",))
        for pid, d in goalie_decisions(conn, sid).items():
            conn.execute("UPDATE goalie_season_stats SET gs=?, w=?, l=?, otl=?, so=? WHERE player_id=? AND "
                         "season_start_year=? AND league_id=? AND split='RS'", (d["gs"], d["w"], d["l"], d["otl"], d["so"],
                                                                                pid, year, top))
        if not conn.execute("SELECT 1 FROM skater_season_stats WHERE season_start_year=? AND league_id=? AND split='PO'",
                            (year, top)).fetchone():
            _fold_playoffs(conn, sid, year, top)
        order, _ = _team_seasons(conn, sid, year, top)
        _awards(conn, sid, year, order, day)
        done.append(year)
    if done:
        conn.commit()
    return done



def repair_lower(conn):
    """Saves from before v27 have lower-league seasons scored by the old formula (a good NCAA player could put up
    four points a game). Rescale those seasons once: keep each league's order of scorers, map their points a game onto
    the v27 curve (hs.game.world.LOWER_PPG at the same rank), keep each player's goal share."""
    import statistics
    from .world import LOWER_PPG, LOWER_Z, top_league_id
    try:
        top = top_league_id(conn)
    except Exception:
        top = 1
    abbr = {r[0]: r[1] for r in conn.execute("SELECT league_id, abbr FROM leagues")}
    nd = statistics.NormalDist()
    fixed = []
    for (key,) in conn.execute("SELECT key FROM pack_info WHERE key LIKE 'lower_stats_%'").fetchall():
        year = int(key.rsplit("_", 1)[1])
        flag = f"lower_v27_{year}"
        if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (flag,)).fetchone():
            continue
        conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (flag,))
        for (lid,) in conn.execute("SELECT DISTINCT league_id FROM skater_season_stats WHERE season_start_year=? AND "
                                   "league_id<>? AND split='RS'", (year, top)).fetchall():
            rows = conn.execute("SELECT s.rowid, s.gp, s.g, s.a, p.position FROM skater_season_stats s JOIN players p USING "
                                "(player_id) WHERE s.season_start_year=? AND s.league_id=? AND s.split='RS' AND s.gp>0",
                                (year, lid)).fetchall()
            if not rows:
                continue
            base = LOWER_PPG.get(abbr.get(lid), 0.45)
            order = sorted(rows, key=lambda r: ((r[2] + r[3]) / r[1]) / (0.5 if r[4] == "D" else 1.0))
            n = len(order)
            for i, r in enumerate(order):
                z = max(-2.5, min(3.0, nd.inv_cdf((i + 0.5) / n)))
                ppg = base * (0.5 if r[4] == "D" else 1.0) * math.exp(LOWER_Z * z)
                pts = int(round(ppg * r[1]))
                share = r[2] / (r[2] + r[3]) if (r[2] + r[3]) else (0.25 if r[4] == "D" else 0.45)
                g = min(pts, int(round(pts * share)))
                conn.execute("UPDATE skater_season_stats SET g=?, a=? WHERE rowid=?", (g, pts - g, r[0]))
        fixed.append(year)
    return fixed


def season_summary(conn, team, year, reached):
    """The end-of-season letter from the league office: record, finish, playoffs, leaders, what comes next."""
    ts = conn.execute("SELECT * FROM team_seasons WHERE season_start_year=? AND team_id=?", (year, team)).fetchone()
    if ts is None:
        return f"Your season: {ROUND_WORDS[reached]}."
    yr = f"{year}-{(year + 1) % 100:02d}"
    lines = [f"Your {yr} season is over: {ROUND_WORDS[reached]}.",
             f"Record {ts['w']}-{ts['l']}-{ts['otl']}, {ts['pts']} points: {_ord(ts['div_rank'])} in the division, "
             f"{_ord(ts['conf_rank'])} in the conference, {_ord(ts['league_rank'])} in the league. Goals {ts['gf']} for, {ts['ga']} against."]
    lead = conn.execute("SELECT p.first_name||' '||p.last_name, s.g, s.a FROM skater_season_stats s JOIN players p USING (player_id) "
                        "WHERE s.season_start_year=? AND s.team_id=? AND s.split='RS' ORDER BY s.g+s.a DESC LIMIT 3", (year, team)).fetchall()
    if lead:
        lines.append("Leading scorers: " + "; ".join(f"{r[0]} {r[1]}-{r[2]}-{r[1] + r[2]}" for r in lead) + ".")
    prev = conn.execute("SELECT pts FROM team_seasons WHERE season_start_year=? AND team_id=?", (year - 1, team)).fetchone()
    if prev:
        lines.append(f"That is {ts['pts'] - prev[0]:+d} points on last season.")
    lines.append("Next: the board reviews the season, then the draft lottery and the draft. Your expiring contracts are on the "
                 "Transactions tab.")
    return "\n".join(lines)


def _ord(n):
    n = int(n or 0)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"