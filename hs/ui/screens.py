"""Phase A (v31): the depth of the screens. Read-only views over data the game already keeps.

* strip: your games from yesterday into next week (the header's schedule strip) and what today is (the Continue
  button names it)
* league_day: every game in the league on a day, with scores, and the day's news
* transactions_hub: free agents, upcoming free agents, the trade block, waivers, offer sheets, the injured, your
  short list
* depth_chart: an organisation by position (NHL, minors, unsigned rights) and its future picks
* txn_log: transactions by season and club
* milestones: players close to career marks, and marks reached this season
* reports: injury report, positional rankings, prospect rankings, game performances, morale
* draft_log: past drafts, with what became of each pick
* season_page: one season of league history (standings, champion, awards, leaders)
* rules_view: the league's rules in one place
* team_info: a club's people and set-up
* notes_view: the notebook and short list
"""
from __future__ import annotations

import datetime
import json

from ..game import contracts as K
from ..game import roster as R
from ..game.state import get_state, user_team
from ..schema import top_league_sql


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


def _today(conn):
    return datetime.date.fromisoformat(get_state(conn)[0])


def _age(birth, on):
    b = datetime.date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def _abbr(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}


def _name(r):
    return f"{r['first_name']} {r['last_name']}"


def _top_ids(conn):
    return {r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")}


def _top_league(conn):
    return conn.execute("SELECT league_id FROM leagues ORDER BY COALESCE(level, 1), league_id LIMIT 1").fetchone()[0]


def _values(conn, where="1=1", args=()):
    """{pid: (value, position, birth)} for many players in one query (age-adjusted like roster.player_value)."""
    on = _today(conn)
    out = {}
    for p in conn.execute(f"SELECT p.player_id, p.position, p.birth_date, a.* FROM players p JOIN player_attributes a USING (player_id) "
                          f"WHERE {where}", args):
        base = R.value_from_attrs({k: p[k] for k in p.keys()}, p["position"])
        out[p["player_id"]] = (round(max(0.0, base * R.age_factor(_age(p["birth_date"], on)))), p["position"], p["birth_date"])
    return out


# ---------------------------------------------------------------- the header strip and the Continue button
def strip(conn):
    me = user_team(conn)
    today = _today(conn)
    ab = _abbr(conn)
    lo, hi = (today - datetime.timedelta(days=1)).isoformat(), (today + datetime.timedelta(days=6)).isoformat()
    days = []
    games = {r["game_date"]: r for r in conn.execute(
        "SELECT * FROM games WHERE (home_team_id=? OR away_team_id=?) AND game_date BETWEEN ? AND ? ORDER BY game_date",
        (me, me, lo, hi))}
    for k in range(-1, 7):
        d = (today + datetime.timedelta(days=k)).isoformat()
        g = games.get(d)
        x = dict(date=d, today=k == 0, past=k < 0)
        if g:
            home = g["home_team_id"] == me
            x.update(game_id=g["game_id"], opp=ab[g["away_team_id"] if home else g["home_team_id"]], home=home, type=g["game_type"])
            if g["played"]:
                mine, theirs = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
                x["result"] = ("W" if mine > theirs else "OTL" if g["went_to_ot"] else "L") + f" {mine}-{theirs}"
        days.append(x)
    return dict(days=days, event=today_event(conn, games.get(today.isoformat())))


def today_event(conn, game=None):
    """What today is, for the Continue button: a game, the deadline, a draft, an offseason phase."""
    phase = K.season_state(conn)
    today = _today(conn)
    if phase != "regular_season":
        return {"finished": "Season over", "draft": "Draft day", "rights": "Re-signing", "free_agency": "Free agency",
                "arbitration": "Arbitration", "awards": "Awards", "preseason": "Training camp",
                "playoffs": "Playoffs"}.get(phase, phase.replace("_", " ").title())
    try:
        from ..game import trades as TR
        if TR.deadline(conn) == today:
            return "Trade deadline day"
    except Exception:
        pass
    if game:
        ab = _abbr(conn)
        me = user_team(conn)
        home = game["home_team_id"] == me
        return f"{'Playoff game' if game['game_type'] == 'PO' else 'Game'} {'vs' if home else 'at'} {ab[game['away_team_id'] if home else game['home_team_id']]}"
    last = conn.execute("SELECT MAX(game_date) FROM games WHERE game_type='RS'").fetchone()[0]
    if last == today.isoformat():
        return "Last day of the regular season"
    return None


def play_targets(conn):
    """Dates to play until (Play > Play until): the deadline, the first of each coming month, the last regular-season day."""
    today = _today(conn)
    out = []
    try:
        from ..game import trades as TR
        dl = TR.deadline(conn)
        if dl and dl > today:
            out.append(dict(date=(dl - datetime.timedelta(days=3)).isoformat(), label="Three days before the trade deadline"))
            out.append(dict(date=dl.isoformat(), label="Trade deadline day"))
    except Exception:
        pass
    last = conn.execute("SELECT MAX(game_date) FROM games WHERE game_type='RS'").fetchone()[0]
    if last:
        end = datetime.date.fromisoformat(last)
        m = datetime.date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        while m < end and len(out) < 12:
            out.append(dict(date=m.isoformat(), label=m.strftime("1 %B")))
            m = datetime.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        if end > today:
            out.append(dict(date=end.isoformat(), label="Last day of the regular season"))
    me = user_team(conn)
    nxt = conn.execute("SELECT game_date FROM games WHERE played=0 AND (home_team_id=? OR away_team_id=?) AND game_date>? "
                       "ORDER BY game_date LIMIT 1 OFFSET 4", (me, me, today.isoformat())).fetchone()
    if nxt:
        out.append(dict(date=nxt[0], label="Your fifth game from now"))
    return sorted(out, key=lambda x: x["date"])


# ---------------------------------------------------------------- the league, day by day
def league_day(conn, day=None):
    today = get_state(conn)[0]
    day = (day or today)[:10]
    ab = _abbr(conn)
    top = _top_ids(conn)
    me = user_team(conn)
    games = []
    for g in conn.execute("SELECT * FROM games WHERE game_date=? ORDER BY game_id", (day,)):
        if g["home_team_id"] not in top:
            continue
        x = dict(game_id=g["game_id"], home=ab[g["home_team_id"]], away=ab[g["away_team_id"]], home_id=g["home_team_id"],
                 away_id=g["away_team_id"], type=g["game_type"], played=bool(g["played"]), mine=me in (g["home_team_id"], g["away_team_id"]))
        if g["played"]:
            x.update(hg=g["home_goals"], ag=g["away_goals"], ot={1: "OT", 2: "SO"}.get(g["went_to_ot"] or 0, ""))
            star = conn.execute("SELECT p.player_id, p.first_name, p.last_name, s.goals, s.assists FROM player_game_stats s JOIN players p "
                                "USING (player_id) WHERE s.game_id=? ORDER BY s.goals*2+s.assists DESC, s.goals DESC LIMIT 1",
                                (g["game_id"],)).fetchone()
            if star and (star["goals"] or star["assists"]):
                x["star"] = dict(player_id=star["player_id"], name=_name(star), g=star["goals"], a=star["assists"])
        games.append(x)
    prev = conn.execute("SELECT MAX(game_date) FROM games WHERE game_date<?", (day,)).fetchone()[0]
    nxt = conn.execute("SELECT MIN(game_date) FROM games WHERE game_date>?", (day,)).fetchone()[0]
    news = [dict(event_id=e["event_id"], text=e["summary"], type=e["event_type"]) for e in conn.execute(
        "SELECT * FROM league_events WHERE event_date=? AND importance>=2 AND event_type<>'GAME_RESULT' ORDER BY importance DESC, event_id LIMIT 15", (day,))]
    return dict(day=day, today=today, games=games, prev=prev, next=nxt, news=news)


# ---------------------------------------------------------------- transactions hub
HUB_TABS = ("free", "upcoming", "block", "waivers", "sheets", "injured", "shortlist")


def transactions_hub(conn, tab="free", team=None):
    out_ = _transactions_hub(conn, tab)
    out_["clubs"] = [dict(team_id=r[0], abbr=r[1]) for r in conn.execute(f"SELECT team_id, abbr FROM teams WHERE {top_league_sql()} ORDER BY abbr")]
    if team:                                          # v38 (#12): one club at a time
        t = int(team)
        ab = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()
        ab = ab[0] if ab else None
        out_["rows"] = [r for r in out_["rows"] if r.get("team_id") == t or r.get("team") == ab or r.get("holding") == ab or r.get("offering") == ab]
        out_["team"] = t
    return out_


def _transactions_hub(conn, tab="free"):
    tab = tab if tab in HUB_TABS else "free"
    ab = _abbr(conn)
    on = _today(conn)
    year = K.signing_year(conn)
    out = dict(tab=tab, tabs=list(HUB_TABS), rows=[])
    rows = out["rows"]
    if tab == "free":
        for v, pid, pos in R.free_agents(conn)[:150]:
            p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
            try:
                ask = K.asking(conn, pid, "UFA")
            except Exception:
                ask = None
            rows.append(dict(player_id=pid, name=_name(p), pos=pos, age=_age(p["birth_date"], on), value=round(v), ask=ask))
    elif tab == "upcoming":
        top = _top_ids(conn)
        vals = _values(conn, f"p.team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()}) AND p.status IN ('active','injured','ltir')")
        for c in conn.execute("SELECT c.*, p.first_name, p.last_name, p.birth_date FROM contracts c JOIN players p USING (player_id) "
                              "WHERE c.start_year+c.years-1=? AND p.status IN ('active','injured','ltir')", (year,)):
            if c["team_id"] not in top or c["player_id"] not in vals:
                continue
            try:
                status = K.rights_status(conn, c["player_id"], year)
            except Exception:
                status = ""
            v, pos, _ = vals[c["player_id"]]
            rows.append(dict(player_id=c["player_id"], name=_name(c), pos=pos, age=_age(c["birth_date"], on), team=ab.get(c["team_id"]),
                             team_id=c["team_id"], cap_hit=c["cap_hit"], status=status, value=v))
        rows.sort(key=lambda r: -r["value"])
        del rows[200:]
    elif tab == "block":
        if _has(conn, "trade_block"):
            for r in conn.execute("SELECT b.since, p.* FROM trade_block b JOIN players p USING (player_id) ORDER BY b.since DESC"):
                c = K.current_contract(conn, r["player_id"], year)
                rows.append(dict(player_id=r["player_id"], name=_name(r), pos=r["position"], age=_age(r["birth_date"], on),
                                 team=ab.get(r["team_id"]), team_id=r["team_id"], since=r["since"],
                                 cap_hit=c["cap_hit"] if c else None, value=round(R.player_value(conn, r["player_id"]))))
    elif tab == "waivers":
        if _has(conn, "waivers"):
            for r in conn.execute("SELECT w.*, p.first_name, p.last_name, p.position, p.birth_date FROM waivers w JOIN players p USING (player_id) "
                                  "ORDER BY w.resolved IS NOT NULL, w.placed DESC LIMIT 120"):
                rows.append(dict(player_id=r["player_id"], name=_name(r), pos=r["position"], age=_age(r["birth_date"], on),
                                 team=ab.get(r["team_id"]), placed=r["placed"], clears=r["clears"], outcome=r["outcome"] or "on waivers",
                                 claimed_by=ab.get(r["claimed_by"]), open=r["resolved"] is None))
    elif tab == "sheets":
        if _has(conn, "offer_sheets"):
            cols = [x[1] for x in conn.execute("PRAGMA table_info(offer_sheets)")]
            for r in conn.execute("SELECT * FROM offer_sheets ORDER BY rowid DESC LIMIT 60"):
                d = dict(zip(cols, r))
                pid = d.get("player_id")
                p = conn.execute("SELECT first_name, last_name, position FROM players WHERE player_id=?", (pid,)).fetchone()
                rows.append(dict(player_id=pid, name=_name(p) if p else "?", pos=p["position"] if p else "",
                                 offering=ab.get(d.get("from_team")), holding=ab.get(d.get("owner_team")), made_on=d.get("made_on"), comp=d.get("comp"),
                                 aav=d.get("aav") or d.get("cap_hit"), years=d.get("years"), status=d.get("status") or d.get("outcome")))
    elif tab == "injured":
        top = _top_ids(conn)
        for r in conn.execute("SELECT p.*, i.start_date, i.expected_return, i.description FROM players p JOIN injuries i USING (player_id) "
                              "WHERE p.status IN ('injured','ltir') AND i.expected_return>=? ORDER BY i.expected_return DESC", (on.isoformat(),)):
            if r["team_id"] not in top:
                continue
            rows.append(dict(player_id=r["player_id"], name=_name(r), pos=r["position"], team=ab.get(r["team_id"]), team_id=r["team_id"],
                             injury=r["description"], since=r["start_date"], back=r["expected_return"], ltir=r["status"] == "ltir",
                             days=(datetime.date.fromisoformat(r["expected_return"]) - on).days))
        seen, uniq = set(), []
        for r in rows:
            if r["player_id"] not in seen:
                seen.add(r["player_id"])
                uniq.append(r)
        out["rows"] = sorted(uniq, key=lambda r: r["back"])
    elif tab == "shortlist":
        out["rows"] = shortlist_rows(conn)
    return out


def shortlist_rows(conn):
    from ..game import notes as N
    from ..game.world import where_is
    ab = _abbr(conn)
    on = _today(conn)
    year = K.signing_year(conn)
    out = []
    for s in N.shortlist(conn):
        p = conn.execute("SELECT * FROM players WHERE player_id=?", (s["player_id"],)).fetchone()
        if p is None:
            continue
        c = K.current_contract(conn, p["player_id"], year)
        out.append(dict(player_id=p["player_id"], name=_name(p), pos=p["position"], age=_age(p["birth_date"], on),
                        team=ab.get(p["team_id"]) or where_is(conn, p["player_id"]), team_id=p["team_id"], status=p["status"],
                        cap_hit=c["cap_hit"] if c else None, ends=c["start_year"] + c["years"] - 1 if c else None,
                        value=round(R.player_value(conn, p["player_id"])), added=s["added"], reason=s["reason"]))
    return out


# ---------------------------------------------------------------- depth chart
def depth_chart(conn, team_id=None):
    me = user_team(conn)
    t = int(team_id) if team_id else me
    on = _today(conn)
    year = K.signing_year(conn)
    from ..game.world import where_is
    pot = {r[0]: r[1] for r in conn.execute("SELECT player_id, potential FROM player_dev")} if _has(conn, "player_dev") else {}
    cols = {k: [] for k in ("C", "LW", "RW", "D", "G")}

    def add(p, level):
        pos = p["position"] if p["position"] in cols else ("C" if p["position"] in ("F",) else "D")
        c = K.current_contract(conn, p["player_id"], year)
        cols.setdefault(pos, []).append(dict(player_id=p["player_id"], name=_name(p), age=_age(p["birth_date"], on), level=level,
                                             value=round(R.player_value(conn, p["player_id"])), potential=pot.get(p["player_id"]),
                                             cap_hit=c["cap_hit"] if c else None, ends=c["start_year"] + c["years"] - 1 if c else None,
                                             club=where_is(conn, p["player_id"]) if level != "NHL" else None))
    for p in conn.execute("SELECT * FROM players WHERE team_id=? AND status IN ('active','injured','ltir','prospect')", (t,)):
        add(p, "NHL" if p["status"] != "prospect" else "Minors")
    if _has(conn, "draft_rights"):
        for p in conn.execute("SELECT p.* FROM draft_rights r JOIN players p USING (player_id) WHERE r.team_id=? AND "
                              "p.player_id NOT IN (SELECT player_id FROM contracts WHERE team_id=?)", (t, t)):
            add(p, "Rights")
    order = {"NHL": 0, "Minors": 1, "Rights": 2}
    for k in cols:
        cols[k].sort(key=lambda x: (order[x["level"]], -x["value"]))
    picks = []
    try:
        from ..game import gm_trades as GT
        from ..game import trades as T
        for kind, a in GT.assets_of(conn, t):
            if kind == "pick":
                y, rnd, orig = a
                picks.append(dict(year=y, round=rnd, label=T.pick_label(conn, y, rnd, orig, t)))
    except Exception:
        pass
    tm = conn.execute("SELECT abbr, name, nickname FROM teams WHERE team_id=?", (t,)).fetchone()
    return dict(team_id=t, abbr=tm["abbr"], name=f"{tm['name']} {tm['nickname'] or ''}".strip(), columns=cols, picks=picks,
                order=["G", "D", "LW", "C", "RW"], pick_grid=pick_grid(conn, t))


def pick_grid(conn, t, years=3):
    """v38 (#7, #11): a club's picks as a grid, draft by draft and round by round: its own pick (or who has it now),
    and the picks it holds from other clubs. Swaps and conditions are noted where the save has them."""
    from ..game import trades as T
    from ..game.draft import draft_year
    y0 = draft_year(conn)
    started = {r[0] for r in conn.execute("SELECT DISTINCT draft_year FROM draft_picks")} if _has(conn, "draft_picks") else set()
    ys = [y for y in range(y0, y0 + years + 1) if y not in started][:years]
    moved = {(r[0], r[1], r[2]): r[3] for r in conn.execute(
        "SELECT draft_year, round, original_team_id, owner_team_id FROM draft_pick_owners")} if _has(conn, "draft_pick_owners") else {}
    ab = lambda x: (conn.execute("SELECT abbr FROM teams WHERE team_id=?", (x,)).fetchone() or ["?"])[0]
    swaps = {}
    if _has(conn, "pick_swaps"):
        for r in conn.execute("SELECT * FROM pick_swaps"):
            d = dict(r)
            swaps[(d.get("draft_year"), d.get("round"))] = d
    rows = []
    for y in ys:
        cells = []
        for rnd in range(1, 8):
            own_owner = moved.get((y, rnd, t), t)
            extra = [ab(o) for (yy, rr, o), owner in moved.items() if yy == y and rr == rnd and owner == t and o != t]
            sw = swaps.get((y, rnd))
            cells.append(dict(round=rnd, own=own_owner == t, to=None if own_owner == t else ab(own_owner), extra=extra,
                              swap=bool(sw and t in (sw.get("team_a"), sw.get("team_b")))))
        rows.append(dict(year=y, cells=cells))
    return rows


# ---------------------------------------------------------------- transaction log by season
TXN_LABEL = {"trade": "Trade", "sign": "Signing", "signed": "Signing", "release": "Release", "draft": "Draft", "recall": "Recall",
             "assign": "Assignment", "injury": "Injury", "return": "Return", "waiver": "Waivers", "claim": "Waiver claim",
             "retire": "Retirement", "buyout": "Buyout", "elc": "Entry-level", "waivers": "Waivers", "club": "Minor / European club",
             "graduate": "Junior graduate", "contract": "Contract", "arbitration": "Arbitration"}


def txn_log(conn, season=None, team=None, kind="", minor=False):
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT start_year FROM seasons ORDER BY start_year DESC")]
    season = int(season) if season else K.season_year(conn)
    lo, hi = f"{season}-07-01", f"{season + 1}-06-30"
    ab = _abbr(conn)
    me = user_team(conn)
    t = None if team in (None, "", "all") else (me if team == "mine" else int(team))
    q = "SELECT x.*, p.first_name, p.last_name, p.position FROM transactions x LEFT JOIN players p USING (player_id) WHERE x.txn_date BETWEEN ? AND ?"
    a = [lo, hi]
    if t:
        q += " AND (x.from_team_id=? OR x.to_team_id=?)"
        a += [t, t]
    if kind:
        q += " AND x.txn_type=?"
        a.append(kind)
    elif not minor:                                   # minor-league and European club moves only when asked for
        lg = _top_league(conn)
        top = f"SELECT team_id FROM teams WHERE {top_league_sql()}"
        q += (f" AND x.txn_type NOT IN ('club', 'graduate') AND (x.from_team_id IN ({top}) OR x.to_team_id IN ({top}) OR "
              f"x.player_id IN (SELECT player_id FROM skater_season_stats WHERE league_id={lg} UNION "
              f"SELECT player_id FROM goalie_season_stats WHERE league_id={lg}))")
    rows = [dict(date=r["txn_date"], type=r["txn_type"], label=TXN_LABEL.get(r["txn_type"], (r["txn_type"] or "").title()),
                 player_id=r["player_id"], name=_name(r) if r["first_name"] else "", pos=r["position"],
                 frm=ab.get(r["from_team_id"]) if r["from_team_id"] != r["to_team_id"] else None, to=ab.get(r["to_team_id"]), detail=r["detail"])
            for r in conn.execute(q + " ORDER BY x.txn_date DESC, x.txn_id DESC LIMIT 600", a)]
    kinds = [r[0] for r in conn.execute("SELECT DISTINCT txn_type FROM transactions ORDER BY txn_type")]
    return dict(season=season, seasons=seasons or [season], team=team or "all", kind=kind, kinds=kinds,
                kind_labels={k: TXN_LABEL.get(k, (k or "").title()) for k in kinds}, minor=bool(minor), rows=rows)


# ---------------------------------------------------------------- milestones
SKATER_MARKS = {"gp": [500, 750, 1000, 1250, 1500], "g": [100, 200, 300, 400, 500, 600, 700, 800],
                "a": [200, 300, 400, 500, 600, 700, 800, 1000], "pts": [250, 500, 750, 1000, 1250, 1500]}
GOALIE_MARKS = {"gp": [300, 500, 750, 1000], "w": [100, 200, 300, 400, 500], "so": [25, 50, 75, 100]}
NEAR = {"gp": 25, "g": 10, "a": 15, "pts": 20, "w": 10, "so": 3}
LABEL = {"gp": "games", "g": "goals", "a": "assists", "pts": "points", "w": "wins", "so": "shutouts"}


def career_totals(conn):
    """Top-league careers of active players: recorded seasons plus this season's games so far."""
    lg = _top_league(conn)
    year = K.season_year(conn)
    rec_years = {r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM skater_season_stats WHERE league_id=?", (lg,))}
    sk, gk = {}, {}
    for r in conn.execute("SELECT player_id, SUM(gp), SUM(g), SUM(a) FROM skater_season_stats WHERE league_id=? AND split='RS' GROUP BY player_id", (lg,)):
        sk[r[0]] = dict(gp=r[1] or 0, g=r[2] or 0, a=r[3] or 0)
    for r in conn.execute("SELECT player_id, SUM(gp), SUM(w), SUM(so) FROM goalie_season_stats WHERE league_id=? AND split='RS' GROUP BY player_id", (lg,)):
        gk[r[0]] = dict(gp=r[1] or 0, w=r[2] or 0, so=r[3] or 0)
    from ..game import career as CR                # v41: careers before the save began
    for pid, p in CR.all_prior(conn).items():
        if p["w"] or p["so"] or pid in gk:
            x = gk.setdefault(pid, dict(gp=0, w=0, so=0))
            for k in ("gp", "w", "so"):
                x[k] += p[k] or 0
        else:
            x = sk.setdefault(pid, dict(gp=0, g=0, a=0))
            for k in ("gp", "g", "a"):
                x[k] += p[k] or 0
    now_sk, now_gk = {}, {}
    if year not in rec_years:
        sid = conn.execute("SELECT season_id FROM seasons WHERE start_year=? AND league_id=?", (year, lg)).fetchone()
        if sid:
            for r in conn.execute("SELECT s.player_id, COUNT(*), SUM(s.goals), SUM(s.assists), SUM(s.shots_against) FROM player_game_stats s JOIN games g "
                                  "USING (game_id) WHERE g.season_id=? AND g.game_type='RS' GROUP BY s.player_id", (sid[0],)):
                now_sk[r[0]] = dict(gp=r[1], g=r[2] or 0, a=r[3] or 0)
            for r in conn.execute("SELECT s.player_id, COUNT(*), SUM(CASE WHEN (g.home_team_id=s.team_id AND g.home_goals>g.away_goals) OR "
                                  "(g.away_team_id=s.team_id AND g.away_goals>g.home_goals) THEN 1 ELSE 0 END), "
                                  "SUM(CASE WHEN (g.home_team_id=s.team_id AND g.away_goals=0) OR (g.away_team_id=s.team_id AND g.home_goals=0) THEN 1 ELSE 0 END) "
                                  "FROM player_game_stats s JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE g.season_id=? "
                                  "AND g.game_type='RS' AND p.position='G' AND s.shots_against>0 GROUP BY s.player_id", (sid[0],)):
                now_gk[r[0]] = dict(gp=r[1], w=r[2] or 0, so=r[3] or 0)
    return sk, gk, now_sk, now_gk


def milestones(conn):
    sk, gk, now_sk, now_gk = career_totals(conn)
    ab = _abbr(conn)
    near, reached = [], []
    top = _top_ids(conn)
    for p in conn.execute("SELECT * FROM players WHERE status IN ('active','injured','ltir')"):
        if p["team_id"] not in top:
            continue
        goalie = p["position"] == "G"
        base, now, marks = (gk, now_gk, GOALIE_MARKS) if goalie else (sk, now_sk, SKATER_MARKS)
        b = dict(base.get(p["player_id"]) or {})
        n = now.get(p["player_id"]) or {}
        tot = {k: (b.get(k) or 0) + (n.get(k) or 0) for k in marks if k != "pts"}
        before = {k: (b.get(k) or 0) for k in tot}
        if not goalie:
            tot["pts"], before["pts"] = tot["g"] + tot["a"], before["g"] + before["a"]
        for k, ms in marks.items():
            for m in ms:
                if before[k] < m <= tot[k]:
                    reached.append(dict(player_id=p["player_id"], name=_name(p), team=ab.get(p["team_id"]), stat=LABEL[k], mark=m, total=tot[k]))
                elif 0 < m - tot[k] <= NEAR[k]:
                    near.append(dict(player_id=p["player_id"], name=_name(p), team=ab.get(p["team_id"]), stat=LABEL[k], mark=m,
                                     total=tot[k], to_go=m - tot[k]))
                    break
    near.sort(key=lambda x: (x["to_go"] / NEAR[[k for k, v in LABEL.items() if v == x["stat"]][0]], -x["mark"]))
    reached.sort(key=lambda x: -x["mark"])
    return dict(near=near[:80], reached=reached[:80])


# ---------------------------------------------------------------- reports
REPORTS = ("injuries", "positional", "prospects", "performances", "morale")


def reports(conn, kind="positional"):
    kind = kind if kind in REPORTS else "positional"
    ab = _abbr(conn)
    on = _today(conn)
    out = dict(kind=kind, kinds=list(REPORTS))
    if kind == "injuries":
        out["rows"] = transactions_hub(conn, "injured")["rows"]
    elif kind == "positional":
        vals = _values(conn, f"p.team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()}) AND p.status IN ('active','injured','ltir')")
        team = {r[0]: r[1] for r in conn.execute("SELECT player_id, team_id FROM players WHERE player_id IN (%s)" % ",".join(map(str, vals)) )} if vals else {}
        names = {r[0]: f"{r[1]} {r[2]}" for r in conn.execute("SELECT player_id, first_name, last_name FROM players WHERE player_id IN (%s)" % ",".join(map(str, vals)))} if vals else {}
        groups = {}
        for pid, (v, pos, birth) in vals.items():
            groups.setdefault(pos, []).append(dict(player_id=pid, name=names[pid], team=ab.get(team.get(pid)), team_id=team.get(pid),
                                                   value=v, age=_age(birth, on)))
        out["groups"] = {k: sorted(v, key=lambda x: -x["value"])[:15] for k, v in groups.items() if k in ("C", "LW", "RW", "D", "G")}
        me = user_team(conn)
        out["mine"] = {k: next((i + 1 for i, x in enumerate(sorted(v, key=lambda x: -x["value"])) if x["team_id"] == me), None)
                       for k, v in groups.items()}
    elif kind == "prospects":
        pot = {r[0]: r[1] for r in conn.execute("SELECT player_id, potential FROM player_dev")} if _has(conn, "player_dev") else {}
        from ..game.world import where_is
        rows = []
        vals = _values(conn, "p.status IN ('prospect','active') AND p.birth_date>?", ((on - datetime.timedelta(days=int(365.25 * 22))).isoformat(),))
        rights = {r[0]: r[1] for r in conn.execute("SELECT player_id, team_id FROM draft_rights")} if _has(conn, "draft_rights") else {}
        top = _top_ids(conn)
        for pid, (v, pos, birth) in vals.items():
            p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
            owner = p["team_id"] if p["team_id"] in top else rights.get(pid)
            if owner is None:
                continue
            score = (pot.get(pid) or 10) * 4 + v * 0.35
            rows.append(dict(player_id=pid, name=_name(p), pos=pos, age=_age(birth, on), owner=ab.get(owner), team_id=owner,
                             value=v, potential=pot.get(pid), score=round(score, 1), nhl=p["status"] == "active" and p["team_id"] in top,
                             club=None if p["status"] == "active" and p["team_id"] in top else where_is(conn, pid)))
        out["rows"] = sorted(rows, key=lambda x: -x["score"])[:100]
        for i, r in enumerate(out["rows"]):
            r["rank"] = i + 1
    elif kind == "performances":
        sid = conn.execute("SELECT season_id FROM seasons WHERE start_year=? AND league_id=?", (K.season_year(conn), _top_league(conn))).fetchone()
        rows, grows = [], []
        if sid:
            for r in conn.execute("SELECT s.*, g.game_date, g.home_team_id, g.away_team_id, p.first_name, p.last_name, p.position FROM player_game_stats s "
                                  "JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND p.position<>'G' "
                                  "ORDER BY s.goals*2+s.assists DESC, s.goals DESC, s.shots DESC LIMIT 25", (sid[0],)):
                opp = r["away_team_id"] if r["team_id"] == r["home_team_id"] else r["home_team_id"]
                rows.append(dict(game_id=r["game_id"], date=r["game_date"], player_id=r["player_id"], name=_name(r), team=ab.get(r["team_id"]),
                                 opp=ab.get(opp), g=r["goals"], a=r["assists"], pts=r["goals"] + r["assists"], sog=r["shots"]))
            for r in conn.execute("SELECT s.*, g.game_date, g.home_team_id, g.away_team_id, p.first_name, p.last_name FROM player_game_stats s "
                                  "JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND p.position='G' "
                                  "AND s.shots_against>=20 ORDER BY s.saves DESC, (s.shots_against-s.saves) LIMIT 15", (sid[0],)):
                opp = r["away_team_id"] if r["team_id"] == r["home_team_id"] else r["home_team_id"]
                grows.append(dict(game_id=r["game_id"], date=r["game_date"], player_id=r["player_id"], name=_name(r), team=ab.get(r["team_id"]),
                                  opp=ab.get(opp), sv=r["saves"], sa=r["shots_against"], pct=round(r["saves"] / r["shots_against"], 3)))
        out["skaters"], out["goalies"] = rows, grows
    elif kind == "morale":
        me = user_team(conn)
        rows = []
        if _has(conn, "morale"):
            for r in conn.execute("SELECT m.*, p.first_name, p.last_name, p.position FROM morale m JOIN players p USING (player_id) "
                                  "WHERE p.team_id=? AND p.status IN ('active','injured','ltir') ORDER BY m.morale", (me,)):
                rows.append(dict(player_id=r["player_id"], name=_name(r), pos=r["position"], morale=round(r["morale"]),
                                 role=round(r["role"]), team=round(r["team"]), contract=round(r["contract"]),
                                 trust_mgmt=round(r["trust_mgmt"]), trust_coach=round(r["trust_coach"]),
                                 trade_request=bool(r["trade_request"])))
        room = conn.execute("SELECT * FROM team_room WHERE team_id=?", (me,)).fetchone() if _has(conn, "team_room") else None
        out["rows"] = rows
        out["room"] = dict(cohesion=round(room["cohesion"]), atmosphere=room["atmosphere"],
                           leadership=round(room["leadership_strength"])) if room else None
    return out


# ---------------------------------------------------------------- past drafts
def _pick_note(note):
    """The draft log's note: imported history shows only a relocated club's old name."""
    if note and note.startswith("history"):
        return note[9:-1] if note.startswith("history (") else None
    return note


def draft_log(conn, year=None):
    if not _has(conn, "draft_picks"):
        return dict(years=[], year=None, rows=[])
    from ..game import career as CR
    CR.ensure_draft_names(conn)
    years = [r[0] for r in conn.execute("SELECT DISTINCT draft_year FROM draft_picks d WHERE player_id IS NOT NULL OR EXISTS (SELECT 1 FROM "
                                        "past_draft_names n WHERE n.draft_year=d.draft_year AND n.overall=d.overall) ORDER BY draft_year DESC")]
    if not years:
        return dict(years=[], year=None, rows=[])
    year = int(year) if year and int(year) in years else years[0]
    ab = _abbr(conn)
    lg = _top_league(conn)
    gp = {r[0]: r[1] for r in conn.execute("SELECT player_id, SUM(gp) FROM skater_season_stats WHERE league_id=? AND split='RS' GROUP BY player_id", (lg,))}
    gp.update({r[0]: (gp.get(r[0]) or 0) + (r[1] or 0) for r in conn.execute(
        "SELECT player_id, SUM(gp) FROM goalie_season_stats WHERE league_id=? AND split='RS' GROUP BY player_id", (lg,))})
    me = user_team(conn)
    from ..game.world import where_is
    rows = []
    for r in conn.execute("SELECT d.*, p.first_name, p.last_name, p.position, p.nationality, p.status, p.team_id cur FROM draft_picks d "
                          "JOIN players p USING (player_id) WHERE d.draft_year=? ORDER BY d.overall", (year,)):
        rows.append(dict(overall=r["overall"], round=r["round"], team=ab.get(r["team_id"]), mine=r["team_id"] == me, player_id=r["player_id"],
                         name=_name(r), pos=r["position"], nat=r["nationality"], note=_pick_note(r["lottery_note"]),
                         now=ab.get(r["cur"]) if r["cur"] else (where_is(conn, r["player_id"]) if r["status"] != "retired" else "retired"),
                         nhl_gp=(gp.get(r["player_id"]) or 0) + CR.nhl_gp(conn, r["player_id"]), value=round(R.player_value(conn, r["player_id"]))))
    for r in conn.execute("SELECT d.overall, d.round, d.team_id, n.name FROM draft_picks d JOIN past_draft_names n USING (draft_year, overall) "
                          "WHERE d.draft_year=?", (year,)):           # v41: imported picks of players not in this world
        rows.append(dict(overall=r[0], round=r[1], team=ab.get(r[2]), mine=r[2] == me, player_id=None, name=r[3], pos="",
                         nat="", note="imported", now="not in this world", nhl_gp=None, value=None))
    rows.sort(key=lambda x: x["overall"])
    return dict(years=years, year=year, rows=rows)


# ---------------------------------------------------------------- league history: one season
def season_page(conn, year=None):
    if not _has(conn, "team_seasons"):
        return dict(years=[], year=None)
    lg = _top_league(conn)
    years = [r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM team_seasons WHERE league_id=? ORDER BY 1 DESC", (lg,))]
    if not years:
        return dict(years=[], year=None)
    year = int(year) if year and int(year) in years else years[0]
    ab = _abbr(conn)
    names = {r[0]: f"{r[1]} {r[2] or ''}".strip() for r in conn.execute("SELECT team_id, name, nickname FROM teams")}
    conf = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT team_id, conference, division FROM teams")}
    standings = []
    for r in conn.execute("SELECT * FROM team_seasons WHERE season_start_year=? AND league_id=? ORDER BY pts DESC, w DESC", (year, lg)):
        standings.append(dict(team_id=r["team_id"], abbr=ab.get(r["team_id"]), name=names.get(r["team_id"]), conf=conf.get(r["team_id"], ("", ""))[0],
                              div=conf.get(r["team_id"], ("", ""))[1], gp=r["gp"], w=r["w"], l=r["l"], otl=r["otl"], pts=r["pts"],
                              gf=r["gf"], ga=r["ga"], playoffs=r["playoff_text"] or ""))
    champ = max(standings, key=lambda x: (_round(conn, year, x["team_id"]), x["pts"]), default=None)
    champ = champ if champ and _round(conn, year, champ["team_id"]) >= 4 else None
    awards = []
    for r in conn.execute("SELECT a.*, p.first_name, p.last_name FROM awards a LEFT JOIN players p USING (player_id) WHERE a.season_start_year=?", (year,)):
        awards.append(dict(award=r["award"], player_id=r["player_id"], name=_name(r) if r["first_name"] else (r["detail"] or ""),
                           team=ab.get(r["team_id"]), team_id=r["team_id"], detail=r["detail"]))
    scorers = [dict(player_id=r[0], name=f"{r[1]} {r[2]}", team=ab.get(r[3]), gp=r[4], g=r[5], a=r[6], pts=r[5] + r[6]) for r in conn.execute(
        "SELECT s.player_id, p.first_name, p.last_name, s.team_id, s.gp, s.g, s.a FROM skater_season_stats s JOIN players p USING (player_id) "
        "WHERE s.season_start_year=? AND s.league_id=? AND s.split='RS' ORDER BY s.g+s.a DESC, s.g DESC LIMIT 15", (year, lg))]
    goalies = [dict(player_id=r[0], name=f"{r[1]} {r[2]}", team=ab.get(r[3]), gp=r[4], w=r[5], so=r[6],
                    sv=round(1 - r[7] / r[8], 3) if r[8] else None, gaa=round(r[7] * 3600 / r[9], 2) if r[9] else None) for r in conn.execute(
        "SELECT s.player_id, p.first_name, p.last_name, s.team_id, s.gp, s.w, s.so, s.ga, s.sa, s.toi_sec FROM goalie_season_stats s JOIN players p "
        "USING (player_id) WHERE s.season_start_year=? AND s.league_id=? AND s.split='RS' AND s.gp>=25 ORDER BY s.w DESC LIMIT 10", (year, lg))]
    return dict(years=years, year=year, standings=standings, champion=champ, awards=awards, scorers=scorers, goalies=goalies)


def _round(conn, year, t):
    r = conn.execute("SELECT playoff_round FROM team_seasons WHERE season_start_year=? AND team_id=?", (year, t)).fetchone()
    return (r[0] or 0) if r else 0


# ---------------------------------------------------------------- rules
def rules_view(conn):
    from ..league.eras import describe
    from ..league.season import db_rules
    base = db_rules(conn, base=True)
    year = K.season_year(conn)
    cr = K.crules(conn)
    lim = R.limits(conn)

    def m(k, v):
        if "pct" in k or "share" in k:
            return f"{v * 100:.0f}%" if v <= 1 else f"{v:g}%"
        return f"${v:,.0f}" if v >= 1000 else f"{v:g}"
    money = [(k.replace("_", " ").capitalize().replace("Ufa", "UFA").replace("nhl", "NHL"), m(k, v)) for k, v in cr.items() if isinstance(v, (int, float)) and not isinstance(v, bool)][:40]
    return dict(season=year, this=describe(base, year), next=describe(base, year + 1), era=base.get("era_preset") or "none",
                cap=money, roster=_roster_rules(lim))


def _roster_rules(lim):
    lo, hi = lim
    out = []
    for label, d in (("Fewest", lo), ("Most", hi)):
        if isinstance(d, dict):
            out += [(f"{label} {k}", v) for k, v in d.items()]
        else:
            out.append((f"{label} players", d))
    return out


# ---------------------------------------------------------------- team info
def team_info(conn, team_id):
    t = conn.execute("SELECT * FROM teams WHERE team_id=?", (team_id,)).fetchone()
    if t is None:
        raise ValueError("No such club.")
    me = user_team(conn)
    lg = conn.execute("SELECT name, abbr FROM leagues WHERE league_id=?", (t["league_id"],)).fetchone()
    out = dict(team_id=team_id, name=f"{t['name']} {t['nickname'] or ''}".strip(), abbr=t["abbr"], league=lg["name"] if lg else "",
               conference=t["conference"], division=t["division"], colours=[t["primary_color"], t["secondary_color"]], mine=team_id == me)
    out["affiliates"] = [dict(team_id=r[0], name=f"{r[1]} {r[2] or ''}".strip(), league=r[3]) for r in conn.execute(
        "SELECT t.team_id, t.name, t.nickname, l.abbr FROM teams t JOIN leagues l USING (league_id) WHERE t.parent_team_id=?", (team_id,))]
    if t["parent_team_id"]:
        p = conn.execute("SELECT team_id, name, nickname FROM teams WHERE team_id=?", (t["parent_team_id"],)).fetchone()
        out["parent"] = dict(team_id=p[0], name=f"{p[1]} {p[2] or ''}".strip()) if p else None
    if _has(conn, "owners"):
        o = conn.execute("SELECT * FROM owners WHERE team_id=?", (team_id,)).fetchone()
        if o:
            out["owner"] = dict(name=o["name"], archetype=o["archetype"], summary=o["summary"])
    if _has(conn, "board"):
        b = conn.execute("SELECT * FROM board WHERE team_id=?", (team_id,)).fetchone()
        if b:
            out["gm"] = dict(name=b["gm_name"], since=b["gm_since"])
            if team_id == me:
                from ..game.org import label
                out["job"] = dict(confidence=round(b["confidence"]), label=label(b["confidence"]), warnings=b["warnings"])
    from ..game.staff import ROLES, ROLE_NAMES
    order = {k: i for i, (k, _) in enumerate(ROLES)}
    out["staff"] = sorted([dict(staff_id=r["staff_id"], name=r["name"], role=ROLE_NAMES.get(r["role"], r["role"].replace("_", " ")), age=r["age"],
                                k=order.get(r["role"], 99)) for r in conn.execute("SELECT * FROM staff WHERE team_id=?", (team_id,))],
                          key=lambda x: x["k"]) if _has(conn, "staff") else []
    out["leaders"] = [dict(player_id=r[0], name=f"{r[1]} {r[2]}", role=r[3]) for r in conn.execute(
        "SELECT l.player_id, p.first_name, p.last_name, l.role FROM leadership l JOIN players p USING (player_id) WHERE l.team_id=? "
        "ORDER BY l.role DESC", (team_id,))] if _has(conn, "leadership") else []
    if _has(conn, "team_room"):
        r = conn.execute("SELECT * FROM team_room WHERE team_id=?", (team_id,)).fetchone()
        if r:
            out["room"] = dict(cohesion=round(r["cohesion"]), atmosphere=r["atmosphere"], leadership=round(r["leadership_strength"]))
    yr = K.signing_year(conn)
    try:
        out["cap"] = dict(payroll=K.payroll(conn, team_id, yr), room=K.cap_room(conn, team_id, yr), ceiling=K.crules(conn)["cap_ceiling"])
    except Exception:
        pass
    if _has(conn, "media_state"):
        m = conn.execute("SELECT * FROM media_state WHERE team_id=?", (team_id,)).fetchone()
        if m:
            out["mood"] = dict(fans=round(m["fan_sentiment"]), media=round(m["media_sentiment"]), controversy=round(m["controversy"]))
    out["numbers"] = []            # retired numbers are not in the data yet (packs can add them later)
    return out


# ---------------------------------------------------------------- notes
def notes_view(conn):
    from ..game import notes as N
    ab = _abbr(conn)
    rows = []
    for n in N.notes(conn):
        p = conn.execute("SELECT first_name, last_name FROM players WHERE player_id=?", (n["player_id"],)).fetchone() if n["player_id"] else None
        rows.append(dict(n, player=_name(p) if p else None, team=ab.get(n["team_id"])))
    return dict(notes=rows, shortlist=shortlist_rows(conn))


def player_marks(conn, pid):
    """For the player screen: notes about him and whether he is on your short list."""
    from ..game import notes as N
    return dict(notes=N.notes(conn, player_id=pid), shortlisted=N.on_shortlist(conn, pid))


# ---------------------------------------------------------------- search: staff too
def staff_search(conn, q):
    q = (q or "").strip()
    if len(q) < 2 or not _has(conn, "staff"):
        return []
    ab = _abbr(conn)
    return [dict(staff_id=r[0], name=r[1], role=r[2].replace("_", " "), team=ab.get(r[3]) or "available")
            for r in conn.execute("SELECT staff_id, name, role, team_id FROM staff WHERE name LIKE ? ORDER BY team_id IS NULL, name LIMIT 8", (f"%{q}%",))]


# ---------------------------------------------------------------- CSV
def to_csv(rows, columns=None):
    """rows: list of lists (first is the header) or dicts. Returns CSV text."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    if rows and isinstance(rows[0], dict):
        columns = columns or list(rows[0].keys())
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])
    else:
        for r in rows or []:
            w.writerow(r)
    return buf.getvalue()


def _json(v):
    return json.dumps(v)


# ---------------------------------------------------------------- player search with filters (phase A2)
def player_search(conn, q):
    """The Find Players screen: any player in the world by name, position, age, league, status, nationality, value
    and cap hit. q is the request's query dict (strings)."""
    on = _today(conn)
    year = K.signing_year(conn)
    me = user_team(conn)
    ab = _abbr(conn)
    where, args = ["p.status <> 'retired'"], []
    name = (q.get("q") or "").strip()
    if name:
        where.append("(p.first_name||' '||p.last_name) LIKE ?")
        args.append(f"%{name}%")
    pos = q.get("pos") or ""
    if pos in ("C", "LW", "RW", "D", "G"):
        where.append("p.position=?")
        args.append(pos)
    elif pos == "F":
        where.append("p.position IN ('C','LW','RW')")
    nat = (q.get("nat") or "").strip().upper()
    if nat:
        where.append("p.nationality=?")
        args.append(nat)
    amin, amax = int(q.get("age_min") or 0), int(q.get("age_max") or 0)
    if amin:
        where.append("p.birth_date<=?")
        args.append(datetime.date(on.year - amin, on.month, min(on.day, 28)).isoformat())
    if amax:
        where.append("p.birth_date>?")
        args.append(datetime.date(on.year - amax - 1, on.month, min(on.day, 28)).isoformat())
    league = q.get("league") or ""
    status = q.get("status") or ""
    if league == "NHL":
        where.append(f"p.team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()}) AND p.status IN ('active','injured','ltir')")
    elif league:
        where.append("p.club_id IN (SELECT t.team_id FROM teams t JOIN leagues l USING (league_id) WHERE l.abbr=?) AND "
                     "(p.status='prospect' OR p.team_id IS NULL)")
        args.append(league)
    if status == "fa":
        where.append("p.team_id IS NULL AND p.player_id NOT IN (SELECT player_id FROM draft_rights) AND p.status<>'prospect'")
    elif status == "mine" and me:
        where.append("(p.team_id=? OR p.player_id IN (SELECT player_id FROM draft_rights WHERE team_id=?))")
        args += [me, me]
    elif status == "block" and _has(conn, "trade_block"):
        where.append("p.player_id IN (SELECT player_id FROM trade_block)")
    elif status == "expiring":
        where.append("p.player_id IN (SELECT player_id FROM contracts WHERE start_year+years-1=?)")
        args.append(K.season_year(conn))
    elif status == "rights" and _has(conn, "draft_rights"):
        where.append("p.player_id IN (SELECT player_id FROM draft_rights) AND p.player_id NOT IN (SELECT player_id FROM contracts)")
    sql = "SELECT p.player_id, p.position, p.birth_date, a.* FROM players p JOIN player_attributes a USING (player_id) WHERE " + " AND ".join(where)
    vmin = float(q.get("value_min") or 0)
    cap_max = float(q.get("cap_max") or 0) * 1e6
    pot = {r[0]: r[1] for r in conn.execute("SELECT player_id, potential FROM player_dev")} if _has(conn, "player_dev") else {}
    rows = []
    for p in conn.execute(sql + " LIMIT 6000", args):
        base = R.value_from_attrs({k: p[k] for k in p.keys()}, p["position"])
        age = _age(p["birth_date"], on)
        v = round(max(0.0, base * R.age_factor(age)))
        if v < vmin:
            continue
        rows.append((v, p["player_id"], age))
    rows.sort(key=lambda x: -x[0])
    out = []
    from ..game.world import where_is
    for v, pid, age in rows:
        if len(out) >= 200:
            break
        p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
        c = K.current_contract(conn, pid, year)
        if cap_max and c and c["cap_hit"] > cap_max:
            continue
        out.append(dict(player_id=pid, name=_name(p), pos=p["position"], age=age, nat=p["nationality"], value=v, potential=pot.get(pid),
                        team=ab.get(p["team_id"]), team_id=p["team_id"], club=None if p["team_id"] and p["status"] != "prospect" else where_is(conn, pid),
                        status=p["status"], cap_hit=c["cap_hit"] if c else None, ends=c["start_year"] + c["years"] - 1 if c else None))
    leagues = [r[0] for r in conn.execute("SELECT abbr FROM leagues ORDER BY COALESCE(level, 1), abbr")]
    nats = [r[0] for r in conn.execute("SELECT nationality, COUNT(*) n FROM players WHERE status<>'retired' AND nationality IS NOT NULL "
                                       "GROUP BY nationality ORDER BY n DESC LIMIT 30")]
    return dict(rows=out, total=len(rows), leagues=leagues, nats=nats)


# ---------------------------------------------------------------- v38 (#24): the sim centre's leaders
def sim_leaders(conn, n=5):
    """This regular season's top five in points, goals and save % (15+ games), for the sim centre's side panel."""
    sid = conn.execute("SELECT season_id FROM seasons WHERE league_id IN (SELECT league_id FROM leagues WHERE COALESCE(level,1)=1) "
                       "ORDER BY start_year DESC LIMIT 1").fetchone()
    if not sid:
        return dict(points=[], goals=[], goalies=[])
    ab = _abbr(conn)
    rows = conn.execute("SELECT s.player_id, p.first_name||' '||p.last_name n, p.position, p.team_id, COUNT(*) gp, SUM(s.goals) g, SUM(s.assists) a, "
                        "SUM(s.saves) sv, SUM(s.shots_against) sa FROM player_game_stats s JOIN games g USING (game_id) JOIN players p USING (player_id) "
                        "WHERE g.season_id=? AND g.game_type='RS' GROUP BY s.player_id", (sid[0],)).fetchall()
    sk = [r for r in rows if r["position"] != "G"]
    pts = sorted(sk, key=lambda r: (-(r["g"] + r["a"]), -r["g"], r["gp"]))[:n]
    gls = sorted(sk, key=lambda r: (-r["g"], r["gp"]))[:n]
    gk = sorted([r for r in rows if r["position"] == "G" and r["gp"] >= 15 and r["sa"]], key=lambda r: -(r["sv"] / r["sa"]))[:n]
    f = lambda r, v: dict(player_id=r["player_id"], name=r["n"], team=ab.get(r["team_id"]), value=v)
    return dict(points=[f(r, r["g"] + r["a"]) for r in pts], goals=[f(r, r["g"]) for r in gls],
                goalies=[f(r, f"{r['sv'] / r['sa']:.3f}".lstrip("0")) for r in gk])
