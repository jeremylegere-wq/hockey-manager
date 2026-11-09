"""AI-to-AI trades: clubs the user does not manage trade with each other during the season and the offseason.

v39: a friction-based router (hs/game/trade_model.py has the formulas). Each day the router first decides what
kind of deal is being looked for, then who and what:
  minor    a swap of minor-leaguers, or one for future considerations (contract limits, a fresh start)
  depth    a fringe NHL player or minor-league veteran for a late pick or future considerations
  roster   a player who would make the buyer's top lineup, for prospects, picks and depth (the pre-v39 trade),
           pursued only when the buyer's need at his position is at least his friction, and paid for at
           1.05 + friction/100 of his value; or a like-for-like "hockey trade" between clubs with opposite needs
  swap     draft-day pick swaps (moving up or down, this year's pick for next year's)
The mix follows the calendar (docs/TRADES.md); real 2024-25: 74 in-season trades, about a third of them minor-league
swaps or futures deals, a quarter depth players for picks, a third NHL regulars; 55 in the offseason, 18 of them
pick-for-pick on draft day. Every deal goes through roster.trade(), the same rules a user trade meets; clauses (NTC,
NMC, modified lists) can block it. The user's club is never involved. See docs/TRADES.md.
"""
from __future__ import annotations

import bisect
import collections
import datetime
import random
import json
import statistics

from . import roster as R
from . import trade_model as TM
from .events import emit, player_name, team_abbr
from .state import user_team
from ..schema import top_league_sql

TOP = {"F": 6, "D": 4, "G": 1}            # how many players per group make up a club's top lineup
DEPTH = {"F": 12, "D": 6, "G": 2}
DEADLINE_RUSH_DAYS = 14
P_ATTEMPT = 0.15                           # chance of one trade attempt on an ordinary in-season day (v25: 0.10 gave
                                           # 13-23 trades a season once AI targets went cheapest-first)
RUSH_ATTEMPTS = 2                          # attempts per day in the deadline rush
OFFSEASON_ATTEMPTS = {"draft": 60, "free_agency": 55}
COOLDOWN_DAYS = 30                         # a newly signed player cannot be traded for this long
MAX_TRADES_PER_CLUB = 4                    # in-season AI roster trades (NHL regulars) per club per season
MAX_DEALS_PER_CLUB = 9                     # all AI deals per club per season (minor, depth and roster)
# v30 (defect 16a): stars move rarely. A star is a player valued in the league's top 15%. Unless he asked out, only a
# seller moves one, only with this chance per try (more in the deadline rush), and at most STAR_TRADES_MAX a season.
STAR_SHARE = 0.15
STAR_P, STAR_P_RUSH = 0.2, 0.45
STAR_TRADES_MAX = 4
# v39 router (docs/TRADES.md "How the market decides"): expected attempts a day by phase, and the mix of kinds
ATTEMPTS = {"early": 0.33, "mid": 0.55, "rush": 5.0, "deadline": 75.0}
MIX = {"early": {"minor": 0.52, "depth": 0.23, "roster": 0.25},
       "mid": {"minor": 0.47, "depth": 0.23, "roster": 0.30},
       "rush": {"minor": 0.20, "rental": 0.35, "depth": 0.15, "roster": 0.30},
       "deadline": {"minor": 0.20, "rental": 0.35, "depth": 0.15, "roster": 0.30},
       "draft": {"swap": 0.25, "roster": 0.50, "minor": 0.10, "depth": 0.15},
       "free_agency": {"roster": 0.50, "depth": 0.25, "minor": 0.25}}
P_HOCKEY_TRADE = 0.25                      # share of roster attempts that look for a like-for-like trade first
HOCKEY_NEED, HOCKEY_SURPLUS = 35.0, 10.0   # need scores: a club short at one group and comfortable at another
MINOR_POTENTIAL_MAX = 12.0                 # minor-leaguers with this potential or more are real prospects, not swap fodder
P_FUTURES = 0.4                            # share of minor deals that send a player away for future considerations
FUTURES_MAX = 4.0                          # a player worth less than this (trade scale) goes for future considerations
MINOR_GAP, MINOR_GAP_ABS = 0.3, 6.0        # minor-league swaps: values within 30% (or 6 points)
MINOR_FARM_FULL = 8                        # a farm team with this many players at his position does not want another
DEPTH_KEEP = {"F": 9, "D": 5, "G": 1}      # depth deals: players below a club's top nine F / five D / starting goalie
DEPTH_FRICTION_MAX = 15.0
RENTAL_SELLER_S, RENTAL_BUYER_S = 0.45, 0.55   # deadline rentals: out of the race sells, in it buys
DEPTH_NEED = 15.0
ROOM_BUY, ROOM_SELL = 2.0, 3.0
DUMP_ROOM = 2_000_000                      # cap dumps: only a club within $2M of the cap pays to dump (buyer keeps $2M)
P_DUMP_IN_SEASON = 0.3                     # in season, clubs rarely pay to dump a contract
P_SWAP_TARGET = 0.6                        # a club tries to move up only when it has a player in mind             # cohesion after a contender buys / a club in the race sells a regular
P_THREE_TEAM = 0.04                        # chance an AI attempt becomes a three-team deal (a facilitator takes salary)
REQUEST_DISCOUNT = 0.75                    # a club shopping a player who asked out accepts 75% of his value


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS draft_pick_owners (draft_year INTEGER, round INTEGER, "
                 "original_team_id INTEGER, owner_team_id INTEGER, note TEXT, "
                 "PRIMARY KEY (draft_year, round, original_team_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS pick_protection (draft_year INTEGER, round INTEGER, original_team_id INTEGER, "
                 "top INTEGER, PRIMARY KEY (draft_year, round, original_team_id))")


def protection(conn, y, rnd, orig):
    """v39: the top-N protection on a pick, or 0."""
    ensure_tables(conn)
    r = conn.execute("SELECT top FROM pick_protection WHERE draft_year=? AND round=? AND original_team_id=?",
                     (y, rnd, orig)).fetchone()
    return r[0] if r else 0


def protect(conn, y, rnd, orig, top):
    ensure_tables(conn)
    if top:
        conn.execute("INSERT OR REPLACE INTO pick_protection VALUES (?,?,?,?)", (y, rnd, orig, int(top)))
    else:
        conn.execute("DELETE FROM pick_protection WHERE draft_year=? AND round=? AND original_team_id=?", (y, rnd, orig))


# ---------------------------------------------------------------- v41: conditional picks
# A 2nd-7th round pick that upgrades one round if a condition comes true this season: the club that gave it owes its
# pick one round higher instead (and gets the lower one back). The higher pick is held against it until the draft.
CONDITIONS = {"playoffs": "make the playoffs", "round2": "win a playoff round"}
COND_SHARE = 0.5          # how often a deadline buyer's eligible pick is also offered with a condition
COND_ROUND2_S = 0.75      # a buyer this strong (competitive state 0-1) makes it 'win a round' rather than 'make the playoffs'


