"""The leadership group (docs/CAPTAINCY.md): naming a captain and alternates is a decision the room, the owner and
the media all react to.

preview() says what will happen before you commit; apply() does it. What moves:
  * The room's choice: every player ranks the leaders by leadership x2 + professionalism + experience + standing
    (hs.game.people.choose_leaders' score). Naming the room's own top three costs nothing; every pick from outside it
    costs cohesion (3 for the captain, 1.5 for an alternate) and the veteran passed over loses 3 trust in you.
  * A new captain: +6 morale, +5 trust; his leadership sets the room's leadership strength.
  * Losing the C: trust -(6 + 1.2 per point of ego over 10), role -4, morale -5; an ego-driven player (15+) with
    little loyalty (8 or less) may ask for a trade (chance 15% + 4% per ego point over 15). Losing an A: half that.
  * Mid-season changes unsettle the room: -2 cohesion more than in the preseason or summer.
  * The owner: +1.5 board confidence for a captain 24 or younger if he prefers youth (7+); -1.5 for stripping a
    franchise veteran (value 60+, 28+) if he is involved (6+); +0.5 for the room's own choice.
Every change makes news (a headline, posts from the insider and the fans), lands in your inbox (the head coach's view
and any reaction), and puts a press conference in the press room (hs.game.press).
"""
from __future__ import annotations

import datetime
import json
import random

from . import contracts as K
from .events import emit, player_name, team_abbr
from .people import traits
from .roster import player_value
from .state import add_message, get_state


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS leadership_history (team_id INTEGER, player_id INTEGER, role TEXT, "
                 "start_date TEXT, end_date TEXT, season_start_year INTEGER)")


def captain_history(conn, t):
    """v38 (#19): the club's captains in order, with tenure: [{player_id, start, end, days}]. The captain the save began
    with counts first even when no history row was written for him. pack_info 'captains_before' ({ABBR: n}) carries the
    club's real count from before the save, so the numbering can match the club's own history."""
    ensure_tables(conn)
    day = get_state(conn)[0]
    rows = [dict(player_id=r[0], start=r[1], end=r[2]) for r in conn.execute(
        "SELECT player_id, start_date, end_date FROM leadership_history WHERE team_id=? AND role='C' ORDER BY start_date, rowid", (t,))]
    first = conn.execute("SELECT player_id, since FROM leadership WHERE team_id=? AND role='C'", (t,)).fetchone()
    if first and not any(r["player_id"] == first[0] for r in rows) and not rows:
        rows.insert(0, dict(player_id=first[0], start=first[1], end=None))
    for r in rows:
        a = datetime.date.fromisoformat(r["start"]) if r["start"] else None
        b = datetime.date.fromisoformat(r["end"] or day)
        r["days"] = (b - a).days if a else None
    return rows


def captain_number(conn, t, pid):
    """(nth captain of the club, the longest-serving captain on record or None)."""
    import json
    hist = captain_history(conn, t)
    order = []
    for r in hist:
        if r["player_id"] not in order:
            order.append(r["player_id"])
    if pid not in order:
        order.append(pid)
    base = 0
    r = conn.execute("SELECT value FROM pack_info WHERE key='captains_before'").fetchone()
    if r:
        try:
            base = int(json.loads(r[0]).get(team_abbr(conn, t), 0))
        except (ValueError, TypeError, AttributeError):
            base = 0
    longest = max((h for h in hist if h["days"] is not None), key=lambda h: h["days"], default=None)
    return base + order.index(pid) + 1, longest


def _age(conn, pid, day):
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    d = datetime.date.fromisoformat(day)
    bb = datetime.date.fromisoformat(b)
    return d.year - bb.year - ((d.month, d.day) < (bb.month, bb.day))


def room_ranking(conn, t, day):
    """[(pid, score)] best first: who the dressing room would choose."""
    rows = conn.execute("SELECT p.player_id, p.birth_date FROM players p WHERE p.team_id=? AND p.status IN "
                        "('active','injured') AND p.position<>'G'", (t,)).fetchall()
    on = datetime.date.fromisoformat(day)
    out = []
    for r in rows:
        tr = traits(conn, r["player_id"])
        exp = min(10, max(0, (on.year - int(r["birth_date"][:4])) - 22))
        out.append((r["player_id"], tr["leadership"] * 2 + tr["professionalism"] + exp + player_value(conn, r["player_id"]) / 10))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def current(conn, t):
    return {r[0]: r[1] for r in conn.execute("SELECT player_id, role FROM leadership WHERE team_id=?", (t,))}


