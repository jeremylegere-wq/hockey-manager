"""Read model for the UI: plain dicts built from the game database with the same functions the CLI uses.

Nothing here changes game state or computes hockey outcomes; actions go through hs.game.cli (see server.py), so the
UI and the CLI always share validation and rules.
"""
from __future__ import annotations

import datetime
import json

from ..game import contracts as K
from ..game import events as E
from ..game import roster as R
from ..game.state import get_state, user_team
from ..league import standings as st
from ..league.season import db_rules, team_rows
from ..schema import top_league_sql

SK_KEYS = [("Offence", ["offensive_awareness", "shot_accuracy", "shot_power", "passing", "puck_control", "net_presence",
                        "faceoffs"]),
           ("Defence", ["positioning", "defensive_awareness", "checking", "stick_checking", "shot_blocking"]),
           ("Skating & physical", ["speed", "acceleration", "agility", "balance", "endurance", "strength", "hitting",
                                   "toughness"]),
           ("Mental", ["composure", "leadership", "teamwork", "determination", "professionalism", "mental_toughness",
                       "aggression", "bravery"])]
G_KEYS = [("Goaltending", ["goalie_positioning", "reflexes", "glove", "blocker", "low_shot_save", "rebound_control",
                           "recovery", "poke_check"]),
          ("Other", ["goalie_puck_handling", "goalie_passing", "goalie_skating", "goalie_stamina"])]
# v38: the native ratings, as the player screens show them
NATIVE_LABEL = {"one_on_ones": "One on Ones", "pass_tendency": "Pass Tendency", "important_matches": "Important Matches",
                "work_rate": "Work Rate", "injury_proneness": "Injury Proneness", "natural_fitness": "Natural Fitness",
                "pokecheck": "Pokecheck", "faceoffs": "Faceoffs", "slapshot": "Slapshot", "wristshot": "Wristshot"}
SK_NATIVE = [("Technical", ["agitation", "checking", "deflections", "deking", "faceoffs", "movement", "passing", "pass_tendency",
                            "pokecheck", "positioning", "slapshot", "stickhandling", "versatility", "wristshot"]),
             ("Mental", ["aggression", "anticipation", "bravery", "consistency", "decisions", "dirtiness", "flair",
                         "important_matches", "leadership", "teamwork", "creativity", "work_rate"]),
             ("Physical", ["acceleration", "agility", "balance", "fighting", "hitting", "injury_proneness", "natural_fitness",
                           "pace", "stamina", "strength"])]
G_NATIVE = [("Goalkeeping", ["blocker", "glove", "rebounds", "recovery", "reflexes", "one_on_ones", "positioning", "pokecheck",
                             "stickhandling", "passing"]),
            ("Mental", ["anticipation", "bravery", "consistency", "decisions", "important_matches", "leadership", "teamwork",
                        "work_rate", "aggression", "flair"]),
            ("Physical", ["acceleration", "agility", "balance", "injury_proneness", "natural_fitness", "pace", "stamina", "strength"])]


def native_groups(conn, pid, pos):
    from ..game import ratings as RT
    r = RT.of(conn, pid)
    if r is None:
        return None, None
    groups = [dict(title=t, items=[dict(key=k, label=NATIVE_LABEL.get(k, k.replace("_", " ").title()), value=r[k])
                                   for k in keys if r.get(k) is not None])
              for t, keys in (G_NATIVE if pos == "G" else SK_NATIVE)]
    extra = dict(current_ability=r["current_ability"], potential_ability=r["potential_ability"],
                 positions={k[4:].upper(): r[k] for k in ("pos_g", "pos_ld", "pos_rd", "pos_lw", "pos_c", "pos_rw")},
                 roles=dict(offensive=r["role_off"], defensive=r["role_def"]))
    return groups, extra


LIST_KEYS = {"F": ["offensive_awareness", "passing", "puck_control", "shot_accuracy", "positioning",
                   "defensive_awareness", "hitting", "speed"],
             "D": ["offensive_awareness", "passing", "puck_control", "shot_accuracy", "positioning",
                   "defensive_awareness", "hitting", "speed"],
             "G": ["goalie_positioning", "reflexes", "glove", "blocker", "low_shot_save", "rebound_control"]}


def _has(conn, table):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone())


def _age(birth, on):
    b = datetime.date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def _today(conn):
    s = get_state(conn)
    return datetime.date.fromisoformat(s[0]) if s else datetime.date.today()


def season_id(conn):
    return conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]


def teams_map(conn):
    return {r["team_id"]: dict(r) for r in conn.execute("SELECT team_id, name, nickname, abbr, league_id FROM teams")}


def _unread(conn):
    """v39 (#2): unread mail, not counting archived messages (what the Inbox folder shows)."""
    from ..game.state import _inbox_columns
    _inbox_columns(conn)
    return conn.execute("SELECT COUNT(*) FROM inbox WHERE read=0 AND COALESCE(archived, 0)=0").fetchone()[0]


def state(conn):
    me = user_team(conn)
    if me is None:
        from ..game import gm as GMx
        if get_state(conn) and GMx.unemployed(conn):        # out of work: the world goes on, the Job Centre is open
            s = GMx.settings(conn)
            return dict(started=True, unemployed=True, team_id=None, team="Out of work", abbr="", date=get_state(conn)[0],
                        phase=K.season_state(conn), season=K.season_year(conn), record=None, unread=conn.execute(
                            "SELECT COUNT(*) FROM inbox WHERE read=0").fetchone()[0], fired=True, strip=None,
                        reputation=s["reputation"], jobs=len(__import__("hs.game.org", fromlist=["x"]).vacancies(conn)),
                        badges=dict(offers=0, press=0, meetings=0), cap=None)
        return dict(started=False)
    tm = teams_map(conn)[me]
    rec, _ = st.table(conn, season_id(conn))
    r = rec.get(me)
    pts = st.points(r, db_rules(conn)["points"]) if r else 0
    fired = conn.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone()
    out = dict(started=True, team_id=me, team=f"{tm['name']} {tm['nickname'] or ''}".strip(), abbr=tm["abbr"],
               date=get_state(conn)[0], phase=K.season_state(conn), season=K.season_year(conn),
               record=dict(w=r["w"], l=r["l"], otl=r["otl"], t=r.get("t", 0), pts=pts, gp=r["gp"]) if r else None,
               unread=_unread(conn), fired=bool(fired))
    from ..game import trades as TR
    out["trade_deadline"] = TR.deadline(conn).isoformat()
    from ..game import editor as _ED                       # v49: the UI offers commissioner-only edits
    out["commissioner"] = _ED.enabled(conn)
    # badges for the tabs: things waiting for you
    out["badges"] = dict(
        offers=conn.execute("SELECT COUNT(*) FROM trade_offers WHERE status='open' AND expires>=?", (out["date"],)).fetchone()[0]
        if _has(conn, "trade_offers") else 0,
        press=conn.execute("SELECT COUNT(*) FROM press_events WHERE team_id=? AND status='pending' AND expires>=?", (me, out["date"])).fetchone()[0]
        if _has(conn, "press_events") else 0,
        meetings=conn.execute("SELECT COUNT(*) FROM inbox WHERE read=0 AND (subject LIKE 'Meeting request%' OR subject LIKE 'URGENT%' OR subject LIKE 'A directive%')").fetchone()[0])
    try:
        from . import screens
        out["strip"] = screens.strip(conn)
    except Exception:                       # decoration: never break the header
        out["strip"] = None
    yr = K.signing_year(conn)
    out["cap"] = dict(season=yr, payroll=K.payroll(conn, me, yr), room=K.cap_room(conn, me, yr),
                      ceiling=K.crules(conn)["cap_ceiling"])
    if _has(conn, "board"):
        b = conn.execute("SELECT confidence, warnings FROM board WHERE team_id=?", (me,)).fetchone()
        from ..game.org import label
        out["board"] = dict(confidence=round(b["confidence"]), label=label(b["confidence"]), warning=bool(b["warnings"]))
        if _has(conn, "ultimatums"):
            from ..game import boardroom as BR
            u = BR.open_ultimatum(conn, me)
            if u:
                gp, pts = BR._record(conn, me, season_id(conn))
                out["board"]["ultimatum"] = dict(need=u["points_needed"] - (pts - u["pts_at_issue"]),
                                                 games=u["games"] - (gp - u["gp_at_issue"]))
    return out


def dashboard(conn):
    me = user_team(conn)
    out = dict(state=state(conn))
    if _has(conn, "owners"):
        o = conn.execute("SELECT * FROM owners WHERE team_id=?", (me,)).fetchone()
        out["owner"] = dict(o)
        out["objectives"] = [dict(r) for r in conn.execute(
            "SELECT category, description, importance, status, result FROM objectives WHERE team_id=? AND "
            "status='active' ORDER BY objective_id", (me,))]
    if _has(conn, "team_room"):
        rm = conn.execute("SELECT * FROM team_room WHERE team_id=?", (me,)).fetchone()
        if rm:
            out["room"] = dict(cohesion=round(rm["cohesion"]), atmosphere=rm["atmosphere"],
                               leadership=round(rm["leadership_strength"], 1), reasons=json.loads(rm["reasons"] or "[]"))
        out["leaders"] = [dict(role=r["role"], player_id=r["player_id"], name=E.player_name(conn, r["player_id"]))
                          for r in conn.execute("SELECT * FROM leadership WHERE team_id=? ORDER BY role DESC", (me,))]
    attention = []
    if _has(conn, "concerns"):
        for c in conn.execute("SELECT * FROM concerns WHERE team_id=? AND status='open' ORDER BY raised_on", (me,)):
            attention.append(dict(kind="meeting", player_id=c["player_id"], text=f"{E.player_name(conn, c['player_id'])} "
                                  f"{c['detail']}", since=c["raised_on"]))
        for p in conn.execute("SELECT * FROM promises WHERE team_id=? AND status='active' ORDER BY deadline", (me,)):
            attention.append(dict(kind="promise", player_id=p["player_id"], text=f"Promise to "
                                  f"{E.player_name(conn, p['player_id'])}: {p['description']}", since=p["made_on"]))
    out["attention"] = attention
    out["news"] = [dict(date=e["event_date"], type=e["event_type"], text=e["summary"], player_id=e["player_id"],
                        importance=e["importance"]) for e in E.recent(conn, team_id=me, limit=10)]
    out["league_news"] = [dict(date=e["event_date"], type=e["event_type"], text=e["summary"], player_id=e["player_id"])
                          for e in _league_feed(conn, 8)]
    tm = teams_map(conn)
    out["next_games"] = [dict(date=g["game_date"], home=g["home_team_id"] == me,
                              opponent=tm[g["away_team_id"] if g["home_team_id"] == me else g["home_team_id"]]["abbr"])
                         for g in conn.execute("SELECT game_date, home_team_id, away_team_id FROM games WHERE played=0 AND "
                                               "game_type='RS' AND (home_team_id=? OR away_team_id=?) ORDER BY game_date "
                                               "LIMIT 3", (me, me))]
    out["recent_results"] = results(conn, me, 5)
    out["standings"] = standings(conn, "division", only_mine=True)
    return out


def results(conn, team, n=10):
    tm = teams_map(conn)
    out = []
    for g in conn.execute("SELECT * FROM games WHERE played=1 AND (home_team_id=? OR away_team_id=?) ORDER BY game_date "
                          "DESC, game_id DESC LIMIT ?", (team, team, n)):
        home = g["home_team_id"] == team
        gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
        out.append(dict(game_id=g["game_id"], date=g["game_date"], opponent=tm[g["away_team_id"] if home else g["home_team_id"]]["abbr"],
                        home=home, gf=gf, ga=ga, result="T" if gf == ga else "W" if gf > ga else ("OTL" if g["went_to_ot"] else "L"),
                        ot={0: "", 1: "OT", 2: "SO"}.get(g["went_to_ot"], ""), playoff=g["game_type"] == "PO"))
    return out


