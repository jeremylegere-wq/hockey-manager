"""The v39 trade model: how hard a player is to move, how much a club needs one, and what picks, packages and
retained salary are worth. docs/TRADES.md "How the market decides (v39)" has the formulas and where each number
came from. Used by hs.game.trades (AI clubs) and hs.game.gm_trades (your trades), so both sides of the table work
the same way.

Competitive state S (0 hard rebuild .. 1 all-in contender)
  S = 1 - (rank - 1) / (n - 1), rank by points percentage once clubs have played 10 games (paper strength before).

Need score N (0..100), per club and position group (F, D, G)
  roster deficit   D_r = sum_i w_i * max(0, target_i - current_i) / (sum_i w_i * sd)
                   slot i of the depth chart (F 12, D 6, G 2) with weights 1.0/0.75/0.5/0.25 by line (D 1.0/0.7/0.4,
                   G 1.0/0.3); target_i = the 65th percentile of every club's i-th best player (a playoff club's
                   depth); sd = spread of the group's values. Players out for 3+ weeks do not count.
  pipeline deficit D_p = max(0, 1 - sum_j readiness_j * max(0, (potential_j - 10) / 5) / target)
                   prospects at the group; readiness 0.9 at 22+, 0.7 at 21, 0.5 at 20, 0.3 younger;
                   target F 2.5, D 1.5, G 0.8
  urgency          U = 0.25 for each top-lineup player out 3+ weeks (0.4 in the deadline rush)
  N = 100 * clamp(alpha * D_r + 0.3 * beta * D_p + U, 0, 1),  alpha = 0.2 + 0.8 S,  beta = 1 - 0.8 S

Friction F (0..100): how hard a player is to pry loose
  q = (value - group mean) / group sd among NHL regulars
  F = 30 q^2 (q > 0) * (1 + 0.12 (years left - 1)) * (0.8 + 2 * cap share)
      x0.7 on an expiring deal in season (a rental), +40 NMC / +30 NTC / +10 modified, +15 captain / +8 alternate,
      x1.25 on a contender, x0.7 on a seller, x0.6 in the offseason, x0.3 if he asked out; capped at 100.
  A club pursues a player only if its need at his position is at least his friction (N >= F), and the seller wants
  1.05 + F / 100 of his value back.

Picks: an offset power law (our refinement of a pure p^-gamma curve, which is too flat at the bottom and unbounded at
the top):  V(p) = 13960 * (p + 14)^-1.5,  p = 32 (round - 1) + slot (worst club first)
  1st overall 240, 16th 85, 32nd 45, mid 2nd 29, mid 3rd 15, mid 4th 10, 7th 4.
  This year's slot follows the standings; for later drafts it regresses to mid-round (half in a year, three
  quarters in two) and is discounted 15% a year; a future 1st of a weak club carries up to 30% for the lottery.

Packages: the pieces a club receives (or gives) are added best first at 100%, 80%, 64%... so four nickels do not buy
a quarter.

Retained salary is an asset the retaining club gives: 10 points per $1M of cap it keeps paying (this season's
remaining share plus later seasons), times 1 + (15 - its cap room in $M) / 5 (1..3): clubs with room broker cap
cheaply, clubs near the ceiling barely at all.
"""
from __future__ import annotations

import datetime
import statistics

SLOT_W = {"F": [1.0] * 3 + [0.75] * 3 + [0.5] * 3 + [0.25] * 3, "D": [1.0, 1.0, 0.7, 0.7, 0.4, 0.4], "G": [1.0, 0.3]}
TARGET_PCT = 0.65
PIPE_TARGET = {"F": 2.5, "D": 1.5, "G": 0.8}
URGENCY, URGENCY_RUSH, LONG_INJURY_DAYS = 0.25, 0.4, 21
PIPE_WEIGHT = 0.3

F_Q, F_TERM, F_CAP0, F_CAP = 30.0, 0.12, 0.8, 2.0
F_RENTAL, F_NMC, F_NTC, F_MNTC, F_C, F_A = 0.7, 40.0, 30.0, 10.0, 15.0, 8.0
F_POSTURE = {"contender": 1.25, "middle": 1.0, "seller": 0.7}
F_OFFSEASON, F_REQUEST, F_MAX = 0.6, 0.3, 100.0
ACCEPT = 1.05

PICK_A, PICK_C, PICK_G = 13960.0, 14.0, 1.5
PICK_DISCOUNT, LOTTERY = 0.15, 0.3
DECAY = 0.8
RET_RATE, RET_ROOM = 10.0, 15.0


# ---------------------------------------------------------------- picks
def pick_curve(p):
    return PICK_A * (max(1.0, p) + PICK_C) ** -PICK_G


