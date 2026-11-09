"""Build a game database from a validated data pack.

    python -m hs.ingest <pack_dir> <out.db> [--force]
"""
from __future__ import annotations

import datetime

import argparse
import sqlite3
from pathlib import Path

from .attributes import ALL_ATTRS
from .datapack import PackError, load_pack, validate
import json

from .league.rules import load_rules
from .schema import SCHEMA_VERSION, ddl


def _i(v):
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _v38_extras(conn, pack_dir, T):
    """v38: native ratings (back-filled when the pack has none), the engine scale, personalities, hidden attributes,
    staff, club profiles and rivalries, for packs that carry them (docs/DB_IMPORT.md)."""
    from .attributes import RATING_COLS
    pack_dir = Path(pack_dir)
    for key, fname in (("engine_scale", "engine_scale.json"), ("rivalries", "rivalries.json")):
        f = pack_dir / fname
        if f.exists():
            conn.execute("INSERT OR REPLACE INTO pack_info VALUES (?, ?)", (key, f.read_text(encoding="utf-8")))
    if T.get("ratings.csv"):
        conn.executemany(f"INSERT OR REPLACE INTO player_ratings (player_id, {', '.join(RATING_COLS)}) VALUES "
                         f"({', '.join('?' * (len(RATING_COLS) + 1))})",
                         [[_i(r["player_id"])] + [_i(r.get(c)) for c in RATING_COLS] for r in T["ratings.csv"]])
    from .game import ratings as RT
    RT.backfill(conn)
    if T.get("personality.csv"):
        from .game.people import TRAITS, ensure_tables as people_tables
        people_tables(conn)
        conn.executemany(f"INSERT OR REPLACE INTO personality VALUES (?, {', '.join('?' * len(TRAITS))})",
                         [[_i(r["player_id"])] + [_i(r.get(t)) or 10 for t in TRAITS] for r in T["personality.csv"]])
    if T.get("hidden.csv"):
        from .game.hidden import HIDDEN, ensure_table as hidden_table
        hidden_table(conn)
        conn.executemany(f"INSERT OR REPLACE INTO hidden VALUES (?, {', '.join('?' * len(HIDDEN))})",
                         [[_i(r["player_id"])] + [_i(r.get(h)) or 10 for h in HIDDEN] for r in T["hidden.csv"]])
    if T.get("staff.csv"):
        conn.execute("CREATE TABLE IF NOT EXISTS pack_staff (name TEXT, role TEXT, team_id INTEGER, age INTEGER, nationality TEXT)")
        conn.executemany("INSERT INTO pack_staff VALUES (?,?,?,?,?)",
                         [(r["name"], r["role"], _i(r["team_id"]), _i(r.get("age")), r.get("nationality")) for r in T["staff.csv"]])
    if T.get("suspensions.csv") or T.get("injuries.csv"):   # v53: preset suspensions and injuries
        from .game import discipline
        r = conn.execute("SELECT value FROM pack_info WHERE key='season_start_year'").fetchone()
        discipline.load_pack(conn, T, int(r[0]) if r and str(r[0]).isdigit() else datetime.date.today().year)
    if T.get("leadership.csv"):
        from .game.people import ensure_tables as people_tables
        people_tables(conn)
        conn.executemany("INSERT INTO leadership VALUES (?,?,?,?)",
                         [(_i(r["team_id"]), _i(r["player_id"]), r["role"], None) for r in T["leadership.csv"]])
    if T.get("club_profiles.csv"):
        conn.execute("CREATE TABLE IF NOT EXISTS club_profile (team_id INTEGER PRIMARY KEY, capacity INTEGER, market INTEGER, "
                     "arena TEXT, reputation INTEGER, founded INTEGER, city TEXT)")
        conn.executemany("INSERT OR REPLACE INTO club_profile VALUES (?,?,?,?,?,?,?)",
                         [(_i(r["team_id"]), _i(r.get("capacity")), _i(r.get("market")), r.get("arena"), _i(r.get("reputation")),
                           _i(r.get("founded")), r.get("city")) for r in T["club_profiles.csv"]])


