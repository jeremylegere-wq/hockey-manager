"""Contract valuation: what a player is worth each season of a deal, and whether the deal is good.

The method follows the public "surplus value" approach (projected wins above replacement priced at the market cost
of a win, summed over the term, minus the cap hits), built on what this game knows:

1. Current level. The player's perceived overall: ratings blended with his NHL record (ice time and points per game;
   goalies' games and save %), the same lens the trade AI and the salary market use (hs.game.trades.Perception).
2. Ageing. The market's expectation of how a typical player changes each year (AGE_DELTA; goalies two years later).
   Clubs do not see a player's hidden development profile, so a late bloomer or an early decliner surprises them.
3. Wins above replacement. WAR = scale x (overall - REPLACEMENT)^WAR_POWER. Replacement level (9.9) is roughly the
   best player a club can call up or sign for the minimum. The scale is fitted each day so the league's rostered
   players add up to WINS_PER_TEAM wins above replacement per club.
4. Cost of a win. The cap money clubs spend above the minimum, divided by those wins (about $5.3M at a $104M cap,
   close to the ~$5-5.5M public models use), growing with the cap (CAP_GROWTH a year).
5. Market value of a season = minimum salary + WAR x cost of a win (x0.65 for goalies, whom clubs pay less per win). Surplus = sum over the term of (market value -
   cap hit). Grade: A +$10M or more, B +$3M, C within $3M, D down to -$10M, F worse ("albatross").
6. Risk. 200 simulated futures (a starting error and a yearly random walk around the age curve) give the chance the
   deal ends up positive.

7. The star ceiling. No club pays a star his full WAR: above STAR_SOFT of the cap (~$9.4M at $104M) only STAR_TAKE
   of the extra value turns into salary. That is the NHL's shape (the best players earn 12-13% of the cap, nowhere near
   the 20% maximum) and it keeps one summer's bidding from handing a dozen players the maximum.

Stars are worth far more than they are paid (that is why their deals are bargains); depth players on long deals above
~$4M rarely are.
"""
from __future__ import annotations

import datetime
import math
import random

REPLACEMENT = 9.9
WAR_POWER = 1.5
WINS_PER_TEAM = 15.0
SPEND_SHARE = 0.95
CAP_GROWTH = 0.05
STAR_SOFT, STAR_TAKE = 0.09, 0.25   # fair AAV above 9% of the cap is paid at 25 cents on the dollar
GOALIE_MAX_SHARE = 0.11      # and no goalie gets more than ~11% of the cap
GOALIE_MARKET = 0.65          # clubs pay goalies less per win (volatile, one plays): top goalie deals run ~$10M
START_SD, YEAR_SD = 0.18, 0.12
# expected change in overall over the next year at this age (age on 15 September), for a typical skater
AGE_DELTA = {18: 0.35, 19: 0.35, 20: 0.33, 21: 0.25, 22: 0.17, 23: 0.10, 24: 0.04, 25: 0.0, 26: 0.0, 27: 0.0,
             28: 0.0, 29: -0.03, 30: -0.08, 31: -0.12, 32: -0.15, 33: -0.18, 34: -0.21, 35: -0.28, 36: -0.36,
             37: -0.44, 38: -0.52}
GRADES = [(10_000_000, "A", "elite bargain"), (3_000_000, "B", "good value"), (-3_000_000, "C", "fair market"),
          (-10_000_000, "D", "overpay"), (-1e18, "F", "albatross")]


def age_delta(age, goalie=False):
    a = age - 2 if goalie else age
    if a <= 18:
        return AGE_DELTA[18]
    return AGE_DELTA.get(a, AGE_DELTA[38] - 0.08 * (a - 38))


def overall_of_value(v):
    """player_value (0-100) back to the overall scale."""
    return v / 100.0 * 19.0 + 1.0


def war(ov, scale):
    return scale * max(0.0, ov - REPLACEMENT) ** WAR_POWER


