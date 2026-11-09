"""Lineups: priority lists that rebuild your lines before every game, and the goalie start rule (v52; docs/LINES.md
"Lineups").

You rank players for each slot: centres, left wings, right wings, left and right defence, goalies, the power play and
the penalty kill (a player may be on several lists). Before each of your games, with lineups on, the lines are built
from the lists: the first healthy player on the roster not already used fills each slot in order (C1, C2... then the
wings line by line, then the pairs), the power play takes the first ten dressed players on its list (two units of
five), the penalty kill the first eight (two of four), and an empty power-play or penalty-kill list leaves those units to
the engine (drawn from the top lines); a list that runs out is filled from the best remaining players
at the position. Overtime units are kept as saved. Your saved lines are replaced each game day, so lines you set by
hand stay only until the next game; turn lineups off to set lines by hand again.

The goalie rule (with lineups on): "usual" (the first goalie on the list starts about 82% of games, as before),
"every game" (he starts them all), "rest on back-to-backs" (the second goalie starts the second of two games on
consecutive days), "every fourth game" (the second goalie starts every fourth game).
"""
from __future__ import annotations

import datetime
import json

from . import lineup as L
from . import roster as R
from .events import player_name
from .state import get_state, user_team

LISTS = ("C", "LW", "RW", "LD", "RD", "G", "PP", "PK")
GOALIE_RULES = ("usual", "every_game", "back_to_back", "every_fourth")


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS lineup_priority (team_id INTEGER PRIMARY KEY, data TEXT, goalie_rule TEXT DEFAULT 'usual', "
                 "enabled INTEGER DEFAULT 0, starts INTEGER DEFAULT 0)")


def get(conn, team):
    ensure_table(conn)
    r = conn.execute("SELECT data, goalie_rule, enabled, starts FROM lineup_priority WHERE team_id=?", (team,)).fetchone()
    if not r:
        return dict(lists={k: [] for k in LISTS}, goalie_rule="usual", enabled=False, starts=0)
    d = json.loads(r[0] or "{}")
    return dict(lists={k: d.get(k, []) for k in LISTS}, goalie_rule=r[1] or "usual", enabled=bool(r[2]), starts=r[3] or 0)


def _store(conn, team, cur):
    ensure_table(conn)
    conn.execute("INSERT OR REPLACE INTO lineup_priority VALUES (?,?,?,?,?)",
                 (team, json.dumps(cur["lists"]), cur["goalie_rule"], int(cur["enabled"]), cur.get("starts", 0)))


def suggest(conn, team):
    """Lists from the club's current lines and depth (a starting point to reorder)."""
    cur = L.current(conn, team) or {}
    lists = {k: [] for k in LISTS}
    for ln in cur.get("F", []):
        for slot, pid in zip(("C", "LW", "RW"), ln):
            lists[slot].append(pid)
    for pr in cur.get("D", []):
        for slot, pid in zip(("LD", "RD"), pr):
            lists[slot].append(pid)
    lists["G"] = list(cur.get("G", []))
    lists["PP"] = [p for u in cur.get("PP", []) for p in u]
    lists["PK"] = [p for u in cur.get("PK", []) for p in u]
    # everyone else on the roster at the end of his position's lists
    used = {p for v in lists.values() for p in v}
    for r in sorted(R.roster(conn, team), key=lambda r: -R.player_value(conn, r["player_id"])):
        if r["player_id"] in used:
            continue
        pos = r["position"]
        key = {"C": "C", "LW": "LW", "RW": "RW", "G": "G"}.get(pos, "LD" if len(lists["LD"]) <= len(lists["RD"]) else "RD")
        lists[key].append(r["player_id"])
    return lists


def set_list(conn, team, key, pids):
    if key not in LISTS:
        raise ValueError("Lists: " + ", ".join(LISTS) + ".")
    roster = {r["player_id"]: r["position"] for r in R.roster(conn, team)}
    bad = [p for p in pids if p not in roster]
    if bad:
        raise ValueError(f"{player_name(conn, bad[0])} is not on the NHL roster.")
    if key == "G" and any(roster[p] != "G" for p in pids):
        raise ValueError("Only goalies on the goalie list.")
    if key != "G" and any(roster[p] == "G" for p in pids):
        raise ValueError("No goalies on a skater list.")
    cur = get(conn, team)
    cur["lists"][key] = list(dict.fromkeys(pids))
    _store(conn, team, cur)


def set_enabled(conn, team, on):
    cur = get(conn, team)
    if on and not any(cur["lists"].values()):
        cur["lists"] = suggest(conn, team)
    cur["enabled"] = bool(on)
    _store(conn, team, cur)


def set_goalie_rule(conn, team, rule):
    if rule not in GOALIE_RULES:
        raise ValueError("Goalie rule: " + ", ".join(GOALIE_RULES) + ".")
    cur = get(conn, team)
    cur["goalie_rule"] = rule
    _store(conn, team, cur)


