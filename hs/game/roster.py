"""Roster moves and AI roster management.

A team's roster = players with that team_id and status in ('active','injured'). Limits: max 26, min 20 (override with
rules.json {"roster": {"max": .., "min": ..}}). To play, a team needs 12 forwards, 6 D and 2 goalies, all healthy.

player_value (about 0-100, 50 = league-average rating):
    skaters: mean(offensive_awareness, passing, puck_control, shot_accuracy, positioning, defensive_awareness, hitting)
    goalies: mean(goalie_positioning, reflexes, glove, blocker, low_shot_save, rebound_control)
    value = (mean - 1) / 19 * 100 * age_factor
    age_factor: 1 from 21 to 33; -1% per year under 21; -2% per year over 33 (ratings already age; this only nudges).
Missing attributes count as the neutral 10.

trade_value (what the AI compares in trades), v39: value above replacement,
    TV50 * ((value - REPLACEMENT) / (50 - REPLACEMENT)) ** TRADE_EXPONENT   (0 at or below REPLACEMENT = 42)
on the same scale as draft picks (a mid 1st-round pick is 85, a mid 2nd 29): an average NHL player (50) is worth 30
(a 2nd), the 75th percentile (53) about 85 (a mid 1st), the 90th (56) about 190, the best (61) about 550; a fringe
NHLer (46.8) about 5 (a 4th or 5th), a minor-league veteran nothing. Fitted to what real deadline deals pay (a late
1st for a top-six rental, a 2nd for a middle-six regular, a 4th-7th or future considerations for depth). Before v39
it was 100 * (value / 50) ** 2.5, which priced a replacement-level forward (44) like a late 1st-round pick (73), so
clubs swapped NHL regulars for prospects far more than real clubs do.
"""
from __future__ import annotations

import datetime
import json

from .state import add_message, get_state, user_team

DEFAULT_MAX, DEFAULT_MIN = 26, 20
NEED = {"F": 12, "D": 6, "G": 2}
TRADE_EXPONENT = 3.3
TV50 = 30.0                 # v39: trade value of an average NHL player (50)
REPLACEMENT = 42.0          # v39: the value of a freely available player (a 13th forward / AHL call-up)
UPGRADE_PROB = 0.02
UPGRADE_MARGIN = 5.0
SKATER_KEYS = ("offensive_awareness", "passing", "puck_control", "shot_accuracy", "positioning", "defensive_awareness",
               "hitting")
GOALIE_KEYS = ("goalie_positioning", "reflexes", "glove", "blocker", "low_shot_save", "rebound_control")


class RosterError(Exception):
    pass


def group(pos):
    return "G" if pos == "G" else "D" if pos == "D" else "F"


