"""Your scouting network (phase E, v36): regions, scouts' assignments, knowledge levels A-E with decay, the watch list,
tournament trips, central scouting's lists by stage, a mock draft, pick suggestions and exceptional juniors.

Knowledge. Your club knows each draft-eligible prospect to a level, from points 0-100: A 80+, B 60+, C 40+, D 20+, E
under 20. Everyone starts at 45 (C: what every AI club sees; AI clubs keep the v13 scouting model, which is C). Each
week each of your scouts adds points to the prospects of the region he is assigned to ((his evaluation / 20) x 8 a
week; unassigned scouts spread themselves over all five regions), double for a prospect on your watch list; your
director of amateur scouting adds a third of that everywhere; and every prospect loses 6% of his points a week
(knowledge fades unless it is kept up), so a prospect's points settle at 16.7 x the weekly gain: with the default
spread (two average scouts over all regions, an average director) that is about 50, a C, like the AI clubs; two scouts
on one region take it to A there and leave the rest at D.
Your own error on a prospect is your staff's error x A 0.5, B 0.75, C 1.0, D 1.25, E 1.5 (hs/game/scouting.py, Lens).

Regions: the CHL (OHL, WHL, QMJHL), US college and junior, Sweden and Finland, the rest of Europe, Russia.

Tournaments: send a scout to the World Juniors, the Top Prospects Game, the Frozen Four, the U18 Worlds, the Memorial
Cup, the combine or the Hlinka Gretzky Cup; when it ends, every prospect he saw there (by region, age and the
league's consensus) gains 12 points (more for a better scout). One trip per scout per event.

Central scouting publishes three lists a season: preliminary (15 October), midterm (15 January) and final (15 April),
each closer to the truth than the last (its error 1.0, 0.7, 0.45 of a rating point around the league's consensus),
ranked within North American and international skaters and goalies, with A (first round), B (second or third) and C
(fourth to sixth) grades.
"""
from __future__ import annotations

import datetime
import random

from .state import add_message, get_state, user_team

REGIONS = {"chl": "CHL (OHL, WHL, QMJHL)", "usa": "US college and junior", "nordic": "Sweden and Finland",
           "europe": "Rest of Europe", "russia": "Russia"}