def standings(conn, mode="division", only_mine=False):
    rules = db_rules(conn)
    rec, h2h = st.table(conn, season_id(conn))
    info = {t["team_id"]: t for t in team_rows(conn)}
    order = st.rank(rec, h2h, rules) if rec else sorted(info)
    me = user_team(conn)
    groups = {}
    for t in order:
        i = info[t]
        key = {"division": f"{i['conference']} - {i['division']}", "conference": i["conference"],
               "league": "League"}[mode]
        r = rec.get(t, dict(gp=0, w=0, l=0, otl=0, gf=0, ga=0, rw=0))
        groups.setdefault(key, []).append(dict(team_id=t, abbr=i["abbr"], name=i["name"], gp=r["gp"], w=r["w"], l=r["l"],
                                               otl=r["otl"], t=r.get("t", 0), pts=st.points(r, rules["points"]) if r["gp"] else 0,
                                               gf=r["gf"], ga=r["ga"], mine=t == me))
    if only_mine:
        return {k: v for k, v in groups.items() if any(x["mine"] for x in v)}
    return groups


def _contract_dict(conn, pid, year):
    c = K.current_contract(conn, pid, year) or K.last_contract(conn, pid)
    if c is None:
        return None
    end = c["start_year"] + c["years"] - 1
    return dict(cap_hit=c["cap_hit"], start=c["start_year"], years=c["years"], ends=end, type=c["contract_type"],
                no_trade=bool(c["no_trade"]), expiring=end == year,
                status_at_expiry=K.rights_status(conn, pid, end) if end == year else None)


def roster(conn, include_system=False):
    me = user_team(conn)
    on = _today(conn)
    year = K.season_year(conn)
    statuses = "('active','injured','ltir','prospect')" if include_system else "('active','injured','ltir')"
    rows = conn.execute(f"SELECT p.*, a.* FROM players p LEFT JOIN player_attributes a USING (player_id) WHERE "
                        f"p.team_id=? AND p.status IN {statuses} ORDER BY p.position, p.last_name", (me,)).fetchall()
    morale = {r["player_id"]: dict(r) for r in conn.execute("SELECT * FROM morale")} if _has(conn, "morale") else {}
    leaders = {r[0]: r[1] for r in conn.execute("SELECT player_id, role FROM leadership WHERE team_id=?", (me,))} \
        if _has(conn, "leadership") else {}
    stats = {r["player_id"]: dict(r) for r in conn.execute(
        "SELECT s.player_id, COUNT(*) gp, SUM(goals) g, SUM(assists) a, AVG(toi_sec) toi, SUM(saves) sv, "
        "SUM(shots_against) sa FROM player_game_stats s JOIN games g USING (game_id) WHERE g.season_id=? AND "
        "g.game_type='RS' AND s.team_id=? GROUP BY s.player_id", (season_id(conn), me))}
    from ..game.world import where_is
    from ..game import waivers as W
    from ..game import ltir as LT
    period = W.in_period(conn)
    out = {"F": [], "D": [], "G": []}
    for r in rows:
        g = R.group(r["position"])
        s = stats.get(r["player_id"], {})
        m = morale.get(r["player_id"])
        out[g].append(dict(
            player_id=r["player_id"], name=f"{r['first_name']} {r['last_name']}", pos=r["position"], num=r["jersey_number"],
            age=_age(r["birth_date"], on), status=r["status"], value=round(R.player_value(conn, r["player_id"])),
            ratings={k: r[k] for k in LIST_KEYS[g]}, contract=_contract_dict(conn, r["player_id"], year),
            morale=round(m["morale"]) if m else None, leader=leaders.get(r["player_id"]),
            club=where_is(conn, r["player_id"]) if r["status"] == "prospect" else None,
            gp=s.get("gp", 0), g=s.get("g", 0), a=s.get("a", 0), toi=round((s.get("toi") or 0) / 60, 1),
            sv_pct=round(s["sv"] / s["sa"], 3) if s.get("sa") else None,
            waivers=W.status(conn, r["player_id"])["why"],
            ltir_ok=r["status"] == "injured" and LT.eligible(conn, r["player_id"])[0],
            needs_waivers=period and r["status"] == "active" and W.needs_waivers(conn, r["player_id"],
                                                                                 get_state(conn)[0])))
    wire = []
    claims = {x[0] for x in conn.execute("SELECT player_id FROM waiver_claims WHERE team_id=?", (me,))} \
        if _has(conn, "waiver_claims") else set()
    for w in W.on_wire(conn):
        p = conn.execute("SELECT first_name||' '||last_name n, position, birth_date FROM players WHERE player_id=?",
                         (w["player_id"],)).fetchone()
        c = K.current_contract(conn, w["player_id"], year)
        order = W.claim_order(conn, w["team_id"])
        wire.append(dict(player_id=w["player_id"], name=p["n"], pos=p["position"], age=_age(p["birth_date"], on),
                         team=E.team_abbr(conn, w["team_id"]), mine=w["team_id"] == me, clears=w["clears"],
                         cap=c["cap_hit"] if c else None, value=round(R.player_value(conn, w["player_id"])),
                         priority=(order.index(me) + 1) if me in order else None, of=len(order),
                         claimed=w["player_id"] in claims))
    cap = K.crules(conn)["cap_ceiling"]
    ltir = dict(players=[dict(player_id=x["player_id"], name=E.player_name(conn, x["player_id"]), cap_hit=x["cap_hit"],
                              earliest=x["earliest"]) for x in LT.active(conn, me)],
                ceiling=LT.ceiling(conn, me), cap=cap, payroll=K.payroll(conn, me))
    return dict(groups=out, columns=LIST_KEYS, wire=wire, waiver_period=period, ltir=ltir)


def player(conn, pid):
    from ..game.world import where_is
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None:
        raise KeyError("no such player")
    a = conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone()
    me = user_team(conn)
    tm = teams_map(conn)
    year = K.season_year(conn)
    on = _today(conn)
    groups = []
    if a is not None:
        for title, keys in (G_KEYS if p["position"] == "G" else SK_KEYS):
            groups.append(dict(title=title, items=[dict(key=k, label=k.replace("_", " ").replace("goalie ", "").title(),
                                                        value=a[k]) for k in keys if a[k] is not None]))
    engine_groups = groups
    nat, extra = native_groups(conn, pid, p["position"])
    if nat:
        groups = nat
    stats = []
    tbl = "goalie_season_stats" if p["position"] == "G" else "skater_season_stats"
    cols = "gp, toi_sec, ga, sa" if p["position"] == "G" else "gp, g, a, pim, sog, toi_sec"
    for r in conn.execute(f"SELECT s.season_start_year season, COALESCE(l.abbr, s.league_name, '') league, "
                          f"COALESCE(t.abbr, s.club_name, '') team, "
                          f"{cols} FROM {tbl} s LEFT JOIN leagues l USING (league_id) LEFT JOIN teams t ON "
                          f"t.team_id=s.team_id WHERE s.player_id=? AND s.split='RS' ORDER BY s.season_start_year", (pid,)):
        d = dict(r)
        if p["position"] == "G" and d.get("sa"):
            d["sv_pct"] = round(1 - (d["ga"] or 0) / d["sa"], 3)
        if p["position"] != "G":
            d["pts"] = (d.get("g") or 0) + (d.get("a") or 0)
        stats.append(d)
    contracts = [dict(r) for r in conn.execute("SELECT start_year, years, cap_hit, contract_type, team_id FROM contracts "
                                               "WHERE player_id=? ORDER BY start_year", (pid,))]
    for c in contracts:
        c["team"] = tm.get(c["team_id"], {}).get("abbr", "")
    out = dict(player_id=pid, name=f"{p['first_name']} {p['last_name']}", position=p["position"], shoots=p["shoots"],
               jersey_number=p["jersey_number"] if "jersey_number" in p.keys() else None,
               suspended=__import__("hs.game.discipline", fromlist=["x"]).games_left(conn, pid),
               age=_age(p["birth_date"], on), birth_date=p["birth_date"], height_cm=p["height_cm"],
               weight_kg=p["weight_kg"], nationality=p["nationality"], status=p["status"],
               team=tm.get(p["team_id"], {}).get("abbr") if p["team_id"] else None, club=where_is(conn, pid),
               mine=p["team_id"] == me, value=round(R.player_value(conn, pid)), attributes=groups, stats=stats,
               contract=_contract_dict(conn, pid, year) if p["team_id"] else None, contracts=contracts,
               events=[dict(date=e["event_date"], text=e["summary"]) for e in E.recent(conn, player_id=pid, limit=15)])
    out["engine_attributes"] = engine_groups
    cc = K.current_contract(conn, pid, year) or K.last_contract(conn, pid)      # v41: what the deal pays each season
    if cc is not None:
        from ..game import ledger as LG
        out["pay"] = LG.years_of(conn, cc["contract_id"])
        out["pay_structure"] = LG.structure_of(conn, cc["contract_id"])
    from ..game import career as CR                                           # v41: NHL career before the save
    out["career_prior"] = CR.prior(conn, pid)
    if extra:                                         # v38: ability as stars; potential only your own staff can judge
        mine = p["team_id"] == me
        out["ability"] = dict(current=round(extra["current_ability"] / 40, 1),
                              potential=round(extra["potential_ability"] / 40, 1) if mine else None,
                              positions=extra["positions"], roles=extra["roles"])
    out["team_id"], out["club_id"] = p["team_id"], p["club_id"]
    out["club_name"] = tm.get(p["club_id"], {}).get("name") if p["club_id"] else None
    out["team_name"] = f"{tm[p['team_id']]['name']} {tm[p['team_id']]['nickname'] or ''}".strip() if p["team_id"] in tm else None
    if _has(conn, "leadership"):
        ld = conn.execute("SELECT role FROM leadership WHERE player_id=?", (pid,)).fetchone()
        out["leader"] = ld[0] if ld else None
    inj = conn.execute("SELECT * FROM injuries WHERE player_id=? ORDER BY rowid DESC LIMIT 1", (pid,)).fetchone() \
        if p["status"] in ("injured", "ltir") else None
    if inj:
        out["injury"] = {k: inj[k] for k in inj.keys() if k in ("description", "start_date", "expected_return")}
    rights = conn.execute("SELECT * FROM draft_rights WHERE player_id=?", (pid,)).fetchone() \
        if _has(conn, "draft_rights") else None
    if rights:
        out["rights"] = dict(team=tm.get(rights["team_id"], {}).get("abbr"), draft_year=rights["draft_year"],
                             pick=rights["overall_pick"], expires=rights["expires_year"])
    dev = conn.execute("SELECT potential FROM player_dev WHERE player_id=?", (pid,)).fetchone() \
        if _has(conn, "player_dev") else None
    if dev and dev[0] is not None and out["age"] <= 24:
        from ..game import draft as D
        from ..game.cli import CLI
        out["projection"] = CLI._grade(D.perceived(conn, me, pid, dev[0], 0), p["position"] == "G")
    out["valuation"] = _valuation(conn, pid)
    if p["team_id"] == me and _has(conn, "morale"):
        m = conn.execute("SELECT * FROM morale WHERE player_id=?", (pid,)).fetchone()
        s = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone()
        if m:
            out["morale"] = {k: round(m[k]) for k in ("morale", "role", "team", "contract", "trust_mgmt", "trust_coach")}
            out["morale"]["trade_request"] = bool(m["trade_request"])
        if s:
            out["personality"] = {k: s[k] for k in s.keys() if k != "player_id"}
        c = conn.execute("SELECT * FROM concerns WHERE player_id=? AND status='open'", (pid,)).fetchone()
        if c:
            from ..game.people import promise_terms
            out["concern"] = dict(topic=c["topic"], detail=c["detail"], since=c["raised_on"],
                                  promise=promise_terms(conn, pid, c["topic"], get_state(conn)[0])[1])
    return out


