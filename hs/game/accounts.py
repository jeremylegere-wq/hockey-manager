"""Financial statements (v54; docs/FINANCE.md "Financial statements"): a chart of accounts over the club's cash ledger,
a profit and loss report in the manner of an accounting package's (period, levels, monthly or quarterly columns,
budget and prior-year comparison, drill-down to the journal lines), the season's budget, a cash statement, and the
board's quarterly finance reviews.

The fiscal year runs July to June (FY 2026 = 1 July 2026 to 30 June 2027), as the league's clubs keep their books:
signing bonuses paid on 1 July open the year, the playoffs close it.

Chart of accounts (the ledger's categories, finance.py, mapped to accounts; three levels: section, group, account)
  4000 Revenue                       4110 regular-season gate, 4120 playoff gate, 4210 concessions and merchandise,
                                     4310 national media, 4320 local media, 4410 sponsorship, 4510 revenue sharing received
  5000 Cost of hockey operations     5110 player salaries, 5120 signing bonuses, 5210 hockey staff, 5310 team travel,
                                     5410 scouting, 5420 player development
  6000 Operating expenses            6110 game-day operations, 6120 building fixed costs, 6210 marketing,
                                     6310 administration, 6410 revenue sharing paid, 6910 other
  6500 Depreciation                  6510 arena improvements (renovations and new seats are capital: written off over
                                     ten years from the month after they are paid; not a cash cost)
  7000 Non-operating                 7110 interest earned, 7120 interest paid (the club's cash: 2% a year earned on a
                                     balance, 6% paid on an overdraft, monthly)
  8000 Owner                         8110 distributions to the owner, 8120 owner contributions (below the net result:
                                     equity, not profit)
Subtotals: total revenue; hockey operations margin (revenue less hockey operations); EBITDA (less operating
expenses); operating profit (less depreciation); net profit (after interest); retained (after the owner).

The budget: set when the season opens (opening night) for the whole fiscal year: July to September at what actually
happened, October to June planned from the schedule (home and road games by month), today's prices, the fans' mood
and last season's form, the contracts' cash, staff salaries and the club's budgets; no playoff revenue (budgets do not
assume the playoffs). Asked for before opening night, a provisional budget is drawn the same way with a standard
schedule and replaced at the opening.

The board (your club): on 1 October, 1 January, 1 April and 1 July the finance office reports the quarter just ended
(year to date against the budget, and the forecast: actual so far plus the budget for the rest of the year) and the
owner replies. How much he cares depends on his spending trait: an owner who spends 4 or less takes 2 confidence for
a net result $5M under budget and 4 for $10M, and gives 2 for $5M over; 5-6: -2 for $10M under, +1 for $10M over; 7+:
-1 for $20M under. The 1 July report is the annual report: no confidence change (the summer review reads the books).
"""
from __future__ import annotations

import calendar
import datetime
import json

from .state import add_message, get_state, user_team

INTEREST_EARNED, INTEREST_PAID = 0.02, 0.06            # a year, on the club's cash
DEPRECIATION_MONTHS = 120

# code: (name, level-2 group code)
ACCOUNTS = {
    "4110": "Regular-season gate", "4120": "Playoff gate", "4210": "Concessions and merchandise", "4310": "National media",
    "4320": "Local media", "4410": "Sponsorship", "4510": "Revenue sharing received",
    "5110": "Player salaries", "5120": "Signing bonuses", "5210": "Hockey staff", "5310": "Team travel", "5410": "Scouting",
    "5420": "Player development",
    "6110": "Game-day operations", "6120": "Building fixed costs", "6210": "Marketing", "6310": "Administration",
    "6410": "Revenue sharing paid", "6910": "Other",
    "6510": "Arena improvements",
    "7110": "Interest earned", "7120": "Interest paid", "7130": "Arena loan interest", "6520": "New arena",
    "8110": "Distributions to the owner", "8120": "Owner contributions",
}
GROUPS = {
    "4100": ("Ticketing", ["4110", "4120"]), "4200": ("Game day and retail", ["4210"]), "4300": ("Media rights", ["4310", "4320"]),
    "4400": ("Partnerships", ["4410"]), "4500": ("League revenue sharing", ["4510"]),
    "5100": ("Player compensation", ["5110", "5120"]), "5200": ("Hockey staff", ["5210"]), "5300": ("Team travel", ["5310"]),
    "5400": ("Player personnel", ["5410", "5420"]),
    "6100": ("Arena operations", ["6110", "6120"]), "6200": ("Sales and marketing", ["6210"]), "6300": ("General and administrative", ["6310"]),
    "6400": ("League assessments", ["6410"]), "6900": ("Other", ["6910"]),
    "6500": ("Depreciation", ["6510", "6520"]),
    "7100": ("Interest", ["7110", "7120", "7130"]),
    "8100": ("Owner", ["8110", "8120"]),
}
SECTIONS = [
    ("4000", "Revenue", ["4100", "4200", "4300", "4400", "4500"]),
    ("5000", "Cost of hockey operations", ["5100", "5200", "5300", "5400"]),
    ("S1", "Hockey operations margin", None),
    ("6000", "Operating expenses", ["6100", "6200", "6300", "6400", "6900"]),
    ("S2", "EBITDA", None),
    ("6500", "Depreciation", ["6500"]),
    ("S3", "Operating profit", None),
    ("7000", "Non-operating income and expenses", ["7100"]),
    ("S4", "Net profit", None),
    ("8000", "Owner", ["8100"]),
    ("S5", "Retained by the club", None),
]
SUBTOTAL_OF = {"S1": ["4000", "5000"], "S2": ["4000", "5000", "6000"], "S3": ["4000", "5000", "6000", "6500"],
               "S4": ["4000", "5000", "6000", "6500", "7000"], "S5": ["4000", "5000", "6000", "6500", "7000", "8000"]}