class Market:
    """League-wide prices for today: WAR scale and cost of a win (cached with the salary market's values)."""

    def __init__(self, conn):
        from . import contracts as K
        self.conn = conn
        self.values = K.league_values(conn)            # MarketValues (perceived values, cached per day)
        cr = K.crules(conn)
        self.cr = cr
        self.year = K.signing_year(conn)
        teams = conn.execute("SELECT COUNT(*) FROM teams WHERE league_id=(SELECT league_id FROM teams WHERE "
                             "team_id IN (SELECT team_id FROM contracts) LIMIT 1)").fetchone()[0] or 32
        rostered = [r[0] for r in conn.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL AND "
                                               "club_id=team_id AND status IN ('active','injured')")]
        raw = sum(max(0.0, overall_of_value(self.values.value(p)) - REPLACEMENT) ** WAR_POWER for p in rostered)
        total_wins = WINS_PER_TEAM * teams
        self.scale = total_wins / raw if raw > 0 else 1.0
        cap = cr["cap_ceiling"] or cr.get("reference_payroll") or 100_000_000
        pool = cap * teams * SPEND_SHARE - cr["min_salary"] * max(len(rostered), 1)
        self.cost_per_win = max(1.0, pool / total_wins)
        self.min_salary = cr["min_salary"]
        self.max_salary = cr["max_salary_pct"] * cap if cr["cap_ceiling"] else None

    def cpw(self, season):
        return self.cost_per_win * (1 + CAP_GROWTH) ** max(0, season - self.year)

    def minimum(self, season):
        return self.min_salary * (1 + CAP_GROWTH) ** max(0, season - self.year)


_CACHE = {}


def market(conn):
    from . import contracts as K
    key = id(K.league_values(conn))
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = Market(conn)
    return _CACHE[key]


def _player(conn, pid):
    r = conn.execute("SELECT birth_date, position FROM players WHERE player_id=?", (pid,)).fetchone()
    return r["birth_date"], r["position"] == "G"


def _age(birth, season):
    b = datetime.date.fromisoformat(birth)
    on = datetime.date(season, 9, 15)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def projection(conn, pid, first_season, years, m=None):
    """[(season, age, projected overall, WAR, market value)] for the coming seasons (the market's expectation)."""
    m = m or market(conn)
    birth, goalie = _player(conn, pid)
    ov = overall_of_value(m.values.value(pid))
    out = []
    for k in range(years):
        season = first_season + k
        age = _age(birth, season)
        if k > 0:
            ov += age_delta(age - 1, goalie)
        w = war(ov, m.scale)
        out.append((season, age, ov, w, m.minimum(season) + w * m.cpw(season) * (GOALIE_MARKET if goalie else 1.0)))
    return out


def fair_aav(conn, pid, years, first_season=None, m=None):
    """The AAV at which a deal of this length is worth exactly its cost (zero surplus), within league limits."""
    m = m or market(conn)
    first_season = first_season if first_season is not None else m.year
    proj = projection(conn, pid, first_season, years, m)
    aav = sum(p[4] for p in proj) / len(proj)
    if m.max_salary:
        soft = STAR_SOFT / m.cr["max_salary_pct"] * m.max_salary
        if aav > soft:
            aav = soft + (aav - soft) * STAR_TAKE
        aav = min(aav, m.max_salary)
    if V_goalie(conn, pid) and m.max_salary:
        aav = min(aav, GOALIE_MAX_SHARE / 0.20 * m.max_salary)
    return max(m.min_salary, int(round(aav / 5000) * 5000))


def V_goalie(conn, pid):
    return _player(conn, pid)[1]


def grade(surplus):
    for cut, letter, words in GRADES:
        if surplus >= cut:
            return letter, words
    return "F", "albatross"


def evaluate(conn, pid, aav, years, first_season, sims=200, m=None):
    """Surplus value of a deal: dict(rows, value, cost, surplus, grade, words, p_positive)."""
    m = m or market(conn)
    proj = projection(conn, pid, first_season, years, m)
    value = sum(p[4] for p in proj)
    cost = aav * years
    surplus = value - cost
    birth, goalie = _player(conn, pid)
    rng = random.Random(f"val-{pid}-{first_season}-{years}-{aav}")
    pos = 0
    base = [p[2] for p in proj]
    for _ in range(sims):
        shift, total = rng.gauss(0, START_SD), 0.0
        for k, (season, age, ov, w, v) in enumerate(proj):
            if k:
                shift += rng.gauss(0, YEAR_SD)
            total += (m.minimum(season) + war(base[k] + shift, m.scale) * m.cpw(season)
                      * (GOALIE_MARKET if goalie else 1.0) - aav)
        pos += total > 0
    letter, words = grade(surplus)
    return dict(rows=proj, value=value, cost=cost, surplus=surplus, grade=letter, words=words,
                p_positive=pos / sims)


def evaluate_contract(conn, pid, m=None):
    """Evaluate a player's current contract over its remaining seasons (None if he has none)."""
    from . import contracts as K
    m = m or market(conn)
    season = K.signing_year(conn)                 # the coming season once this one is over
    c = K.current_contract(conn, pid, season)
    if c is None:
        return None
    first = max(season, c["start_year"])
    left = c["start_year"] + c["years"] - first
    if left <= 0:
        return None
    r = evaluate(conn, pid, c["cap_hit"], left, first, m=m)
    r.update(contract=dict(c), first_season=first, years_left=left)
    return r
