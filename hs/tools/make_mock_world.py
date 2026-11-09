"""Build the mock world: a fictional 32-club league with farm, junior, college and European leagues around it.

    python -m hs.tools.make_mock_world [--out save/world.db] [--seed 1] [--force]

Three steps in one (make_mock_league -> build_world --fictional -> ingest), about a second. Everything in it is invented:
players, clubs, towns. The game builds it on first launch when no world is present (hs/bootstrap.py), so a fresh
download plays at once. Use another --seed for another league.
"""
from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

from .. import ingest
from . import build_world, make_mock_league

WORLD_NAME = "Premier Hockey League (fictional)"


def build(out, seed=1, force=False, clubs=None, name=None):
    out = Path(out)
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        league, world = Path(tmp) / "league", Path(tmp) / "world"
        make_mock_league.generate(league, seed, clubs)
        build_world.build(league, world, seed, fictional=True)
        ingest.build_db(world, str(out), overwrite=True)
    conn = sqlite3.connect(out)
    conn.execute("INSERT OR REPLACE INTO pack_info VALUES ('world_name', ?)", (f"{name or WORLD_NAME}, seed {seed}",))
    conn.commit()
    conn.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="save/world.db")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clubs", help="a CSV of your own 32 clubs (city, nickname, abbr, conference, division); "
                                    "see docs/MAKE_YOUR_OWN_TEAMS.md")
    ap.add_argument("--name", help="the world's name on the New Game screen")
    a = ap.parse_args(argv)
    from ..leaguedata import fictional as FIC
    try:
        clubs = FIC.load_clubs(a.clubs) if a.clubs else None
    except (ValueError, OSError) as e:
        raise SystemExit(f"Cannot use the clubs file: {e}")
    print(f"built {build(a.out, a.seed, a.force, clubs, a.name)}")


if __name__ == "__main__":
    main()