def limits(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    ro = (json.loads(r["value"]).get("roster") or {}) if r else {}
    return ro.get("min", DEFAULT_MIN), ro.get("max", DEFAULT_MAX)


def _today(conn):
    st = get_state(conn)
    return datetime.date.fromisoformat(st[0]) if st else datetime.date.today()


def age_factor(age):
    """Small asset-value adjustment; ageing itself now lives in the ratings (hs.worldgen), so this only nudges."""
    if age < 21:
        return max(0.0, 1 - 0.01 * (21 - age))
    if age > 33:
        return max(0.0, 1 - 0.02 * (age - 33))
    return 1.0


# The single value number (0-100 on the rating scale) every management system reads: trades, the salary market,
# depth decisions, waivers. FLAT is the original (equal weights on seven attributes, hitting included);
# VALUE_WEIGHTS replaces it from v25 (docs/RATINGS_MODEL.md).
# Fitted (non-negative least squares) on ratings built from data up to 2023-24 against 2024-25 ice time, points
# and game score a game, blended 50/50 with a prior that gives defence its due; tested on 2024 ratings against
# 2025-26 (hs/tools/ratings_check.py). Rank correlation out of sample, forwards: ice time 0.61, points 0.67, game
# score 0.69 (flat formula: 0.24 / 0.28 / 0.37); defence 0.43 / 0.55 / 0.63 (flat 0.30 / 0.38 / 0.45).
VALUE_WEIGHTS = {
    "F": {"passing": 0.365, "puck_control": 0.143, "stick_checking": 0.13, "offensive_awareness": 0.104,
          "composure": 0.061, "shot_accuracy": 0.061, "defensive_awareness": 0.05, "positioning": 0.05,
          "shot_power": 0.036},
    "D": {"offensive_awareness": 0.188, "passing": 0.169, "puck_control": 0.151, "stick_checking": 0.142,
          "positioning": 0.114, "defensive_awareness": 0.1, "composure": 0.053, "shot_accuracy": 0.042,
          "shot_blocking": 0.025, "shot_power": 0.017},
}
# The weighted composite is wider than the flat formula (forwards sd 5.8 against 3.5 value points). The salary
# market, trade values, waiver claims and depth decisions were all calibrated on the flat formula's scale, and a
# trial with the wider spread broke them (max-salary contracts for a dozen players, AI trades down from ~35 to 4-20
# a season, waiver claims tripled). So the composite is mapped back onto the flat formula's mean and spread for NHL
# skaters: the order of players changes (the fix), the scale does not. RAW = (mean, sd) of the weighted composite,
# FLAT = (mean, sd) of the flat formula, NHL rosters of the 2025-26 pack.
VALUE_SCALE = {"F": {"raw": (48.87, 5.76), "flat": (50.18, 3.50)},
               "D": {"raw": (49.38, 5.84), "flat": (49.72, 3.79)}}


def value_from_attrs(a, pos):
    """Value from a dict of attributes and the position (no age adjustment)."""
    if pos == "G":
        keys = GOALIE_KEYS
        vals = [a.get(k) if a.get(k) is not None else 10 for k in keys]
        return (sum(vals) / len(vals) - 1) / 19.0 * 100.0
    w = (VALUE_WEIGHTS or {}).get("D" if pos == "D" else "F")
    if not w:
        vals = [a.get(k) if a.get(k) is not None else 10 for k in SKATER_KEYS]
        return (sum(vals) / len(vals) - 1) / 19.0 * 100.0
    tot = sum(w.values())
    x = sum(wt * (a.get(k) if a.get(k) is not None else 10) for k, wt in w.items()) / tot
    raw = (x - 1) / 19.0 * 100.0
    sc = VALUE_SCALE["D" if pos == "D" else "F"]
    return sc["flat"][0] + (raw - sc["raw"][0]) * sc["flat"][1] / sc["raw"][1]


def player_value(conn, player_id, on=None):
    p = conn.execute("SELECT p.position, p.birth_date, a.* FROM players p JOIN player_attributes a USING (player_id) "
                     "WHERE p.player_id=?", (player_id,)).fetchone()
    if p is None:
        return 0.0
    base = value_from_attrs({k: p[k] for k in p.keys()}, p["position"])
    on = on or _today(conn)
    born = datetime.date.fromisoformat(p["birth_date"])
    age = on.year - born.year - ((on.month, on.day) < (born.month, born.day))
    return max(0.0, base * age_factor(age))


def roster(conn, team_id):
    return conn.execute("SELECT player_id, position, status FROM players WHERE team_id=? AND status IN "
                        "('active','injured') ORDER BY player_id", (team_id,)).fetchall()


def counts(conn, team_id, healthy_only=True):
    c = {"F": 0, "D": 0, "G": 0}
    from .discipline import suspended                     # v53: a suspended player cannot dress
    out = suspended(conn) if healthy_only else set()
    for r in roster(conn, team_id):
        if healthy_only and (r["status"] != "active" or r["player_id"] in out):
            continue
        c[group(r["position"])] += 1
    return c


def shortages(conn, team_id):
    c = counts(conn, team_id)
    return [g for g, n in NEED.items() if c[g] < n]


def free_agents(conn, pos_group=None):
    """Free agents (no team, healthy, with ratings) as [(value, player_id, position)] best first."""
    conn.execute("CREATE TABLE IF NOT EXISTS pto (player_id INTEGER PRIMARY KEY, team_id INTEGER, since TEXT, "
                 "status TEXT DEFAULT 'camp', report TEXT)")   # v39: players at a camp on a tryout are spoken for
    rows = conn.execute("SELECT p.player_id, p.position FROM players p JOIN player_attributes a USING (player_id) "
                        "WHERE p.team_id IS NULL AND p.club_id IS NULL AND p.status='active' AND p.player_id NOT IN "
                        "(SELECT player_id FROM draft_rights) AND p.player_id NOT IN (SELECT player_id FROM pto WHERE "
                        "status IN ('camp','report')) ORDER BY p.player_id").fetchall()
    out = [(player_value(conn, r["player_id"]), r["player_id"], r["position"]) for r in rows
           if pos_group is None or group(r["position"]) == pos_group]
    return sorted(out, key=lambda x: (-x[0], x[1]))


def _log(conn, day, typ, pid, frm, to, detail):
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                 "VALUES (?,?,?,?,?,?)", (day, typ, pid, frm, to, detail))


