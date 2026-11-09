"""Contracts, salary cap, cap accounting and player rights.

All money is in whole dollars. A contract covers seasons start_year .. start_year + years - 1 (season = its start
year). The current season is MAX(seasons.start_year). Rules come from rules.json "contracts" (defaults below, set
from the 2026 CBA where confirmed; see docs/CBA_2026.md for which numbers are confirmed). "cap_ceiling": null turns
the cap off (e.g. pre-2005 eras).

Cap accounting for a team in a season (simplified):
    roster players (active/injured)        full cap hit, less any share retained by other teams
    players in the system (status prospect) cap hit above the burial allowance (minimum salary + $375K)
    + shares it retains on traded contracts + buyout charges (table cap_charges)
Not modelled: LTIR relief, performance bonuses, two-way contracts, waivers, signing bonuses, salary vs cap hit.

Market value: a player's asking AAV comes from his percentile among rostered players by player_value:
    aav = min_salary + (top - min_salary) * percentile ** 3.5,   top = 13% of the cap (or of a reference payroll)
which gives an average near 3.5% of the cap and a top salary near 13%, about what the real league shows.
"""
from __future__ import annotations

from ..schema import top_league_sql

import datetime
import json
import random

from .roster import RosterError, player_value
from .state import get_state

CONTRACT_DEFAULTS = {
    "cap_ceiling": 104_000_000,        # 2026-27 figure projected by the league in 2025; verify before relying on it
    "cap_floor": 76_900_000,           # approximate (floor has run at about 74% of the ceiling)
    "min_salary": 850_000,             # 2026-27 league minimum (confirmed)
    "max_salary_pct": 0.20,            # max AAV as share of the cap (prior CBA; unconfirmed for 2026)
    "max_term_resign": 7,              # confirmed
    "max_contracts": 50,               # standard player contracts per organisation (junior-age players in junior exempt)
    "max_term_new": 6,                 # confirmed
    "qualifying_offer": [[1_250_000, 1.10], [1_750_000, 1.05], [None, 1.00]],   # prior salary <= limit -> factor
    "ufa_age": 27, "ufa_nhl_seasons": 7,                                         # prior CBA; unconfirmed
    "arbitration_pro_years": [[20, 4], [21, 3], [23, 2], [99, 1]],              # age at first contract -> years
    "arbitration_walkaway": 4_740_000,                                           # verify yearly
    "club_election_floor": 0.85,
    "retention_max_pct": 0.5, "retention_max_contracts": 3,                       # prior CBA; unconfirmed
    "buyout_age": 26, "buyout_share_young": 1 / 3, "buyout_share_old": 2 / 3,
    "burial_extra": 375_000,
    "reference_payroll": 104_000_000,  # used for salary scale when the cap is off
}
MARKET_TOP_PCT = 0.13
MARKET_EXPONENT = 3.5
OFFSEASON_STATES = ("draft", "rights", "free_agency", "arbitration", "awards", "preseason")


class CapError(RosterError):
    pass


def ensure_contract_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS retained (contract_id INTEGER NOT NULL, team_id INTEGER NOT NULL, "
                 "pct REAL NOT NULL, PRIMARY KEY (contract_id, team_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS cap_charges (charge_id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, "
                 "season_start_year INTEGER NOT NULL, amount INTEGER NOT NULL, reason TEXT, player_id INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS offseason_rights (season_start_year INTEGER NOT NULL, "
                 "player_id INTEGER NOT NULL, team_id INTEGER NOT NULL, status TEXT NOT NULL, prev_aav INTEGER, "
                 "qo INTEGER, qualified INTEGER, decided_by TEXT, arb_eligible INTEGER, arb_elected_by TEXT, "
                 "player_ask INTEGER, team_offer INTEGER, award INTEGER, award_years INTEGER, outcome TEXT, "
                 "PRIMARY KEY (season_start_year, player_id))")


def crules(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    out = dict(CONTRACT_DEFAULTS)
    if r:
        out.update(json.loads(r["value"]).get("contracts") or {})
    return out


def season_year(conn):
    return conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]


