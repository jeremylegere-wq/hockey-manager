"""Careers before the save began (v41; docs/HISTORY.md).

A world built from a database export has no past seasons on file, so a 34-year-old with 1,100 NHL games looks like a
rookie to the waiver rules, the milestone watch, the Hall of Fame and the all-time leaders. `career_prior` holds what
each player did in the NHL *before the first season on file*: games, goals, assists (skaters), wins and shutouts
(goalies), playoff games and seasons. Everything that adds up a career adds it in.

Sources
  - the M3 player profile export (File > Import career history, or `career import <file>`): NHL games and NHL seasons
    for the players it covers (it has no goals or assists), matched by name and birth date
  - the editor's CSV (columns career_gp, career_g, career_a, career_w, career_so, career_po_gp, career_seasons), or
    the player editor, for anything else
A world with past seasons on file (the data-pack worlds) should only get careers from before its first season, or
games are counted twice; the importer refuses players who already have recorded NHL seasons unless told otherwise.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata

FIELDS = ("gp", "g", "a", "w", "so", "po_gp", "seasons")
EDITOR_COLS = tuple(f"career_{k}" for k in FIELDS)


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS career_prior (player_id INTEGER PRIMARY KEY, gp INTEGER DEFAULT 0, "
                 "g INTEGER DEFAULT 0, a INTEGER DEFAULT 0, w INTEGER DEFAULT 0, so INTEGER DEFAULT 0, "
                 "po_gp INTEGER DEFAULT 0, seasons INTEGER DEFAULT 0, source TEXT)")


def prior(conn, pid):
    ensure_table(conn)
    r = conn.execute(f"SELECT {', '.join(FIELDS)}, source FROM career_prior WHERE player_id=?", (pid,)).fetchone()
    return dict(zip(FIELDS + ("source",), r)) if r else None


def all_prior(conn):
    ensure_table(conn)
    return {r[0]: dict(zip(FIELDS, r[1:])) for r in conn.execute(f"SELECT player_id, {', '.join(FIELDS)} FROM career_prior")}


def set_prior(conn, pid, source="editor", **vals):
    """Set some of a player's pre-save career numbers (others keep their value)."""
    ensure_table(conn)
    bad = [k for k in vals if k not in FIELDS]
    if bad:
        raise ValueError(f"Unknown career field {bad[0]}.")
    conn.execute("INSERT OR IGNORE INTO career_prior (player_id, source) VALUES (?, ?)", (pid, source))
    if vals:
        conn.execute(f"UPDATE career_prior SET {', '.join(f'{k}=?' for k in vals)}, source=? WHERE player_id=?",
                     [max(0, int(v or 0)) for v in vals.values()] + [source, pid])


def nhl_gp(conn, pid):
    p = prior(conn, pid)
    return p["gp"] if p else 0


# ---------------------------------------------------------------- the M3 profile export
def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def _dob(s):
    """'6.10.1990' or '1990-10-06' -> '1990-10-06'."""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return s[:10]


def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def import_m3(conn, text, apply=False, overwrite_recorded=False):
    """Match the M3 player profiles (CSV text) to this world's players by name and birth date and take their NHL games
    and seasons. Returns dict(rows, with_nhl, matched, unmatched (names), skipped_recorded, applied)."""
    ensure_table(conn)
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    need = {"player_name", "date_of_birth", "career_nhl_games_raw"}
    if not rd.fieldnames or not need <= set(rd.fieldnames):
        raise ValueError("Not an M3 player profile file (needs player_name, date_of_birth, career_nhl_games_raw).")
    idx = {}
    for pid, f, l, b in conn.execute("SELECT player_id, first_name, last_name, birth_date FROM players"):
        idx.setdefault((_norm(f) + _norm(l), (b or "")[:10]), []).append(pid)
    recorded = {r[0] for r in conn.execute("SELECT DISTINCT player_id FROM skater_season_stats WHERE split='RS' UNION "
                                           "SELECT DISTINCT player_id FROM goalie_season_stats WHERE split='RS'")}
    res = dict(rows=0, with_nhl=0, matched=0, unmatched=[], skipped_recorded=0, applied=False)
    todo = []
    for r in rd:
        res["rows"] += 1
        gp, ssn = _num(r.get("career_nhl_games_raw")), _num(r.get("career_nhl_seasons_raw"))
        if gp <= 0 and ssn <= 0:
            continue
        res["with_nhl"] += 1
        hit = idx.get((_norm(r["player_name"]), _dob(r["date_of_birth"])), [])
        if len(hit) != 1:
            res["unmatched"].append(r["player_name"])
            continue
        if hit[0] in recorded and not overwrite_recorded:
            res["skipped_recorded"] += 1
            continue
        res["matched"] += 1
        todo.append((hit[0], gp, max(ssn, 1 if gp else 0)))
    if apply:
        for pid, gp, ssn in todo:
            set_prior(conn, pid, "m3", gp=gp, seasons=ssn)
        res["applied"] = True
    res["unmatched"] = res["unmatched"][:100]
    return res