def _sign(conn, team_id, pid, day, detail="signed free agent", aav=None, years=None, check=True, values=None):
    """Sign a free agent. With contracts in play he gets a contract at his asking price unless given terms."""
    from . import contracts as K
    import random as _r
    if aav is None:
        aav = K.asking(conn, pid, "UFA", values)
    if years is None:
        years = K.term_wanted(conn, pid, _r.Random(f"{pid}-{day}"), K.crules(conn)["max_term_new"])
    K.sign_contract(conn, pid, team_id, years, aav, day, check=check, resign=False, detail=detail)
    _log(conn, day, "sign", pid, None, team_id, detail)


def affiliate(conn, team_id):
    """The organisation's AHL club (lowest-level farm club with this parent), or None."""
    r = conn.execute("SELECT t.team_id FROM teams t JOIN leagues l USING (league_id) WHERE t.parent_team_id=? "
                     "ORDER BY COALESCE(l.level, 9), t.team_id LIMIT 1", (team_id,)).fetchone()
    return r["team_id"] if r else None


def _release(conn, team_id, pid, day, detail="released to free agency"):
    conn.execute("UPDATE players SET team_id=NULL, club_id=NULL, status=CASE WHEN status='prospect' THEN 'active' "
                 "ELSE status END WHERE player_id=?", (pid,))
    _log(conn, day, "release", pid, team_id, None, detail)
    from .events import emit, player_name, team_abbr
    emit(conn, "PLAYER_RELEASED", day, f"{team_abbr(conn, team_id)}: {player_name(conn, pid)} {detail}",
         team_id=team_id, player_id=pid)


def send_down(conn, team_id, pid, day, detail="assigned to the minors", waive=True):
    """Keep the player in the organisation but off the NHL roster (status 'prospect'). In the waiver period a
    player who is not exempt goes on waivers first (hs/game/waivers.py); returns "waivers" when he does."""
    if team_id == user_team(conn):                # v39: a no-movement clause keeps him up unless he agrees
        from . import clauses as CL
        if CL.blocks_assignment(conn, pid):
            from .events import player_name
            raise RosterError(f"{player_name(conn, pid)} has a no-movement clause: he cannot be sent down or waived "
                              "without his consent.")
    if waive:
        from . import waivers as W
        if W.needs_waivers(conn, pid, day):
            W.place(conn, team_id, pid, day)
            return "waivers"
    conn.execute("UPDATE players SET status='prospect', club_id=? WHERE player_id=? AND team_id=?",
                 (affiliate(conn, team_id), pid, team_id))
    _log(conn, day, "assign", pid, team_id, team_id, detail)


