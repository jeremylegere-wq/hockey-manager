"""Build a full hockey world pack around an NHL pack: AHL and ECHL affiliates, CHL, NCAA and European clubs.

    python -m hs.tools.build_world <nhl_pack> <out_pack> [--seed 1] [--nhl-roster 23]

The NHL pack supplies the 32 clubs and their (real) players. Everything below the NHL is generated: players in the
farm, junior, college and European clubs are fictional (invented names, ratings from the league's level), as are
the existing draft rights of NHL clubs. Real-world club names for the other leagues come from
hs.leaguedata.world_2025_26. The output inherits the input's redistributable flag (False for MoneyPuck packs).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
from pathlib import Path

from ..attributes import ALL_ATTRS
from ..leaguedata import world_2025_26 as W
from ..worldgen import (FILLER_OFFSET, age_mean_offset, class_leagues, filler_profile, gen_player, make_draft_class, make_profile,
                        overall_of, pick_nationality, pick_position, roster_age)

FIRST_TEAM_ID = 1000
PLAYER_FIELDS = ["player_id", "first_name", "last_name", "birth_date", "position", "shoots", "height_cm",
                 "weight_kg", "nationality", "team_id", "status", "club_id"]
DEV_FIELDS = ["player_id", "potential", "peak_age", "decline_age", "growth_rate", "decline_rate"]
PROSPECT_FIELDS = ["player_id", "hidden_bloom", "maturity", "archetype", "exposure", "khl_until", "class_year"]
CLASS_AGES = [(17, 0), (18, 0), (19, 8), (20, 20), (21, 30)]    # (age, best players already real NHLers)
NEED_ACTIVE = {"G": 2, "D": 7, "F": 13}


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def abbr_of(name):
    words = [w for w in re.split(r"[\s\-/.']+", name) if w and w[0].isalpha()]
    if len(words) == 1:
        return words[0][:4].upper()
    return "".join(w[0] for w in words[:3]).upper()


def group(pos):
    return "G" if pos == "G" else "D" if pos == "D" else "F"


def build(nhl_pack, out, seed=1, nhl_roster=23, only=None, clubs_per_league=None, fictional=False):
    """only: league abbreviations to include (default all); clubs_per_league: cap per league (small test worlds).
    If the NHL pack's abbreviations are not the real NHL ones (a custom league), farm clubs are assigned to its
    clubs in turn. fictional=True replaces every real club name below the top league with an invented one (and the
    affiliations with 'in turn'), so the world contains no real names at all."""
    nhl_pack, out = Path(nhl_pack), Path(out)
    rng = random.Random(f"world-{seed}")
    man = json.loads((nhl_pack / "manifest.json").read_text())
    rules = json.loads((nhl_pack / "rules.json").read_text()) if (nhl_pack / "rules.json").exists() else {}
    year = int((rules.get("season") or {}).get("start", f"{man['season_start_year']}")[:4])
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("history",):
        if (nhl_pack / sub).exists():
            shutil.copytree(nhl_pack / sub, out / sub, dirs_exist_ok=True)
    if (nhl_pack / "contracts.csv").exists():
        shutil.copy(nhl_pack / "contracts.csv", out / "contracts.csv")

    leagues = read(nhl_pack / "leagues.csv")
    top_league = leagues[0]["league_id"]
    teams = read(nhl_pack / "teams.csv")
    nhl_by_abbr = {t["abbr"]: t["team_id"] for t in teams}
    world = {}
    for k, (abbr, (name, kind, level, country, games, mean, roster, ages)) in enumerate(W.LEAGUES.items()):
        if only and abbr not in only:
            continue
        lid = str(100 + k)
        leagues.append(dict(league_id=lid, name=name, abbr=abbr, country=country, level=level, games_per_team=games))
        world[lid] = dict(abbr=abbr, kind=kind, level=level, games=games, mean=mean, roster=roster,
                          age_min=ages[0], age_max=ages[1])
    tid = FIRST_TEAM_ID
    clubs = []                                            # (team_id, league_id, parent)
    lid_of = {w["abbr"]: lid for lid, w in world.items()}
    base_ids = [t["team_id"] for t in teams]
    feeders, used_places = W.FEEDERS, set()
    ahl_echl = (("AHL", W.AHL), ("ECHL", W.ECHL))
    if fictional:
        from ..leaguedata import fictional as FIC
        ahl_echl = tuple((a, {n: None for n in FIC.club_names(a, len(t), rng, used_places)}) for a, t in ahl_echl)
        feeders = {a: FIC.club_names(a, len(names), rng, used_places) for a, names in W.FEEDERS.items()}
    for abbr, table in ahl_echl:
        if abbr not in lid_of:
            continue
        unused = [t for t in base_ids if t not in {nhl_by_abbr.get(p) for p in table.values()}]
        for name, parent in list(table.items())[:clubs_per_league or None]:
            par = nhl_by_abbr.get(parent) or (unused.pop(0) if unused else "")
            teams.append(dict(team_id=tid, league_id=lid_of[abbr], name=name, nickname="", abbr=abbr_of(name),
                              parent_team_id=par))
            clubs.append((tid, lid_of[abbr], par or None))
            tid += 1
    for abbr, names in feeders.items():
        if abbr not in lid_of:
            continue
        for name in names[:clubs_per_league or None]:
            teams.append(dict(team_id=tid, league_id=lid_of[abbr], name=name, nickname="", abbr=abbr_of(name)))
            clubs.append((tid, lid_of[abbr], None))
            tid += 1
    affiliate = {parent: t for t, lid, parent in clubs if parent and world[lid]["abbr"] == "AHL"}

    # NHL players: best ~23 per club dress for the NHL club, the rest play for its AHL affiliate
    players = read(nhl_pack / "players.csv")
    attrs = {r["player_id"]: r for r in read(nhl_pack / "attributes.csv")}
    by_team = {}
    for p in players:
        p.setdefault("club_id", "")
        if p.get("team_id") and p.get("status", "active") == "active":
            by_team.setdefault(p["team_id"], []).append(p)
    usage = {}                                           # last season's NHL games: who actually held the spots
    for f in ("skater_seasons.csv", "goalie_seasons.csv"):
        path = nhl_pack / "history" / f
        if path.exists():
            rows = [r for r in read(path) if r.get("split") == "RS" and r.get("league_id") == top_league]
            last = max((int(r["season"]) for r in rows), default=None)
            for r in rows:
                if int(r["season"]) == last:
                    usage[r["player_id"]] = usage.get(r["player_id"], 0) + int(float(r.get("gp") or 0))
    for team_id, members in by_team.items():
        ranked = sorted(members, key=lambda p: (-min(usage.get(p["player_id"], 0), 40),
                                                -overall_of(attrs.get(p["player_id"], {}), p["position"])))
        keep, counts = [], {"G": 0, "D": 0, "F": 0}
        for p in ranked:
            g = group(p["position"])
            if counts[g] < NEED_ACTIVE[g]:
                keep.append(p)
                counts[g] += 1
        for p in ranked:
            if len(keep) >= nhl_roster:
                break
            if p not in keep:
                keep.append(p)
        for p in members:
            if p in keep:
                p["club_id"] = team_id
            else:
                p["status"], p["club_id"] = "prospect", affiliate.get(team_id, "")

    # generated players fill every other club to its roster size
    next_pid = max(int(p["player_id"]) for p in players) + 1
    dev_rows, attr_rows = [], []
    on_club = {}
    for p in players:
        if p.get("club_id"):
            on_club[str(p["club_id"])] = on_club.get(str(p["club_id"]), 0) + 1
    youth = []                                           # candidates for existing draft rights
    prospect_rows = []
    # draft classes: 17-21-year-olds from the calibrated cohort model; the best of the older cohorts are already
    # real NHLers (in the NHL pack), so they are left out here
    by_abbr = {}
    for team_id, lid, parent in clubs:
        by_abbr.setdefault(world[lid]["abbr"], []).append((team_id, lid))
    for age, drop in CLASS_AGES:
        for pl, at, prof, info in make_draft_class(rng, W.NAMES, year, age, drop):
            spot = None
            for abbr in class_leagues(pl["nationality"], age, rng):
                options = [(t, l) for t, l in by_abbr.get(abbr, []) if world[l]["age_min"] <= age <= world[l]["age_max"]]
                if options:
                    spot = min(options, key=lambda x: (on_club.get(str(x[0]), 0), rng.random()))
                    break
            if spot is None:
                continue
            team_id, lid = spot
            on_club[str(team_id)] = on_club.get(str(team_id), 0) + 1
            pl.update(player_id=next_pid, team_id="", status="active", club_id=team_id)
            players.append(pl)
            attr_rows.append(dict(at, player_id=next_pid, potential=max(1, min(20, round(prof["potential"])))))
            dev_rows.append(dict(prof, player_id=next_pid))
            khl_until = year + info["khl_years"] - 1 if info["khl_years"] else ""
            prospect_rows.append(dict(player_id=next_pid, hidden_bloom=info["hidden_bloom"], maturity=info["maturity"],
                                      archetype=info["archetype"], exposure=info["exposure"], khl_until=khl_until,
                                      class_year=info["class_year"]))
            if 18 <= age <= 21:
                youth.append((prof["potential"], next_pid, age))
            next_pid += 1
    for team_id, lid, parent in clubs:
        w = world[lid]
        mix = W.NATIONALITY_MIX[w["abbr"]]
        need = w["roster"] - on_club.get(str(team_id), 0)
        goalies = 0
        for k in range(max(0, need)):
            pos = "G" if goalies < 3 and k % 8 == 0 else pick_position(rng)
            goalies += pos == "G"
            age = roster_age(rng, w["kind"], w["age_min"], w["age_max"])
            nat = pick_nationality(rng, mix)
            is_youth = age <= 21 and w["kind"] in ("junior", "college", "europe")
            pl, at, prof = gen_player(rng, W.NAMES, nat, pos, age, year, w["mean"] + age_mean_offset(age, w["kind"])
                                      + (FILLER_OFFSET if is_youth else 0.0))
            if is_youth:
                prof = filler_profile(rng, age, overall_of(at, pos), pos)     # talent comes from the classes
            pl.update(player_id=next_pid, team_id="", status="active", club_id=team_id)
            players.append(pl)
            attr_rows.append(dict(at, player_id=next_pid, potential=max(1, min(20, round(prof["potential"])))))
            dev_rows.append(dict(prof, player_id=next_pid))
            next_pid += 1

    # existing draft rights: NHL clubs hold the rights to the best young prospects (snake order, with noise)
    nhl_ids = [t["team_id"] for t in read(nhl_pack / "teams.csv")]
    ranked = sorted(youth, key=lambda x: -(x[0] + rng.gauss(0, 0.4)))[: len(nhl_ids) * 8]
    rights = []
    for i, (pot, pid, age) in enumerate(ranked):
        rnd, k = divmod(i, len(nhl_ids))
        team = nhl_ids[k if rnd % 2 == 0 else len(nhl_ids) - 1 - k]
        draft_year = year - max(0, age - 18)
        rights.append(dict(player_id=pid, team_id=team, draft_year=draft_year, overall_pick=i + 1,
                           expires_year=draft_year + (4 if age - (year - draft_year) <= 18 else 3)))

    stats = {}
    stats["leagues"] = write(out / "leagues.csv", ["league_id", "name", "abbr", "country", "level", "games_per_team"], leagues)
    stats["teams"] = write(out / "teams.csv", ["team_id", "league_id", "name", "nickname", "abbr", "conference",
                                               "division", "primary_color", "secondary_color", "logo",
                                               "parent_team_id"], teams)
    stats["players"] = write(out / "players.csv", PLAYER_FIELDS, players)
    base_attr = read(nhl_pack / "attributes.csv")
    stats["attribute_rows"] = write(out / "attributes.csv", ["player_id"] + ALL_ATTRS + ["potential"],
                                    base_attr + attr_rows)
    stats["development_rows"] = write(out / "development.csv", DEV_FIELDS, dev_rows)
    stats["prospects"] = write(out / "prospects.csv", PROSPECT_FIELDS, prospect_rows)
    stats["draft_rights"] = write(out / "draft_rights.csv", ["player_id", "team_id", "draft_year", "overall_pick",
                                                             "expires_year"], rights)
    rules["world"] = {"leagues": world, "top_league_id": top_league}
    (out / "rules.json").write_text(json.dumps(rules, indent=1), encoding="utf-8")
    man.update(name=f"{man['name']}-world", season_start_year=year,
               description=man.get("description", "") + " World layer: players outside the NHL are generated "
                                                         "(fictional); club names are " + ("invented." if fictional else "real."))
    (out / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    if not man.get("redistributable", False):
        (out / "README.txt").write_text("PERSONAL USE ONLY: built on a non-redistributable NHL pack.\n",
                                        encoding="utf-8")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nhl_pack")
    ap.add_argument("out_pack")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--nhl-roster", type=int, default=23)
    ap.add_argument("--fictional", action="store_true", help="invent every club name below the top league")
    a = ap.parse_args(argv)
    for k, v in build(a.nhl_pack, a.out_pack, a.seed, a.nhl_roster, fictional=a.fictional).items():
        print(f"  {k:<20}{v:>8}")


if __name__ == "__main__":
    main()
