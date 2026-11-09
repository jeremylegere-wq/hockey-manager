"""Draft-floor trading: picks as a currency whose price moves with the board.

Pick value chart: a points value for every pick, pick 1 = 1000, 32 = 300, a mid 3rd-rounder ~100, a 5th ~38,
the last pick 12 (log-linear between the anchors below). Future picks are valued at the middle of their round,
discounted 15% (clubs overvalue the present).

Live board multiplier: when a player the league had rated well above the current slot is still on the board,
the slot is worth more: up to +50% (M_live = 1 + 0.5 * min(1, slide / 10)).

Three modules (from the brief and its decision tree):
  A  Moving up. A club whose top target (on its own board) is clearly better than anyone it expects to be left at
     its next pick tries to jump the clubs in between. It offers its next pick plus later picks (this draft first,
     then next year's) to cover the chart gap, plus half the slot's live-board spike (value x (M_live - 1)). If it
     is desperate (the gap on its board is large) the seller adds a 25% desperation premium on the gap. The seller only moves down if its
     own top choice is not much better than what it expects at the lower pick (its target is gone or similar
     players remain).
  B  Consolidation. A club holding more than 9 picks bundles three late picks (rounds 5-7) into one higher pick
     from a club with few, and only if its contract count leaves room under the 50-contract limit for draftees.
  C  Blockbuster player-for-picks deals run through hs.game.trades on draft day (see docs/TRADES.md).

The user's club is never traded with automatically. `pickswap` lets the user propose pick deals on draft day;
the AI prices them with the same chart (no premium charged to the user, but the live-board multiplier applies).
"""
from __future__ import annotations

import math
import random

from . import contracts as K
from .events import emit, team_abbr
from .state import get_state, user_team

ANCHORS = [(1, 1000), (2, 900), (3, 820), (5, 700), (10, 520), (16, 420), (32, 300), (48, 200), (64, 140),
           (80, 100), (96, 75), (128, 45), (160, 28), (192, 18), (224, 12)]
FUTURE_DISCOUNT = 0.85
LIVE_MAX, LIVE_SLIDE = 0.5, 10
LIVE_SHARE = 0.5              # share of the live-board spike the club moving down can charge
DESPERATION = 1.25
MOVE_UP_GAP = 0.45            # a club's top target must beat its expected next-pick option by this (overall points)
DESPERATE_GAP = 0.8
SELLER_TOLERANCE = 0.35       # the seller moves down if its own loss on its board is below this (and below
SELLER_SHARE = 0.6            # this share of what the buyer gains)
MAX_PER_ROUND = {1: 4, 2: 4, 3: 2, 4: 2, 5: 1, 6: 1, 7: 1}
OVERPAY = 2.5                 # a buyer will not hand over more than 2.5x the chart gap (or the gap + 40 points)
CONSOLIDATE_AT = 9


def chart(n):
    """Points value of overall pick n (1-based)."""
    if n <= ANCHORS[0][0]:
        return float(ANCHORS[0][1])
    for (a, va), (b, vb) in zip(ANCHORS, ANCHORS[1:]):
        if n <= b:
            t = (n - a) / (b - a)
            return math.exp(math.log(va) + t * (math.log(vb) - math.log(va)))
    return float(ANCHORS[-1][1])


def future_value(rnd, n_teams=32):
    return chart((rnd - 1) * n_teams + n_teams // 2) * FUTURE_DISCOUNT


def live_multiplier(slide):
    return 1 + LIVE_MAX * min(1.0, max(0, slide) / LIVE_SLIDE)


def _year_picks(conn, year, team_id, after=0):
    return [r[0] for r in conn.execute("SELECT overall FROM draft_picks WHERE draft_year=? AND team_id=? AND "
                                       "player_id IS NULL AND overall>? ORDER BY overall", (year, team_id, after))]


def _future_picks(conn, year, team_id):
    from .trades import ensure_tables, pick_owner
    ensure_tables(conn)
    teams = [r[0] for r in conn.execute("SELECT team_id FROM teams WHERE league_id=(SELECT league_id FROM teams "
                                        "WHERE team_id=?)", (team_id,))]
    return [(year + 1, rnd, t) for rnd in range(1, 5) for t in teams if pick_owner(conn, year + 1, rnd, t) == team_id]


def _move_future(conn, pick, to, day):
    y, rnd, orig = pick
    conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, orig, to, f"traded {day}"))


