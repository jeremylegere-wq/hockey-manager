"""Salary arbitration (restricted free agents).

Model (our own; real hearings weigh statistics, role and comparable contracts):
  hearing value what the arbitrator sees: 75% the box score of the last two NHL seasons (platform year 60%, the
                year before 40%; skaters points per game 70% + goals per game 30%; goalies save % 60% + wins per
                game 40%), mapped onto the value scale by percentile in his position group, and 25% everything else
                (ratings). Arbitrators reward counting stats, not play-driving: a point-producer wins big awards, a
                quiet play-driver does not (which analytics-minded clubs can exploit).
  comparables   median cap hit of rostered players whose hearing value is within COMP_BAND of his
                (falls back to his market value if fewer than MIN_COMPS)
  player ask    max(market, comparables) * 1.12
  team offer    min(market, comparables) * 0.88, never below the qualifying offer (player-elected) or
                club_election_floor x prior salary (club-elected)
  award         0.5 x comparables + 0.25 x ask + 0.25 x offer, +-4% arbitrator noise, kept between offer and ask.
                As far as we know NHL arbitrators may award any figure (unlike MLB's pick-one-side system), so
                the award is not forced to one side's number.
  term          1 or 2 years, chosen by the side that did not elect (1 if he is one year from UFA status).
  walk-away     on player-elected awards at or above arbitration_walkaway the club may decline; he becomes a UFA.
"""
from __future__ import annotations

import datetime
import random
import statistics

from . import contracts as K
from .roster import player_value

COMP_BAND = 4.0
MIN_COMPS = 5


BOX_WEIGHT = 0.75
PLATFORM_WEIGHT = 0.6
MIN_GAMES = 20


