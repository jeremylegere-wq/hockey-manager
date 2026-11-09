"""Manager state kept in the game database (a save is the .db file)."""
from __future__ import annotations

import datetime
import json
import sqlite3

from ..league.season import create_schedule, db_rules

# NB: `current_date` is also an SQL keyword (today's date). Always read it via SELECT * / the helpers below,
# or quote it as "current_date"; an unquoted `SELECT current_date` silently returns the real-world date.


def connect(db_path, shared=False):
    """Open a game database; older saves get the newer game tables added (nothing existing is changed).

    shared=True lets other threads use the connection; the caller must serialise access (the UI server holds a lock)."""
    conn = sqlite3.connect(db_path, check_same_thread=not shared)
    conn.row_factory = sqlite3.Row
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='players'").fetchone():
        from ..schema import migrate
        if migrate(conn):
            conn.commit()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='game_state'").fetchone():
        ensure_game_tables(conn)
        if conn.execute("SELECT 1 FROM game_state").fetchone() and conn.execute(
                "SELECT 1 FROM players WHERE jersey_number IS NULL AND status<>'retired' AND COALESCE(club_id, team_id) IS NOT NULL "
                "LIMIT 1").fetchone():
            from . import numbers                    # v49: everyone at a club wears a number
            numbers.fix(conn)
            conn.commit()
    return conn