def call_up(conn, team_id, pid, day, detail="recalled from the minors", check=True):
    _, mx = limits(conn)
    p = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] != team_id or p["status"] != "prospect":
        raise RosterError("That player is not in your system.")
    if check and len(roster(conn, team_id)) >= mx:
        raise RosterError(f"Roster is full ({mx}); send someone down first.")
    if check:
        from . import contracts as K
        c = K.current_contract(conn, pid)
        if c:
            cr = K.crules(conn)
            buried = max(0, c["cap_hit"] - cr["min_salary"] - cr["burial_extra"])
            K.check_cap(conn, team_id, c["cap_hit"] - buried, what="Recalling him")
    conn.execute("UPDATE players SET status='active', club_id=? WHERE player_id=?", (team_id, pid))
    _log(conn, day, "recall", pid, team_id, team_id, detail)


def prospects(conn, team_id, pos_group=None):
    rows = conn.execute("SELECT player_id, position FROM players WHERE team_id=? AND status='prospect' "
                        "ORDER BY player_id", (team_id,)).fetchall()
    out = [(player_value(conn, r["player_id"]), r["player_id"], r["position"]) for r in rows
           if pos_group is None or group(r["position"]) == pos_group]
    return sorted(out, key=lambda x: (-x[0], x[1]))


def sign_free_agent(conn, team_id, player_id, day, aav=None, years=None):
    """User signing. Without terms he signs at his asking price; with terms he accepts only at >= 95% of it."""
    from . import contracts as K
    _, mx = limits(conn)
    p = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (player_id,)).fetchone()
    if p is None:
        raise RosterError("No such player.")
    if p["team_id"] is not None:
        raise RosterError("That player is not a free agent.")
    if p["status"] != "active":
        raise RosterError("That player is injured and cannot be signed.")
    if len(roster(conn, team_id)) >= mx:
        raise RosterError(f"Roster is full ({mx}); release someone first.")
    ask = K.asking(conn, player_id, "UFA")
    if aav is not None and aav < 0.95 * ask:
        raise RosterError(f"He wants at least ${ask:,.0f} a year.")
    _sign(conn, team_id, player_id, day, aav=aav if aav is not None else ask, years=years)


def release(conn, team_id, player_id, day):
    """Release a player; a remaining contract is bought out (cap charges for twice the remaining term)."""
    from . import contracts as K
    mn, _ = limits(conn)
    p = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (player_id,)).fetchone()
    if p is None or p["team_id"] != team_id:
        raise RosterError("That player is not on this team.")
    if p["status"] != "prospect" and len(roster(conn, team_id)) <= mn:
        raise RosterError(f"Roster is at the minimum ({mn}); sign someone first.")
    cost = K.buyout(conn, team_id, player_id, day)
    _release(conn, team_id, player_id, day, f"bought out (${cost:,.0f} total)" if cost else "released to free agency")
    return cost


