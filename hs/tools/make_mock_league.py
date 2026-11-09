"""A fictional 32-club top league (a data pack), the base of the mock world that ships with the game.

    python -m hs.tools.make_mock_league packs/mock_league [--seed 1]

32 invented clubs in two conferences and four divisions, 26 generated players each (23 dress, three start on the
farm), contracts under a salary cap, an 82-game schedule (84 from 2026-27 under the era preset) and the usual playoff format. Players come from the same
calibrated generator as the farm and junior leagues (hs/worldgen.py), so the league plays like the real one:
about six goals a game, a penalty or two a side. Names, places and clubs are made up; the pack is CC0.

Next: `python -m hs.tools.build_world packs/mock_league packs/mock_world --fictional` adds the farm, junior,
college and European leagues, and `python -m hs.ingest packs/mock_world world.db` builds the game database.
`python -m hs.tools.make_mock_world` does all three.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from ..attributes import ALL_ATTRS
from ..leaguedata import fictional as FIC
from ..leaguedata import nhl_2025_26 as NHL
from ..leaguedata import world_2025_26 as W
from ..worldgen import gen_player, overall_of

SEASON = 2026
ROSTER = {"C": 5, "LW": 5, "RW": 5, "D": 8, "G": 3}
NHL_MEAN, NHL_SD = 10.55, 0.67                       # the dressed NHL player (docs/SIM_CALIBRATION.md)
MIX = {"CAN": 42, "USA": 28, "SWE": 8, "FIN": 5, "RUS": 5, "CZE": 4, "SVK": 2, "SUI": 2, "GER": 2, "DEN": 0}
MIX = {k: v for k, v in MIX.items() if v and k in W.NAMES}
NAT_FALLBACK = {"DEN": "SWE"}
CAP = 95_500_000
FREE_AGENTS = 60


def _w(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _color(i):
    import colorsys
    r, g, b = colorsys.hls_to_rgb((i * 0.381966) % 1, 0.32, 0.55)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _salary(ov, age, rng):
    """Cap hit from quality: ~$0.8M for a fringe player up to ~$12M for a star; entry-level deals for the young."""
    z = (ov - NHL_MEAN) / NHL_SD
    if age <= 21:
        return 950_000 + int(rng.random() * 400_000), "entry_level"
    hit = 3_300_000 * 2.718 ** (0.85 * z) * rng.uniform(0.85, 1.15)
    return int(max(775_000, min(12_500_000, hit)) // 25_000 * 25_000), "standard"


def generate(out: Path, seed=1):
    rng = random.Random(f"mock-league-{seed}")
    out = Path(out)
    _w(out / "leagues.csv", ["league_id", "name", "abbr", "country", "level", "games_per_team"],
       [[1, "Premier Hockey League", "PHL", "", 1, 82]])
    teams = []
    for i, (city, nick, abbr, conf, div) in enumerate(FIC.NHL_CLUBS):
        teams.append([i + 1, 1, city, nick, abbr, conf, div, _color(i), "#ffffff", ""])
    _w(out / "teams.csv", ["team_id", "league_id", "name", "nickname", "abbr", "conference", "division",
                           "primary_color", "secondary_color", "logo"], teams)
    players, attrs, contracts, pid = [], [], [], 0

    def add(team_id, pos, age, mean):
        nonlocal pid
        pid += 1
        nat = rng.choices(list(MIX), list(MIX.values()))[0]
        pl, at, prof = gen_player(rng, W.NAMES, nat, pos, age, SEASON, mean, NHL_SD)
        players.append([pid, pl["first_name"], pl["last_name"], pl["birth_date"], pos, pl["shoots"], pl["height_cm"],
                        pl["weight_kg"], nat, team_id, "active"])
        potential = max(1, min(20, round(prof["potential"])))
        attrs.append([pid] + [at.get(a, "") for a in ALL_ATTRS] + [potential])
        return pid, overall_of(at, pos)

    for t in range(1, len(teams) + 1):
        strength = rng.gauss(0, 0.16)                     # clubs differ a little (the real spread is small)
        for pos, n in ROSTER.items():
            for _ in range(n):
                age = max(19, min(38, int(rng.triangular(19, 38, 26))))
                p, ov = add(t, pos, age, NHL_MEAN + strength)
                hit, kind = _salary(ov, age, rng)
                contracts.append([p, t, SEASON, rng.randint(1, 4) if kind == "standard" else rng.randint(1, 3), hit, kind, 0])
    for k in range(FREE_AGENTS):                          # unsigned free agents, a notch below the clubs
        pos = rng.choices(list(ROSTER), list(ROSTER.values()))[0]
        add("", pos, rng.randint(21, 37), NHL_MEAN - 0.8)
    _w(out / "players.csv", ["player_id", "first_name", "last_name", "birth_date", "position", "shoots", "height_cm",
                             "weight_kg", "nationality", "team_id", "status"], players)
    _w(out / "attributes.csv", ["player_id"] + ALL_ATTRS + ["potential"], attrs)
    _w(out / "contracts.csv", ["player_id", "team_id", "start_year", "years", "cap_hit", "contract_type", "no_trade"], contracts)
    rules = json.loads(json.dumps(NHL.RULES))
    rules.update(name="Premier Hockey League", era_preset="nhl")
    rules["season"] = {"start": f"{SEASON}-10-07", "end": f"{SEASON + 1}-04-16", "breaks": []}
    (out / "rules.json").write_text(json.dumps(rules, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "format_version": "0.1", "name": "mock-league", "version": "1", "source": "generated",
        "redistributable": True, "contains_real_names": False, "season_start_year": SEASON, "license": "CC0-1.0",
        "description": "Fictional 32-club top league with generated players (hs.tools.make_mock_league)."}, indent=2),
        encoding="utf-8")
    return len(teams), pid


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    n, p = generate(Path(a.out), a.seed)
    print(f"wrote {n} clubs and {p} players to {a.out}")


if __name__ == "__main__":
    main()
