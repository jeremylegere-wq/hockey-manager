"""Free agency as a timed auction (opening day, 1 July).

The market opens at noon and runs in rounds (HOURS after noon). Each round:
  * every AI club with cap room, budget and a contract slot picks its best target: the free agent who most improves
    its top lineup (6 F, 4 D, 1 G) at a position, and makes one offer;
  * every player with offers takes the best one if it beats his current asking price, otherwise waits.

Prices (all anchored on hs.game.valuation: the zero-surplus AAV for the term he wants):
  ask(t)     = fair x (FLOOR + (PEAK[tier] - FLOOR) x e^(-t / ASK_TAU))
               Tier 1 asks 120% of fair at noon, Tier 2 110%, Tier 3 100%; after a day everyone left is near half.
  offer(t)   = min(fair x (1 + premium x e^(-t / FOMO_TAU)), ask(t) x (1 + 15% x e^(-t / FOMO_TAU))): clubs bid
               over the ask in the frenzy, up to their own ceiling (premium drawn per club and tier: Tier 1 10-25%,
               Tier 2 0-12%), and never above their cap room or owner budget.
  ceiling    no ask or bid goes above FRENZY_MAX (125%) of fair, however scarce the class (fair itself pays stars only
             part of their value above 9% of the cap: hs.game.valuation, the star ceiling).
  panic buy  a club whose Tier 1/2 target signs elsewhere in the first hour, with $5M+ in room, goes for the next best
             at that position for the next 90 minutes: +1 year, +$1.5M, and a no-move clause.
Terms (what players ask for, by tier and age): Tier 1 27-29 the maximum, 30-31 five, 32+ three; Tier 2 up to 31
four-five, 32+ two-three; Tier 3 one-two. Players weigh security more after 30 (utility = AAV x years^s).
Veterans 32+ take 10% less utility from a non-contender (a first step towards ring-chasing).

Tiers by perceived overall: Tier 1 >= 11.3 (stars), Tier 2 >= 10.5 (middle six / top four), Tier 3 >= 9.6 (depth).
Clubs keep room for their own qualified RFAs (QO or ask, whichever is higher), who sign later in the summer.
Anyone below is left to the depth market afterwards. Players still unsigned after the auction keep their last ask
(fa_market) and sign later as 1-2 year "prove-it" deals, by AI clubs filling rosters or by you.

You can line up offers before it opens: in the rights phase `ufas` lists who is about to hit the market and
`offer <player> <aav> <years>` registers an offer that competes at noon with everyone else's.
"""
from __future__ import annotations

import datetime
import math
import random

from . import contracts as K
from . import roster as R
from . import valuation as V
from .events import emit, player_name, team_abbr
from .state import get_state, user_team
from ..schema import top_league_sql

HOURS = [0, 0.5, 1, 2, 4, 8, 24, 48, 96, 168]
TIER_CUTS = [(11.3, 1), (10.5, 2), (9.6, 3)]
PEAK = {1: 1.20, 2: 1.10, 3: 1.00}
FLOOR, ASK_TAU = 0.5, 10.0
PREMIUM = {1: (0.10, 0.25), 2: (0.0, 0.12), 3: (0.0, 0.0)}
FOMO_TAU = 6.0
OVERBID = 0.15
FRENZY_MAX = 1.25                       # no ask or bid above 125% of fair value, however hot the market
PANIC_ROOM, PANIC_AAV, PANIC_WINDOW = 5_000_000, 1_500_000, 1.5
TOP = {"F": 6, "D": 4, "G": 1}
# weak classes (see scarcity()): the ratio ran 0.19-0.26 (mean 0.24) over four summers on the 2025-26 world
SCARCITY_BASE, SCARCITY_SPAN = 0.27, 0.15
SCARCITY_ASK, SCARCITY_PREMIUM, SCARCITY_TERM = 0.25, 0.20, 2
PSEUDO_FILL = 3                         # in a weak class, depth players fill each position's top three
# bargains
LENS = {"analytics": 0.6, "balanced": 0.25, "traditional": 0.0}   # weight on ratings over the box score
BARGAIN_EDGE = 0.15
RING_AGE, RING_P, RING_SHARE = 33, 0.35, 0.55
REP_PENALTY = 0.15
FILL_RESERVE = 23                       # clubs keep enough room to fill a 23-man roster at the minimum


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS fa_market (player_id INTEGER PRIMARY KEY, season INTEGER, tier INTEGER, "
                 "fair INTEGER, ask INTEGER, wanted INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS fa_offers (player_id INTEGER, team_id INTEGER, season INTEGER, aav INTEGER, "
                 "years INTEGER, made_on TEXT, PRIMARY KEY (player_id, team_id, season))")
    conn.execute("CREATE TABLE IF NOT EXISTS fa_log (season INTEGER, player_id INTEGER, team_id INTEGER, hour REAL, "
                 "aav INTEGER, years INTEGER, tier INTEGER, fair INTEGER, peak_ask INTEGER, panic INTEGER, "
                 "user_offer INTEGER, note TEXT)")
    if "note" not in {r[1] for r in conn.execute("PRAGMA table_info(fa_log)")}:
        conn.execute("ALTER TABLE fa_log ADD COLUMN note TEXT")
    conn.execute("CREATE TABLE IF NOT EXISTS fa_summary (season INTEGER PRIMARY KEY, scarcity REAL, k REAL, "
                 "pseudo INTEGER)")


