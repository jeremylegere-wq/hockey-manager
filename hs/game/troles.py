"""Tactical roles (v55; docs/TACTICS.md "Tactical roles"): jobs you give players, with a fit score and an effect on the
ice while they are out there.

Twelve roles. Each has an upside and a cost, by strength state. The upside is scaled by the player's execution, the
cost is not, and every role breaks even at execution 1 (a player of the league's average fit for that role), as the
tactics do (docs/TACTICS.md): so a role pays only when the player suits it, and costs when he does not.

    fit       = 50 + 15 x (his average in the role's attributes against the league's NHL players at his position, in
                standard deviations), 0-100: 65 is about the best sixth, 80 the best 2-3%
    execution = 0.2 + fit / 62.5, 0.2-1.8 (fit 50 -> 1.0; fit 75 -> 1.4)

Effects (multipliers while he is on the ice; "allow" = what the opponents on the ice get):
  Forwards
    Agitator           draws penalties: the opponents' penalty rate +16% x exec | he takes them: his unit's +16%, and he is
                       the one who goes (an opposing club with an enforcer dressed halves his draw)
    Shadow             against the opponents' top line: their attempts -8% x exec, their shot quality -4% x exec | his
                       unit's attempts -4% (every shift)
    Net-front presence his unit's shot quality +4% x exec, rebounds +15% x exec (even strength and power play) | attempts
                       -3%, penalties +5%
    Trigger man        power play: shot quality +6% x exec and he takes the shot (x1.8) | power-play attempts -5%
    Forechecker        attempts +5% x exec | penalties +12%, attempts allowed +2%
    Enforcer           the opponents' penalty rate +8% x exec, their shot quality -2% x exec; the other club's
                       agitators draw half as much | attempts -3%; he goes to the box more often
    Penalty killer     short-handed: attempts allowed -6% x exec, quality allowed -2% x exec | even-strength attempts -2%
  Defence
    Shutdown D         attempts allowed -5% x exec | attempts -5%
    Puck mover         attempts +5% x exec | attempts allowed +5%
    PP quarterback     power play: attempts +7% x exec | power-play shot quality -6% (point shots)
    Crease-clearer     quality allowed -4% x exec, rebounds allowed -20% x exec | penalties +12%, attempts allowed +3%
    Rover              shot quality +5% x exec | quality allowed +5% (odd-man rushes)

You set roles on the Lines screen (or `troles`); a player has one role or none. "Suggest" fills each role with the
best-fitting dressed player who clears fit 60 (a role is worth having from about there). AI clubs do the same at
setup, every preseason and when a lineup is rebuilt: so roles move results between clubs, not the league's scoring.
"""
from __future__ import annotations

import statistics

from . import roster as R
from .events import player_name
from .state import user_team

