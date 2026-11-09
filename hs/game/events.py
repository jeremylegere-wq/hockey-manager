"""Shared event log: the simulation writes facts here; history, dashboard, inbox and (later) media read them.

Presentation never writes game state. Each event has a type, date, season, the entities involved and a JSON
payload. Importance 1 (routine) to 3 (major) lets readers filter. Transactions remain the authoritative record of
roster moves; events point at the same facts so narrative layers have one place to look.
"""
from __future__ import annotations

import json

TYPES = {
    "PLAYER_SIGNED", "PLAYER_RELEASED", "PLAYER_TRADED", "PLAYER_INJURED", "PLAYER_RETIRED", "PLAYER_DRAFTED",
    "ARBITRATION_AWARD", "CHAMPIONSHIP", "PLAYOFFS_ELIMINATED", "PROMISE_MADE", "PROMISE_FULFILLED", "PROMISE_BROKEN",
    "PROMISE_WITHDRAWN", "CONCERN_RAISED", "CONVERSATION", "TRADE_REQUEST", "CAPTAIN_CHANGED", "STAFF_HIRED",
    "STAFF_DISMISSED", "COACH_FIRED", "GM_FIRED", "GM_HIRED", "OBJECTIVES_SET", "OBJECTIVE_MET", "OBJECTIVE_FAILED",
    "BOARD_REVIEW", "MORALE_SHIFT", "RECORD_BROKEN", "TRADE_COMPLETED", "RUMOUR",
    "AWARD_WON", "PRESSER", "MEDIA_STORY", "LOCKER_ROOM", "LEAGUE_CHAMPION",
    "ALL_STAR", "HALL_OF_FAME", "EXHIBITION", "ACHIEVEMENT",               # v37, phase F
    "EXPANSION_PICK",                                                      # v45
}


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS league_events (event_id INTEGER PRIMARY KEY, event_date TEXT NOT NULL, "
                 "season_start_year INTEGER, event_type TEXT NOT NULL, team_id INTEGER, player_id INTEGER, "
                 "staff_id INTEGER, other_team_id INTEGER, importance INTEGER DEFAULT 1, summary TEXT, payload TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_events_team ON league_events(team_id, event_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_events_player ON league_events(player_id)")


def emit(conn, event_type, date, summary, team_id=None, player_id=None, staff_id=None, other_team_id=None,
         importance=1, **payload):
    if event_type not in TYPES:
        raise ValueError(f"unknown event type {event_type}")
    season = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
    conn.execute("INSERT INTO league_events (event_date, season_start_year, event_type, team_id, player_id, staff_id, "
                 "other_team_id, importance, summary, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (date, season, event_type, team_id, player_id, staff_id, other_team_id, importance, summary,
                  json.dumps(payload) if payload else None))


def recent(conn, team_id=None, player_id=None, types=None, min_importance=1, limit=20, season=None):
    q = "SELECT * FROM league_events WHERE importance >= ?"
    args = [min_importance]
    if team_id is not None:
        q += " AND (team_id=? OR other_team_id=?)"
        args += [team_id, team_id]
    if player_id is not None:
        q += " AND player_id=?"
        args.append(player_id)
    if types:
        q += f" AND event_type IN ({','.join('?' * len(types))})"
        args += list(types)
    if season is not None:
        q += " AND season_start_year=?"
        args.append(season)
    return conn.execute(q + " ORDER BY event_date DESC, event_id DESC LIMIT ?", (*args, limit)).fetchall()


def player_name(conn, pid):
    r = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()
    return r[0] if r else f"#{pid}"


def team_abbr(conn, tid):
    r = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (tid,)).fetchone()
    return r[0] if r else "FA"
