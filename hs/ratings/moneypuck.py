"""Derive 1-20 player ratings from observed outcomes (MoneyPuck season summaries) -> data pack.

    python -m hs.ratings.moneypuck <moneypuck_dir> <out_pack_dir> [--season 2025] [--backtest]

Method (all of it is ours; only the *inputs* come from MoneyPuck):
  1. Per player-season, take process rates (shot attempts/60, xG per shot, hits/60, ...) at 5-on-5
     (goalies: all situations, per shot). On-ice metrics are measured relative to the player's team.
  2. Measure how repeatable each rate is (year-to-year correlation r among qualified players). That gives the
     true-talent spread  sd_true = sd_observed * sqrt(r)  and a shrinkage constant  k = n0 * (1 - r) / r.
  3. Pool the last 3 seasons (recency weighted), shrink toward the league mean by n / (n + k): noisy stats
     such as finishing move little, repeatable ones such as hits move a lot.
  4. Rating = 10.5 + 3 * (z in units of true-talent sd), so 3 rating points ~ 1 sd of real skill.
  5. Attributes are weighted blends of those z-scores (ATTRIBUTE_MODEL). Attributes with no observable
     signal in this data are set to a neutral 10 (UNMEASURED) until another source provides them.

PERSONAL / NON-COMMERCIAL USE: MoneyPuck data is free for non-commercial use with credit to MoneyPuck.com.
Packs made here contain real names and are marked redistributable=false.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from ..attributes import ALL_ATTRS

CENTRE, SPREAD = 10.5, 3.0     # rating = CENTRE + SPREAD * z(true-talent sd)
NEUTRAL = 10
SEASON_WEIGHTS = (1.0, 0.6, 0.36)   # this season, last, the one before
MIN_5V5_MIN = 400                   # qualification for calibration (skaters, 5on5 minutes)
MIN_G_SOG = 500                     # qualification for calibration (goalies)


def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return 0.0


def mins(r):
    return f(r, "icetime") / 60.0


# metric -> (numerator(row), denominator(row), higher_is_better, team_relative, min_den)
SKATER_METRICS = {
    "att60":   (lambda r: f(r, "I_F_shotAttempts") * 60, mins, 1, False, 0),
    "xg60":    (lambda r: f(r, "I_F_xGoals") * 60, mins, 1, False, 0),
    "shotq":   (lambda r: f(r, "I_F_xGoals"), lambda r: f(r, "I_F_unblockedShotAttempts"), 1, False, 40),
    "acc":     (lambda r: f(r, "I_F_shotsOnGoal"), lambda r: f(r, "I_F_unblockedShotAttempts"), 1, False, 40),
    "fin":     (lambda r: f(r, "I_F_goals") - f(r, "I_F_xGoals"), lambda r: f(r, "I_F_unblockedShotAttempts"), 1, False, 40),
    "hdshare": (lambda r: f(r, "I_F_highDangerShots"), lambda r: f(r, "I_F_unblockedShotAttempts"), 1, False, 40),
    "pa60":    (lambda r: f(r, "I_F_primaryAssists") * 60, mins, 1, False, 0),
    "pts60":   (lambda r: f(r, "I_F_points") * 60, mins, 1, False, 0),
    "hits60":  (lambda r: f(r, "I_F_hits") * 60, mins, 1, False, 0),
    "blocks60": (lambda r: f(r, "shotsBlockedByPlayer") * 60, mins, 1, False, 0),
    "take60":  (lambda r: f(r, "I_F_takeaways") * 60, mins, 1, False, 0),
    "give60":  (lambda r: f(r, "I_F_giveaways") * 60, mins, -1, False, 0),
    "pen60":   (lambda r: f(r, "penalties") * 60, mins, -1, False, 0),
    "pim60":   (lambda r: f(r, "penalityMinutes") * 60, mins, 1, False, 0),
    "fo":      (lambda r: f(r, "faceoffsWon"), lambda r: f(r, "faceoffsWon") + f(r, "faceoffsLost"), 1, False, 150),
    "xgf_on":  (lambda r: f(r, "OnIce_F_xGoals") * 60, mins, 1, True, 0),
    "xga_on":  (lambda r: f(r, "OnIce_A_xGoals") * 60, mins, -1, True, 0),
    "satt_a":  (lambda r: f(r, "OnIce_A_shotAttempts") * 60, mins, -1, True, 0),
}
GOALIE_METRICS = {
    "sae":   (lambda r: f(r, "xGoals") - f(r, "goals"), lambda r: f(r, "ongoal"), 1, False, 0),
    "hd_sae": (lambda r: f(r, "highDangerxGoals") - f(r, "highDangerGoals"), lambda r: f(r, "highDangerShots"), 1, False, 100),
    "md_sae": (lambda r: f(r, "mediumDangerxGoals") - f(r, "mediumDangerGoals"), lambda r: f(r, "mediumDangerShots"), 1, False, 100),
    "ld_sae": (lambda r: f(r, "lowDangerxGoals") - f(r, "lowDangerGoals"), lambda r: f(r, "lowDangerShots"), 1, False, 300),
    "reb":   (lambda r: f(r, "rebounds") - f(r, "xRebounds"), lambda r: f(r, "ongoal"), -1, False, 0),
    "frz":   (lambda r: f(r, "freeze") - f(r, "xFreeze"), lambda r: f(r, "ongoal"), 1, False, 0),
}
# attribute -> {metric: weight}.  'weight_lb' is body weight from the bios file (an observed fact, no shrinkage).
ATTRIBUTE_MODEL = {
    "F": {
        "shot_accuracy": {"acc": .5, "fin": .5}, "shot_power": {"fin": .5, "acc": .5},
        # v25: 5-on-5 points per 60 added (a strong, repeatable talent signal); giveaways dropped from puck control
        # (they rise with how much a player carries the puck, so they marked the best puck carriers down)
        "passing": {"pa60": .4, "pts60": .3, "xgf_on": .3}, "puck_control": {"att60": .5, "xgf_on": .3, "pts60": .2},
        "offensive_awareness": {"xg60": .35, "pts60": .3, "shotq": .2, "hdshare": .15}, "net_presence": {"hdshare": 1},
        "faceoffs": {"fo": 1},
        "checking": {"hits60": .3, "take60": .3, "xga_on": .4}, "stick_checking": {"take60": .6, "satt_a": .4},
        "shot_blocking": {"blocks60": 1}, "positioning": {"xga_on": .5, "satt_a": .5},
        "defensive_awareness": {"take60": .5, "xga_on": .5},
        "strength": {"hits60": .5, "weight_lb": .5}, "hitting": {"hits60": 1}, "toughness": {"pim60": 1},
        "aggression": {"pim60": .5, "hits60": .5}, "bravery": {"blocks60": .5, "hits60": .5},
        "composure": {"pen60": 1},
    },
    "G": {
        "goalie_positioning": {"sae": .5, "hd_sae": .5}, "reflexes": {"hd_sae": 1},
        "glove": {"md_sae": .5, "sae": .5}, "blocker": {"ld_sae": .5, "sae": .5},
        "low_shot_save": {"ld_sae": 1}, "rebound_control": {"reb": 1}, "recovery": {"frz": 1},
    },
}
ATTRIBUTE_MODEL["D"] = ATTRIBUTE_MODEL["F"]
MEASURED_DIRECT = {"hitting", "toughness", "shot_blocking", "faceoffs", "rebound_control", "recovery"}
UNMEASURED = [a for a in ALL_ATTRS if a not in ATTRIBUTE_MODEL["F"] and a not in ATTRIBUTE_MODEL["G"]]
GROUP = {"C": "F", "L": "F", "R": "F", "D": "D", "G": "G"}
POS_NAME = {"C": "C", "L": "LW", "R": "RW", "D": "D", "G": "G"}


# ---------------------------------------------------------------- loading
def load_seasons(mp: Path):
    """season -> pid -> {'g': group, 'name', 'team', 'm': {metric: (num, den)}, 'q': qualifies, 'all': row-all}"""
    data = {}
    for p in sorted(mp.glob("skaters_*.csv")):
        y = int(p.stem.split("_")[1])
        rows = list(csv.DictReader(open(p, encoding="utf-8")))
        s5 = {r["playerId"]: r for r in rows if r["situation"] == "5on5"}
        al = {r["playerId"]: r for r in rows if r["situation"] == "all"}
        seas = {}
        for pid, r in s5.items():
            g = GROUP.get(r["position"])
            if g in ("F", "D"):
                seas[pid] = {"g": g, "name": r["name"], "team": r["team"], "pos": r["position"], "all": al.get(pid),
                             "m": {k: (fn(r), fd(r)) for k, (fn, fd, _, _, _) in SKATER_METRICS.items()},
                             "q": mins(r) >= MIN_5V5_MIN}
        _team_adjust(seas)
        data.setdefault(y, {}).update(seas)
    for p in sorted(mp.glob("goalies_*.csv")):
        y = int(p.stem.split("_")[1])
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r["situation"] == "all":
                data.setdefault(y, {})[r["playerId"]] = {
                    "g": "G", "name": r["name"], "team": r["team"], "pos": "G", "all": r,
                    "m": {k: (fn(r), fd(r)) for k, (fn, fd, _, _, _) in GOALIE_METRICS.items()},
                    "q": f(r, "ongoal") >= MIN_G_SOG}
    for y in data:
        _centre_on_league(data[y], SKATER_METRICS, GOALIE_METRICS)
    return data


def _centre_on_league(seas, skater_metrics, goalie_metrics):
    """Express every metric as a deviation from that season's league rate, so scoring-environment drift
    between eras (e.g. shooting % rising from 8.5% to 10.5%) does not leak into ratings."""
    for grp in ("F", "D", "G"):
        metrics = goalie_metrics if grp == "G" else skater_metrics
        rows = [s for s in seas.values() if s["g"] == grp and s["q"]]
        for m, (_, _, _, _, min_den) in metrics.items():
            tn = sum(s["m"][m][0] for s in rows if s["m"][m][1] >= max(min_den, 1e-9))
            td = sum(s["m"][m][1] for s in rows if s["m"][m][1] >= max(min_den, 1e-9))
            mu = tn / td if td else 0.0
            for s in seas.values():
                if s["g"] == grp:
                    n, d = s["m"][m]
                    s["m"][m] = (n - mu * d, d)


def _team_adjust(seas):
    """Replace on-ice (num, den) by (num - team_rate * den, den): performance relative to the team."""
    for metric, (_, _, _, rel, _) in SKATER_METRICS.items():
        if not rel:
            continue
        tot = defaultdict(lambda: [0.0, 0.0])
        for pid, s in seas.items():
            n, d = s["m"][metric]
            t = tot[(s["team"], s["g"])]
            t[0] += n
            t[1] += d
        for pid, s in seas.items():
            n, d = s["m"][metric]
            tn, td = tot[(s["team"], s["g"])]
            s["m"][metric] = (n - (tn / td if td else 0) * d, d)


# ---------------------------------------------------------------- calibration
def corr(a, b):
    n = len(a)
    if n < 3:
        return float("nan")
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else float("nan")


def calibrate(data, upto):
    """Per (group, metric): mu, sd_obs, r, n0, sd_true, k  — using only seasons <= upto."""
    params = {}
    for grp, metrics in (("F", SKATER_METRICS), ("D", SKATER_METRICS), ("G", GOALIE_METRICS)):
        for m, (_, _, sign, _, min_den) in metrics.items():
            xs, dens, a, b = [], [], [], []
            for y in sorted(k for k in data if k <= upto):
                for pid, s in data[y].items():
                    if s["g"] != grp or not s["q"] or s["m"][m][1] < max(min_den, 1e-9):
                        continue
                    n, d = s["m"][m]
                    xs.append(n / d)
                    dens.append(d)
                    nxt = data.get(y + 1, {}).get(pid)
                    if y + 1 <= upto and nxt and nxt["q"] and nxt["m"][m][1] >= max(min_den, 1e-9):
                        a.append(n / d)
                        b.append(nxt["m"][m][0] / nxt["m"][m][1])
            if len(xs) < 30:
                continue
            tot_d = sum(dens)
            mu = sum(x * d for x, d in zip(xs, dens)) / tot_d
            sd_obs = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))
            r = max(0.02, min(0.98, corr(a, b))) if len(a) > 30 else 0.3
            n0 = tot_d / len(xs)
            params[(grp, m)] = {"mu": mu, "sd_obs": sd_obs, "r": r, "n0": n0,
                                "sd_true": sd_obs * math.sqrt(r), "k": n0 * (1 - r) / r,
                                "sign": sign, "n_players": len(xs), "n_pairs": len(a)}
    return params


def pooled(data, pid, season):
    """Recency-weighted (num, den) for a player over the last three seasons; also returns last row seen."""
    num = den = 0.0
    out, last = {}, None
    for i, w in enumerate(SEASON_WEIGHTS):
        s = data.get(season - i, {}).get(pid)
        if s:
            last = last or s
            for m, (n, d) in s["m"].items():
                a = out.setdefault(m, [0.0, 0.0])
                a[0] += w * n
                a[1] += w * d
    return out, last


def z_scores(pooled_m, grp, params):
    z = {}
    for (g, m), p in params.items():
        if g != grp or m not in pooled_m:
            continue
        n, d = pooled_m[m]
        raw = n / d if d > 0 else p["mu"]
        shrunk = p["mu"] + (raw - p["mu"]) * d / (d + p["k"]) if d > 0 else p["mu"]
        z[m] = p["sign"] * (shrunk - p["mu"]) / p["sd_true"] if p["sd_true"] else 0.0
    return z


def clamp_rating(x):
    return max(1, min(20, int(math.floor(x + 0.5))))


def attributes_for(z, grp, weight_z=0.0):
    z = dict(z, weight_lb=weight_z)
    row = {}
    for a in ALL_ATTRS:
        spec = ATTRIBUTE_MODEL[grp].get(a)
        if spec is None:
            row[a] = NEUTRAL if (grp == "G") == (a in ATTRIBUTE_MODEL["G"] or a.startswith("goalie_") or a in
                                                  ("reflexes", "glove", "blocker", "rebound_control", "recovery",
                                                   "poke_check", "low_shot_save")) else ""
            continue
        tw = sum(spec.values())
        row[a] = clamp_rating(CENTRE + SPREAD * sum(w * z.get(m, 0.0) for m, w in spec.items()) / tw)
    return row


# ---------------------------------------------------------------- bios
def parse_height(s):
    m = re.match(r"\s*(\d+)'\s*(\d+)", s or "")
    return round((int(m.group(1)) * 12 + int(m.group(2))) * 2.54) if m else ""


def read_bios(mp: Path):
    bios = {}
    for r in csv.DictReader(open(mp / "allPlayersLookup.csv", encoding="utf-8")):
        bios[r["playerId"]] = r
    return bios


# ---------------------------------------------------------------- pack writer
def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def _rules_start_year(structure):
    """Season year of a league structure's own calendar (so the pack and its rules agree)."""
    from importlib import import_module
    rules = import_module(f"hs.leaguedata.{structure}").RULES
    return rules["season"]["start"][:4]


