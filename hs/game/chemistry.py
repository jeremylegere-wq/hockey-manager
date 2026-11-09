"""Line chemistry (phase B, v33): players who play together get better together.

Every regular-season game, each club's forward lines (the three pairs in a trio) and defence pairs add a game to
those pairs. A pair's chemistry is min(1, games together / FULL) and halves once they have been apart for a month
(not on the same line). The engine compares the two units on the ice (each unit's average over its pairs, as a
difference from the league's average pair) and moves even-strength attempts by Skill.chem per unit of difference
(0.05), so splitting a line that clicks costs something, and a club that never settles its lines gives a little away.
League-neutral: only the difference between two units counts, and chemistry is taken relative to the league average.
"""
from __future__ import annotations

import datetime

FULL = 30            # games together for full chemistry
APART_DAYS = 30


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS chemistry (team_id INTEGER, a INTEGER, b INTEGER, games INTEGER, last TEXT, "
                 "PRIMARY KEY (team_id, a, b))")


def _pairs(units):
    for u in units:
        ids = sorted(p.pid for p in u)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                yield a, b


def record(conn, team, day):
    """After a game: the club's lines and pairs (an engine Team) played together once more."""
    ensure_table(conn)
    rows = [(team.team_id, a, b, day) for a, b in _pairs(list(team.lines) + list(team.pairs))]
    conn.executemany("INSERT INTO chemistry (team_id, a, b, games, last) VALUES (?,?,?,1,?) ON CONFLICT(team_id, a, b) "
                     "DO UPDATE SET games=games+1, last=excluded.last", [(t, a, b, d) for t, a, b, d in rows])


def level(games, last, today):
    lv = min(1.0, (games or 0) / FULL)
    if last and (today - datetime.date.fromisoformat(last)).days > APART_DAYS:
        lv *= 0.5
    return lv


def load(conn, today):
    """{team_id: {frozenset({a, b}): chemistry relative to the league's average pair}} for the loader."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='chemistry'").fetchone():
        return {}
    today = datetime.date.fromisoformat(today) if isinstance(today, str) else today
    raw = {}
    for t, a, b, g, last in conn.execute("SELECT c.team_id, c.a, c.b, c.games, c.last FROM chemistry c JOIN players pa ON pa.player_id=c.a "
                                         "JOIN players pb ON pb.player_id=c.b WHERE pa.team_id=c.team_id AND pb.team_id=c.team_id"):
        raw.setdefault(t, {})[frozenset((a, b))] = level(g, last, today)
    vals = [v for d in raw.values() for v in d.values()]
    if not vals:
        return {}
    # the league's average pair on a line (pairs who are not together score 0 and pull the average down a little)
    m = sum(vals) / len(vals)
    return {t: {k: v - m for k, v in d.items()} for t, d in raw.items()}


def team_view(conn, team, today):
    """For the Lines screen: each of a club's current units with its chemistry (0-100)."""
    ensure_table(conn)
    today = datetime.date.fromisoformat(today) if isinstance(today, str) else today
    lv = {}
    for a, b, g, last in conn.execute("SELECT a, b, games, last FROM chemistry WHERE team_id=?", (team.team_id,)):
        lv[frozenset((a, b))] = (level(g, last, today), g)
    out = []
    for kind, units in (("F", team.lines), ("D", team.pairs)):
        for i, u in enumerate(units):
            pairs = [lv.get(frozenset((x.pid, y.pid)), (0.0, 0)) for k, x in enumerate(u) for y in u[k + 1:]]
            out.append(dict(unit=f"{kind}{i + 1}", players=[p.pid for p in u], chemistry=round(100 * sum(p[0] for p in pairs) / max(1, len(pairs))),
                            games=min((p[1] for p in pairs), default=0)))
    return out
