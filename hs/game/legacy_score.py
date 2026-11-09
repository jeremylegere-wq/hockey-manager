"""The Career Legacy Score (CLS) and the Hall of Fame queue (v45; docs/HALL_OF_FAME.md).

1. Season Value (SV): each NHL regular season against the league average of that season's starters at the position
   (starters: a club's top six forwards, six defencemen and starting goalie, times the clubs that season: the top six
   rather than all twelve forwards so that the three positions share one scale - the tenth-best season of the decade
   is about 2.5 for a forward, 2.8 for a defenceman and 2.3 for a goalie). An average starter scores 1.0; an
   MVP-calibre season about 2.2-2.8, a historic one 3+.
     forwards     SV = 0.75 x points/avg points + 0.25 x goals/avg goals
     defencemen   SV = 0.50 x points/avg points + 0.30 x DPS/avg DPS + 0.20 x TOI/avg TOI
     goalies      SV = 0.30 x wins/avg wins + 0.50 x GSAA term + 0.20 x starts/avg starts
   Defensive point shares (DPS) here: minutes played x the club's defence (the league's goals against a game over
   the club's) x (1 + half his plus-minus a game, capped at +-0.5). Minutes come from TOI where the season has it,
   else 20 a game for a defenceman. GSAA is saves minus what a league-average save % would have stopped; because the
   average starter's GSAA is near zero (so a ratio would blow up), its term is 1 + (GSAA - starters' average GSAA) /
   (1% of the starters' average shots against): one point of save % over a starter's workload is worth +1.0.
2. Peak vs longevity (PVL): peak P = the sum of his best 7 SV; longevity L = the sum of the rest. PVL = 10P + 3L.
3. Hardware ledger (HL): Hart and Conn Smythe +50; Norris and Vezina +40; Selke and Art Ross +25; First All-Star Team
   +15; a championship +30 plus up to +20 for his share of the run (his playoff points against the average of the
   champion's regulars, or a goalie's share of the wins); milestones (career totals, before the save included):
     forwards     500 goals +20, 1000 points +20, 1500 points +30
     defencemen   1000 games +15, 500 points +20, 1000 points +40
     goalies      300 wins +15, 500 wins +30, 50 shutouts +20
   (Trophies count for seasons played in the save; the database's history carries no trophies.)
CLS = PVL + HL. Tiers: Inner Circle over 450; First Ballot 350-449; Hall of Fame 250-349; Hall of Very Good 180-249.

Induction (each summer, when the re-signing phase opens): a player becomes eligible three years after he retired
(the summer after his last NHL season); a CLS of 250 puts him on the ballot, for up to ten years; the best four by
CLS go in (a tie goes to the one longer on the ballot). If you sit on the selection committee (career option hof),
your up-to-four votes move a candidate ahead of any unbacked candidate within 15 points of him.
"""
from __future__ import annotations

from collections import defaultdict

WAIT = 3
MAX_IN = 4
THRESHOLD = 250.0
BALLOT_YEARS = 10
PEAK_N = 7
PEAK_W, LONG_W = 10.0, 3.0
VOTE_EDGE = 15.0
STARTERS = {"F": 6, "D": 6, "G": 1}
TIERS = [(450, "Inner Circle"), (350, "First Ballot"), (250, "Hall of Fame"), (180, "Hall of Very Good")]
HARDWARE = {"hart": 50, "conn_smythe": 50, "norris": 40, "vezina": 40, "selke": 25, "art_ross": 25}
ALL_STAR = 15
CUP_BASE, CUP_SHARE = 30.0, 20.0
MILESTONES = {
    "F": [("g", 500, 20, "500 goals"), ("pts", 1000, 20, "1,000 points"), ("pts", 1500, 30, "1,500 points")],
    "D": [("gp", 1000, 15, "1,000 games"), ("pts", 500, 20, "500 points"), ("pts", 1000, 40, "1,000 points")],
    "G": [("w", 300, 15, "300 wins"), ("w", 500, 30, "500 wins"), ("so", 50, 20, "50 shutouts")],
}


def tier(cls):
    return next((name for bar, name in TIERS if cls >= bar), "")


def _group(pos):
    return "G" if pos == "G" else "D" if pos == "D" else "F"