QUARTERS = {1: (7, 8, 9), 2: (10, 11, 12), 3: (1, 2, 3), 4: (4, 5, 6)}
STANDARD_HOME = {10: 6, 11: 7, 12: 7, 1: 6, 2: 5, 3: 7, 4: 3}      # 41 home games (and as many on the road) by month


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS finance_budget (team_id INTEGER, fy INTEGER, account TEXT, month TEXT, amount REAL, "
                 "PRIMARY KEY (team_id, fy, account, month))")
    conn.execute("CREATE TABLE IF NOT EXISTS finance_budget_meta (team_id INTEGER, fy INTEGER, built TEXT, status TEXT, note TEXT, "
                 "PRIMARY KEY (team_id, fy))")
    conn.execute("CREATE TABLE IF NOT EXISTS board_fin_reports (team_id INTEGER, fy INTEGER, quarter INTEGER, day TEXT, data TEXT, "
                 "comment TEXT, delta REAL, PRIMARY KEY (team_id, fy, quarter))")


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


# ---------------------------------------------------------------- the calendar
def fy_of(day):
    d = day if isinstance(day, datetime.date) else datetime.date.fromisoformat(str(day)[:10])
    return d.year if d.month >= 7 else d.year - 1


def fy_months(fy):
    return [f"{fy + (1 if m < 7 else 0)}-{m:02d}" for m in (7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6)]


def fy_label(fy):
    return f"FY {fy}-{(fy + 1) % 100:02d}"


def quarter_of(month):
    m = int(month[5:7])
    return next(q for q, ms in QUARTERS.items() if m in ms)


def period_months(fy, period, today=None):
    """period: 'year', 'ytd', 'q1'..'q4', or 'YYYY-MM'. Returns (months, label)."""
    ms = fy_months(fy)
    p = (period or "year").lower()
    if p == "ytd":
        cur = (today or "9999-12")[:7]
        sel = [m for m in ms if m <= cur]
        return sel or ms[:1], f"Year to date ({_mlabel(sel[-1]) if sel else _mlabel(ms[0])})"
    if p in ("q1", "q2", "q3", "q4"):
        q = int(p[1])
        return [m for m in ms if quarter_of(m) == q], f"Q{q} ({_mlabel(ms[3 * (q - 1)])} - {_mlabel(ms[3 * q - 1])})"
    if len(p) == 7 and p in ms:
        return [p], _mlabel(p)
    return ms, "Full year"


def _mlabel(m):
    return f"{calendar.month_abbr[int(m[5:7])]} {m[:4]}"


def _shift(m, years):
    return f"{int(m[:4]) + years}{m[4:]}"


# ---------------------------------------------------------------- the ledger as accounts
def account_of(category, detail, amount):
    d = (detail or "").lower()
    if category == "gate":
        return "4120" if d.startswith("playoff") else "4110"
    if category == "media":
        return "4310" if d == "national" else "4320"
    if category == "sharing":
        return "4510" if amount >= 0 else "6410"
    if category == "payroll":
        return "5120" if "bonus" in d else "5110"
    if category == "arena":
        return "6120" if d == "fixed" else "6110"
    if category == "interest":
        return "7110" if amount >= 0 else "7120"
    if category == "owner":
        return "8110" if amount < 0 else "8120"
    if category in ("arena_capital", "loan", "loan_principal"):
        return None                                      # capital and financing: on the cash statement (capital depreciated)
    if category == "loan_interest":
        return "7130"
    return {"concessions": "4210", "sponsorship": "4410", "staff": "5210", "travel": "5310", "scouting": "5410",
            "development": "5420", "marketing": "6210", "admin": "6310"}.get(category, "6910")


