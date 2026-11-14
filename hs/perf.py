"""Read caches that cannot go stale (v60; docs/PERFORMANCE.md).

A sim day asks the same questions of the database thousands of times (a player's value, a club's roster) between
writes. `memo(conn, name)` returns a dict that lives exactly as long as the database is unchanged: sqlite counts every
row it inserts, updates or deletes (`Connection.total_changes`), and the dict is thrown away the moment that count
moves. So a cached answer is always the answer the query would give, and results are identical with or without it.

The count only sees this connection's own writes, so the cache is used only while a connection is simulating
(`with simulating(conn):` in hs/game/dayloop.py), when nothing else writes to the save. Any other reader (the
interface's own connections) gets a fresh dict every time and so always reads the database.
"""
from __future__ import annotations

from contextlib import contextmanager

_live = []           # [conn, depth, total_changes, {name: dict}] for connections that are simulating


@contextmanager
def simulating(conn):
    e = next((x for x in _live if x[0] is conn), None)
    if e is None:
        e = [conn, 0, conn.total_changes, {}]
        _live.append(e)
    e[1] += 1
    try:
        yield
    finally:
        e[1] -= 1
        if e[1] <= 0:
            _live.remove(e)


def memo(conn, name):
    for e in _live:
        if e[0] is conn:
            tc = conn.total_changes
            if e[2] != tc:
                e[2], e[3] = tc, {}
            d = e[3].get(name)
            if d is None:
                d = e[3][name] = {}
            return d
    return {}
