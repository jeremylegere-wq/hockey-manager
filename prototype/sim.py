"""Game simulation + daily loop.

Design: every game is driven by a per-game seed stored in `games.seed`, and every shot/goal/save/penalty is
written to `game_events`. That means any past game can be replayed exactly and any historical view
(box score, shot map, line usage) is derived from stored events, not recomputed from partial totals.
"""
import math
import random
from datetime import date, timedelta

PERIOD_SEC = 1200


def _poisson(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _load_team(conn, team_id):
    rows = conn.execute(
        """SELECT p.player_id, p.position, a.* FROM players p
           JOIN player_attributes a USING (player_id)
           WHERE p.team_id = ? AND p.status = 'active'""", (team_id,)).fetchall()
    skaters = [r for r in rows if r["position"] != "G"]
    goalies = sorted([r for r in rows if r["position"] == "G"], key=lambda r: -r["goaltending"])
    return skaters, goalies


def _off(skaters):
    top = sorted(skaters, key=lambda r: -(r["shooting"] + r["passing"] + r["skating"]))[:12]
    return sum(r["shooting"] + r["passing"] + r["skating"] for r in top) / (3 * max(1, len(top)))


def _def(skaters):
    ds = sorted(skaters, key=lambda r: -(r["defense"] + r["checking"]))[:10]
    return sum(r["defense"] + r["checking"] for r in ds) / (2 * max(1, len(ds)))


def simulate_game(conn, game_id):
    g = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
    seed = g["seed"] or (game_id * 7919 + 13)
    rng = random.Random(seed)
    teams = {g["home_team_id"]: _load_team(conn, g["home_team_id"]),
             g["away_team_id"]: _load_team(conn, g["away_team_id"])}
    ids = [g["home_team_id"], g["away_team_id"]]
    goals = {t: 0 for t in ids}
    stats = {}
    seq = 0
    events = []

    def stat(pid, tid):
        return stats.setdefault(pid, dict(team=tid, goals=0, assists=0, shots=0, saves=0, sa=0))

    def emit(period, clock, etype, tid, pid=None, opp=None, xg=None, detail=None):
        nonlocal seq
        seq += 1
        events.append((game_id, seq, period, clock, etype, tid, pid, opp, xg, detail))

    def play_period(period, length, sudden_death=False):
        for tid in ids:
            opp = ids[1] if tid == ids[0] else ids[0]
            sk, _ = teams[tid]
            _, opp_g = teams[opp]
            if not sk or not opp_g:
                continue
            edge = (_off(sk) - _def(teams[opp][0])) / 20.0
            lam = (28.0 / 3) * (length / PERIOD_SEC) * (1 + edge) * (1.05 if tid == ids[0] else 1.0)
            for _ in range(_poisson(rng, max(0.5, lam))):
                clock = rng.randint(0, length - 1)
                shooter = rng.choices(sk, weights=[r["shooting"] ** 2 for r in sk])[0]
                xg = 0.045 + shooter["shooting"] * 0.004
                goalie = opp_g[0]
                save_p = min(0.96, max(0.84, 0.865 + goalie["goaltending"] * 0.0035)) - (xg - 0.08) * 0.5
                emit(period, clock, "shot", tid, shooter["player_id"], goalie["player_id"], round(xg, 3))
                stat(shooter["player_id"], tid)["shots"] += 1
                stat(goalie["player_id"], opp)["sa"] += 1
                if rng.random() > save_p:
                    goals[tid] += 1
                    stat(shooter["player_id"], tid)["goals"] += 1
                    helper = rng.choice([r for r in sk if r["player_id"] != shooter["player_id"]])
                    stat(helper["player_id"], tid)["assists"] += 1
                    emit(period, clock, "goal", tid, shooter["player_id"], goalie["player_id"], round(xg, 3),
                         f"A: {helper['player_id']}")
                else:
                    stat(goalie["player_id"], opp)["saves"] += 1
                    emit(period, clock, "save", opp, goalie["player_id"], shooter["player_id"], round(xg, 3))
                if sudden_death and goals[ids[0]] != goals[ids[1]]:
                    return
            if rng.random() < 0.6 * (length / PERIOD_SEC):
                p = rng.choice(sk)
                emit(period, rng.randint(0, length - 1), "penalty", tid, p["player_id"], None, None, "minor 2:00")

    for per in (1, 2, 3):
        play_period(per, PERIOD_SEC)
    ot = 0
    if goals[ids[0]] == goals[ids[1]]:
        ot = 1
        play_period(4, 300, sudden_death=True)
        if goals[ids[0]] == goals[ids[1]]:  # shootout, simplified
            winner = rng.choice(ids)
            goals[winner] += 1
            emit(5, 0, "goal", winner, None, None, None, "shootout winner")

    conn.execute("UPDATE games SET home_goals=?, away_goals=?, went_to_ot=?, played=1, seed=? WHERE game_id=?",
                 (goals[ids[0]], goals[ids[1]], ot, seed, game_id))
    conn.executemany("INSERT INTO game_events (game_id, seq, period, clock_sec, event_type, team_id, player_id, "
                     "opp_player_id, xg, detail) VALUES (?,?,?,?,?,?,?,?,?,?)", events)
    conn.executemany(
        "INSERT INTO player_game_stats (game_id, player_id, team_id, toi_sec, goals, assists, shots, saves, "
        "shots_against) VALUES (?,?,?,?,?,?,?,?,?)",
        [(game_id, pid, s["team"], 0, s["goals"], s["assists"], s["shots"], s["saves"], s["sa"])
         for pid, s in stats.items()])
    return goals[ids[0]], goals[ids[1]]


def _roll_injuries(conn, day, rng):
    healthy = conn.execute("SELECT player_id FROM players WHERE status='active'").fetchall()
    for r in healthy:
        if rng.random() < 0.0015:
            weeks = rng.choice([1, 1, 2, 3, 4, 8, 12])
            ret = (date.fromisoformat(day) + timedelta(weeks=weeks)).isoformat()
            conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (r["player_id"],))
            conn.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)",
                         (r["player_id"], day, ret, f"{weeks} week(s)"))
            conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, detail) VALUES (?,?,?,?)",
                         (day, "injury", r["player_id"], f"out {weeks} week(s)"))
    for r in conn.execute("SELECT injury_id, player_id FROM injuries WHERE expected_return <= ? AND "
                          "player_id IN (SELECT player_id FROM players WHERE status='injured')", (day,)).fetchall():
        conn.execute("UPDATE players SET status='active' WHERE player_id=?", (r["player_id"],))


