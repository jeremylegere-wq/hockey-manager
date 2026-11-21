"""How each club is covered (v0.62, issue #12; docs/PRESS.md "The club's media").

Coverage level (1-5) follows the market (the club's finance profile, 1-10): a big market has more reporters, more
press conferences after games and more at stake in each one.

  coverage   1      2      3      4      5
  post-game  1/10   1/8    1/6    1/5    1/4     chance of a press conference after a game with no story
  pressure   30     35     40     45     50      the base of every press conference's pressure (it scales the effects)

Base attitude: the local media's lean, fixed for the save (seeded by club; bigger markets lean critical more often):
critical (45), neutral (55) or friendly (65). Each Monday the media's mood drifts toward 3/4 of what the results say
and 1/4 of the lean, and toward the lean alone when there are no results yet.

Focus players: each season the media picks up to three players at your club to follow: the star (the best player),
the phenom (the best player 22 or under) and the contract (the highest cap hit among players worth less than the
club's median for what they are paid). Questions about a player go to them first. When one leaves, the media picks
again.
"""
from __future__ import annotations

import random

from .state import get_state

COVERAGE_POSTGAME = {1: 1 / 10, 2: 1 / 8, 3: 1 / 6, 4: 1 / 5, 5: 1 / 4}
ATTITUDE_BASE = {"critical": 45.0, "neutral": 55.0, "friendly": 65.0}
ATTITUDE_WORDS = {"critical": "critical: quick to turn on a bad week", "neutral": "neutral: it follows the results",
                  "friendly": "friendly: slow to turn on the club"}
FOCUS_KINDS = ("star", "phenom", "contract")


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS media_focus (team_id INTEGER, season INTEGER, player_id INTEGER, kind TEXT, "
                 "PRIMARY KEY (team_id, season, kind))")


def _market(conn, t):
    try:
        from . import finance as FN
        p = FN.profile(conn, t)
        return int(p["market"]) if p and p.get("market") is not None else 5
    except Exception:
        return 5


def coverage(conn, t):
    m = max(1, min(10, _market(conn, t)))
    return 1 + round((m - 1) * 4 / 9)


def attitude(conn, t):
    seed = get_state(conn)[1]
    rng = random.Random(f"{seed}-media-attitude-{t}")
    c = coverage(conn, t)
    w = {"critical": 1 + 0.5 * (c - 1), "neutral": 3.0, "friendly": 1 + 0.5 * (5 - c)}
    return rng.choices(list(w), weights=list(w.values()))[0]


def base_sentiment(conn, t):
    return ATTITUDE_BASE[attitude(conn, t)]


def postgame_chance(conn, t):
    return COVERAGE_POSTGAME[coverage(conn, t)]


def base_pressure(conn, t):
    return 25 + 5 * coverage(conn, t)


def _season(conn):
    from .contracts import season_year
    return season_year(conn)


def focus_players(conn, t):
    """[(player_id, kind)] the media follows at this club this season (chosen once, chosen again if one leaves)."""
    ensure_tables(conn)
    y = _season(conn)
    rows = conn.execute("SELECT f.player_id, f.kind FROM media_focus f JOIN players p USING (player_id) WHERE f.team_id=? AND "
                        "f.season=? AND p.team_id=? AND p.status IN ('active','injured')", (t, y, t)).fetchall()
    have = {k for _, k in rows}
    if len(rows) == conn.execute("SELECT COUNT(*) FROM media_focus WHERE team_id=? AND season=?", (t, y)).fetchone()[0] \
            and have:
        return sorted(((p, k) for p, k in rows), key=lambda x: FOCUS_KINDS.index(x[1]))
    conn.execute("DELETE FROM media_focus WHERE team_id=? AND season=?", (t, y))
    from . import contracts as K
    from .roster import player_value
    roster = conn.execute("SELECT player_id, birth_date FROM players WHERE team_id=? AND status IN ('active','injured')", (t,)).fetchall()
    if not roster:
        return []
    val = {r[0]: player_value(conn, r[0]) for r in roster}
    picked = []
    star = max(val, key=lambda p: (val[p], -p))
    picked.append((star, "star"))
    young = [r[0] for r in roster if r[1] and y - int(r[1][:4]) <= 22 and r[0] != star]
    if young:
        picked.append((max(young, key=lambda p: (val[p], -p)), "phenom"))
    caps = {}
    for p in val:
        c = K.current_contract(conn, p, y)
        if c:
            caps[p] = c["cap_hit"]
    if caps:
        ratio = {p: val[p] / max(1.0, caps[p] / 1e6) for p in caps}
        med = sorted(ratio.values())[len(ratio) // 2]
        under = [p for p in caps if ratio[p] < med and p not in {x for x, _ in picked}]
        if under:
            picked.append((max(under, key=lambda p: (caps[p], -p)), "contract"))
    conn.executemany("INSERT OR REPLACE INTO media_focus VALUES (?,?,?,?)", [(t, y, p, k) for p, k in picked])
    return picked


def profile(conn, t):
    """For the press room: coverage, attitude and the focus players."""
    from .events import player_name
    a = attitude(conn, t)
    c = coverage(conn, t)
    return dict(coverage=c, coverage_words=["", "light", "modest", "steady", "heavy", "saturation"][c],
                attitude=a, attitude_words=ATTITUDE_WORDS[a], base=ATTITUDE_BASE[a],
                postgame=round(postgame_chance(conn, t), 3), pressure=base_pressure(conn, t),
                focus=[dict(player_id=p, name=player_name(conn, p), kind=k) for p, k in focus_players(conn, t)])
