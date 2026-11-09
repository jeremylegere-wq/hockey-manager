"""Commissioner mode: league-level powers (v47; docs/EDITOR.md "Commissioner tools").

All of these need commissioner mode (Settings, or `editor on`), which marks the save as edited for good, and none is
open to a challenge-mode career.
  trade      any two clubs swap players (and picks), with no AI approval; the cap and roster checks still apply
             unless you force it
  takeover   you become the GM of another club at once (your old club gets a new GM)
  fire       an AI club's GM or head coach goes (a new GM is named; the best head coach on the market is hired)
  injure     a player is out for a number of days; heal brings him back now
  rules      the salary cap ceiling and floor, the league minimum, the roster limits, the trade deadline (MM-DD)
Every action is logged in the editor's log.
"""
from __future__ import annotations

import datetime
import json
import random

from . import editor
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

RULE_KEYS = {"cap": ("contracts", "cap_ceiling"), "floor": ("contracts", "cap_floor"), "min_salary": ("contracts", "min_salary"),
             "roster_max": ("roster", "max"), "roster_min": ("roster", "min"), "deadline": ("contracts", "trade_deadline")}


def _need(conn):
    editor._need(conn)


def _team(conn, v):
    from ..schema import top_league_sql
    r = conn.execute(f"SELECT team_id FROM teams WHERE UPPER(abbr)=UPPER(?) AND {top_league_sql()}", (str(v).strip(),)).fetchone()
    if not r:
        raise ValueError(f"No NHL club {v}.")
    return r[0]


def _day(conn):
    return get_state(conn)[0]


# ---------------------------------------------------------------- trade
def trade(conn, a, give_a, b, give_b, picks_a=(), picks_b=(), force=False):
    """Club a gives players give_a (and picks [(year, round, original)]) to club b for give_b / picks_b."""
    _need(conn)
    from . import roster as R
    from . import trades as T
    day = _day(conn)
    for team, pids in ((a, give_a), (b, give_b)):
        for p in pids:
            if conn.execute("SELECT team_id FROM players WHERE player_id=?", (p,)).fetchone()[0] != team:
                raise ValueError(f"{player_name(conn, p)} is not with {team_abbr(conn, team)}.")
    for team, picks in ((a, picks_a), (b, picks_b)):
        for y, rnd, orig in picks:
            if T.pick_owner(conn, y, rnd, orig) != team:
                raise ValueError(f"{team_abbr(conn, team)} do not own {team_abbr(conn, orig)}'s {y} round-{rnd} pick.")
    if not give_a and not give_b and not picks_a and not picks_b:
        raise ValueError("Nothing to trade.")
    if force:
        for pids, frm, to in ((give_a, a, b), (give_b, b, a)):
            for p in pids:
                R.transfer(conn, p, frm, to, day)
    else:
        R.trade(conn, a, list(give_a), b, list(give_b), day)
    T.ensure_tables(conn)
    for picks, to in ((picks_a, b), (picks_b, a)):
        for y, rnd, orig in picks:
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, orig, to, f"commissioner trade {day}"))
    names = lambda ps, pk: ", ".join([player_name(conn, p) for p in ps] + [f"{team_abbr(conn, o)} {y} round {r}" for y, r, o in pk]) or "nothing"
    text = f"{team_abbr(conn, a)} send {names(give_a, picks_a)} to {team_abbr(conn, b)} for {names(give_b, picks_b)}"
    emit(conn, "TRADE_COMPLETED", day, text, team_id=a, other_team_id=b, importance=2, kind="commissioner")
    editor._log(conn, "trade", text + (" (forced)" if force else ""))
    return text