def _actuals(conn, t, months):
    """{account: {month: amount}} for the months (signed: revenue +, costs -)."""
    out = {}
    if not months or not _has(conn, "finance_ledger"):
        return out
    lo, hi = min(months) + "-01", max(months) + "-31"
    want = set(months)
    for cat, det, day, amt in conn.execute("SELECT category, detail, day, amount FROM finance_ledger WHERE team_id=? AND day>=? AND day<=?",
                                           (t, lo, hi)):
        m = day[:7]
        if m not in want:
            continue
        a = account_of(cat, det, amt)
        if a:
            out.setdefault(a, {})
            out[a][m] = out[a].get(m, 0) + amt
    for m, (v, va) in _depreciation(conn, t, months, split=True).items():
        if v:
            out.setdefault("6510", {})[m] = v
        if va:
            out.setdefault("6520", {})[m] = va
    return out


def _capital(conn, t):
    if not _has(conn, "finance_ledger"):
        return []
    return conn.execute("SELECT day, amount, detail FROM finance_ledger WHERE team_id=? AND category='arena_capital'", (t,)).fetchall()


def _months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def _depreciation(conn, t, months, split=False):
    """{month: -charge}: each capital payment written off from the month after it is paid: renovations and seats over
    ten years, a new arena (v57) over thirty. split: {month: (renovations, new arena)}."""
    caps = _capital(conn, t)
    out = {}
    for m in months:
        v = va = 0.0
        for day, amt, det in caps:
            k = _months_between(day[:7], m)
            arena = "new arena" in (det or "")
            life = 360 if arena else DEPRECIATION_MONTHS
            if 1 <= k <= life:
                if arena:
                    va += amt / life
                else:
                    v += amt / life
        out[m] = (round(v), round(va)) if split else round(v + va)
    return out


def fy_result(conn, t, fy, upto=None):
    """(revenue, costs, net profit) of the fiscal year (net profit before the owner; costs positive), through `upto`."""
    months = [m for m in fy_months(fy) if not upto or m <= upto[:7]]
    a = _actuals(conn, t, months)
    tot = {k: sum(v.values()) for k, v in a.items()}
    rev = sum(v for k, v in tot.items() if k[0] == "4" or k == "7110")
    net = sum(v for k, v in tot.items() if k[0] != "8")
    return rev, rev - net, net


# ---------------------------------------------------------------- the budget
def _schedule(conn, t, fy):
    """{month: (home, road)} for the fiscal year's regular season (a standard one if not drawn yet)."""
    r = conn.execute("SELECT season_id FROM seasons WHERE start_year=?", (fy,)).fetchone()
    out = {}
    if r:
        for d, h in conn.execute("SELECT game_date, home_team_id=? FROM games WHERE season_id=? AND game_type='RS' AND "
                                 "(home_team_id=? OR away_team_id=?)", (t, r[0], t, t)):
            m = d[:7]
            hh, rr = out.get(m, (0, 0))
            out[m] = (hh + (1 if h else 0), rr + (0 if h else 1))
    if not out:
        for m in fy_months(fy):
            n = STANDARD_HOME.get(int(m[5:7]), 0)
            if n:
                out[m] = (n, n)
    return out


