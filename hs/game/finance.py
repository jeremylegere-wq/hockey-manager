"""Club finances (phase C, v34): the gate, the rest of the revenue, the costs, budgets, ticket prices, the arena, and
the owner's cut. Numbers are this game's own (round, plausible magnitudes for a top league), not any club's books.

Each club has a profile (club_finance): its market (1-10), arena capacity and quality, prices for three seat types,
three budgets (scouting, development, marketing) and its cash. Every regular-season and playoff home game sells
seats (attendance) by demand; the rest arrives and leaves month by month (finance_ledger), and the season closes with
the owner's cut and a summary (finance_season).

Attendance, per seat type (lower bowl 44% of seats, upper bowl 50%, premium 6%):
    demand = 0.92 + 0.003 x (fan sentiment - 55) + 0.30 x (points % - 0.5) + 0.012 x (market - 5)
             + 0.0015 x (arena quality - 60) + weekend 0.03 + a rival 0.03 + noise
             x (price / the club's reference price) ^ -elasticity   (lower 1.1, upper 1.35, premium 0.8)
    sold = capacity of the type x min(1, demand); playoffs: a full house at 1.6 x the price
The fans' mood (hs/game/press.py) therefore reaches the gate (the second half of defect 12).

Other revenue: concessions and merchandise per fan ($40, more when the fans are happy), national media ($30M a year,
the same for everyone), local media ($6M + $2.2M x market), sponsorship ($9M + $2.4M x market, more when winning).
Revenue sharing: each club in a market of 4 or under receives $12M a year, paid by the clubs in markets of 8 and up.
Costs: player payroll (v41: the contracts' cash, salaries paid over the seven months of the regular season and signing bonuses on 1 July; hs/game/ledger.py), staff salaries, arena
operations ($0.7M a home game and $1.1M a month), travel ($0.25M a road game), administration ($1.4M a month), and the
three budgets. At the season's close the owner takes a share of a profit (more if he spends little) or covers part of
a loss (more if he spends freely).

Budgets (the club's choice, per year; the league default for each is what every AI club spends, so they are neutral
league-wide): scouting moves your scouts' error (up to 15% either way), development your development rate (up to
+5% / -4%), marketing the fans' mood (up to 0.5 a week either way).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import random

from .state import add_message, get_state, user_team

SEATS = {"lower": (0.44, 1.35, 1.10), "upper": (0.50, 0.70, 1.35), "premium": (0.06, 3.60, 0.80)}   # share, price x, elasticity
BASE_PRICE = 95.0
BUDGETS = {"scouting": 3_000_000, "development": 4_000_000, "marketing": 3_000_000}
BUDGET_RANGE = (0.25, 3.0)                        # x the default
PER_FAN, NATIONAL_MEDIA = 40.0, 30_000_000
ARENA_GAME, ARENA_MONTH, TRAVEL_GAME, ADMIN_MONTH = 700_000, 1_100_000, 250_000, 1_400_000
SEASON_MONTHS = (10, 11, 12, 1, 2, 3, 4)
SHARING = 12_000_000                  # a year, to each club in a market of 4 or under
# a club's market, 1-10: a few of the league's biggest and smallest are set; the rest come from the club's name
MARKET = {"TOR": 10, "NYR": 10, "MTL": 9, "CHI": 9, "LAK": 8, "BOS": 8, "PHI": 8, "DET": 7, "VAN": 7, "EDM": 6, "CGY": 6,
          "WSH": 7, "DAL": 7, "PIT": 6, "NYI": 6, "NJD": 6, "SEA": 6, "COL": 6, "VGK": 6, "MIN": 6, "TBL": 5, "FLA": 5,
          "ANA": 5, "SJS": 5, "STL": 5, "OTT": 5, "BUF": 4, "CAR": 4, "NSH": 4, "UTA": 4, "CBJ": 4, "WPG": 3}
RIVALS = {"TOR": "MTL", "MTL": "TOR", "NYR": "NYI", "NYI": "NYR", "EDM": "CGY", "CGY": "EDM", "BOS": "MTL", "PIT": "PHI",
          "PHI": "PIT", "CHI": "DET", "DET": "CHI", "LAK": "ANA", "ANA": "LAK", "VAN": "SEA", "SEA": "VAN"}


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS club_finance (team_id INTEGER PRIMARY KEY, market INTEGER, capacity INTEGER, "
                 "arena_quality REAL, price_lower REAL, price_upper REAL, price_premium REAL, budget_scouting REAL, "
                 "budget_development REAL, budget_marketing REAL, cash REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS finance_ledger (entry_id INTEGER PRIMARY KEY, team_id INTEGER, day TEXT, season INTEGER, "
                 "category TEXT, amount REAL, detail TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS finance_ledger_team ON finance_ledger (team_id, season)")
    conn.execute("CREATE TABLE IF NOT EXISTS attendance (game_id INTEGER PRIMARY KEY, team_id INTEGER, season INTEGER, day TEXT, "
                 "lower INTEGER, upper INTEGER, premium INTEGER, total INTEGER, capacity INTEGER, gate REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS finance_season (team_id INTEGER, season INTEGER, revenue REAL, costs REAL, profit REAL, "
                 "owner REAL, fill REAL, detail TEXT, PRIMARY KEY (team_id, season))")


def _top(conn):
    from ..schema import top_league_sql
    return [r[0] for r in conn.execute(f"SELECT team_id, abbr FROM teams WHERE {top_league_sql()} ORDER BY team_id")]


def _market(abbr):
    if abbr in MARKET:
        return MARKET[abbr]
    return 3 + int(hashlib.md5(abbr.encode()).hexdigest(), 16) % 6


def ref_price(market):
    return BASE_PRICE * (0.80 + 0.04 * market)


def setup(conn):
    """Profiles for clubs that have none (a new game, or a save from before v34)."""
    ensure_tables(conn)
    for t in _top(conn):
        if conn.execute("SELECT 1 FROM club_finance WHERE team_id=?", (t,)).fetchone():
            continue
        ab = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()[0]
        m = _market(ab)
        rng = random.Random(f"finance-{ab}")
        cap = int(round(17_200 + (m - 5) * 350 + rng.gauss(0, 500), -1))
        if _has(conn, "club_profile"):                   # v38: an imported database's arena and market
            cp = conn.execute("SELECT capacity, market FROM club_profile WHERE team_id=?", (t,)).fetchone()
            if cp:
                cap = cp[0] or cap
                m = cp[1] or m
        p = ref_price(m)
        conn.execute("INSERT INTO club_finance VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (t, m, max(14_500, min(21_500, cap)), round(max(35, min(92, rng.gauss(62, 12))), 1),
                      round(p * SEATS["lower"][1]), round(p * SEATS["upper"][1]), round(p * SEATS["premium"][1]),
                      BUDGETS["scouting"], BUDGETS["development"], BUDGETS["marketing"], 20_000_000 + m * 3_000_000))


def profile(conn, t):
    setup(conn)
    r = conn.execute("SELECT * FROM club_finance WHERE team_id=?", (t,)).fetchone()
    return dict(r) if r else None


def _season(conn):
    from .contracts import season_year
    return season_year(conn)


def _post(conn, t, day, cat, amount, detail=""):
    conn.execute("INSERT INTO finance_ledger (team_id, day, season, category, amount, detail) VALUES (?,?,?,?,?,?)",
                 (t, day, _season(conn), cat, round(amount), detail))
    conn.execute("UPDATE club_finance SET cash=cash+? WHERE team_id=?", (round(amount), t))


def _mood(conn, t):
    if not _has(conn, "media_state"):
        return 55.0
    r = conn.execute("SELECT fan_sentiment FROM media_state WHERE team_id=?", (t,)).fetchone()
    return r[0] if r else 55.0


def _points_pct(conn, t):
    r = conn.execute("SELECT SUM(CASE WHEN (home_team_id=? AND home_goals>away_goals) OR (away_team_id=? AND away_goals>home_goals) THEN 2 "
                     "WHEN went_to_ot>0 THEN 1 ELSE 0 END), COUNT(*) FROM games g JOIN seasons s USING (season_id) WHERE played=1 AND "
                     "game_type='RS' AND (home_team_id=? OR away_team_id=?) AND s.start_year=?", (t, t, t, t, _season(conn))).fetchone()
    if not r or not r[1]:
        prev = conn.execute("SELECT pts, gp FROM team_seasons WHERE team_id=? ORDER BY season_start_year DESC LIMIT 1", (t,)).fetchone() \
            if _has(conn, "team_seasons") else None
        return (prev[0] / (2 * prev[1])) if prev and prev[1] else 0.5
    return r[0] / (2 * r[1])


def _rival_bump(conn, t, opp_abbr):
    """v37: +3% for a rivalry (hs/game/rivalry.py), +5% heated or bitter."""
    if not opp_abbr:
        return 0.0
    o = conn.execute("SELECT team_id FROM teams WHERE abbr=?", (opp_abbr,)).fetchone()
    if not o:
        return 0.0
    from . import rivalry as RV
    p = RV.points(conn, t, o[0])
    return 0.05 if p >= 70 else 0.03 if p >= RV.BIG else 0.0


def _novelty(conn, t):
    """v57: a new arena's first seasons (hs/game/arena.py)."""
    try:
        from .arena import novelty
        return novelty(conn, t)
    except Exception:
        return 0.0


