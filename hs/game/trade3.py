"""Three-team trades (docs/TRADES.md): the user and two AI clubs, any asset to either of the other two clubs.

Each AI club judges its own part exactly as in a two-club trade (hs.game.gm_trades.evaluate): what it receives,
from either club, against what it gives up, to either club; it accepts at 105% (130% for a core player; a contender
will not move its core). A club can be a pure facilitator (it takes a contract and passes on a pick), as long as
what it gets is worth more than what it gives. The whole deal goes through or none of it does.

Execution is a set of two-club transfers inside one savepoint. Roster limits and the cap are checked on the final
state: AI clubs make room or recall players as needed; the user's side recalls prospects but never signs anyone.
Salary retention is not offered in three-team deals.
"""
from __future__ import annotations

import itertools

from . import gm_trades as GT
from . import roster as R
from . import trades as T
from .events import emit, player_name, team_abbr
from .state import get_state, user_team


def _by_team(moves):
    recv, give = {}, {}
    for frm, to, a in moves:
        give.setdefault(frm, []).append(a)
        recv.setdefault(to, []).append(a)
    return recv, give


def validate(conn, moves):
    me = user_team(conn)
    teams = {t for f, to, _ in moves for t in (f, to)}
    if me not in teams:
        raise R.RosterError("Your club must be part of the trade.")
    if len(teams) != 3:
        raise R.RosterError("A three-team trade needs assets moving with three clubs.")
    seen = set()
    for frm, to, a in moves:
        if frm == to:
            raise R.RosterError("An asset has to move to another club.")
        k = GT.asset_key(a)
        if k in seen:
            raise R.RosterError("An asset can only move once.")
        seen.add(k)
        if a[0] == "player":
            owner = conn.execute("SELECT team_id FROM players WHERE player_id=?", (a[1],)).fetchone()
            if owner is None or owner[0] != frm:
                raise R.RosterError(f"{player_name(conn, a[1])} is not on {team_abbr(conn, frm)}.")
        elif T.pick_owner(conn, *a[1]) != frm:
            raise R.RosterError(f"{team_abbr(conn, frm)} do not own that pick.")
    recv, give = _by_team(moves)
    for t in teams - {me}:
        if not recv.get(t):
            raise R.RosterError(f"{team_abbr(conn, t)} would get nothing; every club must receive something.")
    return me, sorted(teams - {me})


def evaluate(conn, moves, day=None):
    """{team_id: gm_trades.evaluate dict} for both AI clubs, plus accept (both say yes)."""
    day = day or get_state(conn)[0]
    me, others = validate(conn, moves)
    m = T.Market(conn, day)
    recv, give = _by_team(moves)
    out = {}
    for t in others:
        out[t] = GT.evaluate(conn, me, t, recv.get(t, []), give.get(t, []), day, m)
        out[t]["abbr"] = team_abbr(conn, t)
    return dict(clubs=out, accept=all(v["accept"] for v in out.values()), me=me, others=others)


def _pairs(moves):
    p = {}
    for frm, to, a in moves:
        key = tuple(sorted((frm, to)))
        p.setdefault(key, {frm: [], to: []})
        p[key].setdefault(frm, []).append(a)
        p[key].setdefault(to, [])
    return p