def build_budget(conn, t, fy, day=None):
    """Draw the fiscal year's budget (replacing any)."""
    from . import finance as FN
    from . import ledger as LG
    ensure_tables(conn)
    day = day or get_state(conn)[0]
    f = FN.profile(conn, t)
    if f is None:
        return None
    opened = bool(conn.execute("SELECT 1 FROM seasons WHERE start_year=?", (fy,)).fetchone())
    months = fy_months(fy)
    summer = [m for m in months if int(m[5:7]) in (7, 8, 9)]
    actual = _actuals(conn, t, summer) if opened else {}
    sched = _schedule(conn, t, fy)
    # a typical game: about 45% of home games fall on a Friday to Sunday (demand +3%)
    we, wd = FN.demand(conn, t, f, day="2027-10-16"), FN.demand(conn, t, f, day="2027-10-13")
    dem = {k: 0.45 * we[k] + 0.55 * wd[k] for k in we}
    gate = sum(int(f["capacity"] * s) * min(1.0, dem[k]) * f[f"price_{k}"] for k, (s, _, _) in FN.SEATS.items())
    fans = sum(int(f["capacity"] * s) * min(1.0, dem[k]) for k, (s, _, _) in FN.SEATS.items())
    mood, pts = FN._mood(conn, t), FN._points_pct(conn, t)
    per_fan = FN.PER_FAN * (0.9 + 0.004 * (mood - 55))
    local = (6e6 + 2.2e6 * f["market"]) * (0.9 + 0.2 * mood / 100)
    spons = (9e6 + 2.4e6 * f["market"]) * (0.85 + 0.3 * pts)
    ms = [FN.profile(conn, x)["market"] for x in FN._top(conn)]
    n_small, n_big = sum(m <= 4 for m in ms), sum(m >= 8 for m in ms)
    share = 0.0
    if n_small and n_big:
        share = FN.SHARING if f["market"] <= 4 else -FN.SHARING * n_small / n_big if f["market"] >= 8 else 0.0
    try:
        salaries = LG.cash(conn, t, fy, "salary")
    except Exception:
        salaries = 0
    try:
        bonuses = LG.cash(conn, t, fy, "bonus")
    except Exception:
        bonuses = 0
    staff = conn.execute("SELECT COALESCE(SUM(salary), 0) FROM staff WHERE team_id=?", (t,)).fetchone()[0] if _has(conn, "staff") else 0
    cash = f["cash"]
    rate = INTEREST_EARNED if cash >= 0 else INTEREST_PAID
    dep = _depreciation(conn, t, months)
    lr = conn.execute("SELECT balance, rate FROM arena_loans WHERE team_id=?", (t,)).fetchone() if _has(conn, "arena_loans") else None
    loan_bal, loan_rate = (lr[0], lr[1]) if lr else (0, 0)
    rows = {}

    def put(a, m, v):
        if v:
            rows[(a, m)] = rows.get((a, m), 0) + v
    for m in months:
        mo = int(m[5:7])
        if opened and m in summer:
            for a, mv in actual.items():
                put(a, m, mv.get(m, 0))
            continue
        home, road = sched.get(m, (0, 0))
        put("4110", m, gate * home)
        put("4210", m, fans * per_fan * home)
        put("4310", m, FN.NATIONAL_MEDIA / 12)
        put("4320", m, local / 12)
        put("4410", m, spons / 12)
        put("4510" if share > 0 else "6410", m, share / 12)
        if mo in FN.SEASON_MONTHS:
            put("5110", m, -salaries / len(FN.SEASON_MONTHS))
        if mo == 7:
            put("5120", m, -bonuses)
        put("5210", m, -staff / 12)
        put("5310", m, -FN.TRAVEL_GAME * road)
        put("5410", m, -f["budget_scouting"] / 12)
        put("5420", m, -f["budget_development"] / 12)
        put("6110", m, -FN.ARENA_GAME * home)
        put("6120", m, -FN.ARENA_MONTH)
        put("6210", m, -f["budget_marketing"] / 12)
        put("6310", m, -FN.ADMIN_MONTH)
        put("6510", m, dep.get(m, 0))
        put("7110" if cash >= 0 else "7120", m, cash * rate / 12)
        if loan_bal:
            put("7130", m, -loan_bal * loan_rate / 12)
    conn.execute("DELETE FROM finance_budget WHERE team_id=? AND fy=?", (t, fy))
    conn.executemany("INSERT INTO finance_budget VALUES (?,?,?,?,?)", [(t, fy, a, m, round(v)) for (a, m), v in rows.items()])
    status = "approved" if opened else "provisional"
    note = ("July to September at actual; October to June planned from the schedule, today's prices and fans, last season's "
            "form and the contracts' cash; no playoff revenue") if opened else \
        "Provisional (before opening night): a standard schedule; it is redrawn when the season opens"
    conn.execute("INSERT OR REPLACE INTO finance_budget_meta VALUES (?,?,?,?,?)", (t, fy, day, status, note))
    return status


def ensure_budget(conn, t, fy):
    ensure_tables(conn)
    r = conn.execute("SELECT status FROM finance_budget_meta WHERE team_id=? AND fy=?", (t, fy)).fetchone()
    opened = bool(conn.execute("SELECT 1 FROM seasons WHERE start_year=?", (fy,)).fetchone())
    if r is None or (r[0] == "provisional" and opened):
        build_budget(conn, t, fy)


def _budget(conn, t, fy, months):
    ensure_budget(conn, t, fy)
    out = {}
    want = set(months)
    for a, m, v in conn.execute("SELECT account, month, amount FROM finance_budget WHERE team_id=? AND fy=?", (t, fy)):
        if m in want:
            out.setdefault(a, {})[m] = v
    return out


def budget_meta(conn, t, fy):
    ensure_budget(conn, t, fy)
    r = conn.execute("SELECT built, status, note FROM finance_budget_meta WHERE team_id=? AND fy=?", (t, fy)).fetchone()
    return dict(built=r[0], status=r[1], note=r[2]) if r else None


# ---------------------------------------------------------------- the report
GAME_ACCOUNTS = {"4110", "4120", "4210", "5310", "6110"}     # booked game by game; everything else on the 1st of the month


def _sum(data, accounts, months, weight=None):
    w = weight or {}
    return sum(data.get(a, {}).get(m, 0) * (w.get(m, 1.0) if a in GAME_ACCOUNTS else 1.0) for a in accounts for m in months)


def _partial(today):
    """{this month: share of it gone}: for the month under way, the budget and last year's figures for the accounts booked
    game by game are prorated by days (the rest is booked on the 1st, in full)."""
    d = datetime.date.fromisoformat(today)
    return {today[:7]: d.day / calendar.monthrange(d.year, d.month)[1]}


