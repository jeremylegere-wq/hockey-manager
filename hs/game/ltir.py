"""Long-term injured reserve (docs/LTIR.md).

Eligible: an injured player expected to miss at least 10 of his club's NHL games and 24 days. His cap hit stays on
the payroll, but the club may spend past the cap: the first time it puts someone on LTIR, its accruable cap space
limit is fixed at the cap minus its cap space that day (its payroll, if it is under the cap); while anyone is on
LTIR its ceiling is that limit plus the relief pool (the cap hits of everyone on LTIR). A club below that ceiling
does not bank anything, and the limit resets once nobody is on LTIR. When a player is fit again he can only be
activated if the club is cap compliant without his relief; AI clubs send players down until they are (at most three
moves, then they activate him anyway and stay over), the user is told and activates him with `activate`. Players on
LTIR do not count against the roster limit. LTIR ends with the regular season.
Sources: CapFriendly's LTIR FAQ (2017) for the limit and pool; the 2026-30 CBA's changes to LTIR and the
playoffs are not modelled.
"""
from __future__ import annotations

import datetime

from . import contracts as K
from . import roster as R
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

MIN_DAYS, MIN_GAMES = 24, 10
AI_PLACE_ROOM = 3_000_000       # AI clubs use LTIR when an eligible injury leaves them this close to the cap


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS ltir (ltir_id INTEGER PRIMARY KEY, player_id INTEGER, team_id INTEGER, "
                 "placed TEXT, cap_hit INTEGER, earliest TEXT, ended TEXT, outcome TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS ltir_limit (team_id INTEGER PRIMARY KEY, acsl INTEGER, since TEXT)")


