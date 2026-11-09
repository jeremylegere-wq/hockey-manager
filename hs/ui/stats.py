"""The stats hub (docs/STATS.md): league leaders, league-wide and team stat tables for any season and league, team
pages in the style of hockeydb (season by season, roster stats, franchise leaders), the league's history (champions,
awards, all-time leaders) and the player-page extras (career by team and season, game log, percentile ranks).

Seasons already finished read the season tables (skater/goalie_season_stats, team_seasons, awards). The NHL season
in progress is worked out from the box scores (player_game_stats), so the hub is live during the season.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

from ..game import contracts as K
from ..game.state import get_state, user_team


def _teams(conn):
    return {r[0]: dict(team_id=r[0], abbr=r[1], name=r[2], nickname=r[3] or "", league_id=r[4], parent=r[5],
                       conference=r[6], division=r[7])
            for r in conn.execute("SELECT team_id, abbr, name, nickname, league_id, parent_team_id, conference, division "
                                  "FROM teams")}


def _leagues(conn):
    return {r[0]: dict(league_id=r[0], name=r[1], abbr=r[2], level=r[3])
            for r in conn.execute("SELECT league_id, name, abbr, level FROM leagues")}


def _top(conn):
    from ..game.world import top_league_id
    try:
        return top_league_id(conn)
    except Exception:
        return 1


def _current(conn):
    """(season_id, start_year) of the NHL season the game is in, and whether its box scores are still live."""
    r = conn.execute("SELECT season_id, start_year FROM seasons WHERE league_id=? ORDER BY start_year DESC LIMIT 1",
                     (_top(conn),)).fetchone()
    if r is None:
        return None, None, False
    recorded = conn.execute("SELECT 1 FROM pack_info WHERE key=?", (f"stats_recorded_{r[1]}",)).fetchone()
    return r[0], r[1], not recorded


def seasons(conn, league_id=None):
    league_id = league_id or _top(conn)
    ys = {r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM skater_season_stats WHERE league_id=?",
                                     (league_id,))}
    sid, yr, live = _current(conn)
    if live and league_id == _top(conn) and conn.execute("SELECT 1 FROM games WHERE season_id=? AND played=1",
                                                          (sid,)).fetchone():
        ys.add(yr)
    return sorted(ys, reverse=True)


def _age(birth, year):
    if not birth:
        return None
    b = datetime.date.fromisoformat(birth)
    on = datetime.date(year, 9, 15)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def _live_skaters(conn, sid, split, team=None):
    q = ("SELECT s.player_id, s.team_id, COUNT(*) gp, SUM(s.goals) g, SUM(s.assists) a, SUM(s.shots) sog, "
         "SUM(s.toi_sec) toi FROM player_game_stats s JOIN games g USING (game_id) JOIN players p USING (player_id) "
         "WHERE g.season_id=? AND g.game_type=? AND p.position<>'G'" + (" AND s.team_id=?" if team else "") +
         " GROUP BY s.player_id, s.team_id")
    return [dict(r) for r in conn.execute(q, (sid, split, team) if team else (sid, split))]


def _live_goalies(conn, sid, split, team=None):
    from ..game.history import goalie_decisions
    dec = goalie_decisions(conn, sid, split)
    q = ("SELECT s.player_id, s.team_id, COUNT(*) gp, SUM(s.toi_sec) toi, SUM(s.saves) sv, SUM(s.shots_against) sa "
         "FROM player_game_stats s JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE g.season_id=? "
         "AND g.game_type=? AND p.position='G'" + (" AND s.team_id=?" if team else "") + " GROUP BY s.player_id, s.team_id")
    out = []
    for r in conn.execute(q, (sid, split, team) if team else (sid, split)):
        d = dict(r)
        d["ga"] = (d["sa"] or 0) - (d["sv"] or 0)
        d.update({k: dec.get(d["player_id"], {}).get(k, 0) for k in ("gs", "w", "l", "otl", "so")})
        out.append(d)
    return out


def skater_rows(conn, year, league_id=None, team=None, split="RS"):
    """Per player per club: GP G A P PIM SOG SH% TOI/GP, with name, position, age."""
    league_id = league_id or _top(conn)
    sid, cur, live = _current(conn)
    if live and year == cur and league_id == _top(conn):
        raw = _live_skaters(conn, sid, split, team)
    else:
        q = ("SELECT player_id, team_id, gp, g, a, sog, toi_sec toi, pim FROM skater_season_stats WHERE season_start_year=? "
             "AND league_id=? AND split=?" + (" AND team_id=?" if team else ""))
        raw = [dict(r) for r in conn.execute(q, (year, league_id, split, team) if team else (year, league_id, split))]
    return _decorate(conn, raw, year, goalie=False)


def goalie_rows(conn, year, league_id=None, team=None, split="RS"):
    league_id = league_id or _top(conn)
    sid, cur, live = _current(conn)
    if live and year == cur and league_id == _top(conn):
        raw = _live_goalies(conn, sid, split, team)
    else:
        q = ("SELECT player_id, team_id, gp, gs, w, l, otl, so, ga, sa, toi_sec toi FROM goalie_season_stats WHERE "
             "season_start_year=? AND league_id=? AND split=?" + (" AND team_id=?" if team else ""))
        raw = [dict(r) for r in conn.execute(q, (year, league_id, split, team) if team else (year, league_id, split))]
    return _decorate(conn, raw, year, goalie=True)


def _decorate(conn, raw, year, goalie):
    tm = _teams(conn)
    if not raw:
        return []
    ids = list({r["player_id"] for r in raw})
    info = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for p in conn.execute(f"SELECT player_id, first_name, last_name, position, birth_date, nationality FROM players "
                              f"WHERE player_id IN ({','.join('?' * len(chunk))})", chunk):
            info[p[0]] = p
    me = user_team(conn)
    out = []
    for r in raw:
        p = info.get(r["player_id"])
        if p is None:
            continue
        t = tm.get(r["team_id"], {})
        d = dict(player_id=r["player_id"], name=f"{p[1]} {p[2]}", pos=p[3], age=_age(p[4], year), nat=p[5],
                 team_id=r["team_id"], team=t.get("abbr", ""), team_name=t.get("name", ""),
                 mine=r["team_id"] == me or t.get("parent") == me, gp=r["gp"] or 0)
        toi = r.get("toi") or 0
        if goalie:
            sa, ga = r.get("sa") or 0, r.get("ga") or 0
            d.update(gs=r.get("gs") or 0, w=r.get("w") or 0, l=r.get("l") or 0, otl=r.get("otl") or 0,
                     so=r.get("so") or 0, ga=ga, sa=sa, sv=sa - ga,
                     sv_pct=round((sa - ga) / sa, 3) if sa else None,
                     gaa=round(ga * 3600 / toi, 2) if toi else None, toi=round(toi / 60))
        else:
            g, a = r.get("g") or 0, r.get("a") or 0
            d.update(g=g, a=a, p=g + a, pim=r.get("pim") or 0, sog=r.get("sog") or 0,
                     sh_pct=round(100 * g / r["sog"], 1) if r.get("sog") else None,
                     ppg=round((g + a) / d["gp"], 2) if d["gp"] else 0,
                     toi_gp=round(toi / 60 / d["gp"], 1) if toi and d["gp"] else None)
        out.append(d)
    return out


def _combine(rows, goalie=False):
    """One line per player for league tables (players who changed club: totals, clubs joined with /)."""
    by = {}
    for r in rows:
        x = by.get(r["player_id"])
        if x is None:
            by[r["player_id"]] = dict(r)
            continue
        x["team"] = f"{x['team']}/{r['team']}"
        x["mine"] = x["mine"] or r["mine"]
        for k in (("gp", "gs", "w", "l", "otl", "so", "ga", "sa", "sv", "toi") if goalie else ("gp", "g", "a", "p", "pim", "sog")):
            x[k] = (x.get(k) or 0) + (r.get(k) or 0)
    out = list(by.values())
    for x in out:
        if goalie:
            x["sv_pct"] = round(x["sv"] / x["sa"], 3) if x.get("sa") else None
            x["gaa"] = round(x["ga"] * 60 / x["toi"], 2) if x.get("toi") else None
        else:
            x["sh_pct"] = round(100 * x["g"] / x["sog"], 1) if x.get("sog") else None
            x["ppg"] = round(x["p"] / x["gp"], 2) if x["gp"] else 0
    return out


LEADER_CATS = [("p", "Points", False), ("g", "Goals", False), ("a", "Assists", False), ("ppg", "Points a game", False),
               ("sog", "Shots", False), ("d_p", "Points by defencemen", False), ("rookie_p", "Rookie points", False),
               ("w", "Wins", True), ("sv_pct", "Save %", True), ("gaa", "Goals against average", True), ("so", "Shutouts", True)]


def hub(conn, year=None, league_id=None, split="RS"):
    league_id = int(league_id or _top(conn))
    ys = seasons(conn, league_id)
    year = int(year) if year else (ys[0] if ys else K.season_year(conn))
    sk = _combine(skater_rows(conn, year, league_id, split=split))
    gl = _combine(goalie_rows(conn, year, league_id, split=split), goalie=True)
    games = max([r["gp"] for r in sk] or [0])
    min_gp = max(1, int(games * 0.25))
    prior = {r[0] for r in conn.execute("SELECT player_id FROM skater_season_stats WHERE league_id=? AND split='RS' AND "
                                        "season_start_year<? AND gp>25", (league_id, year))}
    leaders = {}
    for key, label, goalie in LEADER_CATS:
        if goalie:
            pool = [x for x in gl if x["gp"] >= min_gp or key in ("w", "so")]
            if key == "gaa":
                pool = sorted([x for x in pool if x["gaa"] is not None], key=lambda x: x["gaa"])
            else:
                pool = sorted([x for x in pool if x.get(key) is not None], key=lambda x: -(x[key] or 0))
        elif key == "d_p":
            pool = sorted([x for x in sk if x["pos"] == "D"], key=lambda x: (-x["p"], -x["g"]))
        elif key == "rookie_p":
            pool = sorted([x for x in sk if x["player_id"] not in prior and (x["age"] or 99) <= 25], key=lambda x: (-x["p"], -x["g"]))
        elif key == "ppg":
            pool = sorted([x for x in sk if x["gp"] >= min_gp], key=lambda x: -x["ppg"])
        else:
            pool = sorted(sk, key=lambda x: (-(x[key] or 0), -x["p"]))
        stat = {"d_p": "p", "rookie_p": "p"}.get(key, key)
        leaders[key] = dict(label=label, stat=stat, rows=pool[:10])
    lg = _leagues(conn)
    return dict(season=year, seasons=ys, league_id=league_id, leagues=[v for v in lg.values() if seasons(conn, v["league_id"])],
                league=lg.get(league_id, {}).get("name"), split=split, leaders=leaders, skaters=sk, goalies=gl,
                min_gp=min_gp, live=_current(conn)[2] and year == _current(conn)[1] and league_id == _top(conn))


# ---------------------------------------------------------------- team pages

def team_page(conn, team_id, year=None):
    tm = _teams(conn)
    t = tm.get(team_id)
    if t is None:
        raise ValueError("No such team.")
    lg = _leagues(conn).get(t["league_id"], {})
    years = sorted({r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM skater_season_stats WHERE team_id=?",
                                               (team_id,))}, reverse=True)
    sid, cur, live = _current(conn)
    if t["league_id"] == _top(conn) and live and cur not in years and conn.execute(
            "SELECT 1 FROM games WHERE season_id=? AND played=1", (sid,)).fetchone():
        years.insert(0, cur)
    year = int(year) if year else (years[0] if years else K.season_year(conn))
    sk = sorted(skater_rows(conn, year, t["league_id"], team_id), key=lambda x: (-x["p"], -x["g"]))
    gl = sorted(goalie_rows(conn, year, t["league_id"], team_id), key=lambda x: -x["gp"])
    po_sk = sorted(skater_rows(conn, year, t["league_id"], team_id, "PO"), key=lambda x: (-x["p"], -x["g"]))
    from ..game.history import ensure_tables
    ensure_tables(conn)
    hist = [dict(r) for r in conn.execute("SELECT * FROM team_seasons WHERE team_id=? ORDER BY season_start_year DESC",
                                          (team_id,))]
    record = next((h for h in hist if h["season_start_year"] == year), None)
    if record is None and t["league_id"] == _top(conn) and year == cur:
        from ..league import standings as st
        from ..league.season import db_rules
        rec, _ = st.table(conn, sid)
        r = rec.get(team_id)
        if r:
            record = dict(gp=r["gp"], w=r["w"], l=r["l"], otl=r["otl"], pts=st.points(r, db_rules(conn)["points"]),
                          gf=r["gf"], ga=r["ga"], playoff_text="season in progress")
    # franchise leaders: every season this club has in the database
    lead = defaultdict(lambda: dict(gp=0, g=0, a=0))
    for r in conn.execute("SELECT player_id, gp, g, a FROM skater_season_stats WHERE team_id=? AND split='RS'", (team_id,)):
        x = lead[r[0]]
        x["gp"] += r[1] or 0
        x["g"] += r[2] or 0
        x["a"] += r[3] or 0
    if live and t["league_id"] == _top(conn):
        for r in _live_skaters(conn, sid, "RS", team_id):
            x = lead[r["player_id"]]
            x["gp"] += r["gp"] or 0
            x["g"] += r["g"] or 0
            x["a"] += r["a"] or 0
    names = {}
    ids = list(lead)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for p in conn.execute(f"SELECT player_id, first_name||' '||last_name FROM players WHERE player_id IN "
                              f"({','.join('?' * len(chunk))})", chunk):
            names[p[0]] = p[1]
    leaders = sorted(({"player_id": k, "name": names.get(k, "?"), **v, "p": v["g"] + v["a"]} for k, v in lead.items()),
                     key=lambda x: -x["p"])[:15]
    affil = [dict(team_id=x["team_id"], abbr=x["abbr"], name=x["name"], league=_leagues(conn).get(x["league_id"], {}).get("abbr"))
             for x in tm.values() if x["parent"] == team_id]
    parent = tm.get(t["parent"]) if t["parent"] else None
    staff = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        staff = [dict(r) for r in conn.execute("SELECT staff_id, name, role FROM staff WHERE team_id=? ORDER BY role", (team_id,))]
    return dict(team=t, league=lg, season=year, seasons=years, skaters=sk, goalies=gl, playoff_skaters=po_sk,
                record=record, history=hist, leaders=leaders, affiliates=affil,
                parent=dict(team_id=parent["team_id"], abbr=parent["abbr"], name=parent["name"]) if parent else None,
                staff=staff, mine=team_id == user_team(conn), awards=_awards_for(conn, team_id=team_id))


def _awards_for(conn, team_id=None, player_id=None):
    from ..game.history import AWARDS, ensure_tables
    ensure_tables(conn)
    q, a = "SELECT * FROM awards WHERE 1=1", []
    if team_id:
        q += " AND team_id=?"
        a.append(team_id)
    if player_id:
        q += " AND player_id=?"
        a.append(player_id)
    return [dict(season=r["season_start_year"], award=AWARDS.get(r["award"], (r["award"],))[0], key=r["award"],
                 player_id=r["player_id"], detail=r["detail"]) for r in conn.execute(q + " ORDER BY season_start_year DESC", a)]


# ---------------------------------------------------------------- league history

def history(conn):
    from ..game.history import AWARDS, ensure_tables
    ensure_tables(conn)
    tm = _teams(conn)
    top = _top(conn)
    champs = [dict(season=r[0], team_id=r[1], abbr=tm.get(r[1], {}).get("abbr"), name=tm.get(r[1], {}).get("name"),
                   pts=r[2]) for r in conn.execute("SELECT season_start_year, team_id, pts FROM team_seasons WHERE "
                                                   "playoff_round=5 ORDER BY season_start_year DESC")]
    awards = defaultdict(dict)
    for r in conn.execute("SELECT * FROM awards ORDER BY season_start_year DESC"):
        who = None
        if r["player_id"]:
            p = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (r["player_id"],)).fetchone()
            who = p[0] if p else "?"
        elif r["staff_id"]:
            s = conn.execute("SELECT name FROM staff WHERE staff_id=?", (r["staff_id"],)).fetchone()
            who = s[0] if s else "?"
        else:
            who = tm.get(r["team_id"], {}).get("name")
        awards[r["season_start_year"]][r["award"]] = dict(who=who, player_id=r["player_id"], team=tm.get(r["team_id"], {}).get("abbr"),
                                                          detail=r["detail"])
    alltime = []
    from ..game import career as CR                # v41: seasons on file plus careers before the save began
    for r in CR.alltime_skaters(conn, top, 50):
        p = conn.execute("SELECT first_name||' '||last_name, position, status FROM players WHERE player_id=?", (r["player_id"],)).fetchone()
        alltime.append(dict(player_id=r["player_id"], name=p[0] if p else "?", pos=p[1] if p else "", active=bool(p and p[2] != "retired"),
                            seasons=r["seasons"], gp=r["gp"], g=r["g"], a=r["a"], p=r["p"], prior=r["prior"]))
    games = []
    for r in CR.alltime_games(conn, top, 50):
        p = conn.execute("SELECT first_name||' '||last_name, position, status FROM players WHERE player_id=?", (r["player_id"],)).fetchone()
        games.append(dict(player_id=r["player_id"], name=p[0] if p else "?", pos=p[1] if p else "",
                          active=bool(p and p[2] != "retired"), gp=r["gp"], seasons=r["seasons"]))
    single = []
    for r in conn.execute("SELECT player_id, season_start_year, team_id, gp, g, a, g+a p FROM skater_season_stats WHERE "
                          "league_id=? AND split='RS' ORDER BY p DESC LIMIT 25", (top,)):
        p = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (r[0],)).fetchone()
        single.append(dict(player_id=r[0], name=p[0] if p else "?", season=r[1], team=tm.get(r[2], {}).get("abbr"),
                           team_id=r[2], gp=r[3], g=r[4], a=r[5], p=r[6]))
    first = conn.execute("SELECT MIN(season_start_year) FROM skater_season_stats WHERE league_id=?", (top,)).fetchone()[0]
    return dict(champions=champs, awards=[dict(season=y, **{k: v for k, v in a.items()}) for y, a in sorted(awards.items(), reverse=True)],
                award_names={k: v[0] for k, v in AWARDS.items()}, alltime=alltime, single=single, since=first,
                games=games, prior=bool(CR.all_prior(conn)))


# ---------------------------------------------------------------- player page extras

def player_extras(conn, pid):
    tm = _teams(conn)
    lg = _leagues(conn)
    p = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
    goalie = p and p[0] == "G"
    rows = []
    tbl = "goalie_season_stats" if goalie else "skater_season_stats"
    for r in conn.execute(f"SELECT * FROM {tbl} WHERE player_id=? ORDER BY season_start_year, split DESC", (pid,)):
        d = dict(r)
        t = tm.get(d["team_id"], {})
        # v42: history imported from the database keeps the names of clubs and leagues the world does not have
        row = dict(season=d["season_start_year"], split=d["split"], team_id=d["team_id"],
                   team=t.get("name") or d.get("club_name") or "?", abbr=t.get("abbr") or d.get("club_name") or "",
                   league=lg.get(d["league_id"], {}).get("abbr") or d.get("league_name") or "", league_id=d["league_id"],
                   gp=d["gp"] or 0)
        if goalie:
            sa, ga = d.get("sa") or 0, d.get("ga") or 0
            row.update(w=d.get("w"), l=d.get("l"), otl=d.get("otl"), so=d.get("so"), ga=ga, sa=sa,
                       sv_pct=round((sa - ga) / sa, 3) if sa else None,
                       gaa=round(ga * 3600 / d["toi_sec"], 2) if d.get("toi_sec") else None)
        else:
            row.update(g=d["g"] or 0, a=d["a"] or 0, p=(d["g"] or 0) + (d["a"] or 0), pim=d.get("pim"), sog=d.get("sog"),
                       pm=d.get("plus_minus"))
        rows.append(row)
    sid, cur, live = _current(conn)
    if live:
        for split in ("RS", "PO"):
            live_rows = (_live_goalies if goalie else _live_skaters)(conn, sid, split)
            for r in [x for x in live_rows if x["player_id"] == pid]:
                t = tm.get(r["team_id"], {})
                row = dict(season=cur, split=split, team_id=r["team_id"], team=t.get("name", "?"), abbr=t.get("abbr", ""),
                           league=lg.get(_top(conn), {}).get("abbr", ""), league_id=_top(conn), gp=r["gp"], live=True)
                if goalie:
                    row.update(w=r["w"], l=r["l"], otl=r["otl"], so=r["so"], ga=r["ga"], sa=r["sa"],
                               sv_pct=round(r["sv"] / r["sa"], 3) if r["sa"] else None,
                               gaa=round(r["ga"] * 3600 / r["toi"], 2) if r["toi"] else None)
                else:
                    row.update(g=r["g"] or 0, a=r["a"] or 0, p=(r["g"] or 0) + (r["a"] or 0), sog=r["sog"])
                rows.append(row)
    totals = defaultdict(lambda: defaultdict(float))
    for r in rows:
        k = (r["league"], r["split"])
        for f in (("gp", "w", "l", "otl", "so", "ga", "sa") if goalie else ("gp", "g", "a", "p", "pim", "sog")):
            totals[k][f] += r.get(f) or 0
        totals[k]["seasons"] += 1
    tot = []
    for (league, split), v in totals.items():
        d = dict(league=league, split=split, **{k: int(x) for k, x in v.items()})
        if goalie:
            d["sv_pct"] = round((d["sa"] - d["ga"]) / d["sa"], 3) if d.get("sa") else None
        tot.append(d)
    log = []
    q = ("SELECT g.game_id, g.game_date, g.home_team_id, g.away_team_id, g.home_goals, g.away_goals, g.went_to_ot, "
         "g.game_type, s.team_id, s.goals, s.assists, s.shots, s.toi_sec, s.saves, s.shots_against FROM player_game_stats s "
         "JOIN games g USING (game_id) WHERE s.player_id=? ORDER BY g.game_date DESC, g.game_id DESC LIMIT 12")
    for r in conn.execute(q, (pid,)):
        home = r["team_id"] == r["home_team_id"]
        gf, ga = (r["home_goals"], r["away_goals"]) if home else (r["away_goals"], r["home_goals"])
        log.append(dict(game_id=r["game_id"], date=r["game_date"], opp=tm.get(r["away_team_id"] if home else r["home_team_id"], {}).get("abbr"),
                        home=home, result=("W" if gf > ga else "OTL" if r["went_to_ot"] else "L") + f" {gf}-{ga}",
                        g=r["goals"], a=r["assists"], sog=r["shots"], toi=round((r["toi_sec"] or 0) / 60, 1),
                        sv=r["saves"], sa=r["shots_against"], playoff=r["game_type"] == "PO"))
    # where he ranks among his position in the league (value and this season's production)
    pct = {}
    try:
        from ..game import roster as R
        vals = K.league_values(conn)
        me_v = vals.value(pid)
        grp = "G" if goalie else ("D" if p[0] == "D" else "F")
        same = [vals.value(x[0]) for x in conn.execute("SELECT player_id, position FROM players WHERE team_id IS NOT NULL AND "
                                                         "status IN ('active','injured')") if R.group(x[1]) == grp]
        pct["value"] = round(100 * sum(1 for v in same if v < me_v) / max(1, len(same)))
    except Exception:
        pass
    attrs = []
    keys = (["goalie_positioning", "reflexes", "glove", "blocker", "low_shot_save", "rebound_control"] if goalie else
            ["offensive_awareness", "passing", "puck_control", "shot_accuracy", "positioning", "defensive_awareness",
             "stick_checking", "hitting"])
    for r in conn.execute(f"SELECT season_start_year, {', '.join(keys)}, potential FROM attribute_history WHERE player_id=? "
                          "ORDER BY season_start_year", (pid,)):
        attrs.append(dict(season=r[0], **{k: r[i + 1] for i, k in enumerate(keys)}, potential=r[len(keys) + 1]))
    return dict(career=rows, totals=tot, log=log, percentile=pct, attr_history=attrs, attr_keys=keys,
                awards=_awards_for(conn, player_id=pid), goalie=goalie)