def _section_accounts(code):
    sec = next(s for s in SECTIONS if s[0] == code)
    return [a for g in sec[2] for a in GROUPS[g][1]]


def pnl(conn, t, fy=None, period=None, columns="total", compare="none", level=3, hide_zero=True):
    """The profit and loss report. columns: total | monthly | quarterly. compare (total columns only): none | budget |
    prior | both. level: 1 sections, 2 groups, 3 accounts."""
    ensure_tables(conn)
    today = get_state(conn)[0]
    fy = int(fy) if fy else fy_of(today)
    cur_fy = fy_of(today)
    period = period or ("ytd" if fy == cur_fy else "year")
    months, plabel = period_months(fy, period, today)
    level = max(1, min(3, int(level or 3)))
    act = _actuals(conn, t, months)
    cols = []
    if columns == "monthly":
        cols = [dict(key=m, label=_mlabel(m), src="act", months=[m]) for m in months]
    elif columns == "quarterly":
        for q in sorted({quarter_of(m) for m in months}, key=lambda q: [quarter_of(x) for x in fy_months(fy)].index(q)):
            qm = [m for m in months if quarter_of(m) == q]
            cols.append(dict(key=f"q{q}", label=f"Q{q}", src="act", months=qm))
    if columns in ("monthly", "quarterly"):
        cols.append(dict(key="total", label="Total", src="act", months=months))
        compare = "none"
    else:
        cols.append(dict(key="actual", label="Actual", src="act", months=months))
    bud = prior = None
    if compare in ("budget", "both"):
        bud = _budget(conn, t, fy, months)
        cols += [dict(key="budget", label="Budget", src="bud", months=months), dict(key="var_b", label="Variance", src="var", of="budget"),
                 dict(key="pct_b", label="% of budget", src="pct", of="budget")]
    if compare in ("prior", "both"):
        pm = [_shift(m, -1) for m in months]
        prior = _actuals(conn, t, pm)
        prior = {a: {_shift(m, 1): v for m, v in mv.items()} for a, mv in prior.items()}
        cols += [dict(key="prior", label=fy_label(fy - 1), src="pri", months=months), dict(key="var_p", label="Variance", src="var", of="prior"),
                 dict(key="pct_p", label="Change %", src="pct", of="prior")]

    part = _partial(today)

    def values(accounts):
        out = []
        base = {}
        for c in cols:
            if c["src"] in ("act", "bud", "pri"):
                data = {"act": act, "bud": bud or {}, "pri": prior or {}}[c["src"]]
                v = round(_sum(data, accounts, c["months"], None if c["src"] == "act" else part))
                base[c["key"]] = v
                out.append(v)
            elif c["src"] == "var":
                out.append(base["actual"] - base[c["of"]])
            else:
                b = base[c["of"]]
                if c["key"] == "pct_b":
                    out.append(round(100 * base["actual"] / b, 1) if b else None)
                else:
                    out.append(round(100 * (base["actual"] - b) / abs(b), 1) if b else None)
        return out
    rows = []
    for code, name, groups in SECTIONS:
        if groups is None:
            accs = [a for s in SUBTOTAL_OF[code] for a in _section_accounts(s)]
            rows.append(dict(code="", name=name, level=1, kind="subtotal", vals=values(accs)))
            continue
        accs = _section_accounts(code)
        rows.append(dict(code=code, name=name, level=1, kind="section", vals=values(accs), drill=code))
        if level >= 2:
            for g in groups:
                gname, gaccs = GROUPS[g]
                gv = values(gaccs)
                if hide_zero and not any(x for x, c in zip(gv, cols) if c["src"] in ("act", "bud", "pri")):
                    continue
                if level >= 3 and len(gaccs) == 1 and ACCOUNTS[gaccs[0]] == gname:
                    rows.append(dict(code=gaccs[0], name=gname, level=2, kind="account", vals=gv, drill=gaccs[0]))
                    continue
                rows.append(dict(code=g, name=gname, level=2, kind="group", vals=gv, drill=g))
                if level >= 3:
                    for a in gaccs:
                        av = values([a])
                        if hide_zero and not any(x for x, c in zip(av, cols) if c["src"] in ("act", "bud", "pri")):
                            continue
                        rows.append(dict(code=a, name=ACCOUNTS[a], level=3, kind="account", vals=av, drill=a))
    from . import finance as FN
    seasons = sorted({fy_of(r[0]) for r in conn.execute("SELECT DISTINCT substr(day,1,7)||'-01' FROM finance_ledger WHERE team_id=?", (t,))}
                     | {cur_fy}, reverse=True) if _has(conn, "finance_ledger") else [cur_fy]
    return dict(team_id=t, fy=fy, fy_label=fy_label(fy), fys=[dict(fy=x, label=fy_label(x)) for x in seasons], period=period,
                period_label=plabel, months=[dict(m=m, label=_mlabel(m)) for m in fy_months(fy)], columns=[dict(key=c["key"], label=c["label"],
                kind=c["src"]) for c in cols], rows=rows, compare=compare, layout=columns, level=level, hide_zero=bool(hide_zero),
                budget=budget_meta(conn, t, fy) if bud is not None else None, cash=FN.profile(conn, t)["cash"],
                note="Revenue and income are positive, costs negative; a positive variance is better than the comparison.")