def _top(conn):
    from .legacy import _top as t
    return t(conn)


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------- season values
def season_values(conn, split="RS", pids=None):
    """{pid: {year: SV}} for every NHL season on file (or for `pids`). League averages always use every player."""
    lg = _top(conn)
    pos = {r[0]: _group(r[1]) for r in conn.execute("SELECT player_id, position FROM players")}
    # the clubs' defence: goals against a game, from the goalies' lines
    team_ga = defaultdict(lambda: [0, 0])
    lg_sv = defaultdict(lambda: [0, 0])
    grows = conn.execute("SELECT player_id, season_start_year, COALESCE(CAST(team_id AS TEXT), club_name), gp, gs, w, so, ga, sa "
                         "FROM goalie_season_stats WHERE league_id=? AND split=?", (lg, split)).fetchall()
    for pid, y, tk, gp, gs, w, so, ga, sa in grows:
        team_ga[(y, tk)][0] += ga or 0
        team_ga[(y, tk)][1] += (gs or 0) or (gp or 0)
        lg_sv[y][0] += (sa or 0) - (ga or 0)
        lg_sv[y][1] += sa or 0
    lg_gapg = {}
    for (y, tk), (ga, g) in team_ga.items():
        lg_gapg.setdefault(y, [0, 0])
        lg_gapg[y][0] += ga
        lg_gapg[y][1] += g
    lg_gapg = {y: ga / g if g else 3.0 for y, (ga, g) in lg_gapg.items()}

    def team_def(y, tk):
        ga, g = team_ga.get((y, tk), (0, 0))
        return (lg_gapg.get(y, 3.0) / (ga / g)) if g and ga else 1.0

    seasons = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))   # y -> pid -> stat
    clubs = defaultdict(set)
    for pid, y, tk, gp, g, a, pm, toi in conn.execute(
            "SELECT player_id, season_start_year, COALESCE(CAST(team_id AS TEXT), club_name), gp, g, a, plus_minus, toi_sec "
            "FROM skater_season_stats WHERE league_id=? AND split=?", (lg, split)):
        grp = pos.get(pid, "F")
        if grp == "G":
            continue
        gp = gp or 0
        s = seasons[y][pid]
        s["gp"] += gp
        s["g"] += g or 0
        s["pts"] += (g or 0) + (a or 0)
        mins = (toi or 0) / 60 if toi and toi > 0 else gp * (20 if grp == "D" else 15)
        s["toi"] += mins
        if grp == "D":
            pmg = max(-0.5, min(0.5, (pm or 0) / gp)) if gp else 0.0
            s["dps"] += mins * team_def(y, tk) * (1 + 0.5 * pmg)
        clubs[y].add(tk)
    for pid, y, tk, gp, gs, w, so, ga, sa in grows:
        s = seasons[y][pid]
        s["gp"] += gp or 0
        s["starts"] += (gs or 0) or (gp or 0)
        s["w"] += w or 0
        sv = lg_sv[y][0] / lg_sv[y][1] if lg_sv[y][1] else 0.905
        s["gsaa"] += ((sa or 0) - (ga or 0)) - (sa or 0) * sv
        s["sa"] += sa or 0
        clubs[y].add(tk)
    out = defaultdict(dict)
    for y, players in seasons.items():
        n_clubs = max(len(clubs[y]), 1) if split == "RS" else max(len(clubs[y]), 1)
        by = {"F": [], "D": [], "G": []}
        for pid, s in players.items():
            by[pos.get(pid, "F")].append((pid, s))
        avg = {}
        for grp, rows in by.items():
            key = (lambda x: (x[1]["starts"], x[1]["w"])) if grp == "G" else (lambda x: (x[1]["gp"], x[1]["pts"]))
            st = [s for _, s in sorted(rows, key=key, reverse=True)[:STARTERS[grp] * n_clubs]]
            avg[grp] = {k: _mean([s[k] for s in st]) for k in ("gp", "g", "pts", "toi", "dps", "w", "gsaa", "starts", "sa")}
        for grp, rows in by.items():
            A = avg[grp]
            r = lambda v, k: v / A[k] if A[k] > 0 else 0.0
            for pid, s in rows:
                if pids is not None and pid not in pids:
                    continue
                if grp == "F":
                    v = 0.75 * r(s["pts"], "pts") + 0.25 * r(s["g"], "g")
                elif grp == "D":
                    v = 0.50 * r(s["pts"], "pts") + 0.30 * r(s["dps"], "dps") + 0.20 * r(s["toi"], "toi")
                else:
                    scale = max(10.0, 0.01 * A["sa"])
                    gs_term = max(0.0, 1 + (s["gsaa"] - A["gsaa"]) / scale) if s["sa"] else r(s["starts"], "starts")
                    v = 0.30 * r(s["w"], "w") + 0.50 * gs_term * min(1.0, r(s["starts"], "starts")) + 0.20 * r(s["starts"], "starts")
                out[pid][y] = round(v, 3)
    return out


