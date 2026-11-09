"""The dual ledger (v41; docs/FINANCE.md "Cap and cash"): what a contract counts against the cap (its average, the
cap hit) and what it actually pays each season (salary plus signing bonus).

Structures
  flat        every season pays the cap hit (entry-level deals, short deals, depth contracts)
  front       front-loaded: the first seasons pay more, the last less (a 10% step), the total equal to cap hit x years
  bonus       front-loaded, and a share of each season's pay is a signing bonus paid on 1 July (lockout-proof money,
              the way big UFA deals are written now): 40% for a $7M+ deal, 25% for $4-7M
Contracts the world came with are paid flat (the database knows the years left, not where in the deal he is).
Contracts signed in the game: yours take the structure you offer (players value money early: front-loaded takes 1.5%
off his ask, bonus-heavy 3%); the AI's are front-loaded at four years or more and $4M+ (bonus-heavy at $7M+), flat
otherwise.

Cash
  A club's player payroll in cash this season = the salaries and bonuses of its contracts this season (retained
  salary: the share it keeps; a buried one-way deal: the full salary, though the cap counts only part; a two-way deal,
  $1.15M or less, in the minors: a minor-league salary, 12% of it and at least $80,000; a buyout: its payments and the
  bonuses still owed). Finance pays salaries over the regular season's months and bonuses on 1 July.
"""
from __future__ import annotations

import random

STRUCTURES = ("flat", "front", "bonus")
STEP = 0.10
BONUS_SHARE = ((7_000_000, 0.40), (4_000_000, 0.25))
TALKS_DISCOUNT = {"flat": 0.0, "front": 0.015, "bonus": 0.03}
TWO_WAY_MAX = 1_150_000          # deals at or under this are two-way: in the minors they pay a minor-league salary
MINOR_PAY_SHARE, MINOR_PAY_MIN = 0.12, 80_000


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS contract_years (contract_id INTEGER, season INTEGER, salary INTEGER, "
                 "bonus INTEGER, PRIMARY KEY (contract_id, season))")
    conn.execute("CREATE TABLE IF NOT EXISTS buyout_cash (team_id INTEGER, season INTEGER, player_id INTEGER, amount INTEGER, "
                 "PRIMARY KEY (team_id, season, player_id))")


def default_structure(cap_hit, years, kind="standard", rng=None):
    if kind == "entry_level" or years < 4 or cap_hit < 4_000_000:
        return "flat"
    return "bonus" if cap_hit >= 7_000_000 else "front"


def schedule(cap_hit, years, structure):
    """[(salary, bonus)] per season summing to cap_hit x years."""
    if structure == "flat" or years <= 1:
        return [(int(cap_hit), 0)] * years
    mid = (years - 1) / 2
    w = [1 + STEP * (mid - i) for i in range(years)]
    tot = cap_hit * years
    pays = [tot * x / sum(w) for x in w]
    out = []
    share = next((s for lo, s in BONUS_SHARE if cap_hit >= lo), 0.0) if structure == "bonus" else 0.0
    for p in pays:
        b = int(round(p * share / 1000) * 1000)
        out.append((int(round((p - b) / 1000) * 1000), b))
    diff = int(tot - sum(a + b for a, b in out))
    out[0] = (out[0][0] + diff, out[0][1])
    return out


def write(conn, contract_id, structure=None):
    ensure_table(conn)
    c = conn.execute("SELECT * FROM contracts WHERE contract_id=?", (contract_id,)).fetchone()
    if c is None:
        return
    st = structure or default_structure(c["cap_hit"], c["years"], c["contract_type"])
    conn.execute("DELETE FROM contract_years WHERE contract_id=?", (contract_id,))
    for i, (s, b) in enumerate(schedule(c["cap_hit"], c["years"], st)):
        conn.execute("INSERT INTO contract_years VALUES (?,?,?,?)", (contract_id, c["start_year"] + i, s, b))


def ensure_all(conn):
    """Give every contract without a schedule one (once per contract). These are the contracts the world came with:
    the database only knows the years left, not where in the deal he is, so they are paid flat."""
    ensure_table(conn)
    for (cid,) in conn.execute("SELECT c.contract_id FROM contracts c WHERE NOT EXISTS (SELECT 1 FROM contract_years y "
                               "WHERE y.contract_id=c.contract_id)").fetchall():
        write(conn, cid, "flat")


def years_of(conn, contract_id):
    ensure_table(conn)
    rows = conn.execute("SELECT season, salary, bonus FROM contract_years WHERE contract_id=? ORDER BY season",
                        (contract_id,)).fetchall()
    if not rows:
        write(conn, contract_id, "flat")
        rows = conn.execute("SELECT season, salary, bonus FROM contract_years WHERE contract_id=? ORDER BY season",
                            (contract_id,)).fetchall()
    return [dict(season=r[0], salary=r[1], bonus=r[2], cash=r[1] + r[2]) for r in rows]


def structure_of(conn, contract_id):
    ys = years_of(conn, contract_id)
    if not ys or len({y["cash"] for y in ys}) == 1:
        return "flat"
    return "bonus" if any(y["bonus"] for y in ys) else "front"


def cash(conn, team, season, part=None):
    """The club's player cash this season: salaries and bonuses (part: 'salary' or 'bonus' for one of them)."""
    from . import contracts as K
    ensure_all(conn)
    tot = 0
    for r in conn.execute("SELECT c.contract_id, c.cap_hit, y.salary, y.bonus, p.status FROM contracts c JOIN contract_years y "
                          "USING (contract_id) JOIN players p ON p.player_id=c.player_id WHERE c.team_id=? AND y.season=?",
                          (team, season)).fetchall():
        keep = 1 - K.retained_share(conn, r[0])
        sal = r[2]
        if r[4] == "prospect" and r[1] <= TWO_WAY_MAX:         # a two-way deal in the minors: the minor-league salary
            sal = max(MINOR_PAY_MIN, int(sal * MINOR_PAY_SHARE))
        tot += keep * ((sal if part != "bonus" else 0) + (r[3] if part != "salary" else 0))
    for r in conn.execute("SELECT r.pct, c.contract_id, y.salary, y.bonus FROM retained r JOIN contracts c USING (contract_id) "
                          "JOIN contract_years y USING (contract_id) WHERE r.team_id=? AND y.season=?", (team, season)).fetchall():
        tot += r[0] * ((r[2] if part != "bonus" else 0) + (r[3] if part != "salary" else 0))
    paid = {r[0]: r[1] for r in conn.execute("SELECT player_id, amount FROM buyout_cash WHERE team_id=? AND season=?",
                                             (team, season))}
    for amt, reason, pid in conn.execute("SELECT amount, reason, player_id FROM cap_charges WHERE team_id=? AND "
                                         "season_start_year=?", (team, season)).fetchall() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='cap_charges'").fetchone() and part != "bonus" else []:
        tot += paid.get(pid, amt) if reason == "buyout" else amt     # v41: a buyout's cash is not its cap charge
    return int(tot)


def grid(conn, team, seasons):
    """{player_id: {season: dict(cap, salary, bonus)}} for a club's contracts (the contracts screen's cash view)."""
    ensure_all(conn)
    out = {}
    q = ",".join("?" * len(seasons))
    for r in conn.execute(f"SELECT c.player_id, c.cap_hit, y.season, y.salary, y.bonus FROM contracts c JOIN contract_years y "
                          f"USING (contract_id) WHERE c.team_id=? AND y.season IN ({q})", (team, *seasons)).fetchall():
        out.setdefault(r[0], {})[r[2]] = dict(cap=r[1], salary=r[3], bonus=r[4])
    return out
