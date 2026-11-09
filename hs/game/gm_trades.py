"""Trades with the user's club: the same valuation AI clubs use with each other, future picks, counter-offers,
AI clubs calling with offers, and a trading block. See docs/TRADES.md ("Your trades").

An AI club judges a deal from its own position (trades.Market): the league's perceived value of each player
(ratings blended with NHL usage and production, young players with part of their potential), contract surplus,
picks by slot (this year's from the standings, later years at mid-round), and its posture: rebuilding clubs pay
more for youth and picks, contenders for help now and for the player who fills their weakest group.

  accept           what it receives >= 105% of what it gives (its own weights)
  core             one of its top three skaters or its starting goalie: 130%, and a contender will not sell its core
  asked out        a player who asked for a trade: his club takes 75% of his value
  just moved       a player traded this season or signed in the last 30 days (a free agent: a year) cannot move
  calendar         until the trade deadline; again from the draft through the preseason

Counter-offer ("what would it take"): for the assets you ask for, the club names the cheapest set of up to three of
your assets (players outside your top lineup at that position, prospects, picks) it would accept, cheapest by your
own valuation.

Offers to you: on an in-season day an AI club looks at your roster with 3% probability (8% in the deadline rush, and
three times as often while you have players on the block): a club whose weakest group one of your players would
improve builds the cheapest package it can (the same search as AI-to-AI trades) and calls. Offers last three days;
`offers`, `accept <id>`, `decline <id>`. Your core is not asked for unless it is on the block.
"""
from __future__ import annotations

import datetime
import json
import random
import re

from . import roster as R
from . import trades as T
from . import trade_model as TM
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

ACCEPT = 1.05
CORE_PREMIUM = 1.30            # before v39; v39 uses friction (trade_model): 1.05 + friction/100
UNTOUCHABLE = 90.0             # v39: friction at which a club will not discuss a player at all
P_OFFER, P_OFFER_RUSH, BLOCK_MULT = 0.03, 0.08, 3.0
P_DEPTH_CALL = 0.6             # v39: share of calls that are about a depth player
OFFER_DAYS = 3
MAX_OPEN_OFFERS = 3


def ensure_tables(conn):
    T.ensure_tables(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS trade_offers (offer_id INTEGER PRIMARY KEY, made TEXT, expires TEXT, "
                 "team_id INTEGER, they_give TEXT, they_get TEXT, status TEXT DEFAULT 'open', note TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS trade_block (player_id INTEGER PRIMARY KEY, since TEXT)")


# ---------------------------------------------------------------- assets

def asset_key(a):
    if a[0] == "pick":
        top = a[2] if len(a) > 2 and a[2] else 0
        if T.parse_spec(top):                                  # v41: conditional, e.g. ':cpo-18'
            return f"pick:{a[1][0]}:{a[1][1]}:{a[1][2]}:{top}"
        return f"pick:{a[1][0]}:{a[1][1]}:{a[1][2]}" + (f":p{top}" if top else "")
    return f"player:{a[1]}"


def parse_key(k):
    """'pick:2027:1:18' or with a protection 'pick:2027:1:18:p10' (v39), 'player:123'."""
    p = k.split(":")
    if p[0] == "pick" and len(p) > 4 and T.parse_spec(p[4]):    # v41: conditional
        return ("pick", (int(p[1]), int(p[2]), int(p[3])), p[4])
    if p[0] == "pick":
        top = int(p[4][1:]) if len(p) > 4 and p[4].startswith("p") and p[4][1:].isdigit() else 0
        if top and (int(p[2]) != 1 or top not in TM.PROTECT_OPTIONS):
            raise ValueError("Only 1st-round picks can be protected, top 3, 5 or 10.")
        return ("pick", (int(p[1]), int(p[2]), int(p[3])), top) if top else ("pick", (int(p[1]), int(p[2]), int(p[3])))
    return ("player", int(p[1]))


def describe(conn, a, owner):
    if a[0] == "pick":
        y, rnd, orig = a[1]
        return T.pick_label(conn, y, rnd, orig, owner, a[2] if len(a) > 2 and a[2] else None)
    return player_name(conn, a[1])


ROUND_WORDS = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "5th": 5, "6th": 6,
               "7th": 7}