def pvl(svs):
    vals = sorted(svs, reverse=True)
    peak, rest = vals[:PEAK_N], vals[PEAK_N:]
    return PEAK_W * sum(peak) + LONG_W * sum(rest), sum(peak), sum(rest)


# ---------------------------------------------------------------- hardware
def _totals(conn, pid, grp):
    from . import career as CR
    lg = _top(conn)
    pr = CR.prior(conn, pid) or {}
    if grp == "G":
        r = conn.execute("SELECT SUM(gp), SUM(w), SUM(so) FROM goalie_season_stats WHERE player_id=? AND league_id=? AND split='RS'",
                         (pid, lg)).fetchone()
        return dict(gp=(r[0] or 0) + (pr.get("gp") or 0), w=(r[1] or 0) + (pr.get("w") or 0), so=(r[2] or 0) + (pr.get("so") or 0))
    r = conn.execute("SELECT SUM(gp), SUM(g), SUM(a) FROM skater_season_stats WHERE player_id=? AND league_id=? AND split='RS'",
                     (pid, lg)).fetchone()
    gp, g, a = (r[0] or 0) + (pr.get("gp") or 0), (r[1] or 0) + (pr.get("g") or 0), (r[2] or 0) + (pr.get("a") or 0)
    return dict(gp=gp, g=g, pts=g + a)


def _cups(conn, pid, grp):
    """[(year, share 0-1)] for each championship he played in the playoffs for."""
    if not _has(conn, "team_seasons"):
        return []
    lg = _top(conn)
    tbl = "goalie_season_stats" if grp == "G" else "skater_season_stats"
    out = []
    for y, t in conn.execute(f"SELECT DISTINCT s.season_start_year, s.team_id FROM {tbl} s JOIN team_seasons ts ON "
                             "ts.season_start_year=s.season_start_year AND ts.team_id=s.team_id WHERE s.player_id=? AND "
                             "s.league_id=? AND ts.playoff_round=5 AND s.split='RS'", (pid, lg)).fetchall():
        if grp == "G":
            mine = conn.execute("SELECT COALESCE(SUM(w),0) FROM goalie_season_stats WHERE player_id=? AND season_start_year=? AND "
                                "team_id=? AND split='PO'", (pid, y, t)).fetchone()[0]
            share = min(1.0, mine / 16.0)
        else:
            rows = [r[0] + r[1] for r in conn.execute(
                "SELECT COALESCE(SUM(s.g),0), COALESCE(SUM(s.a),0) FROM skater_season_stats s JOIN players p USING (player_id) WHERE "
                "s.season_start_year=? AND s.team_id=? AND s.split='PO' AND p.position<>'G' GROUP BY s.player_id ORDER BY SUM(s.gp) DESC "
                "LIMIT 18", (y, t))]
            mine = conn.execute("SELECT COALESCE(SUM(g),0)+COALESCE(SUM(a),0) FROM skater_season_stats WHERE player_id=? AND "
                                "season_start_year=? AND team_id=? AND split='PO'", (pid, y, t)).fetchone()[0]
            avg = _mean(rows)
            share = min(1.0, (mine / avg) / 2.0) if avg else 0.0          # twice the regulars' average fills it
        out.append((y, share))
    return out


def hardware(conn, pid, grp=None, totals=None):
    """(points, [(label, points)])."""
    if grp is None:
        p = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
        grp = _group(p[0] if p else "C")
    items = []
    if _has(conn, "awards"):
        from .history import AWARDS
        for k, n in conn.execute("SELECT award, COUNT(*) FROM awards WHERE player_id=? GROUP BY award", (pid,)):
            if k in HARDWARE:
                items.append((f"{AWARDS[k][0]}{f' x{n}' if n > 1 else ''}", HARDWARE[k] * n))
            elif k.startswith("allstar_"):
                items.append(("_allstar", ALL_STAR * n))
    stars = sum(v for k, v in items if k == "_allstar")
    items = [x for x in items if x[0] != "_allstar"]
    if stars:
        items.append((f"First All-Star Team x{stars // ALL_STAR}", stars))
    for y, share in _cups(conn, pid, grp):
        items.append((f"Championship {y}-{(y + 1) % 100:02d}", round(CUP_BASE + CUP_SHARE * share, 1)))
    t = totals or _totals(conn, pid, grp)
    for k, bar, pts, label in MILESTONES[grp]:
        if t.get(k, 0) >= bar:
            items.append((label, pts))
    return round(sum(v for _, v in items), 1), items


