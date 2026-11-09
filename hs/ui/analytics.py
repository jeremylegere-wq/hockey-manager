"""Advanced analytics for the UI (docs/ANALYTICS.md): team process and luck, player and goalie value, contract
efficiency, and playoff odds, all from the simulated season's recorded events.

Definitions (this season, regular season):
  attempts (Corsi)    shots on goal + missed + blocked; CF% = attempts for / (for + against)
  xG                  the engine's goal probability of each shot on goal (recorded with the event), summed;
                      empty-net goals carry no xG. xGF% = xGF / (xGF + xGA)
  PDO                 shooting % + save % (x1000; 1000 is average; far from it usually means luck)
  goals above xG      goals - xG (finishing, or luck)
  GSAx                goalie: xG of the shots on goal he faced - goals he allowed
  expected points     a Pythagorean expectation: GF^2 / (GF^2 + GA^2) x games x 2
  playoff odds        2,000 simulations of the remaining schedule; each game's home-win chance from the two clubs'
                      strength (goal difference per game, half from xG), with ~23% of games reaching overtime; the
                      league's playoff format decides who qualifies (ties broken at random)
"""
from __future__ import annotations

import math
import random
import statistics

from ..game import contracts as K
from ..game.state import get_state, user_team
from ..league import standings as st
from ..league.season import db_rules, team_rows
from ..schema import top_league_sql

_CACHE = {}


def _sid(conn):
    return conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]


def _teams(conn):
    return {r["team_id"]: dict(r) for r in conn.execute(f"SELECT team_id, abbr, name, nickname, conference, division "
                                                       f"FROM teams WHERE {top_league_sql()}")}


def team_table(conn):
    sid = _sid(conn)
    tm = _teams(conn)
    T = {t: dict(team_id=t, abbr=v["abbr"], name=v["name"], gp=0, gf=0, ga=0, sf=0, sa=0, cf=0, ca=0, xgf=0.0,
                 xga=0.0, pim=0) for t, v in tm.items()}
    q = ("SELECT e.team_id t, CASE WHEN e.team_id=g.home_team_id THEN g.away_team_id ELSE g.home_team_id END o, "
         "e.event_type k, COUNT(*) n, COALESCE(SUM(e.xg), 0) x FROM game_events e JOIN games g USING (game_id) "
         "WHERE g.season_id=? AND g.game_type='RS' AND e.period<=4 GROUP BY 1, 2, 3")
    for r in conn.execute(q, (sid,)):
        a, o = T.get(r["t"]), T.get(r["o"])
        if a is None or o is None:
            continue
        k = r["k"]
        if k in ("shot", "goal", "miss", "block"):
            a["cf"] += r["n"]
            o["ca"] += r["n"]
        if k in ("shot", "goal"):
            a["sf"] += r["n"]
            o["sa"] += r["n"]
            a["xgf"] += r["x"]
            o["xga"] += r["x"]
        if k == "penalty":
            a["pim"] += r["n"]
    rec, _ = st.table(conn, sid)
    rules = db_rules(conn)
    for t, x in T.items():
        r = rec.get(t)
        if not r:
            continue
        x.update(gp=r["gp"], gf=r["gf"], ga=r["ga"], pts=st.points(r, rules["points"]))
    out = []
    for x in T.values():
        gp = max(1, x["gp"])
        x["cf_pct"] = round(100 * x["cf"] / max(1, x["cf"] + x["ca"]), 1)
        x["xgf_pct"] = round(100 * x["xgf"] / max(1e-9, x["xgf"] + x["xga"]), 1) if x["xgf"] + x["xga"] else 50.0
        x["sh_pct"] = round(100 * x["gf"] / max(1, x["sf"]), 1)
        x["sv_pct"] = round(1 - x["ga"] / max(1, x["sa"]), 3)
        x["pdo"] = round(1000 * (x["gf"] / max(1, x["sf"]) + 1 - x["ga"] / max(1, x["sa"])))
        x["xgf_gp"], x["xga_gp"] = round(x["xgf"] / gp, 2), round(x["xga"] / gp, 2)
        x["gf_gp"], x["ga_gp"] = round(x["gf"] / gp, 2), round(x["ga"] / gp, 2)
        x["g_minus_xg"] = round(x["gf"] - x["xgf"], 1)
        x["exp_pts"] = round(x["gf"] ** 2 / max(1, x["gf"] ** 2 + x["ga"] ** 2) * x["gp"] * 2, 1) if x["gp"] else 0
        x["pts"] = x.get("pts", 0)
        x["luck"] = round(x["pts"] - x["exp_pts"], 1)
        x["xgf"], x["xga"] = round(x["xgf"], 1), round(x["xga"], 1)
        out.append(x)
    out.sort(key=lambda x: -x["xgf_pct"])
    return out


