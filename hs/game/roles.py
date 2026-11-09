"""Player roles (phase B, v33): what kind of player each one is, read from his ratings, and what a line is missing.

Major roles come from the attributes (each role's attributes averaged, compared with the player's own average; the
best fit wins, with his fit as a 0-100 score):
  forwards   sniper, playmaker, power forward, two-way forward, grinder, enforcer
  defence    offensive D, defensive D, two-way D, physical D
  goalies    positional, athletic
Supplementary roles come from value, age and contract: franchise, star, core, depth, prospect, veteran.
The Lines screen uses them to say what a line has and lacks (no finisher, no puck mover, no defensive conscience).
Display only: the engine reads the ratings themselves, so roles never change a result.
"""
from __future__ import annotations

import datetime
import statistics

from . import roster as R

MAJOR = {
    "F": {
        "Sniper": ("shot_accuracy", "shot_power", "offensive_awareness"),
        "Playmaker": ("passing", "puck_control", "offensive_awareness"),
        "Power forward": ("strength", "net_presence", "hitting", "shot_power"),
        "Two-way forward": ("defensive_awareness", "positioning", "stick_checking", "faceoffs"),
        "Grinder": ("checking", "hitting", "endurance", "determination"),
        "Enforcer": ("toughness", "aggression", "hitting", "strength"),
    },
    "D": {
        "Offensive D": ("passing", "puck_control", "offensive_awareness", "shot_power"),
        "Defensive D": ("positioning", "defensive_awareness", "shot_blocking", "stick_checking"),
        "Two-way D": ("passing", "positioning", "defensive_awareness", "puck_control"),
        "Physical D": ("hitting", "strength", "checking", "toughness"),
    },
    "G": {
        "Positional": ("goalie_positioning", "rebound_control", "low_shot_save"),
        "Athletic": ("reflexes", "glove", "blocker", "recovery"),
    },
}
OFFENCE = {"Sniper", "Power forward", "Playmaker"}
BIAS = {"Enforcer": 1.6, "Grinder": 0.0, "Power forward": 0.45, "Physical D": 0.8, "Two-way D": -0.35}


def _group(pos):
    return "G" if pos == "G" else "D" if pos == "D" else "F"


def major_role(a, pos):
    g = _group(pos)
    roles = MAJOR[g]
    keys = sorted({k for v in roles.values() for k in v})
    own = statistics.fmean((a.get(k) or 10) for k in keys)
    # the specialist roles have to stand out (a skilled forward who is also strong is not an enforcer)
    score = {r: statistics.fmean((a.get(k) or 10) for k in ks) - own - BIAS.get(r, 0.0) for r, ks in roles.items()}
    best = max(score, key=score.get)
    return best, max(0, min(100, round(50 + 12 * score[best])))


def supplementary(value, age, contract_years_left):
    if value >= 62:
        return "Franchise"
    if value >= 57:
        return "Star"
    if age <= 21 and value < 50:
        return "Prospect"
    if age >= 33:
        return "Veteran"
    if value >= 50:
        return "Core"
    return "Depth"


def team_roles(conn, team):
    """{pid: dict(role, fit, tag)} for a club's players."""
    on = datetime.date.fromisoformat(conn.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone()[0])
    year = on.year if on.month >= 7 else on.year - 1
    out = {}
    from . import contracts as K
    for p in conn.execute("SELECT p.player_id, p.position, p.birth_date, a.* FROM players p JOIN player_attributes a USING (player_id) "
                          "WHERE p.team_id=? AND p.status IN ('active','injured','ltir','prospect')", (team,)):
        a = {k: p[k] for k in p.keys()}
        role, fit = major_role(a, p["position"])
        b = datetime.date.fromisoformat(p["birth_date"])
        age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
        c = K.current_contract(conn, p["player_id"], year)
        m = lambda *ks: statistics.fmean((a.get(k) or 10) for k in ks)
        out[p["player_id"]] = dict(role=role, fit=fit, tag=supplementary(R.player_value(conn, p["player_id"]), age,
                                                                         (c["start_year"] + c["years"] - year) if c else 0),
                                   shot=m("shot_accuracy", "shot_power"), pas=m("passing", "puck_control"),
                                   dfn=m("defensive_awareness", "positioning"))
    return out


def line_notes(roles, line, d=False):
    """What a line (or a pair) lacks, in a few words: judged on the ratings (a finisher shoots 12+, a playmaker passes
    12+, a defensive conscience reads the game 11+; a pair needs a puck mover and a stay-at-home side)."""
    rs = [roles.get(p) for p in line if p and roles.get(p)]
    if not rs:
        return []
    best = lambda k: max(r[k] for r in rs)
    notes = []
    if d:
        if best("dfn") < 11:
            notes.append("no stay-at-home defenceman")
        if best("pas") < 11:
            notes.append("nobody to move the puck")
        return notes
    if best("shot") < 12:
        notes.append("no finisher")
    if best("pas") < 12:
        notes.append("no playmaker")
    if best("dfn") < 11:
        notes.append("no defensive conscience")
    return notes
