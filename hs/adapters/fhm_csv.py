"""Adapter: Franchise Hockey Manager CSV export  ->  data pack (format 0.1).

    python -m hs.adapters.fhm_csv <fhm_csv_dir> <out_pack_dir>

PERSONAL USE ONLY. The pack this writes contains data owned by third parties; it is marked
redistributable=false and must not be published or committed. The adapter only *reads* the export
and translates it into this engine's own attribute model (hs.attributes).

Assumptions to confirm against the game: height is in inches and weight in pounds; season stat 'Year'
is the season's start year (2011 = 2011-12); Potential stars (0.5-5) map to 1-20 as stars * 4.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

from ..attributes import ALL_ATTRS, RATING_MAX, RATING_MIN

# our attribute  <-  FHM rating column (normalised header: lowercase, letters/digits only)
RATING_MAP = {
    "speed": "speed", "acceleration": "acceleration", "agility": "agility", "balance": "balance",
    "endurance": "stamina",
    "shot_accuracy": "shootingaccuracy", "shot_power": "shootingrange", "passing": "passing",
    "puck_control": "puckhandling", "offensive_awareness": "offensiveread", "net_presence": "screening",
    "faceoffs": "faceoffs",
    "checking": "checking", "stick_checking": "stickchecking", "shot_blocking": "shotblocking",
    "positioning": "positioning", "defensive_awareness": "defensiveread",
    "strength": "strength", "hitting": "hitting", "toughness": "fighting",
    "aggression": "aggression", "bravery": "bravery", "determination": "determination",
    "teamwork": "teamplayer", "leadership": "leadership", "composure": "temperament",
    "professionalism": "professionalism", "mental_toughness": "mentaltoughness",
    "goalie_positioning": "gpositioning", "reflexes": "reflexes", "glove": "glove", "blocker": "blocker",
    "rebound_control": "rebound", "recovery": "recovery", "poke_check": "gpokecheck",
    "low_shot_save": "lowshots", "goalie_puck_handling": "gpuckhandling", "goalie_passing": "gpassing",
    "goalie_skating": "gskating", "goalie_stamina": "goaliestamina",
}
assert set(RATING_MAP) == set(ALL_ATTRS), "adapter must map every engine attribute"

POSITION_COLUMNS = [("g", "G"), ("c", "C"), ("lw", "LW"), ("rw", "RW"), ("ld", "D"), ("rd", "D")]  # tie-break order
LEAGUE_LEVELS = {"NHL": 1, "AHL": 2}


def norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", h.lower().replace("+/-", "plusminus").replace("%", "pct"))


def read_fhm(path: Path):
    with open(path, newline="", encoding="cp1252", errors="replace") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = [norm(h) for h in next(reader)]
        for row in reader:
            if row:
                yield {h: (v.strip() if v.strip() not in ("", "-") else None) for h, v in zip(header, row)}


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def clamp(v):
    return None if v is None else max(RATING_MIN, min(RATING_MAX, v))


def stars_to_potential(s):
    m = re.match(r"[\d.]+", s or "")
    return clamp(round(float(m.group()) * 4)) if m else None


def iso_date(s):
    try:
        y, mo, d = (int(x) for x in (s or "").split("-"))
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def write_csv(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def convert(src: Path, out: Path, season_start_year=None) -> dict:
    src, out = Path(src), Path(out)
    need = ["league_data", "team_data", "player_master", "player_ratings"]
    missing = [n for n in need if not (src / f"{n}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"{src} is missing {missing}; point at import_export/csv")
    stats = {}

    leagues = list(read_fhm(src / "league_data.csv"))
    stats["leagues"] = write_csv(out / "leagues.csv", ["league_id", "name", "abbr", "level"],
                                 [[r["leagueid"], r["name"], r["abbr"], LEAGUE_LEVELS.get(r["abbr"], 3)]
                                  for r in leagues])

    conf = {(r["leagueid"], r["conferenceid"]): r["name"] for r in read_fhm(src / "conferences.csv")}
    div = {(r["leagueid"], r["conferenceid"], r["divisionid"]): r["name"] for r in read_fhm(src / "divisions.csv")}
    teams = []
    for r in read_fhm(src / "team_data.csv"):
        lg, cf, dv = r["leagueid"], r.get("conferenceid"), r.get("divisionid")
        teams.append([r["teamid"], lg, r["name"], r["nickname"], r["abbr"], conf.get((lg, cf), ""),
                      div.get((lg, cf, dv), ""), r.get("primarycolor"), r.get("secondarycolor"), ""])
    team_ids = {t[0] for t in teams}  # FHM uses team id -1 for 'no team'; anything else unknown is blanked too
    stats["teams"] = write_csv(out / "teams.csv",
                               ["team_id", "league_id", "name", "nickname", "abbr", "conference", "division",
                                "primary_color", "secondary_color", "logo"], teams)

    ratings = {r["playerid"]: r for r in read_fhm(src / "player_ratings.csv")}
    players, attrs, clipped = [], [], 0
    for r in read_fhm(src / "player_master.csv"):
        pid, active = r["playerid"], r["playerid"] in ratings and r.get("retired") != "1"
        pos = "C"
        if active:
            rt = ratings[pid]
            prof = {k: to_int(rt.get(k)) or 0 for k, _ in POSITION_COLUMNS}
            best = max(POSITION_COLUMNS, key=lambda kp: prof[kp[0]])
            pos = best[1]
            vals = []
            for a in ALL_ATTRS:
                raw = to_int(rt.get(RATING_MAP[a]))
                clipped += raw is not None and not RATING_MIN <= raw <= RATING_MAX
                vals.append(clamp(raw))
            attrs.append([pid] + vals + [stars_to_potential(rt.get("potential"))])
        h, w = to_int(r.get("height")), to_int(r.get("weight"))
        players.append([pid, r["firstname"], r["lastname"], iso_date(r.get("dateofbirth")), pos,
                        {"Left": "L", "Right": "R"}.get(r.get("hand"), ""),
                        round(h * 2.54) if h else "", round(w * 0.4536) if w else "", r.get("nationalityone") or "",
                        r["teamid"] if active and r["teamid"] in team_ids else "",
                        "active" if active else "retired"])
    stats["players"] = write_csv(out / "players.csv",
                                 ["player_id", "first_name", "last_name", "birth_date", "position", "shoots",
                                  "height_cm", "weight_kg", "nationality", "team_id", "status"], players)
    stats["attribute_rows"] = write_csv(out / "attributes.csv", ["player_id"] + ALL_ATTRS + ["potential"], attrs)
    stats["ratings_clamped_to_1_20"] = clipped

    if (src / "player_contract.csv").exists():
        rows = []
        for r in read_fhm(src / "player_contract.csv"):
            years = [int(k[5:]) for k, v in r.items() if k.startswith("major") and (to_int(v) or 0) > 0]
            if not years or r.get("team") not in team_ids or r["playerid"] not in ratings:
                continue
            rows.append([r["playerid"], r["team"], min(years), len(years), to_int(r.get("averagesalary")) or 0,
                         "entry_level" if r.get("elc") == "Yes" else "standard",
                         1 if "Yes" in (r.get("ntc"), r.get("nmc")) else 0])
        stats["contracts"] = write_csv(out / "contracts.csv",
                                       ["player_id", "team_id", "start_year", "years", "cap_hit",
                                        "contract_type", "no_trade"], rows)

    for kind, fields in (("skater", [("gp", "gp"), ("g", "g"), ("a", "a"), ("pim", "pim"),
                                     ("plus_minus", "plusminus"), ("sog", "sog"), ("toi_sec", "toi")]),
                         ("goalie", [("gp", "gp"), ("gs", "gs"), ("toi_sec", "min"), ("w", "w"), ("l", "l"),
                                     ("otl", "tol"), ("so", "so"), ("ga", "ga"), ("sa", "sa")])):
        rows = []
        for split in ("rs", "po", "ps"):
            for stem in (f"player_{kind}_career_stats_{split}", f"player_{kind}_retired_career_stats_{split}"):
                if not (src / f"{stem}.csv").exists():
                    continue
                for r in read_fhm(src / f"{stem}.csv"):
                    rows.append([r["playerid"], r["year"], r.get("teamid"), r.get("leagueid"), split.upper()]
                                + [r.get(f) for _, f in fields])
        stats[f"{kind}_season_rows"] = write_csv(
            out / "history" / f"{kind}_seasons.csv",
            ["player_id", "season", "team_id", "league_id", "split"] + [n for n, _ in fields], rows)

    if season_start_year is None:  # season of the most recent game data in the export
        yrs = [to_int(r["dateyear"]) for r in read_fhm(src / "boxscore_summary.csv")] \
            if (src / "boxscore_summary.csv").exists() else []
        season_start_year = min(yrs) if yrs else 2011
    (out / "manifest.json").write_text(json.dumps({
        "format_version": "0.1", "name": "fhm-import", "version": "1",
        "source": "fhm_csv", "redistributable": False, "contains_real_names": True,
        "season_start_year": season_start_year,
        "description": "Converted from a personal Franchise Hockey Manager CSV export. PERSONAL USE ONLY: do not publish."},
        indent=2), encoding="utf-8")
    (out / "README.txt").write_text("PERSONAL USE ONLY. Derived from a third-party game's export. "
                                    "Do not publish, share or commit this folder.\n", encoding="utf-8")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_dir")
    ap.add_argument("out_pack")
    ap.add_argument("--season-start-year", type=int)
    a = ap.parse_args(argv)
    for k, v in convert(Path(a.csv_dir), Path(a.out_pack), a.season_start_year).items():
        print(f"  {k:<26}{v:>9}")


if __name__ == "__main__":
    main()
