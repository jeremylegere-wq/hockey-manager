"""Standings from played games, with configurable tiebreakers (default: the NHL's order)."""
from __future__ import annotations

from collections import defaultdict


def table(conn, season_id=None, game_type="RS"):
    """Per-team record dict from played games. went_to_ot: 0 regulation, 1 overtime, 2 shootout; equal goals = tie."""
    q = ("SELECT home_team_id, away_team_id, home_goals, away_goals, went_to_ot FROM games "
         "WHERE played=1 AND game_type=?" + (" AND season_id=?" if season_id else ""))
    rows = conn.execute(q, (game_type, season_id) if season_id else (game_type,)).fetchall()
    rec = defaultdict(lambda: dict(gp=0, w=0, l=0, otl=0, t=0, rw=0, row=0, gf=0, ga=0))
    h2h = defaultdict(lambda: [0, 0])      # (a, b) -> [points a earned vs b, games]
    return _fill(rows, rec, h2h)


def _fill(rows, rec, h2h, win_pts=2, otl_pts=1, tie_pts=1):
    for h, a, hg, ag, ot in rows:
        for t, o, gf, ga in ((h, a, hg, ag), (a, h, ag, hg)):
            r = rec[t]
            r["gp"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf == ga:                     # a tie (eras without a shootout)
                r["t"] += 1
                p = tie_pts
            elif gf > ga:
                r["w"] += 1
                r["rw"] += ot == 0
                r["row"] += ot <= 1
                p = win_pts
            else:
                r["l"] += ot == 0
                r["otl"] += ot > 0
                p = otl_pts if ot > 0 else 0
            h2h[(t, o)][0] += p
            h2h[(t, o)][1] += 1
    return rec, h2h


def points(rec, pts):
    return (rec["w"] * pts["win"] + rec["otl"] * pts["ot_loss"] + rec["l"] * pts["loss"]
            + rec.get("t", 0) * pts.get("tie", 1))


def rank(rec, h2h, rules, ids=None):
    """Team ids best-to-worst under rules['tiebreakers']. Head-to-head uses games among the tied group only."""
    pts = rules["points"]
    ids = list(ids if ids is not None else rec)
    stat = {t: dict(points=points(rec[t], pts), points_pct=points(rec[t], pts) / max(1, rec[t]["gp"] * pts["win"]),
                    regulation_wins=rec[t]["rw"], regulation_overtime_wins=rec[t]["row"], wins=rec[t]["w"],
                    goal_diff=rec[t]["gf"] - rec[t]["ga"], goals_for=rec[t]["gf"]) for t in ids}

    def order(group, crits):
        if len(group) <= 1 or not crits:
            return sorted(group)
        c, rest = crits[0], crits[1:]
        if c == "head_to_head_points":
            val = {}
            for t in group:
                p = sum(h2h[(t, o)][0] for o in group if o != t)
                g = sum(h2h[(t, o)][1] for o in group if o != t)
                val[t] = p / g if g else 0.0
        else:
            val = {t: stat[t][c] for t in group}
        out = []
        for v in sorted(set(val.values()), reverse=True):
            out += order([t for t in group if val[t] == v], rest)
        return out
    return order(ids, rules["tiebreakers"])
