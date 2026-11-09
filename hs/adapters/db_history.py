"""Adapter: career history and past drafts from your own community database file (database.db), v42.

    python -m hs.adapters.db_history <database.db> <export folder> <game or world .db> [--apply]

PERSONAL USE ONLY, like the export adapter (hs/adapters/db_export.py): it reads a file you own locally and writes
into your own world or save; nothing from it ships with this program.

The file is a run of sections, each a 6-byte header (uint16 tag, uint32 record count) followed by its records. Two
fixed-width sections are read (the layouts were worked out against a community editor's column list and checked
against real careers: Nick Suzuki's 2021-22 is 82 GP, 21 G, 40 A; Connor Hellebuyck's 2023-24 is 60 GP, 37-19-4,
5 shutouts):

  career history (tag 13), 36 bytes:   0 id (int32)   4 staff (int32)   8 club (int32)   12 competition (int32)
      16 season start year (uint16)   18 goalie minutes (uint16)   20 goals against (uint16)   22 shutouts (uint8)
      23 saves (uint16)   25 penalty minutes (uint16)   27 plus/minus (int8)   28 games   29 goals   30 assists
      31 wins   32 losses   33 ties / OT losses   34 playoffs (1)   35 on loan
  drafted players (tag 24), 29 bytes:  0 id   4 draft (0 = NHL Entry Draft)   8 staff   12 club   16-23 unused
      24 year (uint16)   26 overall pick (uint16)   28 round

Ids map through the export folder: staff -> player via staff_normalized.csv (staff_record_index -> player_data_ref;
the world's player id is player_data_ref + 1), clubs via clubs_lookup.csv, competitions via
club_competitions_lookup.csv. Seasons go into skater_season_stats / goalie_season_stats with source='history'
(clubs and leagues outside the world keep their names in club_name / league_name); NHL Entry Draft picks go into
draft_picks (players not in the world keep their names). See docs/HISTORY.md.
"""
from __future__ import annotations

import argparse
import csv
import mmap
import re
import sqlite3
import struct
import unicodedata
from pathlib import Path

