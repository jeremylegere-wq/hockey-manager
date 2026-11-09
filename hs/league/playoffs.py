"""Playoff qualification, fixed brackets, and series simulation.

Formats: "division_wildcard" (NHL: top N per division + wildcards, fixed bracket, no reseeding) and
"conference_top_n" (top N per conference, 1vN ... fixed bracket). Best-of-N with a home-ice pattern.
"""
from __future__ import annotations

from datetime import timedelta

from ..sim.engine import simulate_game
from ..sim.loader import write_result
from .rules import structure


def qualify_division_wildcard(order, teams, po):
    """order: ranked team ids (league-wide). Returns {conference: {...}} with seeds."""
    st = structure(teams)
    pos = {t: i for i, t in enumerate(order)}
    out = {}
    for conf, divs in st.items():
        div_top, rest = {}, []
        for dname, members in divs.items():
            ranked = sorted(members, key=pos.get)
            div_top[dname] = ranked[:po["per_division"]]
            rest += ranked[po["per_division"]:]
        wild = sorted(rest, key=pos.get)[:po["wildcards_per_conference"]]
        out[conf] = {"divisions": div_top, "wildcards": wild}
    return out


def qualify_conference_top_n(order, teams, po):
    pos = {t: i for i, t in enumerate(order)}
    n = po.get("teams_per_conference", 8)
    return {conf: {"seeds": sorted([t for d in divs.values() for t in d], key=pos.get)[:n]}
            for conf, divs in structure(teams).items()}


def play_series(high, low, rounds_info, conn, teams, env, skill, po, season_id, start_day, game_id_seed,
                store_events=True):
    """Play one series. `high` has home ice. Returns dict(winner, loser, wins, games)."""
    need = po["series_length"] // 2 + 1
    wins = {high: 0, low: 0}
    day, n = start_day, 0
    while max(wins.values()) < need:
        home, away = (high, low) if po["home_pattern"][n] else (low, high)
        seed = game_id_seed * 7919 + n
        res = simulate_game(teams[home], teams[away], env, skill, seed, events=store_events, playoff=True)
        cur = conn.execute("INSERT INTO games (season_id, game_date, home_team_id, away_team_id, game_type, series_id, game_no) "
                           "VALUES (?,?,?,?, 'PO', ?, ?)", (season_id, day.isoformat(), home, away, rounds_info, n + 1))
        write_result(conn, cur.lastrowid, home, away, res, seed, teams)
        wins[home if res.goals[0] > res.goals[1] else away] += 1
        n += 1
        day += timedelta(days=2)
    w = max(wins, key=wins.get)
    return dict(series=rounds_info, high=high, low=low, winner=w, loser=low if w == high else high,
                wins=(wins[w], wins[low if w == high else high]), games=n, end=day)


def run_playoffs(conn, q, teams, env, skill, rules, order, season_id, start_day, seed):
    """Run the bracket for a qualification dict `q`. Returns list of rounds, each a list of series dicts."""
    po = rules["playoffs"]
    pos = {t: i for i, t in enumerate(order)}
    better = lambda a, b: a if pos[a] < pos[b] else b
    rounds, day = [], start_day
    sid = [0]

    def _series(label, high, low, start):
        sid[0] += 1
        r = play_series(high, low, label, conn, teams, env, skill, po, season_id, start, seed * 100 + sid[0])
        return r

    if po["format"] == "division_wildcard":
        r1, r2, finalists = [], [], {}
        bracket = {}
        for conf, info in q.items():
            (d1, top1), (d2, top2) = list(info["divisions"].items())
            w1, w2 = (d1, d2) if pos[top1[0]] < pos[top2[0]] else (d2, d1)   # division winner with the better record
            wc = sorted(info["wildcards"], key=pos.get)                        # wc[0] better wildcard
            m = {w1: (info["divisions"][w1][0], wc[1]), w2: (info["divisions"][w2][0], wc[0])}
            bracket[conf] = (m, {d: info["divisions"][d] for d in (d1, d2)})
        # round 1
        r1s = {}
        for conf, (m, divs) in bracket.items():
            for d, (winner, wcard) in m.items():
                r1s[(conf, d, "A")] = _series(f"R1 {conf} {d} winner v WC", winner, wcard, day)
                r1s[(conf, d, "B")] = _series(f"R1 {conf} {d} 2v3", divs[d][1], divs[d][2], day)
        rounds.append(list(r1s.values()))
        day = max(s["end"] for s in r1s.values()) + timedelta(days=1)
        # division finals (fixed bracket): winner of A-series meets winner of B-series within the division
        rank_in_div = {}
        for conf, (m, divs) in bracket.items():
            for d, members in divs.items():
                for i, t in enumerate(members):
                    rank_in_div[t] = i + 1
            for wcard in q[conf]["wildcards"]:
                rank_in_div[wcard] = 4
        r2s, conf_winners = {}, {}
        for conf, (m, divs) in bracket.items():
            for d in divs:
                a, b = r1s[(conf, d, "A")]["winner"], r1s[(conf, d, "B")]["winner"]
                hi, lo = (a, b) if rank_in_div[a] < rank_in_div[b] else (b, a)
                r2s[(conf, d)] = _series(f"R2 {conf} {d}", hi, lo, day)
        rounds.append(list(r2s.values()))
        day = max(s["end"] for s in r2s.values()) + timedelta(days=1)
        cf = {}
        for conf, (m, divs) in bracket.items():
            a, b = [r2s[(conf, d)]["winner"] for d in divs]
            cf[conf] = _series(f"Conference final {conf}", better(a, b), b if better(a, b) == a else a, day)
        rounds.append(list(cf.values()))
        day = max(s["end"] for s in cf.values()) + timedelta(days=1)
        a, b = [s["winner"] for s in cf.values()]
        final = _series("Final", better(a, b), b if better(a, b) == a else a, day)
        rounds.append([final])
        return rounds, final["winner"]

    # conference_top_n: fixed bracket 1vN, 2v(N-1)... inside each conference, winners meet by bracket order
    conf_champs = {}
    for conf, info in q.items():
        seeds = info["seeds"]
        n = len(seeds)
        slots = _bracket_order(n)
        field = [(seeds[slots[2 * i]], seeds[slots[2 * i + 1]]) for i in range(n // 2)]
        current = field
        rnd = 1
        while True:
            results = [_series(f"R{rnd} {conf}", *(sorted(p, key=pos.get))[:2], day) for p in current]
            while len(rounds) < rnd:
                rounds.append([])
            rounds[rnd - 1] += results
            day = max(s["end"] for s in results) + timedelta(days=1)
            winners = [s["winner"] for s in results]
            if len(winners) == 1:
                conf_champs[conf] = winners[0]
                break
            current = [(winners[2 * i], winners[2 * i + 1]) for i in range(len(winners) // 2)]
            rnd += 1
    a, b = list(conf_champs.values())
    final = _series("Final", better(a, b), b if better(a, b) == a else a, day)
    rounds.append([final])
    return rounds, final["winner"]


def _bracket_order(n):
    """Seed positions for a fixed single-elimination bracket of n (power of two): [0,7,3,4,1,6,2,5] for 8."""
    order = [0]
    while len(order) < n:
        m = len(order) * 2
        order = [x for o in order for x in (o, m - 1 - o)]
    return order