def parse_pick(conn, text, owner):
    """'2027 1st', '2027 2nd TOR' (originally Toronto's), '2027 R3' or 'pick:2027:1:18' -> ("pick", (y, r, orig)).
    v39: '2027 1st top10' (or 'top 5', 'top-3') is a protected 1st."""
    t = text.strip()
    cm = re.search(r"\s+if\s+(?:([A-Za-z]{2,4})\s+)?(playoffs|make the playoffs|round2|wins? a round)\s*$", t, re.I)
    if cm:                                                     # v41: '2027 2nd if playoffs', '2027 3rd if TOR round2'
        a = parse_pick(conn, t[:cm.start()], owner)
        if a is None:
            return None
        team = owner
        if cm.group(1):
            r = conn.execute("SELECT team_id FROM teams WHERE UPPER(abbr)=UPPER(?)", (cm.group(1),)).fetchone()
            if r is None:
                raise ValueError(f"Unknown team {cm.group(1)}.")
            team = r[0]
        kind = "playoffs" if "playoff" in cm.group(2).lower() else "round2"
        why = T.check_condition(conn, a[1][0], a[1][1], a[1][2], owner, kind, team)
        if why:
            raise ValueError(why)
        return ("pick", a[1], T.cond_spec(kind, team))
    pm = re.search(r"\s+top[\s-]*(\d+)(?:\s+protected)?\s*$", t, re.I)
    if pm:
        a = parse_pick(conn, t[:pm.start()], owner)
        top = int(pm.group(1))
        if a is None or a[1][1] != 1 or top not in TM.PROTECT_OPTIONS:
            raise ValueError("Only 1st-round picks can be protected: top 3, top 5 or top 10.")
        return ("pick", a[1], top)
    if t.startswith("pick:"):
        return parse_key(t)
    m = re.match(r"^(\d{4})\s+(?:r(\d)|(\w+))(?:\s+(?:round\s+)?(?:pick\s+)?)?(?:\s*(?:from\s+)?([A-Za-z]{2,4}))?$", t, re.I)
    if not m:
        return None
    y = int(m.group(1))
    rnd = int(m.group(2)) if m.group(2) else ROUND_WORDS.get((m.group(3) or "").lower())
    if not rnd:
        return None
    orig = owner
    if m.group(4) and m.group(4).lower() not in ("round", "pick"):
        r = conn.execute("SELECT team_id FROM teams WHERE UPPER(abbr)=UPPER(?)", (m.group(4),)).fetchone()
        if r is None:
            raise ValueError(f"Unknown team {m.group(4)}.")
        orig = r[0]
    if T.pick_owner(conn, y, rnd, orig) != owner:
        # the owner may hold another club's pick in that round: take it if there is exactly one
        held = [o for (yy, rr, o) in T.picks_owned(conn, owner, [y], _all_teams(conn)) if rr == rnd]
        if len(held) == 1 and orig == owner:
            orig = held[0]
        else:
            raise ValueError(f"{team_abbr(conn, owner)} do not own that {y} round-{rnd} pick.")
    if y not in T.tradeable_years(conn):
        raise ValueError(f"{y} picks cannot be traded now (tradeable drafts: "
                         f"{', '.join(str(x) for x in T.tradeable_years(conn))}).")
    return ("pick", (y, rnd, orig))


def _all_teams(conn):
    from ..schema import top_league_sql
    return [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]


def assets_of(conn, team, m=None):
    """Tradeable assets: NHL players and prospects under contract, and picks in the tradeable drafts."""
    out = []
    for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured','prospect') "
                          "ORDER BY player_id", (team,)):
        out.append(("player", r[0]))
    years = T.tradeable_years(conn)
    for y, rnd, orig in sorted(T.picks_owned(conn, team, years, _all_teams(conn))):
        out.append(("pick", (y, rnd, orig)))
    return out


# ---------------------------------------------------------------- calendar

