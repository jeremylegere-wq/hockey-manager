"""Build engine Teams from a game database (schema v2) and run games."""
from __future__ import annotations

import sqlite3

from .engine import Player, Team


def load_teams(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    use = {}
    # each NHL-organisation player's last season (v44: only those players, and one pass, not a correlated subquery
    # over every season line in the world: imported history made that the slowest part of a game day)
    for t in ("skater_season_stats", "goalie_season_stats"):
        last = {}
        for pid, y, toi, gp in conn.execute(
                f"SELECT s.player_id, s.season_start_year, s.toi_sec, s.gp FROM {t} s JOIN players p USING (player_id) "
                "WHERE s.split='RS' AND p.status='active' AND p.team_id IS NOT NULL"):
            cur = last.get(pid)
            if cur is None or y > cur[0]:
                last[pid] = [y, toi or 0, gp or 0]
            elif y == cur[0]:
                cur[1] += toi or 0
                cur[2] += gp or 0
        for pid, (y, toi, gp) in last.items():
            use[pid] = (toi, gp)
    names = {t["team_id"]: t["abbr"] for t in conn.execute("SELECT team_id, abbr FROM teams")}
    by_team = {}
    from ..game.discipline import suspended             # v53: suspended players do not dress
    out_ = suspended(conn)
    for r in conn.execute("SELECT p.player_id, p.position, p.team_id, p.first_name, p.last_name, a.* FROM players p "
                          "JOIN player_attributes a USING (player_id) WHERE p.status='active' AND p.team_id IS NOT NULL"):
        if r["player_id"] in out_:
            continue
        d = dict(r)
        toi, gp = use.get(d["player_id"], (0, 0))
        pl = Player.from_attrs(d["player_id"], d["position"], d, f"{d['first_name']} {d['last_name']}", toi, gp)
        if not toi:   # no history: order by overall usefulness so the depth chart is still sensible
            pl.toi = 1000 * (pl.gen + pl.sup + pl.qual) / 3
        by_team.setdefault(d["team_id"], []).append(pl)
    teams = {tid: Team(tid, names.get(tid, str(tid)), pl) for tid, pl in by_team.items()
             if sum(p.pos == "G" for p in pl) >= 1 and sum(p.pos != "G" for p in pl) >= 12}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lineups'").fetchone():
        import json
        for tid, data in conn.execute("SELECT team_id, data FROM lineups"):
            if tid in teams:
                teams[tid].missing = teams[tid].apply_lineup(json.loads(data))
    try:
        from ..game.tactics import engine_effects
        for tid, m in engine_effects(conn).items():
            if tid in teams:
                teams[tid].tac = m
        normalise_counters(teams)
    except (sqlite3.OperationalError, TypeError):   # a bare pack without game tables
        pass
    try:                                                # v30: the media's and the fans' mood (hs/game/press.py)
        from ..game.press import engine_form
        for tid, (f, h) in engine_form(conn).items():
            if tid in teams:
                teams[tid].form, teams[tid].home_form = f, h
    except sqlite3.OperationalError:
        pass
    centre_on_league(teams)
    try:                                                # v33: line chemistry, relative to the league's average pair
        from ..game.chemistry import load as chem_load
        st = conn.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone()
        if st:
            for tid, ch in chem_load(conn, st[0]).items():
                if tid in teams:
                    teams[tid].chem = ch
    except sqlite3.OperationalError:
        pass
    try:                                                # v35: hidden attributes, rust after a layoff, playing hurt
        apply_people(conn, teams)
    except sqlite3.OperationalError:
        pass
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lineups'").fetchone():   # v33: player tendencies
        import json
        for tid, data in conn.execute("SELECT team_id, data FROM lineups"):
            if tid in teams:
                for pid, tnd in (json.loads(data).get("tend") or {}).items():
                    p = teams[tid].by_id.get(int(pid))
                    if p is not None:
                        apply_tendency(p, tnd)
    try:                                                # v55: tactical roles
        from ..game.troles import engine_roles
        for pid, (fx, extra) in engine_roles(conn).items():
            for t in teams.values():
                p = t.by_id.get(pid)
                if p is not None:
                    p.rfx = fx
                    p.temper *= extra.get("temper", 1.0)
                    p.protect = bool(extra.get("protect"))
                    break
        role_neutral(teams)
    except sqlite3.OperationalError:
        pass
    return teams


def role_neutral(teams):
    """v55: the league's average effect of tactical roles on the penalty rate (players' own penalties and the ones they
    draw, weighted by the share of the even-strength game his effect reaches, measured: forwards 0.22, defencemen 0.26) is divided out of every
    club's rate, so roles move penalties between clubs, not the league's total."""
    import math
    tot, n = 0.0, 0
    for t in teams.values():
        x = 0.0
        for p in t.skaters:
            d = (p.rfx or {}).get("ev") or {}
            share = 0.26 if p.pos == "D" else 0.22
            x += share * (math.log(d.get("pen", 1.0)) + math.log(d.get("draw", 1.0)))
        tot += x
        n += 1
    norm = math.exp(-tot / n) if n else 1.0
    for t in teams.values():
        t.role_pen = norm


RUST = 0.25          # v35: a player back from a layoff of two weeks or more starts this far below himself (sd), and it
                     # wears off over a game per week he was out (up to five)
HURT = 0.35          # v35: a player playing through an injury, until he would have been back


def apply_people(conn, teams):
    import datetime
    from ..game import hidden as HD
    hid = HD.all_of(conn)
    for t in teams.values():
        for p in t.skaters + t.goalies:
            h = hid.get(p.pid)
            if h:
                p.cons_sd = HD.consistency_sd(h["consistency"])
                p.bg = HD.big_games_fin(h["big_games"])
                p.temper = HD.temper_weight(h["temperament"])
    st = conn.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone()
    if not st:
        return
    today = datetime.date.fromisoformat(st[0])
    since = (today - datetime.timedelta(days=60)).isoformat()
    byid = {p.pid: p for t in teams.values() for p in t.skaters}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(injuries)")}
    for r in conn.execute("SELECT player_id, start_date, expected_return" + (", playing_hurt" if "playing_hurt" in cols else ", 0")
                          + " FROM injuries WHERE expected_return>=?", (since,)):
        p = byid.get(r[0])
        if p is None:
            continue
        start, back = datetime.date.fromisoformat(r[1]), datetime.date.fromisoformat(r[2])
        if r[3] and back > today:                       # playing through it
            p.gen -= HURT
            p.sup -= HURT
            p.fin -= HURT
            continue
        out = (back - start).days
        if out < 14 or back > today:
            continue
        games = min(5, out // 7)
        played = conn.execute("SELECT COUNT(*) FROM player_game_stats s JOIN games g USING (game_id) WHERE s.player_id=? AND g.game_date>=?",
                              (r[0], r[2])).fetchone()[0]
        left = max(0, games - played)
        if left:
            k = RUST * left / games
            p.gen -= k
            p.sup -= k


TEND = {  # tendency -> (shot weight, assist weight, gen shift, sup shift) in the engine's units
    "shoot": {"pass first": (0.6, 1.35), "normal": (1.0, 1.0), "shoot first": (1.6, 0.75)},
    "style": {"defensive": (-0.12, 0.12), "normal": (0.0, 0.0), "attacking": (0.12, -0.12)},
}


def apply_tendency(p, tnd):
    """Player tendencies (Lines screen): shoot first / pass first, and an attacking or defensive bent. They move a
    player's share of his unit's shots and assists, and trade a little defence for offence (or back)."""
    sw, aw = TEND["shoot"].get((tnd or {}).get("shoot", "normal"), (1.0, 1.0))
    g, d = TEND["style"].get((tnd or {}).get("style", "normal"), (0.0, 0.0))
    p.shoot_w, p.assist_w = sw, aw
    p.gen += g
    p.sup += d


def normalise_counters(teams):
    """v33: the counters between two clubs' settings, averaged over every pairing in the league, are divided out, so
    whatever mix of tactics the league plays, counters only move results between clubs, never the league's totals."""
    from ..game.tactics import counters
    ts = [t for t in teams.values() if t.tac and t.tac.get("settings")]
    if len(ts) < 2:
        return
    tot = dict(att=0.0, qual=0.0, pp_att=0.0, pp_qual=0.0)
    n = 0
    for a in ts:
        for b in ts:
            if a is not b:
                c = counters(a.tac["settings"], b.tac["settings"])
                for k in tot:
                    tot[k] += c[k]
                n += 1
    norm = {k: n / v for k, v in tot.items()}
    for t in ts:
        t.tac["cnt_norm"] = norm


SKATER_INDICES = ("gen", "qual", "fin", "sup", "blk", "comp", "pas")
GOALIE_INDICES = ("save", "reb")


def centre_on_league(teams: dict) -> None:
    """Express every skill index relative to this league's own average (dressed players only), so that a custom
    league whose ratings run high or low plays like a league of average players: environment rates (shots,
    goals) stay put and only differences between players and teams matter."""
    sk = [p for t in teams.values() for p in t.skaters]
    gl = [t.goalies[0] for t in teams.values()]
    for names, group in ((SKATER_INDICES, sk), (GOALIE_INDICES, gl)):
        ids = {id(p) for p in group}                     # (v44: a set, not a list scan: 24M comparisons a week)
        for n in names:
            m = sum(getattr(p, n) for p in group) / len(group)
            for t in teams.values():
                for p in t.skaters + t.goalies:
                    if id(p) in ids or (names is SKATER_INDICES and p.pos != "G") or (names is GOALIE_INDICES and p.pos == "G"):
                        setattr(p, n, getattr(p, n) - m)


def write_result(conn, game_id, home_id, away_id, res, seed, teams):
    """Store a played game: score, every event, and per-player box score. Replayable from `seed`."""
    ids = (home_id, away_id)
    conn.execute("UPDATE games SET home_goals=?, away_goals=?, went_to_ot=?, played=1, seed=? WHERE game_id=?",
                 (res.goals[0], res.goals[1], 2 if res.shootout else int(res.went_to_ot), seed, game_id))
    conn.executemany(
        "INSERT INTO game_events (game_id, seq, period, clock_sec, event_type, team_id, player_id, opp_player_id, xg, detail)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(game_id, n + 1, per, clock, typ, ids[ti], pid, opp, xg, det)
         for n, (per, clock, typ, ti, pid, opp, xg, det) in enumerate(res.events)])
    conn.executemany(
        "INSERT INTO player_game_stats (game_id, player_id, team_id, toi_sec, goals, assists, shots, saves, shots_against)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [(game_id, pid, ids[s["team"]], s["toi"], s["g"], s["a"], s["sog"], s["saves"], s["sa"])
         for pid, s in res.stats.items()])
    write_ratings(conn, game_id, ids, res, teams)


