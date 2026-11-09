"""Rules that change by season: overtime format, ties, points for an overtime loss, schedule length.

A pack's rules.json can carry
    "eras": [{"from": 2026, "schedule": {"games_per_team": 84, ...}}, {"until": 1982, "overtime": {...}}, ...]
or "era_preset": "nhl" for the built-in NHL history below. `for_season(rules, start_year)` returns the rules with
every era whose range covers that season merged in (later entries win). Seasons are named by the year they start.

NHL history (regular season; playoff overtime has always been 20-minute 5v5 sudden death in this sim):
  to 1982-83     no overtime: tied games stay tied (a point each)
  1983-84        5 minutes of 5v5 sudden death; still tied = tie; an overtime loss is a loss (no point)
  1999-2000      4v4 for 5 minutes; the overtime loser keeps a point; ties remain
  2005-06        4v4, then a shootout: no more ties
  2015-16        3v3, then a shootout
  2026-27        84 games: four against every division rival (28), three against the other division of the
                 conference (24), two against the other conference (32). The 2026-30 CBA sets 84 games; the
                 four-each split is the arrangement the league described, not a published schedule matrix.
(The 1942-43 to 1982-83 seasons had no overtime; earlier, ten-minute overtimes were played. Schedules before
2026 keep the pack's own schedule rules.)
"""
from __future__ import annotations

import json

NHL_ERAS = [
    {"until": 1982, "overtime": {"format": "none", "minutes": 0, "shootout": False},
     "points": {"win": 2, "ot_loss": 0, "loss": 0, "tie": 1}},
    {"from": 1983, "until": 1998, "overtime": {"format": "5v5", "minutes": 5, "shootout": False},
     "points": {"win": 2, "ot_loss": 0, "loss": 0, "tie": 1}},
    {"from": 1999, "until": 2004, "overtime": {"format": "4v4", "minutes": 5, "shootout": False},
     "points": {"win": 2, "ot_loss": 1, "loss": 0, "tie": 1}},
    {"from": 2005, "until": 2014, "overtime": {"format": "4v4", "minutes": 5, "shootout": True}},
    {"from": 2015, "overtime": {"format": "3v3", "minutes": 5, "shootout": True}},
    {"from": 2026, "schedule": {"games_per_team": 84,
                                "same_division": {"games": 4, "reduced_games": 4, "reduced_opponents_per_team": 0},
                                "same_conference": {"games": 3}, "other_conference": {"games": 2}}},
]
PRESETS = {"nhl": NHL_ERAS}


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = json.loads(json.dumps(v))
    return base


def eras_of(rules):
    eras = list(PRESETS.get((rules or {}).get("era_preset") or "", []))
    return eras + list((rules or {}).get("eras") or [])


def for_season(rules, start_year):
    """The rules in force for the season starting in start_year."""
    out = json.loads(json.dumps(rules))
    for e in eras_of(rules):
        if e.get("from", -10 ** 9) <= start_year <= e.get("until", 10 ** 9):
            _merge(out, {k: v for k, v in e.items() if k not in ("from", "until")})
    return out


def describe(rules, start_year):
    r = for_season(rules, start_year)
    ot = r["overtime"]
    if ot["format"] == "none" or not ot.get("minutes"):
        o = "no overtime" + (", shootout" if ot.get("shootout") else ", ties stand")
    else:
        o = f"{ot['minutes']} min {ot['format']} overtime" + (", then a shootout" if ot.get("shootout") else
                                                               ", then a tie")
    p = r["points"]
    pts = f"win {p['win']}, overtime loss {p['ot_loss']}" + (f", tie {p.get('tie', 1)}" if not ot.get("shootout") else "")
    return f"{start_year}-{(start_year + 1) % 100:02d}: {r['schedule']['games_per_team']} games, {o}; points {pts}"
