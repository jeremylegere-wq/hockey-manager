"""Regret, untradeable contracts, buyouts and salary dumps.

Every contract signed (free agents, re-signings, extensions, arbitration awards; not ELCs) is valued when it is
signed (hs.game.valuation) and the expectation is kept. Later the same valuation is run on the seasons left:

  regret ($)      = what the remaining seasons were expected to be worth at signing - what they are worth now
  regret index    = (cap hit / this season's worth) x seasons left x 1.15^(years past 30)   ("the regret factor")
  phases          optimism for the first 4 months (nobody admits anything), then realisation
  untradeable     a year or more in, worth under 75% of what was expected and graded D or F: no club takes it
                  without a sweetener

What clubs do about it (AI clubs, in the June buyout window, i.e. on entering the rights phase):
  buyout          a contract worth under half its cap hit this season, on a player outside the club's top
                  lineup, signed before 35 (35+ deals give no cap relief), when the buyout actually saves cap money
                  this season and the club needs room (under $5M) or the deal is $6M+ under water: one a club a
                  summer
  salary dump     an F contract (surplus below -$8M) on a club with under $10M of room, moved to a club with lots
                  of room and no playoff ambitions,
                  with a sweetener: a 2nd for up to $6M of negative value, a 1st up to $18M, a 1st and a 2nd up to
                  $30M; worse than that and the club buys out or lives with it
"""
from __future__ import annotations

import datetime
import math

from . import contracts as K
from . import roster as R
from . import valuation as V
from .events import emit, player_name, team_abbr
from .state import user_team
from ..schema import top_league_sql

OPTIMISM_DAYS = 120
UNTRADEABLE_AFTER_DAYS = 365
UNTRADEABLE_SHARE = 0.75
BUYOUT_VALUE_SHARE = 0.5
BUYOUT_MIN_HIT = 2_000_000
NEED_ROOM = 5_000_000
CUT_LOSSES = -6_000_000        # a contract this far under water is bought out even without a cap squeeze
DUMP_ROOM = 10_000_000
DUMP_SURPLUS = -8_000_000
SWEETENERS = [(6_000_000, [2]), (18_000_000, [1]), (30_000_000, [1, 2])]


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS contract_expect (player_id INTEGER, team_id INTEGER, start_year INTEGER, "
                 "years INTEGER, aav INTEGER, signed_on TEXT, expected_value REAL, expected_surplus REAL, "
                 "grade TEXT, age_at_signing INTEGER, PRIMARY KEY (player_id, start_year))")


def record_signing(conn, pid, team, start_year, aav, years, day):
    ensure_tables(conn)
    try:
        ev = V.evaluate(conn, pid, aav, years, start_year, sims=50)
    except Exception:
        return
    birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    age = V._age(birth, start_year)
    conn.execute("INSERT OR REPLACE INTO contract_expect VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (pid, team, start_year, years, aav, day, ev["value"], ev["surplus"], ev["grade"], age))


def status(conn, pid, today=None):
    """Regret picture for a player's current contract, or None."""
    ensure_tables(conn)
    ev = V.evaluate_contract(conn, pid)
    if ev is None:
        return None
    c = ev["contract"]
    exp = conn.execute("SELECT * FROM contract_expect WHERE player_id=? AND start_year=?",
                       (pid, c["start_year"])).fetchone()
    today = today or K.today(conn)
    birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    age = V._age(birth, ev["first_season"])
    worth_now = ev["rows"][0][4]
    index = (c["cap_hit"] / max(worth_now, K.crules(conn)["min_salary"])) * ev["years_left"] * \
        1.15 ** max(0, age - 30)
    out = dict(player_id=pid, team_id=c["team_id"], cap_hit=c["cap_hit"], years_left=ev["years_left"],
               surplus=ev["surplus"], grade=ev["grade"], value=ev["value"], index=index, regret=None,
               phase="no record", untradeable=False, days=None)
    if exp is None:
        return out
    days = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(exp["signed_on"])).days
    share_left = ev["years_left"] / exp["years"]
    expected_rem = exp["expected_value"] * share_left
    out["days"] = days
    out["expected_surplus"] = exp["expected_surplus"]
    if days < OPTIMISM_DAYS:
        out.update(regret=0.0, phase="optimism")
        return out
    out["regret"] = expected_rem - ev["value"]
    out["phase"] = "realisation"
    out["untradeable"] = (days >= UNTRADEABLE_AFTER_DAYS and ev["value"] < UNTRADEABLE_SHARE * expected_rem
                          and ev["grade"] in ("D", "F"))
    return out


def worst(conn, n=20, team_id=None):
    """The league's (or a club's) contracts by regret index, worst first."""
    q = ("SELECT p.player_id FROM players p WHERE p.team_id IS NOT NULL AND p.status IN ('active','injured','prospect')"
         + (" AND p.team_id=?" if team_id else ""))
    rows = []
    for (pid,) in conn.execute(q, (team_id,) if team_id else ()).fetchall():
        st = status(conn, pid)
        if st and st["cap_hit"] > K.crules(conn)["min_salary"] * 1.5:
            rows.append(st)
    return sorted(rows, key=lambda s: (-s["index"], s["surplus"]))[:n]


def _signed_at_35_plus(conn, c):
    birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (c["player_id"],)).fetchone()[0]
    return V._age(birth, c["start_year"]) >= 35


def _needs_room(conn, t, year):
    room = K.cap_room(conn, t, year)
    return room is not None and room - K.pending_rfa_cost(conn, t) < NEED_ROOM


