"""Your European club's games, played by the real game engine (v61; docs/EUROPE.md).

The leagues around the NHL are played by the results model (hs/game/leagues.py). The club you run is the exception:
each of its games is played by the same engine as an NHL game, with your lines, tactics and tendencies and the
opponent's own lines, so it has a box score, a recap and the 2D replay. The score goes back into the league like any
other result (lg_games), and the players' lines into the league's season statistics.

Nothing here touches the NHL's tables. A match is kept in its own tables:

  eu_match          one row a game (its lg_games id, the score, ot 0 / 1 / 2 / 3 = regulation / overtime / shootout / tie)
  eu_match_events   the engine's events, as game_events
  eu_match_stats    each player's line, as player_game_stats
  eu_match_ratings  each player's 1-10 game rating, as game_ratings

A match is shown under the game id EU_BASE + match_id. `shadow` lends the game page, the recap and the replay a view
in which these tables stand in for the NHL's (temporary tables of the same names, on the same connection, for the
length of the call), so the same code shows both.

Centring: every engine rating is expressed against the club's own league (the average dressed player of its clubs),
as an NHL game is against the NHL's, so a KHL game plays at the engine's usual rates and only the difference between
the two clubs counts. The league's scoring level then comes from its rules (gpg) through the results model's other
games; the engine's games stay within the league's usual range (about 5-6 goals a game).

The second game of a two-game series on aggregate goals (a few play-ins) stays with the results model.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3

EU_BASE = 900_000_000
_MEANS: dict = {}


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS eu_match (match_id INTEGER PRIMARY KEY, lg_game_id INTEGER, league_id INTEGER, "
                 "season INTEGER, day TEXT, home INTEGER, away INTEGER, hg INTEGER, ag INTEGER, ot INTEGER, stage TEXT, seed INTEGER)")
    conn.execute("CREATE INDEX IF NOT EXISTS eu_match_lg ON eu_match (lg_game_id)")
    conn.execute("CREATE TABLE IF NOT EXISTS eu_match_events (match_id INTEGER, seq INTEGER, period INTEGER, clock_sec INTEGER, "
                 "event_type TEXT, team_id INTEGER, player_id INTEGER, opp_player_id INTEGER, xg REAL, detail TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS eu_match_events_m ON eu_match_events (match_id)")
    conn.execute("CREATE TABLE IF NOT EXISTS eu_match_stats (match_id INTEGER, player_id INTEGER, team_id INTEGER, toi_sec INTEGER, "
                 "goals INTEGER, assists INTEGER, shots INTEGER, saves INTEGER, shots_against INTEGER, PRIMARY KEY (match_id, player_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS eu_match_ratings (match_id INTEGER, player_id INTEGER, team_id INTEGER, offence REAL, "
                 "defence REAL, overall REAL, PRIMARY KEY (match_id, player_id))")


def is_eu(gid):
    return gid is not None and int(gid) >= EU_BASE


def of_lg_game(conn, lg_game_id):
    """The engine match played for this league game (its game id for the game page), or None."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='eu_match'").fetchone():
        return None
    r = conn.execute("SELECT match_id FROM eu_match WHERE lg_game_id=?", (lg_game_id,)).fetchone()
    return EU_BASE + r[0] if r else None


# ---------------------------------------------------------------- the clubs as engine teams
def _club_team(conn, club):
    from ..sim.loader import load_club
    t = load_club(conn, club)
    if t is None:
        return None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lineups'").fetchone():   # tendencies, as an NHL club's
        from ..sim.loader import apply_tendency
        r = conn.execute("SELECT data FROM lineups WHERE team_id=?", (club,)).fetchone()
        if r:
            for pid, tnd in (json.loads(r[0]).get("tend") or {}).items():
                p = t.by_id.get(int(pid))
                if p is not None:
                    apply_tendency(p, tnd)
    return t