def _effects(conn, t, captain, alts, day):
    """What would change, as data (shared by preview and apply)."""
    now = current(conn, t)
    new = {captain: "C", **{a: "A" for a in alts}}
    rank = room_ranking(conn, t, day)
    top3 = [p for p, _ in rank[:3]]
    state = K.season_state(conn)
    mid = state == "regular_season" and conn.execute("SELECT COUNT(*) FROM games WHERE played=1 AND game_type='RS' AND "
                                                     "(home_team_id=? OR away_team_id=?)", (t, t)).fetchone()[0] > 0
    people, cohesion, board, notes = [], 0.0, 0.0, []
    for pid, role in now.items():
        if new.get(pid) == role:
            continue
        tr = traits(conn, pid)
        lost = role == "C" and new.get(pid) != "C"
        scale = (0.75 if new.get(pid) == "A" else 1.0) if lost else 0.5
        if role == "A" and new.get(pid) == "C":
            continue
        hit = (6 + max(0, tr["ego"] - 10) * 1.2) * scale
        p_req = 0.15 + 0.04 * (tr["ego"] - 15) if lost and tr["ego"] >= 15 and tr["loyalty"] <= 8 else 0.0
        people.append(dict(player_id=pid, name=player_name(conn, pid),
                           change=("gives up the C (stays an alternate)" if lost and new.get(pid) == "A" else
                                   f"loses the {'C' if role == 'C' else 'A'}"),
                           trust=-round(hit, 1), role=-round(4 * scale, 1), morale=-round(5 * scale, 1),
                           trade_request_chance=round(min(0.5, p_req), 2),
                           mood="furious" if hit >= 10 else "hurt" if hit >= 6 else "disappointed"))
        if lost:
            v, age = player_value(conn, pid), _age(conn, pid, day)
            o = _owner(conn, t)
            if o and v >= 60 and age >= 28 and (o["involvement"] or 0) >= 6:
                board -= 1.5
                notes.append(f"the owner is uneasy about stripping {player_name(conn, pid)}")
    for pid, role in new.items():
        if now.get(pid) == role or (now.get(pid) == "C" and role == "A"):
            continue
        people.append(dict(player_id=pid, name=player_name(conn, pid), change="named captain" if role == "C" else "named alternate",
                           trust=5 if role == "C" else 2.5, role=3 if role == "C" else 1.5, morale=6 if role == "C" else 3,
                           trade_request_chance=0, mood="proud"))
        if pid not in top3:
            cohesion -= 3 if role == "C" else 1.5
            notes.append(f"the room expected someone else{' as captain' if role == 'C' else ''} than {player_name(conn, pid)}")
    passed = [p for p in top3 if p not in new and now.get(p) is None]
    for p in passed:
        if any(x not in top3 for x in new):
            people.append(dict(player_id=p, name=player_name(conn, p), change="passed over", trust=-3, role=0, morale=-2,
                               trade_request_chance=0, mood="overlooked"))
    if mid and now and set(now.items()) != set(new.items()):
        cohesion -= 2
        notes.append("a change in the middle of the season unsettles the room")
    o = _owner(conn, t)
    if o and new and _age(conn, captain, day) <= 24 and (o["youth_pref"] or 0) >= 7 and now.get(captain) != "C":
        board += 1.5
        notes.append("the owner loves handing the C to a young player")
    if captain in top3[:1] and now.get(captain) != "C":
        board += 0.5
        notes.append("the room's own choice")
    tr = traits(conn, captain)
    strength = round(tr["leadership"] * 0.6 + sum(traits(conn, a)["leadership"] for a in alts) * 0.2, 1)
    return dict(new=new, now=now, people=people, cohesion=round(cohesion, 1), board=round(board, 1), notes=notes,
                room_choice=[dict(player_id=p, name=player_name(conn, p), score=round(s, 1)) for p, s in rank[:6]],
                mid_season=mid, leadership_strength=strength)


def _owner(conn, t):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone():
        return None
    return conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone()


def _check(conn, t, captain, alts):
    alts = [a for a in alts if a and a != captain]
    if len(set(alts)) != len(alts):
        raise ValueError("Pick two different alternates.")
    if len(alts) > 2:
        raise ValueError("At most two alternate captains.")
    for pid in [captain, *alts]:
        r = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
        if r is None or r[0] != t or r[1] not in ("active", "injured"):
            raise ValueError("The leadership group must come from your NHL roster.")
        if conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0] == "G":
            raise ValueError(f"{player_name(conn, pid)} is a goalie: goalies cannot wear the C or the A (a league rule since 1948).")
    return alts


def preview(conn, t, captain, alts):
    alts = _check(conn, t, captain, alts)
    return _effects(conn, t, captain, alts, get_state(conn)[0])