def contracts_view(conn):
    me = user_team(conn)
    year = K.season_year(conn)
    nxt = K.signing_year(conn)
    total, lines = K.payroll(conn, me, nxt, detail=True)
    cr = K.crules(conn)
    rows = []
    on = _today(conn)
    for r in conn.execute("SELECT player_id, first_name||' '||last_name n, position, status, birth_date FROM players "
                          "WHERE team_id=? ORDER BY position, last_name", (me,)):
        c = _contract_dict(conn, r["player_id"], year)
        ev = _valuation(conn, r["player_id"]) if c else None
        rows.append(dict(player_id=r["player_id"], name=r["n"], pos=r["position"], status=r["status"],
                         grade=ev and ev["grade"], surplus=ev and ev["surplus"],
                         age=_age(r["birth_date"], on), value=round(R.player_value(conn, r["player_id"])), contract=c,
                         asking=K.asking(conn, r["player_id"], c["status_at_expiry"]) if c and c["expiring"] else None))
    dead = [dict(kind=k, player=E.player_name(conn, p) if p else "", amount=a) for k, p, a in lines if k != "player"]
    future = []
    for y in range(year, year + 5):
        future.append(dict(season=y, payroll=K.payroll(conn, me, y),
                           committed=conn.execute("SELECT COUNT(*) FROM contracts c JOIN players p USING (player_id) "
                                                  "WHERE p.team_id=? AND c.start_year<=? AND c.start_year+c.years>?",
                                                  (me, y, y)).fetchone()[0]))
    # v38 (#10, #21): every contract year by year, for the cap grid and its chart
    seasons = list(range(year, year + 5))
    grid = []
    for r in conn.execute("SELECT c.player_id, c.start_year, c.years, c.cap_hit, c.contract_type, p.first_name||' '||p.last_name n, p.position, "
                          "p.status FROM contracts c JOIN players p USING (player_id) WHERE p.team_id=? AND c.start_year+c.years>?", (me, year)):
        cells = [r["cap_hit"] if r["start_year"] <= y < r["start_year"] + r["years"] else None for y in seasons]
        if any(cells):
            grid.append(dict(player_id=r["player_id"], name=r["n"], pos=r["position"], status=r["status"], type=r["contract_type"], cells=cells,
                             ends=r["start_year"] + r["years"] - 1))
    grid.sort(key=lambda x: ({"G": 2, "D": 1}.get(x["pos"], 0), -(x["cells"][0] or 0)))
    from ..game import ledger as LG                   # v41: cash by season (salary + signing bonus)
    cg = LG.grid(conn, me, seasons)
    for g in grid:
        yrs = cg.get(g["player_id"], {})
        g["cash"] = [(yrs[y]["salary"] + yrs[y]["bonus"]) if y in yrs and g["cells"][i] else None for i, y in enumerate(seasons)]
        g["bonus"] = [yrs[y]["bonus"] if y in yrs and g["cells"][i] else None for i, y in enumerate(seasons)]
    return dict(season=nxt, payroll=total, ceiling=cr["cap_ceiling"], floor=cr["cap_floor"],
                room=None if cr["cap_ceiling"] is None else cr["cap_ceiling"] - total, players=rows, other_charges=dead,
                outlook=future, contracts=K.contract_count(conn, me, nxt), max_contracts=cr.get("max_contracts"),
                grid=grid, grid_seasons=seasons, cash_by_season=[LG.cash(conn, me, y) for y in seasons], dead_by_season=[sum(a for k, p_, a in K.payroll(conn, me, y, detail=True)[1] if k != "player")
                                                                 for y in seasons])


def offseason_view(conn):
    from ..game import offseason as O
    me = user_team(conn)
    phase = K.season_state(conn)
    out = dict(phase=phase, phases=O.ORDER, date=get_state(conn)[0])
    out["rights"] = []
    for r in O.rights_rows(conn, me):
        d = dict(r)
        d["name"] = E.player_name(conn, r["player_id"])
        d["asking"] = K.asking(conn, r["player_id"], r["status"])
        out["rights"].append(d)
    if _has(conn, "draft_picks"):
        from ..game import draft as D
        year = D.draft_year(conn)
        tm = teams_map(conn)
        picks = conn.execute("SELECT * FROM draft_picks WHERE draft_year=? ORDER BY overall", (year,)).fetchall()
        out["draft"] = dict(year=year, picks=[dict(overall=p["overall"], round=p["round"], team=tm[p["team_id"]]["abbr"],
                                                   mine=p["team_id"] == me, note=p["lottery_note"],
                                                   player=E.player_name(conn, p["player_id"]) if p["player_id"] else None,
                                                   player_id=p["player_id"]) for p in picks])
        nxt = next((p for p in picks if p["player_id"] is None), None)
        out["draft"]["on_clock"] = bool(nxt and nxt["team_id"] == me)
        if phase == "draft":
            out["draft"]["board"] = _board(conn, me, 40)
    if _has(conn, "offer_sheets"):
        from ..game import offer_sheets as OS
        out["offer_sheets"] = [dict(player_id=x["player_id"], name=E.player_name(conn, x["player_id"]),
                                    by=teams_map(conn)[x["from_team"]]["abbr"], owner=teams_map(conn)[x["owner_team"]]["abbr"],
                                    aav=x["aav"], years=x["years"], comp=OS.describe(json.loads(x["comp"])),
                                    status=x["status"], note=x["note"], mine=x["owner_team"] == me)
                               for x in OS.sheets(conn)]
    if phase == "rights":
        from ..game import free_agency as FA
        out["upcoming"] = [dict(player_id=x["pid"], name=E.player_name(conn, x["pid"]), pos=x["pos"], age=x["age"],
                                tier=x["tier"], team=teams_map(conn)[x["team_id"]]["abbr"], years=x["years"],
                                ask=x["peak_ask"], fair=x["fair"]) for x in FA.upcoming(conn)[:60]]
    if phase in ("free_agency", "arbitration", "awards", "preseason", "finished", "rights", "regular_season"):
        fas = []
        values = K.league_values(conn)
        for v, pid, pos in R.free_agents(conn)[:60]:
            p = conn.execute("SELECT first_name||' '||last_name n, birth_date FROM players WHERE player_id=?",
                             (pid,)).fetchone()
            fas.append(dict(player_id=pid, name=p["n"], pos=pos, age=_age(p["birth_date"], _today(conn)), value=round(v),
                            asking=K.asking(conn, pid, "UFA", values)))
        out["free_agents"] = fas
    out["prospects"] = []
    if _has(conn, "draft_rights"):
        from ..game.world import where_is
        for r in conn.execute("SELECT d.*, p.first_name||' '||p.last_name n, p.position, p.birth_date FROM draft_rights d "
                              "JOIN players p USING (player_id) WHERE d.team_id=? ORDER BY d.overall_pick", (me,)):
            out["prospects"].append(dict(player_id=r["player_id"], name=r["n"], pos=r["position"],
                                         age=_age(r["birth_date"], _today(conn)), pick=r["overall_pick"],
                                         draft_year=r["draft_year"], expires=r["expires_year"],
                                         club=where_is(conn, r["player_id"])))
    return out


def inbox(conn, all_=False):
    rows = conn.execute("SELECT * FROM inbox " + ("" if all_ else "WHERE read=0 ") + "ORDER BY msg_id DESC LIMIT 100")
    return [dict(r) for r in rows]


def schedule(conn, n=20):
    me = user_team(conn)
    tm = teams_map(conn)
    return dict(upcoming=[dict(date=g["game_date"], home=g["home_team_id"] == me,
                               opponent=tm[g["away_team_id"] if g["home_team_id"] == me else g["home_team_id"]]["abbr"])
                          for g in conn.execute("SELECT * FROM games WHERE played=0 AND (home_team_id=? OR "
                                                "away_team_id=?) ORDER BY game_date LIMIT ?", (me, me, n))],
                results=results(conn, me, n))


def _league_feed(conn, n):
    """League-wide news: importance 2+, with one line per AI trade (not one per player moved)."""
    me = user_team(conn)
    rows = E.recent(conn, min_importance=2, limit=n * 4)
    keep = [e for e in rows if e["event_type"] != "PLAYER_TRADED" or me in (e["team_id"], e["other_team_id"])]
    return keep[:n]


def history(conn, scope="club", n=60):
    me = user_team(conn)
    if scope == "trades":
        rows = E.recent(conn, types=["TRADE_COMPLETED", "PLAYER_TRADED"], limit=n * 3)
        rows = [e for e in rows if e["event_type"] == "TRADE_COMPLETED" or me in (e["team_id"], e["other_team_id"])][:n]
    elif scope == "league":
        rows = _league_feed(conn, n)
    else:
        rows = E.recent(conn, team_id=me, limit=n)
    return [dict(date=e["event_date"], type=e["event_type"], text=e["summary"], player_id=e["player_id"],
                 importance=e["importance"]) for e in rows]


def _valuation(conn, pid):
    from ..game import valuation as V
    try:
        ev = V.evaluate_contract(conn, pid)
    except Exception:
        return None
    if ev is None:
        return None
    from ..game import regret as RG
    st = RG.status(conn, pid)
    elc = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='elc_terms'").fetchone():
        e = conn.execute("SELECT * FROM elc_terms WHERE player_id=?", (pid,)).fetchone()
        if e:
            elc = dict(signing_bonus=e["signing_bonus"], perf_max=e["perf_max"], slides=e["slides"],
                       leverage=e["leverage"], earned=e["earned_total"])
    return dict(elc=elc, rows=[dict(season=s, age=a, proj=round(o, 2), war=round(w, 2), worth=round(v)) for s, a, o, w, v
                      in ev["rows"]], value=round(ev["value"]), cost=round(ev["cost"]), surplus=round(ev["surplus"]),
                grade=ev["grade"], words=ev["words"], p_positive=round(ev["p_positive"], 2),
                regret=None if not st or st["regret"] is None else round(st["regret"]),
                phase=st and st["phase"], untradeable=bool(st and st["untradeable"]),
                expected=st and st.get("expected_surplus") and round(st["expected_surplus"]))


def _board(conn, me, n):
    from ..game import draft as D
    from ..game import scout_net as SN
    from ..game.world import where_is
    rows = D.board_rows(conn, me, n)
    lv = SN.levels(conn, [r["pid"] for r in rows])
    SN.ensure_tables(conn)
    watch = {r[0] for r in conn.execute("SELECT player_id FROM watchlist")}
    out = []
    for r in rows:
        out.append(dict(rank=r["rank"], player_id=r["pid"], name=E.player_name(conn, r["pid"]), pos=r["pos"],
                        age=r["age"], height=r["height"], nat=r["nat"], grade=r["grade"], line=r["line"],
                        flags=r["flags"] + (["exceptional status"] if SN.is_exceptional(conn, r["pid"]) else []),
                        club=where_is(conn, r["pid"]), level=lv.get(r["pid"]), watched=r["pid"] in watch,
                        region=SN.region_of(conn, r["pid"], r["nat"])))
    return out


def scouting_view(conn):
    """Next draft as the user's scouts see it, any time of year, plus the club's scouting set-up."""
    from ..game import draft as D
    from ..game import scouting as S
    me = user_team(conn)
    style = S.club_style(conn, me)
    return dict(year=D.draft_year(conn), style=style, style_label=S.STYLE_LABEL[style],
                error=round(S.club_sd(conn, me) * S.OWN_SCALE, 2), board=_board(conn, me, 60))


def teams_list(conn):
    return [dict(team_id=r["team_id"], abbr=r["abbr"], name=f"{r['name']} {r['nickname'] or ''}".strip())
            for r in conn.execute(f"SELECT * FROM teams WHERE {top_league_sql()} ORDER BY name")]


def news_view(conn, scope="club"):
    """Headlines, game recaps, the social feed and power rankings (hs/game/media.py; read-only)."""
    from ..game import media as M
    me = user_team(conn)
    return dict(headlines=M.headlines(conn, None if scope == "league" else me, 30),
                recaps=M.recent_recaps(conn, None if scope == "league" else me, 12),
                social=M.social(conn, 30), power=M.power_rankings(conn), scope=scope)


def game_view(conn, gid):
    """One game: the recap plus the 2D replay timeline (hs/game/replay.py)."""
    from ..game import media as M, replay as RP
    return dict(recap=M.recap(conn, gid), replay=RP.build(conn, gid))


# ---------------------------------------------------------------- trades (hs/game/gm_trades.py)