def build_pack(mp: Path, out: Path, season: int, structure=None):
    data = load_seasons(mp)
    params = calibrate(data, season)
    bios = read_bios(mp)
    weights_lb = {"F": [], "D": []}
    for pid, s in data[season].items():
        b = bios.get(pid)
        if s["g"] in weights_lb and b and f(b, "weight") > 0:
            weights_lb[s["g"]].append(f(b, "weight"))
    wstats = {g: (sum(v) / len(v), math.sqrt(sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)))
              for g, v in weights_lb.items()}
    abbrs = sorted({s["team"] for y in data for s in data[y].values()})
    tid = {a: i + 1 for i, a in enumerate(abbrs)}
    current = sorted({s["team"] for s in data[season].values()})
    stats = {}
    info = {}
    if structure == "nhl_2025_26":      # real league structure + rules (personal packs only; see the module docstring)
        from ..leaguedata import nhl_2025_26 as nhl
        info = nhl.TEAMS
        unknown = [a for a in current if a not in info]
        if unknown:
            raise ValueError(f"teams not in the nhl_2025_26 structure: {unknown}")
        (out).mkdir(parents=True, exist_ok=True)
        (out / "rules.json").write_text(json.dumps(nhl.RULES, indent=1), encoding="utf-8")
    elif structure:
        raise ValueError(f"unknown structure '{structure}'")
    stats["teams"] = write_csv(out / "teams.csv",
                               ["team_id", "league_id", "name", "nickname", "abbr", "conference", "division",
                                "primary_color", "secondary_color", "logo"],
                               [[tid[a], 1, *( (info[a][0], info[a][1], a, info[a][2], info[a][3]) if a in info
                                              else (a, a, a, "", "")), "", "", ""] for a in current])
    write_csv(out / "leagues.csv", ["league_id", "name", "abbr", "country", "level", "games_per_team"],
              [[1, "National Hockey League", "NHL", "", 1, 82]])
    players, attrs, missing_bio = [], [], 0
    seen = {pid for y in data for pid in data[y]}
    for pid in sorted(seen, key=int):
        b = bios.get(pid)
        if not b or not re.match(r"^\d{4}-\d{2}-\d{2}$", b.get("birthDate") or ""):
            missing_bio += 1
            continue
        recent = next((data[y][pid] for y in sorted(data, reverse=True) if pid in data[y]), None)
        pos_code = b.get("position") or (recent or {}).get("pos") or "C"
        grp = GROUP.get(pos_code, "F")
        active = pid in data[season]
        first, _, last = b["name"].partition(" ")
        players.append([pid, first, last or first, b["birthDate"], POS_NAME.get(pos_code, "C"),
                        b.get("shootsCatches", ""), parse_height(b.get("height")),
                        round(f(b, "weight") * 0.4536) if f(b, "weight") else "", b.get("nationality", ""),
                        tid[data[season][pid]["team"]] if active and data[season][pid]["team"] in current else "",
                        "active" if active else "retired"])
        if active:
            pm, _ = pooled(data, pid, season)
            z = z_scores(pm, grp, params)
            wz = 0.0
            if grp in wstats and f(b, "weight") > 0:
                wz = (f(b, "weight") - wstats[grp][0]) / wstats[grp][1] / 1.0 if wstats[grp][1] else 0.0
            row = attributes_for(z, grp, wz)
            attrs.append([pid] + [row[a] for a in ALL_ATTRS] + [""])
    stats["players"] = write_csv(out / "players.csv",
                                 ["player_id", "first_name", "last_name", "birth_date", "position", "shoots",
                                  "height_cm", "weight_kg", "nationality", "team_id", "status"], players)
    stats["attribute_rows"] = write_csv(out / "attributes.csv", ["player_id"] + ALL_ATTRS + ["potential"], attrs)
    stats["skipped_no_bio_or_dob"] = missing_bio
    known = {p[0] for p in players}
    sk, gl = [], []
    for y in sorted(data):
        for pid, s in data[y].items():
            r = s["all"]
            if pid not in known or r is None:
                continue
            base = [pid, y, tid[s["team"]], 1, "RS"]
            if s["g"] == "G":
                gl.append(base + [int(f(r, "games_played")), "", round(f(r, "icetime")), "", "", "", "",
                                  round(f(r, "goals")), round(f(r, "ongoal"))])
            else:
                sk.append(base + [int(f(r, "games_played")), round(f(r, "I_F_goals")),
                                  round(f(r, "I_F_primaryAssists") + f(r, "I_F_secondaryAssists")),
                                  round(f(r, "penalityMinutes")), "", round(f(r, "I_F_shotsOnGoal")),
                                  round(f(r, "icetime"))])
    stats["skater_season_rows"] = write_csv(
        out / "history" / "skater_seasons.csv",
        ["player_id", "season", "team_id", "league_id", "split", "gp", "g", "a", "pim", "plus_minus", "sog", "toi_sec"], sk)
    stats["goalie_season_rows"] = write_csv(
        out / "history" / "goalie_seasons.csv",
        ["player_id", "season", "team_id", "league_id", "split", "gp", "gs", "toi_sec", "w", "l", "otl", "so", "ga", "sa"], gl)
    (out / "manifest.json").write_text(json.dumps({
        "format_version": "0.1", "name": f"moneypuck-derived-{season}", "version": "1", "source": "moneypuck_ratings",
        "redistributable": False, "contains_real_names": True, "season_start_year": (int(_rules_start_year(structure)) if structure else season + 1),
        "description": "Ratings derived from MoneyPuck.com season summaries (non-commercial use, credit MoneyPuck.com). "
                       "Team names are abbreviations only. PERSONAL USE ONLY."}, indent=2), encoding="utf-8")
    (out / "ratings_model.json").write_text(json.dumps({
        "centre": CENTRE, "spread_per_sd_true_talent": SPREAD, "season_weights": SEASON_WEIGHTS,
        "unmeasured_attributes_set_to_neutral": UNMEASURED, "attribute_model": ATTRIBUTE_MODEL,
        "metric_params": {f"{g}.{m}": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in p.items()}
                          for (g, m), p in params.items()}}, indent=1), encoding="utf-8")
    (out / "README.txt").write_text("PERSONAL USE ONLY. Derived from MoneyPuck.com data (non-commercial use, credit "
                                    "MoneyPuck.com). Do not publish or commit.\n", encoding="utf-8")
    return stats, params