# role -> (label, positions, attributes, states, upside {key: per exec}, cost {key: fixed}, extra)
# keys: att (own unit attempts), allow (opponents' attempts), qual (own goal probability), allow_qual, reb (own
# rebound chance), allow_reb, pen (own unit's penalty rate), draw (opponents' penalty rate), allow_top /
# allow_qual_top (against the opponents' top line only), shoot (his weight on taking the shot)
ROLES = {
    "agitator": ("Agitator", "F", ("aggression", "determination", "agility", "toughness"), ("ev",),
                 {"draw": 0.12}, {"pen": 0.08, "allow": 0.01}, {"temper": 1.6}),
    "shadow": ("Shadow", "F", ("defensive_awareness", "positioning", "stick_checking", "speed"), ("ev",),
               {"allow_top": -0.08, "allow_qual_top": -0.04}, {"att": -0.04}, {}),
    "net_front": ("Net-front presence", "F", ("net_presence", "strength", "toughness", "bravery"), ("ev", "pp"),
                  {"qual": 0.04, "reb": 0.15}, {"att": -0.04}, {}),
    "trigger": ("Trigger man", "F", ("shot_power", "shot_accuracy", "composure", "offensive_awareness"), ("pp",),
                {"qual": 0.06}, {"att": -0.05}, {"shoot": 1.8}),
    "forechecker": ("Forechecker", "F", ("speed", "checking", "hitting", "endurance"), ("ev",),
                    {"att": 0.05}, {"pen": 0.04, "allow": 0.04}, {}),
    "enforcer": ("Enforcer", "F", ("toughness", "strength", "aggression", "hitting"), ("ev",),
                 {"draw": 0.04, "allow_qual": -0.02}, {"att": -0.03}, {"temper": 1.5, "protect": True}),
    "pk_specialist": ("Penalty killer", "FD", ("defensive_awareness", "positioning", "shot_blocking", "speed"), ("sh", "ev"),
                      {"sh:allow": -0.06, "sh:allow_qual": -0.02}, {"ev:att": -0.02}, {}),
    "shutdown": ("Shutdown D", "D", ("positioning", "defensive_awareness", "stick_checking", "shot_blocking"), ("ev",),
                 {"allow": -0.05}, {"att": -0.05}, {}),
    "puck_mover": ("Puck mover", "D", ("passing", "puck_control", "speed", "offensive_awareness"), ("ev",),
                   {"att": 0.05}, {"allow": 0.05}, {}),
    "pp_qb": ("PP quarterback", "D", ("passing", "puck_control", "offensive_awareness", "composure"), ("pp",),
              {"att": 0.07}, {"qual": -0.06}, {}),
    "crease_clearer": ("Crease-clearer", "D", ("strength", "hitting", "positioning", "bravery"), ("ev", "sh"),
                       {"allow_qual": -0.04, "allow_reb": -0.20}, {"pen": 0.04, "allow": 0.05}, {"temper": 1.3}),
    "rover": ("Rover", "D", ("speed", "offensive_awareness", "puck_control", "shot_accuracy"), ("ev",),
              {"qual": 0.05}, {"allow_qual": 0.05}, {}),
}
SUGGEST_FIT = 60
MAX_PER_ROLE = 2


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS tactical_roles (team_id INTEGER, player_id INTEGER PRIMARY KEY, role TEXT)")


def _pos(position):
    return "G" if position == "G" else "D" if position == "D" else "F"


def _z(v):
    return ((v if v is not None else 10) - 10.5) / 3.0


def league_means(conn):
    """{(role, F|D): the league's average NHL player's role z} (cached per connection and day)."""
    from .state import get_state
    key = (id(conn), get_state(conn)[0] if conn.execute("SELECT 1 FROM sqlite_master WHERE name='game_state'").fetchone() else "")
    if _CACHE.get("key") == key:
        return _CACHE["means"]
    from ..schema import top_league_sql
    rows = conn.execute(f"SELECT p.position, a.* FROM players p JOIN player_attributes a USING (player_id) WHERE p.status='active' AND "
                        f"p.team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()}) AND p.position<>'G'").fetchall()
    means = {}
    for r, (_, pos, attrs, *_x) in ROLES.items():
        for g in ("F", "D"):
            vals = [statistics.fmean(_z(x[a]) for a in attrs) for x in rows if _pos(x["position"]) == g]
            means[(r, g)] = (statistics.fmean(vals), statistics.pstdev(vals) or 0.3) if len(vals) > 1 else (0.0, 0.3)
    _CACHE.update(key=key, means=means)
    return means


_CACHE = {}


def fit(conn, attrs_row, position, role, means=None):
    label, pos, attrs, *_ = ROLES[role]
    g = _pos(position)
    if g not in pos:
        return None
    means = means or league_means(conn)
    mu, sd = means[(role, g)]
    z = (statistics.fmean(_z(attrs_row[a]) for a in attrs) - mu) / sd
    return max(0, min(100, round(50 + 15 * z)))


def execution(f):
    return max(0.2, min(1.8, 0.2 + (f or 0) / 62.5))


def fits(conn, pid, means=None):
    """{role: fit} for every role open to his position."""
    r = conn.execute("SELECT p.position, a.* FROM players p JOIN player_attributes a USING (player_id) WHERE p.player_id=?", (pid,)).fetchone()
    if r is None:
        return {}
    means = means or league_means(conn)
    out = {}
    for role in ROLES:
        f = fit(conn, r, r["position"], role, means)
        if f is not None:
            out[role] = f
    return out


