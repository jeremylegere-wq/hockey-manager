"""Rivalries (phase F, v37): a real rivalry model in place of "same division = rivalry".

Every pair of top-league clubs has rivalry points, 0-100:
  * a base: 22 for the same division, 10 for the same conference, 0 otherwise; +30 for a traditional rivalry
    (finance.RIVALS, or a pack's own list in pack_info 'rivalries': [["TOR", "MTL", 30], ...])
  * regular-season meetings add heat: +0.4 a game, +0.4 more when it is decided by one goal or in overtime, +0.3
    for a chippy one (ten or more penalties between them)
  * playoff meetings add the most: +2 a game, +8 for the series, +4 more for a seventh game, +6 more for a final
  * each summer the heat cools: points move a quarter of the way back to the base
Levels: under 30 none; 30-49 simmering (a potential rivalry); 50-69 rivalry; 70-84 heated; 85+ bitter.
A club's main rival is its highest pair at 50 or more; its potential rivals are pairs 35-49 that warmed this season.

What a rivalry (50+) does:
  * big games: the hidden "big games" attribute (hs/game/hidden.py), which used to count only in the playoffs,
    counts in rivalry games too. It is centred on the league's average, so league scoring does not move
  * the press room treats the game as a rivalry game (pressure, the questions; hs/game/press.py)
  * the gate: +3% demand (+5% heated or bitter) for the home club (hs/game/finance.py)
  * fan swings: your fans swing harder after a rivalry game, win or lose (+-1.5 to 3 on their mood)
"""
from __future__ import annotations

import json

from ..schema import top_league_sql

LEVELS = ((85, "bitter"), (70, "heated"), (50, "rivalry"), (30, "simmering"), (0, "none"))
BIG = 50
COOL = 0.25


def ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS rivalries (a INTEGER, b INTEGER, base REAL, points REAL, season_start REAL, "
                 "PRIMARY KEY (a, b))")
    if not conn.execute("SELECT 1 FROM rivalries LIMIT 1").fetchone():
        seed(conn)


def _key(x, y):
    return (x, y) if x < y else (y, x)


def _traditional(conn):
    abbr = {r[0]: r[1] for r in conn.execute(f"SELECT abbr, team_id FROM teams WHERE {top_league_sql()}")}
    out = {}
    r = conn.execute("SELECT value FROM pack_info WHERE key='rivalries'").fetchone()
    pairs = []
    if r:
        try:
            pairs = [(x[0], x[1], float(x[2]) if len(x) > 2 else 30.0) for x in json.loads(r[0])]
        except (ValueError, TypeError, IndexError):
            pairs = []
    else:
        from .finance import RIVALS
        pairs = [(a, b, 30.0) for a, b in RIVALS.items()]
    for a, b, pts in pairs:
        if a in abbr and b in abbr and a != b:
            out[_key(abbr[a], abbr[b])] = pts
    return out


def seed(conn):
    teams = conn.execute(f"SELECT team_id, conference, division FROM teams WHERE {top_league_sql()} ORDER BY team_id").fetchall()
    trad = _traditional(conn)
    rows = []
    for i, x in enumerate(teams):
        for y in teams[i + 1:]:
            base = 22.0 if x["division"] and x["division"] == y["division"] else 10.0 if x["conference"] and x["conference"] == y["conference"] else 0.0
            base += trad.get(_key(x["team_id"], y["team_id"]), 0.0)
            rows.append((x["team_id"], y["team_id"], base, base, base))
    conn.executemany("INSERT OR REPLACE INTO rivalries VALUES (?,?,?,?,?)", rows)


def level_name(p):
    return next(n for t, n in LEVELS if p >= t)


def points(conn, x, y):
    ensure(conn)
    r = conn.execute("SELECT points FROM rivalries WHERE a=? AND b=?", _key(x, y)).fetchone()
    return r[0] if r else 0.0


def all_points(conn):
    ensure(conn)
    return {(a, b): p for a, b, p in conn.execute("SELECT a, b, points FROM rivalries")}


def is_big(pts_map, x, y):
    return pts_map.get(_key(x, y), 0.0) >= BIG


def _add(conn, x, y, d):
    conn.execute("UPDATE rivalries SET points=MIN(100, points+?) WHERE a=? AND b=?", (d,) + _key(x, y))