# ---------------------------------------------------------------- backtest
def backtest(mp: Path, first=2013, last=2024):
    """Does shrunk, pooled history predict next season better than last season's raw number?"""
    data = load_seasons(mp)
    agg = defaultdict(lambda: {"raw": [], "shr": [], "act": []})
    for T in range(first, last + 1):
        params = calibrate(data, T)
        for pid, s in data[T].items():
            nxt = data.get(T + 1, {}).get(pid)
            if not nxt or not nxt["q"] or not s["q"]:
                continue
            pm, _ = pooled(data, pid, T)
            for (g, m), p in params.items():
                if g != s["g"] or m not in pm or m not in nxt["m"]:
                    continue
                n, d = pm[m]
                nn, nd = nxt["m"][m]
                min_den = (SKATER_METRICS if g != "G" else GOALIE_METRICS)[m][4]
                if d <= 0 or nd <= max(min_den, 1e-9) or s["m"][m][1] < max(min_den, 1e-9):
                    continue
                raw = s["m"][m][0] / s["m"][m][1]
                shr = p["mu"] + (n / d - p["mu"]) * d / (d + p["k"])
                a = agg[(g, m)]
                a["raw"].append(raw)
                a["shr"].append(shr)
                a["act"].append(nn / nd)
    print(f"{'group.metric':<14}{'n':>6}{'r(raw)':>9}{'r(model)':>10}{'RMSE raw':>11}{'RMSE model':>12}")
    for (g, m), a in sorted(agg.items()):
        rmse = lambda x: math.sqrt(sum((u - v) ** 2 for u, v in zip(x, a["act"])) / len(x))
        print(f"{g + '.' + m:<14}{len(a['act']):>6}{corr(a['raw'], a['act']):>9.2f}{corr(a['shr'], a['act']):>10.2f}"
              f"{rmse(a['raw']):>11.4f}{rmse(a['shr']):>12.4f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moneypuck_dir")
    ap.add_argument("out_pack", nargs="?")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--structure", choices=["nhl_2025_26"], help="add real league structure and rules.json")
    a = ap.parse_args(argv)
    if a.backtest:
        backtest(Path(a.moneypuck_dir))
    if a.out_pack:
        stats, _ = build_pack(Path(a.moneypuck_dir), Path(a.out_pack), a.season, a.structure)
        for k, v in stats.items():
            print(f"  {k:<22}{v:>9}")


if __name__ == "__main__":
    main()
