"""Challenge mode and challenges (v47; docs/CHALLENGES.md).

Challenge mode (a career setting; once on it stays on)
  * no commissioner mode and no editor
  * during the regular season and the playoffs you sim a day, a week or to the next game at most (a week at a
    time; `sim season` and long `sim to` jumps are for the off-season)
  * you can be fired (the "cannot be fired" option is switched off)
  * the career is marked: GM leaders, achievements and the Challenges screen show it
Challenges (goals with a deadline, taken on at the start of a career, before your club's first game; one at a time):
  turnaround   make the playoffs within your first two seasons            (suggested: one of the five weakest clubs)
  rebuild      win a playoff round within four seasons                    (suggested: the weakest club)
  win_now      win the championship within three seasons                  (suggested: the strongest clubs)
  cap_hell     be cap-compliant on opening night of your first season and make the playoffs within two
                                                                           (suggested: the club with the least cap room)
  dynasty      win three championships within eight seasons                (any club)
  expansion    an expansion club is announced; you run your club this season, take over the new one when it ends,
               and must make the playoffs within its first three seasons
Each season's end checks the goal; the challenge is won when it is met, lost when the deadline passes or you lose
your job (or leave the club, other than for the expansion club). The result is permanent: an inbox note, a news
story and a line on the Challenges screen.
"""
from __future__ import annotations

import json

from .events import emit, team_abbr
from .state import add_message, get_state, user_team

MAX_SIM_DAYS = 7
CHALLENGES = {
    "turnaround": dict(name="Turnaround", goal="Make the playoffs within your first two seasons.", seasons=2, suggest="weak5"),
    "rebuild": dict(name="Rebuild", goal="Win a playoff round within four seasons.", seasons=4, suggest="weakest"),
    "win_now": dict(name="Win now", goal="Win the championship within three seasons.", seasons=3, suggest="strong"),
    "cap_hell": dict(name="Cap hell", goal="Be cap-compliant on opening night of your first season and make the playoffs within two.",
                     seasons=2, suggest="cap"),
    "dynasty": dict(name="Dynasty", goal="Win three championships within eight seasons.", seasons=8, suggest="any"),
    "expansion": dict(name="Expansion", goal="Run your club this season, take over a new expansion club when it ends, and make the "
                                             "playoffs within its first three seasons.", seasons=4, suggest="any"),
}