def tier_of(ov):
    for cut, t in TIER_CUTS:
        if ov >= cut:
            return t
    return None


def wanted_term(tier, age, max_term):
    if tier == 1:
        t = max_term if age <= 29 else 5 if age <= 31 else 3
    elif tier == 2:
        t = 5 if age <= 28 else 4 if age <= 31 else 2 if age >= 34 else 3
    else:
        t = 2 if age <= 30 else 1
    return max(1, min(max_term, t))


def security(age):
    return 0.15 if age < 30 else 0.3 if age < 33 else 0.4


def utility(aav, years, age):
    return aav * years ** security(age)


def ask_mult(tier, hour):
    return FLOOR + (PEAK[tier] - FLOOR) * math.exp(-hour / ASK_TAU)


def asking_price(conn, pid):
    """The stored post-auction ask for a free agent this summer (None if he was not in the auction)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='fa_market'").fetchone():
        return None
    r = conn.execute("SELECT ask, season FROM fa_market WHERE player_id=?", (pid,)).fetchone()
    if r is None or r[1] != K.signing_year(conn):
        return None
    return r[0]


def upcoming(conn):
    """Players about to become unrestricted free agents (rights phase): [dict(pid, team, tier, fair, ask, years)]."""
    m = V.market(conn)
    year = K.season_year(conn)
    out = []
    for r in conn.execute("SELECT player_id, team_id FROM offseason_rights WHERE season_start_year=? AND status='UFA' "
                          "AND outcome IS NULL", (year,)).fetchall():
        info = _info(conn, r[0], m)
        if info["tier"] is None:
            continue
        out.append(dict(info, team_id=r[1]))
    return sorted(out, key=lambda x: -x["ov"])


def _info(conn, pid, m):
    birth, goalie = V._player(conn, pid)
    age = V._age(birth, m.year)
    ov = V.overall_of_value(m.values.value(pid))
    tier = tier_of(ov)
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    years = wanted_term(tier or 3, age, K.crules(conn)["max_term_new"])
    fair = V.fair_aav(conn, pid, years, m.year, m)
    return dict(pid=pid, age=age, ov=ov, tier=tier, pos=pos, group=R.group(pos), years=years, fair=fair,
                peak_ask=int(fair * PEAK.get(tier or 3, 1.0)))


def register_offer(conn, me, pid, aav, years, day):
    """The user's offer, made before the market opens; it competes at noon on 1 July."""
    ensure_tables(conn)
    year = K.season_year(conn)
    live = K.season_state(conn) == "free_agency" and live_state(conn) is not None and not live_state(conn)["done"]
    if live:                                          # the war room: offers go into the next round
        p = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
        if p is None or p[0] is not None:
            raise ValueError("He is not on the market.")
    elif K.season_state(conn) != "rights":
        raise ValueError("Offers to upcoming free agents are made in the rights phase (before 1 July); "
                         "once the market is open use `sign`.")
    else:
        r = conn.execute("SELECT team_id FROM offseason_rights WHERE season_start_year=? AND player_id=? AND status='UFA' "
                         "AND outcome IS NULL", (year, pid)).fetchone()
        if r is None:
            raise ValueError("He is not an upcoming unrestricted free agent.")
        if r[0] == me:
            raise ValueError("He is your own player: re-sign him with `extend`.")
    cr = K.crules(conn)
    if not 1 <= years <= cr["max_term_new"]:
        raise ValueError(f"Term must be 1-{cr['max_term_new']} years.")
    if aav < cr["min_salary"]:
        raise ValueError("Below the league minimum.")
    if cr["cap_ceiling"] and aav > cr["max_salary_pct"] * cr["cap_ceiling"]:
        raise ValueError(f"Above the maximum salary (${cr['max_salary_pct'] * cr['cap_ceiling']:,.0f}).")
    conn.execute("INSERT OR REPLACE INTO fa_offers VALUES (?,?,?,?,?,?)", (pid, me, K.signing_year(conn), int(aav),
                                                                          int(years), day))
    info = _info(conn, pid, V.market(conn))
    warm = utility(aav, years, info["age"]) >= utility(info["peak_ask"], info["years"], info["age"])
    if live:
        return f"Offer in: {player_name(conn, pid)}, {years} yr x ${aav:,.0f}. It is heard in the next round."
    return (f"Offer registered: {player_name(conn, pid)}, {years} yr x ${aav:,.0f}. He wants about "
            f"{info['years']} yr x ${info['peak_ask']:,.0f} at noon; your offer is "
            + ("in his range." if warm else "below what he is asking at the opening; it may work later in the day "
                                             "if nobody beats it, but offers are only heard at noon."))


