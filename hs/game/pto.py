"""Professional tryouts (v39, register #18; docs/PTO.md).

From the arbitration phase to the start of the season you can bring up to three unsigned free agents to training
camp on a professional tryout. A player on a tryout has no contract and counts against nothing; other clubs cannot
sign him while he is in your camp. Camp shows you exactly what he is: on opening day the head coach reports where he
would fit on your depth chart, with his ratings, and you sign him (one year at his asking price, or less if you
negotiate) or let him go. Tryouts end at the start of the regular season; anyone you have not signed by the end of
opening week goes back to free agency.
"""
from __future__ import annotations

import datetime

from . import contracts as K
from . import roster as R
from .events import emit, player_name
from .state import add_message, get_state, user_team

MAX_PTO = 3
WINDOW = ("arbitration", "awards", "preseason")
GRACE_DAYS = 7


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS pto (player_id INTEGER PRIMARY KEY, team_id INTEGER, since TEXT, "
                 "status TEXT DEFAULT 'camp', report TEXT)")


def current(conn, team=None):
    ensure_table(conn)
    team = user_team(conn) if team is None else team
    return [dict(r) for r in conn.execute("SELECT * FROM pto WHERE team_id=? AND status IN ('camp','report') ORDER BY since",
                                          (team,))]


def held(conn):
    """Players on any club's tryout (kept out of the free-agent pool)."""
    ensure_table(conn)
    return {r[0] for r in conn.execute("SELECT player_id FROM pto WHERE status IN ('camp','report')")}


def invite(conn, pid, day=None):
    ensure_table(conn)
    me = user_team(conn)
    day = day or get_state(conn)[0]
    if K.season_state(conn) not in WINDOW:
        raise R.RosterError("Tryouts run from the arbitration phase to the start of the season (training camp).")
    p = conn.execute("SELECT team_id, club_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] is not None or p["club_id"] is not None or p["status"] != "active":
        raise R.RosterError("Only unsigned free agents can come to camp on a tryout.")
    if pid in held(conn):
        raise R.RosterError(f"{player_name(conn, pid)} is already at a camp on a tryout.")
    if len(current(conn, me)) >= MAX_PTO:
        raise R.RosterError(f"You can have at most {MAX_PTO} players on tryouts.")
    conn.execute("INSERT OR REPLACE INTO pto (player_id, team_id, since, status) VALUES (?,?,?, 'camp')", (pid, me, day))
    emit(conn, "PLAYER_SIGNED", day, f"{player_name(conn, pid)} joins {_abbr(conn, me)} camp on a professional tryout",
         team_id=me, player_id=pid, importance=1, kind="pto")
    return f"{player_name(conn, pid)} will come to training camp on a professional tryout (no contract)."


def release(conn, pid, day=None):
    ensure_table(conn)
    day = day or get_state(conn)[0]
    conn.execute("UPDATE pto SET status='released' WHERE player_id=?", (pid,))
    return f"{player_name(conn, pid)}'s tryout is over; he is a free agent again."


def _abbr(conn, t):
    r = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()
    return r[0] if r else "?"


def _fit(conn, pid, team):
    """Where he would slot on the club's depth chart at his position, in words."""
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = R.group(pos)
    v = R.player_value(conn, pid)
    mine = sorted((R.player_value(conn, r["player_id"]) for r in R.roster(conn, team) if R.group(r["position"]) == g),
                  reverse=True)
    rank = 1 + sum(1 for x in mine if x > v)
    word = {"F": "forward", "D": "defenceman", "G": "goalie"}[g]
    dressed = {"F": 12, "D": 6, "G": 2}[g]
    verdict = ("would play every night" if rank <= dressed - 2 else "is a depth option, about where your last regulars are"
               if rank <= dressed + 1 else "would be in the press box or the minors")
    return rank, f"He would be your {rank}{'st' if rank == 1 else 'nd' if rank == 2 else 'rd' if rank == 3 else 'th'}-best {word}: he {verdict}."


def camp_reports(conn, day):
    """Opening day: the head coach reports on each tryout, with a sign-or-release choice."""
    ensure_table(conn)
    me = user_team(conn)
    out = []
    for r in current(conn, me):
        if r["status"] != "camp":
            continue
        pid = r["player_id"]
        rank, words = _fit(conn, pid, me)
        ask = K.asking(conn, pid, "UFA")
        conn.execute("UPDATE pto SET status='report', report=? WHERE player_id=?", (words, pid))
        name = player_name(conn, pid)
        from .state import staff_sender
        add_message(conn, day, f"Camp report: {name}", f"{name} finished camp on his tryout. {words} His agent asks "
                    f"${ask:,.0f} for one year. Sign him or let him go; if you do neither he is a free agent again "
                    f"after opening week.", sender=staff_sender(conn, "HC", me),
                    actions=[dict(label=f"Sign {name} (1 yr, ${ask / 1e6:.2f}M)", cmd=f"sign {pid} {ask} 1", primary=True),
                             dict(label="Negotiate", href=f"#player/{pid}"),
                             dict(label="Let him go", cmd=f"pto release {pid}")])
        out.append(f"Tryout: {name}: {words}")
    return out


def daily(conn, day):
    """End tryouts that have run past opening week."""
    ensure_table(conn)
    if K.season_state(conn) != "regular_season":
        return
    for r in conn.execute("SELECT player_id, since FROM pto WHERE status='report'").fetchall():
        p = conn.execute("SELECT team_id FROM players WHERE player_id=?", (r[0],)).fetchone()
        if p and p[0] is not None:
            conn.execute("UPDATE pto SET status='signed' WHERE player_id=?", (r[0],))
            continue
        first = conn.execute("SELECT MIN(game_date) FROM games WHERE game_type='RS' AND season_id=(SELECT season_id "
                             "FROM seasons ORDER BY start_year DESC LIMIT 1)").fetchone()[0]
        if first and (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(first[:10])).days >= GRACE_DAYS:
            conn.execute("UPDATE pto SET status='released' WHERE player_id=?", (r[0],))