# ---------------------------------------------------------------- all-time
def alltime_skaters(conn, league, limit=50):
    """Skaters by career NHL points: seasons on file plus the pre-save career."""
    ensure_table(conn)
    tot = {}
    for r in conn.execute("SELECT player_id, COUNT(DISTINCT season_start_year), SUM(gp), SUM(g), SUM(a) FROM "
                          "skater_season_stats WHERE league_id=? AND split='RS' GROUP BY player_id", (league,)):
        tot[r[0]] = dict(seasons=r[1] or 0, gp=r[2] or 0, g=r[3] or 0, a=r[4] or 0, prior=False)
    for pid, p in all_prior(conn).items():
        if not (p["g"] or p["a"]) and pid not in tot:
            continue                                   # games only (the M3 profiles): that is the games table's job
        t = tot.setdefault(pid, dict(seasons=0, gp=0, g=0, a=0, prior=False))
        for k in ("seasons", "gp", "g", "a"):
            t[k] += p[k] or 0
        t["prior"] = True
    goalies = {r[0] for r in conn.execute("SELECT player_id FROM players WHERE position='G'")}
    rows = [dict(player_id=k, **v, p=v["g"] + v["a"]) for k, v in tot.items() if k not in goalies and v["g"] + v["a"] > 0]
    rows.sort(key=lambda x: (-x["p"], -x["gp"]))
    return rows[:limit]


def alltime_games(conn, league, limit=50):
    """Everyone by career NHL games (pre-save plus on file)."""
    ensure_table(conn)
    tot = {}
    for t in ("skater_season_stats", "goalie_season_stats"):
        for r in conn.execute(f"SELECT player_id, SUM(gp), COUNT(DISTINCT season_start_year) FROM {t} WHERE league_id=? "
                              "AND split='RS' GROUP BY player_id", (league,)):
            x = tot.setdefault(r[0], [0, 0])
            x[0] = max(x[0], r[1] or 0) if t == "goalie_season_stats" else x[0] + (r[1] or 0)
            x[1] = max(x[1], r[2] or 0)
    for pid, p in all_prior(conn).items():
        x = tot.setdefault(pid, [0, 0])
        x[0] += p["gp"] or 0
        x[1] += p["seasons"] or 0
    rows = sorted(({"player_id": k, "gp": v[0], "seasons": v[1]} for k, v in tot.items() if v[0]), key=lambda x: -x["gp"])
    return rows[:limit]


# ---------------------------------------------------------------- past drafts (v41)
DRAFT_ALIASES = {"year": "draft_year", "draftyear": "draft_year", "season": "draft_year", "rd": "round", "rnd": "round",
                 "pick": "overall", "ovr": "overall", "overallpick": "overall", "no": "overall", "club": "team",
                 "teamabbr": "team", "name": "player", "playername": "player", "prospect": "player", "id": "player_id",
                 "pid": "player_id", "dob": "birth_date", "born": "birth_date", "birthdate": "birth_date",
                 "first": "first_name", "firstname": "first_name", "last": "last_name", "lastname": "last_name",
                 "surname": "last_name"}