# ---------------------------------------------------------------- takeover / fire
def takeover(conn, team):
    _need(conn)
    me = user_team(conn)
    if me == team:
        raise ValueError("You already run that club.")
    from . import expansion as XP
    day = _day(conn)
    if me is None:                                         # out of work: the commissioner simply hires you
        from . import gm as GMx
        GMx.ensure_tables(conn)
        conn.execute("UPDATE manager SET team_id=? WHERE id=1", (team,))
        conn.execute("UPDATE board SET gm_name='You', confidence=60, warnings=0, vacancy=0 WHERE team_id=?", (team,))
        conn.execute("DELETE FROM pack_info WHERE key='gm_status'")
        conn.execute("INSERT INTO gm_career VALUES (?,?,NULL,NULL)", (team, day))
    else:
        XP._take_over(conn, me, team, day)
    editor._log(conn, "takeover", f"{team_abbr(conn, me) if me else 'out of work'} -> {team_abbr(conn, team)}")
    add_message(conn, day, "New club", f"You are now the general manager of {team_abbr(conn, team)}.", sender="Commissioner")
    return f"You now run {team_abbr(conn, team)}."


def fire(conn, team, who):
    _need(conn)
    if team == user_team(conn):
        raise ValueError("That is your club: use the staff screen for your coaches.")
    day = _day(conn)
    rng = random.Random(f"{get_state(conn)[1]}-commish-{team}-{who}-{day}")
    if who == "gm":
        from . import org
        org.ensure_tables(conn)
        old = conn.execute("SELECT gm_name FROM board WHERE team_id=?", (team,)).fetchone()
        new = f"{rng.choice(org.GM_FIRST)} {rng.choice(org.GM_LAST)}"
        conn.execute("UPDATE board SET gm_name=?, gm_since=?, confidence=60 WHERE team_id=?", (new, org.season_year(conn), team))
        emit(conn, "GM_FIRED", day, f"{team_abbr(conn, team)} fire GM {old[0] if old else ''} and name {new}", team_id=team, importance=2)
        editor._log(conn, "fire", f"{team_abbr(conn, team)} GM {old[0] if old else '?'} -> {new}")
        return f"{team_abbr(conn, team)}: {new} is the new GM."
    if who == "coach":
        from . import staff
        hc = conn.execute("SELECT staff_id, name FROM staff WHERE team_id=? AND role='HC'", (team,)).fetchone()
        if hc:
            staff.dismiss(conn, team, hc[0], day, reason="fire")
        staff.refill_market(conn)
        best = conn.execute("SELECT staff_id, name FROM staff WHERE team_id IS NULL AND role='HC' AND staff_id<>? "
                            "ORDER BY coaching + leadership DESC LIMIT 1", (hc[0] if hc else -1,)).fetchone()
        if not best:
            raise ValueError("No head coach is available.")
        staff.hire(conn, team, best[0], day)
        editor._log(conn, "fire", f"{team_abbr(conn, team)} coach {hc[1] if hc else '-'} -> {best[1]}")
        return f"{team_abbr(conn, team)}: {best[1]} is the new head coach."
    raise ValueError("fire <ABBR> gm|coach")


# ---------------------------------------------------------------- injuries
def injure(conn, pid, days, what="injury (commissioner)"):
    _need(conn)
    days = int(days)
    if not 1 <= days <= 365:
        raise ValueError("Days: 1-365.")
    day = _day(conn)
    back = (datetime.date.fromisoformat(day) + datetime.timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM injuries WHERE player_id=? AND expected_return>?", (pid, day))
    conn.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)", (pid, day, back, what))
    conn.execute("UPDATE players SET status='injured' WHERE player_id=? AND status='active'", (pid,))
    editor._log(conn, "injure", f"{player_name(conn, pid)} out until {back}")
    return f"{player_name(conn, pid)} is out until {back}."


def heal(conn, pid):
    _need(conn)
    day = _day(conn)
    conn.execute("UPDATE injuries SET expected_return=? WHERE player_id=? AND expected_return>?", (day, pid, day))
    conn.execute("UPDATE players SET status='active' WHERE player_id=? AND status IN ('injured','ltir')", (pid,))
    editor._log(conn, "heal", player_name(conn, pid))
    return f"{player_name(conn, pid)} is healthy."