def _has(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='ltir'").fetchone() is not None


def active(conn, team):
    if not _has(conn):
        return []
    return conn.execute("SELECT * FROM ltir WHERE team_id=? AND ended IS NULL ORDER BY ltir_id", (team,)).fetchall()


def ceiling(conn, team):
    """The club's effective cap ceiling today (the cap, or its accruable limit plus the relief pool)."""
    cap = K.crules(conn)["cap_ceiling"]
    if cap is None or not _has(conn):
        return cap
    rows = active(conn, team)
    if not rows:
        return cap
    lim = conn.execute("SELECT acsl FROM ltir_limit WHERE team_id=?", (team,)).fetchone()
    acsl = lim[0] if lim else cap
    return max(cap, acsl + sum(r["cap_hit"] for r in rows))


def _expected_return(conn, pid):
    r = conn.execute("SELECT expected_return FROM injuries WHERE player_id=? ORDER BY injury_id DESC LIMIT 1",
                     (pid,)).fetchone()
    return r[0] if r else None


def games_missed(conn, team, day, until):
    return conn.execute("SELECT COUNT(*) FROM games WHERE played=0 AND game_type='RS' AND game_date>=? AND "
                        "game_date<? AND (home_team_id=? OR away_team_id=?)", (day, until, team, team)).fetchone()[0]


def eligible(conn, pid, day=None):
    """(ok, why) for putting this player on LTIR today."""
    day = day or get_state(conn)[0]
    p = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
    if K.season_state(conn) != "regular_season":
        return False, "LTIR is used during the regular season."
    if p is None or p["status"] != "injured":
        return False, "Only injured players can go on LTIR."
    back = _expected_return(conn, pid)
    if back is None:
        return False, "No injury on record."
    days = (datetime.date.fromisoformat(back) - datetime.date.fromisoformat(day)).days
    games = games_missed(conn, p["team_id"], day, back)
    if days < MIN_DAYS or games < MIN_GAMES:
        return False, f"He is expected back in {days} days and {games} games (LTIR needs {MIN_DAYS} days and " \
                      f"{MIN_GAMES} games)."
    if K.current_contract(conn, pid) is None:
        return False, "He has no contract."
    return True, f"Out {days} days and {games} games."


def place(conn, pid, day=None):
    ensure_tables(conn)
    day = day or get_state(conn)[0]
    ok, why = eligible(conn, pid, day)
    if not ok:
        raise R.RosterError(why)
    team = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    cap = K.crules(conn)["cap_ceiling"]
    if not active(conn, team):                         # the limit is fixed when a club enters LTIR
        acsl = min(cap, K.payroll(conn, team)) if cap else 0
        conn.execute("INSERT OR REPLACE INTO ltir_limit VALUES (?,?,?)", (team, acsl, day))
    hit = K.current_contract(conn, pid)["cap_hit"]
    earliest = (datetime.date.fromisoformat(day) + datetime.timedelta(days=MIN_DAYS)).isoformat()
    conn.execute("INSERT INTO ltir (player_id, team_id, placed, cap_hit, earliest) VALUES (?,?,?,?,?)",
                 (pid, team, day, hit, earliest))
    conn.execute("UPDATE players SET status='ltir' WHERE player_id=?", (pid,))
    R._log(conn, day, "ltir", pid, team, team, f"placed on LTIR ({why.lower()})")
    emit(conn, "PLAYER_INJURED", day, f"{team_abbr(conn, team)} place {player_name(conn, pid)} on LTIR",
         team_id=team, player_id=pid, importance=2, kind="ltir", cap_hit=hit)
    return f"{player_name(conn, pid)} is on LTIR. {why} Your ceiling is now ${ceiling(conn, team):,.0f}."


def _close(conn, row, day, outcome):
    conn.execute("UPDATE ltir SET ended=?, outcome=? WHERE ltir_id=?", (day, outcome, row["ltir_id"]))
    if not active(conn, row["team_id"]):
        conn.execute("DELETE FROM ltir_limit WHERE team_id=?", (row["team_id"],))


def compliant_without(conn, team, row):
    """Payroll fits under the ceiling the club would have once this player leaves LTIR."""
    cap = K.crules(conn)["cap_ceiling"]
    if cap is None:
        return True
    others = [r for r in active(conn, team) if r["ltir_id"] != row["ltir_id"]]
    if others:
        lim = conn.execute("SELECT acsl FROM ltir_limit WHERE team_id=?", (team,)).fetchone()[0]
        ceil = max(cap, lim + sum(r["cap_hit"] for r in others))
    else:
        ceil = cap
    return K.payroll(conn, team) <= ceil


def activate(conn, pid, day=None, force=False):
    ensure_tables(conn)
    day = day or get_state(conn)[0]
    row = conn.execute("SELECT * FROM ltir WHERE player_id=? AND ended IS NULL", (pid,)).fetchone()
    if row is None:
        raise R.RosterError("He is not on LTIR.")
    back = _expected_return(conn, pid)
    if back and back > day:
        raise R.RosterError(f"He is not fit yet (expected back {back}).")
    if day < row["earliest"]:
        raise R.RosterError(f"Players stay on LTIR at least {MIN_DAYS} days (until {row['earliest']}).")
    if not force and not compliant_without(conn, row["team_id"], row):
        over = K.payroll(conn, row["team_id"]) - (K.crules(conn)["cap_ceiling"] or 0)
        raise R.RosterError(f"Activating him would leave you over the cap (about ${over:,.0f} over without his "
                            "relief); send down, trade or waive salary first.")
    _, mx = R.limits(conn)
    team = row["team_id"]
    if not force and len(R.roster(conn, team)) >= mx:
        raise R.RosterError(f"Your roster is full ({mx}); send someone down first.")
    conn.execute("UPDATE players SET status='active' WHERE player_id=?", (pid,))
    _close(conn, row, day, "activated")
    R._log(conn, day, "return", pid, team, team, "activated from LTIR")
    return f"{player_name(conn, pid)} is activated from LTIR."


def daily(conn, day):
    """Fit players come off LTIR (AI clubs get compliant first); AI clubs put eligible injuries on LTIR when they
    are close to the cap. Returns lines for the user."""
    if K.season_state(conn) != "regular_season":
        return []
    ensure_tables(conn)
    me = user_team(conn)
    out = []
    for row in conn.execute("SELECT * FROM ltir WHERE ended IS NULL").fetchall():
        back = _expected_return(conn, row["player_id"])
        if (back and back > day) or day < row["earliest"]:
            continue
        team, pid = row["team_id"], row["player_id"]
        if team == me:
            if not conn.execute("SELECT 1 FROM inbox WHERE subject='Ready to come off LTIR' AND body LIKE ?",
                                (f"%#{pid})%",)).fetchone():
                add_message(conn, day, "Ready to come off LTIR",
                            f"{player_name(conn, pid)} (#{pid}) is fit. To activate him you must be cap compliant "
                            "without his relief: `activate " + str(pid) + "` (or the button on the Roster screen).")
            continue
        for _ in range(3):                             # AI: make room under the cap, then bring him back
            if compliant_without(conn, team, row):
                break
            cands = sorted(((K.current_contract(conn, r["player_id"]) or {"cap_hit": 0})["cap_hit"], r["player_id"])
                           for r in R.roster(conn, team) if r["status"] == "active")
            buriable = [c for c in cands if c[0] > K.crules(conn)["min_salary"]]
            if not buriable:
                break
            R.send_down(conn, team, R._lowest_healthy(conn, team)[1], day, "assigned to the minors (cap, LTIR return)")
        _, mx = R.limits(conn)
        while len(R.roster(conn, team)) >= mx:
            R.make_room(conn, team, day, None)
        activate(conn, pid, day, force=True)
    # AI clubs: new long injuries
    for r in conn.execute("SELECT p.player_id, p.team_id FROM players p WHERE p.status='injured' AND p.team_id IS NOT "
                          "NULL").fetchall():
        if r["team_id"] == me or active_row(conn, r["player_id"]):
            continue
        ok, _ = eligible(conn, r["player_id"], day)
        if not ok:
            continue
        room = K.cap_room(conn, r["team_id"])
        if room is not None and room < AI_PLACE_ROOM:
            place(conn, r["player_id"], day)
    return out


def active_row(conn, pid):
    return conn.execute("SELECT 1 FROM ltir WHERE player_id=? AND ended IS NULL", (pid,)).fetchone() is not None


def end_of_season(conn, day):
    """LTIR ends with the regular season: everyone comes off (still injured if not healed)."""
    if not _has(conn):
        return
    for row in conn.execute("SELECT * FROM ltir WHERE ended IS NULL").fetchall():
        back = _expected_return(conn, row["player_id"])
        conn.execute("UPDATE players SET status=? WHERE player_id=? AND status='ltir'",
                     ("injured" if back and back > day else "active", row["player_id"]))
        _close(conn, row, day, "season over")
