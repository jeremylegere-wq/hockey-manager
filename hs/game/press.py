"""The press room (docs/PRESS.md): media availability as a decision, with consequences that travel.

You speak for the club (you are the GM). Reporters ask; you choose an answer from a set written for the situation.
Every answer has an archetype, and the archetype has a base effect on three things, which the context then scales:

  archetype                 room morale   board   fans      also
  back the group                +5          +2      +2
  take responsibility           +8          +5      +4
  cliche                        +1          +1       0
  deflect                       -2          -3      -2
  call out a player            -15         -5      +8       the player: trust and morale down, by his ego
  blame the officials           +5         -10     +15      a league fine is possible
  credit yourself               -5          +5      +5
  question the coach           -10         -12     +10      the coach's standing with the players drops
  demand accountability         +3          -5      +8
  no comment                    -1          -2      -3
  speak from the heart          +6          +3      +8
  issue an ultimatum           -12         -15     +12      trade talk, players worry about their futures

  context: x (1 + pressure/200) where pressure is 40 + 15 for a losing streak of 3+, + 15 for a rivalry (same
  division), + the hot seat (board confidence under 45: +20); x1.2 after three or more losses in a row.
Effects land on: every player's morale (the room number x 0.3) and the room's cohesion (x 0.25); board confidence
(x 0.35, through the boardroom); and the club's media state (fan sentiment, media sentiment, controversy, 0-100).
A named player also feels it personally (call out: trust -(10 + ego/2), morale -8; praise: trust +4, morale +3).

Stories follow answers (the story queue): a player you called out may confront you the next day (inbox), the
dressing room may leak to the insider two days later (a headline and posts), a GM who blames the officials may be
fined, an ultimatum starts trade talk. Reporters remember: a later press conference can ask about something you said.

When press conferences happen: after your games when there is a story (a blowout, a losing or winning streak, a
rivalry, a big comeback or collapse) and otherwise one game in six; a weekly availability; media day before the
season; trade deadline day; the end of your season; after you make a trade; when you name a captain; when a player
asks for a trade. Captaincy, trade requests, the deadline and the end of the season are "major": a long sim stops
for them. Skipped press conferences expire (3 days; major ones 5) and count as "no comment" with the media and
the fans (no effect on the room or the board).
"""
from __future__ import annotations

import datetime
import json
import random

from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

ARCH = {  # morale, board, fans, media sentiment, controversy
    "back_group": (5, 2, 2, 2, 0), "accountable": (8, 5, 4, 4, 0), "cliche": (1, 1, 0, -1, 0), "deflect": (-2, -3, -2, -3, 2),
    "call_out": (-15, -5, 8, 6, 18), "refs": (5, -10, 15, 4, 14), "self_credit": (-5, 5, 5, -2, 4),
    "coach": (-10, -12, 10, 8, 20), "demand": (3, -5, 8, 4, 6), "no_comment": (-1, -2, -3, -6, 2),
    "heart": (6, 3, 8, 6, 2), "ultimatum": (-12, -15, 12, 10, 24), "praise": (6, 2, 3, 2, 0),
}
LABEL = {"back_group": "Back the group", "accountable": "Take responsibility", "cliche": "Stay on message",
         "deflect": "Deflect", "call_out": "Call him out", "refs": "Blame the officials", "self_credit": "Take the credit",
         "coach": "Question the coach", "demand": "Demand more", "no_comment": "No comment", "heart": "Speak from the heart",
         "ultimatum": "Ultimatum", "praise": "Praise him"}
MAJOR = {"captaincy", "trade_request", "deadline", "season_end", "media_day", "introduction"}
OUTLETS = [("The Athletic", "beat reporter"), ("TSN", "insider"), ("Sportsnet", "reporter"), ("the local paper", "columnist"),
           ("a radio host", "host"), ("ESPN", "national writer")]
REPORTERS = ["Dana Morrow", "Pierre-Luc Gagnon", "Mike Kessel", "Sarah Lindqvist", "Ray Bouchard", "Jen Okafor", "Tom Haley",
             "Anika Strand", "Chris Malone", "Elise Fortin"]


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS press_events (press_id INTEGER PRIMARY KEY, team_id INTEGER, kind TEXT, "
                 "created TEXT, expires TEXT, status TEXT, context TEXT, questions TEXT, answers TEXT, outcome TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS media_state (team_id INTEGER PRIMARY KEY, fan_sentiment REAL, media_sentiment "
                 "REAL, controversy REAL, updated TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS story_queue (story_id INTEGER PRIMARY KEY, team_id INTEGER, due TEXT, kind TEXT, "
                 "player_id INTEGER, payload TEXT, status TEXT)")


def media_state(conn, t):
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM media_state WHERE team_id=?", (t,)).fetchone()
    if r is None:
        conn.execute("INSERT INTO media_state VALUES (?,?,?,?,?)", (t, 55.0, 55.0, 10.0, get_state(conn)[0]))
        return dict(team_id=t, fan_sentiment=55.0, media_sentiment=55.0, controversy=10.0)
    return dict(r)


def _days(day, n):
    return (datetime.date.fromisoformat(day) + datetime.timedelta(days=n)).isoformat()


def _rng(*k):
    return random.Random("-".join(map(str, k)))


def _club(conn, t):
    r = conn.execute("SELECT name, nickname FROM teams WHERE team_id=?", (t,)).fetchone()
    return f"{r[0]} {r[1] or ''}".strip()