def execute(conn, moves, day):
    ok, why = GT.window_open(conn, day)
    if not ok:
        raise R.RosterError(why)
    me, others = validate(conn, moves)
    mn, mx = R.limits(conn)

    def active(ps):
        return sum(1 for p in ps if conn.execute("SELECT status FROM players WHERE player_id=?",
                                                 (p,)).fetchone()[0] in ("active", "injured"))
    players_in = {t: [a[1] for f, to, a in moves if to == t and a[0] == "player"] for t in [me, *others]}
    players_out = {t: [a[1] for f, to, a in moves if f == t and a[0] == "player"] for t in [me, *others]}
    conn.execute("SAVEPOINT trade3")
    try:
        for t in [me, *others]:                       # final roster sizes
            final = len(R.roster(conn, t)) - active(players_out[t]) + active(players_in[t])
            if t == me:
                if final > mx:
                    raise R.RosterError(f"You would have {final} players (maximum {mx}); send someone down first.")
                for _ in range(max(0, mn - final)):
                    up = [u for u in R.prospects(conn, me) if u[1] not in players_out[me]]
                    if not up:
                        raise R.RosterError(f"The trade would leave you below the roster minimum ({mn}).")
                    R.call_up(conn, me, up[0][1], day, "recalled to fill the roster after a trade")
            else:
                if final > mx:
                    R.make_room(conn, t, day, None)
                T._top_up(conn, t, mn - (len(R.roster(conn, t)) - active(players_out[t]) + active(players_in[t])), day,
                          exclude=set(players_out[t]))
        pairs = _pairs(moves)
        done, last = False, None
        # pairwise transfers; intermediate roster or cap states can fail in one order and not another
        for order in itertools.permutations(list(pairs)):
            conn.execute("SAVEPOINT trade3_try")
            try:
                for a_, b_ in order:
                    side = pairs[(a_, b_)]
                    pa = [x[1] for x in side[a_] if x[0] == "player"]
                    pb = [x[1] for x in side[b_] if x[0] == "player"]
                    if pa or pb:
                        _trade_loose(conn, a_, pa, b_, pb, day)
                conn.execute("RELEASE trade3_try")
                done = True
                break
            except R.RosterError as e:
                last = e
                conn.execute("ROLLBACK TO trade3_try")
                conn.execute("RELEASE trade3_try")
        if not done:
            raise last or R.RosterError("The trade could not be completed.")
        for frm, to, a in moves:
            if a[0] == "pick":
                conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (*a[1], to, f"traded {day}"))
        for t in [me, *others]:
            if t != me:
                R.ensure_dressable(conn, t, day)
        _final_checks(conn, [me, *others], mn, mx)
    except Exception:
        conn.execute("ROLLBACK TO trade3")
        conn.execute("RELEASE trade3")
        raise
    conn.execute("RELEASE trade3")
    GT.ensure_tables(conn)
    for p in players_out[me]:
        conn.execute("DELETE FROM trade_block WHERE player_id=?", (p,))
    parts = []
    for t in [me, *others]:
        got = [GT.describe(conn, a, t) for f, to, a in moves if to == t]
        parts.append(f"{team_abbr(conn, t)} get " + ", ".join(got))
    text = "Three-team trade: " + "; ".join(parts)
    emit(conn, "TRADE_COMPLETED", day, text, team_id=me, other_team_id=others[0],
         player_id=(players_in[me] or players_out[me] or [None])[0], importance=3, user=True, three_team=True,
         third_team_id=others[1])
    from . import press
    press.schedule(conn, "trade", day, dict(other=f"{team_abbr(conn, others[0])} and {team_abbr(conn, others[1])}"))
    return text


def _trade_loose(conn, a, give_a, b, give_b, day):
    """R.trade without its per-pair roster-size check (sizes are checked on the final state)."""
    real = R.limits
    R.limits = lambda c: (0, 10 ** 6)
    try:
        R.trade(conn, a, give_a, b, give_b, day)
    finally:
        R.limits = real


def _final_checks(conn, teams, mn, mx):
    from . import contracts as K
    cap = K.crules(conn)["cap_ceiling"]
    for t in teams:
        n = len(R.roster(conn, t))
        if not mn <= n <= mx:
            raise R.RosterError(f"{team_abbr(conn, t)} would have {n} players ({mn}-{mx} allowed).")
        if cap and K.payroll(conn, t) > cap and t == user_team(conn):
            raise R.RosterError(f"The trade would put {team_abbr(conn, t)} over the cap.")


def propose(conn, moves, day):
    ok, why = GT.window_open(conn, day)
    if not ok:
        raise R.RosterError(why)
    ev = evaluate(conn, moves, day)
    if not ev["accept"]:
        return False, "Rejected. " + " ".join(v["why"] for v in ev["clubs"].values() if not v["accept"])
    text = execute(conn, moves, day)
    return True, "Accepted. " + text + "."