def season_state(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='season_state'").fetchone()
    return r["value"] if r else "regular_season"


def signing_year(conn):
    """Season a contract signed today starts in: next season once this one is over."""
    return season_year(conn) + (1 if season_state(conn) in ("finished",) + OFFSEASON_STATES else 0)


def today(conn):
    st = get_state(conn)
    return st[0] if st else datetime.date.today().isoformat()


def age_on(birth_date, on):
    b = datetime.date.fromisoformat(birth_date)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def current_contract(conn, pid, year=None):
    year = season_year(conn) if year is None else year
    return conn.execute("SELECT * FROM contracts WHERE player_id=? AND start_year<=? AND start_year+years>? "
                        "ORDER BY start_year DESC, contract_id DESC LIMIT 1", (pid, year, year)).fetchone()


def last_contract(conn, pid):
    return conn.execute("SELECT * FROM contracts WHERE player_id=? ORDER BY start_year+years DESC, contract_id DESC "
                        "LIMIT 1", (pid,)).fetchone()


def retained_share(conn, contract_id):
    return conn.execute("SELECT COALESCE(SUM(pct),0) FROM retained WHERE contract_id=?", (contract_id,)).fetchone()[0]


def payroll(conn, team_id, year=None, detail=False):
    """Cap hit counted against team_id in season `year`."""
    cr = crules(conn)
    year = season_year(conn) if year is None else year
    burial = cr["min_salary"] + cr["burial_extra"]
    lines, total = [], 0
    for p in conn.execute("SELECT player_id, status FROM players WHERE team_id=? AND status IN "
                          "('active','injured','prospect','waivers','ltir')", (team_id,)).fetchall():
        c = current_contract(conn, p["player_id"], year)
        if c is None:
            continue
        own = round(c["cap_hit"] * (1 - retained_share(conn, c["contract_id"])))
        if p["status"] == "prospect":
            own = max(0, own - burial)
        total += own
        lines.append(("player", p["player_id"], own))
    for r in conn.execute("SELECT r.pct, c.cap_hit, c.player_id FROM retained r JOIN contracts c USING (contract_id) "
                          "WHERE r.team_id=? AND c.start_year<=? AND c.start_year+c.years>?",
                          (team_id, year, year)).fetchall():
        amt = round(r["pct"] * r["cap_hit"])
        total += amt
        lines.append(("retained", r["player_id"], amt))
    for r in conn.execute("SELECT amount, player_id, reason FROM cap_charges WHERE team_id=? AND season_start_year=?",
                          (team_id, year)).fetchall():
        total += r["amount"]
        lines.append((r["reason"], r["player_id"], r["amount"]))
    return (total, lines) if detail else total


def pending_rfa_cost(conn, team_id):
    """Cap room a club should keep for its qualified restricted free agents still unsigned this summer (they accept
    the qualifying offer or go to arbitration later, past the cap check): the higher of QO and his ask, each."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='offseason_rights'").fetchone():
        return 0
    tot = 0
    for r in conn.execute("SELECT player_id, qo FROM offseason_rights WHERE season_start_year=? AND team_id=? AND "
                          "status='RFA' AND COALESCE(qualified, 1)=1 AND outcome IS NULL",
                          (season_year(conn), team_id)).fetchall():
        tot += max(r["qo"] or 0, asking(conn, r["player_id"], "RFA"))
    return tot


def _ceiling(conn, team_id, year=None):
    """The cap, or a club's LTIR ceiling this season (hs/game/ltir.py)."""
    cap = crules(conn)["cap_ceiling"]
    if cap is None or (year is not None and year != season_year(conn)):
        return cap
    from .ltir import ceiling
    return ceiling(conn, team_id)


def cap_room(conn, team_id, year=None):
    cap = _ceiling(conn, team_id, year)
    return None if cap is None else cap - payroll(conn, team_id, year)


def check_cap(conn, team_id, adding, year=None, removing=0, what="This move"):
    cap = _ceiling(conn, team_id, year)
    if cap is None:
        return
    before = payroll(conn, team_id, year)
    after = before + adding - removing
    if after > cap and after > before:
        raise CapError(f"{what} would put the team at ${after:,.0f}, over the ${cap:,.0f} cap.")


# ---------------- market value

def _scale(conn):
    cr = crules(conn)
    return cr["cap_ceiling"] or cr["reference_payroll"]


class MarketValues(list):
    """The salary market's view of the league: sorted perceived values of every player in an NHL organisation (the
    percentile scale for market_aav) plus `value(pid)` for any player, rostered or not. Perceived value blends
    ratings with NHL usage and production (hs.game.trades.Perception), so pay follows what clubs can see."""

    def __init__(self, conn):
        from .trades import Perception
        rows = conn.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL AND status IN "
                            "('active','injured')").fetchall()
        raw = {r[0]: player_value(conn, r[0]) for r in rows}
        self.lens = Perception(conn, raw)
        self.of = {pid: self.lens.value(pid, v) for pid, v in raw.items()}
        self.conn = conn
        super().__init__(sorted(self.of.values()))

    def value(self, pid):
        if pid in self.of:
            return self.of[pid]
        return self.lens.value(pid, player_value(self.conn, pid))


