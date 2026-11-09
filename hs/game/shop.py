"""Shop a player (v42, register v39 #3; docs/TRADES.md "Shopping a player").

You tell the league a player is available. Every club that could use him hears it, but the calls come in over the
next days, not at once, and most open low: a club pays close to his value only when it really needs him.

  interest   a club calls if it is open for business and he would make its lineup (or, for a fringe player, its
             depth) at a position where its need is at least his friction x 0.7 (shopping him lowers it)
  timing     each interested club calls once, on a day drawn 1-10 days out (sooner the more it needs him)
  price      its opening offer is worth to you: need under 40: 70-80% of his value; 40-70: 80-92%; 70+: 92-102%
             (a contender at the deadline adds 5%)
  limits     the shop runs 14 days; at most 5 calls; each offer stands 5 days; an offer is never made that would leave
             you short of a dressable roster
  the player he hears about it: a trust and morale knock as with a rumour (hs/game/rumours.py), once
At the end, if nobody called, your assistant says so. Shopping puts him on the trading block too.
"""
from __future__ import annotations

import datetime
import json
import random

from . import roster as R
from . import trades as T
from . import trade_model as TM
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

SHOP_DAYS = 14
MAX_CALLS = 5
OFFER_DAYS = 5
INTEREST_FRICTION = 0.7


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS shop (player_id INTEGER PRIMARY KEY, team_id INTEGER, since TEXT, until TEXT, "
                 "plan TEXT, calls INTEGER DEFAULT 0, status TEXT DEFAULT 'open')")


def price_factor(need, rng, contender_rush=False):
    if need < 40:
        f = rng.uniform(0.70, 0.80)
    elif need < 70:
        f = rng.uniform(0.80, 0.92)
    else:
        f = rng.uniform(0.92, 1.02)
    return f + (0.05 if contender_rush else 0.0)


def _fits(m, buyer, pid, g):
    """He makes the buyer's lineup (top nine F, five D, starting goalie) or improves its depth."""
    v = m.value_of(pid)
    have = sorted(m.groups[buyer][g], reverse=True)
    top_bar = have[T.TOP[g] - 1] if len(have) >= T.TOP[g] else 0.0
    depth_bar = have[R.NEED[g] - 1] if len(have) >= R.NEED[g] else 0.0
    return v >= top_bar or v >= depth_bar + 0.5


def shop(conn, pid, day=None, seed=None):
    """Put a player of yours on the market. Returns a summary line."""
    from . import gm_trades as GT
    ensure_tables(conn)
    day = day or get_state(conn)[0]
    me = user_team(conn)
    r = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
    if r is None or r[0] != me:
        raise R.RosterError("You can only shop your own players.")
    ok, why = GT.window_open(conn, day)
    if not ok:
        raise R.RosterError(why)
    cur = conn.execute("SELECT status FROM shop WHERE player_id=? AND status='open'", (pid,)).fetchone()
    if cur:
        raise R.RosterError(f"{player_name(conn, pid)} is already being shopped.")
    rng = random.Random(f"{seed if seed is not None else get_state(conn)[1]}-shop-{pid}-{day}")
    m = T.Market(conn, day)
    g = m.group_of.get(pid) or R.group(conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0])
    fr = m.friction(pid, me) * INTEREST_FRICTION
    clause = [b for b in m.teams if T._clause_ok(m, pid, me, b)]
    if len(clause) >= len(m.teams):
        raise R.RosterError(f"{player_name(conn, pid)}'s clause rules out every club: he would have to agree first.")
    keen = []
    for b in m.teams:
        if not m.open_for_business(b) or b in clause:
            continue
        need = m.needs[b][g]
        if need < fr or not _fits(m, b, pid, g):
            continue
        keen.append((need + rng.uniform(-8, 8), need, b))
    keen = sorted(keen, reverse=True)[:MAX_CALLS]               # the clubs most in need call
    plan, on = [], datetime.date.fromisoformat(day)
    for k, (_, need, b) in enumerate(keen):
        # the keenest calls first (in 1-3 days for a desperate club, 3-6 for a mild one), the rest a day or three apart
        on += datetime.timedelta(days=(rng.randint(1, 3) if need >= 70 else rng.randint(3, 6)) if k == 0 else rng.randint(1, 3))
        plan.append(dict(team=b, day=on.isoformat(), need=round(need, 1)))
    until = (datetime.date.fromisoformat(day) + datetime.timedelta(days=SHOP_DAYS)).isoformat()
    conn.execute("INSERT OR REPLACE INTO shop VALUES (?,?,?,?,?,0,'open')", (pid, me, day, until, json.dumps(plan)))
    GT.block(conn, pid, True)
    name = player_name(conn, pid)
    emit(conn, "RUMOUR", day, f"{team_abbr(conn, me)} are telling teams {name} is available", team_id=me, player_id=pid,
         importance=2, kind="shopped")
    try:
        from .rumours import _hurt
        _hurt(conn, me, pid, 1, day)
    except Exception:
        pass
    n = len(plan)
    add_message(conn, day, f"{name} is on the market",
                f"We've let the league know {name} is available. "
                + (f"{n} club{'s' if n != 1 else ''} should be in touch over the next week or so; expect the first calls to "
                   "come in low unless a club badly needs him. Offers land in your inbox and on the Trade screen."
                   if n else "Honestly, I don't see a fit anywhere right now: nobody needs what he brings at a price we'd take. "
                   "I'll pass on anything that comes in."),
                sender="Assistant GM")
    return f"Shopping {name}: {n} club{'s' if n != 1 else ''} interested; calls over the next {SHOP_DAYS} days."