def _label(conn, p, owner=None):
    if isinstance(p, int):
        return f"#{p}"
    y, rnd, orig = p
    nth = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd, f"{rnd}th")
    return f"{y} {nth}" + ("" if orig == owner else f" ({team_abbr(conn, orig)})")


def _value(p, n_teams):
    return chart(p) if isinstance(p, int) else future_value(p[1], n_teams)


def _package(conn, year, team_id, first, need, n_teams):
    """Cheapest set of the club's later picks (this draft, then next year's 1st-4th) worth at least `need` on top
    of `first`. Returns (picks, total value) or None."""
    have = [p for p in _year_picks(conn, year, team_id, after=first)] + _future_picks(conn, year, team_id)
    have.sort(key=lambda p: _value(p, n_teams))
    for p in have:                                    # one pick that covers it
        if _value(p, n_teams) >= need:
            return [p], _value(p, n_teams)
    tot, out = 0.0, []
    for p in sorted(have, key=lambda p: -_value(p, n_teams)):
        if tot >= need:
            break
        out.append(p)
        tot += _value(p, n_teams)
        if len(out) == 3:
            break
    return (out, tot) if tot >= need else None


def try_move_up(conn, year, slot, owner, board, available, day, rng):
    """Before `owner` picks at `slot`: does another AI club trade up to take this pick? Returns a line or None.

    board: the draft's _Board (club views); available: prospects still on the board."""
    me = user_team(conn)
    if owner == me or not available:
        return None
    n_teams = conn.execute("SELECT COUNT(DISTINCT team_id) FROM draft_picks WHERE draft_year=? AND round=1",
                           (year,)).fetchone()[0] or 32
    upcoming = conn.execute("SELECT overall, team_id FROM draft_picks WHERE draft_year=? AND player_id IS NULL AND "
                            "overall>? ORDER BY overall LIMIT 20", (year, slot)).fetchall()
    top = min(available, key=lambda x: x.get("expected_slot", slot))
    slide = max(0, slot - top.get("expected_slot", slot))     # a player the league rated higher is still here
    m_live = live_multiplier(slide)
    seller_style, seller_view = board.proj(owner)
    s_ranked = sorted((seller_view[x["pid"]] for x in available), reverse=True)
    for k, row in enumerate(upcoming):
        buyer, their = row["team_id"], row["overall"]
        if buyer in (owner, me):
            continue
        _, view = board.proj(buyer)
        ranked = sorted((view[x["pid"]] for x in available), reverse=True)
        between = k + 1                                  # picks made before the buyer's own turn
        if len(ranked) <= between:
            continue
        gap = ranked[0] - ranked[between]
        if gap < MOVE_UP_GAP:
            continue
        # would the seller drop to the buyer's slot? only if it loses little on its own board
        s_between = min(len(s_ranked) - 1, between)
        if s_ranked[0] - s_ranked[s_between] > min(SELLER_TOLERANCE, SELLER_SHARE * gap):
            continue
        # the chart gap, plus the desperation premium on that gap, plus part of the slot's live-board spike
        extra = ((chart(slot) - chart(their)) * (DESPERATION if gap >= DESPERATE_GAP else 1.0)
                 + LIVE_SHARE * chart(slot) * (m_live - 1))
        pack = _package(conn, year, buyer, their, extra, n_teams) if extra > 0 else ([], 0.0)
        if pack is None or (extra > 0 and pack[1] > max(OVERPAY * extra, extra + 40)):
            continue
        if rng.random() > 0.6:                           # not every phone call ends in a deal
            continue
        extras, _ = pack
        conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (buyer, year, slot))
        conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (owner, year, their))
        for p in extras:
            if isinstance(p, int):
                conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (owner, year, p))
            else:
                _move_future(conn, p, owner, day)
        got = ", ".join([f"#{their}"] + [_label(conn, p, buyer) for p in extras])
        text = (f"{team_abbr(conn, buyer)} trade up to #{slot} with {team_abbr(conn, owner)} for {got}"
                + (" (desperation premium paid)" if gap >= DESPERATE_GAP else ""))
        emit(conn, "TRADE_COMPLETED", day, text, team_id=buyer, other_team_id=owner, importance=2,
             kind="draft_move_up", slot=slot, gave=[their] + [p if isinstance(p, int) else list(p) for p in extras],
             live_multiplier=round(m_live, 2))
        board.need.pop(buyer, None)
        board.views.pop(buyer, None)
        return text
    return None