def ensure_game_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS manager (id INTEGER PRIMARY KEY, team_id INTEGER, name TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS inbox (msg_id INTEGER PRIMARY KEY, date TEXT, subject TEXT, body TEXT, "
                 "read INTEGER DEFAULT 0)")
    _inbox_columns(conn)
    from .contracts import ensure_contract_tables
    from .events import ensure_table as ensure_events
    ensure_contract_tables(conn)
    ensure_events(conn)
    _dedupe_recorded_seasons(conn)
    conn.commit()


def _dedupe_recorded_seasons(conn):
    """Saves from before v22: a simulated season was added next to the pack's stats for that same season, so it
    counted twice. Rows recorded by the game were appended after every pack row, so for each recorded season the
    pack's copy is the rows below the first row the game wrote; those move to replaced_*_season_stats. Once."""
    if conn.execute("SELECT 1 FROM pack_info WHERE key='stats_dedup_v22'").fetchone():
        return
    years = sorted(int(r[0].rsplit("_", 1)[1]) for r in conn.execute(
        "SELECT key FROM pack_info WHERE key LIKE 'stats_recorded_%'"))
    for t in ("skater_season_stats", "goalie_season_stats"):
        if not years:
            break
        conn.execute(f"CREATE TABLE IF NOT EXISTS replaced_{t} AS SELECT * FROM {t} WHERE 0")
        for y in years:
            league = conn.execute("SELECT league_id FROM seasons WHERE start_year=? ORDER BY season_id LIMIT 1",
                                  (y,)).fetchone()
            if not league:
                continue
            # the game's rows for season y: the last block written for it (one row per player and team)
            dup = conn.execute(f"SELECT COUNT(*) FROM (SELECT player_id FROM {t} WHERE season_start_year=? AND "
                               "league_id=? AND split='RS' GROUP BY player_id, team_id HAVING COUNT(*) > 1)",
                               (y, league[0])).fetchone()[0]
            if not dup:
                continue
            first_game_row = conn.execute(
                f"SELECT MIN(m) FROM (SELECT MAX(rowid) m FROM {t} WHERE season_start_year=? AND league_id=? AND "
                "split='RS' GROUP BY player_id, team_id HAVING COUNT(*) > 1)", (y, league[0])).fetchone()[0]
            where = f"season_start_year=? AND league_id=? AND split='RS' AND rowid<?"
            conn.execute(f"INSERT INTO replaced_{t} SELECT * FROM {t} WHERE {where}", (y, league[0], first_game_row))
            conn.execute(f"DELETE FROM {t} WHERE {where}", (y, league[0], first_game_row))
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('stats_dedup_v22', '1')")


def get_state(conn):
    """(current_date ISO string, rng_seed) or None before a game has been started."""
    r = conn.execute('SELECT "current_date" AS d, rng_seed AS s FROM game_state WHERE id=1').fetchone()
    return (r["d"], r["s"]) if r else None


def user_team(conn):
    r = conn.execute("SELECT team_id FROM manager WHERE id=1").fetchone()
    return r["team_id"] if r else None


def season_state(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='season_state'").fetchone()
    return r["value"] if r else "regular_season"


def add_message(conn, day, subject, body, sender=None, actions=None):
    """A message for you. sender: who wrote it ("Name, Head Coach"); actions: [{"label", "href"} or {"label", "cmd"}]
    shown as buttons in the reading pane (v38). Commands in backticks in the body become buttons too."""
    _inbox_columns(conn)
    conn.execute("INSERT INTO inbox (date, subject, body, sender, actions) VALUES (?,?,?,?,?)",
                 (day, subject, body, sender, json.dumps(actions) if actions else None))


def _inbox_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(inbox)")}
    for c, typ in (("sender", "TEXT"), ("actions", "TEXT"), ("flagged", "INTEGER DEFAULT 0"), ("archived", "INTEGER DEFAULT 0")):
        if c not in cols:
            conn.execute(f"ALTER TABLE inbox ADD COLUMN {c} {typ}")


def staff_sender(conn, role, t=None):
    """'Name, Head Coach' for a member of your staff (role HC, AC, MED, SCOUT_DIR, SCOUT, DEV, GC, ANALYTICS)."""
    titles = {"HC": "Head Coach", "AC": "Assistant Coach", "MED": "Head Physio", "SCOUT_DIR": "Director of Scouting",
              "SCOUT": "Scout", "DEV": "Development Coach", "GC": "Goalie Coach", "ANALYTICS": "Analytics"}
    t = t if t is not None else user_team(conn)
    try:
        r = conn.execute("SELECT name FROM staff WHERE team_id=? AND role=? ORDER BY staff_id LIMIT 1", (t, role)).fetchone()
    except sqlite3.OperationalError:
        r = None
    return f"{r[0]}, {titles.get(role, role)}" if r else titles.get(role, "Staff")


def new_game(db_path, team_abbr, seed=1):
    conn = connect(db_path)
    try:
        ensure_game_tables(conn)
        if conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]:
            raise ValueError("A game is already in progress in this database (use a fresh copy of the ingested pack).")
        rules = db_rules(conn)
        if rules is None:
            raise ValueError("This pack has no rules.json; add one (see docs/LEAGUES_AND_SCHEDULES.md).")
        from ..schema import top_league_sql
        row = conn.execute(f"SELECT team_id FROM teams WHERE UPPER(abbr)=UPPER(?) AND {top_league_sql()}",
                           (team_abbr,)).fetchone()
        if not row:
            raise ValueError(f"Team {team_abbr} not found.")
        create_schedule(conn, rules, seed)
        from .contracts import generate_contracts
        generate_contracts(conn, seed)       # only players in a club system without a current contract
        from .draft import ensure_tables
        from .world import ensure_profiles
        ensure_tables(conn)
        ensure_profiles(conn)                # hidden development profiles for players the pack did not give one
        first = conn.execute("SELECT MIN(game_date) FROM games").fetchone()[0]
        start = (datetime.date.fromisoformat(first) - datetime.timedelta(days=1)).isoformat()
        conn.execute('INSERT OR REPLACE INTO game_state (id, "current_date", rng_seed) VALUES (1, ?, ?)', (start, seed))
        conn.execute("INSERT OR REPLACE INTO manager (id, team_id, name) VALUES (1, ?, 'Manager')", (row["team_id"],))
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state','regular_season')")
        from . import org, people, staff
        staff.setup(conn)
        people.setup(conn, start)
        from . import finance
        finance.setup(conn)
        org.setup(conn, start)
        conn.commit()
        return row["team_id"]
    finally:
        conn.close()