def demand(conn, t, f, opp_abbr=None, day=None, rng=None):
    """Fraction of each seat type sold for a home game (before the capacity cap)."""
    mood, pts = _mood(conn, t), _points_pct(conn, t)
    d = datetime.date.fromisoformat(day) if day else None
    ab = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()[0]
    base = (0.92 + 0.003 * (mood - 55) + 0.30 * (pts - 0.5) + 0.012 * (f["market"] - 5) + 0.0015 * (f["arena_quality"] - 60)
            + (0.03 if d and d.weekday() >= 4 else 0) + _rival_bump(conn, t, opp_abbr) + _novelty(conn, t)
            + (rng.gauss(0, 0.025) if rng else 0))
    ref = ref_price(f["market"])
    out = {}
    for k, (share, mult, el) in SEATS.items():
        price = f[f"price_{k}"]
        out[k] = max(0.15, base * (price / (ref * mult)) ** (-el))
    return out


def home_game(conn, gid, day, playoff=False):
    """Seats, the gate and the concessions for one home game (idempotent per game)."""
    if conn.execute("SELECT 1 FROM attendance WHERE game_id=?", (gid,)).fetchone():
        return None
    g = conn.execute("SELECT home_team_id, away_team_id FROM games WHERE game_id=?", (gid,)).fetchone()
    t, opp = g[0], g[1]
    f = profile(conn, t)
    if f is None:
        return None
    opp_ab = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (opp,)).fetchone()[0]
    rng = random.Random(f"gate-{gid}")
    dem = {k: 1.0 for k in SEATS} if playoff else demand(conn, t, f, opp_ab, day, rng)
    sold, gate = {}, 0.0
    for k, (share, mult, el) in SEATS.items():
        seats = int(f["capacity"] * share)
        sold[k] = int(seats * min(1.0, dem[k]))
        gate += sold[k] * f[f"price_{k}"] * (1.6 if playoff else 1.0)
    total = sum(sold.values())
    conn.execute("INSERT INTO attendance VALUES (?,?,?,?,?,?,?,?,?,?)", (gid, t, _season(conn), day, sold["lower"], sold["upper"],
                                                                        sold["premium"], total, f["capacity"], round(gate)))
    per_fan = PER_FAN * (0.9 + 0.004 * (_mood(conn, t) - 55))
    _post(conn, t, day, "gate", gate, f"{'playoff ' if playoff else ''}game {gid}: {total:,} fans")
    _post(conn, t, day, "concessions", total * per_fan, f"game {gid}")
    _post(conn, t, day, "arena", -ARENA_GAME, f"game {gid}")
    _post(conn, opp, day, "travel", -TRAVEL_GAME, f"game {gid}")
    return total