def game_ratings(res, goalies=()):
    """v35: a 1-10 rating for each player's game: offence (goals, assists, shots, attempts), defence (blocks, the
    goals his team allowed while he played, penalties), and overall (forwards 60/40, defence 40/60). Goalies: save %
    against the league's .900, a shutout, the goals let in."""
    blocks, ga = {}, [0, 0]
    for per, clock, typ, ti, pid, opp, xg, det in res.events:
        if typ == "block" and opp:
            blocks[opp] = blocks.get(opp, 0) + 1
    ga = [res.goals[1], res.goals[0]]
    out = {}
    for pid, s in res.stats.items():
        team_ga = ga[s["team"]]
        if pid in goalies or (s["sa"] and not s["att"] and s["sog"] == 0 and s["toi"] >= 600 and s.get("saves") is not None and s["sa"] > 0):
            sv = s["saves"] / s["sa"] if s["sa"] else 1.0
            ov = 6.0 + (sv - 0.900) * 22 + (1.0 if s["sa"] >= 15 and s["saves"] == s["sa"] else 0) - 0.25 * max(0, (s["sa"] - s["saves"]) - 3)
            ov = max(1.0, min(10.0, ov))
            out[pid] = (None, None, round(ov, 1))
            continue
        share = min(1.0, s["toi"] / 1200.0) if s["toi"] else 0.0
        off = 5.5 + 1.4 * s["g"] + 0.8 * s["a"] + 0.15 * s["sog"] + 0.04 * s["att"]
        de = 6.0 + 0.3 * blocks.get(pid, 0) - (0.35 * team_ga - 1.0) * share - 0.25 * (s["pim"] // 2)
        off, de = max(1.0, min(10.0, off)), max(1.0, min(10.0, de))
        out[pid] = (round(off, 1), round(de, 1), None)
    return out


def write_ratings(conn, game_id, ids, res, teams):
    conn.execute("CREATE TABLE IF NOT EXISTS game_ratings (game_id INTEGER, player_id INTEGER, team_id INTEGER, offence REAL, "
                 "defence REAL, overall REAL, PRIMARY KEY (game_id, player_id))")
    pos = {}
    goalies = set()
    for t in teams.values() if isinstance(teams, dict) else []:
        for p in t.skaters:
            pos[p.pid] = p.pos
        for g in t.goalies:
            goalies.add(g.pid)
            pos[g.pid] = "G"
    rows = []
    for pid, (off, de, gov) in game_ratings(res, goalies).items():
        if gov is not None:
            ov = gov
        else:
            ov = round(0.4 * off + 0.6 * de, 1) if pos.get(pid) == "D" else round(0.6 * off + 0.4 * de, 1)
        rows.append((game_id, pid, ids[res.stats[pid]["team"]], off, de, ov))
    conn.executemany("INSERT OR REPLACE INTO game_ratings VALUES (?,?,?,?,?,?)", rows)