def _trade_assets(conn, team, m, me):
    from ..game import gm_trades as GT
    from ..game import trades as T
    from ..game import clauses as CL
    year = K.season_year(conn)
    block = set(GT.on_block(conn)) if team == me else set()
    players, picks = [], []
    for a in GT.assets_of(conn, team, m):
        if a[0] == "pick":
            y, rnd, orig = a[1]
            picks.append(dict(key=GT.asset_key(a), label=T.pick_label(conn, y, rnd, orig, team), year=y, round=rnd,
                              value=round(T._asset_value(m, a, team, False), 1), orig=E.team_abbr(conn, orig),
                              own=orig == team, protected=T.protection(conn, y, rnd, orig),
                              protect_values={t: round(T._asset_value(m, ("pick", a[1], t), team, False), 1)
                                              for t in (3, 5, 10)} if rnd == 1 else None,
                              cond_values={sp: round(T._asset_value(m, ("pick", a[1], sp), team, False), 1)
                                           for sp in (T.cond_spec(k, team) for k in T.CONDITIONS)
                                           if not T.check_condition(conn, y, rnd, orig, team, T.parse_spec(sp)[0], team)}
                              if rnd >= 2 and y == m.this_year else None,
                              condition=T.condition(conn, y, rnd, orig)))
            continue
        pid = a[1]
        p = conn.execute("SELECT first_name||' '||last_name n, position, birth_date, status FROM players WHERE "
                         "player_id=?", (pid,)).fetchone()
        m.values.setdefault(pid, R.player_value(conn, pid))
        c = K.current_contract(conn, pid, year)
        players.append(dict(key=GT.asset_key(a), player_id=pid, name=p["n"], pos=p["position"],
                            age=_age(p["birth_date"], _today(conn)),
                            status=p["status"], value=round(T._asset_value(m, a, team, False), 1),
                            cap=c["cap_hit"] if c else None, ends=(c["start_year"] + c["years"]) if c else None,
                            core=pid in m.core.get(team, set()), block=pid in block,
                            moved=pid in m.recently_moved, friction=round(m.friction(pid, team)) if team != me else None,
                            clause=(lambda c: c["short"] if c else None)(CL.of(conn, pid))))
    players.sort(key=lambda x: (x["status"] == "prospect", -x["value"]))
    return dict(players=players, picks=picks)


def trade_view(conn, team=None):
    from ..game import gm_trades as GT
    from ..game import trades as T
    me = user_team(conn)
    day = get_state(conn)[0]
    m = T.Market(conn, day)
    others = [dict(team_id=t, abbr=E.team_abbr(conn, t), posture=m.outlook[t], need=m.need(t)) for t in m.teams]
    others.sort(key=lambda x: x["abbr"])
    other = int(team) if team else None
    ok, why = GT.window_open(conn, day)
    out = dict(teams=others, team_id=other, window=dict(open=ok, why=why), deadline=str(T.deadline(conn)),
               mine=_trade_assets(conn, me, m, me), abbr=E.team_abbr(conn, me),
               offers=[dict(offer_id=r["offer_id"], text=GT.describe_offer(conn, r), note=r["note"])
                       for r in GT.open_offers(conn)])
    if other:
        out["theirs"] = _trade_assets(conn, other, m, me)
        out["their_abbr"] = E.team_abbr(conn, other)
        out["posture"], out["need"] = m.outlook[other], m.need(other)
        out["needs"] = {g: round(v) for g, v in m.needs[other].items()}      # v39: need scores 0-100
        out["state"] = round(m.S[other], 2)
    return out


def trade_eval(conn, team, give, get):
    from ..game import gm_trades as GT
    me = user_team(conn)
    g = [GT.parse_key(k) for k in give.split(",") if k]
    t = [GT.parse_key(k) for k in get.split(",") if k]
    if not g and not t:
        return dict(empty=True)
    return GT.evaluate(conn, me, int(team), g, t, get_state(conn)[0])


def trade_ask(conn, team, get):
    from ..game import gm_trades as GT
    me = user_team(conn)
    t = [GT.parse_key(k) for k in get.split(",") if k]
    pkg, why = GT.what_it_takes(conn, me, int(team), t, get_state(conn)[0])
    return dict(give=[GT.asset_key(a) for a in pkg] if pkg else [], why=why)


def lines_view(conn):
    """The lineup the engine will use, and who can go where (hs/game/lineup.py)."""
    from ..game import lineup as L
    me = user_team(conn)
    cur = L.current(conn, me)
    players = []
    for r in conn.execute("SELECT player_id, first_name||' '||last_name n, position, status FROM players WHERE "
                          "team_id=? AND status IN ('active','injured') ORDER BY position, last_name", (me,)):
        players.append(dict(player_id=r["player_id"], name=r["n"], pos=r["position"], status=r["status"],
                            value=round(R.player_value(conn, r["player_id"]))))
    from ..game import tactics as TC
    from ..game import boardroom as BR
    o = BR.owner(conn, me)
    from ..game import roles as RL
    roles = RL.team_roles(conn, me)
    for p in players:
        p.update(roles.get(p["player_id"], {}))
    notes = {}
    if cur:
        for i, ln in enumerate(cur["F"]):
            notes[f"F{i + 1}"] = RL.line_notes(roles, ln)
        for i, pr in enumerate(cur["D"]):
            notes[f"D{i + 1}"] = RL.line_notes(roles, pr, d=True)
    chem = []
    try:
        from ..sim.loader import load_teams
        from ..game.chemistry import team_view
        t = load_teams(conn).get(me)
        if t:
            chem = team_view(conn, t, get_state(conn)[0])
    except Exception:
        pass
    return dict(lineup=cur, players=players, system=TC.system_of(conn, me), systems=TC.options(conn, me),
                owner_identity=o["identity"] if o else None, line_notes=notes, chemistry=chem,
                tendencies={k: list(v) for k, v in __import__("hs.game.lineup", fromlist=["x"]).TENDENCIES.items()})


def tactics_view(conn, opp=None):
    """The Tactics screen (v33): the twelve settings with fit, execution and value for each option; the presets;
    the preferences; the next opponent's settings and what counters them."""
    from ..game import tactics as TC
    me = user_team(conn)
    nxt = conn.execute("SELECT home_team_id, away_team_id, game_date FROM games WHERE played=0 AND (home_team_id=? OR away_team_id=?) "
                       "ORDER BY game_date LIMIT 1", (me, me)).fetchone()
    opp = int(opp) if opp else (nxt[1] if nxt and nxt[0] == me else nxt[0] if nxt else None)
    sc = None
    if opp:
        sc = TC.scout_opponent(conn, me, opp)
        sc.update(team_id=opp, abbr=E.team_abbr(conn, opp), date=nxt[2] if nxt and opp in (nxt[0], nxt[1]) else None,
                  labels={k: TC.SETTINGS[k][3][v][0] for k, v in sc["theirs"].items()})
    m = TC.multipliers_for(conn, me)
    from ..game import boardroom as BR
    o = BR.owner(conn, me)
    return dict(settings=TC.setting_options(conn, me), presets=TC.options(conn, me), system=TC.system_of(conn, me),
                prefs=TC.prefs_of(conn, me), pref_options={k: dict(label=v[0], options=v[1]) for k, v in TC.PREFS.items()},
                value=round(TC.expected_value(m) * 100, 2), multipliers={k: round(v, 3) for k, v in m.items()}, scout=sc,
                owner_identity=o["identity"] if o else None,
                teams=[dict(team_id=r[0], abbr=r[1]) for r in conn.execute(f"SELECT team_id, abbr FROM teams WHERE {top_league_sql()} AND team_id<>? ORDER BY abbr", (me,))])


def staff_view(conn, role=None):
    """Your staff, what their quality does, and the market (hs/game/staff.py)."""
    if not _has(conn, "staff"):
        return dict(enabled=False)
    from ..game import staff as S
    me = user_team(conn)
    keys = ["coaching", "development", "evaluation", "medical", "communication", "leadership", "reputation"]
    row = lambda r: dict(staff_id=r["staff_id"], role=r["role"], role_name=S.ROLE_NAMES[r["role"]], name=r["name"],
                         age=r["age"], style=r["style"], salary=r["salary"], main=S.MAIN_ATTR[r["role"]],
                         **{k: r[k] for k in keys if k in r.keys()},
                         contract_end=r["contract_end"] if "contract_end" in r.keys() else None)
    mine = [row(r) for r in S.members(conn, me)]
    q = "SELECT * FROM staff WHERE team_id IS NULL" + (" AND role=?" if role else "")
    market = sorted((row(r) for r in conn.execute(q, (role,) if role else ())), key=lambda r: -r[r["main"]])[:40]
    held = {}
    for m in mine:
        held[m["role"]] = held.get(m["role"], 0) + 1
    return dict(enabled=True, mine=mine, market=market, roles=S.ROLE_NAMES,
                limits={k: S.ROLE_LIMIT[k] for k in S.ROLE_NAMES}, held=held,
                effects=dict(scout_sd=round(S.scout_sd(conn, me), 2), development=round(S.development_multiplier(conn, me), 2),
                             injury=round(S.injury_multiplier(conn, me), 2)))


def board_view(conn):
    """Owner, board confidence, objectives and reviews (hs/game/org.py)."""
    if not _has(conn, "board"):
        return dict(enabled=False)
    from ..game import org
    from ..game import boardroom as BR
    BR.ensure_tables(conn)
    me = user_team(conn)
    b, o = org.board_status(conn, me)
    hot = BR.trigger(conn, me, get_state(conn)[0]) if K.season_state(conn) == "regular_season" else None
    u = BR.open_ultimatum(conn, me)
    ult = None
    if u:
        sid = season_id(conn)
        gp, pts = BR._record(conn, me, sid)
        ult = dict(issued=u["issued"], games=u["games"], need=u["points_needed"], played=gp - u["gp_at_issue"],
                   got=pts - u["pts_at_issue"])
    directives = [dict(r) for r in conn.execute("SELECT * FROM directives WHERE team_id=? ORDER BY directive_id DESC "
                                                "LIMIT 10", (me,))]
    past_ult = [dict(r) for r in conn.execute("SELECT * FROM ultimatums WHERE team_id=? AND status<>'open' ORDER BY "
                                              "ultimatum_id DESC LIMIT 5", (me,))]
    btrend = [dict(date=r["date"], confidence=round(r["confidence"] * 100), trigger=r["trigger"]) for r in conn.execute(
        "SELECT * FROM board_trend WHERE team_id=? ORDER BY date", (me,))]
    objectives = [dict(r) for r in conn.execute("SELECT * FROM objectives WHERE team_id=? ORDER BY season_start_year "
                                                "DESC, objective_id LIMIT 24", (me,))]
    reviews = [dict(date=h["review_date"], kind=h["kind"], delta=round(h["delta"], 1), confidence=round(h["confidence"]),
                    reasons=json.loads(h["reasons"])) for h in conn.execute(
        "SELECT * FROM board_history WHERE team_id=? ORDER BY rowid DESC LIMIT 20", (me,))]
    trend = [dict(date=h["review_date"], confidence=round(h["confidence"])) for h in conn.execute(
        "SELECT review_date, confidence FROM board_history WHERE team_id=? ORDER BY rowid", (me,))]
    return dict(enabled=True, hot=hot, warn_at=BR.WARN, rumour_at=BR.RUMOUR, ultimatum=ult, directives=directives,
                past_ultimatums=past_ult, weekly=btrend,
                confidence=round(b["confidence"]), label=org.label(b["confidence"]),
                warning=bool(b["warnings"]), gm_since=b["gm_since"] if "gm_since" in b.keys() else None,
                owner=dict(o), objectives=objectives, reviews=reviews, trend=trend,
                vacancies=[E.team_abbr(conn, t) for t in org.vacancies(conn)])


# ================================================================ v26: standings, inbox, news, cards, talks, trades