def window_open(conn, day=None):
    from . import contracts as K
    st = K.season_state(conn)
    if st == "regular_season":
        d = datetime.date.fromisoformat(day or K.today(conn))
        return d <= T.deadline(conn), f"The trade deadline ({T.deadline(conn)}) has passed; trading reopens at the draft."
    if st == "finished":
        return False, "Trading reopens at the draft."
    return True, ""


# ---------------------------------------------------------------- valuation

def _value(m, a, team, receiving, fills=None):
    v = T._asset_value(m, a, team, receiving)
    if receiving and fills and a[0] == "player":
        g = R.group(m.conn.execute("SELECT position FROM players WHERE player_id=?", (a[1],)).fetchone()[0])
        if g == fills:
            v *= 1.2
    return v


def _player_value_known(m, pid):
    if pid not in m.values:
        m.values[pid] = R.player_value(m.conn, pid)
    return pid


def evaluate(conn, me, other, give, get, day=None, m=None, retain=None):
    """How `other` sees: it receives `give` (from the user), gives `get`. Returns a dict with accept and why.
    v39: both sides are valued as packages (best piece 100%, then 80%, 64%); the club wants 1.05 + friction/100 of
    what it gives (friction of the hardest-to-move player it gives: trade_model.friction); clauses must allow each
    player's move; retained salary counts as an asset of the club that retains it."""
    day = day or get_state(conn)[0]
    m = m or T.Market(conn, day)
    retain = retain or {}
    for a in give + get:
        if a[0] == "player":
            _player_value_known(m, a[1])
    need = m.need(other)
    rec = [_value(m, a, other, True, need) for a in give]
    out_v, blockers, fr_max = [], [], 0.0
    for a in get:
        v = _value(m, a, other, False)
        if a[0] == "player":
            pid = a[1]
            if pid in m.recently_moved:
                blockers.append(f"{player_name(conn, pid)} was moved or signed too recently to be traded")
            if pid in m.requests:
                v *= T.REQUEST_DISCOUNT
            fr = m.friction(pid, other)
            if fr >= UNTOUCHABLE and pid not in m.requests:
                blockers.append(f"{player_name(conn, pid)} is untouchable for {team_abbr(conn, other)} right now")
            fr_max = max(fr_max, fr)
            why = T._clause_ok(m, pid, other, me)
            if why:
                blockers.append(why)
        out_v.append(v)
    for a in give:
        if a[0] == "player":
            if a[1] in m.recently_moved:
                blockers.append(f"{player_name(conn, a[1])} was moved or signed too recently to be traded")
            why = T._clause_ok(m, a[1], me, other)
            if why:
                blockers.append(why)
    ret_in = sum(TM.retention_value(conn, me, pid, pct, day) for pid, pct in retain.items()
                 if any(a[0] == "player" and a[1] == pid for a in give))
    ret_out = sum(TM.retention_value(conn, other, pid, pct, day) for pid, pct in retain.items()
                  if any(a[0] == "player" and a[1] == pid for a in get))
    receive = TM.package_value(rec) + ret_in
    out = TM.package_value(out_v) + ret_out
    need_ratio = TM.ACCEPT + fr_max / 100.0
    ratio = receive / out if out else (float("inf") if receive else 0.0)
    ok = not blockers and (out == 0 and receive > 0 or ratio >= need_ratio)
    if blockers:
        why = "; ".join(blockers) + "."
    elif ok:
        why = f"{team_abbr(conn, other)} value what they get at {receive:.0f} against {out:.0f} given."
    else:
        short = need_ratio * out - receive
        why = (f"{team_abbr(conn, other)} value what they get at {receive:.0f} against {out:.0f} given; they want "
               f"{need_ratio:.0%} ({short:.0f} more)" + (" because he is hard to pry loose" if fr_max >= 20
                                                        else "") + ".")
    return dict(accept=ok, receive=round(receive, 1), give=round(out, 1), ratio=None if out == 0 else round(ratio, 3),
                need_ratio=round(need_ratio, 3), posture=m.outlook[other], need=need, why=why, blockers=blockers,
                friction=round(fr_max, 1), need_score=round(m.needs[other][need], 1))


