"""2D replay of a played game, built from its stored events (docs/ARCHITECTURE_AUDIT.md section 5, "replay view").

The match engine is statistical: it records what happened (shot, block, miss, goal, penalty, shootout attempt, with
the shooter, the goalie or blocker and the shot's goal probability) but not where anyone stood. The replay places each
event on a 200 x 85 ft rink (centre ice = 0, 0; nets at x = +-89) with plausible positions, deterministically from the
game id, so every past game replays the same way and the engine's calibration is untouched:

  attacking end    home shoots at +x in periods 1, 3 and overtime, at -x in the 2nd; away the other way
  shot distance    from the event's goal probability: 8 + 52 x e^(-xg/0.06) ft (xg 0.03 ~ 40 ft, 0.15 ~ 12 ft),
                   +-20%; angle up to +-70 degrees, narrower for better chances
  misses, blocks   no probability stored: drawn as 30-55 ft attempts; blocks stop a third to half of the way in
  between events   the puck is carried from one event to the next through the neutral zone (frames in between are
                   interpolated in the browser)

Skater dots other than the shooter, blocker and goalie are not real players: the engine does not store who was on
the ice for each shot. They are five generic markers per side, drawn in the attacking team's formation.
"""
from __future__ import annotations

import math
import random

from .events import player_name, team_abbr

NET_X = 89.0
HALF_W = 42.5


def _attack_dir(is_home, period):
    """+1 if this side shoots at the +x net in this period."""
    d = 1 if period in (1, 3) or period >= 4 else -1
    return d if is_home else -d


def _distance(xg, rng):
    if xg is None:
        return rng.uniform(30, 55)
    return max(6.0, (8 + 52 * math.exp(-xg / 0.06)) * rng.uniform(0.8, 1.2))


def _shot_spot(direction, xg, rng):
    dist = _distance(xg, rng)
    spread = 70 if xg is None or xg < 0.05 else 50 if xg < 0.1 else 35
    ang = math.radians(rng.triangular(-spread, spread, 0))
    x = direction * (NET_X - dist * math.cos(ang))
    y = max(-HALF_W + 3, min(HALF_W - 3, dist * math.sin(ang)))
    return round(x, 1), round(y, 1)


def _color(c, fallback):
    c = (c or "").strip()
    return c if c.startswith("#") and len(c) in (4, 7) else fallback


def build(conn, gid):
    g = conn.execute("SELECT * FROM games WHERE game_id=?", (gid,)).fetchone()
    if g is None or not g["played"]:
        raise ValueError("That game has not been played.")
    home, away = g["home_team_id"], g["away_team_id"]
    rng = random.Random(f"replay-{gid}-{g['seed']}")
    teams = {t: conn.execute("SELECT abbr, name, primary_color, secondary_color FROM teams WHERE team_id=?",
                             (t,)).fetchone() for t in (home, away)}
    evs = conn.execute("SELECT * FROM game_events WHERE game_id=? ORDER BY period, clock_sec, seq", (gid,)).fetchall()
    names = {}

    def nm(pid):
        if pid is None:
            return None
        if pid not in names:
            names[pid] = player_name(conn, pid)
        return names[pid]

    out, score = [], {home: 0, away: 0}
    so_round = 0
    for e in evs:
        t = e["team_id"]
        is_home = t == home
        typ = e["event_type"]
        per = e["period"]
        if typ in ("so_goal", "so_miss"):
            so_round += 1
            d = 1                                                     # shootouts at one end
            x, y = round(d * (NET_X - rng.uniform(8, 14)), 1), round(rng.uniform(-6, 6), 1)
            if typ == "so_goal":
                score[t] += 0                                         # shootout goals do not count in the score
            out.append(dict(t=None, period="SO", clock=None, type=typ, team="home" if is_home else "away",
                            shooter=nm(e["player_id"]), shooter_id=e["player_id"], goalie=nm(e["opp_player_id"]),
                            x=x, y=y, net=d * NET_X, round=so_round))
            continue
        d = _attack_dir(is_home, per)
        x, y = _shot_spot(d, e["xg"], rng)
        ev = dict(t=(per - 1) * 1200 + e["clock_sec"], period=per, clock=e["clock_sec"], type=typ,
                  team="home" if is_home else "away", x=x, y=y, net=d * NET_X, xg=e["xg"],
                  shooter=nm(e["player_id"]), shooter_id=e["player_id"])
        if typ == "goal":
            score[t] += 1
            det = e["detail"] or ""
            ev["assists"] = [nm(int(a)) for a in det.split(";")[0][2:].split(",") if a] if det.startswith("A:") else []
            ev["empty_net"] = "EN" in det
            ev["goalie"] = nm(e["opp_player_id"])
            ev["score"] = [score[home], score[away]]
        elif typ == "shot":
            ev["goalie"] = nm(e["opp_player_id"])
        elif typ == "block":
            f = rng.uniform(0.3, 0.5)
            ev["bx"], ev["by"] = round(x + (d * NET_X - x) * f, 1), round(y * (1 - f), 1)
            ev["blocker"] = nm(e["opp_player_id"])
        elif typ == "miss":
            ev["mx"] = round(d * (NET_X + rng.uniform(2, 8)), 1)
            ev["my"] = round(rng.choice((-1, 1)) * rng.uniform(4, 14), 1)
        elif typ == "penalty":
            ev["detail"] = e["detail"] or "minor 2:00"
            ev["x"], ev["y"] = round(rng.uniform(-60, 60), 1), round(rng.uniform(-30, 30), 1)
        out.append(ev)
    length = max([e["t"] for e in out if e["t"] is not None] + [3600])
    if g["went_to_ot"] == 1:
        length = max(length, 3600)
    return dict(game_id=gid, date=g["game_date"], length=length, ot=g["went_to_ot"],
                home=dict(abbr=teams[home]["abbr"], name=teams[home]["name"],
                          color=_color(teams[home]["primary_color"], "#2f6fd6"),
                          alt=_color(teams[home]["secondary_color"], "#ffffff")),
                away=dict(abbr=teams[away]["abbr"], name=teams[away]["name"],
                          color=_color(teams[away]["primary_color"], "#c0392b"),
                          alt=_color(teams[away]["secondary_color"], "#ffffff")),
                final=[g["home_goals"], g["away_goals"]], events=out)