HISTORY_TAG, HISTORY_WIDTH = 13, 36
DRAFTED_TAG, DRAFTED_WIDTH = 24, 29
NHL_ENTRY_DRAFT = 0
FRANCHISE = {"arizonacoyotes": "UTA", "phoenixcoyotes": "UTA", "atlantathrashers": "WPG"}
HIST = struct.Struct("<iiiiHHHBHHbBBBBBBBB")      # 36 bytes
DRAFT = struct.Struct("<iiii8sHHB")               # 29 bytes


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def find_section(buf, tag, width, check, max_count=5_000_000):
    """(payload offset, count) of the section with this tag and record width: a header whose records end exactly at
    the next section's header (tag + 1) and whose records pass `check` (a sample of 200)."""
    pat = struct.pack("<H", tag)
    i = buf.find(pat)
    while i >= 0:
        n = struct.unpack_from("<I", buf, i + 2)[0]
        if 50 < n < max_count:
            end = i + 6 + n * width
            if end + 6 <= len(buf) and struct.unpack_from("<H", buf, end)[0] == tag + 1:
                step = max(1, n // 200)
                sample = [i + 6 + k * width for k in range(0, n, step)]
                if sum(1 for o in sample if check(buf, o)) >= 0.95 * len(sample):
                    return i + 6, n
        i = buf.find(pat, i + 1)
    raise ValueError(f"section {tag} ({width}-byte records) not found: is this the right database file?")


def _hist_ok(buf, o):
    year = struct.unpack_from("<H", buf, o + 16)[0]
    return 1900 <= year <= 2100 and buf[o + 34] in (0, 1)


def _draft_ok(buf, o):
    year, pick = struct.unpack_from("<HH", buf, o + 24)
    return 1900 <= year <= 2100 and 0 <= pick <= 400 and buf[o + 28] <= 20


def history_rows(buf):
    off, n = find_section(buf, HISTORY_TAG, HISTORY_WIDTH, _hist_ok)
    for k in range(n):
        (_id, staff, club, comp, year, mins, ga, so, saves, pim, pm, gp, g, a, w, l, t, po, loan) = \
            HIST.unpack_from(buf, off + k * HISTORY_WIDTH)
        yield dict(staff=staff, club=club, comp=comp, year=year, mins=mins, ga=ga, so=so, saves=saves, pim=pim,
                   pm=pm, gp=gp, g=g, a=a, w=w, l=l, t=t, playoffs=po == 1, loan=bool(loan))


def drafted_rows(buf):
    off, n = find_section(buf, DRAFTED_TAG, DRAFTED_WIDTH, _draft_ok)
    for k in range(n):
        _id, draft, staff, club, _pad, year, pick, rnd = DRAFT.unpack_from(buf, off + k * DRAFTED_WIDTH)
        yield dict(draft=draft, staff=staff, club=club, year=year, pick=pick, round=rnd)


def _find(root, name):
    hits = sorted(Path(root).rglob(name), key=lambda p: str(p))
    if not hits:
        raise FileNotFoundError(f"{name} not found under {root}")
    return hits[-1]


def _read(path):
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        yield from csv.DictReader(fh)


def ensure_columns(conn):
    from ..schema import migrate
    migrate(conn)


def load(conn, db_file, export_root, apply=False, before=None):
    """Read the file and map it onto this world. Returns a summary dict; writes only with apply=True."""
    from ..game import career as CR
    from ..game.draft import ensure_tables as draft_tables, draft_year
    from ..game.contracts import season_year
    from .db_export import DIVISIONS as _DIV, DB_LEAGUES
    DIVISIONS = dict(_DIV, **{name: abbr for name, (abbr, _) in DB_LEAGUES.items()})
    if before is None:                                    # seasons before the world's first one (a save that has
        r = conn.execute("SELECT MIN(start_year) FROM seasons").fetchone()   # played on keeps its own)
        before = r[0] if r and r[0] else season_year(conn)
    staff = {}
    for r in _read(_find(export_root, "staff_normalized.csv")):
        ref = r.get("player_data_ref")
        if ref not in (None, "", "-1"):
            try:
                staff[int(r["staff_record_index"])] = (int(ref) + 1, f"{r.get('forename', '')} {r.get('surname', '')}".strip())
            except ValueError:
                pass
    clubs = {}
    for r in _read(_find(export_root, "clubs_lookup.csv")):
        try:
            clubs[int(r["club_id"])] = (r.get("Long name") or r.get("lookup_name") or "", r.get("Abbreviation") or "")
        except ValueError:
            pass
    comps = {}
    for r in _read(_find(export_root, "club_competitions_lookup.csv")):
        try:
            comps[int(r["league_id"])] = (r.get("Name") or r.get("lookup_name") or "", r.get("Short Name") or r.get("Abbrev.") or "")
        except ValueError:
            pass
    players = {r[0]: r[1] for r in conn.execute("SELECT player_id, position FROM players")}
    league_ids = {}
    for lid, a, b in conn.execute("SELECT league_id, name, abbr FROM leagues"):
        for k in (a, b):
            if k:
                league_ids[_norm(k)] = lid
    teams = {}
    for tid, name, nick, abbr in conn.execute("SELECT team_id, name, nickname, abbr FROM teams"):
        teams.setdefault(_norm(f"{name} {nick or ''}"), tid)
        teams.setdefault(_norm(name), tid)
    top = conn.execute("SELECT league_id FROM leagues ORDER BY COALESCE(level, 1), league_id LIMIT 1").fetchone()[0]

    def league_of(comp):
        name, short = comps.get(comp, ("", ""))
        ab = DIVISIONS.get(name)
        lid = league_ids.get(_norm(ab)) if ab else None
        if lid is None and ab == "NHL":                       # the database's NHL is the world's top league
            lid = top
        return lid, (short or name or None)

    def team_of(club):
        name, ab = clubs.get(club, ("", ""))
        tid = teams.get(_norm(name))
        if tid is None and _norm(name) in FRANCHISE:             # relocated clubs' picks belong to the franchise now
            tid = conn.execute("SELECT team_id FROM teams WHERE abbr=?", (FRANCHISE[_norm(name)],)).fetchone()
            tid = tid[0] if tid else None
        return tid, name or None

    with open(db_file, "rb") as fh:
        buf = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            sk, gk, seen = [], [], set()
            for h in history_rows(buf):
                who = staff.get(h["staff"])
                if who is None or who[0] not in players or not (1950 <= h["year"] < before) or h["gp"] <= 0:
                    continue
                pid = who[0]
                lid, lname = league_of(h["comp"])
                tid, cname = team_of(h["club"])
                split = "PO" if h["playoffs"] else "RS"
                seen.add(pid)
                if players[pid] == "G":
                    gk.append((pid, h["year"], tid, lid, split, h["gp"], h["mins"] * 60, h["w"], h["l"], h["t"], h["so"],
                               h["ga"], h["ga"] + h["saves"], "history", None if tid else cname, None if lid else lname))
                else:
                    sk.append((pid, h["year"], tid, lid, split, h["gp"], h["g"], h["a"], h["pim"], h["pm"],
                               "history", None if tid else cname, None if lid else lname))
            picks = []
            dy = draft_year(conn)
            for d in drafted_rows(buf):
                if d["draft"] != NHL_ENTRY_DRAFT or not (1960 <= d["year"] < dy) or d["pick"] <= 0:
                    continue
                tid, cname = team_of(d["club"])
                if tid is None:
                    continue
                relocated = _norm(cname) in FRANCHISE
                who = staff.get(d["staff"])
                pid = who[0] if who and who[0] in players else None
                picks.append((d["year"], d["pick"], d["round"] or 1, tid, pid, None if pid else (who[1] if who else None),
                              f"history ({cname})" if relocated else "history"))
        finally:
            buf.close()
    nhl_players = {r[0] for r in sk + gk if r[3] == top}
    res = dict(skater_lines=len(sk), goalie_lines=len(gk), players=len(seen), nhl_players=len(nhl_players),
               draft_picks=len(picks), draft_years=sorted({p[0] for p in picks}), applied=False)
    if not apply:
        return res
    ensure_columns(conn)
    draft_tables(conn)
    CR.ensure_draft_names(conn)
    for t in ("skater_season_stats", "goalie_season_stats"):
        conn.execute(f"DELETE FROM {t} WHERE source='history'")
    conn.executemany("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a, "
                     "pim, plus_minus, source, club_name, league_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", sk)
    conn.executemany("INSERT INTO goalie_season_stats (player_id, season_start_year, team_id, league_id, split, gp, toi_sec, "
                     "w, l, otl, so, ga, sa, source, club_name, league_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", gk)
    # the games-only careers (the M3 profiles) give way to real seasons, so nothing counts twice
    CR.ensure_table(conn)
    q = ",".join("?" * len(nhl_players))
    res["prior_replaced"] = conn.execute(f"DELETE FROM career_prior WHERE player_id IN ({q})", list(nhl_players)).rowcount \
        if nhl_players else 0
    held = {(r[0], r[1]) for r in conn.execute("SELECT draft_year, overall FROM draft_picks WHERE COALESCE(lottery_note,'') NOT LIKE 'history%'")}
    conn.execute("DELETE FROM draft_picks WHERE lottery_note LIKE 'history%'")
    added = 0
    for y, ov, rnd, tid, pid, name, note in picks:
        if (y, ov) in held:
            continue
        conn.execute("INSERT OR IGNORE INTO draft_picks VALUES (?,?,?,?,?,?)", (y, ov, rnd, tid, pid, note))
        if not pid and name:
            conn.execute("INSERT OR REPLACE INTO past_draft_names VALUES (?,?,?)", (y, ov, name))
        if pid:                                             # rights the world already holds get their pick number
            conn.execute("UPDATE draft_rights SET overall_pick=? WHERE player_id=? AND draft_year=? AND overall_pick IS NULL",
                         (ov, pid, y)) if conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_rights'").fetchone() else None
        added += 1
    res["draft_picks_added"] = added
    res["clubs_aligned"] = apply_alignment(conn, export_root)
    res["league_games"] = league_games(conn)
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('history_imported', ?)", (str(before),))
    res["applied"] = True
    return res


def league_games(conn):
    """v44: the database leagues' game counts from the history: the regular-season games of a club's busier players
    (90th percentile) in the last season on file. Written into the world's rules. Returns {abbr: games}."""
    import json
    r = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    if not r:
        return {}
    rules = json.loads(r[0])
    meta = (rules.get("world") or {}).get("leagues") or {}
    out = {}
    for lid, m in meta.items():
        if m.get("source") != "database":
            continue
        last = conn.execute("SELECT MAX(season_start_year) FROM skater_season_stats WHERE league_id=? AND source='history' "
                            "AND split='RS'", (int(lid),)).fetchone()[0]
        if last is None:
            continue
        gps = sorted(x[0] for x in conn.execute("SELECT gp FROM skater_season_stats WHERE league_id=? AND season_start_year=? "
                                                 "AND split='RS' AND source='history'", (int(lid), last)) if x[0])
        if len(gps) < 20:
            continue
        g = gps[int(len(gps) * 0.9)]
        m["games"] = int(g)
        conn.execute("UPDATE leagues SET games_per_team=? WHERE league_id=?", (int(g), int(lid)))
        out[m["abbr"]] = int(g)
    conn.execute("UPDATE pack_info SET value=? WHERE key='rules'", (json.dumps(rules),))
    return out


def apply_alignment(conn, export_root):
    """v44: every non-NHL club's division and conference from the export's clubs (schedules and playoffs follow
    them). Returns the number of clubs aligned."""
    from ..leaguedata.league_rules import split_division
    names = {}
    for r in _read(_find(export_root, "clubs_lookup.csv")):
        names.setdefault(_norm(r.get("Long name") or r.get("lookup_name")), r.get("DetailedDivision") or "")
    n = 0
    top = conn.execute("SELECT league_id FROM leagues ORDER BY COALESCE(level, 1), league_id LIMIT 1").fetchone()[0]
    for tid, name, nick in conn.execute("SELECT team_id, name, nickname FROM teams WHERE league_id<>?", (top,)).fetchall():
        dd = names.get(_norm(name)) or names.get(_norm(f"{name} {nick or ''}"))
        if dd is None:
            continue
        conf, div = split_division(dd)
        conn.execute("UPDATE teams SET conference=?, division=? WHERE team_id=?", (conf or None, div or None, tid))
        n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("database")
    ap.add_argument("export_folder")
    ap.add_argument("game_db")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.game_db)
    conn.row_factory = sqlite3.Row
    r = load(conn, a.database, a.export_folder, apply=a.apply)
    conn.commit()
    for k, v in r.items():
        print(f"{k}: {v if not isinstance(v, list) else (str(v[:3]) + ' ... ' + str(v[-3:]) if len(v) > 6 else v)}")


if __name__ == "__main__":
    main()