def monthly(conn, day):
    """On the first of each month: media, sponsorship, salaries (in season), fixed costs and the budgets."""
    setup(conn)
    d = datetime.date.fromisoformat(day)
    key = f"finance_month_{day[:7]}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    from . import contracts as K
    yr = K.season_year(conn)
    in_season = d.month in SEASON_MONTHS
    for t in _top(conn):
        f = profile(conn, t)
        mood, pts = _mood(conn, t), _points_pct(conn, t)
        _post(conn, t, day, "media", NATIONAL_MEDIA / 12, "national")
        _post(conn, t, day, "media", (6_000_000 + 2_200_000 * f["market"]) * (0.9 + 0.2 * mood / 100) / 12, "local")
        _post(conn, t, day, "sponsorship", (9_000_000 + 2_400_000 * f["market"]) * (0.85 + 0.3 * pts) / 12, "")
        from . import ledger as LG                  # v41: cash, not cap: salaries over the season, bonuses on 1 July
        if in_season:
            try:
                pay = LG.cash(conn, t, yr, "salary")
            except Exception:
                pay = 0
            _post(conn, t, day, "payroll", -pay / len(SEASON_MONTHS), "players")
        if d.month == 7:
            try:
                bon = LG.cash(conn, t, K.signing_year(conn), "bonus")
            except Exception:
                bon = 0
            if bon:
                _post(conn, t, day, "payroll", -bon, "signing bonuses")
        staff = conn.execute("SELECT COALESCE(SUM(salary), 0) FROM staff WHERE team_id=?", (t,)).fetchone()[0] if _has(conn, "staff") else 0
        _post(conn, t, day, "staff", -staff / 12, "")
        _post(conn, t, day, "arena", -ARENA_MONTH, "fixed")
        _post(conn, t, day, "admin", -ADMIN_MONTH, "")
        for b in BUDGETS:
            _post(conn, t, day, b, -f[f"budget_{b}"] / 12, "budget")
        cash = conn.execute("SELECT cash FROM club_finance WHERE team_id=?", (t,)).fetchone()[0]   # v54: interest on the cash
        from .accounts import INTEREST_EARNED, INTEREST_PAID
        if cash:
            _post(conn, t, day, "interest", cash * (INTEREST_EARNED if cash > 0 else INTEREST_PAID) / 12,
                  "earned on the balance" if cash > 0 else "on the overdraft")
    # revenue sharing: the league's biggest markets (8+) fund a payment to its smallest (4 and under)
    ms = {t: profile(conn, t)["market"] for t in _top(conn)}
    small, big = [t for t, m in ms.items() if m <= 4], [t for t, m in ms.items() if m >= 8]
    if small and big:
        for t in small:
            _post(conn, t, day, "sharing", SHARING / 12, "revenue sharing")
        for t in big:
            _post(conn, t, day, "sharing", -SHARING * len(small) / len(big) / 12, "revenue sharing")
    try:                                                  # v57: a new arena's construction and its loan
        from . import arena as AR
        AR.monthly(conn, day, lambda t, d, cat, amt, det: _post(conn, t, d, cat, amt, det))
    except Exception:
        pass
    try:                                                  # v54: your budget and the board's quarterly finance review
        from . import accounts as AC
        AC.on_month(conn, day)
    except Exception:
        pass