def consolidate(conn, year, day):
    """Clubs holding many picks bundle three late ones into one higher pick (Module B). Returns lines."""
    me = user_team(conn)
    rng = random.Random(f"{get_state(conn)[1]}-{year}-consolidate")
    rows = conn.execute("SELECT team_id, COUNT(*) n FROM draft_picks WHERE draft_year=? AND player_id IS NULL "
                        "GROUP BY team_id", (year,)).fetchall()
    counts = {r["team_id"]: r["n"] for r in rows}
    n_teams = conn.execute("SELECT COUNT(*) FROM draft_picks WHERE draft_year=? AND round=1", (year,)).fetchone()[0] or 32
    lines = []
    for t, n in sorted(counts.items()):
        if t == me or n <= CONSOLIDATE_AT:
            continue
        late = [p for p in _year_picks(conn, year, t) if p > 4 * n_teams][:3]
        if len(late) < 3:
            continue
        bundle = sum(chart(p * 32 // n_teams) for p in late)      # chart is for a 32-club draft
        partners = [u for u, m in counts.items() if u not in (t, me) and m <= 7]
        rng.shuffle(partners)
        for u in partners:
            theirs = [p for p in _year_picks(conn, year, u) if 2 * n_teams < p <= 4 * n_teams
                      and chart(p * 32 // n_teams) <= bundle]
            if not theirs:
                continue
            target = theirs[0]
            try:
                K.check_contract_limit(conn, u, K.signing_year(conn) + 1)
            except K.CapError:
                continue
            conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (t, year, target))
            for p in late:
                conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (u, year, p))
            text = (f"{team_abbr(conn, t)} consolidate: #{', #'.join(map(str, late))} to {team_abbr(conn, u)} "
                    f"for #{target}")
            emit(conn, "TRADE_COMPLETED", day, text, team_id=t, other_team_id=u, importance=1, kind="draft_consolidate",
                 slot=target, gave=late)
            counts[t] -= 2
            counts[u] += 2
            lines.append(text)
            break
    return lines


def pickswap(conn, year, me, other, give, get, day, board_slide=0):
    """The user's draft-day pick deal. give/get: overall numbers in this draft. The AI accepts at chart value
    (with the live-board multiplier on the picks it gives). Returns a message; raises ValueError if refused."""
    def own(p, t):
        r = conn.execute("SELECT team_id, player_id FROM draft_picks WHERE draft_year=? AND overall=?",
                         (year, p)).fetchone()
        if r is None or r["team_id"] != t or r["player_id"] is not None:
            raise ValueError(f"#{p} is not an unused pick of {team_abbr(conn, t)}.")
    for p in give:
        own(p, me)
    for p in get:
        own(p, other)
    if not give or not get:
        raise ValueError("Name the picks you give and the picks you want.")
    nxt = conn.execute("SELECT MIN(overall) FROM draft_picks WHERE draft_year=? AND player_id IS NULL",
                       (year,)).fetchone()[0]
    m_live = live_multiplier(board_slide)
    value_in = sum(chart(p) for p in give)
    value_out = sum(chart(p) * (m_live if p == nxt else 1.0) for p in get)
    if value_in < value_out:
        raise ValueError(f"{team_abbr(conn, other)} say no: your picks are worth {value_in:.0f} on the chart, theirs "
                         f"{value_out:.0f}" + (f" (x{m_live:.2f} for who is still on the board)" if m_live > 1 else "")
                         + ".")
    for p in give:
        conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (other, year, p))
    for p in get:
        conn.execute("UPDATE draft_picks SET team_id=? WHERE draft_year=? AND overall=?", (me, year, p))
    text = (f"{team_abbr(conn, me)} trade #{', #'.join(map(str, give))} to {team_abbr(conn, other)} for "
            f"#{', #'.join(map(str, get))}")
    emit(conn, "TRADE_COMPLETED", day, text, team_id=me, other_team_id=other, importance=2, kind="draft_pickswap",
         gave=give, got=get)
    return f"Done: {text} (chart {value_in:.0f} for {value_out:.0f})."