def pick_value(slot_worst_first, n_teams, year, this_year, rnd, s_owner=None):
    """Value of a pick on the trade scale. slot_worst_first: the original club's place, worst first (None: mid)."""
    n = max(2, n_teams)
    mid = (n + 1) / 2
    cur = slot_worst_first if slot_worst_first is not None else mid
    y = max(0, year - this_year)
    slot = cur if y == 0 else (0.5 * cur + 0.5 * mid if y == 1 else 0.25 * cur + 0.75 * mid)
    slot = slot * 32.0 / n                                   # keep the curve on a 32-club scale
    v = pick_curve(32 * (rnd - 1) + slot) / (1 + PICK_DISCOUNT) ** y
    if rnd == 1 and y > 0 and s_owner is not None:
        v *= 1 + LOTTERY * (1 - s_owner)
    return v


# ---------------------------------------------------------------- packages
def package_value(values):
    """Best piece at 100%, the next at 80%, then 64%...: consolidated talent is worth more than the same total spread
    over several pieces."""
    return sum(v * DECAY ** i for i, v in enumerate(sorted((max(0.0, v) for v in values), reverse=True)))


# ---------------------------------------------------------------- state and need
def comp_state(rank, n):
    return 1.0 - (rank - 1) / max(1, n - 1)


def long_injured(conn, day):
    """{player_id} out at least three more weeks."""
    cut = (datetime.date.fromisoformat(day) + datetime.timedelta(days=LONG_INJURY_DAYS)).isoformat()
    return {r[0] for r in conn.execute("SELECT i.player_id FROM injuries i JOIN players p USING (player_id) "
                                       "WHERE p.status='injured' AND i.expected_return>=? AND i.start_date<=?",
                                       (cut, day))}


def readiness(age):
    return 0.9 if age >= 22 else 0.7 if age == 21 else 0.5 if age == 20 else 0.3


def need_scores(m, rush=False):
    """{team: {group: N}} for every club in the Market."""
    from . import roster as R
    conn = m.conn
    out_long = long_injured(conn, m.day)
    groups = {g: {} for g in SLOT_W}
    for t in m.all_teams:
        for g in SLOT_W:
            groups[g][t] = []
        for r in R.roster(conn, t):
            pid = r["player_id"]
            if pid in out_long:
                continue
            groups[R.group(r["position"])][t].append(m.values.get(pid, 0.0))
    targets, sds = {}, {}
    for g, w in SLOT_W.items():
        cols = []
        for i in range(len(w)):
            col = sorted((sorted(v, reverse=True) + [0.0] * len(w))[i] for v in groups[g].values())
            cols.append(col[min(len(col) - 1, int(TARGET_PCT * len(col)))] if col else 0.0)
        targets[g] = cols
        allv = [x for v in groups[g].values() for x in v]
        sds[g] = statistics.pstdev(allv) if len(allv) > 2 else 1.0
    pipe = {t: {g: 0.0 for g in SLOT_W} for t in m.all_teams}
    y = m.season
    for r in conn.execute("SELECT p.team_id, p.position, p.birth_date, d.potential FROM players p JOIN player_dev d "
                          "USING (player_id) WHERE p.status='prospect'"):
        if r[0] in pipe and r[3] is not None:
            pipe[r[0]][R.group(r[1])] += readiness(y - int(r[2][:4])) * max(0.0, (r[3] - 10) / 5.0)
    hurt = {t: 0 for t in m.all_teams}
    for pid in out_long:
        t = m.owner.get(pid)
        if t in hurt and pid in m.top_lineup.get(t, ()):
            hurt[t] += 1
    out = {}
    for t in m.all_teams:
        S = m.S[t]
        a, b = 0.2 + 0.8 * S, 1.0 - 0.8 * S
        out[t] = {}
        for g, w in SLOT_W.items():
            cur = sorted(groups[g][t], reverse=True) + [0.0] * len(w)
            dr = sum(wi * max(0.0, targets[g][i] - cur[i]) for i, wi in enumerate(w)) / (sum(w) * max(0.5, sds[g]))
            dp = max(0.0, 1.0 - pipe[t][g] / PIPE_TARGET[g])
            u = (URGENCY_RUSH if rush else URGENCY) * sum(
                1 for pid in out_long if m.owner.get(pid) == t and pid in m.top_lineup.get(t, ())
                and m.group_of.get(pid) == g)
            out[t][g] = 100.0 * min(1.0, max(0.0, a * dr + PIPE_WEIGHT * b * dp + u))
    m.slot_targets = targets
    return out