_MV_CACHE = {}
_DAY_CACHE = {}


def day_values(conn):
    """Perceived values for roster decisions: like league_values but cached for the whole game day, so a club
    trimming its roster player by player does not rebuild the league view after every move."""
    day = conn.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='game_state'").fetchone() else None
    key = (id(conn), day[0] if day else None, conn.execute("SELECT COUNT(*) FROM skater_season_stats").fetchone()[0])
    if key not in _DAY_CACHE:
        _DAY_CACHE.clear()
        _DAY_CACHE[key] = MarketValues(conn)
    return _DAY_CACHE[key]


def league_values(conn):
    """MarketValues for today (cached per game day and roster size)."""
    day = conn.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='game_state'").fetchone() else None
    n = conn.execute("SELECT COUNT(*), COALESCE(SUM(team_id), 0) FROM players WHERE team_id IS NOT NULL AND status IN "
                     "('active','injured')").fetchone()
    key = (id(conn), day[0] if day else None, n[0], n[1],
           conn.execute("SELECT COUNT(*) FROM skater_season_stats").fetchone()[0])
    if key not in _MV_CACHE:
        _MV_CACHE.clear()
        _MV_CACHE[key] = MarketValues(conn)
    return _MV_CACHE[key]


def market_aav(conn, pid, values=None, v=None):
    """Market AAV for a player; `v` overrides his value (e.g. the arbitrator's view of him)."""
    cr = crules(conn)
    values = values if values is not None else league_values(conn)
    if v is None:
        v = values.value(pid) if isinstance(values, MarketValues) else player_value(conn, pid)
    if not values:
        return cr["min_salary"]
    below = sum(1 for x in values if x < v)
    pct = below / len(values)
    top = MARKET_TOP_PCT * _scale(conn)
    aav = cr["min_salary"] + (top - cr["min_salary"]) * pct ** MARKET_EXPONENT
    p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    age = age_on(p["birth_date"], datetime.date.fromisoformat(today(conn)))
    if age > 33:
        aav *= max(0.5, 1 - 0.10 * (age - 33))
    cap_max = cr["max_salary_pct"] * cr["cap_ceiling"] if cr["cap_ceiling"] else None
    if cap_max:
        aav = min(aav, cap_max)
    return max(cr["min_salary"], int(round(aav / 5000) * 5000))


def asking(conn, pid, status="UFA", values=None):
    if status == "UFA":
        from .free_agency import asking_price
        stored = asking_price(conn, pid)
        if stored is not None:
            return stored
    m = market_aav(conn, pid, values)
    return m if status == "UFA" else max(crules(conn)["min_salary"], int(round(m * 0.85 / 5000) * 5000))


def term_wanted(conn, pid, rng, max_term):
    p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    age = age_on(p["birth_date"], datetime.date.fromisoformat(today(conn)))
    lo, hi = (1, 3) if age >= 32 else (2, max_term) if age <= 28 else (1, 4)
    return rng.randint(lo, min(hi, max_term))


# ---------------- rights

def _stats_seasons(conn, pid, top_league_only):
    q = ("SELECT DISTINCT season_start_year FROM {t} s WHERE player_id=? AND split='RS' AND gp>0"
         + (" AND league_id IN (SELECT league_id FROM leagues WHERE level=1 OR level IS NULL)" if top_league_only else
            # v42: pro seasons only (junior, college and leagues outside the world, as in imported history, do not count)
            " AND league_id IN (SELECT league_id FROM leagues WHERE COALESCE(level, 1) <= 3)"))
    years = set()
    for t in ("skater_season_stats", "goalie_season_stats"):
        years |= {r[0] for r in conn.execute(q.format(t=t), (pid,))}
    return sorted(years)