def team_games(conn, team):
    """Game by game for one club: goals, xG, attempts for and against (for rolling charts)."""
    sid = _sid(conn)
    games = conn.execute("SELECT game_id, game_date, home_team_id, away_team_id, home_goals, away_goals FROM games WHERE "
                         "season_id=? AND game_type='RS' AND played=1 AND (home_team_id=? OR away_team_id=?) ORDER BY "
                         "game_date", (sid, team, team)).fetchall()
    ab = {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    agg = {}
    for r in conn.execute("SELECT e.game_id g, e.team_id=? mine, e.event_type k, COUNT(*) n, COALESCE(SUM(e.xg),0) x "
                          "FROM game_events e JOIN games g USING (game_id) WHERE g.season_id=? AND g.game_type='RS' AND "
                          "(g.home_team_id=? OR g.away_team_id=?) AND e.period<=4 GROUP BY 1, 2, 3",
                          (team, sid, team, team)):
        a = agg.setdefault(r["g"], dict(xgf=0.0, xga=0.0, cf=0, ca=0, sf=0, sa=0))
        side = "f" if r["mine"] else "a"
        if r["k"] in ("shot", "goal", "miss", "block"):
            a["c" + side] += r["n"]
        if r["k"] in ("shot", "goal"):
            a["xg" + side] += r["x"]
            a["s" + side] += r["n"]
    out = []
    for g in games:
        home = g["home_team_id"] == team
        a = agg.get(g["game_id"], {})
        out.append(dict(game_id=g["game_id"], date=g["game_date"], opp=ab[g["away_team_id"] if home else g["home_team_id"]],
                        gf=g["home_goals"] if home else g["away_goals"], ga=g["away_goals"] if home else g["home_goals"],
                        xgf=round(a.get("xgf", 0), 2), xga=round(a.get("xga", 0), 2), cf=a.get("cf", 0),
                        ca=a.get("ca", 0), sf=a.get("sf", 0), sa=a.get("sa", 0)))
    return out


def skaters(conn, team=None, min_gp=5):
    sid = _sid(conn)
    ab = {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    ind = {}
    for r in conn.execute("SELECT e.player_id p, e.event_type k, COUNT(*) n, COALESCE(SUM(e.xg),0) x FROM game_events e "
                          "JOIN games g USING (game_id) WHERE g.season_id=? AND g.game_type='RS' AND e.period<=4 AND "
                          "e.event_type IN ('shot','goal','miss','block') GROUP BY 1, 2", (sid,)):
        d = ind.setdefault(r["p"], dict(icf=0, ixg=0.0))
        d["icf"] += r["n"]
        if r["k"] in ("shot", "goal"):
            d["ixg"] += r["x"]
    q = ("SELECT s.player_id, p.first_name, p.last_name, p.position, p.team_id, COUNT(*) gp, SUM(s.goals) g, "
         "SUM(s.assists) a, SUM(s.shots) sog, SUM(s.toi_sec) toi FROM player_game_stats s JOIN games g USING (game_id) "
         "JOIN players p USING (player_id) WHERE g.season_id=? AND g.game_type='RS' AND p.position<>'G' "
         + ("AND p.team_id=? " if team else "") + "GROUP BY s.player_id HAVING gp>=?")
    out = []
    year = K.season_year(conn)
    for r in conn.execute(q, (sid, team, min_gp) if team else (sid, min_gp)):
        d = ind.get(r["player_id"], dict(icf=0, ixg=0.0))
        toi = (r["toi"] or 0) / 3600
        pts = (r["g"] or 0) + (r["a"] or 0)
        c = K.current_contract(conn, r["player_id"], year)
        out.append(dict(player_id=r["player_id"], name=f"{r['first_name']} {r['last_name']}", pos=r["position"],
                        team=ab.get(r["team_id"], "FA"), gp=r["gp"], g=r["g"] or 0, a=r["a"] or 0, p=pts,
                        sog=r["sog"] or 0, icf=d["icf"], ixg=round(d["ixg"], 1), gax=round((r["g"] or 0) - d["ixg"], 1),
                        sh_pct=round(100 * (r["g"] or 0) / max(1, r["sog"] or 0), 1),
                        toi_gp=round(toi * 60 / max(1, r["gp"]), 1), p60=round(pts / toi, 2) if toi else 0,
                        ixg60=round(d["ixg"] / toi, 2) if toi else 0, cap=c["cap_hit"] if c else None))
    out.sort(key=lambda x: -x["p"])
    return out


def goalies(conn, min_gp=3):
    sid = _sid(conn)
    ab = {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    xga = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT e.opp_player_id, SUM(e.event_type='goal'), COUNT(*), COALESCE(SUM(e.xg),0) FROM game_events e JOIN games g "
        "USING (game_id) WHERE g.season_id=? AND g.game_type='RS' AND e.period<=4 AND e.event_type IN ('shot','goal') "
        "AND e.opp_player_id IS NOT NULL GROUP BY 1", (sid,))}
    out = []
    year = K.season_year(conn)
    for r in conn.execute("SELECT s.player_id, p.first_name, p.last_name, p.team_id, COUNT(*) gp, SUM(s.saves) sv, "
                          "SUM(s.shots_against) sa, SUM(s.toi_sec) toi FROM player_game_stats s JOIN games g USING "
                          "(game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND g.game_type='RS' AND "
                          "p.position='G' AND s.shots_against>0 GROUP BY s.player_id HAVING gp>=?", (sid, min_gp)):
        ga, sa, x = xga.get(r["player_id"], (0, 0, 0.0))
        toi = (r["toi"] or 0) / 3600
        c = K.current_contract(conn, r["player_id"], year)
        out.append(dict(player_id=r["player_id"], name=f"{r['first_name']} {r['last_name']}", team=ab.get(r["team_id"], "FA"),
                        gp=r["gp"], sa=r["sa"] or 0, sv_pct=round((r["sv"] or 0) / max(1, r["sa"] or 0), 3),
                        ga=ga, xga=round(x, 1), gsax=round(x - ga, 1), gsax60=round((x - ga) / toi, 2) if toi else 0,
                        cap=c["cap_hit"] if c else None))
    out.sort(key=lambda x: -x["gsax"])
    return out


def playoff_odds(conn, sims=2000):
    day = get_state(conn)[0]
    sid = _sid(conn)
    key = (id(conn), day, sid, conn.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0])
    if key in _CACHE:
        return _CACHE[key]
    rules = db_rules(conn)
    rec, h2h = st.table(conn, sid)
    info = {t["team_id"]: t for t in team_rows(conn)}
    teams = sorted(info)
    tt = {x["team_id"]: x for x in team_table(conn)}
    strength = {}
    for t in teams:
        x = tt.get(t)
        gp = max(1, x["gp"]) if x else 1
        gd = ((x["gf"] - x["ga"]) / gp) if x else 0.0
        xgd = (x["xgf_gp"] - x["xga_gp"]) if x else 0.0
        shrink = gp / (gp + 20)                       # early in the season everybody is closer to average
        strength[t] = shrink * (0.5 * gd + 0.5 * xgd)
    left = conn.execute("SELECT home_team_id, away_team_id FROM games WHERE season_id=? AND game_type='RS' AND played=0",
                        (sid,)).fetchall()
    pts_rule = rules["points"]
    base = {t: st.points(rec[t], pts_rule) if t in rec else 0 for t in teams}
    po = rules["playoffs"]
    from ..league.playoffs import qualify_conference_top_n, qualify_division_wildcard
    made = {t: 0 for t in teams}
    div_win = {t: 0 for t in teams}
    pts_sum = {t: 0.0 for t in teams}
    rng = random.Random(f"odds-{day}")
    for _ in range(sims):
        pts = dict(base)
        for h, a in left:
            ph = 1 / (1 + math.exp(-(1.1 * (strength.get(h, 0) - strength.get(a, 0)) + 0.1)))
            ot = rng.random() < 0.23
            if rng.random() < ph:
                pts[h] += pts_rule["win"]
                if ot:
                    pts[a] += pts_rule["ot_loss"]
            else:
                pts[a] += pts_rule["win"]
                if ot:
                    pts[h] += pts_rule["ot_loss"]
        order = sorted(teams, key=lambda t: (-pts[t], rng.random()))
        q = (qualify_division_wildcard if po["format"] == "division_wildcard" else qualify_conference_top_n)(order, list(info.values()), po)
        for conf, d in q.items():
            ins = [t for dv in d.get("divisions", {}).values() for t in dv] + d.get("wildcards", []) + d.get("seeds", [])
            for t in ins:
                made[t] += 1
            for dv in d.get("divisions", {}).values():
                if dv:
                    div_win[dv[0]] += 1
        for t in teams:
            pts_sum[t] += pts[t]
    me = user_team(conn)
    out = [dict(team_id=t, abbr=info[t]["abbr"], name=info[t]["name"], conference=info[t]["conference"],
                division=info[t]["division"], pts=base[t], proj=round(pts_sum[t] / sims, 1),
                playoffs=round(100 * made[t] / sims, 1), division_title=round(100 * div_win[t] / sims, 1),
                strength=round(strength[t], 2), mine=t == me) for t in teams]
    out.sort(key=lambda x: (-x["playoffs"], -x["proj"]))
    res = dict(rows=out, sims=sims, games_left=len(left))
    _CACHE.clear()
    _CACHE[key] = res
    return res


