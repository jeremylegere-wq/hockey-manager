"""League environment: the real-world numbers the simulator is calibrated against, per game situation.

    python -m hs.sim.env <moneypuck_dir> --season 2025 [--out env_2025.json]

Everything is derived from MoneyPuck season summaries (personal / non-commercial use, credit MoneyPuck.com).
Team rate per 60 for a situation = sum of players' on-ice counts * 60 / sum of players' minutes (the number of
skaters on the ice cancels out), so no team or line data is needed.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return 0.0


def sd(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def read(mp: Path, kind: str, season: int):
    return list(csv.DictReader(open(mp / f"{kind}_{season}.csv", encoding="utf-8")))


def league_env(mp: Path, season: int) -> dict:
    sk, gl = read(mp, "skaters", season), read(mp, "goalies", season)
    games = sum(f(r, "icetime") for r in gl if r["situation"] == "all") / 3600.0 / 2.0
    env = {"season": season, "games": round(games, 1)}
    tot = lambda rows, k: sum(f(r, k) for r in rows)
    for sit, label in (("5on5", "ev"), ("5on4", "pp"), ("4on5", "sh")):
        rows = [r for r in sk if r["situation"] == sit]
        mins = tot(rows, "icetime") / 60.0
        att, blk = tot(rows, "OnIce_F_shotAttempts"), tot(rows, "OnIce_F_blockedShotAttempts")
        mis, sog = tot(rows, "OnIce_F_missedShots"), tot(rows, "OnIce_F_shotsOnGoal")
        gls, xg = tot(rows, "OnIce_F_goals"), tot(rows, "OnIce_F_xGoals")
        reb, rebg = tot(rows, "OnIce_F_rebounds"), tot(rows, "OnIce_F_reboundGoals")
        pl_att = tot(rows, "I_F_shotAttempts")
        d_att = sum(f(r, "I_F_shotAttempts") for r in rows if r["position"] == "D")
        d_g, pl_g = sum(f(r, "I_F_goals") for r in rows if r["position"] == "D"), tot(rows, "I_F_goals")
        env[label] = {
            "att60": att / mins * 60, "blocked_frac": blk / att, "missed_frac": mis / (att - blk),
            "sh_pct": gls / sog,
            "sh_pct_regular": (gls - rebg) / (sog - reb * sog / att), "goals60": gls / mins * 60, "xg_per_unblocked": xg / (att - blk),
            "rebound_att_per_sog": reb / sog, "rebound_frac_of_attempts": reb / att,
            "rebound_sh_pct": rebg / max(1.0, reb * sog / att),
            "d_attempt_share": d_att / pl_att,
            "d_goal_factor": (d_g / d_att) / (pl_g / pl_att) if d_att and pl_g else 0.46,
            "minutes_per_game_all_players": mins / games,
        }
    allrows = [r for r in sk if r["situation"] == "all"]
    penalties = tot(allrows, "penalties")
    g_all = sum(f(r, "goals") for r in gl if r["situation"] == "all")
    sog_all = sum(f(r, "ongoal") for r in gl if r["situation"] == "all")
    ev_min = tot([r for r in sk if r["situation"] == "5on5"], "icetime") / 60 / 10      # 5v5 minutes (both teams)
    pp_min = tot([r for r in sk if r["situation"] == "5on4"], "icetime") / 60 / 5       # PP minutes (power-play side)
    pri, sec = tot(allrows, "I_F_primaryAssists"), tot(allrows, "I_F_secondaryAssists")
    gls_ind = tot(allrows, "I_F_goals")
    env["game"] = {
        "goals_per_team_game": g_all / games / 2, "sog_per_team_game": sog_all / games / 2,
        "sv_pct": 1 - g_all / sog_all, "penalties_per_game_both_teams": penalties / games,
        "pp_minutes_per_game": pp_min / games, "ev_minutes_per_game": ev_min / games,
        "pp_goals_per_game": tot([r for r in sk if r["situation"] == "5on4"], "OnIce_F_goals") / 5 / games,
        "primary_assists_per_goal": pri / gls_ind, "secondary_assists_per_goal": sec / gls_ind,
        "attempts_per_team_game": tot(allrows, "OnIce_F_shotAttempts") / tot(allrows, "icetime") * 3600 * 0 +
        tot(allrows, "I_F_shotAttempts") / games / 2,
    }
    # share of goals scored in situations the sim does not model explicitly (4v4, 3v3, 6v5, empty net, 5v3 ...)
    oth = tot([r for r in sk if r["situation"] == "other"], "OnIce_F_goals")
    env["game"]["other_situation_goals_share"] = oth / max(1.0, tot([r for r in sk if r["situation"] == "all"], "OnIce_F_goals"))
    return env


def team_spreads(mp: Path, seasons) -> dict:
    """Spread of team results across the league, observed (includes luck), averaged over seasons.
    The simulator is tuned to reproduce these when it plays the same rosters."""
    out = defaultdict(list)
    for s in seasons:
        sk, gl = read(mp, "skaters", s), read(mp, "goalies", s)
        t = defaultdict(lambda: defaultdict(float))
        for r in sk:
            if r["situation"] == "5on5":
                for k in ("OnIce_F_shotAttempts", "OnIce_A_shotAttempts", "OnIce_F_xGoals", "OnIce_A_xGoals",
                          "OnIce_F_unblockedShotAttempts", "OnIce_F_goals", "OnIce_A_goals"):
                    t[r["team"]][k] += f(r, k)
            elif r["situation"] == "all":
                t[r["team"]]["gf"] += f(r, "OnIce_F_goals")
                t[r["team"]]["ga"] += f(r, "OnIce_A_goals")
        for r in gl:
            if r["situation"] == "all":
                x = t[r["team"]]
                x["sa"] += f(r, "ongoal")
                x["goals_against_g"] += f(r, "goals")
                x["games"] += f(r, "icetime") / 3600.0
        teams = [x for x in t.values() if x["games"] > 20 and x["OnIce_F_shotAttempts"] > 0]
        # skater sums count each team event once per skater; ratios and per-game figures need care:
        out["cf_pct_sd"].append(sd([x["OnIce_F_shotAttempts"] / (x["OnIce_F_shotAttempts"] + x["OnIce_A_shotAttempts"]) for x in teams]))
        out["xgf_pct_sd"].append(sd([x["OnIce_F_xGoals"] / (x["OnIce_F_xGoals"] + x["OnIce_A_xGoals"]) for x in teams]))
        out["sv_pct_sd"].append(sd([1 - x["goals_against_g"] / x["sa"] for x in teams if x["sa"] > 0]))
        out["goal_diff_per_game_sd"].append(sd([(x["gf"] - x["ga"]) / 5.0 / x["games"] for x in teams]))
    return {k: round(sum(v) / len(v), 5) for k, v in out.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moneypuck_dir")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--spread-seasons", type=int, default=6, help="how many recent seasons for team spreads")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    mp = Path(a.moneypuck_dir)
    env = league_env(mp, a.season)
    env["team_spread"] = team_spreads(mp, [s for s in range(a.season - a.spread_seasons + 1, a.season + 1) if s != 2020])
    text = json.dumps(env, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