# ---------------------------------------------------------------- rules
def rules(conn):
    from . import contracts as K
    from . import roster as R
    from . import trades as T
    cr = K.crules(conn)
    mn, mx = R.limits(conn)
    return dict(cap=cr["cap_ceiling"], floor=cr["cap_floor"], min_salary=cr["min_salary"], roster_max=mx, roster_min=mn,
                deadline=T.deadline(conn).isoformat())


def set_rule(conn, key, value):
    _need(conn)
    if key not in RULE_KEYS:
        raise ValueError("Rules: " + ", ".join(RULE_KEYS) + ".")
    sect, field = RULE_KEYS[key]
    if key == "deadline":
        v = str(value).strip()
        try:
            m, d = (int(x) for x in v[-5:].split("-"))
            datetime.date(2001, m, d)
        except (ValueError, TypeError):
            raise ValueError("The deadline is a month and day: MM-DD (e.g. 03-06).")
        if not (m <= 4 or m >= 10):
            raise ValueError("The deadline falls in the season (October to April).")
        val = f"{m:02d}-{d:02d}"
    elif key in ("roster_max", "roster_min"):
        val = editor._int(value, 15, 30, key)
    else:
        val = editor._money(value)
        if not 100_000 <= val <= 500_000_000:
            raise ValueError("That amount is out of range.")
    r = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    rules_ = json.loads(r[0]) if r else {}
    rules_.setdefault(sect, {})[field] = val
    cur = rules(conn)
    if key == "floor" and val > (rules_.get("contracts", {}).get("cap_ceiling") or cur["cap"]):
        raise ValueError("The floor cannot be above the cap.")
    if key == "cap" and val < (rules_.get("contracts", {}).get("cap_floor") or cur["floor"]):
        raise ValueError("The cap cannot be below the floor.")
    if key == "roster_min" and val > (rules_.get("roster", {}).get("max") or cur["roster_max"]):
        raise ValueError("The minimum cannot be above the maximum.")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('rules', ?)", (json.dumps(rules_),))
    editor._log(conn, "rule", f"{key} = {val}")
    emit(conn, "MEDIA_STORY", _day(conn), f"League rule change: {key.replace('_', ' ')} is now {val}", importance=2,
         headline="League rule change", body=f"The league has changed a rule: {key.replace('_', ' ')} is now {val}.", tag="rules",
         kind="commissioner")
    return f"{key} = {val}"


def _roster(conn, team):
    from . import trades as T
    rows = conn.execute("SELECT player_id, first_name||' '||last_name, position, status FROM players WHERE team_id=? AND status<>'retired' "
                        "ORDER BY status<>'active', position, last_name", (team,)).fetchall()
    from .draft import draft_year
    dy = draft_year(conn)
    picks = []
    T.ensure_tables(conn)
    from ..schema import top_league_sql
    for y in (dy, dy + 1):
        for rnd in range(1, 8):
            for (orig,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}"):
                if T.pick_owner(conn, y, rnd, orig) == team:
                    picks.append(dict(code=f"{y}-{rnd}-{team_abbr(conn, orig)}", label=f"{y} round {rnd}" + ("" if orig == team else f" ({team_abbr(conn, orig)})")))
    return dict(players=[dict(player_id=r[0], name=r[1], pos=r[2], status=r[3]) for r in rows], picks=picks)


def view(conn, a=None, b=None):
    from ..schema import top_league_sql
    from . import challenge
    sides = {}
    for k, t in (("a", a), ("b", b)):
        if t:
            sides[k] = _roster(conn, int(t))
    return dict(sides=sides, enabled=editor.enabled(conn), edited=editor.edited(conn), challenge_mode=challenge.mode_on(conn), rules=rules(conn),
                me=user_team(conn),
                clubs=[dict(team_id=r[0], abbr=r[1], name=f"{r[2]} {r[3] or ''}".strip()) for r in conn.execute(
                    f"SELECT team_id, abbr, name, nickname FROM teams WHERE {top_league_sql()} ORDER BY abbr")],
                log=[dict(r) for r in conn.execute("SELECT * FROM editor_log ORDER BY rowid DESC LIMIT 30")]
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='editor_log'").fetchone() else [])