def catch_up(conn, day):
    """Post every month from the last one posted up to the month of `day` (offseason phases jump weeks at a time)."""
    setup(conn)
    d = datetime.date.fromisoformat(day)
    last = conn.execute("SELECT value FROM pack_info WHERE key='finance_last_month'").fetchone()
    if last is None:                                     # a new game, or a save from before v34: start this month
        conn.execute("INSERT INTO pack_info (key, value) VALUES ('finance_last_month', ?)", (day[:7],))
        monthly(conn, d.replace(day=1).isoformat())
        return
    y, m = map(int, last[0].split("-"))
    while (y, m) < (d.year, d.month):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        monthly(conn, datetime.date(y, m, 1).isoformat())
        conn.execute("UPDATE pack_info SET value=? WHERE key='finance_last_month'", (f"{y}-{m:02d}",))


def weekly(conn, day):
    """Mondays: the marketing budget nudges the fans' mood (zero at the default budget)."""
    if not _has(conn, "media_state"):
        return
    for t in _top(conn):
        dlt = marketing_drift(conn, t)
        if dlt:
            conn.execute("UPDATE media_state SET fan_sentiment=MAX(0, MIN(100, fan_sentiment+?)) WHERE team_id=?", (dlt, t))


def playoff_gates(conn, season_id, day):
    for (gid,) in conn.execute("SELECT game_id FROM games WHERE season_id=? AND game_type='PO' AND played=1", (season_id,)).fetchall():
        home_game(conn, gid, day, playoff=True)