def ensure_conditions(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS pick_conditions (draft_year INTEGER, round INTEGER, original_team_id INTEGER, "
                 "giver_team_id INTEGER, kind TEXT, cond_team_id INTEGER, status TEXT DEFAULT 'pending', "
                 "PRIMARY KEY (draft_year, round, original_team_id))")


def cond_spec(kind, team):
    """The asset tuple's third element for a conditional pick: 'cpo-18' / 'cr2-18'."""
    return f"c{'po' if kind == 'playoffs' else 'r2'}-{int(team)}"


def parse_spec(spec):
    """(kind, team) for a conditional spec, or None (an int there is a top-N protection)."""
    if isinstance(spec, str) and spec.startswith("c") and "-" in spec:
        k, t = spec[1:].split("-", 1)
        return ("playoffs" if k == "po" else "round2"), int(t)
    return None


def condition(conn, y, rnd, orig):
    ensure_conditions(conn)
    r = conn.execute("SELECT giver_team_id, kind, cond_team_id, status FROM pick_conditions WHERE draft_year=? AND round=? "
                     "AND original_team_id=?", (y, rnd, orig)).fetchone()
    return dict(giver=r[0], kind=r[1], team=r[2], status=r[3]) if r else None


def encumbered(conn, y, rnd, orig):
    """True while this pick is owed should a conditional pick one round lower upgrade."""
    ensure_conditions(conn)
    return bool(conn.execute("SELECT 1 FROM pick_conditions WHERE draft_year=? AND round=? AND original_team_id=? AND "
                             "status='pending'", (y, rnd + 1, orig)).fetchone())


def check_condition(conn, y, rnd, orig, giver, kind, team):
    """Why a conditional pick cannot be offered, or None."""
    from .draft import draft_year
    if kind not in CONDITIONS:
        return "Conditions: 'playoffs' or 'round2'."
    if rnd < 2:
        return "Only a 2nd-round pick or later can carry a condition (it upgrades one round)."
    if y != draft_year(conn):
        return f"Conditions only work on this season's picks ({draft_year(conn)})."
    if pick_owner(conn, y, rnd - 1, orig) != giver or encumbered(conn, y, rnd - 1, orig):
        return f"The upgrade needs the {pick_label(conn, y, rnd - 1, orig, giver, 0)} free to owe, and {team_abbr(conn, giver)} do not have it."
    if condition(conn, y, rnd, orig) and condition(conn, y, rnd, orig)["status"] == "pending":
        return "That pick already carries a condition."
    if protection(conn, y, rnd - 1, orig):
        return "The pick it would upgrade to is protected."
    return None


def set_condition(conn, y, rnd, orig, giver, kind, team):
    ensure_conditions(conn)
    conn.execute("INSERT OR REPLACE INTO pick_conditions VALUES (?,?,?,?,?,?,'pending')", (y, rnd, orig, giver, kind, team))


def playoff_spots(conn, n):
    from ..league.season import db_rules
    try:
        po = db_rules(conn)["playoffs"]
        if po.get("format") == "division_wildcard":
            divs = conn.execute(f"SELECT COUNT(DISTINCT division) FROM teams WHERE {top_league_sql()}").fetchone()[0]
            confs = conn.execute(f"SELECT COUNT(DISTINCT conference) FROM teams WHERE {top_league_sql()}").fetchone()[0]
            if divs and confs:
                return min(n, po.get("per_division", 3) * divs + po.get("wildcards_per_conference", 2) * confs)
        if po.get("teams"):
            return int(po["teams"])
        if po.get("per_conference"):
            confs = conn.execute(f"SELECT COUNT(DISTINCT conference) FROM teams WHERE {top_league_sql()}").fetchone()[0] or 1
            return min(n, int(po["per_conference"]) * confs)
    except Exception:
        pass
    return max(2, n // 2)


def p_condition(m, kind, team):
    return TM.p_condition(kind, m.rank.get(team, len(m.all_teams) / 2), len(m.all_teams), m.spots, m.season_frac)


def resolve_conditions(conn, year, po_depth, day):
    """At the draft: every pending condition on this year's picks comes true or lapses. po_depth: {team: deepest
    playoff round reached (1 = made it)}. Returns message lines."""
    ensure_conditions(conn)
    lines = []
    for y, rnd, orig, giver, kind, team in conn.execute(
            "SELECT draft_year, round, original_team_id, giver_team_id, kind, cond_team_id FROM pick_conditions "
            "WHERE draft_year=? AND status='pending'", (year,)).fetchall():
        met = po_depth.get(team, 0) >= (1 if kind == "playoffs" else 2)
        holder = pick_owner(conn, y, rnd, orig)
        what = f"{team_abbr(conn, team)} {'made the playoffs' if kind == 'playoffs' else 'won a playoff round'}"
        if met and pick_owner(conn, y, rnd - 1, orig) == giver:
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                         (y, rnd - 1, orig, holder, f"condition met ({what})"))
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                         (y, rnd, orig, giver, "returned: condition met"))
            lines.append(f"Condition met: {what}, so {team_abbr(conn, holder)} get the round-{rnd - 1} pick "
                         f"(from {team_abbr(conn, orig)}) instead of the round-{rnd} one.")
            st = "met"
        else:
            if met:
                lines.append(f"Condition met ({what}) but {team_abbr(conn, giver)} no longer hold the higher pick; "
                             f"{team_abbr(conn, holder)} keep the round-{rnd} pick.")
            st = "met" if met else "lapsed"
            if not met:
                lines.append(f"Condition not met: {team_abbr(conn, team)} did not {CONDITIONS[kind]}; "
                             f"{team_abbr(conn, holder)} keep the round-{rnd} pick.")
        conn.execute("UPDATE pick_conditions SET status=? WHERE draft_year=? AND round=? AND original_team_id=?",
                     (st, y, rnd, orig))
    return lines


# ---------------------------------------------------------------- calendar

def deadline(conn):
    """Trade deadline for the current season: rules contracts.trade_deadline (MM-DD) or the first Friday of March."""
    from . import contracts as K
    end_year = K.season_year(conn) + 1
    mmdd = K.crules(conn).get("trade_deadline")
    if mmdd:
        m, d = (int(x) for x in mmdd.split("-"))
        return datetime.date(end_year, m, d)
    d = datetime.date(end_year, 3, 1)
    return d + datetime.timedelta(days=(4 - d.weekday()) % 7)


# ---------------------------------------------------------------- assets

GOALIE_STRETCH = 1.0      # (2.5 before the v39 replacement-level scale) goalie ratings are compressed; a starter's edge is worth far more than the raw value shows
PROJECTION_SHARE = 0.65   # the most of the gap to his potential a young player's price includes (an 18-year-old)
PATIENCE = 1.5            # v39 certainty: the share fades as his development window burns without progress
PROSPECT_RISK = 0.85      # extra discount for players still in the minors
POS_PREMIUM = {"C": 1.10, "D": 1.05, "LW": 1.0, "RW": 1.0, "G": 0.80}   # prospects: centres and D are scarcer


def certainty(age, value, proj):
    """How sure clubs are that a young player gets to his potential: 1 at 18, falling as the years from 18 to 24 pass
    while he is still far from it (C = 1 - ((age-18)/6)^1.5 * 2 * gap share, 0.2..1)."""
    if proj <= value:
        return 1.0
    gap = (proj - value) / max(1.0, proj)
    return max(0.2, min(1.0, 1 - (max(0, age - 18) / 6.0) ** PATIENCE * 2 * gap))


def asset_value(conn, pid, pot=None, base=None):
    """Trade value of a player including his future: young players count part of the gap to their potential."""
    v = R.player_value(conn, pid) if base is None else base
    row = conn.execute("SELECT birth_date, position, status FROM players WHERE player_id=?", (pid,)).fetchone()
    age = R._today(conn).year - int(row["birth_date"][:4])
    if row["position"] == "G":
        v = 50 + (v - 50) * GOALIE_STRETCH
    p = pot.get(pid) if pot is not None else None
    if p is None:
        r = conn.execute("SELECT potential FROM player_dev WHERE player_id=?", (pid,)).fetchone()
        p = r[0] if r else None
    if p is not None and age <= 23 and row["position"] != "G":
        proj = (p - 1) / 19.0 * 100.0
        if proj > v:
            v = v + (proj - v) * PROJECTION_SHARE * certainty(age, v, proj)
    tv = R.trade_value(v)
    if row["status"] == "prospect":
        tv *= PROSPECT_RISK * (POS_PREMIUM.get(row["position"], 1.0) if age <= 22 else 1.0)
    return tv + R.contract_adjustment(conn, pid)


def tradeable_years(conn):
    """Draft years whose picks can still move: the next two drafts not yet started."""
    from .draft import draft_year
    y = draft_year(conn)
    started = {r[0] for r in conn.execute("SELECT DISTINCT draft_year FROM draft_picks")} \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_picks'").fetchone() else set()
    return [x for x in (y, y + 1, y + 2) if x not in started][:2]


def pick_owner(conn, year, rnd, original):
    ensure_tables(conn)
    r = conn.execute("SELECT owner_team_id FROM draft_pick_owners WHERE draft_year=? AND round=? AND "
                     "original_team_id=?", (year, rnd, original)).fetchone()
    return r[0] if r else original


def picks_owned(conn, team_id, years, teams):
    moved = {(r[0], r[1], r[2]): r[3] for r in conn.execute(
        "SELECT draft_year, round, original_team_id, owner_team_id FROM draft_pick_owners")}
    ensure_conditions(conn)
    held = {(r[0], r[1] - 1, r[2]) for r in conn.execute(          # v41: a pick owed on a pending condition stays put
        "SELECT draft_year, round, original_team_id FROM pick_conditions WHERE status='pending'")}
    return [(y, rnd, t) for y in years for rnd in range(1, 8) for t in teams
            if moved.get((y, rnd, t), t) == team_id and (y, rnd, t) not in held]


def pick_value(rank_worst_first, n_teams, year, this_year, rnd, s_owner=None):
    """Trade value of a pick (v39 curve, trade_model.pick_value). This year's slot follows the standings; later
    years regress to mid-round, are discounted, and a weak club's future 1st carries a lottery premium."""
    return TM.pick_value(rank_worst_first, n_teams, year, this_year, rnd, s_owner)


def pick_label(conn, y, rnd, original, owner, top=None):
    nth = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd, f"{rnd}th")
    cond = parse_spec(top)
    if cond is None and top is None:
        c = condition(conn, y, rnd, original)
        if c and c["status"] == "pending":
            cond = (c["kind"], c["team"])
    top = 0 if cond else (protection(conn, y, rnd, original) if top is None else top)
    up = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd - 1, f"{rnd - 1}th")
    return (f"{y} {nth}-round pick" + ("" if original == owner else f" (from {team_abbr(conn, original)})")
            + (f" (top-{top} protected)" if top else "")
            + (f" (becomes a {up} if {team_abbr(conn, cond[1])} {CONDITIONS[cond[0]]})" if cond else ""))


# ---------------------------------------------------------------- club situation

def _ai_teams(conn):
    me = user_team(conn)
    return [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")
            if r[0] != me]


