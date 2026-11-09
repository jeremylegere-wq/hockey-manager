"""Quickstarts: a world captured at the start of a season, for new careers to begin from (v48; docs/QUICKSTARTS.md).

Make one (File > Save as quickstart, or `quickstart save <name>`) from any career when a regular season has been
scheduled and no game of it has been played (after the pre-season phase ends). The quickstart keeps the whole world -
rosters, contracts, prospects, history, the leagues around the NHL, expansion clubs, records, the Hall of Fame - and
drops what belongs to your career: your inbox, achievements, challenge, scouting assignments and knowledge, short list
and notes, open trade offers and shops, prospect paths, and your place at your club (it gets a GM of its own). It is
listed with the worlds when you start a new career; pick any club. A quickstart made from an edited save stays marked
as edited.
"""
from __future__ import annotations

import datetime
import random
import sqlite3
from pathlib import Path

from .events import emit, team_abbr
from .state import get_state, user_team

CLEAR = ("inbox", "achievements", "scout_assign", "scout_knowledge", "scout_trips", "watchlist", "shop", "college_paths",
         "story_queue", "press_events")
KEYS = ("challenge", "challenge_history", "challenge_mode", "gm_status", "backup_day", "backup_phase")


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


def can_make(conn):
    st = conn.execute("SELECT value FROM pack_info WHERE key='season_state'").fetchone()
    if not st or st[0] != "regular_season":
        return False, "A quickstart is made at the start of a season: after the pre-season phase, before the first game."
    sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    if conn.execute("SELECT 1 FROM games WHERE season_id=? AND played=1 AND game_type='RS' LIMIT 1", (sid,)).fetchone():
        return False, "This season has started: make a quickstart at the start of the next one (after the pre-season phase)."
    return True, ""


def make(conn, dest, name):
    """Copy the open save to dest as a quickstart world."""
    ok, why = can_make(conn)
    if not ok:
        raise ValueError(why)
    dest = Path(dest)
    if dest.exists():
        raise ValueError(f"A world called {dest.stem} already exists.")
    conn.commit()
    out = sqlite3.connect(dest)
    try:
        conn.backup(out)
    finally:
        out.close()
    c = sqlite3.connect(dest)
    try:
        y = c.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
        day = c.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone()[0]
        me = c.execute("SELECT team_id FROM manager WHERE id=1").fetchone()
        _strip(c, me[0] if me else None)
        for k, v in (("quickstart", name), ("quickstart_day", day), ("quickstart_season", str(y)), ("world_name", f"{name} (quickstart {y}-{(y + 1) % 100:02d})")):
            c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (k, v))
        c.commit()
        c.execute("VACUUM")
    finally:
        c.close()
    return dest


def _strip(c, me):
    """Drop what belongs to the career: the GM's place, messages, scouting and plans."""
    for t in CLEAR:
        if _has(c, t):
            c.execute(f"DELETE FROM {t}")
    for k in KEYS:
        c.execute("DELETE FROM pack_info WHERE key=?", (k,))
    c.execute("DELETE FROM pack_info WHERE key LIKE 'welcome_%'")
    if _has(c, "trade_offers"):
        cols = {r[1] for r in c.execute("PRAGMA table_info(trade_offers)")}
        if "status" in cols:
            c.execute("DELETE FROM trade_offers WHERE status IN ('open','pending')")
    if _has(c, "hof_ballot"):
        c.execute("UPDATE hof_ballot SET my_vote=0")
    if _has(c, "gm_seasons"):
        c.execute("UPDATE gm_seasons SET is_user=0")
    if _has(c, "gm_career"):
        c.execute("DELETE FROM gm_career")
    if _has(c, "expansion"):
        c.execute("UPDATE expansion SET user_gm=0, by_user=0 WHERE status IN ('announced','protecting')")
    if me is not None and _has(c, "board"):
        from .org import GM_FIRST, GM_LAST
        rng = random.Random(f"quickstart-gm-{me}")
        c.execute("UPDATE board SET gm_name=? WHERE team_id=? AND gm_name='You'", (f"{rng.choice(GM_FIRST)} {rng.choice(GM_LAST)}", me))
    c.execute("UPDATE manager SET team_id=NULL WHERE id=1")


def is_quickstart(path):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            r = c.execute("SELECT value FROM pack_info WHERE key='quickstart'").fetchone()
            return bool(r)
        finally:
            c.close()
    except sqlite3.Error:
        return False


def start(db_path, team_abbr_, seed=None):
    """Begin a career in a copy of a quickstart: take the club."""
    from .state import connect
    from ..schema import top_league_sql
    conn = connect(db_path)
    try:
        row = conn.execute(f"SELECT team_id FROM teams WHERE UPPER(abbr)=UPPER(?) AND {top_league_sql()}", (team_abbr_,)).fetchone()
        if not row:
            raise ValueError(f"Team {team_abbr_} not found.")
        t = row[0]
        day = get_state(conn)[0]
        if seed is not None:
            conn.execute("UPDATE game_state SET rng_seed=? WHERE id=1", (int(seed),))
        conn.execute("INSERT OR REPLACE INTO manager (id, team_id, name) VALUES (1, ?, 'Manager')", (t,))
        if _has(conn, "board"):
            conn.execute("UPDATE board SET gm_name='You', confidence=60, warnings=0, vacancy=0 WHERE team_id=?", (t,))
        from . import gm
        gm.ensure_tables(conn)
        conn.execute("DELETE FROM gm_career")
        conn.execute("INSERT INTO gm_career VALUES (?,?,NULL,NULL)", (t, day))
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('career_from_quickstart', ?)",
                     ((conn.execute("SELECT value FROM pack_info WHERE key='quickstart'").fetchone() or [""])[0],))
        emit(conn, "GM_HIRED", day, f"{team_abbr(conn, t)} name a new general manager", team_id=t, importance=2)
        conn.commit()
    finally:
        conn.close()