def what_it_takes(conn, me, other, get, day=None, m=None):
    """The cheapest set of up to three of the user's assets (by the user's own valuation) `other` would accept."""
    day = day or get_state(conn)[0]
    m = m or T.Market(conn, day)
    base = evaluate(conn, me, other, [], get, day, m)
    if base["blockers"]:
        return None, base["why"]
    want = base["give"] * base["need_ratio"]
    targets = {a[1] for a in get if a[0] == "player"}
    groups = {R.group(conn.execute("SELECT position FROM players WHERE player_id=?", (p,)).fetchone()[0])
              for p in targets}
    pool = []
    for g in groups or {"F"}:
        pool += T._package_pool(m, me, g, want)
    # also players at other positions outside the user's top lineup, so a deal need not be like for like
    for g in ("F", "D", "G"):
        if g not in groups:
            pool += [a for a in T._package_pool(m, me, g, want) if a[0] == "player"]
    seen, uniq = set(), []
    for a in pool:
        k = asset_key(a)
        if k not in seen and not (a[0] == "player" and (a[1] in m.recently_moved or T._clause_ok(m, a[1], me, other))):
            seen.add(k)
            uniq.append(a)
    for a in uniq:
        if a[0] == "player":
            _player_value_known(m, a[1])
    need = m.need(other)
    scored = [(a, _value(m, a, other, True, need), T._asset_value(m, a, me, False)) for a in uniq]
    best = _cheapest(scored, want)
    if best is None:
        return None, (f"{team_abbr(conn, other)} want {want:.0f} in value; no package of up to three of your "
                      "prospects, picks and depth players gets there.")
    return best, f"{team_abbr(conn, other)} would do it for " + ", ".join(describe(conn, a, me) for a in best) + "."


def _cheapest(scored, want, pool_size=30):
    """scored: [(asset, value to them, cost to you)] -> the 1-3 assets worth >= want to them as a package that cost
    you least (ties: fewer assets, then less overpay). Exhaustive over the pool_size assets they value most."""
    from itertools import combinations
    scored = sorted((s for s in scored if s[1] > 1.0), key=lambda s: -s[1])[:pool_size]
    best = None
    for k in (1, 2, 3):
        for combo in combinations(scored, k):
            v = TM.package_value([c[1] for c in combo])
            if v < want:
                continue
            key = (round(TM.package_value([c[2] for c in combo]), 1), k, v)
            if best is None or key < best[0]:
                best = (key, [c[0] for c in combo])
    return best[1] if best else None


# ---------------------------------------------------------------- executing