def build(conn, team, day=None):
    """The lineup the lists give today: {"F", "D", "G", "PP", "PK", ...} (and G_force for the goalie rule)."""
    cur = get(conn, team)
    lists = cur["lists"]
    avail = {}
    from .discipline import suspended
    out = suspended(conn)
    for r in R.roster(conn, team):
        if r["status"] == "active" and r["player_id"] not in out:
            avail[r["player_id"]] = r["position"]
    used = set()
    value = {}

    def best(pred):
        c = [p for p, pos in avail.items() if p not in used and pred(pos)]
        if not c:
            return None
        for p in c:
            if p not in value:
                value[p] = R.player_value(conn, p)
        return max(c, key=lambda p: value[p])

    def take(key, pred):
        for p in lists.get(key, []):
            if p in avail and p not in used and avail[p] != "G":
                used.add(p)
                return p
        p = best(pred)
        if p:
            used.add(p)
        return p
    centres = [take("C", lambda pos: pos == "C") for _ in range(4)]
    F = []
    for k in range(4):
        lw = take("LW", lambda pos: pos in ("LW", "RW", "C"))
        rw = take("RW", lambda pos: pos in ("RW", "LW", "C"))
        F.append([centres[k], lw, rw])
    D = []
    for k in range(3):
        ld = take("LD", lambda pos: pos == "D")
        rd = take("RD", lambda pos: pos == "D")
        D.append([ld, rd])
    goalies = [p for p in lists.get("G", []) if p in avail and avail[p] == "G"]
    goalies += sorted((p for p, pos in avail.items() if pos == "G" and p not in goalies), key=lambda p: -R.player_value(conn, p))
    dressed = {p for ln in F for p in ln if p} | {p for pr in D for p in pr if p}

    def units(key, size, n):
        pool = [p for p in lists.get(key, []) if p in dressed]
        if not pool:
            return []                                    # no list: the engine draws the units from the top lines
        for p in dressed:
            if p not in value:
                value[p] = R.player_value(conn, p)
        pool += [p for p in sorted(dressed, key=lambda p: -value[p]) if p not in pool]
        return [pool[i * size:(i + 1) * size] for i in range(n)]
    lu = dict(F=[[x for x in ln] for ln in F], D=[[x for x in pr] for pr in D], G=goalies[:2],
              PP=units("PP", 5, 2), PK=units("PK", 4, 2))
    saved = L.saved(conn, team) or {}
    for k in ("OT3", "OT4"):
        if saved.get(k):
            lu[k] = saved[k]
    rule = cur["goalie_rule"]
    if len(lu["G"]) == 2 and rule != "usual":
        backup_today = False
        if rule == "back_to_back" and day:
            yday = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
            backup_today = bool(conn.execute("SELECT 1 FROM games WHERE game_date=? AND played=1 AND (home_team_id=? OR away_team_id=?)",
                                             (yday, team, team)).fetchone())
        elif rule == "every_fourth":
            backup_today = (cur.get("starts", 0) + 1) % 4 == 0
        if backup_today:
            lu["G"] = [lu["G"][1], lu["G"][0]]
        lu["G_force"] = True
    return lu


def before_games(conn, day):
    """Rebuild your lines from your lists if you play today (called before the day's games)."""
    team = user_team(conn)
    if team is None:
        return None
    cur = get(conn, team)
    if not cur["enabled"]:
        return None
    if not conn.execute("SELECT 1 FROM games WHERE game_date=? AND played=0 AND (home_team_id=? OR away_team_id=?)",
                        (day, team, team)).fetchone():
        return None
    lu = build(conn, team, day)
    L.ensure_table(conn)
    conn.execute("INSERT OR REPLACE INTO lineups (team_id, data, updated) VALUES (?,?,?)", (team, json.dumps(lu), day))
    cur["starts"] = cur.get("starts", 0) + 1
    _store(conn, team, cur)
    return lu


def view(conn, team=None):
    team = team or user_team(conn)
    cur = get(conn, team)
    lists = cur["lists"] if any(cur["lists"].values()) else suggest(conn, team)
    roster = {r["player_id"]: r for r in R.roster(conn, team)}
    name = lambda p: player_name(conn, p)
    return dict(enabled=cur["enabled"], goalie_rule=cur["goalie_rule"], rules=list(GOALIE_RULES),
                lists={k: [dict(player_id=p, name=name(p), pos=roster[p]["position"] if p in roster else "?",
                                status=roster[p]["status"] if p in roster else "gone") for p in v] for k, v in lists.items()},
                roster=[dict(player_id=p, name=name(p), pos=r["position"], status=r["status"]) for p, r in roster.items()],
                preview=build(conn, team) if roster else None)
