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


def build(out, seed=1, force=False):
    out = Path(out)
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        league, world = Path(tmp) / "league", Path(tmp) / "world"
        make_mock_league.generate(league, seed)
        build_world.build(league, world, seed, fictional=True)
        ingest.build_db(world, str(out), overwrite=True)
    conn = sqlite3.connect(out)
    conn.execute("INSERT OR REPLACE INTO pack_info VALUES ('world_name', ?)", (f"{WORLD_NAME}, seed {seed}",))
    conn.commit()
    conn.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="save/world.db")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    print(f"built {build(a.out, a.seed, a.force)}")


if __name__ == "__main__":
    main()