def trade(conn, team_a, give_a, team_b, give_b, day, retain=None):
    """team_a gives give_a to team_b and receives give_b. retain = {player_id: pct} kept by the team giving him up.
    Checks rosters, the cap after the trade, retention limits and no-trade clauses. Changes nothing on failure."""
    from . import contracts as K
    retain = retain or {}
    cr = K.crules(conn)
    mn, mx = limits(conn)
    owner = {}
    for team, give in ((team_a, give_a), (team_b, give_b)):
        for pid in give:
            r = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()
            if r is None or r["team_id"] != team:
                raise RosterError(f"Player {pid} is not on the team giving him up.")
            owner[pid] = team
    if not give_a and not give_b:
        raise RosterError("Nothing to trade.")
    na = len(roster(conn, team_a)) - len(give_a) + len(give_b)
    nb = len(roster(conn, team_b)) - len(give_b) + len(give_a)
    for n, t in ((na, team_a), (nb, team_b)):
        if n > mx:
            raise RosterError(f"Trade would put a team over the roster maximum ({n} > {mx}).")
        if n < mn:
            raise RosterError(f"Trade would put a team under the roster minimum ({n} < {mn}).")
    contracts = {pid: K.current_contract(conn, pid) for pid in list(give_a) + list(give_b)}
    for pid, pct in retain.items():
        if pid not in owner:
            raise RosterError("Salary can only be retained on a player in the trade.")
        if not 0 < pct <= cr["retention_max_pct"]:
            raise RosterError(f"Retention must be between 0 and {cr['retention_max_pct']:.0%}.")
        if contracts[pid] is None:
            raise RosterError("That player has no contract to retain.")
        if K.retained_share(conn, contracts[pid]["contract_id"]) + pct > cr["retention_max_pct"] + 1e-9:
            raise RosterError("That contract already carries the maximum retention.")
        held = conn.execute("SELECT COUNT(*) FROM retained r JOIN contracts c USING (contract_id) WHERE r.team_id=? "
                            "AND c.start_year+c.years>?", (owner[pid], K.season_year(conn))).fetchone()[0]
        if held >= cr["retention_max_contracts"]:
            raise RosterError(f"A team may retain on at most {cr['retention_max_contracts']} contracts.")
    from . import clauses as CL                    # v39: clauses (NTC, NMC, modified lists) ask for his consent
    for pids, to in ((give_a, team_b), (give_b, team_a)):
        for pid in pids:
            why = CL.consent(conn, pid, owner[pid], to)
            if why:
                raise RosterError(why + ".")
    if cr["cap_ceiling"]:
        def moved(pids, keep):
            tot = 0
            for pid in pids:
                c = contracts[pid]
                if c:
                    tot += round(c["cap_hit"] * (1 - K.retained_share(conn, c["contract_id"])))
            return tot
        out_a, out_b = moved(give_a, True), moved(give_b, True)
        ret_a = sum(round(contracts[p]["cap_hit"] * retain[p]) for p in give_a if p in retain)
        ret_b = sum(round(contracts[p]["cap_hit"] * retain[p]) for p in give_b if p in retain)
        K.check_cap(conn, team_a, out_b - ret_b, removing=out_a - ret_a, what="The trade")
        K.check_cap(conn, team_b, out_a - ret_a, removing=out_b - ret_b, what="The trade (for them)")
    for pid, pct in retain.items():
        conn.execute("INSERT INTO retained (contract_id, team_id, pct) VALUES (?,?,?)",
                     (contracts[pid]["contract_id"], owner[pid], pct))
    for pids, frm, to in ((give_a, team_a, team_b), (give_b, team_b, team_a)):
        for pid in pids:
            transfer(conn, pid, frm, to, day, retain.get(pid, 0))


def transfer(conn, pid, frm, to, day, retained=0):
    """Move one player (and his contract) between clubs; no checks (callers check rosters, cap and clauses)."""
    from . import contracts as K
    conn.execute("UPDATE players SET team_id=?, club_id=CASE WHEN status='prospect' THEN ? ELSE ? END "
                 "WHERE player_id=?", (to, affiliate(conn, to), to, pid))
    conn.execute("UPDATE contracts SET team_id=? WHERE player_id=? AND start_year+years>?",
                 (to, pid, K.season_year(conn)))
    _log(conn, day, "trade", pid, frm, to, "traded" + (f" ({retained:.0%} retained)" if retained else ""))
    from .events import emit, player_name, team_abbr
    emit(conn, "PLAYER_TRADED", day, f"{player_name(conn, pid)} traded from {team_abbr(conn, frm)} to "
         f"{team_abbr(conn, to)}", team_id=frm, other_team_id=to, player_id=pid, importance=2, retained=retained)