def standings_rank(conn, proxy=None):
    """{team_id: rank} best first, by points percentage once every club has played 10 games; before that by proxy
    (expected strength), so early-season and summer decisions follow how good a club looks on paper."""
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    pts = {t: [0, 0] for t in teams}
    for g in conn.execute("SELECT home_team_id h, away_team_id a, home_goals hg, away_goals ag, went_to_ot ot FROM "
                          "games WHERE season_id=? AND played=1 AND game_type='RS'", (sid,)):
        for t, gf, ga in ((g["h"], g["hg"], g["ag"]), (g["a"], g["ag"], g["hg"])):
            if t in pts:
                pts[t][1] += 1
                pts[t][0] += 2 if gf > ga else (1 if g["ot"] or gf == ga else 0)
    if min(p[1] for p in pts.values()) >= 10 or not proxy:
        order = sorted(teams, key=lambda t: (-pts[t][0] / max(1, pts[t][1]), t))
    else:
        order = sorted(teams, key=lambda t: (-proxy.get(t, 0), t))
    return {t: i + 1 for i, t in enumerate(order)}


POSTURE_MIN_GP = 20      # clubs do not declare themselves buyers or sellers before this many games


def posture(rank, n):
    if rank <= round(n * 0.31):
        return "contender"
    if rank > n - round(n * 0.375):
        return "seller"
    return "middle"


def group_strength(conn, team_id, values):
    by = {"F": [], "D": [], "G": []}
    for r in R.roster(conn, team_id):
        by[R.group(r["position"])].append(values[r["player_id"]])
    return {g: sum(sorted(v, reverse=True)[:TOP[g]]) / TOP[g] if v else 0.0 for g, v in by.items()}, by


USAGE_WEIGHT = 0.6        # share of a player's perceived value that comes from his NHL record (usage and production)


def _pct(sorted_vals, x):
    """Mid-rank percentile in (0, 1): ties share the middle of their block, so it never saturates at 0 or 1."""
    n = len(sorted_vals)
    lo, hi = bisect.bisect_left(sorted_vals, x), bisect.bisect_right(sorted_vals, x)
    return min(1 - 0.5 / n, max(0.5 / n, (lo + hi) / 2 / n))


_N = statistics.NormalDist()


def _z(sorted_vals, x):
    return _N.inv_cdf(_pct(sorted_vals, x))


def _NOT_HISTORY(conn, table):
    """v42: seasons imported from the database (source='history') stay out of the league's perception of value,
    which was calibrated on the seasons the game plays (and packs with ice time); they count everywhere else."""
    has = any(r[1] == "source" for r in conn.execute(f"PRAGMA table_info({table})"))
    return " AND COALESCE(source, '') <> 'history'" if has else ""


class Perception:
    """What the league thinks players are worth: ratings blended with the NHL record over the last two seasons,
    mapped onto the rating scale within the position group. For skaters the record is half ice time per game and
    half points per game; for goalies, games played and save percentage. Each half becomes a normal score from its
    mid-rank percentile; their mean is rescaled to unit spread and placed on a normal curve with the mean and spread
    of the group's rating values (continuous, so two different records never land on the same value just because
    ratings come in whole numbers). GMs see deployment and
    production, not hidden ratings, so a fourth-liner with flattering ratings is not priced like a first-liner.
    Players with fewer than 10 NHL games keep their rating value. `values` ({pid: rating value}) is the pool the
    percentiles are mapped onto (normally every rostered NHL-organisation player)."""

    def __init__(self, conn, values):
        from . import contracts as K
        y = K.season_year(conn)
        top = conn.execute(f"SELECT league_id FROM teams WHERE {top_league_sql()} LIMIT 1").fetchone()
        top = top[0] if top else 1
        self.rec = {}
        for r in conn.execute("SELECT player_id, SUM(gp), COALESCE(SUM(toi_sec), 0), COALESCE(SUM(g), 0) + "
                              "COALESCE(SUM(a), 0) FROM skater_season_stats WHERE "
                              f"league_id=? AND split='RS' AND season_start_year>=?{_NOT_HISTORY(conn, 'skater_season_stats')} "
                              "GROUP BY player_id", (top, y - 1)):
            if r[1] and r[1] >= 10:
                self.rec[r[0]] = (r[2] / r[1], r[3] / r[1])
        for r in conn.execute("SELECT player_id, SUM(gp), SUM(sa), SUM(ga) FROM goalie_season_stats WHERE "
                              f"league_id=? AND split='RS' AND season_start_year>=?{_NOT_HISTORY(conn, 'goalie_season_stats')} "
                              "GROUP BY player_id", (top, y - 1)):
            if r[1] and r[1] >= 10:
                self.rec[r[0]] = (r[1], 1 - (r[3] or 0) / r[2] if r[2] else 0.9)
        self.pos = {r[0]: R.group(r[1]) for r in conn.execute("SELECT player_id, position FROM players")}
        self.pools = {}
        for g in ("F", "D", "G"):
            ids = [pid for pid in values if self.pos.get(pid) == g]
            have = [pid for pid in ids if pid in self.rec]
            if len(ids) < 5 or len(have) < 5:
                continue
            a = sorted(self.rec[pid][0] for pid in have)
            b = sorted(self.rec[pid][1] for pid in have)
            zs = [0.5 * (_z(a, self.rec[pid][0]) + _z(b, self.rec[pid][1])) for pid in have]
            zsd = statistics.pstdev(zs) or 1.0
            vs = [values[pid] for pid in ids]
            self.pools[g] = (statistics.fmean(vs), statistics.pstdev(vs) or 1.0, a, b, zsd)

    def value(self, pid, raw):
        g = self.pos.get(pid)
        if pid not in self.rec or g not in self.pools:
            return raw
        mean, sd, a, b, zsd = self.pools[g]
        z = 0.5 * (_z(a, self.rec[pid][0]) + _z(b, self.rec[pid][1])) / zsd
        uv = mean + sd * z
        return (1 - USAGE_WEIGHT) * raw + USAGE_WEIGHT * uv


def perceived_values(conn, values):
    """{pid: perceived value} for a pool of rating values (see Perception)."""
    p = Perception(conn, values)
    return {pid: p.value(pid, v) for pid, v in values.items()}


