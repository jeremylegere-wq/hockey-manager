"""Play one game between two teams and print a box score.

    python -m hs.sim.play <game.db> <env.json> HOME AWAY [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import sqlite3

from .engine import Skill, simulate_game
from .loader import load_teams


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db"), ap.add_argument("env"), ap.add_argument("home"), ap.add_argument("away")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    teams = load_teams(sqlite3.connect(a.db))
    by_abbr = {t.name: t for t in teams.values()}
    h, w = by_abbr[a.home], by_abbr[a.away]
    r = simulate_game(h, w, json.load(open(a.env)), Skill(), a.seed)
    ot = " (SO)" if r.shootout else " (OT)" if r.went_to_ot else ""
    print(f"{h.name} {r.goals[0]} - {r.goals[1]} {w.name}{ot}   seed {a.seed}")
    print(f"shots on goal {r.team[0]['sog']}-{r.team[1]['sog']}   attempts {r.team[0]['att']}-{r.team[1]['att']}   "
          f"PIM {r.team[0]['pim']}-{r.team[1]['pim']}")
    names = {p.pid: p.name for t in (h, w) for p in t.skaters + t.goalies}
    for per, clock, typ, ti, pid, opp, xg, det in r.events:
        if typ in ("goal", "so_goal"):
            print(f"  P{per} {clock // 60:02d}:{clock % 60:02d}  {(h, w)[ti].name}  {names.get(pid, '?')}  {det or ''}")


if __name__ == "__main__":
    main()
