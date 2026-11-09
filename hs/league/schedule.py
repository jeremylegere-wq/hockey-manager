"""Schedule generator: who plays whom (from the structure rules), who hosts, and on which day.

    from hs.league.schedule import build_schedule
    games = build_schedule(teams, rules, seed=1)       # [(date, home_id, away_id), ...]

Opponent counts come from `hs.league.rules.opponent_counts`; home games are balanced with an Eulerian
orientation of the odd-count pairs (every team ends with exactly half its games at home when that is possible);
dates come from a pace-based greedy scheduler that discourages back-to-backs, long home/away runs and repeat opponents.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from .rules import opponent_counts

WEEKDAY_WEIGHT = [0.75, 1.15, 1.0, 1.1, 0.85, 1.3, 0.85]   # Mon..Sun: a stylised shape, not fitted to data


class ScheduleError(Exception):
    pass


def orient_odd_pairs(edges, rng):
    """Direct each (a,b) so that out-degree (extra home game) is as even as possible. Euler circuits when all degrees are even."""
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    out = {}
    used = set()
    verts = sorted(adj)
    rng.shuffle(verts)
    for start in verts:
        if all(frozenset((start, w)) in used for w in adj[start]):
            continue
        stack, path = [start], []
        local = {v: [w for w in adj[v]] for v in adj}
        while stack:                                    # Hierholzer
            v = stack[-1]
            while local[v] and frozenset((v, local[v][-1])) in used:
                local[v].pop()
            if local[v]:
                w = local[v].pop()
                used.add(frozenset((v, w)))
                out[frozenset((v, w))] = v              # v hosts the extra game
                stack.append(w)
            else:
                stack.pop()
    return {tuple(sorted(e)): host for e, host in out.items()}


def matchups(teams, rules, rng):
    counts = opponent_counts(teams, rules)
    odd = [pair for pair, g in counts.items() if g % 2]
    host = orient_odd_pairs(odd, rng)
    games = []
    for (a, b), g in counts.items():
        for _ in range(g // 2):
            games += [(a, b), (b, a)]
        if g % 2:
            h = host[(a, b)]
            games.append((h, b if h == a else a))
    return games


def season_days(rules):
    s = rules["season"]
    d, end = date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
    breaks = [(date.fromisoformat(b["start"]), date.fromisoformat(b["end"])) for b in s.get("breaks", [])]
    days = []
    while d <= end:
        if not any(a <= d <= b for a, b in breaks):
            days.append(d)
        d += timedelta(days=1)
    return days


def assign_dates(games, days, rng, b2b_penalty=0.2, repeat_penalty=0.4, noise=0.35):
    ids = sorted({t for g in games for t in g})
    remaining = defaultdict(int)
    for h, a in games:
        remaining[h] += 1
        remaining[a] += 1
    unsched = set(range(len(games)))
    last_day = {t: -9 for t in ids}
    run_home = {t: 0 for t in ids}
    run_away = {t: 0 for t in ids}
    last_pair = {}
    out = []
    max_per_day = len(ids) // 2
    for di, day in enumerate(days):
        if not unsched:
            break
        left = len(days) - di
        target = len(unsched) / left
        n_today = min(max_per_day, max(1, round(target * WEEKDAY_WEIGHT[day.weekday()] * rng.uniform(0.7, 1.3))))
        urgency = {t: remaining[t] / left for t in ids}
        scored = []
        for gi in unsched:
            h, a = games[gi]
            s = urgency[h] + urgency[a]
            if urgency[h] >= 0.98 or urgency[a] >= 0.98:
                s += 10                                              # must play today to finish in time
            s -= b2b_penalty * ((last_day[h] == di - 1) + (last_day[a] == di - 1))
            if run_home[h] >= 3:
                s -= 0.18 * (run_home[h] - 2)
            if run_away[a] >= 3:
                s -= 0.18 * (run_away[a] - 2)
            if di - last_pair.get(frozenset((h, a)), -99) < 7:
                s -= repeat_penalty
            scored.append((s + rng.random() * noise, gi))
        scored.sort(reverse=True)
        busy, picked = set(), []
        for s, gi in scored:
            h, a = games[gi]
            if h in busy or a in busy:
                continue
            if len(picked) >= n_today and s < 5:
                continue
            picked.append(gi)
            busy.update((h, a))
        for gi in picked:
            h, a = games[gi]
            unsched.discard(gi)
            out.append((day, h, a))
            remaining[h] -= 1
            remaining[a] -= 1
            last_day[h] = last_day[a] = di
            run_home[h] += 1
            run_home[a] = 0
            run_away[a] += 1
            run_away[h] = 0
            last_pair[frozenset((h, a))] = di
    if unsched:
        raise ScheduleError(f"{len(unsched)} games did not fit in {len(days)} days")
    return out


def build_schedule(teams, rules, seed=1, tries=40, max_run=6):
    """teams: list of dicts (team_id, conference, division). Returns [(date, home_id, away_id)] sorted by date.
    Tries several random schedules and keeps the first whose longest home/away run is <= max_run (else the best)."""
    best, best_run, last = None, None, None
    for k in range(tries):
        rng = random.Random(seed * 1000 + k)
        try:
            games = matchups(teams, rules, rng)
            sched = sorted(assign_dates(games, season_days(rules), rng), key=lambda g: (g[0], g[1]))
        except ScheduleError as e:
            last = e
            continue
        st = schedule_stats(sched)["teams"]
        run = max(max(t["longest_home"], t["longest_away"]) for t in st)
        if best is None or run < best_run:
            best, best_run = sched, run
        if run <= max_run:
            break
    if best is None:
        raise ScheduleError(f"no valid schedule after {tries} tries: {last}")
    return best


def schedule_stats(sched):
    by = defaultdict(list)
    for d, h, a in sched:
        by[h].append((d, 1))
        by[a].append((d, 0))
    rows = []
    for t, g in by.items():
        g.sort()
        days = [d for d, _ in g]
        b2b = sum((days[i + 1] - days[i]).days == 1 for i in range(len(days) - 1))
        run, longest_h, longest_a, cur = 0, 0, 0, None
        for _, home in g:
            run = run + 1 if home == cur else 1
            cur = home
            if home:
                longest_h = max(longest_h, run)
            else:
                longest_a = max(longest_a, run)
        gaps = [(days[i + 1] - days[i]).days for i in range(len(days) - 1)]
        rows.append(dict(team=t, games=len(g), home=sum(h for _, h in g), b2b=b2b, longest_home=longest_h,
                         longest_away=longest_a, max_gap=max(gaps), games_per_day_max=max(
                             sum(1 for x in g if x[0] == d) for d in set(days))))
    per_day = defaultdict(int)
    for d, _, _ in sched:
        per_day[d] += 1
    return dict(teams=rows, first=min(per_day), last=max(per_day), game_days=len(per_day),
                max_games_in_a_day=max(per_day.values()), min_games_on_a_game_day=min(per_day.values()))