def _team_extras(conn, sid, rules):
    """Per club: last ten, streak, home/away records, games left (regular season)."""
    out = {}
    for t in [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]:
        out[t] = dict(results=[], home=[0, 0, 0], away=[0, 0, 0], left=0)
    for g in conn.execute("SELECT home_team_id h, away_team_id a, home_goals hg, away_goals ag, went_to_ot ot, played "
                          "FROM games WHERE season_id=? AND game_type='RS' ORDER BY game_date, game_id", (sid,)):
        for t, gf, ga, side in ((g["h"], g["hg"], g["ag"], "home"), (g["a"], g["ag"], g["hg"], "away")):
            if t not in out:
                continue
            if not g["played"]:
                out[t]["left"] += 1
                continue
            res = "W" if gf > ga else "T" if gf == ga else ("O" if g["ot"] else "L")
            out[t]["results"].append(res)
            idx = 0 if res == "W" else 2 if res in ("O", "T") else 1
            out[t][side][idx] += 1
    for t, x in out.items():
        last = x["results"][-10:]
        x["l10"] = f"{last.count('W')}-{last.count('L')}-{last.count('O') + last.count('T')}"
        s = ""
        if x["results"]:
            k = x["results"][-1]
            n = 0
            for r in reversed(x["results"]):
                if r != k:
                    break
                n += 1
            s = f"{ {'W': 'W', 'L': 'L', 'O': 'OT', 'T': 'T'}[k]}{n}"
        x["streak"] = s
        x["home"] = "-".join(map(str, x["home"]))
        x["away"] = "-".join(map(str, x["away"]))
        del x["results"]
    return out


def standings_full(conn, mode="wildcard", only_conf_of=None):
    """Division, wild-card or league tables with P%, ROW, L10, streak, home/away and clinch marks
    (x playoff spot, y division, z conference, p best record, e eliminated; worked out from points and games left,
    so they are conservative)."""
    rules = db_rules(conn)
    sid = season_id(conn)
    rec, h2h = st.table(conn, sid)
    info = {t["team_id"]: t for t in team_rows(conn)}
    order = st.rank(rec, h2h, rules) if rec else sorted(info)
    order = [t for t in order if t in info] + [t for t in sorted(info) if t not in order]
    ex = _team_extras(conn, sid, rules)
    me = user_team(conn)
    pts_rule = rules["points"]
    rows = {}
    for i, t in enumerate(order):
        r = rec.get(t, dict(gp=0, w=0, l=0, otl=0, t=0, rw=0, row=0, gf=0, ga=0))
        pts = st.points(r, pts_rule) if r["gp"] else 0
        e = ex.get(t, dict(l10="", streak="", home="", away="", left=0))
        rows[t] = dict(team_id=t, abbr=info[t]["abbr"], name=info[t]["name"], nickname=info[t].get("nickname") or "",
                       conference=info[t]["conference"], division=info[t]["division"], gp=r["gp"], w=r["w"], l=r["l"],
                       otl=r["otl"], t=r.get("t", 0), pts=pts, pct=round(pts / max(1, r["gp"] * pts_rule["win"]), 3),
                       rw=r["rw"], row=r["row"], gf=r["gf"], ga=r["ga"], diff=r["gf"] - r["ga"], l10=e["l10"],
                       streak=e["streak"], home=e["home"], away=e["away"], left=e["left"],
                       max_pts=pts + e["left"] * pts_rule["win"], mine=t == me, rank=i + 1, clinch="")
    po = rules["playoffs"]
    confs = {}
    for t in order:
        confs.setdefault(rows[t]["conference"], []).append(t)
    for conf, ts in confs.items():
        for t in ts:
            r = rows[t]
            reach = sum(1 for u in ts if u != t and rows[u]["max_pts"] >= r["pts"])
            divr = [u for u in ts if u != t and rows[u]["division"] == r["division"]]
            above = sum(1 for u in ts if rows[u]["pts"] > r["max_pts"])
            div_above = sum(1 for u in divr if rows[u]["pts"] > r["max_pts"])
            if r["gp"] and all(rows[u]["max_pts"] < r["pts"] for u in rows if u != t):
                r["clinch"] = "p"
            elif r["gp"] and reach == 0:
                r["clinch"] = "z"
            elif r["gp"] and divr and all(rows[u]["max_pts"] < r["pts"] for u in divr):
                r["clinch"] = "y"
            elif r["gp"] and reach <= 5:
                r["clinch"] = "x"
            elif above >= 8 and (po["format"] != "division_wildcard" or div_above >= po.get("per_division", 3)):
                r["clinch"] = "e"
    out = dict(mode=mode, format=po["format"], per_division=po.get("per_division"),
               wildcards=po.get("wildcards_per_conference"), top_n=po.get("teams_per_conference", 8), groups=[],
               season=K.season_year(conn))
    if mode == "division":
        divs = {}
        for t in order:
            divs.setdefault((rows[t]["conference"], rows[t]["division"]), []).append(rows[t])
        for (conf, div), rs in divs.items():
            out["groups"].append(dict(title=div, conference=conf, sections=[dict(title=None, rows=rs,
                                      cut=po.get("per_division") if po["format"] == "division_wildcard" else None)]))
    elif mode == "league":
        out["groups"].append(dict(title="League", sections=[dict(title=None, rows=[rows[t] for t in order], cut=None)]))
    else:
        for conf, ts in confs.items():
            if only_conf_of is not None and rows.get(only_conf_of, {}).get("conference") != conf:
                continue
            secs = []
            if po["format"] == "division_wildcard":
                divs = {}
                for t in ts:
                    divs.setdefault(rows[t]["division"], []).append(t)
                rest = []
                for div, members in divs.items():
                    secs.append(dict(title=div, rows=[rows[t] for t in members[:po["per_division"]]], cut=None))
                    rest += members[po["per_division"]:]
                rest.sort(key=lambda t: rows[t]["rank"])
                secs.append(dict(title="Wild card", rows=[rows[t] for t in rest], cut=po["wildcards_per_conference"]))
            else:
                secs.append(dict(title=None, rows=[rows[t] for t in ts], cut=po.get("teams_per_conference", 8)))
            out["groups"].append(dict(title=f"{conf} Conference" if "onf" not in conf else conf, conference=conf,
                                      sections=secs))
    return out


# ---------------------------------------------------------------- inbox (mail client)

FOLDERS = [("all", "Inbox"), ("unread", "Unread"), ("flagged", "Flagged"), ("board", "Owner & board"), ("players", "Players & agents"),
           ("trades", "Trades"), ("staff", "Staff reports"), ("league", "League office"), ("archived", "Archive")]
CMD_LABEL = {"accept": "Accept", "decline": "Decline", "walkaway": "Walk away", "fa": "Free agents", "offers": "Offers",
             "qualify": "Qualify", "extend": "Extend", "talk": "Talk", "meet": "Meet"}


def _sender_name(conn, cat, subject):
    """v38: who wrote it, by name where the club has the person (the coach, the physio, the owner...)."""
    from ..game.state import staff_sender
    s = (subject or "").lower()
    me = user_team(conn)
    if cat == "board":
        r = conn.execute("SELECT name FROM owners WHERE team_id=?", (me,)).fetchone() if _has(conn, "owners") else None
        return f"{r[0]}, Owner" if r and r[0] else "Owner's office"
    if any(k in s for k in ("injur", "recovered", "aggravat", "medical", "playing hurt")):
        return staff_sender(conn, "MED")
    if any(k in s for k in ("scout", "draft", "prospect", "central", "tournament", "combine")):
        return staff_sender(conn, "SCOUT_DIR")
    if any(k in s for k in ("development", "training", "camp report")):
        return staff_sender(conn, "DEV")
    if any(k in s for k in ("room", "lines", "tactic", "captain", "leadership")):
        return staff_sender(conn, "HC")
    return {"trades": "Hockey operations", "players": "Player relations", "staff": "Staff", "league": "League office"}.get(cat, "League office")


def _actions(m, body):
    """Buttons for a message: the ones it carries, then commands quoted in `backticks`, then the usual places."""
    import re
    out = list(m)
    have = {a.get("cmd") for a in out}
    for c in re.findall(r"`([a-z][a-z0-9 ._-]{1,40})`", body or ""):
        if c not in have and not c.startswith(("python", "hs ")):
            word = c.split()[0]
            out.append(dict(label=CMD_LABEL.get(word, c), cmd=c))
            have.add(c)
    return out


def _classify(subject, body):
    s = (subject or "").lower()
    if any(k in s for k in ("owner", "board", "directive", "ultimatum", "urgent", "job", "fired", "objective")):
        return "board", "Owner's office", "#6a3fa0"
    if any(k in s for k in ("trade", "offer sheet", "waiver")):
        return "trades", "Hockey operations", "#1f5fa8"
    if any(k in s for k in ("meeting", "qualifying", "contract", "arbitration", "agent", "extension", "promise",
                            "signed", "bonus", "free agen")):
        return "players", "Player relations", "#13806a"
    if any(k in s for k in ("injury", "recovered", "development", "scout", "staff", "medical", "prospect", "draft")):
        return "staff", "Staff", "#b86e00"
    return "league", "League office", "#1f3a5f"


def inbox_view(conn, folder="all", q=""):
    from ..game.state import _inbox_columns
    _inbox_columns(conn)
    rows = conn.execute("SELECT * FROM inbox ORDER BY msg_id DESC").fetchall()
    msgs, counts = [], {k: 0 for k, _ in FOLDERS}
    names = {}
    for r in rows:
        cat, sender, colour = _classify(r["subject"], r["body"])
        if r["sender"]:
            sender = r["sender"]
            low = sender.lower()                          # v38: the folder follows who wrote it
            if "owner" in low:
                cat, colour = "board", "#6a3fa0"
            elif "general manager," in low:
                cat, colour = "trades", "#1f5fa8"
            elif any(k in low for k in ("assistant gm", "coach", "physio", "scout", "development", "analytics")):
                cat, colour = "staff", "#b86e00"
        else:
            key = (cat, (r["subject"] or "").lower()[:30])
            if key not in names:
                names[key] = _sender_name(conn, cat, r["subject"])
            sender = names[key]
        acts = json.loads(r["actions"]) if r["actions"] else []
        m = dict(msg_id=r["msg_id"], date=r["date"], subject=r["subject"], body=r["body"], read=bool(r["read"]),
                 folder=cat, sender=sender, colour=colour, snippet=(r["body"] or "")[:140], flagged=bool(r["flagged"]),
                 archived=bool(r["archived"]), actions=_actions(acts, r["body"]))
        if m["archived"]:
            counts["archived"] += 1
            if folder != "archived":
                continue
        elif folder == "archived":
            continue
        counts["all"] += 1
        counts[cat] += 1
        if m["flagged"]:
            counts["flagged"] += 1
        if not m["read"]:
            counts["unread"] += 1
        if folder == "unread" and m["read"]:
            continue
        if folder == "flagged" and not m["flagged"]:
            continue
        if folder not in ("all", "unread", "flagged", "archived") and cat != folder:
            continue
        if q and q.lower() not in f"{m['subject']} {m['body']}".lower():
            continue
        msgs.append(m)
    return dict(folders=[dict(key=k, label=l, count=counts[k]) for k, l in FOLDERS], messages=msgs[:400],
                unread=counts["unread"], folder=folder)


# ---------------------------------------------------------------- news history

NEWS_TYPES = {"trades": ("TRADE_COMPLETED",), "signings": ("PLAYER_SIGNED", "ARBITRATION_AWARD", "PLAYER_RELEASED"),
              "injuries": ("PLAYER_INJURED",), "front office": ("GM_FIRED", "GM_HIRED", "COACH_FIRED", "STAFF_HIRED",
                                                                "STAFF_DISMISSED", "RUMOUR", "BOARD_REVIEW"),
              "draft": ("PLAYER_DRAFTED",), "retirements": ("PLAYER_RETIRED",)}