def effects(role, f):
    """The engine's per-state multipliers for a player in `role` at fit f: {state: {key: multiplier}} and extras."""
    label, pos, attrs, states, up, cost, extra = ROLES[role]
    x = execution(f)
    fx = {}

    def add(key, v, scaled):
        st = None
        if ":" in key:
            st, key = key.split(":")
        for s in ([st] if st else states):
            d = fx.setdefault(s, {})
            d[key] = d.get(key, 1.0) * (1 + v * (x if scaled else 1.0))
    for k, v in up.items():
        add(k, v, True)
    for k, v in cost.items():
        add(k, v, False)
    if "shoot" in extra:
        for s in states:
            fx.setdefault(s, {})["shoot"] = extra["shoot"]
    return fx, extra


def team_roles(conn, team):
    ensure_table(conn)
    return {r[0]: r[1] for r in conn.execute("SELECT player_id, role FROM tactical_roles WHERE team_id=?", (team,))}


def set_role(conn, team, pid, role):
    ensure_table(conn)
    if role in (None, "", "none"):
        conn.execute("DELETE FROM tactical_roles WHERE player_id=?", (pid,))
        return None
    if role not in ROLES:
        raise ValueError("Roles: " + ", ".join(ROLES) + ".")
    r = conn.execute("SELECT team_id, position FROM players WHERE player_id=?", (pid,)).fetchone()
    if r is None or r[0] != team:
        raise ValueError("He is not on your club.")
    if _pos(r[1]) not in ROLES[role][1]:
        raise ValueError(f"{ROLES[role][0]} is a role for {'forwards' if ROLES[role][1] == 'F' else 'defencemen'}.")
    n = conn.execute("SELECT COUNT(*) FROM tactical_roles WHERE team_id=? AND role=? AND player_id<>?", (team, role, pid)).fetchone()[0]
    if n >= MAX_PER_ROLE:
        raise ValueError(f"Two players at most in a role ({ROLES[role][0]}).")
    conn.execute("INSERT OR REPLACE INTO tactical_roles VALUES (?,?,?)", (team, pid, role))
    return fits(conn, pid).get(role)


def _dressed(conn, team, lines=True):
    """The skaters in the club's lineup today (its saved lines, else the roster's active skaters)."""
    from . import lineup as L
    try:
        if not lines:
            raise LookupError
        cur = L.current(conn, team) or {}
        ids = {p for ln in cur.get("F", []) for p in ln if p} | {p for pr in cur.get("D", []) for p in pr if p}
        if ids:
            return ids
    except Exception:
        pass
    return {r["player_id"] for r in R.roster(conn, team) if r["status"] == "active" and r["position"] != "G"}


def suggest(conn, team, apply=True, lines=True):
    """Give each role the best-fitting dressed players who clear SUGGEST_FIT (one role each, at most one per role,
    two for the penalty killer)."""
    ensure_table(conn)
    means = league_means(conn)
    ids = _dressed(conn, team, lines)
    rows = {r["player_id"]: r for r in conn.execute(f"SELECT p.player_id, p.position, a.* FROM players p JOIN player_attributes a "
                                                    f"USING (player_id) WHERE p.player_id IN ({','.join('?' * len(ids))})", tuple(ids))} if ids else {}
    cand = []
    for pid, r in rows.items():
        for role in ROLES:
            f = fit(conn, r, r["position"], role, means)
            if f is not None and f >= SUGGEST_FIT:
                cand.append((f, pid, role))
    cand.sort(reverse=True)
    taken, used, out = {}, set(), {}
    for f, pid, role in cand:
        cap = 2 if role == "pk_specialist" else 1
        if pid in used or taken.get(role, 0) >= cap:
            continue
        taken[role] = taken.get(role, 0) + 1
        used.add(pid)
        out[pid] = (role, f)
    if apply:
        conn.execute("DELETE FROM tactical_roles WHERE team_id=?", (team,))
        conn.executemany("INSERT OR REPLACE INTO tactical_roles VALUES (?,?,?)", [(team, pid, role) for pid, (role, _) in out.items()])
    return out


