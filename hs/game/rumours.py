"""Trade rumours (defect 6): offers that go nowhere get out, and the players named in them hear about it.

When one of your offers is rejected, each of your players in it may become the subject of a rumour (the insider's
"X has been shopped"). The chance grows each time the same player is shopped (25% the first time, +15% a time after).
A rumour costs the player trust in you and morale, more if he is proud (ego) or loyal, and more each time; a proud
player shopped three times may ask out. When three or more of your players have been in rumours inside 30 days, the
room notices: cohesion drops and the head coach writes to you.
"""
from __future__ import annotations

import datetime
import random

from .events import emit, player_name, team_abbr
from .state import add_message

P_LEAK, P_LEAK_STEP = 0.25, 0.15
ROOM_WINDOW, ROOM_COUNT = 30, 3


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS shopped (player_id INTEGER PRIMARY KEY, team_id INTEGER, times INTEGER, leaks INTEGER, "
                 "last_day TEXT)")


def offer_rejected(conn, me, other, players, day):
    """Your offer to `other` was turned down; `players` are yours in it. Returns the rumour lines."""
    ensure_tables(conn)
    rng = random.Random(f"rumour-{me}-{other}-{day}-{','.join(map(str, players))}")
    out = []
    for pid in players:
        r = conn.execute("SELECT times, leaks FROM shopped WHERE player_id=?", (pid,)).fetchone()
        times = (r[0] if r else 0) + 1
        leaks = r[1] if r else 0
        leaked = rng.random() < P_LEAK + P_LEAK_STEP * (times - 1)
        conn.execute("INSERT OR REPLACE INTO shopped VALUES (?,?,?,?,?)", (pid, me, times, leaks + (1 if leaked else 0), day))
        if not leaked:
            continue
        name, ab, them = player_name(conn, pid), team_abbr(conn, me), team_abbr(conn, other)
        text = rng.choice([f"Hearing {ab} have been shopping {name}. Talks with {them} went nowhere, but he's available.",
                           f"{name}'s name is out there. {ab} made a pitch to {them}; it didn't land.",
                           f"Teams calling {ab} are being told {name} can be had. {them} passed for now."])
        emit(conn, "RUMOUR", day, text, team_id=me, other_team_id=other, player_id=pid, importance=2, kind="shopped", times=times)
        out.append(text)
        _hurt(conn, me, pid, leaks + 1, day)
    _room(conn, me, day)
    return out


def _hurt(conn, me, pid, n, day):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        return
    from .people import traits
    tr = traits(conn, pid)
    hit = 3 + 2 * (n - 1) + max(0, tr["ego"] - 10) * 0.4 + max(0, tr["loyalty"] - 10) * 0.3
    conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-?), morale=MAX(0, morale-?) WHERE player_id=?", (hit, hit * 0.6, pid))
    from .people import log_event
    log_event(conn, pid, day, "trust_mgmt", -hit * 0.6, "read his name in trade rumours" + (f" ({n} times)" if n > 1 else ""))
    if n >= 3 and tr["ego"] >= 14:
        conn.execute("UPDATE morale SET trade_request=1 WHERE player_id=?", (pid,))
        emit(conn, "TRADE_REQUEST", day, f"{player_name(conn, pid)} asks for a trade after hearing his name in rumours again",
             team_id=me, player_id=pid, importance=3)
        add_message(conn, day, f"{player_name(conn, pid)} wants out",
                    f"His agent called: {player_name(conn, pid)} has read his name in trade rumours {n} times and would like "
                    "a fresh start. He is asking for a trade.")


def _room(conn, me, day):
    since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=ROOM_WINDOW)).isoformat()
    n = conn.execute("SELECT COUNT(*) FROM shopped WHERE team_id=? AND leaks>0 AND last_day>=?", (me, since)).fetchone()[0]
    key = f"rumour_room_{me}_{day[:7]}"
    if n < ROOM_COUNT or conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_room'").fetchone():
        conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-3) WHERE team_id=?", (me,))
    add_message(conn, day, "The room has noticed",
                f"From the head coach: {n} of our guys have read their names in trade rumours this month. They're asking each other "
                "who's next. I can keep them focused, but it would help to keep our talks quieter for a while.")