class Market:
    """Everything one round of trade attempts needs, computed once."""

    def __init__(self, conn, day):
        from .draft import draft_year
        ensure_tables(conn)
        self.conn, self.day = conn, day
        self.teams = _ai_teams(conn)
        self.all_teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
        n = len(self.all_teams)
        self.values = {}
        for t in self.all_teams:
            for r in R.roster(conn, t):
                self.values[r["player_id"]] = R.player_value(conn, r["player_id"])
        self.values = perceived_values(conn, self.values)
        self.strength, self.groups = {}, {}
        for t in self.all_teams:
            self.strength[t], self.groups[t] = group_strength(conn, t, self.values)
        proxy = {t: 2 * self.strength[t]["F"] + self.strength[t]["D"] + self.strength[t]["G"] for t in self.all_teams}
        self.rank = standings_rank(conn, proxy)
        sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
        gp = conn.execute("SELECT COUNT(*) FROM games WHERE season_id=? AND played=1 AND game_type='RS'",
                          (sid,)).fetchone()[0] * 2 / max(1, n)
        self.posture = {t: posture(self.rank[t], n) if gp >= POSTURE_MIN_GP else "middle" for t in self.all_teams}
        # v42 (register v39 #5): what the league sees, from the first day: on paper (expected strength) until 10
        # games, then the standings. AI behaviour still waits for POSTURE_MIN_GP games before buying or selling.
        self.outlook = {t: posture(self.rank[t], n) for t in self.all_teams}
        sched = conn.execute("SELECT COUNT(*) FROM games WHERE season_id=? AND game_type='RS'", (sid,)).fetchone()[0] * 2 / max(1, n)
        self.season_frac = min(1.0, gp / sched) if sched else 0.0          # v41: conditional picks
        self.spots = playoff_spots(conn, n)
        self.core = {}
        for t in self.all_teams:
            sk = sorted(((self.values[r["player_id"]], r["player_id"]) for r in R.roster(conn, t)
                         if r["position"] != "G"), reverse=True)[:3]
            gk = sorted(((self.values[r["player_id"]], r["player_id"]) for r in R.roster(conn, t)
                         if r["position"] == "G"), reverse=True)[:1]
            self.core[t] = {pid for _, pid in sk + gk}
        self.league = {g: sum(self.strength[t][g] for t in self.all_teams) / n for g in TOP}
        self.pot = {r[0]: r[1] for r in conn.execute("SELECT player_id, potential FROM player_dev")}
        self.years = tradeable_years(conn)
        self.this_year = draft_year(conn)
        worst_first = sorted(self.all_teams, key=lambda t: -self.rank[t])
        self.pick_slot = {t: i + 1 for i, t in enumerate(worst_first)}
        cut = (datetime.date.fromisoformat(day) - datetime.timedelta(days=COOLDOWN_DAYS)).isoformat()
        season = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
        self.recently_moved = {r[0] for r in conn.execute(        # traded this season, or signed in the last month
            "SELECT player_id FROM league_events WHERE (event_type='PLAYER_TRADED' AND season_start_year=?) OR "
            "(event_type='PLAYER_SIGNED' AND event_date>=?) OR (event_type='PLAYER_SIGNED' AND summary LIKE "
            "'%free agent%' AND event_date>=?)", (season, cut,
                                                 (datetime.date.fromisoformat(day) - datetime.timedelta(days=365))
                                                 .isoformat()))}
        # (a free agent signed within the last year is not flipped: free agents punish clubs that do that)
        self.requests = set()
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
            self.requests = {r[0] for r in conn.execute("SELECT player_id FROM morale WHERE trade_request=1")}
        self._av = {}
        season = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
        self.made = {t: 0 for t in self.all_teams}
        self.deals = {t: 0 for t in self.all_teams}
        for r in conn.execute("SELECT team_id, other_team_id, payload FROM league_events WHERE "
                              "event_type='TRADE_COMPLETED' AND season_start_year=?", (season,)):
            kind = (json.loads(r[2]) if r[2] else {}).get("kind", "roster")
            for t in r[:2]:
                if t in self.made:
                    self.deals[t] += 1
                    if kind == "roster":
                        self.made[t] += 1
        # ---- v39: the friction model's picture of the league
        from . import contracts as K
        self.season = K.season_year(conn)
        self.offseason = K.season_state(conn) != "regular_season"
        self.S = {t: TM.comp_state(self.rank[t], n) for t in self.all_teams}
        self.owner, self.group_of, self.status = {}, {}, {}
        q = ",".join("?" * len(self.all_teams))
        for r in conn.execute(f"SELECT player_id, team_id, position, status FROM players WHERE team_id IN ({q}) AND "
                              "status IN ('active','injured','prospect')", self.all_teams):
            self.owner[r[0]], self.group_of[r[0]], self.status[r[0]] = r[1], R.group(r[2]), r[3]
        self.gstats = {}
        for g in TOP:
            vs = [v for pid, v in self.values.items() if self.group_of.get(pid) == g]
            self.gstats[g] = (statistics.fmean(vs), statistics.pstdev(vs) or 1.0) if len(vs) > 2 else (50.0, 5.0)
        self.top_lineup = {}
        for t in self.all_teams:
            top = set()
            for g, k in TOP.items():
                top |= {pid for _, pid in sorted(((self.values[r["player_id"]], r["player_id"]) for r in R.roster(conn, t)
                                                  if R.group(r["position"]) == g), reverse=True)[:k]}
            self.top_lineup[t] = top
        self.leaders = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='leadership'").fetchone():
            self.leaders = {r[0]: r[1] for r in conn.execute("SELECT player_id, role FROM leadership")}
        self._needs, self._fr = None, {}
        self.rush = False
        from . import clauses as CL
        CL.ensure_table(conn)
        CL.generate_all(conn)
        CL.refresh_lists(conn, self.S, self.season)

    def open_for_business(self, t, kind="roster"):
        if self.deals.get(t, 0) >= MAX_DEALS_PER_CLUB:
            return False
        return kind != "roster" or self.made.get(t, 0) < MAX_TRADES_PER_CLUB

    @property
    def needs(self):
        """v39: {team: {group: need score 0-100}} (trade_model.need_scores)."""
        if self._needs is None:
            self._needs = TM.need_scores(self, self.rush)
        return self._needs

    def friction(self, pid, team=None):
        k = (pid, team)
        if k not in self._fr:
            self._fr[k] = TM.friction(self, pid, team, self.offseason)
        return self._fr[k]

    def value_of(self, pid):
        if pid not in self.values:
            self.values[pid] = R.player_value(self.conn, pid)
        return self.values[pid]

    def av(self, pid):
        if pid not in self._av:
            self._av[pid] = asset_value(self.conn, pid, self.pot, self.values.get(pid))
        return self._av[pid]

    def need(self, t):
        """The group the club needs most (v39 need score; before v39 the weakest group against the league)."""
        n = self.needs.get(t)
        if n and max(n.values()) > 0:
            return max(TOP, key=lambda g: (n[g], -list(TOP).index(g)))
        return min(TOP, key=lambda g: (self.strength[t][g] - self.league[g]) / max(1.0, self.league[g]))

    def age(self, pid):
        b = self.conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        return R._today(self.conn).year - int(b[:4])

    def expiring(self, pid):
        from . import contracts as K
        c = K.current_contract(self.conn, pid)
        return c is not None and c["start_year"] + c["years"] - 1 <= K.season_year(self.conn)

    # how a club values an asset it receives (+) or gives (-), from its own position
    def weight(self, team, pid=None, pick_year=None, receiving=True, fills_need=False):
        p = self.posture[team]
        if pid is None:                                         # a pick (contenders discount later drafts more)
            w = {"seller": 1.2, "middle": 1.0, "contender": 0.85}[p]
            return w * (0.95 if p == "contender" and pick_year and pick_year > self.this_year else 1.0)
        age = self.age(pid)
        w = 1.0
        if p == "seller":
            w = 1.2 if age <= 23 else (0.85 if age >= 30 else 1.0)
        elif p == "contender":
            w = 0.8 if (age <= 22 and self.conn.execute("SELECT status FROM players WHERE player_id=?",
                                                         (pid,)).fetchone()[0] == "prospect") else 1.0
        if receiving and fills_need:
            w *= 1.2
        return w


# ---------------------------------------------------------------- roster trades (NHL regulars)

def _sellable(m, seller, pid):
    """Sellers move veterans and expiring deals; middling clubs only older or expiring veterans; contenders nobody.
    A club's core (top three skaters and its starting goalie) is untouchable unless 31+ and expiring on a seller.
    A player who asked out is always available."""
    if pid in m.recently_moved:
        return False
    if pid in m.requests:
        return True
    age, exp, p = m.age(pid), m.expiring(pid), m.posture[seller]
    if pid in m.core[seller] and not (p == "seller" and age >= 31 and exp):
        return False
    if p == "seller":
        return age >= 26 or exp
    if p == "middle":
        return age >= 30 or (exp and age >= 27) or (m.offseason and age >= 27)
    return m.offseason and age >= 29 and not exp     # summer: even contenders reshuffle veterans with term


def _candidates(m, buyer, g):
    """Players on other AI clubs, at group g, who would make the buyer's top lineup, whose club would sell, and whose
    friction the buyer's need at g overcomes (v39)."""
    mine = sorted(m.groups[buyer][g], reverse=True)
    bar = mine[TOP[g] - 1] if len(mine) >= TOP[g] else 0.0
    need = m.needs[buyer][g]
    out = []
    for s in m.teams:
        if s == buyer or not m.open_for_business(s):
            continue
        for r in R.roster(m.conn, s):
            pid = r["player_id"]
            if r["status"] != "active" or R.group(r["position"]) != g:
                continue
            if m.values[pid] >= bar + 1.0 and _sellable(m, s, pid) and (pid in m.requests or m.friction(pid, s) <= need):
                out.append((s, pid))
    return out


def _package_pool(m, buyer, g, target_value):
    """What the buyer can offer: prospects, picks and depth players at the same group (not its top lineup)."""
    c = m.conn
    pool = []
    for r in c.execute("SELECT player_id FROM players WHERE team_id=? AND status='prospect' ORDER BY player_id", (buyer,)):
        pool.append(("player", r[0]))
    depth = sorted(((m.values[r["player_id"]], r["player_id"]) for r in R.roster(c, buyer)
                    if R.group(r["position"]) == g and r["status"] == "active"), reverse=True)
    spare = max(0, len(depth) + 1 - R.NEED[g])        # never trade a club below what it needs to dress a lineup
    for _, pid in depth[TOP[g]:][:spare]:
        pool.append(("player", pid))
    for y, rnd, orig in picks_owned(c, buyer, m.years, m.all_teams):
        if rnd <= 4:
            pool.append(("pick", (y, rnd, orig)))
    return [a for a in pool if a[0] == "pick" or a[1] not in m.recently_moved]


def _asset_value(m, a, team, receiving):
    if a[0] == "pick":
        y, rnd, orig = a[1]
        spec = a[2] if len(a) > 2 and a[2] is not None else None
        cond = parse_spec(spec)
        if cond is None and spec is None:
            c = condition(m.conn, y, rnd, orig)
            if c and c["status"] == "pending":
                cond = (c["kind"], c["team"])
        if cond:                                           # v41: worth the lower pick, plus the chance of the upgrade
            p = p_condition(m, *cond)
            lo = pick_value(m.pick_slot.get(orig), len(m.all_teams), y, m.this_year, rnd, m.S.get(orig))
            hi = pick_value(m.pick_slot.get(orig), len(m.all_teams), y, m.this_year, rnd - 1, m.S.get(orig))
            return ((1 - p) * lo + p * hi) * m.weight(team, None, y, receiving)
        top = spec if spec is not None else protection(m.conn, y, rnd, orig)
        v = TM.protected_value(m.pick_slot.get(orig), len(m.all_teams), y, m.this_year, rnd, top, m.S.get(orig)) \
            if top else pick_value(m.pick_slot.get(orig), len(m.all_teams), y, m.this_year, rnd, m.S.get(orig))
        return v * m.weight(team, None, y, receiving)
    return m.av(a[1]) * m.weight(team, a[1], receiving=receiving)