def contracts(conn):
    """Cap hit against production for every NHL skater and goalie with 10+ games (the efficiency frontier)."""
    sk = [dict(x, kind="skater", prod=round(x["p"] / max(1, x["gp"]) * 82, 1)) for x in skaters(conn, min_gp=10) if x["cap"]]
    gl = [dict(x, kind="goalie", prod=x["gsax"]) for x in goalies(conn, min_gp=10) if x["cap"]]
    for x in sk:
        x["per_m"] = round(x["prod"] / (x["cap"] / 1e6), 1)
    sk.sort(key=lambda x: -x["per_m"])
    return dict(skaters=sk, goalies=gl)


def view(conn, tab="teams", team=None):
    me = user_team(conn)
    team = team or me
    tm = _teams(conn)
    base = dict(tab=tab, team=team, me=me, teams=[dict(team_id=t, abbr=v["abbr"]) for t, v in sorted(tm.items(), key=lambda kv: kv[1]["abbr"])],
                abbr=tm.get(team, {}).get("abbr"), season=K.season_year(conn))
    if tab == "teams":
        base["rows"] = team_table(conn)
    elif tab == "team":
        base["games"] = team_games(conn, team)
        base["skaters"] = skaters(conn, team, min_gp=1)
        rows = team_table(conn)
        base["league"] = rows
        base["row"] = next((r for r in rows if r["team_id"] == team), None)
        xs = [r for r in conn.execute(
            "SELECT e.xg, e.team_id=? mine FROM game_events e JOIN games g USING (game_id) WHERE g.season_id=? AND "
            "g.game_type='RS' AND (g.home_team_id=? OR g.away_team_id=?) AND e.event_type IN ('shot','goal') AND "
            "e.xg IS NOT NULL", (team, _sid(conn), team, team))]
        base["xg_for"] = [round(r[0], 3) for r in xs if r[1]]
        base["xg_against"] = [round(r[0], 3) for r in xs if not r[1]]
    elif tab == "players":
        base["skaters"] = skaters(conn)
        base["goalies"] = goalies(conn)
    elif tab == "contracts":
        base.update(contracts(conn))
    elif tab == "odds":
        base.update(playoff_odds(conn))
    else:
        raise ValueError("tabs: teams, team, players, contracts, odds")
    return base
