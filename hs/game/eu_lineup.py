"""Your European club in the leagues' results model (v61; docs/EUROPE.md).

The leagues' results model dresses each club's best 12 forwards, 6 defencemen and two goalies (the starter in about
seven games of ten). The club you run is picked on the game's own screens instead, as an NHL club is:

  Lineup    the lines and pairs on the Lineup screen (`lines`), or the lineup lists (`lineups`) when they are on:
            they are rebuilt before each of your games. The results model gives line 1 the most goals and line 4
            the fewest, so who plays where matters. Power-play and penalty-kill units are kept, but the results
            model has no special teams, so they only count through the tactics below.
  Tactics   the twelve settings on the Tactics screen (`tactics`): the goals for and against they are worth to an
            NHL club (hs/game/tactics.py, with your players' fit) scale your goals and the opponent's, relative to the
            default settings, within 15% either way.
  Goalie    the lineup lists' goalie rule: usual (the starter in 70% of games), back_to_back 80%, every_fourth 75%,
            every_game 92%.
"""
from __future__ import annotations

import json

STARTER = {"usual": 0.70, "back_to_back": 0.80, "every_fourth": 0.75, "every_game": 0.92}


def effects(conn, club):
    """(goals-for factor, goals-against factor) of the club's tactics, against the default settings."""
    from . import tactics as TC
    try:
        TC.ensure_table(conn)
        m = TC.multipliers_for(conn, club)
        base = TC.multipliers_for(conn, club, dict(TC.DEFAULTS))
    except Exception:                                     # (a save without the tactics tables)
        return 1.0, 1.0
    gf = (m["att"] * m["qual"] + 0.18 * (m["pp_att"] * m["pp_qual"] - 1)) / (base["att"] * base["qual"] + 0.18 * (base["pp_att"] * base["pp_qual"] - 1))
    ga = (m["allow_att"] * m["allow_qual"] + 0.18 * (m["pk_allow_att"] * m["pk_allow_qual"] - 1)) / \
         (base["allow_att"] * base["allow_qual"] + 0.18 * (base["pk_allow_att"] * base["pk_allow_qual"] - 1))
    clamp = lambda x: max(0.85, min(1.15, x))
    return clamp(gf), clamp(ga)


def starter_share(conn, club):
    from . import lineups as LUP
    try:
        return STARTER.get(LUP.get(conn, club)["goalie_rule"], 0.70)
    except Exception:
        return 0.70


def apply_to(conn, clubs, by, mean_of):
    """Called by the results model for today's clubs: the club you run dresses your lines and plays your tactics."""
    from .europe import club as managed
    from . import lineup as L, lineups as LUP
    me = managed(conn)
    if me is None or me not in clubs:
        return
    try:                                                  # the lineup lists, when on, rebuild the lines first
        st = LUP.get(conn, me)
        if st["enabled"]:
            lu = LUP.build(conn, me)
            L.ensure_table(conn)
            conn.execute("INSERT OR REPLACE INTO lineups (team_id, data, updated) VALUES (?,?,?)",
                         (me, json.dumps(lu), conn.execute('SELECT "current_date" FROM game_state').fetchone()[0]))
    except Exception:
        pass
    cur = L.current(conn, me)
    c = clubs[me]
    if cur:
        rows = {r["player_id"]: r for r in by.get(me, [])}
        ov = lambda p: rows[p]["overall"]
        fwd = [(ov(p), p) for ln in cur["F"] for p in ln if p in rows]
        dmen = [(ov(p), p) for pr in cur["D"] for p in pr if p in rows]
        goalies = [(ov(p), p) for p in cur["G"] if p in rows]
        goalies += sorted(((r["overall"], p) for p, r in rows.items() if r["position"] == "G" and p not in cur["G"]), reverse=True)
        c.fwd, c.dmen, c.goalies = fwd[:12], dmen[:6], goalies[:3]
        mean = mean_of(me)
        vals = [v for v, _ in c.fwd] + [mean - 1.5] * (12 - len(c.fwd)) + [v * 0.8 + mean * 0.2 for v, _ in c.dmen] + [mean - 1.5] * (6 - len(c.dmen))
        c.attack = sum(vals) / len(vals)
        c.ghosts = 18 - len(c.fwd) - len(c.dmen)
    c.t_for, c.t_against = effects(conn, me)
    c.starter = starter_share(conn, me)
