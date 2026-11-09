"""A new arena (v57; docs/FINANCE.md "A new arena"): proposed in the offseason, approved by the owner, built over two
seasons, paid for by the owner's contribution and a loan, opened with a new capacity and quality and a few seasons of
novelty at the gate.

Cost         capacity x $22,000 x (0.6 + 0.4 x quality / 90): 18,000 seats at quality 90 cost $396M
Capacity     15,000-21,000 seats; quality 70-95
The owner    pays 20% + 6% x his spending trait (spending 5: 50%), as contributions; the club borrows the rest
Approval     he says no to a second project, to a club whose arena is already rated 80+, when board confidence is under
             45, or when his share would be more than $40M x his spending trait
Building     24 months from the month after approval: the cost leaves as capital spending, the owner's share arrives as
             his contribution, the loan is drawn down, a 24th each month
The loan     5% a year, repaid monthly over 25 years from the opening (interest on the profit and loss as 7130 arena loan
             interest; the drawdowns and the principal are financing, on the cash statement)
Opening      at the preseason two seasons after approval: the new capacity (the seat types keep their shares) and
             quality; demand +8% in the first season, fading to nothing over five
Accounts     the building is depreciated over 30 years (6520 new arena), renovations over 10 as before
"""
from __future__ import annotations

import datetime
import math

from . import contracts as K
from .state import add_message, get_state, user_team

SEAT_COST = 22_000
CAP_RANGE, QUAL_RANGE = (15_000, 21_000), (70, 95)
LOAN_RATE, LOAN_YEARS, BUILD_MONTHS = 0.05, 25, 24
NOVELTY, NOVELTY_YEARS = 0.08, 5
DEPRECIATION_MONTHS = 360


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS arena_projects (project_id INTEGER PRIMARY KEY, team_id INTEGER, approved TEXT, "
                 "opens_season INTEGER, capacity INTEGER, quality REAL, cost REAL, owner_share REAL, loan REAL, months_paid INTEGER DEFAULT 0, "
                 "status TEXT DEFAULT 'building', opened TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS arena_loans (team_id INTEGER PRIMARY KEY, balance REAL, rate REAL, payment REAL, start TEXT)")


def cost_of(capacity, quality):
    return capacity * SEAT_COST * (0.6 + 0.4 * quality / 90)


def owner_share(spend):
    return max(0.2, min(0.8, 0.2 + 0.06 * spend))


def _spend(conn, t):
    r = conn.execute("SELECT spend FROM owners WHERE team_id=?", (t,)).fetchone() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone() else None
    return (r[0] if r else 5) or 5


def quote(conn, t, capacity, quality):
    """What a project would cost and who pays, and whether the owner would approve it: dict(..., ok, why)."""
    from . import finance as FN
    ensure_tables(conn)
    capacity, quality = int(capacity), float(quality)
    cost = cost_of(capacity, quality)
    spend = _spend(conn, t)
    share = owner_share(spend)
    f = FN.profile(conn, t)
    why = None
    if not CAP_RANGE[0] <= capacity <= CAP_RANGE[1]:
        why = f"Capacity runs from {CAP_RANGE[0]:,} to {CAP_RANGE[1]:,} seats."
    elif not QUAL_RANGE[0] <= quality <= QUAL_RANGE[1]:
        why = f"Quality runs from {QUAL_RANGE[0]} to {QUAL_RANGE[1]}."
    elif conn.execute("SELECT 1 FROM arena_projects WHERE team_id=?", (t,)).fetchone():
        why = "The owner has built his arena: there will not be another."
    elif f["arena_quality"] >= 80:
        why = f"The owner sees no need: the building is rated {f['arena_quality']:.0f}. Renovate instead."
    elif conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone() and \
            conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0] < 45:
        why = "The board does not trust you with a project this size (confidence under 45)."
    elif cost * share > 40_000_000 * spend:
        why = f"The owner will not put in ${cost * share / 1e6:,.0f}M (at most ${40 * spend}M from him)."
    loan = cost * (1 - share)
    r = LOAN_RATE / 12
    n = LOAN_YEARS * 12
    pay = loan * r / (1 - (1 + r) ** -n)
    return dict(capacity=capacity, quality=quality, cost=round(cost), owner_share=round(cost * share), owner_pct=round(share * 100),
                loan=round(loan), payment=round(pay), yearly=round(pay * 12), interest_first_year=round(loan * LOAN_RATE),
                opens=(K.signing_year(conn) + 2) if K.season_state(conn) not in ("regular_season", "playoffs") else K.season_year(conn) + 3,
                ok=why is None, why=why)