def ensure_draft_names(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS past_draft_names (draft_year INTEGER, overall INTEGER, name TEXT, "
                 "PRIMARY KEY (draft_year, overall))")


def import_drafts(conn, text, apply=False):
    """Past drafts from a CSV (draft_year, round, overall, team, player; optional player_id or birth_date). A player
    who is in this world is linked (his page and the draft log show the pick); one who is not keeps his name on the
    draft log. Picks already on file (drafts the game has held) are left alone. Returns a preview/result dict."""
    from .draft import ensure_tables as draft_tables, draft_year
    draft_tables(conn)
    this = draft_year(conn)
    ensure_draft_names(conn)
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not rd.fieldnames:
        raise ValueError("The file has no header row.")
    cols = {h: DRAFT_ALIASES.get(re.sub(r"[^a-z]", "", (h or "").lower()), (h or "").strip().lower()) for h in rd.fieldnames}
    if not {"draft_year", "overall", "team"} <= set(cols.values()):
        raise ValueError("Needs at least draft_year (or year), overall (or pick) and team columns.")
    abbr = {r[1].upper(): r[0] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    n_top = conn.execute("SELECT COUNT(*) FROM teams WHERE league_id=(SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1)").fetchone()[0] or 32
    idx = {}
    for pid, f, l, b in conn.execute("SELECT player_id, first_name, last_name, birth_date FROM players"):
        idx.setdefault(_norm(f) + _norm(l), []).append((pid, (b or "")[:10]))
    res = dict(rows=0, linked=0, named=0, skipped=0, errors=[], years=set(), applied=False)
    todo = []
    for i, raw in enumerate(rd, start=2):
        res["rows"] += 1
        r = {cols[h]: (v or "").strip() for h, v in raw.items() if h in cols}
        try:
            y, ov = _num(r.get("draft_year")), _num(r.get("overall"))
            if not (1960 <= y <= 2100) or ov < 1:
                raise ValueError("needs a draft year and an overall pick number.")
            if y >= this:
                raise ValueError(f"{y} is not a past draft (the game holds the {this} draft itself).")
            rnd = _num(r.get("round")) or (ov - 1) // n_top + 1
            t = abbr.get((r.get("team") or "").upper())
            if t is None:
                raise ValueError(f"unknown team {r.get('team')!r} (use a club abbreviation in this world).")
            if conn.execute("SELECT 1 FROM draft_picks WHERE draft_year=? AND overall=?", (y, ov)).fetchone():
                res["skipped"] += 1
                continue
            name = r.get("player") or " ".join(x for x in (r.get("first_name"), r.get("last_name")) if x)
            pid = _num(r.get("player_id")) or None
            if pid and not conn.execute("SELECT 1 FROM players WHERE player_id=?", (pid,)).fetchone():
                raise ValueError(f"no player {pid}.")
            if pid is None and name:
                hits = idx.get(_norm(name), [])
                if r.get("birth_date"):
                    hits = [h for h in hits if h[1] == _dob(r["birth_date"])]
                if len(hits) == 1:
                    pid = hits[0][0]
            todo.append((y, ov, rnd, t, pid, name))
            res["linked" if pid else "named"] += 1
            res["years"].add(y)
        except ValueError as e:
            res["errors"].append(dict(row=i, error=str(e)))
    if apply:
        for y, ov, rnd, t, pid, name in todo:
            conn.execute("INSERT OR IGNORE INTO draft_picks VALUES (?,?,?,?,?,?)", (y, ov, rnd, t, pid, "imported"))
            if not pid and name:
                conn.execute("INSERT OR REPLACE INTO past_draft_names VALUES (?,?,?)", (y, ov, name))
        res["applied"] = True
    res["years"] = sorted(res["years"])
    res["errors"] = res["errors"][:200]
    return res


# ---------------------------------------------------------------- past seasons, line by line (v42)
SEASON_ALIASES = {"year": "season", "seasonstart": "season", "startyear": "season", "lg": "league", "club": "team",
                  "teamname": "team", "games": "gp", "goals": "g", "assists": "a", "pts": "points", "points": "points",
                  "pm": "plus_minus", "plusminus": "plus_minus", "shots": "sog", "id": "player_id", "pid": "player_id",
                  "name": "player", "playername": "player", "dob": "birth_date", "born": "birth_date",
                  "birthdate": "birth_date", "first": "first_name", "firstname": "first_name", "last": "last_name",
                  "lastname": "last_name", "surname": "last_name", "wins": "w", "losses": "l", "shutouts": "so",
                  "goalsagainst": "ga", "shotsagainst": "sa", "type": "split", "playoffs": "split"}
SKATER_COLS = ("gp", "g", "a", "pim", "plus_minus", "sog")
GOALIE_COLS = ("gp", "w", "l", "otl", "so", "ga", "sa")


def _season(v):
    """'2019', '2019-20' or '2019/2020' -> 2019 (the season's start year)."""
    m = re.match(r"^\s*(\d{4})", v or "")
    return int(m.group(1)) if m else 0


def import_seasons(conn, text, apply=False):
    """Past seasons from a CSV, one row per player, season, league and club: player_id (or player / first and last
    name, with birth_date), season, league, team, split (RS or PO, default RS), then gp, g, a, pim, plus_minus, sog
    for skaters or gp, w, l, otl, so, ga, sa for goalies. They go on file like seasons the game played: the player
    page, career totals, waivers, milestones, the Hall of Fame and the leaders. A player who gets NHL seasons this way
    loses his games-only career total (career_prior), so nothing counts twice. Seasons from this one on are refused.
    Returns a preview/result dict."""
    from .contracts import season_year
    ensure_table(conn)
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not rd.fieldnames:
        raise ValueError("The file has no header row.")
    cols = {h: SEASON_ALIASES.get(re.sub(r"[^a-z]", "", (h or "").lower()), (h or "").strip().lower()) for h in rd.fieldnames}
    if not {"season", "league"} <= set(cols.values()) or "gp" not in cols.values():
        raise ValueError("Needs at least season, league and gp columns, and a player (player_id, or a name).")
    now = season_year(conn)
    leagues = {}
    for lid, a, b in conn.execute("SELECT league_id, name, abbr FROM leagues"):
        for k in (a, b):
            if k:
                leagues[_norm(k)] = lid
    teams = {}
    for tid, ab, nm, nick in conn.execute("SELECT team_id, abbr, name, nickname FROM teams"):
        for k in (ab, nm, f"{nm} {nick or ''}", nick):
            if k:
                teams.setdefault(_norm(k), tid)
    names = {}
    for pid, f, l, b, pos in conn.execute("SELECT player_id, first_name, last_name, birth_date, position FROM players"):
        names.setdefault(_norm(f) + _norm(l), []).append((pid, (b or "")[:10], pos))
    pos_of = {}
    res = dict(rows=0, players=set(), seasons=0, errors=[], unknown_teams=set(), cleared=0, applied=False)
    todo = []
    for i, raw in enumerate(rd, start=2):
        res["rows"] += 1
        r = {cols[h]: (v or "").strip() for h, v in raw.items() if h in cols}
        try:
            pid = _num(r.get("player_id")) or None
            if pid:
                p = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
                if not p:
                    raise ValueError(f"no player {pid}.")
                pos_of[pid] = p[0]
            else:
                name = r.get("player") or " ".join(x for x in (r.get("first_name"), r.get("last_name")) if x)
                hits = names.get(_norm(name), [])
                if r.get("birth_date"):
                    hits = [h for h in hits if h[1] == _dob(r["birth_date"])]
                if len(hits) != 1:
                    raise ValueError(f"{name or 'no name'}: {'not in this world' if not hits else 'more than one match; give birth_date or player_id'}.")
                pid = hits[0][0]
                pos_of[pid] = hits[0][2]
            y = _season(r.get("season"))
            if not 1950 <= y < now:
                raise ValueError(f"season {r.get('season')!r} is not a past season (this one is {now}).")
            lg = leagues.get(_norm(r.get("league")))
            if lg is None:
                raise ValueError(f"unknown league {r.get('league')!r}.")
            tid = teams.get(_norm(r.get("team"))) if r.get("team") else None
            if r.get("team") and tid is None:
                res["unknown_teams"].add(r["team"])
            split = "PO" if (r.get("split") or "").strip().upper() in ("PO", "P", "PLAYOFFS", "YES", "1") else "RS"
            goalie = pos_of[pid] == "G"
            vals = {k: _num(r.get(k)) for k in (GOALIE_COLS if goalie else SKATER_COLS)}
            if not goalie and not r.get("a") and r.get("points") and r.get("g"):
                vals["a"] = max(0, _num(r["points"]) - _num(r["g"]))
            if vals["gp"] <= 0:
                raise ValueError("gp must be at least 1.")
            todo.append((pid, y, tid, lg, split, goalie, vals))
            res["players"].add(pid)
            res["seasons"] += 1
        except ValueError as e:
            res["errors"].append(dict(row=i, error=str(e)))
    if apply:
        nhl = conn.execute("SELECT league_id FROM teams WHERE league_id IS NOT NULL GROUP BY league_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        top = conn.execute("SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
        top = top[0] if top else (nhl[0] if nhl else 1)
        for pid, y, tid, lg, split, goalie, vals in todo:
            tbl = "goalie_season_stats" if goalie else "skater_season_stats"
            conn.execute(f"DELETE FROM {tbl} WHERE player_id=? AND season_start_year=? AND league_id=? AND split=? AND "
                         f"COALESCE(team_id, -1)=COALESCE(?, -1)", (pid, y, lg, split, tid))
            keys = ["player_id", "season_start_year", "team_id", "league_id", "split", *vals]
            conn.execute(f"INSERT INTO {tbl} ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                         (pid, y, tid, lg, split, *vals.values()))
        for pid in {t[0] for t in todo if t[3] == top}:
            if conn.execute("DELETE FROM career_prior WHERE player_id=?", (pid,)).rowcount:
                res["cleared"] += 1
        res["applied"] = True
    res["players"] = len(res["players"])
    res["unknown_teams"] = sorted(res["unknown_teams"])[:50]
    res["errors"] = res["errors"][:200]
    return res
