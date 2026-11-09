"""Play whole seasons with a database's rosters and compare with the real league.

    python -m hs.sim.validate <game.db> <env.json> [--seasons 2] [--seed 1] [--set att=0.08 ...] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from dataclasses import replace

from .engine import Skill, simulate_game
from .loader import load_teams


def schedule(team_ids, n_games, rng):
    """Every ordered pair once, then random extra pairs, until the league has n_games games per team."""
    games = [(a, b) for a in team_ids for b in team_ids if a != b]
    total = len(team_ids) * n_games // 2
    while len(games) < total:
        a, b = rng.sample(team_ids, 2)
        games.append((a, b))
    rng.shuffle(games)
    return games[:total]


def sd(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def run(teams, env, skill, seasons=1, seed=1, games_per_team=82):
    rng = random.Random(seed)
    ids = sorted(teams)
    agg = dict(n=0, att=0, sog=0, goals=0, goals_all=0, ga_goalie=0, pens=0, pp_sec=0, pp_goals=0, sh_goals=0,
               en=0, ot=0, so=0, home_win=0, pim=0, ot_decided=0, assists=0, goals_ev=0)
    per_season = []
    for s in range(seasons):
        tm = {t: dict(att_ev=0, att_ev_a=0, xg=0.0, xg_a=0.0, gf=0, ga=0, sa=0, sv_ga=0, games=0) for t in ids}
        for h, a in schedule(ids, games_per_team, rng):
            r = simulate_game(teams[h], teams[a], env, skill, rng.getrandbits(48), events=False)
            agg["n"] += 1
            for i, t in ((0, h), (1, a)):
                x = r.team[i]
                agg["att"] += x["att"]
                agg["sog"] += x["sog"]
                core = x["ev_goals"] + x["pp_goals"] + x["sh_goals"] + x["ot_goals"]
                agg["goals"] += core
                agg["goals_all"] += core + x["en_goals"]
                agg["en"] += x["en_goals"]
                agg["goals_ev"] += x["ev_goals"]
                agg["pens"] += x["pens"]
                agg["pp_sec"] += x["pp_sec"]
                agg["pp_goals"] += x["pp_goals"]
                agg["pim"] += x["pim"]
                T = tm[t]
                o = r.team[1 - i]
                T["att_ev"] += x["att_ev"]; T["att_ev_a"] += o["att_ev"]
                T["xg"] += x["xg_ev"]; T["xg_a"] += o["xg_ev"]
                T["gf"] += core + x["en_goals"]
                T["ga"] += o["ev_goals"] + o["pp_goals"] + o["sh_goals"] + o["ot_goals"] + o["en_goals"]
                T["sa"] += o["sog"]
                T["sv_ga"] += o["ev_goals"] + o["pp_goals"] + o["sh_goals"] + o["ot_goals"]
                T["games"] += 1
            agg["ot"] += r.went_to_ot
            agg["so"] += r.shootout
            agg["home_win"] += r.goals[0] > r.goals[1]
        per_season.append(dict(
            cf_pct_sd=sd([v["att_ev"] / (v["att_ev"] + v["att_ev_a"]) for v in tm.values()]),
            xgf_pct_sd=sd([v["xg"] / (v["xg"] + v["xg_a"]) for v in tm.values()]),
            sv_pct_sd=sd([1 - v["sv_ga"] / v["sa"] for v in tm.values()]),
            goal_diff_per_game_sd=sd([(v["gf"] - v["ga"]) / v["games"] for v in tm.values()])))
    n2 = agg["n"] * 2
    out = {
        "goals_per_team_game": agg["goals"] / n2, "sog_per_team_game": agg["sog"] / n2,
        "attempts_per_team_game": agg["att"] / n2, "sv_pct": 1 - agg["goals"] / agg["sog"],
        "penalties_per_game_both_teams": agg["pens"] / agg["n"], "pp_minutes_per_game": agg["pp_sec"] / 60 / agg["n"],
        "pp_goals_per_game": agg["pp_goals"] / agg["n"], "empty_net_goals_per_game": agg["en"] / agg["n"],
        "ot_rate": agg["ot"] / agg["n"], "so_rate_of_ot": agg["so"] / max(1, agg["ot"]),
        "home_win_pct": agg["home_win"] / agg["n"],
    }
    for k in per_season[0]:
        out[k] = sum(p[k] for p in per_season) / len(per_season)
    return out


REAL_NOTES = {"ot_rate": "NHL ~0.22-0.25 (outside knowledge, not derived)", "home_win_pct": "NHL ~0.54 (outside knowledge)",
              "so_rate_of_ot": "NHL ~0.35-0.45 (outside knowledge)", "empty_net_goals_per_game": "NHL ~0.2 per game (outside knowledge)"}


def compare(sim, env):
    real = dict(env["game"])
    real.update(env["team_spread"])
    rows = []
    for k in ("goals_per_team_game", "sog_per_team_game", "attempts_per_team_game", "sv_pct",
              "penalties_per_game_both_teams", "pp_minutes_per_game", "pp_goals_per_game",
              "cf_pct_sd", "xgf_pct_sd", "sv_pct_sd", "goal_diff_per_game_sd",
              "ot_rate", "so_rate_of_ot", "home_win_pct", "empty_net_goals_per_game"):
        rows.append((k, sim[k], real.get(k), REAL_NOTES.get(k, "")))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db")
    ap.add_argument("env")
    ap.add_argument("--seasons", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--set", nargs="*", default=[], help="Skill overrides, e.g. att=0.08 goalie=0.1")
    ap.add_argument("--tactics", choices=("db", "ai", "none"), default="db",
                    help="db: the clubs' saved tactics; ai: every club (yours too) takes its AI choice; none: no tactics")
    ap.add_argument("--chem", choices=("db", "random", "none"), default="db",
                    help="line chemistry: as saved, random 0-1 per pair (a stress test of its spread), or none")
    a = ap.parse_args(argv)
    env = json.load(open(a.env))
    from ..league.season import db_rules
    from .engine import skill_for
    _c = sqlite3.connect(a.db)
    _c.row_factory = sqlite3.Row
    try:
        _rules = db_rules(_c, base=True)
    except sqlite3.OperationalError:
        _rules = None
    skill = skill_for(_rules, **{k: float(v) for k, v in (s.split("=") for s in a.set)})
    db = a.db
    if a.tactics == "ai":                                  # on a copy: every club takes its AI settings
        import shutil
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        shutil.copyfile(a.db, tmp)
        c2 = sqlite3.connect(tmp)
        c2.row_factory = sqlite3.Row
        from ..game import tactics as TC
        from ..schema import top_league_sql
        TC.ensure_table(c2)
        for (t,) in c2.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}").fetchall():
            TC._save(c2, t, TC.best_settings(c2, t), None, "ai")
        c2.commit()
        use = {}
        for (t,) in c2.execute("SELECT team_id FROM team_tactics"):
            for k, v in TC.settings_of(c2, t).items():
                if v != TC.DEFAULTS[k]:
                    use[f"{k}={v}"] = use.get(f"{k}={v}", 0) + 1
        print("AI choices across the league:", ", ".join(f"{k} x{n}" for k, n in sorted(use.items(), key=lambda x: -x[1])) or "all defaults")
        c2.close()
        db = tmp
    teams = load_teams(sqlite3.connect(db))
    if a.tactics == "none":
        for t in teams.values():
            t.tac = None
    if a.chem == "none":
        for t in teams.values():
            t.chem = {}
    elif a.chem == "random":
        rr = random.Random(a.seed)
        for t in teams.values():
            raw = {frozenset((x.pid, y.pid)): rr.random() for u in t.lines + t.pairs for k, x in enumerate(u) for y in u[k + 1:]}
            t.chem = {k: v - 0.5 for k, v in raw.items()}
    import time
    t0 = time.time()
    sim = run(teams, env, skill, a.seasons, a.seed)
    print(f"{len(teams)} teams, {a.seasons} season(s) in {time.time() - t0:.0f}s   skill={skill}\n")
    print(f"{'metric':<34}{'sim':>10}{'real':>10}  note")
    for k, s, r, note in compare(sim, env):
        print(f"{k:<34}{s:>10.4f}{'' if r is None else format(r, '10.4f')}  {note}")


if __name__ == "__main__":
    main()