def _combo_ok(assets):
    """v41: a pick at most once (plain or conditional), and never a conditional pick with the pick it upgrades to."""
    picks = [a for a in assets if a[0] == "pick"]
    keys = [a[1] for a in picks]
    if len(set(keys)) < len(keys):
        return False
    for a in picks:
        if len(a) > 2 and parse_spec(a[2]) and (a[1][0], a[1][1] - 1, a[1][2]) in keys:
            return False
    return True


def _build_package(m, buyer, seller, need_value, pool, rng, max_assets=3):
    """The 1-3 assets the seller values at >= need_value as a package (best piece 100%, then 80%, 64%), that cost the
    buyer least by its own valuation. Exhaustive over the 18 assets the seller values most."""
    from itertools import combinations
    scored = [(a, _asset_value(m, a, seller, True), _asset_value(m, a, buyer, False)) for a in pool]
    scored = sorted((s for s in scored if s[1] > 1.0), key=lambda s: -s[1])[:18]
    best = None
    for k in range(1, max_assets + 1):
        for combo in combinations(scored, k):
            if not _combo_ok([x[0] for x in combo]):
                continue
            v = TM.package_value([x[1] for x in combo])
            if v < need_value:
                continue
            cost = TM.package_value([x[2] for x in combo])
            if best is None or (cost, k) < (best[1], len(best[0])):
                best = ([x[0] for x in combo], cost, v)
    return best


def _cap_room(c, team):
    from . import contracts as K
    cap = K.crules(c).get("cap_ceiling")
    return (cap - K.payroll(c, team)) if cap else float("inf")


def _hit(c, pid):
    """His cap hit as it counts for the club holding him: a minor-leaguer's is buried down to the burial amount."""
    from . import contracts as K
    k = K.current_contract(c, pid)
    if not k:
        return 0
    own = k["cap_hit"] * (1 - K.retained_share(c, k["contract_id"]))
    st = c.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()
    if st and st[0] == "prospect":
        cr = K.crules(c)
        own = max(0, own - cr["min_salary"] - cr["burial_extra"])
    return own


def _clause_ok(m, pid, frm, to):
    """None if any clause lets him go from `frm` to `to`, else the reason."""
    from . import clauses as CL
    g = m.group_of.get(pid) or R.group(m.conn.execute("SELECT position FROM players WHERE player_id=?",
                                                      (pid,)).fetchone()[0])
    v = m.values.get(pid, 50.0)
    return CL.check(m.conn, pid, to, m.S.get(frm, 0.5), m.S.get(to, 0.5), TM.role_of(m, frm, v, g),
                    TM.role_of(m, to, v, g), pid in m.requests)


def attempt(conn, day, rng, m=None, deadline_rush=False):
    """One roster-trade attempt. Returns a description of the trade made, or None."""
    m = m or Market(conn, day)
    if len(m.teams) < 2:
        return None
    requested = [pid for pid in m.requests if pid in m.values and pid not in m.recently_moved]
    req_owner = {pid: conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
                 for pid in requested}
    requested = [p for p in requested if req_owner[p] in m.teams]
    if requested and rng.random() < 0.5:
        return shop_request(m, rng.choice(sorted(requested)), rng, day)
    if rng.random() < P_HOCKEY_TRADE:
        done = hockey_trade(m, rng, day)
        if done:
            return done
    wts = [{"contender": 3.0 if deadline_rush else 1.5, "middle": 1.0, "seller": 0.3}[m.posture[t]]
           for t in m.teams]
    open_ = [(t, w) for t, w in zip(m.teams, wts) if m.open_for_business(t)]
    if not open_:
        return None
    buyer = rng.choices([t for t, _ in open_], [w for _, w in open_])[0]
    g = m.need(buyer)
    cands = _candidates(m, buyer, g)
    if not cands:
        return None
    # the cheapest players who would make the top lineup first: most real trades are for the second-line winger or
    # the third pair, not the star whose price no package reaches
    cands.sort(key=lambda c: m.values[c[1]])
    cands = cands[:8]
    rng.shuffle(cands)
    for seller, target in cands[:4]:
        done = _try(m, buyer, seller, target, g, rng, day)
        if done:
            return done
    return None


def shop_request(m, target, rng, day):
    """A club moving a player who asked out canvasses every club that would play him in its top lineup and takes
    the first acceptable offer (clubs are asked in random order)."""
    c = m.conn
    seller = c.execute("SELECT team_id FROM players WHERE player_id=?", (target,)).fetchone()[0]
    g = R.group(c.execute("SELECT position FROM players WHERE player_id=?", (target,)).fetchone()[0])
    buyers = []
    for b in m.teams:
        if b == seller:
            continue
        mine = sorted(m.groups[b][g], reverse=True)
        bar = mine[TOP[g] - 1] if len(mine) >= TOP[g] else 0.0
        if m.values[target] >= bar:
            buyers.append(b)
    rng.shuffle(buyers)
    for b in buyers:
        done = _try(m, b, seller, target, g, rng, day)
        if done:
            return done
    return None


def _top_up(c, team, short, day, exclude=()):
    """Bring a roster up so a trade leaves it at the minimum: recall prospects first, then sign free agents."""
    for _ in range(max(0, short)):
        up = [u for u in R.prospects(c, team) if u[1] not in exclude]
        if up:
            R.call_up(c, team, up[0][1], day, "recalled to fill the roster after a trade")
            continue
        for v, pid, pos in R.free_agents(c)[:15]:
            try:
                R.sign_free_agent(c, team, pid, day)
                break
            except R.RosterError:
                continue
        else:
            raise R.RosterError("No one available to fill the roster.")


def _star_cut(m):
    if not hasattr(m, "_star_cut"):
        vals = sorted(m.values.values(), reverse=True)
        m._star_cut = vals[max(0, int(len(vals) * STAR_SHARE) - 1)] if vals else 1e9
    return m._star_cut


def star_trades_this_season(conn):
    from . import contracts as K
    y = K.season_year(conn)
    return conn.execute("SELECT COUNT(*) FROM league_events WHERE event_type='TRADE_COMPLETED' AND payload LIKE '%\"star\": true%' "
                        "AND season_start_year=?", (y,)).fetchone()[0]


def _room_signal(c, team, S, gained, lost_top):
    """v39: the dressing room reads a trade. A contender adding a regular gets a lift; a club in the race that sells a
    top-lineup player for futures feels the season was given up. (Losing a long-serving leader is already in the
    morale model: people.py, 'leaders traded away'.)"""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='team_room'").fetchone():
        return
    d = 0.0
    if S >= 0.7 and gained:
        d = ROOM_BUY
    elif S >= 0.45 and lost_top and not gained:
        d = -ROOM_SELL
    if d:
        c.execute("UPDATE team_room SET cohesion=MIN(100, MAX(0, cohesion+?)) WHERE team_id=?", (d, team))


def _record(m, kind, teams, moved):
    for t in teams:
        m.deals[t] = m.deals.get(t, 0) + 1
        if kind == "roster":
            m.made[t] = m.made.get(t, 0) + 1
    m.recently_moved.update(moved)
    for t in teams:                          # refresh this club's picture for later attempts today
        for r in R.roster(m.conn, t):
            m.values.setdefault(r["player_id"], R.player_value(m.conn, r["player_id"]))
            m.owner[r["player_id"]] = t
        m.strength[t], m.groups[t] = group_strength(m.conn, t, m.values)
    m._needs, m._fr = None, {}