def news_history(conn, kind="headlines", scope="league", season=None, offset=0, month=""):
    """A season's news, newest first, 40 at a time, by month and type, for any season played. Headlines are the
    newspaper's (hs.game.media); the other kinds are the league's transaction wire."""
    from ..game import media as M
    me = user_team(conn)
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM league_events WHERE "
                                          "season_start_year IS NOT NULL ORDER BY 1 DESC")]
    season = season or (seasons[0] if seasons else K.season_year(conn))
    where, args = ["season_start_year=?", "importance>=2"], [season]
    if scope == "club":
        where.append("(team_id=? OR other_team_id=?)")
        args += [me, me]
    types = M.NEWS_TYPES if kind == "headlines" else NEWS_TYPES.get(kind, ())
    if types:
        where.append(f"event_type IN ({','.join('?' * len(types))})")
        args += list(types)
    if month:
        where.append("substr(event_date,1,7)=?")
        args.append(month)
    rows = conn.execute(f"SELECT * FROM league_events WHERE {' AND '.join(where)} ORDER BY event_date DESC, "
                        f"event_id DESC", args).fetchall()
    tm = teams_map(conn)
    items = []
    for e in rows:
        h = None
        if kind == "headlines":
            h = M._headline(conn, e)
            if h is None:
                continue
        items.append(dict(event_id=e["event_id"], date=e["event_date"], type=e["event_type"], text=h[1] if h else e["summary"],
                          headline=h[0] if h else None, tag=h[2] if h else e["event_type"].lower().replace("_", " "),
                          player_id=e["player_id"], team=tm.get(e["team_id"], {}).get("abbr", ""),
                          mine=me in (e["team_id"], e["other_team_id"])))
    months = [r[0] for r in conn.execute("SELECT DISTINCT substr(event_date,1,7) FROM league_events WHERE "
                                         "season_start_year=? ORDER BY 1 DESC", (season,))]
    return dict(items=items[offset:offset + 40], total=len(items), offset=offset, seasons=seasons, season=season,
                months=months, month=month, kinds=["headlines"] + list(NEWS_TYPES), kind=kind, scope=scope)


# ---------------------------------------------------------------- player card (pop-over)

def player_card(conn, pid):
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None:
        raise ValueError("No such player.")
    year = K.season_year(conn)
    a = conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone()
    keys = LIST_KEYS["G" if p["position"] == "G" else "F"]
    tm = teams_map(conn)
    c = K.current_contract(conn, pid, year)
    sid = season_id(conn)
    s = conn.execute("SELECT COUNT(*) gp, SUM(goals) g, SUM(assists) a, SUM(shots) sog, SUM(toi_sec) toi, SUM(saves) sv, "
                     "SUM(shots_against) sa FROM player_game_stats s JOIN games g USING (game_id) WHERE s.player_id=? AND "
                     "g.season_id=? AND g.game_type='RS'", (pid, sid)).fetchone()
    last = conn.execute("SELECT season_start_year, gp, g, a FROM skater_season_stats WHERE player_id=? AND split='RS' "
                        "ORDER BY season_start_year DESC LIMIT 1", (pid,)).fetchone()
    try:
        from ..game import valuation as V
        val = V.fair_aav(conn, pid, 3)
    except Exception:
        val = None
    return dict(player_id=pid, name=f"{p['first_name']} {p['last_name']}", position=p["position"],
                age=_age(p["birth_date"], _today(conn)) if p["birth_date"] else None, nationality=p["nationality"],
                team=tm.get(p["team_id"], {}).get("abbr") if p["team_id"] else "Free agent", status=p["status"],
                value=round(K.league_values(conn).value(pid), 1),
                ratings=[dict(key=k, label=k.replace("_", " "), value=a[k] if a else None) for k in keys],
                contract=dict(cap_hit=c["cap_hit"], ends=c["start_year"] + c["years"], no_trade=bool(c["no_trade"]))
                if c else None,
                season=dict(gp=s["gp"], g=s["g"] or 0, a=s["a"] or 0, sog=s["sog"] or 0,
                            toi=round((s["toi"] or 0) / max(1, s["gp"]) / 60, 1),
                            sv_pct=round(s["sv"] / s["sa"], 3) if s["sa"] else None) if s and s["gp"] else None,
                last=dict(last) if last else None, fair3=val, mine=p["team_id"] == user_team(conn))


def negotiation_view(conn, pid):
    from ..game import negotiation as N
    N.ensure_tables(conn)
    return N.view(conn, pid)


def trade_eval3(conn, a, b, legs):
    """legs: 'player:1>12,pick:2027:1:12>me' (destination team id, or 'me')."""
    from ..game import gm_trades as GT
    from ..game import trade3 as T3
    me = user_team(conn)
    moves = []
    for leg in [x for x in legs.split(",") if x]:
        key, to = leg.rsplit(">", 1)
        asset = GT.parse_key(key)
        to = me if to == "me" else int(to)
        frm = T3.T.pick_owner(conn, *asset[1]) if asset[0] == "pick" else \
            conn.execute("SELECT team_id FROM players WHERE player_id=?", (asset[1],)).fetchone()[0]
        moves.append((frm, to, asset))
    if not moves:
        return dict(empty=True)
    try:
        ev = T3.evaluate(conn, moves, get_state(conn)[0])
    except Exception as e:
        return dict(accept=False, invalid=str(e), clubs={})
    return dict(accept=ev["accept"], clubs={str(k): dict(abbr=v["abbr"], accept=v["accept"], why=v["why"],
                                                          ratio=v["ratio"], need_ratio=v["need_ratio"],
                                                          receive=v["receive"], give=v["give"])
                                            for k, v in ev["clubs"].items()})


def analytics_view(conn, tab="teams", team=None):
    from . import analytics as AN
    return AN.view(conn, tab, int(team) if team else None)


# ---------------------------------------------------------------- v27: stats hub, team pages, history (hs/ui/stats.py)

def _record_book(conn):
    from ..game import history as H
    H.backfill(conn)


def stats_hub(conn, season=None, league=None, split="RS"):
    from . import stats as S
    _record_book(conn)
    return S.hub(conn, season, league, split)


def team_view(conn, team_id, season=None):
    from . import stats as S
    _record_book(conn)
    return S.team_page(conn, team_id, season)


def league_history(conn):
    from . import stats as S
    _record_book(conn)
    return S.history(conn)


def player_extras(conn, pid):
    from . import stats as S
    _record_book(conn)
    return S.player_extras(conn, pid)


def press_view(conn):
    from ..game import press
    return press.view(conn)


def captaincy_view(conn, c=None, a=""):
    """The leadership group, the roster ranked by the room, and (with c) a preview of a change."""
    from ..game import captaincy as CP
    me = user_team(conn)
    day = get_state(conn)[0]
    rank = CP.room_ranking(conn, me, day)
    cur = CP.current(conn, me)
    from ..game.people import traits
    roster = []
    for pid, score in rank:
        tr = traits(conn, pid)
        p = conn.execute("SELECT first_name||' '||last_name n, position, birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
        roster.append(dict(player_id=pid, name=p["n"], pos=p["position"], age=_age(p["birth_date"], _today(conn)), score=round(score, 1),
                           leadership=tr["leadership"], professionalism=tr["professionalism"], ego=tr["ego"], loyalty=tr["loyalty"],
                           role=cur.get(pid), value=round(R.player_value(conn, pid))))
    out = dict(roster=roster, current=[dict(player_id=p, role=r) for p, r in cur.items()])
    if c:
        alts = [int(x) for x in a.split(",") if x]
        try:
            fx = CP.preview(conn, me, int(c), alts)
            out["preview"] = {k: fx[k] for k in ("people", "cohesion", "board", "notes", "mid_season", "leadership_strength")}
        except ValueError as e:
            out["error"] = str(e)
    return out


def draft_view(conn):
    from ..game import draft as D
    d = D.draft_room(conn)
    d["phase"] = K.season_state(conn)
    me = user_team(conn)
    if d["started"] and not d["done"]:
        d["board"] = _draft_names(conn, D.board_rows(conn, me, limit=60))
        rk = D.rankings(conn, d["year"])
        for r in d["board"]:
            r.update(rk.get(r["pid"], {}))
        d["deals"] = D.pick_deals(conn)
    return d


def _draft_names(conn, rows):
    for r in rows:
        p = conn.execute("SELECT p.first_name||' '||p.last_name, t.name, l.abbr FROM players p LEFT JOIN teams t ON "
                         "t.team_id=p.club_id LEFT JOIN leagues l ON l.league_id=t.league_id WHERE p.player_id=?",
                         (r["pid"],)).fetchone()
        r.update(player_id=r["pid"], name=p[0], club=p[1], league=p[2])
    return rows


def playoffs_view(conn, season=None):
    """The bracket from the playoff games of a season: series by round, wins, games."""
    from ..game.history import AWARDS, VOTERS, ensure_tables
    ensure_tables(conn)
    q = "SELECT season_id, start_year FROM seasons WHERE league_id=(SELECT league_id FROM teams WHERE team_id=?)"
    seasons = [(r[0], r[1]) for r in conn.execute(q + " ORDER BY start_year DESC", (user_team(conn),))
               if conn.execute("SELECT 1 FROM games WHERE season_id=? AND game_type='PO'", (r[0],)).fetchone()]
    if not seasons:
        return dict(seasons=[], rounds=[])
    sid, year = next(((s, y) for s, y in seasons if str(y) == str(season)), seasons[0])
    tm = teams_map(conn)
    series = {}
    for g in conn.execute("SELECT game_id, series_id, game_no, home_team_id, away_team_id, home_goals, away_goals, went_to_ot "
                          "FROM games WHERE season_id=? AND game_type='PO' AND played=1 ORDER BY game_date, game_id", (sid,)):
        s = series.setdefault(g["series_id"], dict(label=g["series_id"], wins={}, games=[], teams=[]))
        for t in (g["home_team_id"], g["away_team_id"]):
            if t not in s["teams"]:
                s["teams"].append(t)
            s["wins"].setdefault(t, 0)
        w = g["home_team_id"] if g["home_goals"] > g["away_goals"] else g["away_team_id"]
        s["wins"][w] += 1
        s["games"].append(dict(game_id=g["game_id"], no=g["game_no"], home=tm[g["home_team_id"]]["abbr"], away=tm[g["away_team_id"]]["abbr"],
                               hg=g["home_goals"], ag=g["away_goals"], ot={1: "OT", 2: "SO"}.get(g["went_to_ot"], "")))
    def rnd(label):
        return 4 if label == "Final" else 3 if label.startswith("Conference") else 2 if label.startswith("R2") else 1
    rounds = {1: [], 2: [], 3: [], 4: []}
    me = user_team(conn)
    for s in series.values():
        a, b = s["teams"][0], s["teams"][1]
        w = max(s["wins"], key=s["wins"].get)
        rounds[rnd(s["label"])].append(dict(label=s["label"], conf="Eastern" if "Eastern" in s["label"] else "Western" if "Western" in s["label"] else "",
                                            teams=[dict(team_id=t, abbr=tm[t]["abbr"], name=tm[t]["name"], wins=s["wins"][t], won=t == w, mine=t == me) for t in (a, b)],
                                            games=s["games"]))
    for k in rounds:
        rounds[k].sort(key=lambda s: (s["conf"], s["label"]))
    champ = next((t for s in rounds[4] for t in s["teams"] if t["won"]), None)
    awards = []
    for r in conn.execute("SELECT * FROM awards WHERE season_start_year=?", (year,)):
        who = None
        if r["player_id"]:
            who = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (r["player_id"],)).fetchone()[0]
        elif r["staff_id"]:
            x = conn.execute("SELECT name FROM staff WHERE staff_id=?", (r["staff_id"],)).fetchone()
            who = x[0] if x else None
        else:
            who = tm.get(r["team_id"], {}).get("name")
        awards.append(dict(key=r["award"], award=AWARDS.get(r["award"], (r["award"], ""))[0], what=AWARDS.get(r["award"], ("", ""))[1],
                           who=who, player_id=r["player_id"], team=tm.get(r["team_id"], {}).get("abbr"), detail=r["detail"],
                           by=VOTERS.get(r["award"], "")))
    order = ["hart", "art_ross", "richard", "vezina", "norris", "calder", "conn_smythe", "jack_adams", "gm_year", "presidents"]
    awards.sort(key=lambda a: order.index(a["key"]) if a["key"] in order else 99)
    final = rounds[4][0] if rounds[4] else None
    leaders = []
    if champ:
        leaders = [dict(player_id=r[0], name=r[1], pos=r[2], gp=r[3], g=r[4], a=r[5]) for r in conn.execute(
            "SELECT s.player_id, p.first_name||' '||p.last_name, p.position, COUNT(*), SUM(s.goals), SUM(s.assists) FROM player_game_stats s "
            "JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND g.game_type='PO' AND s.team_id=? AND "
            "p.position<>'G' GROUP BY 1 ORDER BY SUM(s.goals)+SUM(s.assists) DESC, SUM(s.goals) DESC LIMIT 6", (sid, champ["team_id"]))]
    path = [dict(round=i + 1, opp=next((t for t in s["teams"] if not t["won"]), {}).get("abbr"), score="-".join(str(t["wins"]) for t in sorted(s["teams"], key=lambda t: -t["wins"])))
            for i, k in enumerate((1, 2, 3, 4)) for s in rounds[k] if champ and any(t["team_id"] == champ["team_id"] for t in s["teams"])]
    return dict(seasons=[y for _, y in seasons], season=year, rounds=[rounds[k] for k in (1, 2, 3, 4)], champion=champ, awards=awards,
                final=final, champ_leaders=leaders, champ_path=path)


