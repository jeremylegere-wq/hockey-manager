"""The native ratings layer in a save (v38; the model is in hs/attributes.py).

`player_ratings` holds each player's ratings (42 attributes, current and potential ability, position and role
ratings). The engine attributes in `player_attributes` are derived from them with the save's engine scale
(pack_info 'engine_scale': {attr: [a, b], "_ca": {"S": [a, b], "G": [a, b]}}), written by an import that carries ratings, or empty
(identity) for packs that carry engine attributes only, whose ratings are back-filled from them.

Development (hs/game/world.py) moves the ratings and re-derives the engine attributes; `set_ratings` does the same
for an edit.
"""
from __future__ import annotations

import json
import sqlite3

from ..attributes import (ABILITY_MAX, ALL_ATTRS, BODY, DEVELOPS, MIND, NATIVE_ATTRS, RATING_COLS, RATING_MAX, RATING_MIN,
                          ability_of, derive, ratings_from_engine)


def _q(conn, sql, args=()):
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(sql, args)


def ensure_table(conn):
    conn.execute(f"CREATE TABLE IF NOT EXISTS player_ratings (player_id INTEGER PRIMARY KEY, "
                 f"{', '.join(c + ' INTEGER' for c in RATING_COLS)})")


def scale_of(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='engine_scale'").fetchone()
    if not r:
        return {}, None
    d = json.loads(r[0])
    ca = d.pop("_ca", None)
    if isinstance(ca, list):                          # an older single (a, b)
        ca = {"S": tuple(ca), "G": tuple(ca)}
    elif isinstance(ca, dict):
        ca = {k: tuple(v) for k, v in ca.items()}
    return {k: tuple(v) for k, v in d.items()}, ca


def set_scale(conn, scale, ca):
    d = {k: list(v) for k, v in scale.items()}
    if ca:
        d["_ca"] = {k: list(v) for k, v in ca.items()} if isinstance(ca, dict) else list(ca)
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('engine_scale', ?)", (json.dumps(d),))


def _overall(engine, pos):
    from ..worldgen import overall_of
    return overall_of(engine, pos)


def backfill(conn):
    """Ratings for every player who has engine attributes and no ratings (one batch). Returns how many."""
    ensure_table(conn)
    scale, ca = scale_of(conn)
    rows = _q(conn, "SELECT a.*, p.position, d.potential dpot FROM player_attributes a JOIN players p USING (player_id) "
                        "LEFT JOIN player_dev d USING (player_id) WHERE a.player_id NOT IN (SELECT player_id FROM player_ratings)").fetchall()
    out = []
    for r in rows:
        eng = {a: r[a] for a in ALL_ATTRS}
        pos = r["position"]
        ov = _overall(eng, pos)
        pot = r["dpot"] if r["dpot"] is not None else r["potential"]
        rt = ratings_from_engine(eng, pos, scale, ca, overall=ov, potential=pot)
        out.append([r["player_id"]] + [rt.get(c) for c in RATING_COLS])
    if out:
        conn.executemany(f"INSERT OR REPLACE INTO player_ratings (player_id, {', '.join(RATING_COLS)}) VALUES "
                         f"({', '.join('?' * (len(RATING_COLS) + 1))})", out)
    return len(out)


def of(conn, pid):
    ensure_table(conn)
    r = _q(conn, "SELECT * FROM player_ratings WHERE player_id=?", (pid,)).fetchone()
    if r is None:
        backfill(conn)
        r = _q(conn, "SELECT * FROM player_ratings WHERE player_id=?", (pid,)).fetchone()
    return {c: r[c] for c in RATING_COLS} if r else None


def carry_ability(prev, new, pos, scale, ca):
    """Current ability after the ratings change from prev to new: it moves with the overall the ratings stand for
    (an imported world, where ability anchors the level). Without an ability scale it is read off the ratings."""
    from ..attributes import raw_overall
    if not ca or prev.get("current_ability") in (None, ""):
        return ability_of(raw_overall(new, pos, scale), ca, pos)
    a = (ca.get("G" if pos == "G" else "S") if isinstance(ca, dict) else ca)[0]
    d = raw_overall(new, pos, scale) - raw_overall(prev, pos, scale)
    return max(1, min(ABILITY_MAX, int(round(prev["current_ability"] + a * d))))


def write(conn, pid, ratings, pos, prev=None):
    """Store ratings and re-derive the engine attributes (the one write path for both layers). prev: the ratings
    before a change, so current ability moves with it (an explicit ability edit wins)."""
    ensure_table(conn)
    scale, ca = scale_of(conn)
    ratings = dict(ratings)
    if prev is not None and ratings.get("current_ability") == prev.get("current_ability"):
        ratings["current_ability"] = carry_ability(prev, ratings, pos, scale, ca)
    if not ca or ratings.get("current_ability") in (None, ""):
        eng = derive(ratings, pos, scale)
        ratings["current_ability"] = ability_of(_overall(eng, pos), ca, pos)
    else:
        eng = derive(ratings, pos, scale, ca)
    if ratings.get("potential_ability") not in (None, ""):
        ratings["potential_ability"] = max(ratings["current_ability"], ratings["potential_ability"])
    conn.execute(f"INSERT OR REPLACE INTO player_ratings (player_id, {', '.join(RATING_COLS)}) VALUES "
                 f"({', '.join('?' * (len(RATING_COLS) + 1))})", [pid] + [ratings.get(c) for c in RATING_COLS])
    conn.execute(f"UPDATE player_attributes SET {', '.join(f'{a}=?' for a in ALL_ATTRS)} WHERE player_id=?",
                 [eng[a] if eng[a] != "" else None for a in ALL_ATTRS] + [pid])
    return eng


def set_ratings(conn, pid, changes):
    """An edit: {rating: value}. Values are clamped; the engine attributes follow."""
    cur = of(conn, pid)
    if cur is None:
        raise ValueError("No such player.")
    prev = dict(cur)
    bad = [k for k in changes if k not in RATING_COLS]
    if bad:
        raise ValueError(f"Unknown rating: {bad[0]}.")
    for k, v in changes.items():
        lo, hi = (1, ABILITY_MAX) if k in ("current_ability", "potential_ability") else (RATING_MIN, RATING_MAX)
        cur[k] = max(lo, min(hi, int(v)))
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    return write(conn, pid, cur, pos, prev)


def engine_delta_scale(conn, pos):
    """How far one rating point moves an engine attribute, on average over the ones that make the overall."""
    from ..attributes import COMPOSITES
    from ..worldgen import GOALIE_KEYS, SKATER_KEYS
    scale, _ = scale_of(conn)
    keys = GOALIE_KEYS if pos == "G" else SKATER_KEYS
    dev = set(DEVELOPS["G" if pos == "G" else "S"])
    tot = 0.0
    for k in keys:
        rec = COMPOSITES[k]
        share = sum(w for a, w in rec.items() if a in dev) / sum(rec.values())
        tot += (scale[k][0] if k in scale else 1.0) * share
    return tot / len(keys) or 1.0


def develop(ratings, pos, delta_engine, rng, age, focus=(), k=1.0, noise=0.12):
    """One summer on the ratings: the change the development model wants in the engine overall (delta_engine),
    spread over the ratings that develop, the body ageing first and the mind last (as in worldgen.apply_change)."""
    keys = DEVELOPS["G" if pos == "G" else "S"]
    delta = delta_engine / (k or 1.0)

    def mult(a):
        if delta < 0:
            m = 1.4 if a in BODY else 0.5 if a in MIND else 1.0
        else:
            m = 1.15 if (a in MIND and age >= 22) else 0.9 if (a in BODY and age >= 24) else 1.0
        if a in focus:
            m *= 1.6 if delta >= 0 else 0.6
        return m
    norm = len(keys) / sum(mult(a) for a in keys)
    out = dict(ratings)
    from ..worldgen import stochastic_round
    for a in keys:
        v = ratings.get(a)
        if v is None:
            continue
        out[a] = max(RATING_MIN, min(RATING_MAX, stochastic_round(v + delta * mult(a) * norm + (rng.gauss(0, noise) if noise else 0.0), rng)))
    return out


def focus_ratings(engine_focus):
    """A training focus is named in engine attributes (hs/game/training.py); the ratings that feed them."""
    from ..attributes import COMPOSITES
    return tuple(sorted({k for e in engine_focus for k in COMPOSITES.get(e, {})}))
