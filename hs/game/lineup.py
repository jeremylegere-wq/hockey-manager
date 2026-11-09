"""The user's lines: forward lines, defence pairs, goalies, power-play and penalty-kill units (docs/LINES.md).

Saved in `lineups (team_id, data, updated)` as {"F": [[C, LW, RW] x4], "D": [[L, R] x3], "G": [starter, backup],
"PP": [[5], [5]], "PK": [[4], [4]]}. The engine (hs/sim/engine.Team.apply_lineup) uses it in every game; anyone no
longer available (injured, traded, sent down) is replaced from the default depth chart for that game and the user is
told. `lines auto` deletes it and the club goes back to the automatic depth chart (ice time last season, then
ratings). Ice time follows the lines: F1-F4 get 38/31/20/11% of even-strength shifts, pairs 40/35/25%; the first
power-play and penalty-kill unit 65% of special-teams time. Starting goalie: 82% of starts, as before.
"""
from __future__ import annotations

import datetime
import json

from . import roster as R
from .events import player_name
from .state import get_state, user_team

SLOTS = {"F": (4, 3), "D": (3, 2), "PP": (2, 5), "PK": (2, 4), "OT3": (2, 3), "OT4": (2, 4)}
F_LABELS, D_LABELS = ("C", "LW", "RW"), ("LD", "RD")


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS lineups (team_id INTEGER PRIMARY KEY, data TEXT, updated TEXT)")


def saved(conn, team):
    ensure_table(conn)
    r = conn.execute("SELECT data FROM lineups WHERE team_id=?", (team,)).fetchone()
    return json.loads(r[0]) if r else None


def current(conn, team):
    """The lineup the engine would use today, as ids: {"F", "D", "G", "PP", "PK", "custom", "replaced"}."""
    from ..sim.loader import load_teams
    t = load_teams(conn).get(team)
    if t is None:
        return None
    return dict(F=[[p.pid for p in ln] for ln in t.lines], D=[[p.pid for p in pr] for pr in t.pairs],
                G=[p.pid for p in t.goalies[:2]], PP=[[p.pid for p in u] for u in t.pp],
                PK=[[p.pid for p in u] for u in t.pk], OT3=[[p.pid for p in u] for u in t.ot3], OT4=[[p.pid for p in u] for u in t.ot4],
                tend=(saved(conn, team) or {}).get("tend") or {}, custom=t.custom, replaced=getattr(t, "missing", []))


def save(conn, team, lu):
    ensure_table(conn)
    errors = validate(conn, team, lu)
    if errors:
        raise R.RosterError("; ".join(errors))
    conn.execute("INSERT OR REPLACE INTO lineups VALUES (?,?,?)", (team, json.dumps(lu), get_state(conn)[0]))


def reset(conn, team):
    ensure_table(conn)
    conn.execute("DELETE FROM lineups WHERE team_id=?", (team,))


def validate(conn, team, lu):
    errs = []
    rows = {r["player_id"]: r for r in conn.execute("SELECT player_id, position, status, team_id FROM players WHERE "
                                                    "team_id=?", (team,))}
    seen = set()
    for key in ("F", "D"):
        for unit in lu.get(key, []):
            for pid in unit:
                if pid is None:
                    continue
                r = rows.get(pid)
                if r is None:
                    errs.append(f"{player_name(conn, pid)} is not on your club")
                elif r["status"] not in ("active", "injured"):
                    errs.append(f"{player_name(conn, pid)} is not on the NHL roster")
                elif r["position"] == "G":
                    errs.append(f"{player_name(conn, pid)} is a goalie")
                if pid in seen:
                    errs.append(f"{player_name(conn, pid)} is in two places")
                seen.add(pid)
    for pid in lu.get("G", []):
        r = rows.get(pid)
        if r is None or r["position"] != "G" or r["status"] not in ("active", "injured"):
            errs.append(f"{player_name(conn, pid)} is not one of your NHL goalies")
    dressed = seen
    for key in ("PP", "PK", "OT3", "OT4"):
        for unit in lu.get(key, []):
            for pid in unit:
                if pid not in dressed:
                    errs.append(f"{player_name(conn, pid)} ({key}) must also be in the lines")
            if len(set(unit)) != len(unit):
                errs.append(f"a {key} unit names someone twice")
    return errs