def ai_buyouts(conn, day):
    """June buyout window for AI clubs. Returns lines."""
    me = user_team(conn)
    year = K.signing_year(conn)
    m = V.market(conn)
    cr = K.crules(conn)
    lines = []
    for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id").fetchall():
        if t == me:
            continue
        squeezed = _needs_room(conn, t, year)
        lineup = {}
        for r in R.roster(conn, t):
            lineup.setdefault(R.group(r["position"]), []).append(V.overall_of_value(m.values.value(r["player_id"])))
        best = None
        for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured',"
                              "'prospect')", (t,)).fetchall():
            pid = r[0]
            c = K.current_contract(conn, pid, year)
            if c is None or c["team_id"] != t or c["cap_hit"] < BUYOUT_MIN_HIT:
                continue
            if _signed_at_35_plus(conn, c):
                continue                              # 35+ contracts: the cap hit stays, no point
            ev = V.evaluate_contract(conn, pid, m)
            if ev is None or ev["rows"][0][4] >= BUYOUT_VALUE_SHARE * c["cap_hit"]:
                continue
            pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            g = R.group(pos)
            top = sorted(lineup.get(g, []), reverse=True)
            cut = top[{"F": 6, "D": 4, "G": 1}[g] - 1] if len(top) >= {"F": 6, "D": 4, "G": 1}[g] else 0
            if ev["rows"][0][2] >= cut:
                continue                              # still a top-lineup player
            left = ev["years_left"]
            birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            share = cr["buyout_share_young"] if V._age(birth, year) < cr["buyout_age"] else cr["buyout_share_old"]
            per_year = c["cap_hit"] * left * share / (2 * left)
            saving = c["cap_hit"] - per_year
            if saving <= 0 or not (squeezed or ev["surplus"] <= CUT_LOSSES):
                continue
            if best is None or ev["surplus"] < best[1]:
                best = (pid, ev["surplus"], saving)
        if best:
            pid, surplus, saving = best
            cost = K.buyout(conn, t, pid, day)
            R._release(conn, t, pid, day, f"bought out (${cost:,.0f} total)")
            emit(conn, "PLAYER_RELEASED", day, f"{team_abbr(conn, t)} buy out {player_name(conn, pid)} "
                 f"(saves ${saving / 1e6:.1f}M this season; ${cost / 1e6:.1f}M in dead cap over the years)",
                 team_id=t, player_id=pid, importance=2, kind="buyout", cost=cost)
            lines.append(f"{team_abbr(conn, t)} buy out {player_name(conn, pid)}")
    return lines


def ai_salary_dumps(conn, day, limit=6):
    """Clubs move albatross contracts to clubs with room, paying with picks. Returns lines."""
    from .trades import ensure_tables as trade_tables, pick_owner, posture, standings_rank
    trade_tables(conn)
    me = user_team(conn)
    year = K.signing_year(conn)
    m = V.market(conn)
    rank = standings_rank(conn)
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")
             if r[0] != me]
    from .draft import draft_year
    pick_year = draft_year(conn) + (1 if conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_picks'").fetchone()
                                    and conn.execute("SELECT 1 FROM draft_picks WHERE draft_year=?",
                                                     (draft_year(conn),)).fetchone() else 0)
    lines = []
    for t in teams:
        room = K.cap_room(conn, t, year)
        if len(lines) >= limit or room is None or room - K.pending_rfa_cost(conn, t) >= DUMP_ROOM:
            continue
        worst_deal = None
        for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')",
                              (t,)).fetchall():
            st = status(conn, r[0])
            if (st and DUMP_SURPLUS >= st["surplus"] >= -SWEETENERS[-1][0]
                    and (st["days"] is None or st["days"] >= OPTIMISM_DAYS)):
                c = K.current_contract(conn, r[0], year)
                if c and not c["no_trade"] and (worst_deal is None or st["surplus"] < worst_deal[1]):
                    worst_deal = (r[0], st["surplus"], c["cap_hit"])
        if worst_deal is None:
            continue
        pid, surplus, hit = worst_deal
        need = -surplus
        rounds = next((rs for cap_, rs in SWEETENERS if need <= cap_), None)
        if rounds is None:
            continue
        picks = [(pick_year, rnd, t) for rnd in rounds]
        if any(pick_owner(conn, y, rnd, o) != t for y, rnd, o in picks):
            continue
        takers = [u for u in teams if u != t and posture(rank.get(u, 16), len(rank)) != "contender"
                  and (K.cap_room(conn, u, year) or 0) - K.pending_rfa_cost(conn, u) >= hit + NEED_ROOM]
        if not takers:
            continue
        taker = max(takers, key=lambda u: K.cap_room(conn, u, year) or 0)
        conn.execute("SAVEPOINT dump")
        try:
            R.trade(conn, t, [pid], taker, [], day)
        except R.RosterError:
            conn.execute("ROLLBACK TO dump")
            conn.execute("RELEASE dump")
            continue
        conn.execute("RELEASE dump")
        for y, rnd, o in picks:
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                         (y, rnd, o, taker, f"salary dump {day}"))
        nth = {1: "1st", 2: "2nd"}
        sweet = " and ".join(f"{pick_year} {nth[r]}" for r in rounds)
        text = (f"{team_abbr(conn, t)} dump {player_name(conn, pid)}'s contract (${hit / 1e6:.2f}M, "
                f"{surplus / 1e6:+.1f}M of value) on {team_abbr(conn, taker)}, attaching a {sweet}")
        emit(conn, "TRADE_COMPLETED", day, text, team_id=t, other_team_id=taker, player_id=pid, importance=2,
             kind="salary_dump", picks=[list(p) for p in picks], players_out=[], requested=False, retained=False)
        lines.append(text)
    return lines