def journal(conn, t, fy, code, period=None):
    """The journal lines behind an account, group or section for the period."""
    today = get_state(conn)[0]
    fy = int(fy) if fy else fy_of(today)
    months, plabel = period_months(fy, period or ("ytd" if fy == fy_of(today) else "year"), today)
    code = code or "4000"
    if code in GROUPS:
        accs, name = GROUPS[code][1], GROUPS[code][0]
    elif code in ACCOUNTS:
        accs, name = [code], ACCOUNTS[code]
    elif any(s[0] == code for s in SECTIONS if s[2]):
        accs, name = _section_accounts(code), next(s[1] for s in SECTIONS if s[0] == code)
    else:
        raise ValueError("No such account.")
    want = set(accs)
    lines = []
    lo, hi = min(months) + "-01", max(months) + "-31"
    for eid, day, cat, det, amt in conn.execute("SELECT entry_id, day, category, detail, amount FROM finance_ledger WHERE team_id=? AND "
                                                "day>=? AND day<=? ORDER BY day, entry_id", (t, lo, hi)):
        a = account_of(cat, det, amt)
        if a in want and day[:7] in months:
            lines.append(dict(entry=eid, day=day, account=a, account_name=ACCOUNTS[a], detail=det or cat, amount=amt))
    if "6510" in want or "6520" in want:
        for m, (v, va) in _depreciation(conn, t, months, split=True).items():
            if v and "6510" in want:
                lines.append(dict(entry=None, day=m + "-01", account="6510", account_name=ACCOUNTS["6510"],
                                  detail="depreciation (non-cash): arena improvements over ten years", amount=v))
            if va and "6520" in want:
                lines.append(dict(entry=None, day=m + "-01", account="6520", account_name=ACCOUNTS["6520"],
                                  detail="depreciation (non-cash): the new arena over thirty years", amount=va))
        lines.sort(key=lambda x: x["day"])
    return dict(code=code, name=name, fy=fy, period_label=plabel, lines=lines[-600:], total=sum(x["amount"] for x in lines),
                count=len(lines))


def cash_statement(conn, t, fy=None):
    from . import finance as FN
    today = get_state(conn)[0]
    fy = int(fy) if fy else fy_of(today)
    months = fy_months(fy)
    lo, hi = months[0] + "-01", months[-1] + "-31"
    s = lambda where, args=(): conn.execute(f"SELECT COALESCE(SUM(amount), 0) FROM finance_ledger WHERE team_id=? AND {where}", (t, *args)).fetchone()[0]
    after = s("day>?", (hi,))
    inside = s("day>=? AND day<=?", (lo, hi))
    close = FN.profile(conn, t)["cash"] - after
    capex = s("day>=? AND day<=? AND category='arena_capital'", (lo, hi))
    owner = s("day>=? AND day<=? AND category='owner'", (lo, hi))
    fin = s("day>=? AND day<=? AND category IN ('loan', 'loan_principal')", (lo, hi))
    rev, cost, net = fy_result(conn, t, fy)
    dep = -sum(_depreciation(conn, t, months).values())
    return dict(fy=fy, fy_label=fy_label(fy), opening=round(close - inside), net_profit=round(net), depreciation=round(dep),
                operating=round(inside - capex - owner - fin), capital=round(capex), owner=round(owner), financing=round(fin),
                closing=round(close),
                to_date=fy == fy_of(today))


# ---------------------------------------------------------------- the board
def _ytd(conn, t, fy, upto_month, part=None):
    months = [m for m in fy_months(fy) if m <= upto_month]
    act = _actuals(conn, t, months)
    bud = _budget(conn, t, fy, fy_months(fy))
    res = {}
    for key, secs in (("revenue", ["4000"]), ("hockey", ["5000"]), ("opex", ["6000"]), ("ebitda", SUBTOTAL_OF["S2"]), ("net", SUBTOTAL_OF["S4"]),
                      ("players", None)):
        accs = ["5110", "5120"] if secs is None else [a for s in secs for a in _section_accounts(s)]
        a = _sum(act, accs, months)
        b = _sum(bud, accs, months, part)
        rest = [m for m in fy_months(fy) if m > upto_month]
        left = sum(_sum(bud, [x for x in accs if x in GAME_ACCOUNTS], [m]) * (1 - f) for m, f in (part or {}).items() if m in months)
        res[key] = dict(actual=round(a), budget=round(b), var=round(a - b), full_budget=round(_sum(bud, accs, fy_months(fy))),
                        forecast=round(a + _sum(bud, accs, rest) + left))
    return res


