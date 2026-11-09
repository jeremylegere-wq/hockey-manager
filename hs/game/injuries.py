"""Injuries: rolled per player after each day from ice time played. TODO(later): in-game injuries, injury types."""
from __future__ import annotations

import datetime

from .state import add_message, user_team

BASE_PER_60 = 0.006   # injuries per 60 minutes on ice (~1 per 170 player-games at 20 min)
# (cumulative probability, min days, max days)
SEVERITY = [(0.45, 1, 3), (0.75, 4, 10), (0.90, 11, 30), (0.98, 31, 90), (1.0, 91, 200)]


def _name(conn, pid):
    r = conn.execute("SELECT first_name || ' ' || last_name AS n FROM players WHERE player_id=?", (pid,)).fetchone()
    return r["n"]


def draw_days(rng):
    r = rng.random()
    for cum, lo, hi in SEVERITY:
        if r < cum:
            return rng.randint(lo, hi)
    return rng.randint(SEVERITY[-1][1], SEVERITY[-1][2])


def roll_injuries(conn, day, played_players, rng):
    """played_players: iterable of (player_id, toi_sec). Returns list of (player_id, team_id, days)."""
    mine = user_team(conn)
    out = []
    from . import hidden as HD                       # v35: injury proneness (centred: x1.0 for the average player)
    for pid, toi in sorted(played_players):
        tm = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()
        from .development import injury_factor as _intensity   # v40: training intensity
        if rng.random() >= BASE_PER_60 * toi / 3600.0 * HD.injury_factor(HD.of(conn, pid)["injury_proneness"]) * \
                _intensity(conn, tm[0] if tm else None):
            continue
        days = draw_days(rng)
        team_now = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()["team_id"]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
            from .staff import injury_multiplier
            days = max(1, round(days * injury_multiplier(conn, team_now)))
        ret = (datetime.date.fromisoformat(day) + datetime.timedelta(days=days)).isoformat()
        team = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()["team_id"]
        conn.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)",
                     (pid, day, ret, f"{days} day(s)"))
        conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (pid,))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                     "VALUES (?, 'injury', ?, ?, ?, ?)", (day, pid, team, team, f"out {days} day(s), back {ret}"))
        from .events import emit
        emit(conn, "PLAYER_INJURED", day, f"{_name(conn, pid)} injured, out about {days} day(s)", team_id=team,
             player_id=pid, importance=2 if days >= 30 else 1, days=days)
        if team == mine:
            add_message(conn, day, "Injury report", f"{_name(conn, pid)} is injured and will miss about {days} day(s) "
                                                     f"(expected back {ret}).")
        out.append((pid, team, days))
    return out


def heal_injuries(conn, day):
    """Return players whose expected_return <= day to active. Returns list of (player_id, team_id)."""
    mine = user_team(conn)
    ready = conn.execute("SELECT i.player_id, p.team_id FROM injuries i JOIN players p USING (player_id) "
                         "WHERE p.status='injured' AND i.expected_return <= ? "
                         "AND i.injury_id = (SELECT MAX(injury_id) FROM injuries WHERE player_id=i.player_id) "
                         "ORDER BY i.player_id", (day,)).fetchall()
    out = []
    for r in ready:
        pid, team = r["player_id"], r["team_id"]
        conn.execute("UPDATE players SET status='active' WHERE player_id=?", (pid,))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                     "VALUES (?, 'return', ?, ?, ?, 'returned from injury')", (day, pid, team, team))
        if team == mine:
            add_message(conn, day, "Player recovered", f"{_name(conn, pid)} has recovered and is available.")
        out.append((pid, team))
    return out