def warroom_view(conn):
    """Free agency, live: the round just played, the market with asks and interest, your offers."""
    from ..game import free_agency as FA
    FA.ensure_tables(conn)
    st = FA.live_state(conn)
    pending = conn.execute("SELECT value FROM pack_info WHERE key='fa_live_pending'").fetchone()
    out = dict(phase=K.season_state(conn), open=bool(pending), running=st is not None and not st["done"],
               last=st["last"] if st else None, done=bool(st and st["done"]), summary=st["lines"] if st else None)
    me = user_team(conn)
    yr = K.signing_year(conn)
    out["room"] = K.cap_room(conn, me, yr)
    out["offers"] = [dict(player_id=r[0], name=E.player_name(conn, r[0]), aav=r[1], years=r[2]) for r in conn.execute(
        "SELECT player_id, aav, years FROM fa_offers WHERE team_id=? AND season=?", (me, yr))]
    if not out["last"]:                               # before noon: the pool as the market will open
        rows = []
        for v, pid, pos in R.free_agents(conn)[:80]:
            p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
            rows.append(dict(player_id=pid, name=E.player_name(conn, pid), pos=pos, age=_age(p[0], _today(conn)),
                             value=round(v, 1), ask=K.asking(conn, pid, "UFA")))
        out["pool"] = rows
    out["log"] = [dict(r) for r in conn.execute("SELECT f.*, p.first_name||' '||p.last_name name FROM fa_log f JOIN players p USING "
                                                "(player_id) WHERE season=? ORDER BY hour, aav DESC", (yr,))]
    tm = teams_map(conn)
    for r in out["log"]:
        r["team"] = tm.get(r["team_id"], {}).get("abbr")
    return out


def rights_view(conn):
    """Your expiring contracts as decisions to make before free agency (the rights phase)."""
    from ..game import offseason as O
    from ..game import negotiation as N
    me = user_team(conn)
    rows = []
    for r in O.rights_rows(conn):
        if r["team_id"] != me:
            continue
        d = dict(r)
        d["name"] = E.player_name(conn, r["player_id"])
        p = conn.execute("SELECT position, birth_date FROM players WHERE player_id=?", (r["player_id"],)).fetchone()
        d["pos"], d["age"] = p[0], _age(p[1], _today(conn))
        d["value"] = round(K.league_values(conn).value(r["player_id"]), 1)
        try:
            d["asking"] = K.asking(conn, r["player_id"], r["status"])
        except Exception:
            d["asking"] = None
        d["agent"] = N.agent_of(r["player_id"])
        st = conn.execute("SELECT status FROM negotiations WHERE player_id=?", (r["player_id"],)).fetchone() \
            if _has(conn, "negotiations") else None
        d["talks"] = st[0] if st else None
        d["decided"] = bool(r["outcome"]) or (r["status"] == "RFA" and r["qualified"] is not None)
        rows.append(d)
    rows.sort(key=lambda x: -x["value"])
    return dict(phase=K.season_state(conn), rows=rows, undecided=sum(1 for x in rows if not x["decided"]))


# ---------------------------------------------------------------- v28: calendar, free agents, prospects, development
def calendar_view(conn, month=None):
    """Your season as a calendar: every game (result or opponent), plus the league's key dates."""
    me = user_team(conn)
    tm = teams_map(conn)
    today = get_state(conn)[0]
    sid = season_id(conn)
    games = []
    for g in conn.execute("SELECT * FROM games WHERE season_id=? AND (home_team_id=? OR away_team_id=?) ORDER BY game_date",
                          (sid, me, me)):
        home = g["home_team_id"] == me
        opp = tm[g["away_team_id"] if home else g["home_team_id"]]
        d = dict(game_id=g["game_id"], date=g["game_date"], home=home, opponent=opp["abbr"], opponent_id=opp["team_id"],
                 type=g["game_type"], played=bool(g["played"]))
        if g["played"]:
            mine, theirs = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
            d.update(score=f"{mine}-{theirs}", result="W" if mine > theirs else ("OTL" if g["went_to_ot"] else "L"),
                     ot={0: "", 1: "OT", 2: "SO"}.get(g["went_to_ot"] or 0, ""))
        games.append(d)
    events = []
    try:
        from ..game import trades as TR
        dl = TR.deadline(conn)
        if dl:
            events.append(dict(date=dl, label="Trade deadline"))
    except Exception:
        pass
    if games:
        rs = [g for g in games if g["type"] == "RS"]
        if rs:
            events.append(dict(date=rs[0]["date"], label="Opening night"))
            events.append(dict(date=rs[-1]["date"], label="Last regular-season game"))
    try:                                                  # v37: all-star weekend, exhibitions, the summer's dates, tournaments
        from ..game import exhibitions as EX
        events += [dict(date=d, label=l) for d, l in EX.league_dates(conn)]
    except Exception:
        pass
    for e in events:
        e["date"] = str(e["date"])[:10]
    span = {g["date"][:7] for g in games}
    lo, hi = (min(span), max(span)) if span else (today[:7], today[:7])
    extra = {e["date"][:7] for e in events if e["date"][:7] >= lo[:4] + "-08" and e["date"][:7] <= str(int(hi[:4]) + (1 if hi[5:] > "07" else 0)) + "-07"}
    months = sorted(span | extra | {today[:7]})
    month = month if month in months else (today[:7] if today[:7] in months else months[0])
    return dict(today=today, month=month, months=months, games=games, events=events)


def freeagents_view(conn, pos=""):
    """The free agent centre: everyone unsigned, best first, with the ask; your cap room."""
    me = user_team(conn)
    on = _today(conn)
    out = []
    for v, pid, p in R.free_agents(conn):
        if pos and p != pos:
            continue
        r = conn.execute("SELECT first_name||' '||last_name n, birth_date, nationality FROM players WHERE player_id=?",
                         (pid,)).fetchone()
        try:
            ask = K.asking(conn, pid, "UFA")
        except Exception:
            ask = None
        out.append(dict(player_id=pid, name=r["n"], pos=p, age=_age(r["birth_date"], on), nat=r["nationality"],
                        value=round(v), ask=ask))
        if len(out) >= 150:
            break
    room = K.crules(conn)["cap_ceiling"] - K.payroll(conn, me)
    return dict(players=out, cap_room=room, phase=K.season_state(conn),
                contracts=conn.execute("SELECT COUNT(*) FROM contracts c JOIN players p USING (player_id) WHERE p.team_id=? AND "
                                       "c.start_year<=? AND c.start_year+c.years-1>=?", (me, K.season_year(conn), K.season_year(conn))).fetchone()[0])


def prospects_league(conn, n=120):
    """v38 (#13): the league's best prospects (signed below the NHL, or unsigned rights), by club. Potential is what
    your scouts can see: their knowledge level of the player decides how sure the stars are."""
    from ..game.world import where_is
    on = _today(conn)
    me = user_team(conn)
    try:
        from ..game import scout_net as SN
        know = SN.levels(conn)
    except Exception:
        know = {}
    rows = conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, p.position, p.birth_date, p.team_id t, d.potential FROM players p "
                        "LEFT JOIN player_dev d USING (player_id) WHERE p.status='prospect' AND p.team_id IS NOT NULL UNION "
                        "SELECT p.player_id, p.first_name||' '||p.last_name, p.position, p.birth_date, r.team_id, d.potential FROM draft_rights r "
                        "JOIN players p USING (player_id) LEFT JOIN player_dev d USING (player_id)").fetchall() if _has(conn, "draft_rights") else []
    tm = teams_map(conn)
    out = []
    for r in rows:
        pid = r[0]
        lv = know.get(pid) if r[4] != me else "A"
        pot = r[5]
        shown = pot if lv in ("A", "B") else (round(pot / 2) * 2 if pot is not None and lv == "C" else None)
        v = R.player_value(conn, pid)
        out.append(dict(player_id=pid, name=r[1], pos=r[2], age=_age(r[3], on), team=tm.get(r[4], {}).get("abbr"), team_id=r[4],
                        club=None, value=round(v), potential=shown, known=lv or "E", _p=(shown * 3 if shown is not None else 0) + v))
    out.sort(key=lambda x: -x["_p"])                  # what you can see: ability, and the ceiling your scouts know
    for x in out[:n]:
        x.pop("_p")
        x["club"] = where_is(conn, x["player_id"])
    return dict(league=True, rows=out[:n], total=len(out))


def prospects_view(conn, team=None, scope=None):
    """Your pipeline: unsigned draft rights and signed players below the NHL, with where they play. v38: any club's
    (team), or the league's best (scope='league')."""
    if scope == "league":
        return prospects_league(conn)
    from ..game.world import where_is
    me = int(team) if team else user_team(conn)
    on = _today(conn)
    year = K.season_year(conn)
    rights = []
    if _has(conn, "draft_rights"):
        for r in conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, p.position, p.birth_date, d.draft_year, "
                              "d.overall_pick, d.expires_year FROM draft_rights d JOIN players p USING (player_id) WHERE "
                              "d.team_id=? ORDER BY d.draft_year DESC, d.overall_pick", (me,)):
            rights.append(dict(player_id=r["player_id"], name=r["n"], pos=r["position"], age=_age(r["birth_date"], on),
                               draft_year=r["draft_year"], pick=r["overall_pick"], expires=r["expires_year"],
                               club=where_is(conn, r["player_id"]), value=round(R.player_value(conn, r["player_id"]))))
    signed = []
    for r in conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, p.position, p.birth_date FROM players p "
                          "WHERE p.team_id=? AND p.status='prospect' ORDER BY p.position, p.last_name", (me,)):
        signed.append(dict(player_id=r["player_id"], name=r["n"], pos=r["position"], age=_age(r["birth_date"], on),
                           club=where_is(conn, r["player_id"]), value=round(R.player_value(conn, r["player_id"])),
                           contract=_contract_dict(conn, r["player_id"], year)))
    pot = {r[0]: r[1] for r in conn.execute("SELECT player_id, potential FROM player_attributes WHERE player_id IN (%s)" %
                                             ",".join(str(x["player_id"]) for x in rights + signed) or "0")} if rights + signed else {}
    for x in rights + signed:
        x["potential"] = pot.get(x["player_id"])
    return dict(rights=rights, signed=signed, team_id=me, mine=me == user_team(conn),
                clubs=[dict(team_id=r[0], abbr=r[1]) for r in conn.execute("SELECT team_id, abbr FROM teams WHERE league_id IN "
                                                                          "(SELECT league_id FROM leagues WHERE COALESCE(level,1)=1) ORDER BY abbr")])