def league_means(conn, lid, day):
    """The league's average dressed skater and starting goalie on each engine index (refreshed monthly)."""
    from ..sim.loader import GOALIE_INDICES, SKATER_INDICES
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    key = (path, lid, day[:7])
    if key in _MEANS:
        return _MEANS[key]
    sk, gl = [], []
    for (c,) in conn.execute("SELECT team_id FROM teams WHERE league_id=?", (lid,)).fetchall():
        t = _club_team(conn, c)
        if t is None:
            continue
        sk += t.skaters
        if t.goalies:
            gl.append(t.goalies[0])
    m = {n: sum(getattr(p, n) for p in sk) / max(1, len(sk)) for n in SKATER_INDICES}
    m.update({n: sum(getattr(p, n) for p in gl) / max(1, len(gl)) for n in GOALIE_INDICES})
    _MEANS[key] = m
    return m


def _centre(t, means):
    from ..sim.loader import GOALIE_INDICES, SKATER_INDICES
    for p in t.skaters + t.goalies:
        for n in (GOALIE_INDICES if p.pos == "G" else SKATER_INDICES):
            setattr(p, n, getattr(p, n) - means.get(n, 0.0))


def _tactics(conn, teams):
    try:
        from ..game.tactics import engine_effects
        eff = engine_effects(conn)
    except Exception:                                    # (no tactics for these clubs: the engine's defaults)
        return
    for tid, t in teams.items():
        if tid in eff:
            t.tac = eff[tid]


# ---------------------------------------------------------------- playing a game
def play(conn, g, env, skill, seed, playoff=False, ties=False, split="RS"):
    """Play league game `g` (an lg_games row) with the engine. Returns (hg, ag, ot, lines) with lines in the results
    model's statistics format ({(pid, team, 'S'|'G', split): [...]}), or None when a club cannot dress a lineup."""
    from ..sim.engine import simulate_game
    from ..sim.loader import game_ratings
    ensure_tables(conn)
    h, a = g["home"], g["away"]
    home, away = _club_team(conn, h), _club_team(conn, a)
    if home is None or away is None:
        return None
    means = league_means(conn, g["league_id"], g["day"])
    _centre(home, means)
    _centre(away, means)
    _tactics(conn, {h: home, a: away})
    try:
        from ..sim.loader import apply_people
        apply_people(conn, {h: home, a: away})
    except sqlite3.OperationalError:
        pass
    gseed = seed * 1_000_003 + EU_BASE + g["game_id"]
    ot_rules = dict(format="none", minutes=0, shootout=False) if ties else dict(format="3v3", minutes=5, shootout=True)
    res = simulate_game(home, away, env, skill, gseed, events=True, playoff=playoff, overtime=None if playoff else ot_rules)
    hg, ag = res.goals
    ot = 3 if res.tie else 2 if res.shootout else int(res.went_to_ot)     # (the engine credits the shootout's winner a goal)
    cur = conn.execute("INSERT INTO eu_match (lg_game_id, league_id, season, day, home, away, hg, ag, ot, stage, seed) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (g["game_id"], g["league_id"], g["season"], g["day"], h, a, hg, ag, ot,
                                                          "PO" if playoff else "RS", gseed))
    mid = cur.lastrowid
    ids = (h, a)
    conn.executemany("INSERT INTO eu_match_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                     [(mid, n + 1, per, clock, typ, ids[ti], pid, opp, xg, det)
                      for n, (per, clock, typ, ti, pid, opp, xg, det) in enumerate(res.events)])
    conn.executemany("INSERT OR REPLACE INTO eu_match_stats VALUES (?,?,?,?,?,?,?,?,?)",
                     [(mid, pid, ids[s["team"]], s["toi"], s["g"], s["a"], s["sog"], s["saves"], s["sa"]) for pid, s in res.stats.items()])
    goalies = {p.pid for t in (home, away) for p in t.goalies}
    pos = {p.pid: p.pos for t in (home, away) for p in t.skaters}
    rows = []
    for pid, (off, de, gov) in game_ratings(res, goalies).items():
        ov = gov if gov is not None else (round(0.4 * off + 0.6 * de, 1) if pos.get(pid) == "D" else round(0.6 * off + 0.4 * de, 1))
        rows.append((mid, pid, ids[res.stats[pid]["team"]], off, de, ov))
    conn.executemany("INSERT OR REPLACE INTO eu_match_ratings VALUES (?,?,?,?,?,?)", rows)
    # the lines for the league's season statistics
    lines = {}
    goals = (hg, ag)
    for pid, s in res.stats.items():
        team = ids[s["team"]]
        if pid in goalies:
            if not s["toi"]:
                continue
            lines[(pid, team, "G", split)] = [1, 0, 0, 0, 0, s["sa"] - s["saves"], s["sa"]]
        else:
            lines[(pid, team, "S", split)] = [1, s["g"], s["a"], s["pim"], s["sog"], s["toi"]]
    for side, team in enumerate(ids):                    # the decision goes to the goalie who played the most
        gl = [(s["toi"], pid) for pid, s in res.stats.items() if pid in goalies and s["team"] == side and s["toi"]]
        if not gl:
            continue
        pid = max(gl)[1]
        v = lines[(pid, team, "G", split)]
        mine, theirs = goals[side], goals[1 - side]
        if ot != 3:
            if mine > theirs:
                v[1] = 1
            elif ot:
                v[3] = 1
            else:
                v[2] = 1
        v[4] = 1 if (theirs == 0 or (ot == 2 and v[5] == 0)) and len(gl) == 1 else 0
    return hg, ag, ot, lines