def _train(conn, day, rng):
    """Tiny daily progression: young players drift up, 31+ drift down. Replace with a proper aging curve."""
    year = int(day[:4])
    for r in conn.execute("SELECT p.player_id, p.birth_date FROM players p WHERE status='active'").fetchall():
        age = year - int(r["birth_date"][:4])
        if rng.random() < 0.01:
            delta = 1 if age <= 24 else (-1 if age >= 31 else 0)
            if delta:
                conn.execute("UPDATE player_attributes SET skating = MAX(1, MIN(20, skating + ?)), updated_on=? "
                             "WHERE player_id=?", (delta, day, r["player_id"]))


def sim_day(conn):
    """Advance the world by one day: play scheduled games, roll injuries, train, bump the clock."""
    state = conn.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    day = state["current_date"]
    rng = random.Random(f"{state['rng_seed']}-{day}")
    results = []
    for g in conn.execute("SELECT game_id FROM games WHERE game_date=? AND played=0", (day,)).fetchall():
        results.append((g["game_id"], *simulate_game(conn, g["game_id"])))
    _roll_injuries(conn, day, rng)
    _train(conn, day, rng)
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    conn.execute("UPDATE game_state SET current_date=? WHERE id=1", (nxt,))
    conn.commit()
    return day, results


def season_has_games_left(conn):
    return conn.execute("SELECT COUNT(*) FROM games WHERE played=0").fetchone()[0] > 0