def season_close(conn, year, day):
    """The season's books: revenue, costs, the owner's cut (or his cover for a loss), the summary and a letter."""
    setup(conn)
    if conn.execute("SELECT 1 FROM finance_season WHERE season=? LIMIT 1", (year,)).fetchone():
        return
    me = user_team(conn)
    for t in _top(conn):
        # v54: the fiscal year (July to June) as the profit and loss report has it: arena projects are capital
        # (depreciated, not expensed), the owner's money is below the line (hs/game/accounts.py)
        from . import accounts as AC
        lo, hi = f"{year}-07-01", f"{year + 1}-06-31"
        rows = {r[0]: r[1] for r in conn.execute("SELECT category, SUM(amount) FROM finance_ledger WHERE team_id=? AND day>=? AND day<=? "
                                                 "AND category NOT IN ('owner', 'arena_capital', 'loan', 'loan_principal') GROUP BY category", (t, lo, hi))}
        rev, cost, profit = AC.fy_result(conn, t, year)
        o = conn.execute("SELECT spend FROM owners WHERE team_id=?", (t,)).fetchone() if _has(conn, "owners") else None
        spend = (o[0] if o else 5) or 5
        if profit > 0:
            cut = -profit * max(0.0, min(0.5, 0.15 + 0.05 * (6 - spend)))
        else:
            cut = -profit * (0.5 if spend >= 6 else 0.25)
        if cut:
            _post(conn, t, day, "owner", cut, "the owner's cut" if cut < 0 else "the owner covers part of the loss")
        att = conn.execute("SELECT AVG(1.0 * total / capacity), COUNT(*) FROM attendance WHERE team_id=? AND season=? AND game_id IN "
                           "(SELECT game_id FROM games WHERE game_type='RS')", (t, year)).fetchone()
        fill = att[0] or 0.0
        conn.execute("INSERT OR REPLACE INTO finance_season VALUES (?,?,?,?,?,?,?,?)",
                     (t, year, round(rev), round(cost), round(profit), round(cut), round(fill, 4), json.dumps(rows)))
        if t == me:
            cash = conn.execute("SELECT cash FROM club_finance WHERE team_id=?", (t,)).fetchone()[0]
            m = lambda v: f"${v / 1e6:,.1f}M"
            add_message(conn, day, "The season's books",
                        f"From the club's finance office, the {year}-{(year + 1) % 100:02d} season:\n"
                        f"- Revenue {m(rev)}: gate {m(rows.get('gate', 0))}, concessions and merchandise {m(rows.get('concessions', 0))}, "
                        f"media {m(rows.get('media', 0))}, sponsorship {m(rows.get('sponsorship', 0))}\n"
                        f"- Costs {m(cost)}: players {m(-rows.get('payroll', 0))}, staff {m(-rows.get('staff', 0))}, arena "
                        f"{m(-rows.get('arena', 0))}, travel {m(-rows.get('travel', 0))}, budgets "
                        f"{m(-sum(rows.get(b, 0) for b in BUDGETS))}\n"
                        f"- {'Profit' if profit >= 0 else 'Loss'} {m(abs(profit))}; "
                        f"{'the owner took' if cut < 0 else 'the owner put in'} {m(abs(cut))}\n"
                        f"- Average attendance {fill * 100:.1f}% of {profile(conn, t)['capacity']:,} seats\n"
                        f"Cash in the bank: {m(cash)}. Ticket prices and budgets are on the Finances screen.")


# ---------------------------------------------------------------- the club's choices
def set_price(conn, t, seat, price):
    if seat not in SEATS:
        raise ValueError("Seats: lower, upper, premium.")
    f = profile(conn, t)
    ref = ref_price(f["market"]) * SEATS[seat][1]
    price = float(price)
    if not 0.4 * ref <= price <= 2.5 * ref:
        raise ValueError(f"Keep the {seat} price between ${0.4 * ref:,.0f} and ${2.5 * ref:,.0f}.")
    conn.execute(f"UPDATE club_finance SET price_{seat}=? WHERE team_id=?", (round(price), t))


