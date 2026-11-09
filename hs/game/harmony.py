"""Team harmony (phase D, v35): cliques, clashes and incidents in the dressing room.

Cliques. Players group by language (nationality: the North Americans, the Swedes, the Finns, the Russians, the Czechs
and Slovaks...) and by age (the veterans, 31+, and the kids, 23 and under). A group of four or more is a clique. A
clique is harmless while its members are happy; when its average morale drops under 45 it pulls the room down (one
point of cohesion a week for each unhappy clique).

Clashes. Two players clash when both have a big ego (14+) and either a short fuse (temperament 7 or less) or little
sportsmanship (7 or less), or one of them is a malcontent (ego 16+, professionalism 7 or less) who is unhappy (morale
under 45). Each week a clash has a chance to become an incident: 12%, less with a strong captain (leadership 15+
halves it) and more in a tense room. An incident is a story (an argument at practice, a scuffle in the room, a public
spat): cohesion -3, both players' morale -4 (logged), and a message if it is your club. The Team Info screen lists the
cliques and the clashes.
"""
from __future__ import annotations

import datetime
import random

from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

GROUPS = {"North Americans": {"CAN", "USA"}, "Swedes": {"SWE"}, "Finns": {"FIN"}, "Russians": {"RUS", "BLR", "UKR", "KAZ"},
          "Czechs and Slovaks": {"CZE", "SVK"}, "Germans, Swiss and Austrians": {"GER", "SUI", "AUT"}}
P_INCIDENT = 0.12
INCIDENTS = ["an argument at practice between {a} and {b}", "a scuffle in the dressing room: {a} and {b} had to be pulled apart",
             "{a} and {b} trading words on the bench, caught on camera", "{a} criticises {b} in front of the media"]


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS incidents (incident_id INTEGER PRIMARY KEY, team_id INTEGER, day TEXT, kind TEXT, "
                 "a INTEGER, b INTEGER, text TEXT)")


def _roster(conn, t):
    from .people import traits
    from . import hidden as HD
    on = datetime.date.fromisoformat(get_state(conn)[0])
    out = []
    for r in conn.execute("SELECT p.player_id, p.nationality, p.birth_date, m.morale FROM players p LEFT JOIN morale m USING (player_id) "
                          "WHERE p.team_id=? AND p.status IN ('active','injured','ltir')", (t,)):
        b = datetime.date.fromisoformat(r[2])
        age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
        out.append(dict(pid=r[0], nat=r[1], age=age, morale=r[3] if r[3] is not None else 60, tr=traits(conn, r[0]), h=HD.of(conn, r[0])))
    return out


def cliques(conn, t, roster=None):
    roster = roster if roster is not None else _roster(conn, t)
    out = []
    for name, nats in GROUPS.items():
        mem = [p for p in roster if p["nat"] in nats]
        if len(mem) >= 4 and len(mem) <= len(roster) * 0.5:          # a minority group within the room
            out.append(dict(name=name, players=[p["pid"] for p in mem], morale=round(sum(p["morale"] for p in mem) / len(mem))))
    for name, test in (("The veterans", lambda p: p["age"] >= 31), ("The kids", lambda p: p["age"] <= 23)):
        mem = [p for p in roster if test(p)]
        if len(mem) >= 4:
            out.append(dict(name=name, players=[p["pid"] for p in mem], morale=round(sum(p["morale"] for p in mem) / len(mem))))
    return out


def _volatile(p):
    tr, h = p["tr"], p["h"]
    malcontent = tr["ego"] >= 16 and tr["professionalism"] <= 7 and p["morale"] < 45
    hot = tr["ego"] >= 14 and (h["temperament"] <= 7 or h["sportsmanship"] <= 7)
    return malcontent or hot


def clashes(conn, t, roster=None):
    roster = roster if roster is not None else _roster(conn, t)
    vol = [p for p in roster if _volatile(p)]
    pairs = []
    for i, a in enumerate(vol):
        for b in vol[i + 1:]:
            pairs.append((a["pid"], b["pid"]))
    return pairs


def weekly(conn, day):
    """Every Monday, for every club: unhappy cliques weigh on the room; clashes may become incidents."""
    ensure_table(conn)
    from ..schema import top_league_sql
    from .people import log_event
    me = user_team(conn)
    for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}").fetchall():
        roster = _roster(conn, t)
        if not roster:
            continue
        sad = [c for c in cliques(conn, t, roster) if c["morale"] < 45]
        if sad:
            conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-?) WHERE team_id=?", (len(sad), t))
        cap = conn.execute("SELECT s.leadership FROM leadership l JOIN personality s USING (player_id) WHERE l.team_id=? AND l.role='C'", (t,)).fetchone()
        room = conn.execute("SELECT cohesion FROM team_room WHERE team_id=?", (t,)).fetchone()
        p = P_INCIDENT * (0.5 if cap and cap[0] >= 15 else 1.0) * (1.4 if room and room[0] < 40 else 1.0)
        rng = random.Random(f"{get_state(conn)[1]}-{day}-harmony-{t}")
        for a, b in clashes(conn, t, roster):
            if rng.random() >= p:
                continue
            text = rng.choice(INCIDENTS).format(a=player_name(conn, a), b=player_name(conn, b))
            conn.execute("INSERT INTO incidents (team_id, day, kind, a, b, text) VALUES (?,?,?,?,?,?)", (t, day, "clash", a, b, text))
            conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-3) WHERE team_id=?", (t,))
            for x in (a, b):
                conn.execute("UPDATE morale SET morale=MAX(0, morale-4), team=MAX(0, team-6) WHERE player_id=?", (x,))
                log_event(conn, x, day, "team", -4, "a falling-out with a teammate")
            hl = f"{team_abbr(conn, t)} room: {text}"
            emit(conn, "MEDIA_STORY", day, hl, team_id=t, player_id=a, importance=2 if t == me else 1, headline=hl,
                 body=f"Sources describe {text}. The club played it down.", tag="room", kind="incident")
            if t == me:
                from .state import staff_sender
                from .events import player_name as _pn
                add_message(conn, day, "Trouble in the room", f"We had {text}. I have spoken to both of them. Cohesion has taken "
                            "a knock; a word from you might help: a supportive or a firm conversation, on their Personality tab.",
                            sender=staff_sender(conn, "HC", t),
                            actions=[dict(label=f"Talk to {_pn(conn, x)}", href=f"#player/{x}/person") for x in (a, b)] +
                                    [dict(label="The room (Team Info)", href=f"#teaminfo/{t}")])
            break                                         # one incident a club a week


def view(conn, t):
    ensure_table(conn)
    roster = _roster(conn, t)
    name = lambda x: player_name(conn, x)
    return dict(cliques=[dict(c, names=[name(x) for x in c["players"]]) for c in cliques(conn, t, roster)],
                clashes=[dict(a=a, b=b, names=[name(a), name(b)]) for a, b in clashes(conn, t, roster)],
                incidents=[dict(day=r[0], text=r[1]) for r in conn.execute("SELECT day, text FROM incidents WHERE team_id=? ORDER BY day DESC LIMIT 8", (t,))])
