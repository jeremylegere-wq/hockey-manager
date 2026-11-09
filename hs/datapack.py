"""Data pack loader and validator (format 0.1). Standard library only.

A data pack is a folder of plain CSV files plus manifest.json; see docs/DATAPACK_SPEC.md.
    python -m hs.datapack <pack_dir>      # validate and print issues
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, namedtuple
from datetime import date
from pathlib import Path

from .attributes import ALL_ATTRS, GOALIE_ATTRS, POSITIONS, RATING_MAX, RATING_MIN, SKATER_ATTRS

FORMAT_VERSION = "0.1"
Issue = namedtuple("Issue", "level where message")

REQUIRED_FILES = {
    "leagues.csv": ["league_id", "name", "abbr"],
    "teams.csv": ["team_id", "league_id", "name", "nickname", "abbr"],
    "players.csv": ["player_id", "first_name", "last_name", "birth_date", "position"],
    "attributes.csv": ["player_id"],
}
OPTIONAL_FILES = {
    "contracts.csv": ["player_id", "team_id", "start_year", "years", "cap_hit"],
    "history/skater_seasons.csv": ["player_id", "season", "team_id", "league_id", "split"],
    "history/goalie_seasons.csv": ["player_id", "season", "team_id", "league_id", "split"],
    "draft_rights.csv": ["player_id", "team_id"],
    "development.csv": ["player_id", "potential", "peak_age", "decline_age", "growth_rate", "decline_rate"],
    "prospects.csv": ["player_id", "exposure"],
    # v38: the native ratings layer and what a full database import carries (docs/DB_IMPORT.md)
    "ratings.csv": ["player_id"],
    "personality.csv": ["player_id"],
    "hidden.csv": ["player_id"],
    "staff.csv": ["name", "role", "team_id"],
    "club_profiles.csv": ["team_id"],
    "leadership.csv": ["team_id", "player_id", "role"],
    "suspensions.csv": ["player_id", "games"],          # v53: preset suspensions and injuries
    "injuries.csv": ["player_id"],
}
MANIFEST_KEYS = ["format_version", "name", "version", "source", "redistributable",
                 "contains_real_names", "season_start_year"]
SPLITS = {"RS", "PO", "PS"}  # regular season, playoffs, pre-season
MAX_PER_WHERE = 8


class Pack:
    def __init__(self, path: Path, manifest: dict, columns: dict, tables: dict):
        self.path, self.manifest, self.columns, self.tables = path, manifest, columns, tables


class PackError(Exception):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("; ".join(f"{i.where}: {i.message}" for i in issues if i.level == "error")[:500])


def read_csv(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames or [])
        rows = [{k: (v.strip() if v and v.strip() != "" else None) for k, v in r.items()} for r in reader]
    return cols, rows


def load_pack(path) -> Pack:
    path = Path(path)
    mpath = path / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    columns, tables = {}, {}
    for fname in list(REQUIRED_FILES) + list(OPTIONAL_FILES):
        f = path / fname
        if f.exists():
            columns[fname], tables[fname] = read_csv(f)
    pack = Pack(path, manifest, columns, tables)
    rpath = path / "rules.json"
    pack.rules = json.loads(rpath.read_text(encoding="utf-8")) if rpath.exists() else None
    return pack


class _Collector:
    def __init__(self):
        self.issues, self._count = [], Counter()

    def add(self, level, where, msg):
        self._count[(level, where)] += 1
        if self._count[(level, where)] <= MAX_PER_WHERE:
            self.issues.append(Issue(level, where, msg))
        elif self._count[(level, where)] == MAX_PER_WHERE + 1:
            self.issues.append(Issue(level, where, "... further similar issues suppressed"))

    def error(self, where, msg):
        self.add("error", where, msg)

    def warn(self, where, msg):
        self.add("warning", where, msg)


def _int(v):
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _unique_ids(c, fname, rows, col):
    seen = set()
    for i, r in enumerate(rows, start=2):
        v = r.get(col)
        if v is None:
            c.error(fname, f"row {i}: blank {col}")
        elif v in seen:
            c.error(fname, f"row {i}: duplicate {col} {v}")
        seen.add(v)
    return seen


def validate(pack: Pack):
    from .league.rules import check_rules, merged
    c = _Collector()
    m = pack.manifest
    if not m:
        c.error("manifest.json", "missing or empty")
    for k in MANIFEST_KEYS:
        if m and k not in m:
            c.error("manifest.json", f"missing key '{k}'")
    if m and str(m.get("format_version")) != FORMAT_VERSION:
        c.error("manifest.json", f"format_version must be '{FORMAT_VERSION}'")
    for k in ("redistributable", "contains_real_names"):
        if k in m and not isinstance(m[k], bool):
            c.error("manifest.json", f"'{k}' must be true or false")
    if "season_start_year" in m and not isinstance(m["season_start_year"], int):
        c.error("manifest.json", "'season_start_year' must be an integer")

    for fname, req in {**REQUIRED_FILES, **OPTIONAL_FILES}.items():
        if fname not in pack.tables:
            if fname in REQUIRED_FILES:
                c.error(fname, "required file is missing")
            continue
        for col in req:
            if col not in pack.columns[fname]:
                c.error(fname, f"missing required column '{col}'")

    T = pack.tables
    leagues = _unique_ids(c, "leagues.csv", T.get("leagues.csv", []), "league_id")
    teams = _unique_ids(c, "teams.csv", T.get("teams.csv", []), "team_id")
    players = _unique_ids(c, "players.csv", T.get("players.csv", []), "player_id")

    for i, r in enumerate(T.get("teams.csv", []), start=2):
        if r.get("league_id") not in leagues:
            c.error("teams.csv", f"row {i}: unknown league_id {r.get('league_id')}")
        if r.get("parent_team_id") and r["parent_team_id"] not in teams:
            c.error("teams.csv", f"row {i}: unknown parent_team_id {r['parent_team_id']}")

    pos_of, status_of = {}, {}
    for i, r in enumerate(T.get("players.csv", []), start=2):
        pid = r.get("player_id")
        pos_of[pid] = r.get("position")
        status_of[pid] = (r.get("status") or "active").lower()
        if r.get("position") not in POSITIONS:
            c.error("players.csv", f"row {i}: position '{r.get('position')}' not in {POSITIONS}")
        try:
            date.fromisoformat(r.get("birth_date") or "")
        except ValueError:
            c.error("players.csv", f"row {i}: birth_date '{r.get('birth_date')}' is not YYYY-MM-DD")
        if r.get("team_id") is not None and r["team_id"] not in teams:
            c.error("players.csv", f"row {i}: unknown team_id {r['team_id']}")
        if r.get("club_id") and r["club_id"] not in teams:
            c.error("players.csv", f"row {i}: unknown club_id {r['club_id']}")
        for col in ("height_cm", "weight_kg"):
            if r.get(col) is not None and _int(r[col]) is None:
                c.error("players.csv", f"row {i}: {col} must be an integer")

    known = set(ALL_ATTRS) | {"player_id", "potential"}
    for col in pack.columns.get("attributes.csv", []):
        if col not in known:
            c.warn("attributes.csv", f"unknown column '{col}' will be ignored")
    have_attrs = set()
    for i, r in enumerate(T.get("attributes.csv", []), start=2):
        pid = r.get("player_id")
        if pid not in players:
            c.error("attributes.csv", f"row {i}: unknown player_id {pid}")
            continue
        if pid in have_attrs:
            c.error("attributes.csv", f"row {i}: duplicate player_id {pid}")
        have_attrs.add(pid)
        needed = GOALIE_ATTRS if pos_of.get(pid) == "G" else SKATER_ATTRS
        for a in needed:
            v = _int(r.get(a))
            if v is None:
                c.error("attributes.csv", f"player {pid}: {a} missing or not an integer")
            elif not RATING_MIN <= v <= RATING_MAX:
                c.error("attributes.csv", f"player {pid}: {a}={v} outside {RATING_MIN}-{RATING_MAX}")
        if r.get("potential") is not None:
            v = _int(r["potential"])
            if v is None or not RATING_MIN <= v <= RATING_MAX:
                c.error("attributes.csv", f"player {pid}: potential must be {RATING_MIN}-{RATING_MAX}")
    for pid in players:
        if status_of.get(pid) != "retired" and pid not in have_attrs:
            c.error("attributes.csv", f"non-retired player {pid} has no attributes row")

    for i, r in enumerate(T.get("contracts.csv", []), start=2):
        if r.get("player_id") not in players:
            c.error("contracts.csv", f"row {i}: unknown player_id {r.get('player_id')}")
        if r.get("team_id") not in teams:
            c.error("contracts.csv", f"row {i}: unknown team_id {r.get('team_id')}")
        if (_int(r.get("years")) or 0) < 1:
            c.error("contracts.csv", f"row {i}: years must be >= 1")
        if (_int(r.get("cap_hit")) is None) or _int(r["cap_hit"]) < 0:
            c.error("contracts.csv", f"row {i}: cap_hit must be a non-negative integer")

    for fname in ("history/skater_seasons.csv", "history/goalie_seasons.csv"):
        for i, r in enumerate(T.get(fname, []), start=2):
            if r.get("player_id") not in players:
                c.warn(fname, f"row {i}: player_id {r.get('player_id')} not in players.csv (row will be skipped)")
            if (r.get("split") or "").upper() not in SPLITS:
                c.error(fname, f"row {i}: split must be one of {sorted(SPLITS)}")
            if _int(r.get("season")) is None:
                c.error(fname, f"row {i}: season must be an integer start year")

    if m.get("contains_real_names") is True and m.get("redistributable") is True:
        c.warn("manifest.json", "pack has real names and is marked redistributable: confirm you hold the rights")
    if getattr(pack, "rules", None) is not None:
        lv = {r.get("league_id"): _int(r.get("level")) or 1 for r in T.get("leagues.csv", [])}
        top = min(lv.values()) if lv else 1
        for problem in check_rules(merged(pack.rules), [dict(t, team_id=_int(t.get("team_id"))) for t in T.get("teams.csv", [])
                                                        if lv.get(t.get("league_id"), 1) == top]):
            c.error("rules.json", problem)
        start = (pack.rules.get("season") or {}).get("start")
        y = pack.manifest.get("season_start_year")
        if start and y and int(start[:4]) != int(y):
            c.warn("rules.json", f"season.start {start} is not in manifest season_start_year {y}; "
                                 "the game uses the rules dates, so set season_start_year to {start[:4]}")
    return c.issues


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    pack = load_pack(argv[0])
    issues = validate(pack)
    for i in issues:
        print(f"[{i.level.upper():7}] {i.where}: {i.message}")
    errs = sum(i.level == "error" for i in issues)
    n = {k: len(v) for k, v in pack.tables.items()}
    print(f"\n{argv[0]}: {errs} error(s), {len(issues) - errs} warning(s); rows: {n}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