def apply(conn, t, captain, alts, day=None):
    day = day or get_state(conn)[0]
    alts = _check(conn, t, captain, alts)
    ensure_tables(conn)
    fx = _effects(conn, t, captain, alts, day)
    if fx["now"] == fx["new"]:
        raise ValueError("That is the leadership group you already have.")
    rng = random.Random(f"captaincy-{t}-{day}-{captain}")
    year = K.season_year(conn)
    for pid, role in fx["now"].items():
        if fx["new"].get(pid) != role:
            conn.execute("UPDATE leadership_history SET end_date=? WHERE team_id=? AND player_id=? AND role=? AND end_date IS "
                         "NULL", (day, t, pid, role))
    conn.execute("DELETE FROM leadership WHERE team_id=?", (t,))
    for pid, role in fx["new"].items():
        conn.execute("INSERT INTO leadership VALUES (?,?,?,?)", (t, pid, role, day))
        if fx["now"].get(pid) != role:
            conn.execute("INSERT INTO leadership_history VALUES (?,?,?,?,?,?)", (t, pid, role, day, None, year))
    requests = []
    for x in fx["people"]:
        conn.execute("UPDATE morale SET trust_mgmt=MIN(100, MAX(0, trust_mgmt+?)), role=MIN(100, MAX(0, role+?)), "
                     "morale=MIN(100, MAX(0, morale+?)) WHERE player_id=?", (x["trust"], x["role"], x["morale"], x["player_id"]))
        if x["trade_request_chance"] and rng.random() < x["trade_request_chance"]:
            conn.execute("UPDATE morale SET trade_request=1 WHERE player_id=?", (x["player_id"],))
            emit(conn, "TRADE_REQUEST", day, f"{x['name']} asks {team_abbr(conn, t)} for a trade after losing the captaincy",
                 team_id=t, player_id=x["player_id"], importance=3)
            requests.append(x["name"])
    conn.execute("UPDATE team_room SET cohesion=MIN(100, MAX(0, cohesion+?)), leadership_strength=? WHERE team_id=?",
                 (fx["cohesion"], fx["leadership_strength"], t))
    if fx["board"] and conn.execute("SELECT 1 FROM board WHERE team_id=?", (t,)).fetchone():
        from . import org
        org._apply(conn, t, fx["board"], "captaincy", day, fx["notes"] or ["leadership group"])
    cap, ab = player_name(conn, captain), team_abbr(conn, t)
    club = conn.execute("SELECT name, nickname FROM teams WHERE team_id=?", (t,)).fetchone()
    club = f"{club[0]} {club[1] or ''}".strip()
    old_c = next((p for p, r in fx["now"].items() if r == "C"), None)
    alt_names = [player_name(conn, a) for a in alts]
    if fx["now"].get(captain) != "C":
        headline = rng.choice([f"{club} hand the C to {cap}", f"{cap} named captain of the {club}", f"It's {cap}'s team now"])
        body = (f"The {club} have named {cap} captain" + (f", replacing {player_name(conn, old_c)}" if old_c else "") +
                (f". {' and '.join(alt_names)} will wear the A." if alt_names else ".") +
                (" " + fx["notes"][0][0].upper() + fx["notes"][0][1:] + "." if fx["notes"] else ""))
        nth, longest = captain_number(conn, t, captain)       # v38 (#19): the club's captaincy history
        from .welcome import _ordinal
        body += f" {cap} is the {_ordinal(nth)} captain of the {club}" + ("" if conn.execute(
            "SELECT 1 FROM pack_info WHERE key='captains_before'").fetchone() else " in this era") + "."
        if longest and longest["player_id"] != captain and longest["days"] and longest["days"] >= 365:
            body += f" The longest-serving captain on record is {player_name(conn, longest['player_id'])} ({longest['days'] // 365} seasons)."
    else:
        headline = f"{club} reshape their leadership group"
        body = f"{cap} remains captain; {' and '.join(alt_names) or 'no one'} will wear the A."
    social = [dict(account="@InsiderOnIce", text=f"{ab}: {cap} is the new captain" + (f", taking over from {player_name(conn, old_c)}." if old_c and old_c != captain else "."))]
    fan = f"@{ab}Faithful"
    if fx["cohesion"] < -2:
        social.append(dict(account=fan, text=rng.choice([f"Not sure the room wanted {cap}. Hope this works.", "Bold call. Very bold.",
                                                         "Strange time to change the captain."])))
    else:
        social.append(dict(account=fan, text=rng.choice([f"{cap} with the C. Love it.", "Right choice. Long overdue.",
                                                         f"Captain {cap}. Let's go."])))
    if old_c and old_c != captain:
        social.append(dict(account="@HockeyTalkPod", text=rng.choice([f"How does {player_name(conn, old_c)} feel about this? Watch that space.",
                                                                       f"Losing the C is never easy. {player_name(conn, old_c)} will be asked about it all week."])))
    emit(conn, "CAPTAIN_CHANGED", day, f"{ab} name {cap} captain" if fx["now"].get(captain) != "C" else f"{ab} change their alternates",
         team_id=t, player_id=captain, importance=3 if fx["now"].get(captain) != "C" else 2, previous=old_c, alternates=alts,
         headline=headline, body=body, social=social)
    hc = conn.execute("SELECT name FROM staff WHERE team_id=? AND role='HC'", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone() else None
    lines = [f"{x['name']} {x['change']}: {x['mood']}." for x in fx["people"]]
    room = ("The room has taken it well." if fx["cohesion"] >= 0 else
            "There is some grumbling in the room." if fx["cohesion"] > -4 else "The room is unsettled.")
    add_message(conn, day, "Leadership group", f"{(hc[0] + ', head coach') if hc else 'Your head coach'}: {room} " + " ".join(lines) +
                (f" {', '.join(requests)} asked for a trade." if requests else ""))
    try:
        from . import press
        press.schedule(conn, "captaincy", day, dict(captain=captain, previous=old_c, alternates=alts))
    except ImportError:
        pass
    return fx