LEVELS = (("A", 80), ("B", 60), ("C", 40), ("D", 20), ("E", 0))
FACTOR = {"A": 0.5, "B": 0.75, "C": 1.0, "D": 1.25, "E": 1.5}
START, DECAY, RATE = 45.0, 0.06, 8.0          # knowledge settles at (weekly gain / DECAY): the default spread settles near 50
TOURNAMENTS = {  # key: (name, (month, day) start, days, regions or None for all, ages or None, consensus top-n or None)
    "wjc": ("World Junior Championship", (12, 26), 11, None, (18, 19), 80),
    "tpg": ("CHL/NHL Top Prospects Game", (1, 22), 3, ("chl",), None, None),
    "frozen4": ("NCAA Frozen Four", (4, 8), 4, ("usa",), None, None),
    "u18": ("U18 World Championship", (4, 22), 10, None, (17, 18), None),
    "memorial": ("Memorial Cup", (5, 20), 10, ("chl",), None, None),
    "combine": ("Scouting combine", (6, 1), 6, None, None, 100),
    "hlinka": ("Hlinka Gretzky Cup", (8, 1), 7, None, (17, 17), None),
}
STAGES = (("preliminary", (10, 15), 1.0), ("midterm", (1, 15), 0.7), ("final", (4, 15), 0.45))
TRIP_POINTS = 12


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS scout_knowledge (player_id INTEGER PRIMARY KEY, points REAL, seen TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS scout_assign (staff_id INTEGER PRIMARY KEY, region TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS watchlist (player_id INTEGER PRIMARY KEY, added TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS scout_trips (staff_id INTEGER, event TEXT, year INTEGER, done INTEGER DEFAULT 0, "
                 "PRIMARY KEY (staff_id, event, year))")


def level_of(points):
    for k, cut in LEVELS:
        if points >= cut:
            return k
    return "E"


def region_of(conn, pid, nationality=None):
    r = conn.execute("SELECT l.abbr FROM players p JOIN teams t ON t.team_id=p.club_id JOIN leagues l ON l.league_id=t.league_id "
                     "WHERE p.player_id=?", (pid,)).fetchone()
    if r and r[0] in ("NCAA", "USHL", "USDP", "NTDP"):
        return "usa"
    from .scouting import exposure_of
    nat = nationality or (conn.execute("SELECT nationality FROM players WHERE player_id=?", (pid,)).fetchone() or [None])[0]
    e = exposure_of(conn, pid, nat)
    return e if e in REGIONS else "europe"


def _scouts(conn, t):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return [], None
    sc = conn.execute("SELECT staff_id, name, evaluation FROM staff WHERE team_id=? AND role='SCOUT' ORDER BY staff_id", (t,)).fetchall()
    d = conn.execute("SELECT staff_id, name, evaluation FROM staff WHERE team_id=? AND role='SCOUT_DIR' LIMIT 1", (t,)).fetchone()
    return sc, d


def _pool(conn):
    from .draft import draft_year, eligible_rows
    year = draft_year(conn)
    rows = eligible_rows(conn, year)
    for x in rows:
        x["region"] = region_of(conn, x["pid"], x["nat"])
    return year, rows


def knowledge(conn):
    """{pid: points} for your club (missing = the starting 45)."""
    ensure_tables(conn)
    return {r[0]: r[1] for r in conn.execute("SELECT player_id, points FROM scout_knowledge")}


def levels(conn, pids=None):
    k = knowledge(conn)
    if pids is None:
        return {p: level_of(v) for p, v in k.items()}
    return {p: level_of(k.get(p, START)) for p in pids}


def weekly(conn, day):
    """Mondays: your scouts' week (regions, the watch list, the director), decay, finished trips, central lists."""
    ensure_tables(conn)
    me = user_team(conn)
    stage_lists(conn, day)
    exceptional(conn, day)
    if me is None:
        return
    year, pool = _pool(conn)
    if not pool:
        return
    k = knowledge(conn)
    watch = {r[0] for r in conn.execute("SELECT player_id FROM watchlist")}
    scouts, director = _scouts(conn, me)
    assign = {r[0]: r[1] for r in conn.execute("SELECT staff_id, region FROM scout_assign")}
    gain = {r: 0.0 for r in REGIONS}
    for s in scouts:
        g = RATE * (s["evaluation"] or 10) / 20
        reg = assign.get(s["staff_id"])
        if reg in gain:
            gain[reg] += g
        else:
            for r in gain:
                gain[r] += g / len(gain)
    if director:
        for r in gain:
            gain[r] += RATE * (director["evaluation"] or 10) / 20 / 3
    rows = []
    for x in pool:
        pid = x["pid"]
        cur = k.get(pid, START)
        g = gain[x["region"]] * (2.0 if pid in watch else 1.0)
        new = min(100.0, cur + g - DECAY * cur)        # knowledge fades unless it is kept up: it settles at gain / DECAY
        rows.append((pid, round(max(0.0, new), 2), day if g > 2 else None))
    conn.executemany("INSERT OR REPLACE INTO scout_knowledge VALUES (?,?,?)", rows)
    _trips(conn, day, pool, scouts + ([director] if director else []))


def _event_dates(key, year):
    name, (m, d), days, regions, ages, top = TOURNAMENTS[key]
    start = datetime.date(year, m, d)
    return start, start + datetime.timedelta(days=days)


def next_occurrence(key, today):
    for y in (today.year - 1, today.year, today.year + 1):
        s, e = _event_dates(key, y)
        if e >= today:
            return y, s, e
    return None


def send(conn, staff_id, key, day):
    ensure_tables(conn)
    me = user_team(conn)
    if key not in TOURNAMENTS:
        raise ValueError("Events: " + ", ".join(TOURNAMENTS) + ".")
    r = conn.execute("SELECT role FROM staff WHERE staff_id=? AND team_id=?", (staff_id, me)).fetchone()
    if r is None or r[0] not in ("SCOUT", "SCOUT_DIR"):
        raise ValueError("Send one of your scouts (or the director of amateur scouting).")
    y, s, e = next_occurrence(key, datetime.date.fromisoformat(day))
    conn.execute("INSERT OR IGNORE INTO scout_trips (staff_id, event, year) VALUES (?,?,?)", (staff_id, key, y))
    return TOURNAMENTS[key][0], s, e


def _trips(conn, day, pool, staff):
    today = datetime.date.fromisoformat(day)
    ev = {s["staff_id"]: s["evaluation"] or 10 for s in staff}
    from .scouting import consensus
    for staff_id, key, y in conn.execute("SELECT staff_id, event, year FROM scout_trips WHERE done=0").fetchall():
        s, e = _event_dates(key, y)
        if today < e:
            continue
        name, _, _, regions, ages, top = TOURNAMENTS[key]
        cands = [x for x in pool if (regions is None or x["region"] in regions) and (ages is None or ages[0] <= x["age"] <= ages[1])]
        if top:
            cands = sorted(cands, key=lambda x: -consensus(conn, x, y))[:top]
        pts = TRIP_POINTS * (0.6 + ev.get(staff_id, 10) / 25)
        for x in cands:
            cur = conn.execute("SELECT points FROM scout_knowledge WHERE player_id=?", (x["pid"],)).fetchone()
            conn.execute("INSERT OR REPLACE INTO scout_knowledge VALUES (?,?,?)", (x["pid"], min(100.0, (cur[0] if cur else START) + pts), day))
        conn.execute("UPDATE scout_trips SET done=1 WHERE staff_id=? AND event=? AND year=?", (staff_id, key, y))
        add_message(conn, day, f"Scouting: {name}", f"Our scout is back from the {name}: {len(cands)} draft prospects seen up close. "
                    "Their knowledge levels are up on the Scouting screen.")


def assign(conn, staff_id, region):
    ensure_tables(conn)
    me = user_team(conn)
    r = conn.execute("SELECT role FROM staff WHERE staff_id=? AND team_id=?", (staff_id, me)).fetchone()
    if r is None or r[0] != "SCOUT":
        raise ValueError("Assign one of your amateur scouts.")
    if region not in REGIONS and region != "all":
        raise ValueError("Regions: " + ", ".join(REGIONS) + ", all.")
    if region == "all":
        conn.execute("DELETE FROM scout_assign WHERE staff_id=?", (staff_id,))
    else:
        conn.execute("INSERT OR REPLACE INTO scout_assign VALUES (?,?)", (staff_id, region))


def watch(conn, pid, day, on=True):
    ensure_tables(conn)
    if on:
        conn.execute("INSERT OR REPLACE INTO watchlist VALUES (?,?)", (pid, day))
    else:
        conn.execute("DELETE FROM watchlist WHERE player_id=?", (pid,))


# ---------------------------------------------------------------- central scouting, by stage
def stage_lists(conn, day):
    """Publish the lists whose dates have come (once each per draft year)."""
    from .draft import draft_year
    import json
    year = draft_year(conn)
    d = datetime.date.fromisoformat(day)
    for name, (m, dd), noise in STAGES:
        when = datetime.date(year - 1 if m >= 7 else year, m, dd)
        if d < when:
            continue
        key = f"bureau_{year}_{name}"
        if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
            continue
        lst = _bureau(conn, year, name, noise)
        conn.execute("INSERT INTO pack_info (key, value) VALUES (?,?)", (key, json.dumps(lst)))
        if lst:
            top = next((x for x in lst if x["list"] == "North American skaters" and x["rank"] == 1), lst[0])
            from .events import emit, player_name
            hl = f"Central scouting's {name} list: {player_name(conn, top['pid'])} tops the North American skaters"
            emit(conn, "MEDIA_STORY", day, hl, player_id=top["pid"], importance=2, headline=hl, body=hl + ".", tag="draft", kind="bureau")


def _bureau(conn, year, stage, noise):
    from .draft import eligible_rows
    from .scouting import consensus
    pool = eligible_rows(conn, year)
    if not pool:
        return []
    seed = get_state(conn)[1]
    sc = {}
    for x in pool:
        rng = random.Random(f"{seed}-{year}-bureau-{stage}-{x['pid']}")
        sc[x["pid"]] = consensus(conn, x, year) + rng.gauss(0, noise)
    order = sorted(pool, key=lambda x: -sc[x["pid"]])
    overall = {x["pid"]: i + 1 for i, x in enumerate(order)}
    out, counts = [], {}
    for x in order:
        na = (x["nat"] or "") in ("CAN", "USA")
        lst = ("North American" if na else "International") + (" goalies" if x["goalie"] else " skaters")
        counts[lst] = counts.get(lst, 0) + 1
        o = overall[x["pid"]]
        grade = "A" if o <= 32 else "B" if o <= 96 else "C" if o <= 192 else ""
        if counts[lst] <= (60 if not x["goalie"] else 15):
            out.append(dict(pid=x["pid"], list=lst, rank=counts[lst], grade=grade))
    return out


def bureau_view(conn, stage=None):
    from .draft import draft_year
    import json
    year = draft_year(conn)
    have = [n for n, _, _ in STAGES if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (f"bureau_{year}_{n}",)).fetchone()]
    stage = stage if stage in have else (have[-1] if have else None)
    if not stage:
        return dict(year=year, stages=have, stage=None, lists={})
    rows = json.loads(conn.execute("SELECT value FROM pack_info WHERE key=?", (f"bureau_{year}_{stage}",)).fetchone()[0])
    from .events import player_name
    lv = levels(conn, [r["pid"] for r in rows])
    lists = {}
    for r in rows:
        lists.setdefault(r["list"], []).append(dict(r, name=player_name(conn, r["pid"]), level=lv.get(r["pid"])))
    return dict(year=year, stages=have, stage=stage, lists=lists)


# ---------------------------------------------------------------- mock draft and suggestions
def projected_order(conn):
    """The first round as it stands: the draft order if it is set, else the standings from the bottom up."""
    from .draft import draft_year
    year = draft_year(conn)
    rows = conn.execute("SELECT team_id FROM draft_picks WHERE draft_year=? AND round=1 ORDER BY overall", (year,)).fetchall()
    if rows:
        return [r[0] for r in rows]
    from ..league import standings as st
    from ..schema import top_league_sql
    sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    rec, _ = st.table(conn, sid)
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    pts = {t: ((rec.get(t) or {}).get("w", 0) * 2 + (rec.get(t) or {}).get("otl", 0)) / max(1, (rec.get(t) or {}).get("gp", 0) or 1) for t in teams}
    return sorted(teams, key=lambda t: (pts[t], t))


_MOCK = {}


def mock_draft(conn, n=32):
    """Each club, in order, takes the player its own scouts rate best for the pick (hs/game/scouting.py)."""
    from .draft import draft_year, eligible_rows
    from . import scouting as S
    key = (id(conn), get_state(conn)[0])
    if key in _MOCK:
        return _MOCK[key]
    year = draft_year(conn)
    pool = eligible_rows(conn, year)
    order = projected_order(conn)[:n]
    taken, out = set(), []
    for i, t in enumerate(order):
        lens = S.Lens(conn, t, year)
        need = S.needs(conn, t, year)
        from .roster import group
        best = max((x for x in pool if x["pid"] not in taken),
                   key=lambda x: S.pick_score(lens.view(x["pid"], x["cur"], x["age"], x["goalie"], x["nat"], x["height"]), x["cur"], 1,
                                              need[group(x["pos"])], lens.style, x["goalie"], x["age"]), default=None)
        if best is None:
            break
        taken.add(best["pid"])
        out.append(dict(pick=i + 1, team_id=t, pid=best["pid"], pos=best["pos"]))
    _MOCK.clear()
    _MOCK[key] = out
    return out


def suggestions(conn):
    """For your next first-round pick: best available, a safe pick and a risky one, from your board and the mock."""
    from .draft import board_rows
    me = user_team(conn)
    if me is None:
        return dict(slot=None, items=[])
    order = projected_order(conn)
    slot = order.index(me) + 1 if me in order else None
    mock = mock_draft(conn)
    gone = {m["pid"] for m in mock if slot and m["pick"] < slot}
    board = [r for r in board_rows(conn, me, 80) if r["pid"] not in gone]
    lv = levels(conn, [r["pid"] for r in board])
    if not board:
        return dict(slot=slot, items=[])
    items = [dict(kind="Best available", pid=board[0]["pid"], why=f"your scouts' top player likely left at #{slot}", level=lv[board[0]["pid"]])]
    safe = max([r for r in board[:20] if r["pid"] != board[0]["pid"]] or board[:20], key=lambda r: (r["cur"] - (0 if lv[r["pid"]] in "AB" else 0.4), r["proj"]))
    items.append(dict(kind="Safe pick", pid=safe["pid"], why="closest to the NHL already, and well known to your scouts" if lv[safe["pid"]] in "AB" else "closest to the NHL already", level=lv[safe["pid"]]))
    used = {items[0]["pid"], safe["pid"]}
    risky = max([r for r in board[:30] if r["pid"] not in used] or board[:30], key=lambda r: (r["proj"] - r["cur"]) + (0.3 if lv[r["pid"]] in "DE" else 0))
    items.append(dict(kind="Risky pick", pid=risky["pid"], why="the most growth left" + (", and your scouts barely know him" if lv[risky["pid"]] in "DE" else ""), level=lv[risky["pid"]]))
    return dict(slot=slot, items=items)


# ---------------------------------------------------------------- exceptional juniors
def exceptional(conn, day):
    """Once a year (from September): a 16- or 17-year-old with a ceiling of 13.6+ is granted exceptional status:
    the whole league knows him (your knowledge: A) and the press is on him from now until his draft."""
    d = datetime.date.fromisoformat(day)
    if d.month < 9:
        return
    key = f"exceptional_{d.year}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '[]')", (key,))
    on = datetime.date(d.year, 9, 15)
    rows = conn.execute("SELECT p.player_id, p.birth_date, d.potential FROM players p JOIN player_dev d USING (player_id) WHERE p.team_id IS NULL "
                        "AND p.status IN ('active','injured') AND d.potential>=13.6 AND p.birth_date>?", (f"{d.year - 18}-09-15",)).fetchall()
    found = []
    for pid, birth, pot in rows:
        b = datetime.date.fromisoformat(birth)
        age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
        if 16 <= age <= 17:
            found.append(pid)
    if not found:
        return
    import json
    conn.execute("UPDATE pack_info SET value=? WHERE key=?", (json.dumps(found), key))
    ensure_tables(conn)
    from .events import emit, player_name
    for pid in found:
        conn.execute("INSERT OR REPLACE INTO scout_knowledge VALUES (?,?,?)", (pid, 100.0, day))
        hl = f"{player_name(conn, pid)} granted exceptional status: the next big thing"
        emit(conn, "MEDIA_STORY", day, hl, player_id=pid, importance=3, headline=hl,
             body="Hockey's development people agree: a once-in-a-generation talent, already playing against older players.", tag="draft", kind="exceptional")


def is_exceptional(conn, pid):
    import json
    for (v,) in conn.execute("SELECT value FROM pack_info WHERE key LIKE 'exceptional_%'"):
        if pid in json.loads(v or "[]"):
            return True
    return False


def network_view(conn):
    ensure_tables(conn)
    me = user_team(conn)
    scouts, director = _scouts(conn, me)
    assign_ = {r[0]: r[1] for r in conn.execute("SELECT staff_id, region FROM scout_assign")}
    today = datetime.date.fromisoformat(get_state(conn)[0])
    trips = {(r[0], r[1]): r[2] for r in conn.execute("SELECT staff_id, event, done FROM scout_trips")}
    year, pool = _pool(conn)
    k = knowledge(conn)
    by_region = {r: {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0} for r in REGIONS}
    for x in pool:
        by_region[x["region"]][level_of(k.get(x["pid"], START))] += 1
    events = []
    for key, (name, _, days, regions, ages, top) in TOURNAMENTS.items():
        occ = next_occurrence(key, today)
        if occ:
            events.append(dict(key=key, name=name, start=occ[1].isoformat(), end=occ[2].isoformat(),
                               going=[s["staff_id"] for s in scouts + ([director] if director else []) if (s["staff_id"], key) in trips]))
    events.sort(key=lambda e: e["start"])
    from .events import player_name
    wl = [dict(pid=r[0], name=player_name(conn, r[0]), level=level_of(k.get(r[0], START)), added=r[1])
          for r in conn.execute("SELECT player_id, added FROM watchlist ORDER BY added DESC")]
    return dict(regions=REGIONS, scouts=[dict(staff_id=s["staff_id"], name=s["name"], evaluation=s["evaluation"], region=assign_.get(s["staff_id"], "all"))
                                         for s in scouts],
                director=dict(staff_id=director["staff_id"], name=director["name"], evaluation=director["evaluation"]) if director else None,
                coverage=by_region, events=events, watchlist=wl, year=year, pool=len(pool))