def _get(conn, key, default=None):
    r = conn.execute("SELECT value FROM pack_info WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def _set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (key, value))


def _season(conn):
    from .contracts import season_year
    return season_year(conn)


def _state(conn):
    return _get(conn, "season_state", "regular_season")


# ---------------------------------------------------------------- challenge mode
def mode_on(conn):
    return _get(conn, "challenge_mode") == "1"


def set_mode(conn, on=True):
    """Turn challenge mode on (for good). Not for a save that has used commissioner mode."""
    if not on:
        if mode_on(conn):
            raise ValueError("Challenge mode stays on for the rest of the career.")
        return False
    from . import editor
    if editor.edited(conn):
        raise ValueError("This save has used commissioner mode, so it cannot become a challenge-mode career.")
    _set(conn, "challenge_mode", "1")
    try:
        from . import gm
        x = gm._extra(conn)
        x["unfireable"] = False
        gm._save_extra(conn, x)
    except Exception:
        pass
    return True


def check_sim(conn, kind, days=None):
    """Raise if challenge mode forbids this sim: kind is day|week|next|season|to (days ahead for `to`)."""
    if not mode_on(conn) or _state(conn) not in ("regular_season", "playoffs"):
        return
    if kind == "season" or (kind == "to" and days is not None and days > MAX_SIM_DAYS):
        raise ValueError(f"Challenge mode: during the season you sim a day, a week or to the next game (at most {MAX_SIM_DAYS} days "
                         "at a time). Long sims are for the off-season.")


# ---------------------------------------------------------------- challenges
def current(conn):
    v = _get(conn, "challenge")
    return json.loads(v) if v else None


def history(conn):
    v = _get(conn, "challenge_history")
    return json.loads(v) if v else []


def _save(conn, c):
    _set(conn, "challenge", json.dumps(c) if c else "")


def can_start(conn):
    """A challenge starts before your club has played a game in this career."""
    me = user_team(conn)
    if me is None:
        return False, "You need a club."
    if current(conn) and current(conn).get("status") == "on":
        return False, "You are already on a challenge."
    if _state(conn) != "regular_season":
        return False, "A challenge starts at the beginning of a career (before your club's first game)."
    sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    played = conn.execute("SELECT COUNT(*) FROM games WHERE season_id=? AND played=1 AND game_type='RS' AND (home_team_id=? OR "
                          "away_team_id=?)", (sid, me, me)).fetchone()[0]
    if played == 0 and conn.execute("SELECT COUNT(*) FROM gm_career").fetchone()[0] > 1 if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='gm_career'").fetchone() else False:
        return False, "A challenge starts at the beginning of a career."
    if played:
        return False, "A challenge starts at the beginning of a career, before your club's first game."
    return True, ""


def suggestions(conn):
    """{challenge: [abbr]} clubs that suit each challenge."""
    from ..schema import top_league_sql
    from . import roster as R
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    st = {}
    for t in teams:
        vals = sorted((R.player_value(conn, r["player_id"]) for r in R.roster(conn, t)), reverse=True)[:18]
        st[t] = sum(vals) / len(vals) if vals else 0.0
    order = sorted(teams, key=lambda t: st[t])
    from . import contracts as K
    room = {t: K.cap_room(conn, t, _season(conn)) for t in teams}
    ab = lambda ts: [team_abbr(conn, t) for t in ts]
    return dict(weak5=ab(order[:5]), weakest=ab(order[:1]), strong=ab(order[-3:][::-1]),
                cap=ab(sorted(teams, key=lambda t: room.get(t, 0))[:3]), any=[])


def start(conn, key, day=None):
    if key not in CHALLENGES:
        raise ValueError("Challenges: " + ", ".join(CHALLENGES) + ".")
    ok, why = can_start(conn)
    if not ok:
        raise ValueError(why)
    day = day or get_state(conn)[0]
    me = user_team(conn)
    y = _season(conn)
    c = dict(key=key, name=CHALLENGES[key]["name"], goal=CHALLENGES[key]["goal"], team=me, start=y,
             deadline=y + CHALLENGES[key]["seasons"] - 1, status="on", started=day, progress=[])
    if key == "expansion":
        from . import expansion as XP
        taken = XP._top_abbrs(conn) | {r[0] for r in conn.execute("SELECT abbr FROM expansion")} if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='expansion'").fetchone() else XP._top_abbrs(conn)
        cand = next((x for x in XP.CANDIDATES if x[2] not in taken), None)
        if cand is None:
            raise ValueError("No expansion market is free.")
        XP.ensure_tables(conn)
        if XP.pending(conn):
            raise ValueError("An expansion club is already on its way.")
        XP.announce(conn, day, cand[0], cand[1], cand[2], cand[4], market=cand[3], capacity=cand[5], by_user=True, user_gm=True)
        c["deadline"] = y + 3                               # the new club's first three seasons
        c["expansion_abbr"] = cand[2]
    if key == "cap_hell":
        c["cap_check"] = "pending"
    _save(conn, c)
    add_message(conn, day, f"Challenge: {c['name']}", f"{c['goal']}\nDeadline: the end of the {c['deadline']}-{(c['deadline'] + 1) % 100:02d} "
                "season. Losing your job ends the challenge. Progress is on Manager > Challenges.", sender="Challenge")
    emit(conn, "ACHIEVEMENT", day, f"{team_abbr(conn, me)}'s GM takes on the {c['name']} challenge", team_id=me, importance=1,
         kind="challenge_start", challenge=key)
    return c


def _finish(conn, c, won, day, why):
    c["status"] = "won" if won else "lost"
    c["result"] = why
    c["ended"] = day
    _save(conn, c)
    h = history(conn)
    h.append({k: c[k] for k in ("key", "name", "goal", "start", "deadline", "status", "result", "ended")} | dict(mode=mode_on(conn)))
    _set(conn, "challenge_history", json.dumps(h))
    add_message(conn, day, f"Challenge {'complete' if won else 'failed'}: {c['name']}", why, sender="Challenge")
    emit(conn, "ACHIEVEMENT", day, f"Challenge {'complete' if won else 'failed'}: {c['name']} ({why})", team_id=c.get("team"),
         importance=3 if won else 1, kind="challenge_end", challenge=c["key"], won=won)


def opening_night(conn, day):
    """Cap hell: cap-compliant when the season opens (called when the regular season is scheduled)."""
    c = current(conn)
    if not c or c.get("status") != "on" or c.get("key") != "cap_hell" or c.get("cap_check") != "pending":
        return
    from . import contracts as K
    hit = K.payroll(conn, c["team"], _season(conn))
    ok = hit <= K.crules(conn)["cap_ceiling"]
    c["cap_check"] = "met" if ok else "failed"
    _save(conn, c)
    if not ok:
        _finish(conn, c, False, day, f"Over the cap on opening night (${hit / 1e6:.1f}M against ${K.crules(conn)['cap_ceiling'] / 1e6:.1f}M).")


def season_end(conn, day):
    """After the playoffs: record the season and check the goal."""
    c = current(conn)
    if not c or c.get("status") != "on":
        return []
    y = _season(conn)
    me = user_team(conn)
    if c["key"] == "expansion" and me != c["team"]:
        new = conn.execute("SELECT team_id FROM expansion WHERE abbr=? AND user_gm=1", (c.get("expansion_abbr"),)).fetchone()
        if new and new[0] == me:
            c["team"] = me                                     # took over the new club
            c["expansion_team"] = me
    if me is None or me != c["team"]:
        _finish(conn, c, False, day, "You left the club (or lost your job) before the challenge was done.")
        return [f"Challenge failed: {c['name']}."]
    r = conn.execute("SELECT playoff_round, pts, w, l, otl FROM team_seasons WHERE season_start_year=? AND team_id=?", (y, me)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_seasons'").fetchone() else None
    rnd = (r[0] or 0) if r else 0
    c.setdefault("progress", []).append(dict(season=y, team=team_abbr(conn, me), round=rnd, pts=r[1] if r else None))
    _save(conn, c)
    k = c["key"]
    prog = c["progress"]
    if k == "expansion":
        prog = [p for p in prog if c.get("expansion_team") and p["season"] > c["start"]]
    won = {"turnaround": any(p["round"] >= 1 for p in prog),
           "rebuild": any(p["round"] >= 2 for p in prog),
           "win_now": any(p["round"] >= 5 for p in prog),
           "cap_hell": c.get("cap_check") == "met" and any(p["round"] >= 1 for p in prog),
           "dynasty": sum(1 for p in prog if p["round"] >= 5) >= 3,
           "expansion": any(p["round"] >= 1 for p in prog)}[k]
    if won:
        _finish(conn, c, True, day, {"turnaround": "Into the playoffs.", "rebuild": "A playoff round won.", "win_now": "Champions.",
                                     "cap_hell": "Cap-compliant and into the playoffs.", "dynasty": "Three championships.",
                                     "expansion": "The expansion club made the playoffs."}[k] + f" ({y}-{(y + 1) % 100:02d})")
        return [f"Challenge complete: {c['name']}."]
    if y >= c["deadline"]:
        _finish(conn, c, False, day, f"The deadline ({c['deadline']}-{(c['deadline'] + 1) % 100:02d}) has passed.")
        return [f"Challenge failed: {c['name']}."]
    return []


def abandon(conn, day=None):
    c = current(conn)
    if not c or c.get("status") != "on":
        raise ValueError("You are not on a challenge.")
    _finish(conn, c, False, day or get_state(conn)[0], "Abandoned.")


def view(conn):
    ok, why = can_start(conn)
    try:
        sugg = suggestions(conn) if ok else {}
    except Exception:
        sugg = {}
    from . import editor
    return dict(mode=mode_on(conn), edited=editor.edited(conn), current=current(conn), history=history(conn), can_start=ok, why=why,
                challenges=[dict(key=k, name=v["name"], goal=v["goal"], seasons=v["seasons"], suggest=sugg.get(v["suggest"], []))
                            for k, v in CHALLENGES.items()], max_sim_days=MAX_SIM_DAYS)