def role_of(m, team, value, g):
    """Where a player of this value would slot on this club: 1.0 top line/pair, then 0.75, 0.5, 0.25."""
    mine = sorted((v for v in m.groups[team][g]), reverse=True)
    better = sum(1 for v in mine if v > value)
    per = {"F": 3, "D": 2, "G": 1}[g]
    return max(0.25, 1.0 - 0.25 * (better // per))


# ---------------------------------------------------------------- friction
def friction(m, pid, team=None, offseason=False):
    from . import contracts as K
    from . import clauses as CL
    conn = m.conn
    g = m.group_of.get(pid)
    team = team if team is not None else m.owner.get(pid)
    mean, sd = m.gstats.get(g, (50.0, 5.0))
    q = (m.values.get(pid, mean) - mean) / max(0.5, sd)
    f = F_Q * q * q if q > 0 else 0.0
    c = K.current_contract(conn, pid)
    if c is not None and f > 0:
        left = c["start_year"] + c["years"] - m.season
        cap = K.crules(conn).get("cap_ceiling") or 0
        f *= 1 + F_TERM * max(0, left - 1)
        if cap:
            f *= F_CAP0 + F_CAP * c["cap_hit"] / cap
        if left <= 1 and not offseason:
            f *= F_RENTAL
    cl = CL.of(conn, pid)
    if cl:
        f += {"NMC": F_NMC, "NTC": F_NTC, "MNTC": F_MNTC}[cl["kind"]]
    role = m.leaders.get(pid)
    f += F_C if role == "C" else F_A if role == "A" else 0.0
    f *= F_POSTURE.get(m.posture.get(team, "middle"), 1.0)
    if offseason:
        f *= F_OFFSEASON
    if pid in m.requests:
        f *= F_REQUEST
    return min(F_MAX, f)


# ---------------------------------------------------------------- retention
def retention_value(conn, team, pid, share, day):
    """What retaining `share` of his cap hit costs the retaining club, on the trade scale."""
    from . import contracts as K
    if not share:
        return 0.0
    c = K.current_contract(conn, pid)
    if c is None:
        return 0.0
    y = K.season_year(conn)
    left = c["start_year"] + c["years"] - y                     # seasons including this one
    frac = 1.0
    if K.season_state(conn) == "regular_season":
        r = conn.execute("SELECT MIN(game_date), MAX(game_date) FROM games WHERE game_type='RS' AND season_id="
                         "(SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1)").fetchone()
        if r and r[0]:
            start, end = (datetime.date.fromisoformat(x[:10]) for x in r)
            d = datetime.date.fromisoformat(day)
            frac = max(0.05, min(1.0, (end - d).days / max(1, (end - start).days)))
    years = frac + max(0, left - 1)
    cap = K.crules(conn).get("cap_ceiling") or 0
    room = (cap - K.payroll(conn, team)) / 1e6 if cap else RET_ROOM
    mult = min(3.0, 1.0 + max(0.0, RET_ROOM - room) / 5.0)
    return RET_RATE * c["cap_hit"] * share / 1e6 * years * mult


# ---------------------------------------------------------------- protected picks (v39)
PROTECT_OPTIONS = (3, 5, 10)
SLOT_SD = {0: 1.5, 1: 8.0, 2: 10.0}


def p_inside(slot, top, years_out):
    """Chance a pick lands in the protected range (slot worst-first; lottery noise this year, more spread later)."""
    sd = SLOT_SD.get(years_out, 10.0)
    return statistics.NormalDist(slot, sd).cdf(top + 0.5)


def protected_value(slot_worst_first, n_teams, year, this_year, rnd, top, s_owner=None):
    """A top-`top` protected pick: if it lands in the range the original club keeps it and next year's pick (same
    round, unprotected) goes instead. Value = P(out) * V(pick, slot outside the range) + P(in) * V(next year)."""
    if not top:
        return pick_value(slot_worst_first, n_teams, year, this_year, rnd, s_owner)
    n = max(2, n_teams)
    mid = (n + 1) / 2
    cur = slot_worst_first if slot_worst_first is not None else mid
    y = max(0, year - this_year)
    slot = cur if y == 0 else (0.5 * cur + 0.5 * mid if y == 1 else 0.25 * cur + 0.75 * mid)
    p = p_inside(slot, top, y)
    out_slot = max(slot, top + 3)
    v_out = pick_value(out_slot, n_teams, year, this_year, rnd)
    v_in = pick_value(None, n_teams, year + 1, this_year, rnd, s_owner)
    return (1 - p) * v_out + p * v_in


# ---------------------------------------------------------------- v41: conditional picks
def p_condition(kind, rank_best_first, n, spots, season_frac):
    """Chance a club makes the playoffs ('playoffs') or wins a round ('round2'), from where it stands and how much of
    the season is left (the spread narrows as games are played)."""
    sd = 1.5 + 6.0 * (1 - max(0.0, min(1.0, season_frac)))
    p = statistics.NormalDist(rank_best_first, sd).cdf(spots + 0.5)
    if kind == "round2":
        half = max(1.0, (n - 1) / 2)
        p *= max(0.15, min(0.85, 0.5 + 0.35 * ((n + 1) / 2 - rank_best_first) / half))
    return max(0.0, min(1.0, p))