class _Club:
    def __init__(self, conn, t, m, rng, year):
        from . import org
        self.t = t
        self.room = K.cap_room(conn, t, year)
        o = org.owner(conn, t) if conn.execute("SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone() else None
        cap = K.crules(conn)["cap_ceiling"]
        budget = cap * (0.80 + 0.025 * o["spend"]) if (o and cap) else cap
        self.budget_room = None if budget is None else budget - K.payroll(conn, t, year)
        self.size = len(R.roster(conn, t))
        self.lineup = {g: [] for g in TOP}
        for r in R.roster(conn, t):
            self.lineup[R.group(r["position"])].append(V.overall_of_value(m.values.value(r["player_id"])))
        for g in TOP:
            self.lineup[g].sort(reverse=True)
        self.premium = {k: rng.uniform(*v) for k, v in PREMIUM.items()}
        self.panic = {}                    # group -> hour the panic window opened
        self.primary = None                # pid of the first Tier 1/2 target
        self.contracts_ok = True
        self.contender = False
        self.reserve = K.pending_rfa_cost(conn, t)          # room kept for its own qualified RFAs

    def spendable(self, min_salary):
        rooms = [r for r in (self.room, self.budget_room) if r is not None]
        room = min(rooms) if rooms else 1e12
        return room - self.reserve - max(0, FILL_RESERVE - self.size - 1) * min_salary

    def gain(self, info):
        g = info["group"]
        have = self.lineup[g]
        cut = have[TOP[g] - 1] if len(have) >= TOP[g] else 9.0
        return info["ov"] - cut


def scarcity(conn, pool, clubs, m):
    """Money chasing talent: (spendable room of every AI club) / (fair money of the Tier 1-2 free agents)."""
    demand = sum(max(0.0, c.spendable(m.min_salary)) for c in clubs.values())
    supply = sum(x["fair"] * x["years"] for x in pool.values() if x["tier"] in (1, 2))
    s = demand / supply if supply else 9.9
    k = max(0.0, min(1.0, (s / SCARCITY_BASE - 1.0) / SCARCITY_SPAN))
    return s, k


def quick_trades(conn, team_id, season, window=3):
    """Times in the last `window` summers the club traded a free agent within a year of signing him (no-trade
    clauses aside): free agents remember (the reputation penalty)."""
    n = 0
    for e in conn.execute("SELECT player_id, event_date FROM league_events WHERE event_type='PLAYER_TRADED' AND "
                          "team_id=? AND season_start_year>=?", (team_id, season - window)).fetchall():
        sig = conn.execute("SELECT event_date FROM league_events WHERE event_type='PLAYER_SIGNED' AND player_id=? AND "
                           "team_id=? AND summary LIKE '%free agent%' AND event_date<=? ORDER BY event_date DESC LIMIT 1",
                           (e[0], team_id, e[1])).fetchone()
        if sig and (datetime.date.fromisoformat(e[1]) - datetime.date.fromisoformat(sig[0])).days <= 365:
            n += 1
    return n


def run_auction(conn, day):
    """Opening day of free agency, all of it. Returns summary lines."""
    g = auction(conn, day)
    while True:
        try:
            next(g)
        except StopIteration as e:
            return e.value


def auction(conn, day):
    """Opening day of free agency as a generator: yields a report after every round (hour), so the war room can show
    the market as it moves and you can change your offers between rounds (they are re-read every round). Returns the
    summary lines."""
    ensure_tables(conn)
    me = user_team(conn)
    year = K.signing_year(conn)
    m = V.market(conn)
    cr = K.crules(conn)
    rng = random.Random(f"{get_state(conn)[1]}-{year}-fa-auction")
    pool = {}
    for v, pid, pos in R.free_agents(conn):
        info = _info(conn, pid, m)
        if info["tier"] is not None:
            info["rating_ov"] = V.overall_of_value(R.player_value(conn, pid))
            info["ring"] = (info["age"] >= RING_AGE and info["tier"] in (2, 3)
                            and random.Random(f"{get_state(conn)[1]}-ring-{pid}").random() < RING_P)
            info["note"] = ""
            pool[pid] = info
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")
             if r[0] != me]
    from .scouting import club_style
    from .trades import posture, standings_rank
    rank = standings_rank(conn)
    clubs = {t: _Club(conn, t, m, rng, year) for t in teams}
    season = K.season_year(conn)
    for t, c in clubs.items():
        c.contender = posture(rank.get(t, 16), len(rank)) == "contender"
        c.lens = LENS.get(club_style(conn, t), 0.25)
        c.rep = quick_trades(conn, t, season)
        try:
            K.check_contract_limit(conn, t, year)
        except K.CapError:
            c.contracts_ok = False
    rep_user = quick_trades(conn, me, season) if me else 0
    # --- weak class: money chasing too little talent inflates asks, premiums and terms
    s_ratio, k = scarcity(conn, pool, clubs, m)
    pseudo = []
    if k > 0:
        for g in ("F", "D", "G"):
            grp = sorted((x for x in pool.values() if x["group"] == g), key=lambda x: -x["ov"])
            top = sum(1 for x in grp if x["tier"] in (1, 2))
            for x in grp:
                if top >= PSEUDO_FILL:
                    break
                if x["tier"] == 3:
                    x["tier"], x["note"] = 2, "pseudo-star"
                    pseudo.append(x["pid"])
                    top += 1
        for x in pool.values():
            if x["tier"] in (2, 3):
                x["years"] = min(cr["max_term_new"], x["years"] + round(SCARCITY_TERM * k))
    for x in pool.values():
        if x["ring"]:
            x["years"] = 1
        x["fair"] = V.fair_aav(conn, x["pid"], x["years"], year, m)
        x["peak_ask"] = int(x["fair"] * min(FRENZY_MAX, PEAK[x["tier"]] * (1 + SCARCITY_ASK * k)))
    for c in clubs.values():
        for tier in c.premium:
            c.premium[tier] += SCARCITY_PREMIUM * k

    def ask_at(info, hour):
        return info["fair"] * min(FRENZY_MAX, ask_mult(info["tier"], hour) * (1 + SCARCITY_ASK * k *
                                                                               math.exp(-hour / ASK_TAU)))

    signed_log, spent_by_hour = [], {}
    for hi, hour in enumerate(HOURS):
        if not pool:
            break
        user_offers = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
            "SELECT player_id, aav, years, team_id FROM fa_offers WHERE season=? AND team_id=?", (year, me))} if me else {}
        signed_before = len(signed_log)
        bids = {}                                           # pid -> [(team, aav, years, panic, note)]
        order = list(clubs)
        rng.shuffle(order)
        for t in order:
            c = clubs[t]
            if not c.contracts_ok:
                continue
            cash = c.spendable(m.min_salary)
            if cash < m.min_salary:
                continue
            rep = 1 - REP_PENALTY if c.rep else 1.0
            best = None
            for pid, info in pool.items():
                # the club's own view: analytics-minded clubs trust underlying play (ratings) more than the box score
                seen = info["ov"] + c.lens * (info["rating_ov"] - info["ov"])
                gain = c.gain(dict(info, ov=seen))
                if gain <= 0.05:
                    continue
                note = ""
                if info["ring"] and c.contender:          # a veteran chasing a Cup takes a cheap year
                    years, offer = 1, max(m.min_salary, RING_SHARE * info["fair"])
                    if offer > cash:
                        continue
                    note = "ring-chaser"
                    panic = False
                else:
                    panic = info["group"] in c.panic and hour - c.panic[info["group"]] <= PANIC_WINDOW
                    years = min(cr["max_term_new"], info["years"] + (1 if panic else 0))
                    bargain = (seen - info["ov"] >= BARGAIN_EDGE and info["age"] <= 26 and not panic
                               and info["tier"] != 1)
                    if bargain:
                        years, note = cr["max_term_new"], "bargain"      # lock the undervalued player up long
                    fair = info["fair"] if years == info["years"] else V.fair_aav(conn, pid, years, year, m)
                    w_mkt = V.war(info["ov"], m.scale)
                    view = max(0.7, min(1.6, V.war(seen, m.scale) / w_mkt)) if w_mkt > 0.05 else 1.0
                    prem = c.premium[info["tier"]] * math.exp(-hour / FOMO_TAU)
                    will = fair * view * (1 + prem) + (PANIC_AAV if panic else 0)
                    if m.max_salary:
                        will = min(will, m.max_salary)
                    ask = ask_at(info, hour) * (fair / info["fair"]) / (rep if info["tier"] in (1, 2) else 1.0)
                    # clubs bid just over his current ask (more over it in the frenzy), up to what he is worth to
                    # them: early stars go above value, the day-two leftovers near half
                    offer = min(will, cash, ask * (1 + OVERBID * math.exp(-hour / FOMO_TAU)), fair * FRENZY_MAX)
                    if offer < ask * 0.98:
                        continue
                    if panic:
                        note = "panic buy"
                score = gain * (1.3 if panic else 1.0)
                if best is None or score > best[0]:
                    best = (score, pid, int(round(offer / 5000) * 5000), years, panic, note)
            if best:
                _, pid, aav, years, panic, note = best
                bids.setdefault(pid, []).append((t, aav, years, panic, note))
                if c.primary is None and pool[pid]["tier"] in (1, 2) and hour <= 1:
                    c.primary = pid
        for pid, (aav, years, t) in user_offers.items():
            if pid in pool and K.cap_room(conn, t, year) is not None and K.cap_room(conn, t, year) >= aav:
                bids.setdefault(pid, []).append((t, aav, years, False, "your offer"))
        interest = {pid: len(b) for pid, b in bids.items()}
        for pid in sorted(bids, key=lambda p: -pool[p]["ov"]):
            info = pool.get(pid)
            if info is None:
                continue
            ask_u = utility(ask_at(info, hour), info["years"], info["age"])
            best = None
            for t, aav, years, panic, note in bids[pid]:
                u = utility(aav, years, info["age"])
                if note == "ring-chaser":
                    u /= RING_SHARE                       # the chance at a Cup is worth the pay cut to him
                elif info["age"] >= 32 and t in clubs and not clubs[t].contender:
                    u *= 0.9
                burned = clubs[t].rep if t in clubs else rep_user
                if burned and info["tier"] in (1, 2):
                    u *= 1 - REP_PENALTY                  # free agents remember clubs that flip new signings
                if u >= ask_u * 0.98 and (best is None or u > best[0]):
                    best = (u, t, aav, years, panic, note)
            if best is None:
                continue
            _, t, aav, years, panic, note = best
            note = note or info["note"]
            try:
                K.sign_contract(conn, pid, t, years, aav, day, start_year=year, resign=False,
                                detail=f"signed as free agent ({_clock(hour)}{', ' + note if note else ''})")
            except R.RosterError:
                continue
            if panic:
                conn.execute("UPDATE contracts SET no_trade=1 WHERE player_id=? AND team_id=? AND start_year=?",
                             (pid, t, year))
            conn.execute("INSERT INTO fa_log (season, player_id, team_id, hour, aav, years, tier, fair, peak_ask, "
                         "panic, user_offer, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (year, pid, t, hour, aav, years, info["tier"], info["fair"], info["peak_ask"], int(panic),
                          int(t == me), note))
            spent_by_hour[hour] = spent_by_hour.get(hour, 0) + aav * years
            signed_log.append((hour, t, pid, aav, years, info, panic, note))
            del pool[pid]
            _, mx = R.limits(conn)
            while len(R.roster(conn, t)) > mx:
                low = R._lowest_healthy(conn, t)
                R.send_down(conn, t, low[1], day, "assigned to the minors (roster full)")
            if t in clubs:
                clubs[t] = _refresh(conn, clubs[t], m, year)
            for u, c in clubs.items():               # clubs whose first big target went elsewhere panic
                if c.primary == pid and u != t and hour <= 1 and (c.spendable(m.min_salary) >= PANIC_ROOM):
                    c.panic[info["group"]] = hour
                    c.primary = -1
        conn.commit()
        nxt = HOURS[hi + 1] if hi + 1 < len(HOURS) else None
        mine = {pid: v for pid, v in user_offers.items()}
        yield dict(hour=hour, clock=_clock(hour), next_clock=_clock(nxt) if nxt is not None else None, round=hi + 1,
                   rounds=len(HOURS), scarcity=k,
                   signed=[dict(team_id=x[1], team=team_abbr(conn, x[1]), player_id=x[2], name=player_name(conn, x[2]),
                                aav=x[3], years=x[4], tier=x[5]["tier"], fair=x[5]["fair"], age=x[5]["age"], note=x[7],
                                mine=x[1] == me, was_mine=x[2] in mine)
                           for x in signed_log[signed_before:]],
                   market=[dict(player_id=pid, name=player_name(conn, pid), pos=info["pos"] if "pos" in info else info["group"],
                                age=info["age"], tier=info["tier"], ov=round(info["ov"], 2), fair=info["fair"], years=info["years"],
                                ask=int(round(ask_at(info, nxt if nxt is not None else hour) / 5000) * 5000),
                                interest=interest.get(pid, 0), my_offer=dict(aav=mine[pid][0], years=mine[pid][1]) if pid in mine else None)
                           for pid, info in sorted(pool.items(), key=lambda kv: -kv[1]["ov"])],
                   my_room=K.cap_room(conn, me, year) if me else None)
    conn.execute("DELETE FROM fa_market")
    for pid, info in pool.items():
        conn.execute("INSERT INTO fa_market VALUES (?,?,?,?,?,?)",
                     (pid, year, info["tier"], info["fair"],
                      max(m.min_salary, int(round(ask_at(info, HOURS[-1]) / 5000) * 5000)), min(2, info["years"])))
    conn.execute("DELETE FROM fa_offers WHERE season=?", (year,))
    conn.execute("INSERT OR REPLACE INTO fa_summary VALUES (?,?,?,?)", (year, s_ratio, k, len(pseudo)))
    return _summary(conn, signed_log, spent_by_hour, len(pool), me, s_ratio, k, pseudo)