def execute(conn, me, other, give, get, day, retain=None):
    """Apply a trade between the user's club and `other` (players, picks, retention). Raises RosterError."""
    ok, why = window_open(conn, day)
    if not ok:
        raise R.RosterError(why)
    my_players = [a[1] for a in give if a[0] == "player"]
    their_players = [a[1] for a in get if a[0] == "player"]
    my_picks = [a[1] for a in give if a[0] == "pick"]
    their_picks = [a[1] for a in get if a[0] == "pick"]
    for y, rnd, orig in my_picks:
        if T.pick_owner(conn, y, rnd, orig) != me:
            raise R.RosterError("You do not own that pick.")
    for y, rnd, orig in my_picks + their_picks:
        if T.encumbered(conn, y, rnd, orig):
            raise R.RosterError(f"The {T.pick_label(conn, y, rnd, orig, orig, 0)} is owed on a conditional pick and "
                                "cannot be traded before the draft.")
    for a, giver in [(a, me) for a in give] + [(a, other) for a in get]:
        c = T.parse_spec(a[2]) if a[0] == "pick" and len(a) > 2 else None
        if c:
            why = T.check_condition(conn, *a[1], giver, *c)
            if why:
                raise R.RosterError(why)
    for y, rnd, orig in their_picks:
        if T.pick_owner(conn, y, rnd, orig) != other:
            raise R.RosterError(f"{team_abbr(conn, other)} do not own that pick.")
    conn.execute("SAVEPOINT gm_trade")
    try:
        if my_players or their_players:
            mn, mx = R.limits(conn)
            on = lambda ps: sum(1 for p in ps if conn.execute("SELECT status FROM players WHERE player_id=?",
                                                               (p,)).fetchone()[0] in ("active", "injured"))
            after = len(R.roster(conn, other)) - on(their_players) + on(my_players)
            if after > mx:                                   # the AI side makes room; the user's side is his call
                R.make_room(conn, other, day, None)
            T._top_up(conn, other, mn - (len(R.roster(conn, other)) - on(their_players) + on(my_players)), day)
            short = mn - (len(R.roster(conn, me)) - on(my_players) + on(their_players))
            for _ in range(max(0, short)):                 # the user's side: recall prospects (never sign anyone)
                up = [u for u in R.prospects(conn, me) if u[1] not in my_players]
                if not up:
                    raise R.RosterError(f"The trade would leave you below the roster minimum ({mn}) with no one to "
                                        "recall.")
                R.call_up(conn, me, up[0][1], day, "recalled to fill the roster after a trade")
            R.trade(conn, me, my_players, other, their_players, day, retain or {})
        for y, rnd, orig in my_picks:
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, orig, other,
                                                                                       f"traded {day}"))
        for y, rnd, orig in their_picks:
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, orig, me,
                                                                                       f"traded {day}"))
        for a in give + get:                              # v39: protections travel with the pick
            if a[0] == "pick" and len(a) > 2 and a[2]:
                c = T.parse_spec(a[2])
                if c:                                     # v41: the condition, owed by the club giving the pick
                    T.set_condition(conn, *a[1], me if a in give else other, *c)
                else:
                    T.protect(conn, *a[1], a[2])
        R.ensure_dressable(conn, other, day)
    except Exception:
        conn.execute("ROLLBACK TO gm_trade")
        conn.execute("RELEASE gm_trade")
        raise
    conn.execute("RELEASE gm_trade")
    ensure_tables(conn)
    for p in my_players:
        conn.execute("DELETE FROM trade_block WHERE player_id=?", (p,))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        for p in my_players + their_players:
            conn.execute("UPDATE morale SET trade_request=0 WHERE player_id=? AND trade_request=1", (p,))
    text = (f"{team_abbr(conn, me)} trade " + ", ".join(describe(conn, a, me) for a in give) + f" to "
            f"{team_abbr(conn, other)} for " + ", ".join(describe(conn, a, other) for a in get)
            + (" (" + ", ".join(f"{player_name(conn, p)} {int(v * 100)}% retained" for p, v in retain.items()) + ")"
               if retain else ""))
    emit(conn, "TRADE_COMPLETED", day, text, team_id=me, other_team_id=other,
         player_id=(their_players or my_players or [None])[0], importance=3,
         players_out=my_players, players_in=their_players, picks_out=[list(p) for p in my_picks],
         picks_in=[list(p) for p in their_picks], retained=bool(retain), user=True)
    from . import press
    press.schedule(conn, "trade", day, dict(other=team_abbr(conn, other)))
    return text


def propose(conn, me, other, give, get, day, retain=None):
    ok, why = window_open(conn, day)
    if not ok:
        raise R.RosterError(why)
    ev = evaluate(conn, me, other, give, get, day, retain=retain)
    if not ev["accept"]:
        from . import rumours
        leaks = rumours.offer_rejected(conn, me, other, [a[1] for a in give if a[0] == "player"], day)
        return False, "Rejected. " + ev["why"] + ("" if not leaks else " Word of the talks has got out: " + " ".join(leaks))
    text = execute(conn, me, other, give, get, day, retain)
    return True, "Accepted. " + ev["why"] + " " + text + "."


# ---------------------------------------------------------------- the block and offers

def block(conn, pid, on=True):
    ensure_tables(conn)
    if on:
        conn.execute("INSERT OR REPLACE INTO trade_block VALUES (?,?)", (pid, get_state(conn)[0]))
    else:
        conn.execute("DELETE FROM trade_block WHERE player_id=?", (pid,))


def on_block(conn):
    ensure_tables(conn)
    me = user_team(conn)
    return [r[0] for r in conn.execute("SELECT b.player_id FROM trade_block b JOIN players p USING (player_id) WHERE "
                                       "p.team_id=?", (me,))]