def trade_value(value):
    """Convex trade currency (see module docstring)."""
    return TV50 * (max(value - REPLACEMENT, 0.0) / (50.0 - REPLACEMENT)) ** TRADE_EXPONENT


CONTRACT_WEIGHT = 3.0       # trade-value points per $1M a year of surplus (market value minus cap cost; 15 before v39)
CONTRACT_YEARS = 3          # years of a contract that count in a trade valuation


def contract_adjustment(conn, pid, retained_pct=0.0, values=None):
    """Trade-value points for a contract: positive when he is paid below market (after any retention), counted for
    up to CONTRACT_YEARS remaining seasons. Zero when there is no salary cap."""
    from . import contracts as K
    if not K.crules(conn)["cap_ceiling"]:
        return 0.0
    c = K.current_contract(conn, pid)
    if c is None:
        return 0.0
    years_left = min(CONTRACT_YEARS, c["start_year"] + c["years"] - K.season_year(conn))
    cost = c["cap_hit"] * (1 - K.retained_share(conn, c["contract_id"]) - retained_pct)
    return CONTRACT_WEIGHT * (K.market_aav(conn, pid, values) - cost) / 1_000_000 * years_left


def evaluate_trade(conn, a, give_a, b, give_b, retain=None):
    """AI view; b is the AI team. Each player is worth trade_value(player_value) plus a contract adjustment (cheap
    contracts and retained salary add value, overpaid ones subtract). b accepts when what it receives is worth at
    least 105% of what it gives (goalies it receives get a 15% premium if it has fewer than 3 goalies)."""
    from . import contracts as K
    retain = retain or {}
    values = K.league_values(conn) if K.crules(conn)["cap_ceiling"] else None
    if not give_a and not give_b:
        return False, "Nothing on the table."
    goalies_b = sum(1 for r in roster(conn, b) if r["position"] == "G")
    recv = 0.0
    for pid in give_a:
        v = trade_value(player_value(conn, pid))
        pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()["position"]
        recv += v * (1.15 if pos == "G" and goalies_b < 3 else 1.0) + contract_adjustment(conn, pid, retain.get(pid, 0), values)
    given = sum(trade_value(player_value(conn, pid)) + contract_adjustment(conn, pid, retain.get(pid, 0), values)
                for pid in give_b)
    if recv >= 1.05 * given:
        return True, f"Trade looks fair (they get {recv:.0f}, give {given:.0f})."
    return False, f"Not enough value (they would get {recv:.0f}, give {given:.0f}; they want at least {1.05 * given:.0f})."


def _lowest_healthy(conn, team_id, only_groups=None):
    cands = []
    for r in roster(conn, team_id):
        if r["status"] != "active" or (only_groups and group(r["position"]) not in only_groups):
            continue
        cands.append((player_value(conn, r["player_id"]), r["player_id"], r["position"]))
    if not cands:
        return None
    from .state import user_team
    if team_id != user_team(conn):
        # AI clubs judge their depth the way the league does (ratings and NHL production), and keep non-exempt
        # players off waivers when they can
        from . import contracts as K
        from . import waivers as W
        mv = K.day_values(conn)
        cands = sorted((mv.value(pid), pid, pos) for _, pid, pos in cands)
        return W.ai_send_down_choice(conn, team_id, cands)
    cands.sort()
    return cands[0]


def make_room(conn, team_id, day, keep_group):
    """Send down the lowest-value healthy player outside keep_group (prefer groups above their minimum)."""
    c = counts(conn, team_id)
    surplus = [g for g in NEED if g != keep_group and c[g] > NEED[g]]
    victim = _lowest_healthy(conn, team_id, surplus) or _lowest_healthy(conn, team_id, [g for g in NEED if g != keep_group])
    if victim is None:
        raise RosterError("No one can be moved to make room.")
    send_down(conn, team_id, victim[1], day, "assigned to the minors to make room")
    return victim[1]