def ai_assign(conn):
    """Every AI club suggests its roles (setup, preseason)."""
    from ..schema import top_league_sql
    me = user_team(conn)
    for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}").fetchall():
        if t != me:
            suggest(conn, t, lines=False)


def ensure_ai(conn, day=None):
    """AI clubs' roles: once for a save from before v55, then on the first game day of each month (trades, injuries)."""
    ensure_table(conn)
    month = (day or "")[:7]
    r = conn.execute("SELECT value FROM pack_info WHERE key='troles_ai'").fetchone()
    if r is None or (month and r[0] != month):
        ai_assign(conn)
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('troles_ai', ?)", (month or "1",))


def engine_roles(conn):
    """{player_id: (fx, extra)} for every player with a role (the loader puts them on the engine's players)."""
    ensure_table(conn)
    means = league_means(conn)
    out = {}
    cur = conn.execute("SELECT r.player_id, r.role, p.position, a.* FROM tactical_roles r JOIN players p USING (player_id) "
                       "JOIN player_attributes a USING (player_id) WHERE p.team_id=r.team_id")   # a traded player leaves his role behind
    for r in cur.fetchall():
        if r["role"] not in ROLES:
            continue
        f = fit(conn, r, r["position"], r["role"], means)
        if f is None:
            continue
        out[r["player_id"]] = effects(r["role"], f)
    return out


def describe(role):
    label, pos, attrs, states, up, cost, extra = ROLES[role]
    sign = lambda v: f"{'+' if v > 0 else ''}{round(v * 100):d}%"
    names = {"att": "attempts", "allow": "attempts allowed", "qual": "shot quality", "allow_qual": "quality allowed", "reb": "rebounds",
             "allow_reb": "rebounds allowed", "pen": "penalties", "draw": "opponents' penalties", "allow_top": "top line's attempts",
             "allow_qual_top": "top line's quality"}
    part = lambda d, scaled: ", ".join(f"{names.get(k.split(':')[-1], k)} {sign(v)}{' x exec' if scaled else ''}"
                                       + (f" ({k.split(':')[0]})" if ':' in k else "") for k, v in d.items())
    st = {"ev": "even strength", "pp": "power play", "sh": "short-handed"}
    return dict(role=role, label=label, positions=pos, attributes=list(attrs), states=[st[s] for s in states], upside=part(up, True),
                cost=part(cost, False), extra=("takes the shot on the power play" if "shoot" in extra else "")
                + ("halves the other club's agitators" if extra.get("protect") else ""))


def view(conn, team=None):
    team = team or user_team(conn)
    ensure_table(conn)
    means = league_means(conn)
    roles = team_roles(conn, team)
    ids = _dressed(conn, team)
    rows = []
    for r in conn.execute("SELECT p.player_id, p.position, p.first_name||' '||p.last_name name, a.* FROM players p JOIN player_attributes a "
                          "USING (player_id) WHERE p.team_id=? AND p.status IN ('active', 'injured') AND p.position<>'G'", (team,)):
        fs = {role: fit(conn, r, r["position"], role, means) for role in ROLES}
        fs = {k: v for k, v in fs.items() if v is not None}
        best = max(fs, key=fs.get) if fs else None
        cur = roles.get(r["player_id"])
        rows.append(dict(player_id=r["player_id"], name=r["name"], pos=r["position"], dressed=r["player_id"] in ids, role=cur,
                         fit=fs.get(cur) if cur else None, exec=round(execution(fs.get(cur)), 2) if cur else None, best=best,
                         best_fit=fs.get(best), fits=fs))
    rows.sort(key=lambda x: (not x["dressed"], x["pos"] == "D", -(x["best_fit"] or 0)))
    return dict(team_id=team, players=rows, roles=[describe(k) for k in ROLES], suggest_fit=SUGGEST_FIT, max_per_role=MAX_PER_ROLE)