class HearingLens:
    """The arbitrator's view: box score over ratings (see the module docstring)."""

    def __init__(self, conn, raw):
        from .roster import group
        year = K.season_year(conn)
        top = conn.execute("SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
        top = top[0] if top else 1
        rec = {}
        for pid, season, gp, g, a in conn.execute(
                "SELECT player_id, season_start_year, SUM(gp), SUM(g), SUM(a) FROM skater_season_stats WHERE "
                "league_id=? AND split='RS' AND season_start_year>=? GROUP BY player_id, season_start_year",
                (top, year - 1)):
            w = PLATFORM_WEIGHT if season == year else 1 - PLATFORM_WEIGHT
            d = rec.setdefault(pid, [0.0, 0.0, 0.0, 0])
            if gp:
                d[0] += w * (0.7 * (g + a) / gp + 0.3 * g / gp)
                d[2] += w
                d[3] += gp
        for pid, season, gp, w_, ga, sa in conn.execute(
                "SELECT player_id, season_start_year, SUM(gp), SUM(w), SUM(ga), SUM(sa) FROM goalie_season_stats "
                "WHERE league_id=? AND split='RS' AND season_start_year>=? GROUP BY player_id, season_start_year",
                (top, year - 1)):
            wt = PLATFORM_WEIGHT if season == year else 1 - PLATFORM_WEIGHT
            d = rec.setdefault(pid, [0.0, 0.0, 0.0, 0])
            if gp and sa:
                d[1] += wt * (0.6 * (1 - (ga or 0) / sa) * 10 + 0.4 * (w_ or 0) / gp)
                d[2] += wt
                d[3] += gp
        self.box = {pid: (d[0] + d[1]) / d[2] for pid, d in rec.items() if d[2] > 0 and d[3] >= MIN_GAMES}
        self.pos = {r[0]: group(r[1]) for r in conn.execute("SELECT player_id, position FROM players")}
        self.pools = {}
        for gname in ("F", "D", "G"):
            ids = [p for p in raw if self.pos.get(p) == gname]
            have = sorted(self.box[p] for p in ids if p in self.box)
            if len(have) >= 5:
                self.pools[gname] = (sorted(raw[p] for p in ids), have)
        self.raw = raw

    def value(self, pid, raw=None):
        raw = raw if raw is not None else self.raw.get(pid)
        if raw is None:
            raw = player_value(self._conn, pid) if hasattr(self, "_conn") else 50.0
        g = self.pos.get(pid)
        if pid not in self.box or g not in self.pools:
            return raw
        scale, have = self.pools[g]
        import bisect
        pct = bisect.bisect_right(have, self.box[pid]) / len(have)
        bv = scale[min(len(scale) - 1, int(pct * (len(scale) - 1)))]
        return BOX_WEIGHT * bv + (1 - BOX_WEIGHT) * raw


def market_context(conn):
    """Hearing values and current cap hits of rostered players, computed once per offseason step."""
    year = K.season_year(conn)
    raw, hits = {}, {}
    for r in conn.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL AND status IN ('active','injured')"):
        raw[r["player_id"]] = player_value(conn, r["player_id"])
        c = K.current_contract(conn, r["player_id"], year)
        if c:
            hits[r["player_id"]] = c["cap_hit"]
    lens = HearingLens(conn, raw)
    vmap = {p: lens.value(p) for p in raw}
    return dict(values=sorted(vmap.values()), vmap=vmap, hits=hits, lens=lens)


def hearing_value(conn, pid, ctx):
    return ctx["vmap"].get(pid) if pid in ctx["vmap"] else ctx["lens"].value(pid, player_value(conn, pid))


def comparables(conn, pid, ctx=None):
    ctx = ctx or market_context(conn)
    v = hearing_value(conn, pid, ctx)
    hits = [h for q, h in ctx["hits"].items() if q != pid and abs(ctx["vmap"][q] - v) <= COMP_BAND]
    if len(hits) < MIN_COMPS:
        return K.market_aav(conn, pid, ctx["values"], v=v), len(hits)
    return int(statistics.median(hits)), len(hits)


def submissions(conn, pid, prev_aav, qo, elected_by, ctx=None):
    cr = K.crules(conn)
    ctx = ctx or market_context(conn)
    market = K.market_aav(conn, pid, ctx["values"], v=hearing_value(conn, pid, ctx))
    comp, n = comparables(conn, pid, ctx)
    ask = int(round(max(market, comp) * 1.12 / 5000) * 5000)
    floor = qo if elected_by == "player" else int(cr["club_election_floor"] * prev_aav)
    offer = int(round(max(floor, cr["min_salary"], min(market, comp) * 0.88) / 5000) * 5000)
    ask = max(ask, offer)
    return dict(market=market, comparables=comp, n_comps=n, ask=ask, offer=offer)


def award(conn, pid, sub, seed, year):
    rng = random.Random(f"{seed}-{year}-arb-{pid}")
    raw = (0.5 * sub["comparables"] + 0.25 * sub["ask"] + 0.25 * sub["offer"]) * rng.uniform(0.96, 1.04)
    return int(round(min(max(raw, sub["offer"]), sub["ask"]) / 5000) * 5000)


def one_year_from_ufa(conn, pid, year):
    """True if after one more season he would be a UFA (so only a 1-year award is allowed)."""
    return K.rights_status(conn, pid, year + 1) == "UFA"


def choose_term(conn, pid, amount, market, elected_by, year):
    if one_year_from_ufa(conn, pid, year):
        return 1
    if elected_by == "player":           # club chooses: lock in a good price for two years
        return 2 if amount <= market else 1
    return 1 if amount < market else 2   # player chooses: short when underpaid


def can_walk_away(conn, amount, elected_by):
    return elected_by == "player" and amount >= K.crules(conn)["arbitration_walkaway"]


def club_elected_before(conn, pid):
    return conn.execute("SELECT 1 FROM transactions WHERE player_id=? AND txn_type='arbitration' AND "
                        "detail LIKE 'club-elected%'", (pid,)).fetchone() is not None


def age(conn, pid, on):
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()["birth_date"]
    return K.age_on(b, on)


def hearing_day(year):
    return datetime.date(year + 1, 8, 1).isoformat()
