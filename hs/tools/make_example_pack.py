"""Generate a fictional, freely redistributable example pack.

    python -m hs.tools.make_example_pack packs/example_fictional [--seed 7]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from ..attributes import ALL_ATTRS, GOALIE_ATTRS, SKATER_ATTRS

FIRST = ["Alex", "Sam", "Jordan", "Riley", "Casey", "Morgan", "Drew", "Jamie", "Taylor", "Quinn", "Logan",
         "Blake", "Cameron", "Avery", "Reese", "Parker", "Dylan", "Hayden", "Rowan", "Skyler"]
LAST = ["Larsen", "Beaumont", "Kowalski", "Tremblay", "Novak", "Sutter", "Mercer", "Haldane", "Okafor",
        "Lindqvist", "Brandt", "Castellan", "Dufour", "Ellery", "Fairbanks", "Garrity", "Holloway", "Ivanov",
        "Jarvis", "Keane", "Lachance", "Moreau", "Nilsson", "Orlov", "Pelletier"]
TEAMS = [("Northern", "Lights", "NLT"), ("Harbour", "Kings", "HBK"), ("Prairie", "Wolves", "PRW"),
         ("Granite", "Peaks", "GRP"), ("Lakeshore", "Storm", "LKS"), ("Iron", "Ridge", "IRR"),
         ("Coastal", "Gulls", "CGL"), ("Maple", "Valley", "MPV")]
COLORS = ["#1f4e79", "#7b2d26", "#2e6b3a", "#555555", "#6a3d9a", "#b36b00", "#0b7285", "#8a1c3c"]
ROSTER = ["C"] * 4 + ["LW"] * 4 + ["RW"] * 4 + ["D"] * 6 + ["G"] * 2
# attribute bonuses by archetype (added to a team/player base rating)
ARCHETYPES = {
    "sniper": {"shot_accuracy": 4, "shot_power": 3, "offensive_awareness": 2},
    "playmaker": {"passing": 4, "puck_control": 3, "offensive_awareness": 2},
    "two_way": {"defensive_awareness": 3, "checking": 2, "positioning": 3},
    "grinder": {"hitting": 4, "strength": 3, "toughness": 3, "net_presence": 2},
    "offensive_d": {"shot_power": 3, "passing": 3, "puck_control": 2},
    "defensive_d": {"checking": 4, "stick_checking": 3, "shot_blocking": 4, "positioning": 3},
}


def _w(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def generate(out: Path, seed=7):
    rng = random.Random(seed)
    clip = lambda v: max(1, min(20, int(round(v))))
    _w(out / "leagues.csv", ["league_id", "name", "abbr", "country", "level", "games_per_team"],
       [[1, "Demo Hockey League", "DHL", "", 1, 56]])
    _w(out / "teams.csv", ["team_id", "league_id", "name", "nickname", "abbr", "conference", "division",
                           "primary_color", "secondary_color", "logo"],
       [[i + 1, 1, c, n, a, "East" if i < 4 else "West", ["North", "South", "Prairie", "Coast"][i // 2], COLORS[i], "#ffffff", ""]
        for i, (c, n, a) in enumerate(TEAMS)])
    players, attrs, contracts, pid = [], [], [], 0
    for ti in range(len(TEAMS)):
        base = rng.gauss(10.5, 0.25)   # team strength spread kept close to a real league (see docs/SIM_CALIBRATION.md)
        for pos in ROSTER:
            pid += 1
            kind = (rng.choice(["sniper", "playmaker", "two_way", "grinder"]) if pos in ("C", "LW", "RW")
                    else rng.choice(["offensive_d", "defensive_d", "two_way"]) if pos == "D" else None)
            bonus = ARCHETYPES.get(kind, {})
            age = rng.randint(19, 36)
            players.append([pid, rng.choice(FIRST), rng.choice(LAST), f"{2026 - age}-{rng.randint(1, 12):02d}-"
                            f"{rng.randint(1, 28):02d}", pos, rng.choice("LR"), rng.randint(173, 200),
                            rng.randint(75, 105), "", ti + 1, "active"])
            wanted = GOALIE_ATTRS if pos == "G" else SKATER_ATTRS
            row = {a: clip(rng.gauss(base + bonus.get(a, 0), 1.8)) if a in wanted else "" for a in ALL_ATTRS}
            attrs.append([pid] + [row[a] for a in ALL_ATTRS] + [clip(rng.gauss(base + 1, 2.5))])
            years, raw = rng.randint(1, 5), rng.randint(750, 9000)   # same draws as before: rosters unchanged
            contracts.append([pid, ti + 1, 2026, years, int(850 + (raw - 750) * 0.6) * 1000, "standard", 0])
    fa_rng = random.Random(seed + 1000)   # separate stream so team rosters are unchanged by free agents
    for pos in ["C", "C", "LW", "LW", "RW", "RW", "D", "D", "D", "D", "G", "G"] * 2:
        pid += 1
        age = fa_rng.randint(20, 37)
        players.append([pid, fa_rng.choice(FIRST), fa_rng.choice(LAST), f"{2026 - age}-{fa_rng.randint(1, 12):02d}-"
                        f"{fa_rng.randint(1, 28):02d}", pos, fa_rng.choice("LR"), fa_rng.randint(173, 200),
                        fa_rng.randint(75, 105), "", "", "active"])
        wanted = GOALIE_ATTRS if pos == "G" else SKATER_ATTRS
        row = {a: clip(fa_rng.gauss(9.0, 1.8)) if a in wanted else "" for a in ALL_ATTRS}
        attrs.append([pid] + [row[a] for a in ALL_ATTRS] + [clip(fa_rng.gauss(9.5, 2.5))])
    _w(out / "players.csv", ["player_id", "first_name", "last_name", "birth_date", "position", "shoots",
                             "height_cm", "weight_kg", "nationality", "team_id", "status"], players)
    _w(out / "attributes.csv", ["player_id"] + ALL_ATTRS + ["potential"], attrs)
    _w(out / "contracts.csv", ["player_id", "team_id", "start_year", "years", "cap_hit", "contract_type",
                               "no_trade"], contracts)
    (out / "rules.json").write_text(json.dumps({
        "name": "Demo Hockey League rules",
        "season": {"start": "2026-10-01", "end": "2027-02-28", "breaks": []},
        "schedule": {"games_per_team": 56, "same_division": {"games": 8, "reduced_games": 8, "reduced_opponents_per_team": 0},
                     "same_conference": {"games": 4}, "other_conference": {"games": 10}},
        "playoffs": {"format": "conference_top_n", "teams_per_conference": 2, "series_length": 5,
                     "home_pattern": [1, 1, 0, 0, 1]}}, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "format_version": "0.1", "name": "example-fictional", "version": "1", "source": "generated",
        "redistributable": True, "contains_real_names": False, "season_start_year": 2026,
        "license": "CC0-1.0", "description": "Fictional 8-team league with generated players, for testing."},
        indent=2), encoding="utf-8")
    return pid


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    print(f"wrote {generate(Path(a.out), a.seed)} players to {a.out}")


if __name__ == "__main__":
    main()