def _affordable_fa(conn, team_id, g, values):
    """Best free agent at group g whose asking price fits under the cap; None if none fits."""
    from . import contracts as K
    room = K.cap_room(conn, team_id, K.signing_year(conn))
    for v, pid, pos in free_agents(conn, g):
        if room is None or K.asking(conn, pid, "UFA", values) <= room:
            return pid
    return None


def _emergency_from_world(conn, team_id, g):
    """When no free agent exists at a position, the best player at it with no NHL contract or rights, from the
    club's own affiliate first, then any lower-league club (the real-life emergency signing)."""
    rows = conn.execute("SELECT p.player_id, p.position, p.club_id FROM players p WHERE p.team_id IS NULL AND "
                        "p.status='active' AND p.club_id IS NOT NULL AND p.player_id NOT IN "
                        "(SELECT player_id FROM draft_rights) AND p.birth_date <= ? ORDER BY p.player_id",
                        (f"{_today(conn).year - 20}-12-31",)).fetchall()
    aff = affiliate(conn, team_id)
    best = None
    for r in rows:
        if group(r["position"]) != g:
            continue
        key = (r["club_id"] == aff, player_value(conn, r["player_id"]), -r["player_id"])
        if best is None or key > best[0]:
            best = (key, r["player_id"])
    return best[1] if best else None


def ensure_dressable(conn, team_id, day):
    """Fill each short position: recall the best player from the team's own system, else sign the best affordable
    free agent, else (emergency) the cheapest one regardless of the cap. Returns list of player ids added."""
    from . import contracts as K
    _, mx = limits(conn)
    added, values = [], None
    for g in shortages(conn, team_id):
        while counts(conn, team_id)[g] < NEED[g]:
            if len(roster(conn, team_id)) >= mx:
                make_room(conn, team_id, day, g)
            own = prospects(conn, team_id, g)
            if own:
                call_up(conn, team_id, own[0][1], day, "recalled (roster need)", check=False)
                added.append(own[0][1])
                continue
            values = values if values is not None else K.league_values(conn)
            if team_id == user_team(conn):
                # v39 (#17): your club, short and nobody to recall: the best free agent who will sign for the league
                # minimum (one year), so the game can be played; you hear about it in the inbox
                mn_sal = K.crules(conn)["min_salary"]
                cheap = [x for x in free_agents(conn, g) if K.asking(conn, x[1], "UFA", values) <= mn_sal * 1.05]
                if cheap:
                    pid = max(cheap, key=lambda x: (x[0], -x[1]))[1]
                    _sign(conn, team_id, pid, day, "signed at the league minimum (roster short)", aav=mn_sal, years=1,
                          check=False)
                    from .events import player_name as _pn
                    add_message(conn, day, "Emergency signing", f"You were short at {({'F': 'forward', 'D': 'defence', 'G': 'goal'})[g]} "
                                f"with nobody to recall, so hockey operations signed {_pn(conn, pid)}, the best free agent "
                                f"willing to sign for the league minimum (one year, ${mn_sal:,.0f}), so tonight's game "
                                "can go ahead. You can release or trade him like anyone else.",
                                sender="Hockey operations", actions=[dict(label=f"Open {_pn(conn, pid)}", href=f"#player/{pid}"),
                                                                    dict(label="Free agents", href="#freeagents")])
                    added.append(pid)
                    continue
            pid = _affordable_fa(conn, team_id, g, values)
            if pid is not None:
                try:
                    _sign(conn, team_id, pid, day, "signed free agent (roster need)", values=values)
                except RosterError:                  # contract limit: a one-year emergency deal instead
                    _sign(conn, team_id, pid, day, "signed free agent (emergency)", aav=K.crules(conn)["min_salary"],
                          years=1, check=False)
            else:
                fa = free_agents(conn, g)
                if not fa:
                    pid = _emergency_from_world(conn, team_id, g)
                    if pid is None:
                        break
                    _sign(conn, team_id, pid, day, "signed on an emergency contract from a lower league",
                          aav=K.crules(conn)["min_salary"], years=1, check=False)
                    added.append(pid)
                    continue
                pid = min(fa, key=lambda x: (K.asking(conn, x[1], "UFA", values), x[1]))[1]
                _sign(conn, team_id, pid, day, "signed free agent (emergency)", aav=K.crules(conn)["min_salary"],
                      years=1, check=False)
            added.append(pid)
    return added


