"""Load an FHM CSV export (import_export/csv) into SQLite.

Usage:  python fhm_import.py <csv_dir> [out.db]

FHM's CSVs are semicolon-delimited and Windows-1252 encoded. Every file becomes a table named after
the file; columns are sanitised (e.g. '+/-' -> plus_minus, 'FO%' -> fo_pct) with NUMERIC affinity so
numbers load as numbers. On top of the raw tables it adds a game_date column and convenience views.
The source CSVs are only ever read.
"""
import csv
import re
import sqlite3
import sys
from pathlib import Path


def col_name(raw: str, seen: set) -> str:
    n = raw.strip().lower().replace("+/-", "plus_minus").replace("%", "_pct")
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_") or "col"
    if n[0].isdigit():
        n = "c_" + n
    base, i = n, 2
    while n in seen:
        n, i = f"{base}_{i}", i + 1
    seen.add(n)
    return n


def load_csv(conn, path: Path) -> tuple[str, int]:
    table = path.stem
    with open(path, newline="", encoding="cp1252", errors="replace") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = next(reader)
        keep = [i for i, h in enumerate(header) if h and h.strip()]  # skip blank trailing columns
        seen: set = set()
        cols = [col_name(header[i], seen) for i in keep]
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" ({", ".join(f"{c} NUMERIC" for c in cols)})')
        sql = f'INSERT INTO "{table}" VALUES ({", ".join("?" * len(cols))})'
        batch, n = [], 0
        for row in reader:
            if not row:
                continue
            vals = [(row[i].strip() if i < len(row) else None) for i in keep]
            batch.append([None if v in ("", "-") else v for v in vals])
            if len(batch) >= 20000:
                conn.executemany(sql, batch); n += len(batch); batch = []
        if batch:
            conn.executemany(sql, batch); n += len(batch)
    return table, n


def tables(conn):
    return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}


def cols(conn, t):
    return [r[1] for r in conn.execute(f'pragma table_info("{t}")')]


def build_views(conn):
    have = tables(conn)
    # Season stat lines: current + retired players unified per split (rs = regular season, po = playoffs, ps = pre-season)
    for kind in ("skater", "goalie"):
        for split in ("rs", "po", "ps"):
            a, b = f"player_{kind}_career_stats_{split}", f"player_{kind}_retired_career_stats_{split}"
            if a not in have or b not in have:
                continue
            ca, cb = cols(conn, a), cols(conn, b)
            norm = lambda cs: [c.replace("_", "") for c in cs]
            if norm(ca) != norm(cb):  # retired files spell teamid/leagueid without underscores; match by position
                print(f"  ! skipped v_{kind}_seasons_{split}: column layouts differ")
                continue
            conn.execute(f"DROP VIEW IF EXISTS v_{kind}_seasons_{split}")
            conn.execute(f"CREATE VIEW v_{kind}_seasons_{split} AS "
                         f"SELECT {', '.join(ca)}, 0 AS retired FROM {a} "
                         f"UNION ALL SELECT {', '.join(cb)}, 1 FROM {b}")
    if "boxscore_summary" in have:
        conn.execute("ALTER TABLE boxscore_summary ADD COLUMN game_date TEXT")
        conn.execute("UPDATE boxscore_summary SET game_date = printf('%04d-%02d-%02d', date_year, date_month, date_day)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_bs_game ON boxscore_summary(game_id)")
    for t, c in (("boxscore_skater_summary", "game_id"), ("boxscore_goalie_summary", "game_id"),
                 ("boxscore_period_scoring_summary", "game_id"), ("boxscore_period_penalties_summary", "game_id"),
                 ("player_master", "playerid"), ("player_ratings", "playerid")):
        if t in have and c in cols(conn, t):
            conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_{c} ON {t}({c})")
    if {"boxscore_summary", "team_data"} <= have:
        conn.execute("DROP VIEW IF EXISTS v_games")
        conn.execute("""CREATE VIEW v_games AS
            SELECT g.game_id, g.game_date, g.type, th.abbr AS home, ta.abbr AS away,
                   g.score_home, g.score_away, g.shots_home, g.shots_away, g.arena, g.attendance
            FROM boxscore_summary g
            LEFT JOIN team_data th ON th.teamid = g.team_home
            LEFT JOIN team_data ta ON ta.teamid = g.team_away""")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "golfbag.db"
    if Path(out).exists():
        Path(out).unlink()
    conn = sqlite3.connect(out)
    total = 0
    for p in sorted(src.glob("*.csv")):
        if p.name == "team_lines.csv":  # trailing blank headers + wide positional layout; load raw, skip views
            pass
        t, n = load_csv(conn, p)
        total += n
        print(f"  {t:<45}{n:>9} rows")
    build_views(conn)
    conn.commit()
    print(f"\nLoaded {total:,} rows into {out}")


if __name__ == "__main__":
    main()