def build_db(pack_dir, db_path, overwrite=False) -> dict:
    pack = load_pack(pack_dir)
    issues = validate(pack)
    if any(i.level == "error" for i in issues):
        raise PackError(issues)
    db_path = Path(db_path)
    if db_path.exists():
        if not overwrite:
            raise FileExistsError(f"{db_path} exists (use --force to replace)")
        db_path.unlink()

    m, T = pack.manifest, pack.tables
    y = m["season_start_year"]
    conn = sqlite3.connect(db_path)
    conn.executescript(ddl())

    conn.executemany("INSERT INTO pack_info VALUES (?, ?)",
                     [("schema_version", str(SCHEMA_VERSION))] + [(k, str(v)) for k, v in m.items()])
    conn.executemany("INSERT INTO leagues VALUES (?,?,?,?,?,?)",
                     [(_i(r["league_id"]), r["name"], r["abbr"], r.get("country"), _i(r.get("level")),
                       _i(r.get("games_per_team"))) for r in T["leagues.csv"]])
    label = f"{y}-{(y + 1) % 100:02d}"
    rules = load_rules(pack_dir)
    sdate = (rules or {}).get("season", {}).get("start") or f"{y}-09-01"
    edate = (rules or {}).get("season", {}).get("end")
    conn.executemany("INSERT INTO seasons (league_id, start_year, label, start_date, end_date) VALUES (?,?,?,?,?)",
                     [(_i(r["league_id"]), y, label, sdate, edate) for r in T["leagues.csv"]])
    if rules:
        conn.execute("INSERT INTO pack_info VALUES ('rules', ?)", (json.dumps(rules),))
    conn.executemany("INSERT INTO teams VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     [(_i(r["team_id"]), _i(r["league_id"]), r["name"], r.get("nickname"), r["abbr"],
                       r.get("conference"), r.get("division"), r.get("primary_color"),
                       r.get("secondary_color"), r.get("logo"), _i(r.get("parent_team_id"))) for r in T["teams.csv"]])
    conn.executemany(
        "INSERT INTO players (player_id, first_name, last_name, birth_date, position, shoots, height_cm, "
        "weight_kg, nationality, team_id, status, headshot_path, club_id, jersey_number) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(_i(r["player_id"]), r["first_name"], r["last_name"], r["birth_date"], r["position"], r.get("shoots"),
          _i(r.get("height_cm")), _i(r.get("weight_kg")), r.get("nationality"), _i(r.get("team_id")),
          (r.get("status") or "active").lower(), r.get("headshot"),
          _i(r.get("club_id")) if r.get("club_id") else
          (_i(r.get("team_id")) if (r.get("status") or "active").lower() in ("active", "injured") else None),
          _i(r.get("jersey_number")) if r.get("jersey_number") and 1 <= (_i(r.get("jersey_number")) or 0) <= 98 else None)
         for r in T["players.csv"]])

    cols = ["player_id"] + ALL_ATTRS + ["potential"]
    conn.executemany(f"INSERT INTO player_attributes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [[_i(r.get(c)) for c in cols] for r in T["attributes.csv"]])

    conn.executemany("INSERT INTO draft_rights (player_id, team_id, draft_year, overall_pick, expires_year) "
                     "VALUES (?,?,?,?,?)", [(_i(r["player_id"]), _i(r["team_id"]), _i(r.get("draft_year")),
                                             _i(r.get("overall_pick")), _i(r.get("expires_year")))
                                            for r in T.get("draft_rights.csv", [])])
    conn.executemany("INSERT INTO player_dev VALUES (?,?,?,?,?,?)",
                     [(_i(r["player_id"]), float(r["potential"]), float(r["peak_age"]), float(r["decline_age"]),
                       float(r["growth_rate"]), float(r["decline_rate"])) for r in T.get("development.csv", [])])
    if T.get("prospects.csv"):
        from .game.scouting import ensure_tables as _prospect_table
        _prospect_table(conn)
        conn.executemany("INSERT INTO prospect_info VALUES (?,?,?,?,?,?,?)",
                         [(_i(r["player_id"]), float(r.get("hidden_bloom") or 0), float(r.get("maturity") or 1),
                           r.get("archetype"), r.get("exposure"), _i(r.get("khl_until")) if r.get("khl_until") else None,
                           _i(r.get("class_year")) if r.get("class_year") else None) for r in T["prospects.csv"]])
    for r in T.get("contracts.csv", []):
        conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type, no_trade) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (_i(r["player_id"]), _i(r["team_id"]), _i(r["start_year"]), _i(r["years"]), _i(r["cap_hit"]),
                      r.get("contract_type") or "standard", _i(r.get("no_trade")) or 0))

    _v38_extras(conn, pack_dir, T)

    pids = {_i(r["player_id"]) for r in T["players.csv"]}
    skipped = 0
    for fname, table, fields in (
            ("history/skater_seasons.csv", "skater_season_stats",
             ["gp", "g", "a", "pim", "plus_minus", "sog", "toi_sec"]),
            ("history/goalie_seasons.csv", "goalie_season_stats",
             ["gp", "gs", "toi_sec", "w", "l", "otl", "so", "ga", "sa"])):
        rows = []
        for r in T.get(fname, []):
            if _i(r["player_id"]) not in pids:
                skipped += 1
                continue
            rows.append([_i(r["player_id"]), _i(r["season"]), _i(r.get("team_id")), _i(r.get("league_id")),
                         r["split"].upper()] + [_i(r.get(f)) for f in fields])
        conn.executemany(
            f"INSERT INTO {table} (player_id, season_start_year, team_id, league_id, split, {', '.join(fields)}) "
            f"VALUES ({', '.join('?' * (5 + len(fields)))})", rows)

    conn.execute("INSERT INTO game_state VALUES (1, ?, 1)", (f"{y}-07-01",))
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("leagues", "teams", "players", "player_attributes", "contracts",
                        "skater_season_stats", "goalie_season_stats")}
    conn.close()
    counts["history_rows_skipped"] = skipped
    counts["warnings"] = sum(i.level == "warning" for i in issues)
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pack")
    ap.add_argument("db")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    try:
        counts = build_db(a.pack, a.db, overwrite=a.force)
    except PackError as e:
        for i in e.issues:
            print(f"[{i.level.upper():7}] {i.where}: {i.message}")
        raise SystemExit("Pack failed validation; nothing was imported.")
    manifest = load_pack(a.pack).manifest
    if manifest.get("redistributable") is False:
        print("NOTE: this pack is marked NOT redistributable (personal use only).")
    print(f"Built {a.db}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