def stop(conn, pid):
    ensure_tables(conn)
    conn.execute("UPDATE shop SET status='withdrawn' WHERE player_id=? AND status='open'", (pid,))


def shopping(conn):
    """[(player_id, until, calls made, calls left)] for your open shops."""
    ensure_tables(conn)
    out = []
    for pid, until, plan, calls in conn.execute("SELECT player_id, until, plan, calls FROM shop WHERE status='open'"):
        out.append((pid, until, calls, len(json.loads(plan or "[]"))))
    return out


def daily(conn, day, seed=0):
    """Make today's calls for every open shop. Returns the offers made."""
    from . import gm_trades as GT
    ensure_tables(conn)
    rows = conn.execute("SELECT player_id, team_id, since, until, plan, calls FROM shop WHERE status='open'").fetchall()
    if not rows:
        return []
    me = user_team(conn)
    out = []
    m = None
    for pid, team, since, until, plan, calls in rows:
        plan = json.loads(plan or "[]")
        if team != me or conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0] != me:
            conn.execute("UPDATE shop SET status='done' WHERE player_id=?", (pid,))       # traded or released
            continue
        due = [c for c in plan if c["day"] <= day and not c.get("done")]
        if due and GT.window_open(conn, day)[0]:
            m = m or T.Market(conn, day)
            for c in due:
                c["done"] = True
                text = _call(conn, m, me, c["team"], pid, day, random.Random(f"{seed}-shopcall-{pid}-{c['team']}-{day}"))
                if text:
                    calls += 1
                    out.append(text)
            conn.execute("UPDATE shop SET plan=?, calls=? WHERE player_id=?", (json.dumps(plan), calls, pid))
        if day >= until or (plan and all(c.get("done") for c in plan)):
            conn.execute("UPDATE shop SET status='done' WHERE player_id=?", (pid,))
            if calls == 0:
                add_message(conn, day, f"No takers for {player_name(conn, pid)}",
                            f"We've had {player_name(conn, pid)} out there for a while and nobody has made an offer we "
                            "could put in front of you. He's still on the block if anything changes.", sender="Assistant GM")
    return out


def _call(conn, m, me, buyer, pid, day, rng):
    from . import gm_trades as GT
    g = m.group_of.get(pid)
    if g is None or not m.open_for_business(buyer) or T._clause_ok(m, pid, me, buyer):
        return None
    need = m.needs[buyer][g]
    rush = getattr(m, "rush", False) or (0 <= (T.deadline(conn) - datetime.date.fromisoformat(day)).days < T.DEADLINE_RUSH_DAYS)
    contender = m.S.get(buyer, 0.5) >= T.RENTAL_BUYER_S
    base = T._asset_value(m, ("player", pid), me, False)
    want = base * price_factor(need, rng, contender and rush)
    worth = T._asset_value(m, ("player", pid), buyer, True) * 1.2
    pool = T._package_pool(m, buyer, g, want)
    scored = [(a, T._asset_value(m, a, me, True), T._asset_value(m, a, buyer, False)) for a in pool]
    pkg = GT._cheapest(scored, want)
    if not pkg or TM.package_value([T._asset_value(m, a, buyer, False) for a in pkg]) > worth:
        return None
    if T._hit(conn, pid) > T._cap_room(conn, buyer) + sum(T._hit(conn, a[1]) for a in pkg if a[0] == "player"):
        return None
    mn, _ = R.limits(conn)
    incoming = sum(1 for a in pkg if a[0] == "player" and conn.execute(
        "SELECT status FROM players WHERE player_id=?", (a[1],)).fetchone()[0] in ("active", "injured"))
    if len(R.roster(conn, me)) - 1 + incoming + len(R.prospects(conn, me)) < mn:
        return None
    got = TM.package_value([T._asset_value(m, a, me, True) for a in pkg])
    pct = round(100 * got / base) if base else 0
    note = ("a strong offer: they need him" if need >= 70 else "a fair-ish offer" if need >= 40 else "a low opening offer")
    return GT._post_offer(conn, day, buyer, pkg, pid, f"shopped: {note} (about {pct}% of his value)", days=OFFER_DAYS)