# ---------------------------------------------------------------- the game page's view of a match
SHADOW = ("games", "game_events", "player_game_stats", "game_ratings")


@contextlib.contextmanager
def shadow(conn, gid):
    """Within the block, `games`, `game_events`, `player_game_stats` and `game_ratings` on this connection hold only
    the match `gid` (temporary tables of the same names shadow the NHL's). The caller holds the connection (the UI
    server's lock), so nothing else sees them; they are dropped at the end."""
    mid = int(gid) - EU_BASE
    ensure_tables(conn)
    m = conn.execute("SELECT * FROM eu_match WHERE match_id=?", (mid,)).fetchone()
    if m is None:
        raise ValueError("That game has not been played.")
    sid = conn.execute("SELECT MAX(season_id) FROM seasons").fetchone()[0] or 0
    try:
        conn.execute("CREATE TEMP TABLE games AS SELECT ? AS game_id, ? AS season_id, day AS game_date, home AS home_team_id, "
                     "away AS away_team_id, hg AS home_goals, ag AS away_goals, CASE WHEN ot=3 THEN 0 ELSE ot END AS went_to_ot, "
                     "stage AS game_type, NULL AS series_id, NULL AS game_no, 1 AS played, seed FROM eu_match WHERE match_id=?",
                     (int(gid), sid, mid))
        conn.execute("CREATE TEMP TABLE game_events AS SELECT rowid AS event_id, ? AS game_id, seq, period, clock_sec, event_type, "
                     "team_id, player_id, opp_player_id, xg, detail FROM eu_match_events WHERE match_id=?", (int(gid), mid))
        conn.execute("CREATE TEMP TABLE player_game_stats AS SELECT ? AS game_id, player_id, team_id, toi_sec, goals, assists, "
                     "shots, saves, shots_against FROM eu_match_stats WHERE match_id=?", (int(gid), mid))
        conn.execute("CREATE TEMP TABLE game_ratings AS SELECT ? AS game_id, player_id, team_id, offence, defence, overall "
                     "FROM eu_match_ratings WHERE match_id=?", (int(gid), mid))
        yield conn
    finally:
        for t in SHADOW:
            conn.execute(f"DROP TABLE IF EXISTS temp.{t}")