def _try(m, buyer, seller, target, g, rng, day):
    c = m.conn
    star = m.values.get(target, 0) >= _star_cut(m)
    if star and target not in m.requests:
        if m.posture[seller] != "seller" or star_trades_this_season(c) >= STAR_TRADES_MAX:
            return None
        if rng.random() > (STAR_P_RUSH if getattr(m, "rush", False) else STAR_P):
            return None
    fr = m.friction(target, seller)
    need = m.needs[buyer][g]
    if target not in m.requests and fr > need:
        return None
    if _clause_ok(m, target, seller, buyer):
        return None
    base = m.av(target)
    seller_gives = base * m.weight(seller, target, receiving=False) * (REQUEST_DISCOUNT if target in m.requests else 1.0)
    buyer_gets = base * m.weight(buyer, target, receiving=True, fills_need=True)
    want = seller_gives * (TM.ACCEPT + fr / 100.0)
    pool = _package_pool(m, buyer, g, want)
    pkg = _build_package(m, buyer, seller, want, pool, rng)
    if pkg is None:
        return None
    retain = None
    room = _cap_room(c, buyer)
    incoming = _hit(c, target) - sum(_hit(c, a[1]) for a in pkg[0] if a[0] == "player"
                                     and m.status.get(a[1]) in ("active", "injured"))
    if incoming > room:                      # retention: a cost to the seller, charged to the buyer (v39)
        if (m.posture[seller] == "contender" and target not in m.requests) or incoming * 0.5 > room:
            return None
        retain = {target: 0.5}
        want += TM.retention_value(c, seller, target, 0.5, day)
        pkg = _build_package(m, buyer, seller, want, pool, rng)
        if pkg is None:
            return None
    assets, buyer_cost, seller_gets = pkg
    if buyer_cost > buyer_gets or seller_gets < want:
        return None
    players = [a[1] for a in assets if a[0] == "player"]
    picks = [a[1] for a in assets if a[0] == "pick"]
    if any(_clause_ok(m, p, buyer, seller) for p in players):
        return None
    c.execute("SAVEPOINT ai_trade")
    try:
        mn, mx = R.limits(c)
        on_roster = sum(1 for p in players if c.execute("SELECT status FROM players WHERE player_id=?",
                                                        (p,)).fetchone()[0] in ("active", "injured"))
        if len(R.roster(c, buyer)) + 1 - on_roster > mx:
            R.make_room(c, buyer, day, g)
        _top_up(c, seller, mn - (len(R.roster(c, seller)) - 1 + on_roster), day)
        _top_up(c, buyer, mn - (len(R.roster(c, buyer)) + 1 - on_roster), day, exclude=set(players))
        R.trade(c, buyer, players, seller, [target], day, retain=retain)
        for y, rnd, orig in picks:
            c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                      (y, rnd, orig, seller, f"traded {day}"))
        for t in (buyer, seller):
            R.ensure_dressable(c, t, day)
            if R.shortages(c, t):
                raise R.RosterError("A club would be left unable to dress a lineup.")
    except R.RosterError:
        c.execute("ROLLBACK TO ai_trade")
        c.execute("RELEASE ai_trade")
        return None
    except Exception:
        c.execute("ROLLBACK TO ai_trade")
        c.execute("RELEASE ai_trade")
        raise
    c.execute("RELEASE ai_trade")
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        c.execute("UPDATE morale SET trade_request=0, trust_mgmt=MAX(trust_mgmt, 55), morale=MAX(morale, 58) "
                  "WHERE player_id=?", (target,))
    was_requested = target in m.requests
    m.requests.discard(target)
    _room_signal(c, buyer, m.S[buyer], True, False)
    _room_signal(c, seller, m.S[seller], False, target in m.top_lineup.get(seller, ()))
    _record(m, "roster", (buyer, seller), [target, *players])
    goods = [player_name(c, p) for p in players] + [pick_label(c, y, rnd, orig, buyer) for y, rnd, orig in picks]
    text = (f"{team_abbr(c, buyer)} acquire {player_name(c, target)} from {team_abbr(c, seller)} for "
            f"{', '.join(goods)}" + (" (50% retained)" if retain else ""))
    emit(c, "TRADE_COMPLETED", day, text, team_id=buyer, other_team_id=seller, player_id=target,
         importance=3 if base >= 150 or star else 2, players_out=players, picks=[list(p) for p in picks],
         retained=bool(retain), requested=was_requested, star=star, kind="roster", friction=round(fr, 1),
         need=round(need, 1))
    if not star and rng.random() < P_THREE_TEAM:
        extra = three_team_tail(m, buyer, seller, rng, day)
        if extra:
            text += "; " + extra
    return text


def hockey_trade(m, rng, day):
    """v39: a like-for-like trade. Club A needs group g1 and has a surplus at g2; club B the reverse. Each gives a
    middle-of-the-lineup regular (not its core) for one it values at least as much, its need counted (1.2x), and
    each player's friction must be within the other club's need."""
    c = m.conn
    pairs = []
    for a in m.teams:
        if not m.open_for_business(a):
            continue
        na = m.needs[a]
        g1 = max(TOP, key=lambda g: na[g])
        if na[g1] < HOCKEY_NEED:
            continue
        for g2 in TOP:
            if g2 != g1 and na[g2] <= HOCKEY_SURPLUS and g2 != "G" and g1 != "G":
                pairs.append((a, g1, g2))
    rng.shuffle(pairs)
    for a, g1, g2 in pairs[:4]:
        partners = [b for b in m.teams if b != a and m.open_for_business(b) and m.needs[b][g2] >= HOCKEY_NEED
                    and m.needs[b][g1] <= HOCKEY_SURPLUS]
        rng.shuffle(partners)
        for b in partners[:3]:
            def middle(t, g):
                vals = sorted(((m.values[r["player_id"]], r["player_id"]) for r in R.roster(c, t)
                               if R.group(r["position"]) == g and r["status"] == "active"), reverse=True)
                lo, hi = (2, 8) if g == "F" else (1, 5)
                return [pid for _, pid in vals[lo:hi] if pid not in m.core[t] and pid not in m.recently_moved]
            xs, ys = middle(a, g2), middle(b, g1)
            best = None
            for x in xs:
                for y in ys:
                    va_get = m.av(y) * m.weight(a, y, receiving=True, fills_need=True)
                    va_give = m.av(x) * m.weight(a, x, receiving=False) * (TM.ACCEPT + m.friction(x, a) / 100)
                    vb_get = m.av(x) * m.weight(b, x, receiving=True, fills_need=True)
                    vb_give = m.av(y) * m.weight(b, y, receiving=False) * (TM.ACCEPT + m.friction(y, b) / 100)
                    if va_get < va_give or vb_get < vb_give:
                        continue
                    if m.friction(y, b) > m.needs[a][g1] or m.friction(x, a) > m.needs[b][g2]:
                        continue
                    gap = abs(m.av(x) - m.av(y))
                    if best is None or gap < best[0]:
                        best = (gap, x, y)
            if best is None:
                continue
            _, x, y = best
            if _clause_ok(m, x, a, b) or _clause_ok(m, y, b, a):
                continue
            if _hit(c, y) - _hit(c, x) > _cap_room(c, a) or _hit(c, x) - _hit(c, y) > _cap_room(c, b):
                continue
            c.execute("SAVEPOINT ai_hockey")
            try:
                R.trade(c, a, [x], b, [y], day)
                for t in (a, b):
                    R.ensure_dressable(c, t, day)
                    if R.shortages(c, t):
                        raise R.RosterError("short")
            except R.RosterError:
                c.execute("ROLLBACK TO ai_hockey")
                c.execute("RELEASE ai_hockey")
                continue
            c.execute("RELEASE ai_hockey")
            _record(m, "roster", (a, b), [x, y])
            text = f"{team_abbr(c, a)} trade {player_name(c, x)} to {team_abbr(c, b)} for {player_name(c, y)}"
            emit(c, "TRADE_COMPLETED", day, text, team_id=a, other_team_id=b, player_id=y, importance=2,
                 players_out=[x], picks=[], kind="roster", hockey=True)
            return text
    return None


# ---------------------------------------------------------------- depth and minor-league deals (v39)

def _minor_pool(m, t, min_age=22):
    """A club's minor-leaguers who are not real prospects: 22+ and short of a top-prospect potential."""
    out = []
    for r in m.conn.execute("SELECT p.player_id, p.position, p.birth_date, d.potential FROM players p LEFT JOIN "
                            "player_dev d USING (player_id) WHERE p.team_id=? AND p.status='prospect'", (t,)):
        age = m.season - int(r[2][:4])
        if age >= min_age and (r[3] or 0) < MINOR_POTENTIAL_MAX and r[0] not in m.recently_moved:
            out.append(r[0])
    return out


def _contracts(m, t):
    from . import contracts as K
    return K.contract_count(m.conn, t, m.season)


def _fits_contracts(m, t, extra=1):
    from . import contracts as K
    lim = K.crules(m.conn).get("max_contracts")
    return not lim or _contracts(m, t) + extra <= lim


def minor_deal(m, rng, day):
    """A swap of minor-leaguers (often across positions), or one sent away for future considerations: clubs balance
    their contract count, fill a hole on the farm team, or give a stalled player a fresh start."""
    c = m.conn
    from . import contracts as K
    lim = K.crules(c).get("max_contracts") or 50
    teams = [t for t in m.teams if m.open_for_business(t, "minor")]
    if len(teams) < 2:
        return None
    wts = [3.0 if _contracts(m, t) >= lim - 3 else 1.0 for t in teams]
    a = rng.choices(teams, wts)[0]
    xs = _minor_pool(m, a)
    if not xs:
        return None
    x = rng.choice(xs)
    gx = m.group_of.get(x)
    vx = m.av(x)
    futures = _contracts(m, a) >= lim - 2 or rng.random() < P_FUTURES
    partners = [b for b in teams if b != a]
    rng.shuffle(partners)
    for b in partners[:8]:
        farm = [p for p in _minor_pool(m, b, 20) if m.group_of.get(p) == gx]
        if len(farm) >= MINOR_FARM_FULL:                   # b's farm team is already full at his position
            continue
        if futures:
            if not _fits_contracts(m, b) or _hit(c, x) > _cap_room(c, b) or vx > FUTURES_MAX:
                continue
            ys = []
        else:
            cands = [y for y in _minor_pool(m, b) if m.group_of.get(y) != gx or rng.random() < 0.35]
            cands = [y for y in cands if abs(m.av(y) - vx) <= max(MINOR_GAP_ABS, MINOR_GAP * max(vx, m.av(y)))]
            if not cands:
                continue
            ys = [rng.choice(cands)]
            if _hit(c, x) - _hit(c, ys[0]) > _cap_room(c, b) or _hit(c, ys[0]) - _hit(c, x) > _cap_room(c, a):
                continue
        c.execute("SAVEPOINT ai_minor")
        try:
            R.trade(c, a, [x], b, ys, day)
        except R.RosterError:
            c.execute("ROLLBACK TO ai_minor")
            c.execute("RELEASE ai_minor")
            continue
        c.execute("RELEASE ai_minor")
        _record(m, "minor", (a, b), [x, *ys])
        got = player_name(c, ys[0]) if ys else "future considerations"
        text = f"{team_abbr(c, b)} acquire {player_name(c, x)} from {team_abbr(c, a)} for {got}"
        emit(c, "TRADE_COMPLETED", day, text, team_id=b, other_team_id=a, player_id=x, importance=1,
             players_out=ys, picks=[], kind="minor", futures=not ys)
        return text
    return None