def rights_status(conn, pid, year):
    """'UFA' or 'RFA' when the contract ending after season `year` expires (age on 1 July or NHL seasons)."""
    cr = crules(conn)
    p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    age = age_on(p["birth_date"], datetime.date(year + 1, 7, 1))
    seasons = len(_stats_seasons(conn, pid, True))
    return "UFA" if age >= cr["ufa_age"] or seasons >= cr["ufa_nhl_seasons"] else "RFA"


def arbitration_eligible(conn, pid):
    """Pro years (any league with games played) against the table keyed by age in the first pro season."""
    cr = crules(conn)
    seasons = _stats_seasons(conn, pid, False)
    p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    if not seasons:
        return False
    first_age = age_on(p["birth_date"], datetime.date(seasons[0], 9, 15))
    need = next(n for a, n in cr["arbitration_pro_years"] if first_age <= a)
    return len(seasons) >= need


def qualifying_offer(conn, prev_aav):
    cr = crules(conn)
    for limit, f in cr["qualifying_offer"]:
        if limit is None or prev_aav <= limit:
            return max(cr["min_salary"], int(round(prev_aav * f)))
    return max(cr["min_salary"], prev_aav)


# ---------------- signing and leaving

def contract_count(conn, team_id, year):
    """Contracts counting against the limit in a season: every contract running that season, except players 19 or
    younger who are back with a junior club (the CBA exemption)."""
    rows = conn.execute("SELECT c.player_id, p.birth_date, t.league_id, l.level FROM contracts c JOIN players p USING "
                        "(player_id) LEFT JOIN teams t ON t.team_id=p.club_id LEFT JOIN leagues l ON l.league_id="
                        "t.league_id WHERE c.team_id=? AND c.start_year<=? AND c.start_year+c.years>? AND "
                        "p.status<>'retired'", (team_id, year, year)).fetchall()
    meta = _junior_leagues(conn)
    n = 0
    for r in rows:
        age = age_on(r["birth_date"], datetime.date(year, 9, 15))
        if r["league_id"] in meta and age <= 19:
            continue
        n += 1
    return n


def _junior_leagues(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    world = (json.loads(r["value"]).get("world") or {}).get("leagues", {}) if r else {}
    return {int(k) for k, v in world.items() if v.get("kind") == "junior"}


def check_contract_limit(conn, team_id, year):
    lim = crules(conn).get("max_contracts")
    if lim and contract_count(conn, team_id, year) >= lim:
        raise CapError(f"The club already has {lim} contracts for {year}-{str(year + 1)[2:]} (the limit).")


def sign_contract(conn, pid, team_id, years, aav, day, start_year=None, kind="standard", resign=None, check=True,
                  detail="signed", limit=None):
    cr = crules(conn)
    start_year = signing_year(conn) if start_year is None else start_year
    prev = last_contract(conn, pid)
    resign = (prev is not None and prev["team_id"] == team_id) if resign is None else resign
    if (check if limit is None else limit) and not resign:
        check_contract_limit(conn, team_id, start_year)
    max_term = cr["max_term_resign"] if resign else cr["max_term_new"]
    if check:
        if not 1 <= years <= max_term:
            raise RosterError(f"Term must be 1-{max_term} years ({'re-signing' if resign else 'new team'}).")
        if aav < cr["min_salary"]:
            raise RosterError(f"AAV must be at least the league minimum ${cr['min_salary']:,.0f}.")
        if cr["cap_ceiling"] and aav > cr["max_salary_pct"] * cr["cap_ceiling"]:
            raise RosterError(f"AAV is above the maximum ${cr['max_salary_pct'] * cr['cap_ceiling']:,.0f}.")
        check_cap(conn, team_id, aav, start_year, what="Signing him")
    cur = conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type, no_trade) "
                       "VALUES (?,?,?,?,?,?,0)", (pid, team_id, start_year, years, int(aav), kind))
    from . import ledger as LG                     # v41: the season-by-season salary and bonus schedule
    LG.write(conn, cur.lastrowid)
    if kind != "entry_level":                     # v39: AI clubs' veterans may get a trade clause (clauses.py)
        from . import clauses as CL
        from .state import user_team as _ut
        CL.on_signed(conn, pid, team_id, cur.lastrowid, start_year, years, int(aav), user_club=team_id == _ut(conn))
    conn.execute("UPDATE players SET team_id=?, club_id=CASE WHEN status='prospect' THEN club_id ELSE ? END "
                 "WHERE player_id=?", (team_id, team_id, pid))
    conn.execute("DELETE FROM draft_rights WHERE player_id=?", (pid,))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                 "VALUES (?, 'contract', ?, NULL, ?, ?)",
                 (day, pid, team_id, f"{detail}: {years} yr x ${aav:,.0f} from {start_year}"))
    from .events import emit, player_name, team_abbr
    if kind != "entry_level":
        from .regret import record_signing
        record_signing(conn, pid, team_id, start_year, int(aav), years, day)
    emit(conn, "PLAYER_SIGNED", day, f"{team_abbr(conn, team_id)} {detail}: {player_name(conn, pid)}, {years} yr x "
         f"${aav:,.0f}", team_id=team_id, player_id=pid, importance=2 if aav >= 5_000_000 else 1,
         years=years, aav=int(aav), start_year=start_year, kind=kind)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='concerns'").fetchone():   # v39 (#23): his question is answered
        conn.execute("UPDATE concerns SET status='resolved' WHERE player_id=? AND topic='contract' AND status='open'", (pid,))