def _owner(conn, t):
    if not _has(conn, "owners"):
        return dict(name="The owner", spend=5, archetype="")
    r = conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone()
    if r is None:
        return dict(name="The owner", spend=5, archetype="")
    d = dict(r)
    return dict(name=d.get("name") or "The owner", spend=d.get("spend") or 5, archetype=d.get("archetype") or "")


def board_delta(spend, gap):
    """Confidence change for a net result `gap` dollars against the budget, by the owner's spending trait."""
    if spend <= 4:
        return -4 if gap <= -10e6 else -2 if gap <= -5e6 else 2 if gap >= 5e6 else 0
    if spend <= 6:
        return -2 if gap <= -10e6 else 1 if gap >= 10e6 else 0
    return -1 if gap <= -20e6 else 0


def _comment(o, gap, fc_net, quarter):
    frugal, lavish = o["spend"] <= 4, o["spend"] >= 7
    if quarter == 4:
        lead = "The year is closed. "
    else:
        lead = ""
    if gap <= -10e6:
        txt = ("This is not acceptable. We approved a budget and you are well outside it. I expect a plan to close the gap by the "
               "next report." if frugal else "We are well behind the budget. Winning covers a lot, but the board needs to see costs "
               "under control." if not lavish else "We are behind the numbers. I care about the banner more than the books, "
               "but do not make me write cheques I did not plan for.")
    elif gap <= -5e6:
        txt = ("We are drifting from the budget. Watch the payroll and the discretionary spending." if frugal else
               "A little behind plan. Nothing alarming yet.")
    elif gap >= 5e6:
        txt = ("Ahead of budget. That is how I like to see this club run." if frugal else
               "Ahead of plan: good work from the business side." if not lavish else
               "Ahead of plan. If there is a player out there who makes us better, the money is there.")
    else:
        txt = "In line with the budget. Carry on."
    if fc_net < -20e6 and not lavish:
        txt += f" The forecast is a loss of ${-fc_net / 1e6:.1f}M for the year; the board will not underwrite that indefinitely."
    return lead + txt


def quarterly_review(conn, t, fy, quarter, day):
    """The finance office's report for the quarter just ended, the owner's reply, and the confidence change."""
    ensure_tables(conn)
    if conn.execute("SELECT 1 FROM board_fin_reports WHERE team_id=? AND fy=? AND quarter=?", (t, fy, quarter)).fetchone():
        return None
    upto = fy_months(fy)[3 * quarter - 1]
    y = _ytd(conn, t, fy, upto)
    o = _owner(conn, t)
    gap = y["net"]["var"]
    delta = 0 if quarter == 4 else board_delta(o["spend"], gap)
    comment = _comment(o, gap, y["net"]["forecast"], quarter)
    fill = None
    if _has(conn, "attendance"):
        fill = conn.execute("SELECT AVG(1.0 * total / capacity) FROM attendance WHERE team_id=? AND day>=? AND day<=?",
                            (t, fy_months(fy)[0] + "-01", upto + "-31")).fetchone()[0]
    from . import finance as FN
    cash = FN.profile(conn, t)["cash"]
    data = dict(ytd=y, cash=cash, fill=fill, upto=upto, owner=o["name"], spend=o["spend"])
    if delta and _has(conn, "board") and conn.execute("SELECT 1 FROM board WHERE team_id=?", (t,)).fetchone():
        from . import org
        org._apply(conn, t, delta, "finance", day, [f"Q{quarter} finance report: net result ${gap / 1e6:+.1f}M against budget {delta:+d}"])
    conn.execute("INSERT INTO board_fin_reports VALUES (?,?,?,?,?,?,?)", (t, fy, quarter, day, json.dumps(data), comment, delta))
    m = lambda v: f"{'-' if v < 0 else ''}${abs(v) / 1e6:,.1f}M"
    title = "Annual report" if quarter == 4 else f"Q{quarter} finance report"
    rows = [("Revenue", "revenue"), ("Hockey operations", "hockey"), ("Operating expenses", "opex"), ("EBITDA", "ebitda"), ("Net profit", "net")]
    body = (f"From the finance office: the {'annual report' if quarter == 4 else f'Q{quarter} report'} for {fy_label(fy)}, the year to the end of "
            f"{_mlabel(upto)}.\n"
            + "\n".join(f"- {lab}: {m(y[k]['actual'])} against a budget of {m(y[k]['budget'])} (variance {'+' if y[k]['var'] >= 0 else ''}{m(y[k]['var'])})"
                        for lab, k in rows)
            + (f"\n- Forecast for the year: net {m(y['net']['forecast'])} (budget {m(y['net']['full_budget'])})" if quarter < 4 else "")
            + f"\n- Cash: {m(cash)}" + (f"; the building {fill * 100:.1f}% full on average" if fill else "")
            + f"\n\n{o['name']}, the owner: \"{comment}\""
            + (f"\nBoard confidence {delta:+d}." if delta else ""))
    if t == user_team(conn):
        add_message(conn, day, f"{title}: {fy_label(fy)}", body, sender="The finance office",
                    actions=[{"label": "Open the board pack", "href": "#statements/board"}, {"label": "Profit and loss", "href": "#statements"}])
    return dict(quarter=quarter, delta=delta, comment=comment)