def _late_picks(m, t, max_round=7, min_round=3):
    return sorted((y, rnd, o) for y, rnd, o in picks_owned(m.conn, t, m.years, m.all_teams) if min_round <= rnd <= max_round)


def depth_deal(m, rng, day):
    """A fringe NHL player (outside the dressed lineup's top nine forwards / five defencemen / starting goalie) or a
    minor-league veteran goes to a club whose depth he improves, for a 3rd-7th round pick or future considerations.
    A player who would need waivers to go down, and sits outside his club's dressed lineup, is worth no more than a
    7th: the buyer could otherwise wait and claim him."""
    from . import waivers as W
    c = m.conn
    sellers = [t for t in m.teams if m.open_for_business(t, "depth")]
    if not sellers:
        return None
    s = rng.choices(sellers, [{"seller": 2.0, "middle": 1.3, "contender": 0.8}[m.posture[t]] for t in sellers])[0]
    cands = []
    for g, keep in DEPTH_KEEP.items():
        vals = sorted(((m.values[r["player_id"]], r["player_id"]) for r in R.roster(c, s)
                       if R.group(r["position"]) == g and r["status"] == "active"), reverse=True)
        spare = max(0, len(vals) - R.NEED[g])
        fringe = [pid for _, pid in vals[keep:] if pid not in m.recently_moved]
        cands += [(pid, g, True) for pid in fringe[:spare + 1]]
    cands += [(pid, m.group_of.get(pid), False) for pid in _minor_pool(m, s, 25)]
    rng.shuffle(cands)
    for pid, g, on_nhl in cands[:6]:
        if m.age(pid) < 24 or (m.friction(pid, s) > DEPTH_FRICTION_MAX):
            continue
        v = m.value_of(pid)
        buyers = []
        for b in m.teams:
            if b == s or not m.open_for_business(b, "depth") or m.needs[b][g] < DEPTH_NEED:
                continue
            mine = sorted(m.groups[b][g], reverse=True)
            last = mine[R.NEED[g] - 1] if len(mine) >= R.NEED[g] else 0.0
            if v >= last + 0.5 and m.friction(pid, s) <= m.needs[b][g]:
                buyers.append(b)
        if not buyers:
            continue
        b = rng.choice(buyers)
        price = m.av(pid) * m.weight(s, pid, receiving=False)
        scratch = on_nhl and W.needs_waivers(c, pid, day)
        if scratch:
            price = min(price, pick_value(None, len(m.all_teams), m.this_year, m.this_year, 7))
        picks = []
        if price >= FUTURES_MAX:
            opts = [(pk, _asset_value(m, ("pick", pk), s, True)) for pk in _late_picks(m, b)]
            opts = [(pk, v_) for pk, v_ in opts if v_ >= price]
            if not opts:
                continue
            pk = min(opts, key=lambda o: o[1])
            if pk[1] > price * 2.2 + 2:                  # nothing near his price: no deal
                continue
            picks = [pk[0]]
        worth = m.av(pid) * m.weight(b, pid, receiving=True, fills_need=True)
        sweetener = []
        if worth < 0:                                    # a cap dump: the seller pays to move his contract
            if _cap_room(c, s) > DUMP_ROOM or rng.random() > (1.0 if m.offseason else P_DUMP_IN_SEASON):
                continue
            opts = sorted((_asset_value(m, ("pick", pk), b, True), pk) for pk in picks_owned(c, s, m.years, m.all_teams))
            opts = [o for o in opts if o[0] >= -worth]
            if not opts or _hit(c, pid) + DUMP_ROOM > _cap_room(c, b):
                continue
            sweetener, picks = [opts[0][1]], []
        elif picks and _asset_value(m, ("pick", picks[0]), b, False) > worth:
            continue
        if _hit(c, pid) > _cap_room(c, b) or not _fits_contracts(m, b) or _clause_ok(m, pid, s, b):
            continue
        c.execute("SAVEPOINT ai_depth")
        try:
            mn, mx = R.limits(c)
            if on_nhl:
                if len(R.roster(c, b)) + 1 > mx:
                    R.make_room(c, b, day, g)
                _top_up(c, s, mn - (len(R.roster(c, s)) - 1), day)
            R.trade(c, b, [], s, [pid], day)
            for y, rnd, orig in picks:
                c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, orig, s, f"traded {day}"))
            for y, rnd, orig in sweetener:
                c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, orig, b, f"traded {day}"))
            for t in (b, s):
                R.ensure_dressable(c, t, day)
                if R.shortages(c, t):
                    raise R.RosterError("short")
        except R.RosterError:
            c.execute("ROLLBACK TO ai_depth")
            c.execute("RELEASE ai_depth")
            continue
        c.execute("RELEASE ai_depth")
        _record(m, "depth", (b, s), [pid])
        got = ", ".join(pick_label(c, y, rnd, o, b) for y, rnd, o in picks) or "future considerations"
        extra = (" and " + ", ".join(pick_label(c, y, rnd, o, s) for y, rnd, o in sweetener)) if sweetener else ""
        text = f"{team_abbr(c, b)} acquire {player_name(c, pid)}{extra} from {team_abbr(c, s)} for {got}"
        emit(c, "TRADE_COMPLETED", day, text, team_id=b, other_team_id=s, player_id=pid, importance=1 if not on_nhl else 2,
             players_out=[], picks=[list(p) for p in picks], picks_in=[list(p) for p in sweetener], kind="depth",
             futures=not picks, waiver_bound=bool(scratch), cap_dump=bool(sweetener))
        return text
    return None


def pick_swap(m, rng, day):
    """Draft day: a club moves up (its pick and a later one, or next year's pick, for a better pick this year), or a
    club sells this year's pick for next year's. The seller must value what it gets at 103%; the club moving up is
    willing to pay a little over (it has a player in mind) as long as it values the pick at 85% of the cost."""
    from itertools import combinations
    c = m.conn
    if m.this_year not in m.years:
        return None
    teams = [t for t in m.teams if m.open_for_business(t, "swap")]
    if len(teams) < 2:
        return None
    a = rng.choice(teams)
    if rng.random() > P_SWAP_TARGET:
        return None
    mine = picks_owned(c, a, m.years, m.all_teams)
    if not mine:
        return None
    rnd = rng.choices([1, 2, 3, 4], [4, 4, 2, 1])[0]
    targets = []
    for b in teams:
        if b == a:
            continue
        for pk in picks_owned(c, b, [m.this_year], m.all_teams):
            if pk[1] == rnd:
                targets.append((b, pk))
    rng.shuffle(targets)
    for b, want in targets[:6]:
        give_v = _asset_value(m, ("pick", want), b, False)
        neutral = lambda pk: pick_value(m.pick_slot.get(pk[2]), len(m.all_teams), pk[0], m.this_year, pk[1])
        # the main piece: a's pick in the same round, a worse slot this year, or the same round next year
        mains = [pk for pk in mine if pk[1] == want[1] and pk != want and neutral(pk) < neutral(want)]
        extras = [pk for pk in mine if pk[1] > want[1]]
        opts = mains + extras
        best = None
        for k in (1, 2):
            for combo in combinations(opts, k):
                if not any(pk in mains for pk in combo) or sum(1 for pk in combo if pk in mains) > 1:
                    continue
                got_b = TM.package_value([_asset_value(m, ("pick", pk), b, True) for pk in combo])
                if got_b < give_v * 1.03:
                    continue
                cost_a = TM.package_value([_asset_value(m, ("pick", pk), a, False) for pk in combo])
                if _asset_value(m, ("pick", want), a, True) < 0.85 * cost_a:
                    continue
                if best is None or cost_a < best[0]:
                    best = (cost_a, combo)
        if best is None:
            continue
        for y, r_, o in best[1]:
            c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, r_, o, b, f"traded {day}"))
        c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (*want, a, f"traded {day}"))
        _record(m, "swap", (a, b), [])
        text = (f"{team_abbr(c, a)} acquire {pick_label(c, *want, a)} from {team_abbr(c, b)} for "
                + ", ".join(pick_label(c, y, r_, o, a) for y, r_, o in best[1]))
        emit(c, "TRADE_COMPLETED", day, text, team_id=a, other_team_id=b, importance=1,
             players_out=[], picks=[list(p) for p in best[1]], kind="swap")
        return text
    return None


