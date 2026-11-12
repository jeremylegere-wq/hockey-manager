"""Game settings (File > Settings): one JSON file next to the saves, read by the front end at start-up.

Interface settings only; nothing here changes the simulation. Unknown keys are dropped and values are clamped, so a
hand-edited file cannot break the UI.
"""
from __future__ import annotations

import json
from pathlib import Path

VERSION = "0.59"

DEFAULTS = {
    "ui_scale": 100,            # percent: the whole interface (resolution scaling)
    "units": "metric",          # metric | imperial: heights and weights
    "confirm_phase": True,      # ask before leaving an offseason phase with decisions left
    "player_popups": True,      # the small player card when you hover a name
    "sim_pace": 0.6,            # sim centre pace in seconds a day (0 = instant)
    "highlight_team": True,     # your club's name in capitals in tables
    "show_console": False,      # the command box in the bottom bar
    "intro": True,              # the launch screen (off: straight to the last career)
    "draft_clock": 90,          # seconds you have on the clock in the draft room (then your scouts pick)
    "backups": 3,               # rolling backups kept per career (0 = none); one a game week and at each phase
    "schedule_strip": True,     # the strip of your games (yesterday into next week) under the club header
    # v38: what interrupts "rest of season" and "play until" (a day or a week always stops for anything new)
    "stop_trade_offer": True,   # a club makes you a trade offer
    "stop_board": True,         # the owner's office writes (ultimatums, directives)
    "stop_press": True,         # a major press conference (captaincy, trade request, deadline, season end)
    "stop_deadline": True,      # three days before the trade deadline, and deadline day
    "stop_injury": False,       # one of your players is hurt
    "stop_room": False,         # trouble in the dressing room
}
CHOICES = {"units": ("metric", "imperial")}
RANGES = {"ui_scale": (80, 150), "sim_pace": (0.0, 5.0), "draft_clock": (20, 600), "backups": (0, 10)}


def _clean(d):
    out = dict(DEFAULTS)
    for k, v in (d or {}).items():
        if k not in DEFAULTS:
            continue
        base = DEFAULTS[k]
        try:
            if isinstance(base, bool):
                v = bool(v)
            elif isinstance(base, (int, float)):
                v = type(base)(v)
                lo, hi = RANGES.get(k, (v, v))
                v = max(lo, min(hi, v))
            else:
                v = str(v)
                if k in CHOICES and v not in CHOICES[k]:
                    continue
        except (TypeError, ValueError):
            continue
        out[k] = v
    return out


def load(path):
    p = Path(path)
    try:
        return _clean(json.loads(p.read_text()))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(path, changes):
    cur = load(path)
    cur.update(changes or {})
    cur = _clean(cur)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2))
    return cur