def buyout_check(conn, pid, day):
    """The buyout rules for a user's buyout (docs/CONTRACTS.md): returns None when it may go ahead, else why not.
    Window: 15 June (or 48 hours after the final, whichever is later) to 30 June, and again for 48 hours after an
    arbitration case is settled or awarded (here: the arbitration awards phase). Not for a player who is injured, and not for
    a contract that has not started yet. The player goes on unconditional waivers first; a claim is vanishingly rare."""
    year = signing_year(conn)
    c = current_contract(conn, pid, year)
    if c is None:
        if conn.execute("SELECT 1 FROM contracts WHERE player_id=? AND start_year>?", (pid, year)).fetchone():
            return "His new contract has not started yet: a contract can only be bought out once it has begun."
        return None                                          # nothing to buy out
    p = conn.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()
    if p and p["status"] in ("injured", "ltir"):
        return "He is injured: an injured player cannot be bought out."
    phase = season_state(conn)
    d = datetime.date.fromisoformat(day)
    if phase == "awards":                                    # the 48 hours after arbitration awards
        return None
    if phase in ("finished", "draft", "rights") and d.month == 6 and d.day >= 15:
        return None
    return ("Buyouts are only allowed from 15 June (or 48 hours after the final) to 30 June, and for 48 hours after an "
            "arbitration case. Outside the window: waive him, send him down, or trade him.")


def buyout(conn, team_id, pid, day):
    """End a contract: pay 1/3 (under 26) or 2/3 of the remaining cap hit, spread over twice the remaining years.
    Returns total cost. Buyout windows are not enforced."""
    cr = crules(conn)
    year = signing_year(conn)                     # in the summer, the season just played is already paid
    c = current_contract(conn, pid, year) or conn.execute(
        "SELECT * FROM contracts WHERE player_id=? AND start_year>? ORDER BY start_year LIMIT 1", (pid, year)).fetchone()
    if c is None or c["team_id"] != team_id:
        return 0
    first = max(year, c["start_year"])
    remaining = c["start_year"] + c["years"] - first
    p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    young = age_on(p["birth_date"], datetime.date.fromisoformat(day)) < cr["buyout_age"]
    share = cr["buyout_share_young"] if young else cr["buyout_share_old"]
    keep = 1 - retained_share(conn, c["contract_id"])
    # v41 (defect 5): the buyout pays a share of the remaining *salary*; signing bonuses are still paid as scheduled.
    # Each season of the old term the cap carries his cap hit less the salary he no longer draws plus the buyout
    # payment (a flat deal: just the payment); the extra seasons carry the payment alone.
    from . import ledger as LG
    sched = {y["season"]: y for y in LG.years_of(conn, c["contract_id"])}
    rem = [sched.get(first + k, dict(salary=c["cap_hit"], bonus=0)) for k in range(remaining)]
    total = int(round(sum(y["salary"] for y in rem) * keep * share))
    per = int(round(total / (2 * remaining)))
    charges, cash = [], []
    for k in range(2 * remaining):
        if k < remaining:
            cap = int(round(keep * (c["cap_hit"] - rem[k]["salary"]))) + per
            pay = per + int(round(keep * rem[k]["bonus"]))
        else:
            cap = pay = per
        charges.append((team_id, first + k, cap, pid))
        cash.append((team_id, first + k, pid, pay))
    conn.executemany("INSERT INTO cap_charges (team_id, season_start_year, amount, reason, player_id) "
                     "VALUES (?,?,?,'buyout',?)", charges)
    LG.ensure_table(conn)
    conn.executemany("INSERT OR REPLACE INTO buyout_cash VALUES (?,?,?,?)", cash)
    total += sum(int(round(keep * y["bonus"])) for y in rem)
    new_years = first - c["start_year"]
    if new_years <= 0:
        conn.execute("DELETE FROM contracts WHERE contract_id=?", (c["contract_id"],))
    else:
        conn.execute("UPDATE contracts SET years=? WHERE contract_id=?", (new_years, c["contract_id"]))
    return total