def open_offers(conn):
    ensure_tables(conn)
    day = get_state(conn)[0]
    conn.execute("UPDATE trade_offers SET status='expired' WHERE status='open' AND expires<?", (day,))
    return conn.execute("SELECT * FROM trade_offers WHERE status='open' ORDER BY offer_id").fetchall()


def offer_assets(r):
    return [parse_key(k) for k in json.loads(r["they_give"])], [parse_key(k) for k in json.loads(r["they_get"])]


def describe_offer(conn, r):
    me = user_team(conn)
    they_give, they_get = offer_assets(r)
    return (f"#{r['offer_id']} {team_abbr(conn, r['team_id'])} offer " + ", ".join(describe(conn, a, r["team_id"])
                                                                                  for a in they_give)
            + " for " + ", ".join(describe(conn, a, me) for a in they_get) + f" (until {r['expires']})")


def respond(conn, offer_id, accept, day):
    ensure_tables(conn)
    me = user_team(conn)
    r = conn.execute("SELECT * FROM trade_offers WHERE offer_id=?", (offer_id,)).fetchone()
    if r is None or r["status"] != "open" or r["expires"] < day:
        raise R.RosterError("That offer is no longer open.")
    if not accept:
        conn.execute("UPDATE trade_offers SET status='declined' WHERE offer_id=?", (offer_id,))
        return f"Declined offer #{offer_id}."
    they_give, they_get = offer_assets(r)
    text = execute(conn, me, r["team_id"], they_get, they_give, day)
    conn.execute("UPDATE trade_offers SET status='accepted' WHERE offer_id=?", (offer_id,))
    return "Done: " + text + "."


def ai_offers(conn, day, rng, rush=False):
    """Daily: maybe an AI club calls with an offer for one of the user's players. Returns the offers made.
    v39: like AI-to-AI trades, most calls are for depth: a club short at a position asks about one of your fringe
    players or minor-league veterans for a late pick. The rest are for a regular who would make its top lineup,
    only if its need there is at least his friction (your core is asked about only when you put him on the block)."""
    ensure_tables(conn)
    me = user_team(conn)
    if me is None or len(open_offers(conn)) >= MAX_OPEN_OFFERS or not window_open(conn, day)[0]:
        return []
    blocked = set(on_block(conn))
    from . import shop as SH                      # v42: a player you are shopping gets his calls from the shop
    shopped = {x[0] for x in SH.shopping(conn)}
    blocked -= shopped
    p = (P_OFFER_RUSH if rush else P_OFFER) * (BLOCK_MULT if blocked else 1.0)
    if rng.random() >= p:
        return []
    m = T.Market(conn, day)
    m.rush = rush
    kind = "roster" if blocked and rng.random() < 0.7 else ("depth" if rng.random() < P_DEPTH_CALL else "roster")
    mine = [r for r in R.roster(conn, me) if r["status"] == "active" and r["player_id"] not in shopped]
    buyers = [t for t in m.teams if m.open_for_business(t, kind)]
    rng.shuffle(buyers)
    for buyer in buyers[:8]:
        if kind == "depth":
            made = _depth_call(conn, m, me, buyer, mine, day, rng)
            if made:
                return [made]
            continue
        g = m.need(buyer)
        have = sorted(m.groups[buyer][g], reverse=True)
        bar = have[T.TOP[g] - 1] if len(have) >= T.TOP[g] else 0.0
        cands = [r["player_id"] for r in mine if R.group(r["position"]) == g and m.values.get(r["player_id"], 0) >= bar
                 and r["player_id"] not in m.recently_moved
                 and (r["player_id"] in blocked or (r["player_id"] not in m.core.get(me, set())
                                                    and m.friction(r["player_id"], me) <= m.needs[buyer][g]))
                 and not T._clause_ok(m, r["player_id"], me, buyer)]
        if not cands:
            continue
        # the block first, then the cheapest player who would still improve the buyer: it works up to what it
        # can afford (up to four tries)
        cands.sort(key=lambda pid: (pid not in blocked, m.values[pid]))
        pkg = None
        for target in cands[:4]:
            want = T._asset_value(m, ("player", target), me, False) * ACCEPT
            worth = T._asset_value(m, ("player", target), buyer, True) * 1.2      # fills its need
            pool = T._package_pool(m, buyer, g, want)
            scored = [(a, T._asset_value(m, a, me, True), T._asset_value(m, a, buyer, False)) for a in pool]
            pkg = _cheapest(scored, want)
            if pkg and TM.package_value([T._asset_value(m, a, buyer, False) for a in pkg]) <= worth:
                break
            pkg = None
        if not pkg:
            continue
        mn, _ = R.limits(conn)                         # only offers the user could accept without signing anyone
        incoming = sum(1 for a in pkg if a[0] == "player" and conn.execute(
            "SELECT status FROM players WHERE player_id=?", (a[1],)).fetchone()[0] in ("active", "injured"))
        if len(R.roster(conn, me)) - 1 + incoming + len(R.prospects(conn, me)) < mn:
            continue
        return [_post_offer(conn, day, buyer, pkg, target, "on the block" if target in blocked else f"they need {g}")]
    return []