def set_unit(conn, team, unit, pids):
    """unit: F1-F4, D1-D3, G, PP1-PP2, PK1-PK2. Starts from the current lineup (saved, or the automatic one)."""
    lu = saved(conn, team) or {k: v for k, v in (current(conn, team) or {}).items() if k in ("F", "D", "G", "PP", "PK", "OT3", "OT4", "tend")}
    u = unit.upper()
    key, idx = (u[:3], u[3:]) if u.startswith(("OT3", "OT4")) else (u[:2], u[2:]) if u.startswith(("PP", "PK")) else (u[:1], u[1:])
    if key == "G":
        if not 1 <= len(pids) <= 2:
            raise R.RosterError("Goalies: starter[, backup].")
        lu["G"] = pids
    else:
        if key not in SLOTS or not idx.isdigit() or not 1 <= int(idx) <= SLOTS[key][0]:
            raise R.RosterError("Units: F1-F4, D1-D3, G, PP1-PP2, PK1-PK2, OT31-OT32 (3-on-3), OT41-OT42 (4-on-4).")
        i, n = int(idx) - 1, SLOTS[key][1]
        if not pids and key in ("PP", "PK", "OT3", "OT4"):           # clear a special-teams or overtime unit
            units = lu.get(key, [])
            if i < len(units):
                units.pop(i)
            save(conn, team, lu)
            return lu
        if len(pids) != n:
            raise R.RosterError(f"{u} needs {n} players.")
        units = lu.setdefault(key, [])
        while len(units) <= i:
            units.append([])
        units[i] = pids
        if key in ("F", "D"):                       # a player moved here leaves wherever else he was
            for k in ("F", "D"):
                for j, other in enumerate(lu.get(k, [])):
                    if (k, j) == (key, i):
                        continue
                    lu[k][j] = [None if p in pids else p for p in other]
    save(conn, team, lu)
    return lu


def swap(conn, team, a, b):
    lu = saved(conn, team) or {k: v for k, v in (current(conn, team) or {}).items() if k in ("F", "D", "G", "PP", "PK", "OT3", "OT4", "tend")}
    found = 0
    for k in ("F", "D", "G", "PP", "PK"):
        units = lu.get(k, [])
        if k == "G":
            units = [units]
        for u in units:
            for i, p in enumerate(u):
                if p == a:
                    u[i] = b
                    found += 1
                elif p == b:
                    u[i] = a
                    found += 1
    if not found:
        raise R.RosterError("Neither player is in the lineup.")
    save(conn, team, lu)
    return lu


def describe(conn, team):
    cur = current(conn, team)
    if cur is None:
        return ["Your team cannot dress a lineup right now."]
    nm = lambda p: player_name(conn, p)
    out = [("Your lines" if cur["custom"] else "Automatic lines (last season's ice time); set your own with `lines set`")]
    for i, ln in enumerate(cur["F"], 1):
        out.append(f"F{i}: " + " - ".join(nm(p) for p in ln))
    for i, pr in enumerate(cur["D"], 1):
        out.append(f"D{i}: " + " - ".join(nm(p) for p in pr))
    out.append("G:  " + ", ".join(nm(p) for p in cur["G"]) + "  (starter first)")
    for k in ("PP", "PK"):
        for i, u in enumerate(cur[k], 1):
            out.append(f"{k}{i}: " + ", ".join(nm(p) for p in u))
        if not cur[k]:
            out.append(f"{k}: drawn from the top lines")
    if cur["replaced"]:
        out.append("Replaced for now (unavailable): " + ", ".join(nm(p) for p in cur["replaced"]))
    return out


TENDENCIES = {"shoot": ("pass first", "normal", "shoot first"), "style": ("defensive", "normal", "attacking")}


def set_tendency(conn, team, pid, value):
    """v33: a player's tendency, kept with your lineup: shoot first / pass first / normal (his share of his unit's
    shots and assists), attacking / defensive / normal (a little offence traded for defence, or back)."""
    kind = next((k for k, vs in TENDENCIES.items() if value in vs), None)
    if kind is None:
        raise R.RosterError("Tendencies: shoot first, pass first, attacking, defensive, normal.")
    if not conn.execute("SELECT 1 FROM players WHERE player_id=? AND team_id=?", (pid, team)).fetchone():
        raise R.RosterError("He is not on your club.")
    lu = saved(conn, team) or {k: v for k, v in (current(conn, team) or {}).items() if k in ("F", "D", "G", "PP", "PK", "OT3", "OT4")}
    tend = lu.setdefault("tend", {})
    cur = tend.get(str(pid), {})
    if value == "normal":                       # "normal" resets both
        cur = {}
    else:
        cur[kind] = value
    if cur:
        tend[str(pid)] = cur
    else:
        tend.pop(str(pid), None)
    save(conn, team, lu)
    return cur