def after_game(conn, gid, h, a, hg, ag, ot, me=None, pts_map=None):
    """A regular-season meeting: heat, and your fans' swing after a rivalry game."""
    ensure(conn)
    d = 0.4 + (0.4 if abs(hg - ag) <= 1 or ot else 0.0)
    pens = conn.execute("SELECT COUNT(*) FROM game_events WHERE game_id=? AND event_type='penalty'", (gid,)).fetchone()[0]
    if pens >= 10:
        d += 0.3
    before = (pts_map or {}).get(_key(h, a))
    if before is None:
        before = points(conn, h, a)
    _add(conn, h, a, d)
    if me in (h, a) and before >= BIG:
        won = (hg > ag) == (me == h)
        swing = 1.5 + 1.5 * min(1.0, (before - BIG) / 35)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='media_state'").fetchone():
            conn.execute("UPDATE media_state SET fan_sentiment=MAX(0, MIN(100, fan_sentiment+?)) WHERE team_id=?",
                         (swing if won else -swing, me))


def after_playoffs(conn, season_id):
    """Every playoff series of the season: the meetings that make rivalries."""
    ensure(conn)
    series = {}
    for r in conn.execute("SELECT series_id, home_team_id, away_team_id, game_no FROM games WHERE season_id=? AND game_type='PO' "
                          "AND played=1", (season_id,)):
        s = series.setdefault(r[0], dict(pair=_key(r[1], r[2]), games=0))
        s["games"] = max(s["games"], r[3] or 0) if r[3] else s["games"] + 1
    for sid, s in series.items():
        d = 2.0 * s["games"] + 8.0 + (4.0 if s["games"] >= 7 else 0.0) + (6.0 if str(sid) == "Final" else 0.0)
        _add(conn, *s["pair"], d)
    return len(series)


def season_end(conn, season_id):
    """After the playoffs: the playoff heat goes in, then everything cools a quarter of the way to its base, and the
    season's starting points are remembered (so 'potential' rivals are the ones that warmed)."""
    after_playoffs(conn, season_id)
    conn.execute("UPDATE rivalries SET season_start=points")
    conn.execute("UPDATE rivalries SET points=points-(points-base)*?", (COOL,))


def rivals_of(conn, t):
    """[{team_id, points, level, trend}] for one club, hottest first."""
    ensure(conn)
    out = []
    for a, b, base, p, s0 in conn.execute("SELECT a, b, base, points, season_start FROM rivalries WHERE a=? OR b=? ORDER BY points DESC",
                                          (t, t)):
        out.append(dict(team_id=b if a == t else a, points=round(p, 1), base=base, level=level_name(p),
                        warming=p > (s0 or 0) + 0.5))
    return out


def main_rival(conn, t):
    r = rivals_of(conn, t)
    return r[0] if r and r[0]["points"] >= BIG else None


def potential(conn, t):
    return [x for x in rivals_of(conn, t) if 35 <= x["points"] < BIG and x["warming"]]


def head_to_head(conn, t, o):
    """All-time record (every season the save has played) between two clubs, and their playoff series."""
    w = l = otl = 0
    for h, a, hg, ag, ot, typ in conn.execute("SELECT home_team_id, away_team_id, home_goals, away_goals, went_to_ot, game_type FROM games "
                                              "WHERE played=1 AND ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))",
                                              (t, o, o, t)):
        mine = (hg > ag) == (h == t)
        if mine:
            w += 1
        elif ot and typ == "RS":
            otl += 1
        else:
            l += 1
    series = conn.execute("SELECT COUNT(DISTINCT season_id||'-'||series_id) FROM games WHERE game_type='PO' AND ((home_team_id=? AND "
                          "away_team_id=?) OR (home_team_id=? AND away_team_id=?))", (t, o, o, t)).fetchone()[0]
    return dict(w=w, l=l, otl=otl, series=series)


def view(conn, t):
    tm = {r[0]: dict(team_id=r[0], abbr=r[1], name=f"{r[2]} {r[3] or ''}".strip()) for r in
          conn.execute(f"SELECT team_id, abbr, name, nickname FROM teams WHERE {top_league_sql()}")}
    rows = []
    for x in rivals_of(conn, t)[:6]:
        o = x["team_id"]
        rows.append(dict(x, **tm.get(o, {}), h2h=head_to_head(conn, t, o)))
    m = main_rival(conn, t)
    return dict(team_id=t, main=dict(m, **tm.get(m["team_id"], {})) if m else None, rivals=rows,
                potential=[dict(x, **tm.get(x["team_id"], {})) for x in potential(conn, t)][:4],
                levels=[dict(min=v, name=n) for v, n in LEVELS])