def _post_offer(conn, day, buyer, pkg, target, note, days=OFFER_DAYS):
    expires = (datetime.date.fromisoformat(day) + datetime.timedelta(days=days)).isoformat()
    cur = conn.execute("INSERT INTO trade_offers (made, expires, team_id, they_give, they_get, note) VALUES "
                       "(?,?,?,?,?,?)", (day, expires, buyer, json.dumps([asset_key(a) for a in pkg]),
                                         json.dumps([asset_key(("player", target))]), note))
    r = conn.execute("SELECT * FROM trade_offers WHERE offer_id=?", (cur.lastrowid,)).fetchone()
    text = describe_offer(conn, r)
    add_message(conn, day, f"Trade offer from {team_abbr(conn, buyer)}", text + f". The offer stands until {expires}.",
                sender=f"General manager, {team_abbr(conn, buyer)}",
                actions=[dict(label="Accept the offer", cmd=f"accept {r['offer_id']}", confirm=f"Accept: {text}?", primary=True),
                         dict(label="Decline", cmd=f"decline {r['offer_id']}"), dict(label="Open the trade screen", href="#trade")])
    return text


def _depth_call(conn, m, me, buyer, mine, day, rng):
    """A club short at a position asks about one of your fringe players (outside your top nine F / five D / starting
    goalie) or a minor-league veteran who would improve its depth, for the cheapest late pick you would take."""
    cands = []
    for g, keep in T.DEPTH_KEEP.items():
        if m.needs[buyer][g] < T.DEPTH_NEED:
            continue
        vals = sorted(((m.value_of(r["player_id"]), r["player_id"]) for r in mine if R.group(r["position"]) == g),
                      reverse=True)
        have = sorted(m.groups[buyer][g], reverse=True)
        last = have[R.NEED[g] - 1] if len(have) >= R.NEED[g] else 0.0
        cands += [pid for v, pid in vals[keep:] if v >= last + 0.5 and pid not in m.recently_moved]
        cands += [pid for pid in T._minor_pool(m, me, 25) if m.group_of.get(pid) == g and m.value_of(pid) >= last + 0.5]
    cands = [pid for pid in cands if m.age(pid) >= 24 and not T._clause_ok(m, pid, me, buyer)]
    if not cands:
        return None
    target = rng.choice(cands)
    want = T._asset_value(m, ("player", target), me, False) * ACCEPT
    if want <= 0:
        return None
    worth = T._asset_value(m, ("player", target), buyer, True) * 1.2
    opts = sorted((T._asset_value(m, ("pick", pk), me, True), pk) for pk in T._late_picks(m, buyer, 7, 2))
    opts = [o for o in opts if o[0] >= want and T._asset_value(m, ("pick", o[1]), buyer, False) <= worth]
    if not opts:
        return None
    if T._hit(conn, target) > T._cap_room(conn, buyer):
        return None
    return _post_offer(conn, day, buyer, [("pick", opts[0][1])], target, "depth")