def _roster(conn, t):
    return [r[0] for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')", (t,))]


def _form(conn, t, n=10):
    rows = conn.execute("SELECT home_team_id, home_goals, away_goals, went_to_ot FROM games WHERE played=1 AND game_type='RS' AND "
                        "(home_team_id=? OR away_team_id=?) ORDER BY game_date DESC, game_id DESC LIMIT ?", (t, t, n)).fetchall()
    res = []
    for h, hg, ag, ot in rows:
        gf, ga = (hg, ag) if h == t else (ag, hg)
        res.append("W" if gf > ga else "O" if ot else "L")
    streak_kind = res[0] if res else None
    streak = 0
    for x in res:
        if x == streak_kind or (streak_kind in ("L", "O") and x in ("L", "O")):
            streak += 1
        else:
            break
    return res, streak_kind, streak


def _pressure(conn, t, ctx):
    p = 40
    res, kind, n = _form(conn, t)
    if kind in ("L", "O") and n >= 3:
        p += 15
    if ctx.get("rivalry"):
        p += 15
    b = conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone() else None
    if b and b[0] < 45:
        p += 20
    return min(100, p), (kind in ("L", "O") and n >= 3)


def _top_players(conn, t, n=3):
    from .roster import player_value
    return sorted(_roster(conn, t), key=lambda p: -player_value(conn, p))[:n]


def _goalie(conn, t, gid=None):
    if gid:
        r = conn.execute("SELECT s.player_id FROM player_game_stats s JOIN players p USING (player_id) WHERE s.game_id=? AND "
                         "s.team_id=? AND p.position='G' ORDER BY s.toi_sec DESC LIMIT 1", (gid, t)).fetchone()
        if r:
            return r[0]
    r = conn.execute("SELECT player_id FROM players WHERE team_id=? AND position='G' AND status='active' LIMIT 1", (t,)).fetchone()
    return r[0] if r else None


def _memory(conn, t):
    """The most recent answer that named and criticised a player this season, for a reporter to bring back."""
    from . import contracts as K
    year = K.season_year(conn)
    for r in conn.execute("SELECT answers, created FROM press_events WHERE team_id=? AND status='answered' ORDER BY press_id DESC "
                          "LIMIT 30", (t,)):
        for a in json.loads(r[0] or "[]"):
            if a.get("arch") in ("call_out", "coach") and a.get("target") and r[1][:4] >= str(year):
                return dict(arch=a["arch"], target=a["target"], date=r[1])
    return None


# ---------------------------------------------------------------- question writing

def _q(text, answers, who=None):
    rep = who or "reporter"
    return dict(text=text, reporter=rep, answers=answers)


def _ans(arch, text, target=None, stance=None):
    d = dict(arch=arch, label=LABEL[arch], text=text, target=target)
    if stance:
        d["stance"] = stance
    return d


def _questions(conn, t, kind, ctx, rng):
    club = _club(conn, t)
    nick = club.split(" ")[-1]
    qs = []
    top = _top_players(conn, t)
    star = top[0] if top else None
    starn = player_name(conn, star) if star else "your best player"
    if kind == "postgame":
        gf, ga, opp = ctx["gf"], ctx["ga"], ctx["opp"]
        r_ = conn.execute("SELECT nickname, name FROM teams WHERE abbr=?", (opp,)).fetchone()
        if r_:                                              # v39 (#24): "the Maple Leafs", not "TOR"
            opp = "the " + (r_[0] or r_[1])
        won = gf > ga
        g = ctx.get("goalie")
        gname = player_name(conn, g) if g else "your goalie"
        if won:
            qs.append(_q(f"{gf}-{ga} over {opp}. What did you like about tonight?", [
                _ans("back_group", "Everybody pulled the rope. That's what this group does."),
                _ans("praise", f"{starn} was outstanding. He drove that game.", star),
                _ans("self_credit", "This is the team we built in the summer. It's working."),
                _ans("cliche", "Two points. We'll enjoy it tonight and get back to work tomorrow.")]))
            if ctx.get("streak_w", 0) >= 4:
                qs.append(_q(f"That's {ctx['streak_w']} in a row. Is this team a contender?", [
                    _ans("heart", "I believe in this room. I really do. Why not us?"),
                    _ans("cliche", "One game at a time. Nobody's getting ahead of themselves."),
                    _ans("self_credit", "We said we'd be here. We are.")]))
        else:
            blow = ga - gf >= 4
            qs.append(_q(f"{gf}-{ga} to {opp}{', and it was never close' if blow else ''}. What went wrong?", [
                _ans("accountable", "That's on all of us, me included. We weren't ready and that starts at the top."),
                _ans("call_out", f"Our goaltending has to be better. {gname} knows it.", g),
                _ans("refs", "I'll be careful here, but some of those calls were hard to watch."),
                _ans("demand", "Not good enough. Some guys need to look in the mirror."),
                _ans("cliche", "Credit to them. We'll watch the tape and move on.")]))
            if ctx.get("streak_l", 0) >= 3:
                qs.append(_q(f"That's {ctx['streak_l']} straight. Is the coach's job safe?", [
                    _ans("back_group", "He has my full support. This is a group problem, not one man's."),
                    _ans("coach", "Everyone is being evaluated. Everyone."),
                    _ans("no_comment", "I'm not going to talk about that tonight."),
                    _ans("ultimatum", "If this keeps up, there will be changes. The players know that.")]))
        if ctx.get("rivalry") and won:
            qs.append(_q(f"Beating {opp} always means a little more around here. How sweet was that one?", [
                _ans("heart", "Our fans live for these. So do I. That one's for them."),
                _ans("cliche", "Two points are two points, whoever they're against."),
                _ans("self_credit", f"We built this team to win games like this. Against {opp}, we did."),
                _ans("praise", f"{starn} was the difference tonight, the way big players are in these games.", star)]))
        elif ctx.get("rivalry"):
            qs.append(_q(f"Losing to {opp} stings more than most. How do you take that one?", [
                _ans("accountable", f"It hurts, and it should. Our fans deserved better against {opp}."),
                _ans("cliche", "It's one game in a long season. We'll see them again."),
                _ans("refs", "That one had an edge. I'd like to see it called both ways."),
                _ans("demand", f"Games against {opp} should get the best out of everyone. Tonight they didn't.")]))
    elif kind == "availability":
        res, sk, n = _form(conn, t)
        w = res.count("W")
        qs.append(_q(f"{w}-{len(res) - w} in the last {len(res)}. How do you assess the team right now?", [
            _ans("back_group", "I like where we are. The work is there."),
            _ans("demand", "Some nights we're good, some nights we're not. That has to stop."),
            _ans("accountable", "Results haven't matched expectations, and I own that."),
            _ans("cliche", "We take it a day at a time.")]))
        qs.append(_q(f"There's chatter about {starn}'s future. Is he untouchable?", [
            _ans("praise", f"{starn} is the heart of this team. He isn't going anywhere.", star),
            _ans("no_comment", "I don't talk about trade talk."),
            _ans("deflect", "Nobody is untouchable in this league. You know that.")]))
        mem = _memory(conn, t)
        if mem:
            who = player_name(conn, mem["target"]) if mem["arch"] == "call_out" else "your head coach"
            qs.append(_q(f"On {mem['date']} you were pointed about {who}. Have you two cleared the air?", [
                _ans("accountable", "I said what I said in the moment. We talked. I should've kept it in the room."),
                _ans("demand", "I stand by it. He knows the standard."),
                _ans("no_comment", "That stays between us.")]))
    elif kind == "introduction":                     # v38: meeting the press on day one (hs/game/welcome.py)
        qs.append(_q(f"Welcome. What should {nick} fans expect from this team this season?", [
            _ans("self_credit", "We're here to win the Cup. This roster is good enough, and I'll add to it.", stance="contend"),
            _ans("heart", "Playoff hockey. This city deserves it, and this group can get there.", stance="playoffs"),
            _ans("cliche", "A team that competes every night and gets better as the year goes on.", stance="progress"),
            _ans("accountable", "Honestly? We have work to do. We'll build this the right way, through our young players.", stance="rebuild")]))
        ex, st = ctx.get("expiring"), ctx.get("star")
        if ex:
            en = player_name(conn, ex)
            qs.append(_q(f"{en} can walk at the end of the season. Is getting him signed your first priority?", [
                _ans("praise", f"{en} is a big part of what we want to do here. We'll sit down with his camp soon.", ex),
                _ans("deflect", "I've been in the building for a day. I'll evaluate everyone before I talk contracts."),
                _ans("demand", f"He knows what we need from him. Play well and the rest takes care of itself.", ex)]))
        elif st:
            sn = player_name(conn, st)
            qs.append(_q(f"{sn} is the face of this team. Is he part of your plans, long term?", [
                _ans("praise", f"Absolutely. {sn} is exactly the kind of player you build around.", st),
                _ans("cliche", "Nobody is untouchable in this league, but he's a great player and we're lucky to have him."),
                _ans("demand", f"I'll need to see the best of {sn} every night. That's the standard here.", st)]))
        pr = ctx.get("prospect")
        if pr:
            pn = player_name(conn, pr)
            qs.append(_q(f"There's a lot of excitement about {pn}. Will fans see him in the NHL this year?", [
                _ans("praise", f"If he earns it, yes. {pn} has a real chance to push for a job.", pr),
                _ans("cliche", "We won't rush anybody. He'll play where he develops best."),
                _ans("back_group", "Our prospects will all get a fair look. Nothing is given, nothing is out of reach.")]))
        hc = ctx.get("hc")
        if hc:
            qs.append(_q(f"Is {hc} your coach?", [
                _ans("back_group", f"{hc} is our coach. I'm looking forward to working with him."),
                _ans("deflect", "I'm going to evaluate the whole hockey operation. That's my job."),
                _ans("coach", "We'll see. I have my own ideas about how this team should play.")]))
    elif kind == "media_day":
        qs.append(_q(f"A new season. What's the goal for the {nick} this year?", [
            _ans("heart", "Make this city proud. Make the playoffs and give ourselves a chance."),
            _ans("self_credit", "We made the moves to contend. Anything less is a disappointment."),
            _ans("cliche", "Get better every day and see where that takes us."),
            _ans("ultimatum", "Playoffs. Anything less and changes are coming. The players know it.")]))
        qs.append(_q(f"Who has to step up for this team to take the next step?", [
            _ans("praise", f"{starn}. When he's at his best, we're hard to beat.", star),
            _ans("back_group", "It's not one guy. It's all twenty-three."),
            _ans("demand", "The young guys. It's time.")]))
    elif kind == "deadline":
        qs.append(_q("The deadline has passed. Are you happy with where the roster sits?", [
            _ans("self_credit", "We did what we needed to do. I like this group."),
            _ans("accountable", "I couldn't find the right deal. That's on me, not the players."),
            _ans("back_group", "We believe in the guys in that room. They earned the chance."),
            _ans("deflect", "The market was what it was. Prices were silly.")]))
    elif kind == "season_end":
        qs.append(_q(f"The season's over for the {nick}. How do you sum it up?", [
            _ans("accountable", "Not good enough, and it starts with me. I'll be better."),
            _ans("heart", "I'm proud of how this group battled. We'll be back."),
            _ans("coach", "We'll evaluate everything this summer. Behind the bench too."),
            _ans("self_credit", "We moved forward. The foundation is in place."),
            _ans("ultimatum", "Some players won't be back. That's the reality.")]))
        qs.append(_q("What's the priority this summer?", [
            _ans("cliche", "Get better. Every area."),
            _ans("praise", f"Locking up our core, starting with {starn}.", star),
            _ans("demand", "Toughness. We got pushed around too often.")]))
    elif kind == "trade":
        qs.append(_q(f"Walk us through the trade with {ctx.get('other', 'them')}. Why now?", [
            _ans("self_credit", "We saw a chance to get better and we took it."),
            _ans("heart", "It's never easy moving people out. They gave a lot to this city."),
            _ans("cliche", "It made sense for both sides."),
            _ans("demand", "We needed a different look. The old one wasn't working.")]))
    elif kind == "captaincy":
        c = ctx.get("captain")
        prev = ctx.get("previous")
        cn = player_name(conn, c) if c else "the new captain"
        qs.append(_q(f"Why {cn}, and why now?", [
            _ans("praise", f"{cn} leads the way we want to play. The room follows him.", c),
            _ans("heart", "It's an honour, and he understands that. I couldn't be happier for him."),
            _ans("cliche", "It was the right time, and he's the right guy.")]))
        if prev and prev != c:
            pn = player_name(conn, prev)
            qs.append(_q(f"How did {pn} take the news?", [
                _ans("praise", f"Like a pro. {pn} is still a huge part of this team.", prev),
                _ans("accountable", "It was a hard conversation. I owed him that, face to face."),
                _ans("call_out", "It was time. The room needed a different voice.", prev),
                _ans("no_comment", "That stays between him and me.")]))
    elif kind == "trade_request":
        p = ctx.get("player")
        pn = player_name(conn, p) if p else "the player"
        qs.append(_q(f"Reports say {pn} has asked for a trade. Can you confirm?", [
            _ans("no_comment", "I don't discuss private conversations with players."),
            _ans("heart", f"{pn} has given a lot to this club. We'll do right by him and by the team."),
            _ans("call_out", "We don't reward players who want out. He has a contract.", p),
            _ans("deflect", "There's always noise this time of year.")]))
        qs.append(_q("Will you trade him?", [
            _ans("cliche", "We'll do what's best for the organisation."),
            _ans("ultimatum", "Only if the return is right. I'm in no hurry.", p),
            _ans("praise", "I want to find a way to keep him. He's that good.", p)]))
    elif kind == "contract":
        p = ctx.get("player")
        pn = player_name(conn, p) if p else "the player"
        qs.append(_q(f"Talks with {pn}'s camp have stalled. Is there a gap?", [
            _ans("praise", f"We want {pn} here long term. We'll get there.", p),
            _ans("deflect", "Negotiations happen in private. I'm not going to do them through you."),
            _ans("call_out", "Every player has a number. Some numbers don't make sense.", p),
            _ans("ultimatum", "If he wants to test the market, that's his right. We have options.", p)]))
    outlets = list(OUTLETS)
    rng.shuffle(outlets)
    for i, q in enumerate(qs):
        o = outlets[i % len(outlets)]
        q["reporter"] = f"{rng.choice(REPORTERS)}, {o[0]}"
        q["reporter_kind"] = o[1]
        rng.shuffle(q["answers"])
    return qs


# ---------------------------------------------------------------- scheduling

def schedule(conn, kind, day, ctx=None, team=None):
    ensure_tables(conn)
    t = team if team is not None else user_team(conn)
    if t is None:
        return None
    ctx = dict(ctx or {})
    if conn.execute("SELECT 1 FROM press_events WHERE team_id=? AND kind=? AND created=? AND status='pending'", (t, kind, day)).fetchone():
        return None
    rng = _rng("press", t, kind, day, json.dumps(ctx, sort_keys=True, default=str))
    p, streaky = _pressure(conn, t, ctx)
    ctx["pressure"] = p
    ctx["losing_streak"] = streaky
    qs = _questions(conn, t, kind, ctx, rng)
    if not qs:
        return None
    cur = conn.execute("INSERT INTO press_events (team_id, kind, created, expires, status, context, questions, answers, outcome) "
                       "VALUES (?,?,?,?, 'pending', ?, ?, '[]', NULL)",
                       (t, kind, day, _days(day, 5 if kind in MAJOR else 3), json.dumps(ctx, default=str), json.dumps(qs)))
    return cur.lastrowid


def pending(conn, t=None):
    ensure_tables(conn)
    t = t if t is not None else user_team(conn)
    day = get_state(conn)[0]                                          # the offseason moves the calendar without daily(): expire here too
    for r in conn.execute("SELECT press_id FROM press_events WHERE team_id=? AND status='pending' AND expires<?", (t, day)).fetchall():
        _expire(conn, r[0], day)
    return [dict(r) for r in conn.execute("SELECT * FROM press_events WHERE team_id=? AND status='pending' ORDER BY press_id", (t,))]


def daily(conn, day, summary=None):
    """After each simulated day: post-game press, weekly availability, deadline day, stories coming due, expiries.
    Returns the kinds scheduled (major ones should stop a long sim)."""
    ensure_tables(conn)
    me = user_team(conn)
    if me is None:
        return []
    made = []
    if datetime.date.fromisoformat(day).weekday() == 0:               # Mondays: what the mood does (v30)
        weekly_outcomes(conn, day, me)
    for r in conn.execute("SELECT press_id, kind FROM press_events WHERE team_id=? AND status='pending' AND expires<?", (me, day)).fetchall():
        _expire(conn, r[0], day)
    if summary is not None:
        for gid, h, a, hg, ag, ot in summary.results:
            if me not in (h, a):
                continue
            home = h == me
            gf, ga = (hg, ag) if home else (ag, hg)
            opp = a if home else h
            res, kind, n = _form(conn, me)
            from . import rivalry as RV                   # v37: the rivalry model (hs/game/rivalry.py)
            div = RV.points(conn, me, opp) >= RV.BIG
            story = abs(gf - ga) >= 4 or (kind in ("L", "O") and n >= 3) or (kind == "W" and n >= 4) or bool(div) and _rng("riv", gid).random() < 0.5
            if story or _rng("pg", gid).random() < 1 / 6:
                pid = schedule(conn, "postgame", day, dict(game_id=gid, gf=gf, ga=ga, opp=team_abbr(conn, opp), rivalry=bool(div),
                                                         streak_w=n if kind == "W" else 0, streak_l=n if kind in ("L", "O") else 0,
                                                         goalie=_goalie(conn, me, gid)))
                if pid:
                    made.append("postgame")
    d = datetime.date.fromisoformat(day)
    from . import contracts as K
    from . import trades as T
    if K.season_state(conn) == "regular_season":
        if d.weekday() == 3 and _rng("avail", me, day).random() < 0.5:
            if schedule(conn, "availability", day):
                made.append("availability")
        if d == T.deadline(conn):
            if schedule(conn, "deadline", day):
                made.append("deadline")
        tr = conn.execute("SELECT m.player_id FROM morale m JOIN players p USING (player_id) WHERE p.team_id=? AND m.trade_request=1",
                          (me,)).fetchall() if conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone() else []
        for (pid,) in tr:
            if not conn.execute("SELECT 1 FROM press_events WHERE team_id=? AND kind='trade_request' AND context LIKE ?",
                                (me, f'%"player": {pid}%')).fetchone():
                if schedule(conn, "trade_request", day, dict(player=pid)):
                    made.append("trade_request")
    _stories(conn, me, day)
    return made


def _expire(conn, press_id, day):
    r = conn.execute("SELECT * FROM press_events WHERE press_id=?", (press_id,)).fetchone()
    qs = json.loads(r["questions"])
    ans = [dict(q=i, arch="no_comment", target=None, text="(did not take questions)") for i in range(len(qs))]
    out = _impact(conn, r["team_id"], r["kind"], json.loads(r["context"]), ans, day, quiet=True)
    conn.execute("UPDATE press_events SET status='expired', answers=?, outcome=? WHERE press_id=?",
                 (json.dumps(ans), json.dumps(out), press_id))


# ---------------------------------------------------------------- answering

def answer(conn, press_id, choices, day=None):
    """choices: [answer index per question]. Returns the outcome."""
    day = day or get_state(conn)[0]
    r = conn.execute("SELECT * FROM press_events WHERE press_id=?", (press_id,)).fetchone()
    if r is None or r["status"] != "pending":
        raise ValueError("That press conference is not open.")
    qs = json.loads(r["questions"])
    if len(choices) != len(qs):
        raise ValueError(f"Answer all {len(qs)} questions.")
    ans = []
    for i, (q, c) in enumerate(zip(qs, choices)):
        if not 0 <= c < len(q["answers"]):
            raise ValueError("No such answer.")
        a = q["answers"][c]
        ans.append(dict(q=i, arch=a["arch"], target=a.get("target"), text=a["text"], stance=a.get("stance")))
    out = _impact(conn, r["team_id"], r["kind"], json.loads(r["context"]), ans, day)
    conn.execute("UPDATE press_events SET status='answered', answers=?, outcome=? WHERE press_id=?",
                 (json.dumps(ans), json.dumps(out), press_id))
    return out


def _impact(conn, t, kind, ctx, ans, day, quiet=False):
    mult = 1 + ctx.get("pressure", 40) / 200
    if ctx.get("losing_streak"):
        mult *= 1.2
    tot = dict(morale=0.0, board=0.0, fans=0.0, media=0.0, controversy=0.0)
    personal, lines, stories = {}, [], []
    soft = 1.0
    if t == user_team(conn):                              # media handling (phase A2): bad answers cost less, or more
        from . import gm as GMx
        soft = max(0.7, min(1.3, 1 - 0.03 * (GMx.rating(conn, "media_handling") - 10)))
    from .people import traits
    for a in ans:
        m, b, f, md, c = ARCH[a["arch"]]
        k = mult / max(1, len(ans)) * 1.5
        bad = lambda v: v * soft if v < 0 else v
        tot["morale"] += bad(m) * k
        tot["board"] += bad(b) * k
        tot["fans"] += bad(f) * k
        tot["media"] += bad(md) * k
        tot["controversy"] += (c * soft if c > 0 else c) * k
        tgt = a.get("target")
        if tgt and a["arch"] in ("call_out", "ultimatum"):
            tr = traits(conn, tgt)
            hit = 10 + tr["ego"] / 2
            personal[tgt] = personal.get(tgt, dict(trust=0, morale=0))
            personal[tgt]["trust"] -= hit
            personal[tgt]["morale"] -= 8
            lines.append(f"{player_name(conn, tgt)} heard what you said.")
            stories.append(("confront" if tr["ego"] >= 12 or tr["professionalism"] <= 9 else "sulk", tgt))
            stories.append(("leak", tgt))
        elif tgt and a["arch"] == "praise":
            personal[tgt] = personal.get(tgt, dict(trust=0, morale=0))
            personal[tgt]["trust"] += 4
            personal[tgt]["morale"] += 3
        if a["arch"] == "refs":
            stories.append(("fine", None))
        if a["arch"] == "coach":
            stories.append(("coach_rift", None))
        if a["arch"] == "ultimatum":
            stories.append(("unease", None))
        if a["arch"] in ("accountable", "heart") and _rng("goodpr", t, day, a["q"]).random() < 0.5:
            stories.append(("praise_pr", None))
    stance_lines = []
    if kind == "introduction" and not quiet:          # v38: the promise against the owner's expectation
        from .welcome import STANCE_WORDS, stance_effect
        exp = ctx.get("expected", "playoffs")
        for a in ans:
            if a.get("stance"):
                d = stance_effect(exp, a["stance"])
                tot["board"] += d / 0.35                    # lands as d on the board's confidence
                order = ["rebuild", "progress", "playoffs", "contend"]
                gap = "" if d > 0 else (" (more than he expects)" if order.index(a["stance"]) > order.index(exp) else " (less than he expects)")
                note = f"Introductory press conference: you promised {STANCE_WORDS[a['stance']]}; the owner expects {STANCE_WORDS[exp]}{gap}"
                stance_lines.append(note)
                conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('intro_promise', ?)", (json.dumps(dict(stance=a["stance"], expected=exp, day=day)),))
        lines += stance_lines
    roster = _roster(conn, t)
    if quiet:                                  # a skipped press conference only costs you with the media and fans
        tot["morale"] = tot["board"] = 0.0
    if not quiet and conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        dm = tot["morale"] * 0.3
        for pid in roster:
            extra = personal.get(pid, {})
            conn.execute("UPDATE morale SET morale=MIN(100, MAX(0, morale+?)), trust_mgmt=MIN(100, MAX(0, trust_mgmt+?)) WHERE player_id=?",
                         (dm + extra.get("morale", 0), extra.get("trust", 0), pid))
        if any(a["arch"] == "coach" for a in ans):
            conn.execute(f"UPDATE morale SET trust_coach=MAX(0, trust_coach-4) WHERE player_id IN ({','.join('?' * len(roster))})", roster)
        conn.execute("UPDATE team_room SET cohesion=MIN(100, MAX(0, cohesion+?)) WHERE team_id=?", (tot["morale"] * 0.25, t))
    if conn.execute("SELECT 1 FROM board WHERE team_id=?", (t,)).fetchone() if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='board'").fetchone() else False:
        if abs(tot["board"]) >= 0.1:
            from . import org
            org._apply(conn, t, tot["board"] * 0.35, "introduction" if kind == "introduction" else "press", day,
                       stance_lines or [f"{kind.replace('_', ' ')} press conference"])
    ms = media_state(conn, t)
    ms["fan_sentiment"] = max(0, min(100, ms["fan_sentiment"] + tot["fans"] * 0.6))
    ms["media_sentiment"] = max(0, min(100, ms["media_sentiment"] + tot["media"] * 0.6))
    ms["controversy"] = max(0, min(100, ms["controversy"] * 0.85 + tot["controversy"] * 0.6))
    conn.execute("UPDATE media_state SET fan_sentiment=?, media_sentiment=?, controversy=?, updated=? WHERE team_id=?",
                 (ms["fan_sentiment"], ms["media_sentiment"], ms["controversy"], day, t))
    if not quiet:
        rng = _rng("pr-story", t, day, kind)
        for s, pid in stories:
            delay = {"confront": 1, "sulk": 2, "leak": 2, "fine": 2, "coach_rift": 3, "unease": 2, "praise_pr": 1}[s]
            if s == "leak" and rng.random() > 0.45 + ms["controversy"] / 300:
                continue
            if s == "fine" and rng.random() > 0.4:
                continue
            conn.execute("INSERT INTO story_queue (team_id, due, kind, player_id, payload, status) VALUES (?,?,?,?,?, 'pending')",
                         (t, _days(day, delay), s, pid, json.dumps(dict(kind=kind))))
        # the quote itself is news
        loud = [a for a in ans if a["arch"] in ("call_out", "refs", "coach", "ultimatum", "heart", "accountable")]
        if loud:
            a = max(loud, key=lambda x: ARCH[x["arch"]][4])
            club, ab = _club(conn, t), team_abbr(conn, t)
            hl = {"call_out": f"{ab} GM calls out {player_name(conn, a['target']) if a.get('target') else 'his own player'}",
                  "refs": f"{ab} GM rips the officiating", "coach": f"{ab} GM won't commit to his coach",
                  "ultimatum": f"{ab} GM: 'changes are coming'", "heart": f"{ab} GM's emotional message to the city",
                  "accountable": f"{ab} GM: 'it starts with me'"}[a["arch"]]
            social = [dict(account="@InsiderOnIce", text=f"{ab} GM, today: \"{a['text']}\"")]
            social.append(dict(account="@HockeyTalkPod", text=rng.choice({
                "call_out": ["You do not do that publicly. That room is going to be interesting tomorrow.", "Brutal. Some GMs keep it in-house."],
                "refs": ["That's a fine coming. Worth it? Maybe.", "Said what every fan was thinking."],
                "coach": ["That is not a vote of confidence.", "Coach on the hot seat, officially."],
                "ultimatum": ["The players heard that. Every one of them.", "Bold. Now back it up."],
                "heart": ["Classy. That's how you talk to your fans.", "Love the honesty."],
                "accountable": ["Takes ownership. Respect.", "Good on him for wearing it."]}[a["arch"]])))
            social.append(dict(account=f"@{ab}Faithful", text=rng.choice(
                ["Finally someone said it.", "Not sure about that.", "This is why I love this team.", "Yikes."]
                if a["arch"] in ("call_out", "refs", "coach", "ultimatum") else ["That's our GM.", "Needed to hear that.", "Love it."])))
            emit(conn, "MEDIA_STORY", day, hl, team_id=t, player_id=a.get("target"), importance=2 if a["arch"] in ("heart", "accountable") else 3,
                 headline=hl, body=f"\"{a['text']}\"", tag="press", social=social)
    return dict(totals={k: round(v * (0.3 if k == "morale" else 0.35 if k == "board" else 0.6), 1) for k, v in tot.items()},
                personal={str(k): v for k, v in personal.items()}, lines=lines, media=ms, stories=[s for s, _ in stories])


def _stories(conn, t, day):
    rng = _rng("stories", t, day)
    ab, club = team_abbr(conn, t), _club(conn, t)
    for s in conn.execute("SELECT * FROM story_queue WHERE team_id=? AND status='pending' AND due<=?", (t, day)).fetchall():
        k, pid = s["kind"], s["player_id"]
        pn = player_name(conn, pid) if pid else ""
        if k == "confront":
            on = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone() if pid else None
            if not on or on[0] != t:                     # v39: he has been traded or claimed since: nothing to confront
                conn.execute("UPDATE story_queue SET status='dropped' WHERE story_id=?", (s["story_id"],))
                continue
            add_message(conn, day, f"{pn} wants a word", f"{pn} came to your office this morning, unhappy about what you said publicly. "
                        "He felt blindsided. You can talk to him or let it lie; it will not go away by itself.",
                        sender=__import__("hs.game.state", fromlist=["x"]).staff_sender(conn, "HC", t),
                        actions=[dict(label=f"Talk to {pn}", href=f"#player/{pid}/person", primary=True)])
            conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-2) WHERE team_id=?", (t,))
            emit(conn, "LOCKER_ROOM", day, f"{pn} confronts {ab} management over public criticism", team_id=t, player_id=pid,
                 importance=2, social=[dict(account="@InsiderOnIce", text=f"Hearing {pn} was not happy with the GM's comments. Had it out this morning.")])
        elif k == "sulk":
            add_message(conn, day, "From the head coach", f"{pn} has been quiet since your comments. His practice level has dropped. Worth watching.")
            conn.execute("UPDATE morale SET morale=MAX(0, morale-4) WHERE player_id=?", (pid,))
        elif k == "leak":
            emit(conn, "MEDIA_STORY", day, f"Sources: frustration in the {club} room after GM's comments", team_id=t, player_id=pid, importance=3,
                 headline=f"Sources: {club} players unhappy with GM's public criticism",
                 body=f"Several players reportedly disagreed with management's decision to single out {pn}.", tag="leak",
                 social=[dict(account="@InsiderOnIce", text=f"Sources: some {ab} players felt the GM's comments about {pn} crossed a line."),
                         dict(account=f"@{ab}Faithful", text="Leaks already. Not a great sign.")])
            conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-2) WHERE team_id=?", (t,))
        elif k == "fine":
            emit(conn, "MEDIA_STORY", day, f"League fines {ab} GM $25,000 for comments about officiating", team_id=t, importance=2,
                 headline=f"League fines {ab} GM $25,000", body="The league fined the general manager for public criticism of its officials.",
                 tag="league", social=[dict(account="@InsiderOnIce", text=f"{ab} GM fined $25,000 for his comments on the officiating.")])
            add_message(conn, day, "League office", "The league has fined you $25,000 for your comments about its officials.")
        elif k == "coach_rift":
            from .state import staff_sender
            add_message(conn, day, "From the head coach", "I read your comments. If you have something to say about my job, I'd rather hear it from you.",
                        sender=staff_sender(conn, "HC", t), actions=[dict(label="Staff", href="#staff")])
            emit(conn, "MEDIA_STORY", day, f"Tension between {ab} GM and coach", team_id=t, importance=2,
                 headline=f"Is there a rift between the {club} GM and his coach?", body="The coach was asked about the GM's lukewarm support.", tag="rumour",
                 social=[dict(account="@HockeyTalkPod", text=f"The {ab} coach did not look thrilled answering questions about his GM today.")])
        elif k == "unease":
            add_message(conn, day, "Player relations", "Several players have asked their agents about their futures after your comments. The room is on edge.")
            conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-2) WHERE player_id IN (SELECT player_id FROM players WHERE team_id=?)", (t,))
        elif k == "praise_pr":
            emit(conn, "MEDIA_STORY", day, f"{ab} GM's candour wins fans", team_id=t, importance=1,
                 headline=f"Column: the {club} finally have a GM who tells it straight", body="", tag="column",
                 social=[dict(account=f"@{ab}Faithful", text="Whatever happens, I respect a GM who talks to us like adults.")])
        conn.execute("UPDATE story_queue SET status='done' WHERE story_id=?", (s["story_id"],))


