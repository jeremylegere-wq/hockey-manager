"""First-run setup: find the world and the league environment to play with, building the mock world if there is none.

`--template auto --env auto` (the launchers) means: the first of save/world_2026.db, save/world.db that exists, else
build the fictional world into save/world.db; the environment is save/env_2025.json if you made one, else the shipped
data/env_default.json (league-wide scoring rates; see docs/SIM_CALIBRATION.md). Worlds you add under save/worlds/ or
import in the game are offered on the New Game screen as before.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def resolve(template, env, root=ROOT):
    root = Path(root)
    if template == "auto":
        found = next((p for p in (root / "save" / "world_2026.db", root / "save" / "world.db") if p.exists()), None)
        extra = root / "save" / "worlds"
        if found is None and not (extra.exists() and any(extra.glob("*.db"))):
            from .tools import make_mock_world
            print("First run: building the fictional world (a few seconds)...")
            found = make_mock_world.build(root / "save" / "world.db")
        template = str(found or root / "save" / "world.db")
    if env == "auto":
        mine = root / "save" / "env_2025.json"
        env = str(mine if mine.exists() else root / "data" / "env_default.json")
    return template, env