def set_budget(conn, t, kind, amount):
    if kind not in BUDGETS:
        raise ValueError("Budgets: scouting, development, marketing.")
    lo, hi = BUDGET_RANGE
    amount = float(amount)
    if not lo * BUDGETS[kind] <= amount <= hi * BUDGETS[kind]:
        raise ValueError(f"The {kind} budget runs from ${lo * BUDGETS[kind] / 1e6:.2f}M to ${hi * BUDGETS[kind] / 1e6:.1f}M a year.")
    conn.execute(f"UPDATE club_finance SET budget_{kind}=? WHERE team_id=?", (round(amount), t))


ARENA_COST = 5_000_000                 # per point of arena quality
EXPANSION_COST = 9_000                 # per seat added


def improve_arena(conn, t, points, day):
    """Offseason only: renovations add arena quality (up to 95) at $5M a point, paid at once from the club's cash."""
    from . import contracts as K
    if K.season_state(conn) in ("regular_season", "playoffs"):
        raise ValueError("Renovations happen in the offseason.")
    f = profile(conn, t)
    points = int(points)
    if points < 1 or f["arena_quality"] + points > 95:
        raise ValueError(f"Arena quality is {f['arena_quality']:.0f}; it can go up to 95.")
    cost = points * ARENA_COST
    if f["cash"] - cost < -50_000_000:
        raise ValueError("The owner will not let the club go more than $50M into debt for it.")
    conn.execute("UPDATE club_finance SET arena_quality=arena_quality+? WHERE team_id=?", (points, t))
    _post(conn, t, day, "arena_capital", -cost, f"renovations (+{points} quality)")
    return cost


def expand_arena(conn, t, seats, day):
    from . import contracts as K
    if K.season_state(conn) in ("regular_season", "playoffs"):
        raise ValueError("Construction happens in the offseason.")
    seats = int(seats)
    f = profile(conn, t)
    if seats < 100 or f["capacity"] + seats > 22_000:
        raise ValueError("Add at least 100 seats, up to 22,000 in all.")
    cost = seats * EXPANSION_COST
    if f["cash"] - cost < -50_000_000:
        raise ValueError("The owner will not let the club go more than $50M into debt for it.")
    conn.execute("UPDATE club_finance SET capacity=capacity+? WHERE team_id=?", (seats, t))
    _post(conn, t, day, "arena_capital", -cost, f"{seats} new seats")
    return cost


# ---------------------------------------------------------------- what the budgets do (neutral at the defaults)
def budget_factor(conn, t, kind):
    if t is None or not _has(conn, "club_finance"):
        return 1.0
    r = conn.execute(f"SELECT budget_{kind} FROM club_finance WHERE team_id=?", (t,)).fetchone()
    return (r[0] / BUDGETS[kind]) if r and r[0] else 1.0


def scouting_effect(conn, t):
    """Multiplier on the scouts' error: 0.85 (triple budget) to 1.15 (a quarter)."""
    x = budget_factor(conn, t, "scouting")
    return max(0.85, min(1.15, 1 - 0.075 * (x - 1) if x >= 1 else 1 + 0.2 * (1 - x)))


def development_effect(conn, t):
    x = budget_factor(conn, t, "development")
    return max(0.96, min(1.05, 1 + 0.025 * (x - 1) if x >= 1 else 1 - 0.053 * (1 - x)))


def marketing_drift(conn, t):
    x = budget_factor(conn, t, "marketing")
    return max(-0.5, min(0.5, 0.25 * (x - 1) if x >= 1 else -0.66 * (1 - x)))