def view(conn, press_id=None):
    me = user_team(conn)
    ensure_tables(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM press_events WHERE team_id=? ORDER BY press_id DESC LIMIT 40", (me,))]
    for r in rows:
        r["context"] = json.loads(r["context"] or "{}")
        r["questions"] = json.loads(r["questions"] or "[]")
        r["answers"] = json.loads(r["answers"] or "[]")
        r["outcome"] = json.loads(r["outcome"]) if r["outcome"] else None
        r["major"] = r["kind"] in MAJOR
        r["title"] = {"postgame": f"Post-game: {r['context'].get('gf')}-{r['context'].get('ga')} vs {r['context'].get('opp')}",
                      "availability": "Media availability", "media_day": "Media day", "introduction": "Introductory press conference", "deadline": "Trade deadline",
                      "season_end": "End-of-season press conference", "trade": "The trade", "captaincy": "The captaincy",
                      "trade_request": "Trade request", "contract": "Contract talks"}.get(r["kind"], r["kind"])
    return dict(events=rows, media=media_state(conn, me), pending=[r for r in rows if r["status"] == "pending"])


# ---------------------------------------------------------------- v30 (defect 12): sentiment has consequences
# Checked each Monday for your club. Each outcome has a three-week cooldown. The numbers are 0-100 (media_state).
OUTCOMES = [
    # kind, test, headline, body, board, morale (every player), cohesion, fans, media
    ("hostile_column", lambda m: m["media_sentiment"] < 30, "Column: {club} have lost the plot, and the GM owns it",
     "The coverage has turned. A widely read column calls for change at the top and the talk shows have picked it up.", -1.0, 0, 0, -2, 0),
    ("fans_turning", lambda m: m["fan_sentiment"] < 30, "Boos and empty seats: {club} fans are running out of patience",
     "Season-ticket holders are vocal and the building was quiet. Players notice.", -1.5, -1, 0, 0, -2),
    ("building_rocking", lambda m: m["fan_sentiment"] > 75, "The building is rocking: {club} fans are all in",
     "Sell-outs, noise, merchandise flying off the shelves. The players say the crowd is worth a goal some nights.", 0.5, 1, 0, 0, 1),
    ("controversy_cycle", lambda m: m["controversy"] > 60, "The {club} soap opera: another week of headlines",
     "Every day brings a new storyline. The room is being asked about it constantly and it is wearing on them.", -0.5, -1, -2, -1, -2),
    ("good_press", lambda m: m["media_sentiment"] > 75 and m["controversy"] < 20, "{club} are doing it the right way, say the critics",
     "A run of glowing coverage: the plan, the culture, the way the GM handles himself.", 0.5, 0, 1, 1, 0),
]


FORM_DRIFT_FANS, FORM_DRIFT_MEDIA = 0.25, 0.15


def _recent_form(conn, t, n=10):
    """Points percentage over the club's last n regular-season games this season (None before 5 games)."""
    rows = conn.execute("SELECT home_team_id, home_goals, away_goals, went_to_ot FROM games WHERE played=1 AND game_type='RS' "
                        "AND (home_team_id=? OR away_team_id=?) AND season_id=(SELECT season_id FROM seasons ORDER BY "
                        "start_year DESC LIMIT 1) ORDER BY game_date DESC LIMIT ?", (t, t, n)).fetchall()
    if len(rows) < 5:
        return None
    pts = 0
    for h, hg, ag, ot in rows:
        gf, ga = (hg, ag) if h == t else (ag, hg)
        pts += 2 if gf > ga else (1 if ot else 0)
    return pts / (2 * len(rows))


def weekly_outcomes(conn, day, t=None):
    """What the fans' and the media's mood does this week (stories, the board, the room). Returns headlines."""
    t = t if t is not None else user_team(conn)
    if t is None:
        return []
    m = media_state(conn, t)
    form = _recent_form(conn, t)
    if form is not None:              # v39 (#22): results move the mood too; a hot streak lifts the fans and the coverage
        tgt = 25 + 60 * form
        m["fan_sentiment"] += (tgt - m["fan_sentiment"]) * FORM_DRIFT_FANS
        m["media_sentiment"] += (tgt - m["media_sentiment"]) * FORM_DRIFT_MEDIA
        conn.execute("UPDATE media_state SET fan_sentiment=?, media_sentiment=? WHERE team_id=?",
                     (m["fan_sentiment"], m["media_sentiment"], t))
    out = []
    club = _club(conn, t)
    for kind, test, hl, body, board, morale, coh, dfans, dmedia in OUTCOMES:
        if not test(m):
            continue
        if form is not None and ((kind in ("hostile_column", "fans_turning") and form >= 0.55)
                                 or (kind == "building_rocking" and form < 0.45)):
            continue                  # the story has to fit the results
        key = f"media_out_{t}_{kind}"
        last = conn.execute("SELECT value FROM pack_info WHERE key=?", (key,)).fetchone()
        if last and last[0] > _days(day, -21):
            continue
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?,?)", (key, day))
        h = hl.format(club=club)
        emit(conn, "MEDIA_STORY", day, h, team_id=t, importance=2, headline=h, body=body, tag="media", kind=kind)
        if board:
            from . import org
            org._apply(conn, t, board, "media", day, [h])
        if morale and conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
            conn.execute("UPDATE morale SET morale=MAX(0, MIN(100, morale+?)) WHERE player_id IN (SELECT player_id FROM players WHERE team_id=?)",
                         (morale, t))
        if coh and conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_room'").fetchone():
            conn.execute("UPDATE team_room SET cohesion=MAX(0, MIN(100, cohesion+?)) WHERE team_id=?", (coh, t))
        if dfans or dmedia:
            conn.execute("UPDATE media_state SET fan_sentiment=MAX(0, MIN(100, fan_sentiment+?)), media_sentiment=MAX(0, MIN(100, media_sentiment+?)) "
                         "WHERE team_id=?", (dfans, dmedia, t))
        out.append(h)
    return out


def engine_form(conn):
    """Per club: (form, home_form) multipliers on shot attempts for the game engine. Controversy above 60 costs
    composure (up to -4% at 100); a crowd above 75 helps at home (+1.5%), one below 30 hurts at home (-1.5%)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='media_state'").fetchone():
        return {}
    out = {}
    for r in conn.execute("SELECT team_id, fan_sentiment, controversy FROM media_state"):
        form = 1 - max(0.0, r[2] - 60) / 1000
        home = 1.015 if r[1] > 75 else 0.985 if r[1] < 30 else 1.0
        out[r[0]] = (form, home)
    return out