def rental(m, rng, day):
    """The deadline market (v39): a club out of the race sells a veteran on an expiring deal (outside its core) to a
    club in it whose top nine forwards / five defencemen / starting goalie he would join, for picks. The buyer's need
    at his position must be at least his friction (rentals carry 0.7 of it)."""
    c = m.conn
    sellers = [t for t in m.teams if m.S[t] < RENTAL_SELLER_S and m.open_for_business(t)]
    buyers = [t for t in m.teams if m.S[t] >= RENTAL_BUYER_S and m.open_for_business(t)]
    if not sellers or not buyers:
        return None
    s = rng.choice(sellers)
    pool = [r["player_id"] for r in R.roster(c, s) if r["status"] == "active" and r["player_id"] not in m.core[s]
            and r["player_id"] not in m.recently_moved and m.expiring(r["player_id"]) and m.age(r["player_id"]) >= 26]
    rng.shuffle(pool)
    for pid in pool[:4]:
        g = m.group_of.get(pid)
        if g is None:                                  # not in the market's groups (just called up, say)
            continue
        v = m.value_of(pid)
        fr = m.friction(pid, s)
        bs = []
        for b in buyers:
            mine = sorted(m.groups[b][g], reverse=True)
            bar = mine[DEPTH_KEEP[g] - 1] if len(mine) >= DEPTH_KEEP[g] else 0.0
            if v >= bar + 0.5 and fr <= m.needs[b][g] and not _clause_ok(m, pid, s, b):
                bs.append(b)
        if not bs:
            continue
        b = rng.choice(bs)
        want = m.av(pid) * m.weight(s, pid, receiving=False) * (TM.ACCEPT + fr / 100.0)
        worth = m.av(pid) * m.weight(b, pid, receiving=True, fills_need=True)
        if want <= FUTURES_MAX:
            continue
        picks = [("pick", pk) for pk in picks_owned(c, b, m.years, m.all_teams)]
        owned = set(pk for _, pk in picks)
        for _, (y, rnd, o) in list(picks):                 # v41: a contender's 2nd-4th can upgrade if it goes deep
            if y == m.this_year and 2 <= rnd <= 4 and (y, rnd - 1, o) in owned and not protection(c, y, rnd - 1, o) \
                    and rng.random() < COND_SHARE:
                picks.append(("pick", (y, rnd, o), cond_spec("round2" if m.S[b] >= COND_ROUND2_S else "playoffs", b)))
        pkg = _build_package(m, b, s, want, picks, rng, max_assets=2)
        if pkg is None or pkg[1] > worth:
            continue
        retain = None
        if _hit(c, pid) > _cap_room(c, b):
            if _hit(c, pid) * 0.5 > _cap_room(c, b):
                continue
            retain = {pid: 0.5}
            want += TM.retention_value(c, s, pid, 0.5, day)
            pkg = _build_package(m, b, s, want, picks, rng, max_assets=2)
            if pkg is None or pkg[1] > worth:
                continue
        c.execute("SAVEPOINT ai_rental")
        try:
            mn, mx = R.limits(c)
            if len(R.roster(c, b)) + 1 > mx:
                R.make_room(c, b, day, g)
            _top_up(c, s, mn - (len(R.roster(c, s)) - 1), day)
            R.trade(c, b, [], s, [pid], day, retain=retain)
            for a in pkg[0]:
                c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (*a[1], s, f"traded {day}"))
                if len(a) > 2 and parse_spec(a[2]):
                    set_condition(c, *a[1], b, *parse_spec(a[2]))
            for t in (b, s):
                R.ensure_dressable(c, t, day)
                if R.shortages(c, t):
                    raise R.RosterError("short")
        except R.RosterError:
            c.execute("ROLLBACK TO ai_rental")
            c.execute("RELEASE ai_rental")
            continue
        c.execute("RELEASE ai_rental")
        _room_signal(c, b, m.S[b], True, False)
        _record(m, "roster", (b, s), [pid])
        got = ", ".join(pick_label(c, *a[1], b) for a in pkg[0])
        text = (f"{team_abbr(c, b)} acquire {player_name(c, pid)} from {team_abbr(c, s)} for {got}"
                + (" (50% retained)" if retain else ""))
        emit(c, "TRADE_COMPLETED", day, text, team_id=b, other_team_id=s, player_id=pid, importance=2,
             players_out=[], picks=[list(a[1]) for a in pkg[0]], retained=bool(retain), kind="roster", rental=True,
             friction=round(fr, 1))
        return text
    return None


def three_team_tail(m, buyer, seller, rng, day):
    """Defect 3a: AI clubs make three-team trades too. After a trade, a third club with cap room takes a mid-value
    contract off one side for a late pick (the facilitator), as real three-way deals usually work. Rare."""
    c = m.conn
    from . import contracts as K
    yr = K.season_year(c)
    for side in rng.sample([buyer, seller], 2):
        payroll = K.payroll(c, side)
        cap = K.crules(c)["cap_ceiling"]
        if cap - payroll > 3_000_000:                         # only a side tight to the cap needs a facilitator
            continue
        roster = [r for r in R.roster(c, side) if r["status"] == "active"]
        cands = []
        for r in roster:
            k = K.current_contract(c, r["player_id"], yr)
            if k and 1_500_000 <= k["cap_hit"] <= 5_000_000 and r["player_id"] not in m.core.get(side, set()):
                cands.append((k["cap_hit"], r["player_id"], r["position"]))
        if not cands:
            continue
        hit, pid, pos = max(cands)
        thirds = [t for t in m.teams if t not in (buyer, seller) and cap - K.payroll(c, t) > hit + 1_000_000]
        if not thirds:
            continue
        third = rng.choice(thirds)
        if _clause_ok(m, pid, side, third):
            continue
        picks = [(y, rnd, o) for y, rnd, o in picks_owned(c, side, tradeable_years(c), m.all_teams) if rnd >= 4]
        if not picks:
            continue
        pk = min(picks)
        c.execute("SAVEPOINT ai_trade3")
        try:
            R.trade(c, side, [pid], third, [], day)
            c.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (*pk, third, f"traded {day}"))
            for t in (side, third):
                R.ensure_dressable(c, t, day)
                if R.shortages(c, t):
                    raise R.RosterError("short")
        except (R.RosterError, Exception):
            c.execute("ROLLBACK TO ai_trade3")
            c.execute("RELEASE ai_trade3")
            continue
        c.execute("RELEASE ai_trade3")
        other = seller if side == buyer else buyer
        text = (f"Three-team trade: {team_abbr(c, third)} take {player_name(c, pid)} (${hit / 1e6:.2f}M) from {team_abbr(c, side)} "
                f"with {pick_label(c, *pk, third)} to make the {team_abbr(c, buyer)}-{team_abbr(c, seller)} deal fit under the cap")
        emit(c, "TRADE_COMPLETED", day, text, team_id=side, other_team_id=other, player_id=pid, importance=3,
             three_team=True, third_team_id=third, facilitator=True, kind="depth")
        m.recently_moved.add(pid)
        return text
    return None


# ---------------------------------------------------------------- the router and schedule hooks

STATS = collections.Counter()          # attempts and successes by kind (calibration)
INTENTS = {"minor": minor_deal, "depth": depth_deal, "swap": pick_swap, "rental": None}


def phase_of(conn, day):
    """early (to 31 Dec), mid (to two weeks before the deadline), rush (the last two weeks), deadline (the day)."""
    d, dl = datetime.date.fromisoformat(day), deadline(conn)
    if d == dl:
        return "deadline"
    if (dl - d).days < DEADLINE_RUSH_DAYS:
        return "rush"
    return "early" if d.month >= 7 else "mid"


def route(m, rng, day, phase, n):
    """Make up to n trade attempts of the kinds this phase calls for (MIX). Returns the trades made."""
    mix = MIX[phase]
    made = []
    for _ in range(n):
        kind = rng.choices(list(mix), list(mix.values()))[0]
        STATS[kind + ":try"] += 1
        if kind == "roster":
            t = attempt(m.conn, day, rng, m, deadline_rush=phase in ("rush", "deadline"))
        elif kind == "rental":
            t = rental(m, rng, day)
        else:
            t = INTENTS[kind](m, rng, day)
        if t:
            STATS[kind + ":ok"] += 1
            made.append(t)
    return made


def ai_day(conn, day, rng):
    """In-season daily hook (called by the day loop). Returns the trades made."""
    from . import contracts as K
    if K.season_state(conn) != "regular_season":
        return []
    ensure_tables(conn)
    d, dl = datetime.date.fromisoformat(day), deadline(conn)
    if d > dl:
        return []
    phase = phase_of(conn, day)
    lam = ATTEMPTS[phase]
    n = int(lam) + (1 if rng.random() < lam - int(lam) else 0)
    if not n:
        return []
    m = Market(conn, day)
    m.rush = phase in ("rush", "deadline")
    return route(m, rng, day, phase, n)


def ai_window(conn, day, phase):
    """Offseason trading windows: draft day (pick swaps and player trades) and the opening of free agency."""
    n = OFFSEASON_ATTEMPTS.get(phase, 0)
    if not n:
        return []
    ensure_tables(conn)
    from .state import get_state
    rng = random.Random(f"{get_state(conn)[1]}-{day}-trades-{phase}")
    m = Market(conn, day)
    return route(m, rng, day, phase, n)


def recent(conn, n=30):
    from .events import recent as ev
    return ev(conn, types=["TRADE_COMPLETED"], limit=n)