# ---------------------------------------------------------------- the screen
def view(conn, t, season=None):
    setup(conn)
    f = profile(conn, t)
    season = int(season) if season else _season(conn)
    rows = {r[0]: r[1] for r in conn.execute("SELECT category, SUM(amount) FROM finance_ledger WHERE team_id=? AND season=? AND category NOT IN "
                                             "('loan', 'loan_principal') GROUP BY category", (t, season))}   # v57: financing is not revenue
    att = conn.execute("SELECT COUNT(*), AVG(total), AVG(1.0 * total / capacity), SUM(gate) FROM attendance WHERE team_id=? AND season=?", (t, season)).fetchone()
    games = [dict(r) for r in conn.execute("SELECT a.*, g.away_team_id FROM attendance a JOIN games g USING (game_id) WHERE a.team_id=? AND a.season=? "
                                           "ORDER BY a.day DESC LIMIT 12", (t, season))]
    ab = {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    for g in games:
        g["opp"] = ab.get(g["away_team_id"])
    ref = ref_price(f["market"])
    league = [dict(team_id=r[0], abbr=ab.get(r[0]), fill=round(r[1] or 0, 3), avg=round(r[2] or 0)) for r in conn.execute(
        "SELECT team_id, AVG(1.0 * total / capacity), AVG(total) FROM attendance WHERE season=? GROUP BY team_id ORDER BY 2 DESC", (season,))]
    seasons = [r[0] for r in conn.execute("SELECT DISTINCT season FROM finance_ledger WHERE team_id=? ORDER BY 1 DESC", (t,))] or [season]
    history = [dict(r) for r in conn.execute("SELECT season, revenue, costs, profit, owner, fill FROM finance_season WHERE team_id=? ORDER BY season", (t,))]
    proj = projection(conn, t)
    return dict(profile=f, season=season, seasons=seasons, ledger=rows, revenue=sum(v for v in rows.values() if v > 0),
                costs=-sum(v for v in rows.values() if v < 0), attendance=dict(games=att[0], avg=round(att[1] or 0), fill=round(att[2] or 0, 3), gate=att[3] or 0),
                games=games, prices={k: dict(price=f[f"price_{k}"], ref=round(ref * SEATS[k][1]), share=SEATS[k][0],
                                                 seats=int(f["capacity"] * SEATS[k][0])) for k in SEATS},
                budgets={k: dict(amount=f[f"budget_{k}"], default=v, range=[BUDGET_RANGE[0] * v, BUDGET_RANGE[1] * v]) for k, v in BUDGETS.items()},
                effects=dict(scouting=round(scouting_effect(conn, t), 3), development=round(development_effect(conn, t), 3),
                             marketing=round(marketing_drift(conn, t), 2)),
                league=league, history=history, projection=proj, arena=dict(cost_point=ARENA_COST, cost_seat=EXPANSION_COST))


def projection(conn, t):
    """A rough full-season estimate at today's prices and form (the screen's 'if things go on like this')."""
    f = profile(conn, t)
    dem = demand(conn, t, f)
    gate = sum(int(f["capacity"] * s) * min(1.0, dem[k]) * f[f"price_{k}"] for k, (s, _, _) in SEATS.items())
    fans = sum(int(f["capacity"] * s) * min(1.0, dem[k]) for k, (s, _, _) in SEATS.items())
    mood, pts = _mood(conn, t), _points_pct(conn, t)
    from . import contracts as K
    try:
        from . import ledger as LG
        pay = LG.cash(conn, t, K.signing_year(conn))
    except Exception:
        pay = 0
    staff = conn.execute("SELECT COALESCE(SUM(salary), 0) FROM staff WHERE team_id=?", (t,)).fetchone()[0] if _has(conn, "staff") else 0
    rev = 41 * (gate + fans * PER_FAN * (0.9 + 0.004 * (mood - 55))) + NATIONAL_MEDIA + (6e6 + 2.2e6 * f["market"]) * (0.9 + 0.2 * mood / 100) \
        + (9e6 + 2.4e6 * f["market"]) * (0.85 + 0.3 * pts)
    ms = [profile(conn, x)["market"] for x in _top(conn)]
    n_small, n_big = sum(m <= 4 for m in ms), sum(m >= 8 for m in ms)
    if n_small and n_big:
        rev += SHARING if f["market"] <= 4 else -SHARING * n_small / n_big if f["market"] >= 8 else 0
    cost = pay + staff + 41 * ARENA_GAME + 12 * ARENA_MONTH + 41 * TRAVEL_GAME + 12 * ADMIN_MONTH + sum(f[f"budget_{b}"] for b in BUDGETS)
    return dict(fill=round(min(1.0, fans / f["capacity"]), 3), revenue=round(rev), costs=round(cost), profit=round(rev - cost))