def on_month(conn, day):
    """Called by finance.monthly on the first of each month: your budget, and the board's quarterly review."""
    t = user_team(conn)
    if t is None:
        return
    ensure_tables(conn)
    fy = fy_of(day)
    if conn.execute("SELECT 1 FROM seasons WHERE start_year=?", (fy,)).fetchone():
        ensure_budget(conn, t, fy)
    d = datetime.date.fromisoformat(day)
    prev = (d.replace(day=1) - datetime.timedelta(days=1))
    if prev.month in (9, 12, 3, 6):
        pfy = fy_of(prev)
        if not conn.execute("SELECT 1 FROM finance_ledger WHERE team_id=? AND day LIKE ?", (t, prev.strftime("%Y-%m") + "%")).fetchone():
            return
        q = {9: 1, 12: 2, 3: 3, 6: 4}[prev.month]
        quarterly_review(conn, t, pfy, q, day)


def board_pack(conn, t):
    """The board's view: KPIs year to date against the budget, the forecast, the monthly trend, the reports."""
    ensure_tables(conn)
    from . import finance as FN
    today = get_state(conn)[0]
    fy = fy_of(today)
    cur = today[:7]
    y = _ytd(conn, t, fy, cur, _partial(today))
    months = fy_months(fy)
    act = _actuals(conn, t, months)
    bud = _budget(conn, t, fy, months)
    net_accs = [a for s in SUBTOTAL_OF["S4"] for a in _section_accounts(s)]
    trend = []
    ca = cb = 0
    for m in months:
        a = _sum(act, net_accs, [m]) if m <= cur else None
        b = _sum(bud, net_accs, [m])
        cb += b
        if a is not None:
            ca += a
        trend.append(dict(m=m, label=_mlabel(m), actual=round(a) if a is not None else None, budget=round(b),
                          cum_actual=round(ca) if a is not None else None, cum_budget=round(cb)))
    fill = fans = None
    if _has(conn, "attendance"):
        r = conn.execute("SELECT AVG(1.0 * total / capacity), SUM(total) FROM attendance WHERE team_id=? AND day>=?", (t, months[0] + "-01")).fetchone()
        fill, fans = r[0], r[1]
    fan_rev = _sum(act, ["4110", "4120", "4210"], months)
    # the league: year to date, every club
    league = []
    for x in FN._top(conn):
        rev, cost, net = fy_result(conn, x, fy, today)
        league.append(dict(team_id=x, abbr=conn.execute("SELECT abbr FROM teams WHERE team_id=?", (x,)).fetchone()[0], revenue=round(rev),
                           net=round(net), cash=round(FN.profile(conn, x)["cash"])))
    by_rev = sorted(league, key=lambda r: -r["revenue"])
    by_net = sorted(league, key=lambda r: -r["net"])
    o = _owner(conn, t)
    reports = [dict(fy=r[0], fy_label=fy_label(r[0]), quarter=r[1], day=r[2], comment=r[4], delta=r[5], data=json.loads(r[3]))
               for r in conn.execute("SELECT fy, quarter, day, data, comment, delta FROM board_fin_reports WHERE team_id=? ORDER BY day DESC", (t,))]
    nxt = next((f"{int(m[:4]) + (1 if m[5:7] == '12' else 0)}-{(int(m[5:7]) % 12) + 1:02d}-01" for m in months
                if m >= cur and int(m[5:7]) in (9, 12, 3, 6)), None)
    watch = ("every dollar: he reads the books against the budget each quarter" if o["spend"] <= 4 else
             "the bottom line, within reason" if o["spend"] <= 6 else "results on the ice first; the books only if they go badly wrong")
    pay_fc = -y["players"]["forecast"]
    return dict(fy=fy, fy_label=fy_label(fy), today=today, kpis=y, cash=round(FN.profile(conn, t)["cash"]), fill=fill, fans=fans,
                per_fan=round(fan_rev / fans) if fans else None, payroll_share=round(100 * pay_fc / y["revenue"]["forecast"], 1)
                if y["revenue"]["forecast"] else None, trend=trend, rank_revenue=[r["team_id"] for r in by_rev].index(t) + 1,
                rank_net=[r["team_id"] for r in by_net].index(t) + 1, clubs=len(league), league=by_net,
                owner=dict(o, watches=watch), reports=reports, next_review=nxt, budget=budget_meta(conn, t, fy),
                cash_statement=cash_statement(conn, t, fy))