# ---------------- generating contracts for packs that have none

def generate_contracts(conn, seed):
    """Give every player in a club's system a plausible contract (packs without salary data, e.g. MoneyPuck).
    Skaters and goalies 21 or younger (on 15 September) are on entry-level deals: three years, signed at 18 (so a
    20-year-old is in his last year), the ELC maximum for the best of them, scaling down to the minimum. Without this
    an 18-year-old star drew a market contract, his qualifying offer was too dear to make, and he walked as a UFA at 20.
    Payrolls over 98% of the cap are scaled down. Returns number of contracts created."""
    cr = crules(conn)
    year = season_year(conn)
    rng = random.Random(f"{seed}-contracts")
    values = league_values(conn)
    made = 0
    rows = conn.execute("SELECT player_id, team_id, status FROM players WHERE team_id IS NOT NULL AND status IN "
                        "('active','injured','prospect') ORDER BY player_id").fetchall()
    elc_max = cr.get("elc_max") or (1_000_000 if year <= 2026 else cr["min_salary"] + 175_000)
    for r in rows:
        if current_contract(conn, r["player_id"], year):
            continue
        b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (r["player_id"],)).fetchone()[0]
        age = age_on(b, datetime.date(year, 9, 15)) if b else 25
        kind = "generated"
        if age <= 21:
            v = values.value(r["player_id"])
            pct = sum(1 for x in values if x < v) / max(1, len(values))
            aav = int(round((cr["min_salary"] + (elc_max - cr["min_salary"]) * min(1.0, pct / 0.6) ** 2) / 5000) * 5000)
            years, kind = 3, "entry_level"
            start = year - min(2, max(0, age - 18))
            conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type, "
                         "no_trade) VALUES (?,?,?,?,?,?,0)", (r["player_id"], r["team_id"], start, years,
                                                               max(aav, cr["min_salary"]), kind))
            made += 1
            continue
        if r["status"] == "prospect":
            aav, years = cr["min_salary"], rng.randint(1, 3)
        else:
            aav = int(round(market_aav(conn, r["player_id"], values) * rng.uniform(0.85, 1.15) / 5000) * 5000)
            years = term_wanted(conn, r["player_id"], rng, cr["max_term_new"])
        start = year - rng.randint(0, years - 1)
        conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type, no_trade) "
                     "VALUES (?,?,?,?,?,'generated',0)", (r["player_id"], r["team_id"], start, years, max(aav, cr["min_salary"])))
        made += 1
    cap = cr["cap_ceiling"]
    if cap:
        for (team_id,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}").fetchall():
            pay = payroll(conn, team_id, year)
            if pay > 0.98 * cap:
                f = 0.98 * cap / pay
                conn.execute("UPDATE contracts SET cap_hit=MAX(?, CAST(cap_hit*? AS INTEGER)) WHERE team_id=? AND "
                             "start_year<=? AND start_year+years>?", (cr["min_salary"], f, team_id, year, year))
    return made