def _refresh(conn, c, m, year):
    c.room = K.cap_room(conn, c.t, year)
    if c.budget_room is not None:
        from . import org
        o = org.owner(conn, c.t)
        cap = K.crules(conn)["cap_ceiling"]
        c.budget_room = cap * (0.80 + 0.025 * o["spend"]) - K.payroll(conn, c.t, year)
    c.size = len(R.roster(conn, c.t))
    c.lineup = {g: [] for g in TOP}
    for r in R.roster(conn, c.t):
        c.lineup[R.group(r["position"])].append(V.overall_of_value(m.values.value(r["player_id"])))
    for g in TOP:
        c.lineup[g].sort(reverse=True)
    try:
        K.check_contract_limit(conn, c.t, year)
    except K.CapError:
        c.contracts_ok = False
    return c


def _clock(hour):
    if hour < 24:
        h = 12 + hour
        return f"1 July, {int(h) % 12 or 12}:{int(round((h % 1) * 60)):02d} {'pm' if h >= 12 and h < 24 else 'am'}"
    return f"day {int(hour // 24) + 1}"


def _summary(conn, log, spent_by_hour, left, me, s_ratio=0.0, k=0.0, pseudo=()):
    total = sum(spent_by_hour.values())
    early = sum(v for h, v in spent_by_hour.items() if h <= 2)
    lines = [f"Free agency opened: {len(log)} players signed for ${total / 1e6:,.1f}M in total commitments; "
             f"{100 * early / total if total else 0:.0f}% of it in the first two hours. {left} auction players "
             "are still looking (their asks have dropped: `fa`)."]
    if k > 0:
        lines.append(f"  A thin class: ${s_ratio:.1f} of cap room chases every $1 of top talent, so asks, premiums and "
                     f"terms run high" + (f"; {len(pseudo)} depth players are suddenly being sold as top-six "
                                          "talent" if pseudo else "") + ".")
    stars = [x for x in log if x[5]["tier"] == 1]
    for hour, t, pid, aav, years, info, panic, note in sorted(stars, key=lambda x: -x[3])[:6]:
        lines.append(f"  {team_abbr(conn, t)} sign {player_name(conn, pid)} ({info['age']}), {years} yr x "
                     f"${aav / 1e6:.2f}M at {_clock(hour)} ({aav / info['fair']:.0%} of fair value)")
    for label, key in (("Panic buy", "panic buy"), ("Bargain", "bargain"), ("Ring-chaser", "ring-chaser"),
                       ("Cashing in", "pseudo-star")):
        for hour, t, pid, aav, years, info, panic, note in [x for x in log if x[7] == key][:3]:
            lines.append(f"  {label}: {team_abbr(conn, t)} sign {player_name(conn, pid)} ({info['age']}), {years} yr x "
                         f"${aav / 1e6:.2f}M" + (" with a no-move clause" if panic else ""))
    for hour, t, pid, aav, years, info, panic, note in [x for x in log if x[1] == me]:
        lines.append(f"  Your offer was accepted: {player_name(conn, pid)}, {years} yr x ${aav:,.0f}")
    return lines


def fa_report(conn, season=None):
    """Rows of this summer's auction log (for analysis and the UI)."""
    season = season or K.signing_year(conn)
    return conn.execute("SELECT * FROM fa_log WHERE season=? ORDER BY hour, aav DESC", (season,)).fetchall()


# ---------------------------------------------------------------- the war room (live auction for the UI)

LIVE = {}


def live_start(conn, day):
    """Open the auction without running it (the UI steps through the rounds)."""
    LIVE[id(conn)] = dict(gen=auction(conn, day), day=day, last=None, done=False, lines=None)


def live_state(conn):
    return LIVE.get(id(conn))


def live_step(conn):
    """Run one round. Returns the round report, or None when the auction is over (then lines holds the summary)."""
    st = LIVE.get(id(conn))
    if st is None:
        return None
    if st["done"]:
        return None
    try:
        st["last"] = next(st["gen"])
        return st["last"]
    except StopIteration as e:
        st["done"], st["lines"] = True, e.value or []
        return None


def live_finish(conn):
    """Run the rounds that are left (leaving the phase, or 'sim to the end'). Returns the summary lines."""
    st = LIVE.get(id(conn))
    if st is None:
        return []
    while live_step(conn) is not None:
        pass
    return st["lines"] or []