def propose(conn, t, capacity, quality, day=None):
    """Offseason only: the owner approves the project (or says why not)."""
    if K.season_state(conn) in ("regular_season", "playoffs"):
        raise ValueError("A new arena is planned in the offseason.")
    q = quote(conn, t, capacity, quality)
    if not q["ok"]:
        raise ValueError(q["why"])
    day = day or get_state(conn)[0]
    conn.execute("INSERT INTO arena_projects (team_id, approved, opens_season, capacity, quality, cost, owner_share, loan) VALUES (?,?,?,?,?,?,?,?)",
                 (t, day, q["opens"], q["capacity"], q["quality"], q["cost"], q["owner_share"], q["loan"]))
    if t == user_team(conn):
        add_message(conn, day, "The new arena is approved",
                    f"The owner has approved a new {q['capacity']:,}-seat arena (quality {q['quality']:.0f}) for ${q['cost'] / 1e6:,.0f}M, "
                    f"to open for the {q['opens']}-{(q['opens'] + 1) % 100:02d} season. He puts in ${q['owner_share'] / 1e6:,.0f}M "
                    f"({q['owner_pct']}%); the club borrows ${q['loan'] / 1e6:,.0f}M at {LOAN_RATE * 100:.0f}% over {LOAN_YEARS} years "
                    f"(about ${q['yearly'] / 1e6:,.1f}M a year from the opening). Construction is paid month by month over two years.",
                    sender="The owner", actions=[{"label": "Finances", "href": "#finances"}])
    return q


def monthly(conn, day, post):
    """On the 1st of each month (from finance.monthly): construction payments and the loan's repayments. post(t, day,
    category, amount, detail) books an entry."""
    ensure_tables(conn)
    for p in conn.execute("SELECT * FROM arena_projects WHERE status='building' AND months_paid<? AND approved<?", (BUILD_MONTHS, day)).fetchall():
        part = 1 / BUILD_MONTHS
        post(p["team_id"], day, "arena_capital", -p["cost"] * part, "new arena (construction)")
        post(p["team_id"], day, "owner", p["owner_share"] * part, "the owner's contribution to the new arena")
        post(p["team_id"], day, "loan", p["loan"] * part, "arena loan drawdown")
        conn.execute("UPDATE arena_projects SET months_paid=months_paid+1 WHERE project_id=?", (p["project_id"],))
    for t, bal, rate, pay, start in conn.execute("SELECT team_id, balance, rate, payment, start FROM arena_loans WHERE balance>0 AND start<=?",
                                                 (day,)).fetchall():
        interest = bal * rate / 12
        principal = min(bal, pay - interest)
        post(t, day, "loan_interest", -interest, "arena loan interest")
        post(t, day, "loan_principal", -principal, "arena loan repayment")
        conn.execute("UPDATE arena_loans SET balance=? WHERE team_id=?", (max(0.0, bal - principal), t))


def on_preseason(conn, day):
    """Open the arenas whose season it is."""
    ensure_tables(conn)
    season = K.signing_year(conn)
    out = []
    for p in conn.execute("SELECT * FROM arena_projects WHERE status='building' AND opens_season<=?", (season,)).fetchall():
        conn.execute("UPDATE club_finance SET capacity=?, arena_quality=? WHERE team_id=?", (p["capacity"], p["quality"], p["team_id"]))
        conn.execute("UPDATE arena_projects SET status='open', opened=? WHERE project_id=?", (day, p["project_id"]))
        drawn = p["loan"] * min(BUILD_MONTHS, p["months_paid"]) / BUILD_MONTHS
        r = LOAN_RATE / 12
        n = LOAN_YEARS * 12
        pay = drawn * r / (1 - (1 + r) ** -n) if drawn else 0
        start = (datetime.date.fromisoformat(day).replace(day=1) + datetime.timedelta(days=32)).replace(day=1).isoformat()
        conn.execute("INSERT OR REPLACE INTO arena_loans VALUES (?,?,?,?,?)", (p["team_id"], drawn, LOAN_RATE, pay, start))
        if p["team_id"] == user_team(conn):
            add_message(conn, day, "The new arena opens", f"The new building opens this season: {p['capacity']:,} seats, quality "
                        f"{p['quality']:.0f}. Expect a full house: the novelty is worth about {NOVELTY * 100:.0f}% at the gate this season, "
                        f"fading over {NOVELTY_YEARS}. Loan repayments of ${pay / 1e6:,.2f}M a month start next month.", sender="Business operations")
        out.append(p["team_id"])
    return out


def novelty(conn, t):
    """The demand bump from a new building: +8% in its first season, fading to nothing over five."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='arena_projects'").fetchone():
        return 0.0
    r = conn.execute("SELECT opens_season FROM arena_projects WHERE team_id=? AND status='open'", (t,)).fetchone()
    if not r:
        return 0.0
    age = K.season_year(conn) - r[0]
    return max(0.0, NOVELTY * (1 - age / NOVELTY_YEARS))


def view(conn, t):
    ensure_tables(conn)
    p = conn.execute("SELECT * FROM arena_projects WHERE team_id=? ORDER BY project_id DESC LIMIT 1", (t,)).fetchone()
    loan = conn.execute("SELECT * FROM arena_loans WHERE team_id=?", (t,)).fetchone()
    from . import finance as FN
    f = FN.profile(conn, t)
    default = quote(conn, t, max(CAP_RANGE[0], min(CAP_RANGE[1], int(round(f["capacity"] / 500) * 500) + 500)), 90)
    return dict(project=dict(p) if p else None, loan=dict(loan) if loan else None, novelty=round(novelty(conn, t), 3), quote=default,
                ranges=dict(capacity=CAP_RANGE, quality=QUAL_RANGE), seat_cost=SEAT_COST, rate=LOAN_RATE, years=LOAN_YEARS,
                offseason=K.season_state(conn) not in ("regular_season", "playoffs"))