def score(conn, pid, svs=None):
    """dict(cls, tier, pvl, peak, longevity, hardware, items, seasons, best)."""
    p = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
    grp = _group(p[0] if p else "C")
    if svs is None:
        svs = season_values(conn).get(pid, {})
    v, peak, rest = pvl(list(svs.values()))
    hw, items = hardware(conn, pid, grp)
    cls = round(v + hw, 1)
    best = sorted(svs.items(), key=lambda kv: -kv[1])[:PEAK_N]
    return dict(player_id=pid, group=grp, cls=cls, tier=tier(cls), pvl=round(v, 1), peak=round(peak, 2), longevity=round(rest, 2),
                hardware=hw, items=items, seasons=len(svs), best=[dict(season=y, sv=s) for y, s in sorted(best)])


def scores(conn, pids):
    sv = season_values(conn)
    return {p: score(conn, p, sv.get(p, {})) for p in pids}


# ---------------------------------------------------------------- the queue
def last_season(conn, pid):
    lg = _top(conn)
    r = conn.execute("SELECT MAX(y) FROM (SELECT MAX(season_start_year) y FROM skater_season_stats WHERE player_id=? AND league_id=? AND "
                     "split='RS' UNION ALL SELECT MAX(season_start_year) FROM goalie_season_stats WHERE player_id=? AND league_id=? AND "
                     "split='RS')", (pid, lg, pid, lg)).fetchone()
    return r[0]


def candidates(conn, year):
    """[dict(score..., last, retired, years_on_ballot)] for the `year` ballot: retired, waited, CLS 250+, within ten years."""
    from .legacy import ensure_tables
    ensure_tables(conn)
    lg = _top(conn)
    held = {r[0] for r in conn.execute("SELECT player_id FROM hall_of_fame")}
    lasts = {}
    for t in ("skater_season_stats", "goalie_season_stats"):
        for pid, y in conn.execute(f"SELECT s.player_id, MAX(s.season_start_year) FROM {t} s JOIN players p USING (player_id) WHERE "
                                   f"p.status='retired' AND s.league_id=? AND s.split='RS' GROUP BY s.player_id", (lg,)):
            lasts[pid] = max(lasts.get(pid, y), y)
    sv = None
    out = []
    for pid, last in lasts.items():
        if pid in held:
            continue
        retired = last + 1
        on = (year - retired) - (WAIT - 1)
        if on < 1 or on > BALLOT_YEARS:
            continue
        if sv is None:
            sv = season_values(conn)
        s = score(conn, pid, sv.get(pid, {}))
        if s["cls"] >= THRESHOLD:
            s.update(last=last, retired=retired, years_on_ballot=on)
            out.append(s)
    out.sort(key=lambda s: (s["cls"], s["years_on_ballot"]), reverse=True)
    return out


def order(cands, backed=()):
    """The induction order: CLS (ties: longer on the ballot); a backed candidate passes unbacked ones within 15 points."""
    backed = set(backed)
    eff = lambda s: s["cls"] + (VOTE_EDGE if s["player_id"] in backed else 0.0)
    return sorted(cands, key=lambda s: (eff(s), s["cls"], s["years_on_ballot"]), reverse=True)


def tracker(conn, limit=30, active=True):
    """The best careers by CLS: active players (where they stand) or everyone."""
    sv = season_values(conn)
    where = "status<>'retired'" if active else "1=1"
    ids = [r[0] for r in conn.execute(f"SELECT player_id FROM players WHERE {where}")]
    rough = sorted((pvl(list(sv.get(p, {}).values()))[0], p) for p in ids if p in sv)[-limit * 3:]
    full = [score(conn, p, sv.get(p, {})) for _, p in rough]
    full.sort(key=lambda s: -s["cls"])
    return full[:limit]