PROMOTE_MARGIN = 2.0
YOUNG_PROMOTE_AGE = 22        # clubs give young, high-ceiling players a spot when they are close, not clearly better
YOUNG_PROMOTE_POTENTIAL = 10.6
YOUNG_PROMOTE_MARGIN = -2.5


def _promote_margin(conn, pid):
    r = conn.execute("SELECT p.birth_date, d.potential FROM players p LEFT JOIN player_dev d USING (player_id) "
                     "WHERE p.player_id=?", (pid,)).fetchone()
    if r is None or r[1] is None:
        return PROMOTE_MARGIN
    age = _today(conn).year - int(r[0][:4])
    if age <= YOUNG_PROMOTE_AGE and r[1] >= YOUNG_PROMOTE_POTENTIAL:
        return YOUNG_PROMOTE_MARGIN
    return PROMOTE_MARGIN


def ai_promote(conn, team_id, day):
    """Give a roster spot to a prospect in the system who is now clearly better than the weakest player at his
    position group (value margin PROMOTE_MARGIN), or, for a high-ceiling player 22 or younger, close to him
    (YOUNG_PROMOTE_MARGIN): clubs make room for young players they expect to grow. Returns number of swaps."""
    swaps = 0
    for g in ("F", "D", "G"):
        for _ in range(3):
            own = prospects(conn, team_id, g)
            worst = _lowest_healthy(conn, team_id, [g])
            if not own or worst is None:
                break
            cand = max(own, key=lambda x: (x[0] - _promote_margin(conn, x[1]), -x[1]))
            if cand[0] < worst[0] + _promote_margin(conn, cand[1]):
                break
            send_down(conn, team_id, worst[1], day, "assigned to the minors (lost his spot)")
            call_up(conn, team_id, cand[1], day, "promoted from the system", check=False)
            swaps += 1
    return swaps


def ai_manage(conn, team_id, day, rng):
    """(a) fill positional needs, (b) send down extras on an oversized roster, (c) 2%/day sign a clearly better
    affordable free agent and send down the player he replaces. Returns number of moves made."""
    from . import contracts as K
    moves = len(ensure_dressable(conn, team_id, day))
    _, mx = limits(conn)
    while len(roster(conn, team_id)) > mx:
        c = counts(conn, team_id)
        low = _lowest_healthy(conn, team_id, [g for g in NEED if c[g] > NEED[g]]) or _lowest_healthy(conn, team_id)
        if low is None:
            break
        send_down(conn, team_id, low[1], day, "assigned to the minors (roster over limit)")
        moves += 1
    if rng.random() < UPGRADE_PROB:
        fa = [x for x in free_agents(conn) if group(x[2]) != "G"]
        if fa:
            v, pid, pos = fa[0]
            worst = _lowest_healthy(conn, team_id, [group(pos)])
            if worst and v >= worst[0] + UPGRADE_MARGIN:
                room = K.cap_room(conn, team_id, K.signing_year(conn))
                if room is None or K.asking(conn, pid, "UFA") <= room:
                    try:
                        K.check_contract_limit(conn, team_id, K.signing_year(conn))
                    except RosterError:
                        return moves
                    send_down(conn, team_id, worst[1], day, "assigned to the minors (replaced)")
                    _sign(conn, team_id, pid, day, "signed free agent (upgrade)")
                    moves += 2
    return moves