def development_view(conn):
    """How your organisation is developing: value now against last summer's snapshot, by player."""
    me = user_team(conn)
    on = _today(conn)
    rows = conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, p.position, p.birth_date, p.status FROM players p "
                        "WHERE p.team_id=? AND p.status IN ('active','injured','ltir','prospect')", (me,)).fetchall()
    years = [r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM attribute_history ORDER BY 1 DESC LIMIT 2")]
    out = []
    for r in rows:
        pid = r["player_id"]
        now = R.player_value(conn, pid)
        hist = conn.execute("SELECT * FROM attribute_history WHERE player_id=? ORDER BY season_start_year DESC LIMIT 1",
                            (pid,)).fetchone()
        then = None
        if hist is not None:
            try:
                from ..game.roster import value_from_attrs
                then = value_from_attrs(dict(hist), r["position"])
            except Exception:
                then = None
        pot = conn.execute("SELECT potential FROM player_attributes WHERE player_id=?", (pid,)).fetchone()
        out.append(dict(player_id=pid, name=r["n"], pos=r["position"], age=_age(r["birth_date"], on), status=r["status"],
                        value=round(now), was=round(then) if then is not None else None,
                        change=round(now - then, 1) if then is not None else None,
                        since=hist["season_start_year"] if hist is not None else None,
                        potential=pot[0] if pot else None))
    out.sort(key=lambda x: (-(x["change"] if x["change"] is not None else -99), -x["value"]))
    from ..game import training as TR                 # v36: training focus
    foc = TR.all_focus(conn)
    for x in out:
        x["focus"] = foc.get(x["player_id"], "balanced")
        x["focus_options"] = list(TR.GOALIE_FOCUS if x["pos"] == "G" else TR.SKATER_FOCUS)
    from ..game import development as DV              # v40: the development centre
    dv = DV.org_view(conn, get_state(conn)[0])
    for x in out:
        x["dev"] = dv["players"].get(x["player_id"])
    return dict(players=out, snapshots=years, intensity=dv["intensity"], mentors=dv["mentors"], words=dv["words"],
                intensities={k: dict(growth=v[0], injuries=v[1], ageing=v[2]) for k, v in DV.INTENSITY.items()})


def devlog_view(conn, pid):
    from ..game import development as DV
    return DV.player_view(conn, int(pid))


def search_view(conn, q=""):
    """The search box: players (any league, retired last) and clubs by name."""
    q = (q or "").strip()
    if len(q) < 2:
        return dict(players=[], teams=[])
    like = f"%{q}%"
    players = [dict(player_id=r[0], name=r[1], pos=r[2], team=r[3], status=r[4]) for r in conn.execute(
        "SELECT p.player_id, p.first_name||' '||p.last_name, p.position, COALESCE(t.abbr, c.name, ''), p.status FROM players p "
        "LEFT JOIN teams t ON t.team_id=p.team_id LEFT JOIN teams c ON c.team_id=p.club_id WHERE (p.first_name||' '||p.last_name) "
        "LIKE ? ORDER BY p.status='retired', p.team_id IS NULL, p.last_name LIMIT 14", (like,))]
    teams = [dict(team_id=r[0], name=r[1], abbr=r[2]) for r in conn.execute(
        "SELECT team_id, name||' '||COALESCE(nickname,''), abbr FROM teams WHERE name||' '||COALESCE(nickname,'') LIKE ? OR abbr LIKE ? "
        "ORDER BY name LIMIT 6", (like, q))]
    from . import screens
    return dict(players=players, teams=teams, staff=screens.staff_search(conn, q))


def article_view(conn, event_id):
    """One news story in full (a headline links here, not to the player): the article, the clubs and players in it,
    the season lines of the players, and the reaction."""
    from ..game import media as M
    e = conn.execute("SELECT * FROM league_events WHERE event_id=?", (event_id,)).fetchone()
    if e is None:
        raise ValueError("No such story.")
    h = M._headline(conn, e) or (e["summary"], e["summary"], (e["event_type"] or "").lower().replace("_", " "))
    pl = M._payload(e)
    clubs = []
    for tid in (e["team_id"], e["other_team_id"], pl.get("third_team_id")):
        if tid and tid not in [c["team_id"] for c in clubs]:
            t = conn.execute("SELECT team_id, abbr, name, nickname FROM teams WHERE team_id=?", (tid,)).fetchone()
            if t:
                clubs.append(dict(team_id=t[0], abbr=t[1], name=f"{t[2]} {t[3] or ''}".strip()))
    pids = [e["player_id"]] if e["player_id"] else []
    for k in ("players", "player_ids", "in", "out"):
        v = pl.get(k)
        if isinstance(v, list):
            pids += [x for x in v if isinstance(x, int)]
    # trades: every player named in the summary, matched by name against the clubs involved
    if e["event_type"] == "TRADE_COMPLETED" and clubs:
        ids = ",".join(str(c["team_id"]) for c in clubs)
        for r in conn.execute(f"SELECT player_id, first_name||' '||last_name FROM players WHERE team_id IN ({ids})"):
            if r[1] and r[1] in (e["summary"] or "") and r[0] not in pids:
                pids.append(r[0])
    year = K.season_year(conn)
    people = []
    for pid in pids[:8]:
        p = conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, p.position, p.birth_date, t.abbr FROM players p "
                         "LEFT JOIN teams t ON t.team_id=p.team_id WHERE p.player_id=?", (pid,)).fetchone()
        if not p:
            continue
        s = conn.execute("SELECT SUM(gp), SUM(g), SUM(a) FROM skater_season_stats WHERE player_id=? AND split='RS' AND "
                         "season_start_year=(SELECT MAX(season_start_year) FROM skater_season_stats WHERE player_id=?)", (pid, pid)).fetchone()
        c = K.current_contract(conn, pid, year)
        people.append(dict(player_id=pid, name=p["n"], pos=p["position"], team=p["abbr"], age=_age(p["birth_date"], _today(conn)),
                           value=round(R.player_value(conn, pid)), last=dict(gp=s[0], g=s[1], a=s[2]) if s and s[0] else None,
                           cap_hit=c["cap_hit"] if c else None, ends=(c["start_year"] + c["years"] - 1) if c else None))
    me = user_team(conn)
    try:
        post = M._post(conn, e, me)
    except Exception:
        post = None
    # paragraphs: the wire story, then what it means
    paras = [h[1]]
    if e["event_type"] == "TRADE_COMPLETED":
        parts = [x.strip() for x in (e["summary"] or "").replace("Three-team trade:", "").split(";") if x.strip()]
        if len(parts) > 1:
            paras = [f"{h[0]}." if not h[0].endswith(".") else h[0]] + [p[0].upper() + p[1:] + "." for p in parts]
        if people:
            vets = [x for x in people if x["last"]]
            if vets:
                paras.append("Last season: " + "; ".join(f"{x['name']} {x['last']['g']}-{x['last']['a']}-{x['last']['g'] + x['last']['a']} in "
                                                         f"{x['last']['gp']} games" for x in vets[:4]) + ".")
            money = [x for x in people if x["cap_hit"]]
            if money:
                paras.append("Contracts: " + "; ".join(f"{x['name']} ${x['cap_hit'] / 1e6:.2f}M through {x['ends']}-{(x['ends'] + 1) % 100:02d}"
                                                      for x in money[:4]) + ".")
    related = [dict(event_id=r[0], date=r[1], text=r[2]) for r in conn.execute(
        "SELECT event_id, event_date, summary FROM league_events WHERE event_id<>? AND importance>=2 AND event_type IN "
        f"({','.join('?' * len(M.NEWS_TYPES))}) AND (team_id IN (?,?) OR other_team_id IN (?,?)) ORDER BY event_date DESC, event_id DESC LIMIT 6",
        (event_id, *M.NEWS_TYPES, e["team_id"] or -1, e["other_team_id"] or -1, e["team_id"] or -1, e["other_team_id"] or -1))]
    return dict(event_id=event_id, date=e["event_date"], outlet=M.OUTLET_NEWS, headline=h[0], tag=h[2], paragraphs=paras,
                clubs=clubs, players=people, reaction=post, related=related)


def people_view(conn, pid):
    """v35, for the player screen: what your scouts read of his hidden side, his special abilities, his morale log,
    his game ratings, and (your players) whether he would agree to a mutual termination and can play hurt."""
    from ..game import hidden as HD
    from ..game import people as PE
    from ..game import welfare as W
    me = user_team(conn)
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None:
        raise ValueError("No such player.")
    mine = p["team_id"] == me and me is not None
    a = conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone()
    pers = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone() if _has(conn, "personality") else None
    out = dict(mine=mine, scout=HD.scout_read(conn, pid, mine), abilities=HD.abilities(dict(a) if a else {}, HD.of(conn, pid), p["position"],
                                                                                  dict(pers) if pers else None))
    out["morale_log"] = PE.morale_history(conn, pid) if mine else []
    ratings = []
    if _has(conn, "game_ratings"):
        ratings = [dict(game_id=r[0], date=r[1], offence=r[2], defence=r[3], overall=r[4]) for r in conn.execute(
            "SELECT r.game_id, g.game_date, r.offence, r.defence, r.overall FROM game_ratings r JOIN games g USING (game_id) WHERE r.player_id=? "
            "ORDER BY g.game_date DESC LIMIT 82", (pid,))]
    out["ratings"] = ratings[:10]
    out["rating_avg"] = round(sum(r["overall"] for r in ratings) / len(ratings), 2) if ratings else None
    if mine:
        ok, pay, why = W.terms(conn, pid)
        out["terminate"] = dict(willing=ok, settlement=pay, why=why)
        if p["status"] == "injured":
            inj = conn.execute("SELECT expected_return FROM injuries WHERE player_id=? ORDER BY injury_id DESC LIMIT 1", (pid,)).fetchone()
            if inj:
                left = (datetime.date.fromisoformat(inj[0]) - _today(conn)).days
                out["hurt"] = dict(days_left=left, can_play=left <= W.MAX_DAYS)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(injuries)")}
        if "playing_hurt" in cols and conn.execute("SELECT 1 FROM injuries WHERE player_id=? AND playing_hurt=1 AND expected_return>?",
                                                   (pid, get_state(conn)[0])).fetchone():
            out["playing_hurt"] = True
    return out


def harmony_view(conn, t=None):
    from ..game import harmony as HM
    return HM.view(conn, int(t) if t else user_team(conn))


def scoutnet_view(conn):
    from ..game import scout_net as SN
    return SN.network_view(conn)


def bureau_view(conn, stage=None):
    from ..game import scout_net as SN
    return SN.bureau_view(conn, stage)


def mock_view(conn):
    from ..game import scout_net as SN
    mock = SN.mock_draft(conn)
    ab = {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    sug = SN.suggestions(conn)
    lv = SN.levels(conn, [m["pid"] for m in mock] + [x["pid"] for x in sug["items"]])
    return dict(mock=[dict(m, abbr=ab.get(m["team_id"]), name=E.player_name(conn, m["pid"]), level=lv.get(m["pid"])) for m in mock],
                suggestions=dict(slot=sug["slot"], items=[dict(x, name=E.player_name(conn, x["pid"])) for x in sug["items"]]))


def devchart(conn, pid):
    """v36: a player's ratings by season (attribute groups and overall), for the development chart."""
    from ..game import training as TR
    groups = {"Offence": SK_KEYS[0][1], "Defence": SK_KEYS[1][1], "Skating & physical": SK_KEYS[2][1], "Mental": SK_KEYS[3][1]}
    gk = {"Goaltending": G_KEYS[0][1]}
    p = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
    use = gk if p and p[0] == "G" else groups
    rows = []
    if _has(conn, "attribute_history"):
        rows = [dict(r) for r in conn.execute("SELECT * FROM attribute_history WHERE player_id=? ORDER BY season_start_year", (pid,))]
    cur = conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone()
    pts = []
    mean = lambda r, ks: round(sum((r.get(k) or 10) for k in ks) / len(ks), 2)
    for r in rows:
        pts.append(dict(label=f"{r['season_start_year']}-{(r['season_start_year'] + 1) % 100:02d}", **{g: mean(r, ks) for g, ks in use.items()}))
    if cur:
        pts.append(dict(label="now", **{g: mean(dict(cur), ks) for g, ks in use.items()}))
    return dict(groups=list(use), points=pts, focus=TR.focus_of(conn, pid),
                focus_options=list(TR.GOALIE_FOCUS if p and p[0] == "G" else TR.SKATER_FOCUS), wild=TR.is_wild(pid))
