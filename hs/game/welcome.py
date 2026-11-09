"""Your first day at a club (v38, register #1 and #2): the owner's welcome, the club briefing, the introductory press
conference.

`start_career(conn, day)` runs once a career starts (a new game, or taking a job):
  * the owner writes: who he is, what he expects this season (the board's objectives, required or preferred), the
    payroll he will allow, how patient he is, and what comes next; links to Job Security and Finances
  * your assistant GM sends the club briefing: where the scouts project the club, the forwards, defence and goal
    against the league, the stars and the goalie situation, the leadership group, the cap, who is out of contract this
    summer, the best prospects and the coaching staff; links to the screens
  * the introductory press conference is scheduled for today (the Press room): what you expect this season, the star
    whose contract is ending (or the best player), the best prospect, and the head coach. What you promise is weighed
    against what the owner expects: in line, his confidence rises; promising much more or much less than he expects
    costs you, and the gap is noted on Job Security (board history: "introduction"). Reporters remember your promise.
"""
from __future__ import annotations

import datetime

from .events import player_name, team_abbr
from .state import add_message, get_state, staff_sender, user_team

STANCES = ("rebuild", "progress", "playoffs", "contend")
STANCE_WORDS = {"rebuild": "a rebuild", "progress": "steady progress", "playoffs": "the playoffs", "contend": "a run at the Cup"}


def _club(conn, t):
    r = conn.execute("SELECT name, nickname FROM teams WHERE team_id=?", (t,)).fetchone()
    return f"{r[0]} {r[1] or ''}".strip()


def expected_stance(conn, t):
    """What the owner expects, from his competitive objective."""
    from .contracts import season_year
    r = conn.execute("SELECT code, target FROM objectives WHERE team_id=? AND season_start_year=? AND category='competitive' "
                     "ORDER BY objective_id LIMIT 1", (t, season_year(conn))).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='objectives'").fetchone() else None
    if not r:
        return "playoffs"
    if r[0] == "playoff_round":
        return "contend" if (r[1] or 0) >= 3 else "playoffs"
    return "progress" if r[0] == "playoff_gap" else "rebuild"


def _age(birth, on):
    b = datetime.date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def briefing(conn, t):
    """The facts the welcome, the briefing and the press conference are written from."""
    from .contracts import season_year
    from .org import projected_ranks
    from .roster import player_value
    year = season_year(conn)
    on = datetime.date.fromisoformat(get_state(conn)[0])
    ranks = projected_ranks(conn)
    n = len(ranks)
    rows = conn.execute("SELECT player_id, position, birth_date FROM players WHERE team_id=? AND status IN ('active','injured')", (t,)).fetchall()
    vals = sorted(((player_value(conn, r[0]), r[0], r[1]) for r in rows), reverse=True)
    grp = lambda p: "G" if p == "G" else "D" if p == "D" else "F"

    def group_rank(g, top):
        mine = {}
        for team in ranks:
            vs = sorted((player_value(conn, r[0]) for r in conn.execute(
                "SELECT player_id, position FROM players WHERE team_id=? AND status IN ('active','injured')", (team,)) if grp(r[1]) == g), reverse=True)
            mine[team] = sum(vs[:top]) / max(1, len(vs[:top]))
        order = sorted(mine, key=lambda x: -mine[x])
        return order.index(t) + 1
    groups = {"forwards": group_rank("F", 9), "defence": group_rank("D", 6), "goal": group_rank("G", 1)}
    stars = [pid for _, pid, pos in vals if pos != "G"][:3]
    goalies = [pid for _, pid, pos in vals if pos == "G"][:2]
    expiring = []
    for r in conn.execute("SELECT c.player_id, c.cap_hit, p.birth_date FROM contracts c JOIN players p USING (player_id) WHERE c.team_id=? "
                          "AND c.start_year+c.years-1=? AND p.team_id=?", (t, year, t)):
        expiring.append((player_value(conn, r[0]), r[0], "RFA" if _age(r[2], datetime.date(year + 1, 6, 30)) < 27 else "UFA", r[1]))
    expiring.sort(reverse=True)
    pros = []
    for r in conn.execute("SELECT p.player_id, d.potential FROM players p JOIN player_dev d USING (player_id) WHERE p.team_id=? AND p.status='prospect' "
                          "UNION SELECT r.player_id, d.potential FROM draft_rights r JOIN player_dev d USING (player_id) WHERE r.team_id=?", (t, t)):
        pros.append((r[1] or 0, r[0]))
    pros.sort(reverse=True)
    from . import contracts as K
    cap = K.crules(conn)["cap_ceiling"]
    pay = K.payroll(conn, t)
    hc = conn.execute("SELECT name, style, coaching FROM staff WHERE team_id=? AND role='HC' ORDER BY staff_id LIMIT 1", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone() else None
    capt = conn.execute("SELECT player_id FROM leadership WHERE team_id=? AND role='C'", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='leadership'").fetchone() else None
    ages = [_age(r[2], on) for r in rows]
    return dict(rank=ranks.get(t), n=n, groups=groups, stars=stars, goalies=goalies, expiring=expiring[:5], prospects=[p for _, p in pros[:3]],
                cap=cap, payroll=pay, hc=dict(name=hc[0], style=hc[1], coaching=hc[2]) if hc else None, captain=capt[0] if capt else None,
                avg_age=round(sum(ages) / len(ages), 1) if ages else None, year=year)


def _ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _money(v):
    return f"${v / 1e6:.1f}M"


def start_career(conn, day, t=None):
    t = t if t is not None else user_team(conn)
    if t is None:
        return
    key = f"welcome_{t}_{day}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    from .contracts import season_year
    club, ab = _club(conn, t), team_abbr(conn, t)
    b = briefing(conn, t)
    o = conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone() else None
    objs = conn.execute("SELECT description, importance FROM objectives WHERE team_id=? AND season_start_year=? AND category<>'long-term' "
                        "ORDER BY objective_id", (t, season_year(conn))).fetchall() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='objectives'").fetchone() else []
    me = conn.execute("SELECT name FROM gm_profile WHERE id=1").fetchone() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='gm_profile'").fetchone() else None
    you = me[0].split()[0] if me and me[0] and me[0] != "Manager" else None
    oname = (o["name"] if o and o["name"] else "The owner")
    patience = (o["patience"] if o else 5) or 5
    exp = expected_stance(conn, t)
    lines = [f"Welcome to the {club}, {you}." if you else f"Welcome to the {club}.", "",
             (f"I'll be straight with you about who I am: {o['summary']}. " if o and o["summary"] else "") +
             {"contend": "This group should be playing deep into the spring, and I expect it to.",
              "playoffs": "This club belongs in the playoffs. That is the bar.",
              "progress": "I want to see this club moving in the right direction: competitive, harder to play against, in the race.",
              "rebuild": "We are building something. I want it done properly, not quickly."}[exp], ""]
    if objs:
        lines.append("What I expect this season:")
        lines += [f"  - {d} ({imp})" for d, imp in objs]
        lines.append("")
    lines.append({True: "I am not a patient man. If it isn't working, I will not wait long to say so.",
                  False: "I give people time to do the job properly, as long as I can see the plan working."}[patience <= 4])
    lines += ["", "Your assistant GM has a full briefing on the club for you. Then you meet the press: what you tell them will "
              "be read here as carefully as anywhere. I look forward to working with you.", "", oname]
    add_message(conn, day, f"Welcome to the {club}", "\n".join(lines), sender=f"{oname}, Owner",
                actions=[dict(label="Job security and objectives", href="#board", primary=True), dict(label="Finances", href="#finances")])

    g = b["groups"]
    rank = b["rank"]
    out = [f"Here is where we stand as you walk in.", "",
           f"WHERE WE STAND: our scouts project us {_ordinal(rank)} of {b['n']} on paper. Forwards {_ordinal(g['forwards'])}, defence "
           f"{_ordinal(g['defence'])}, goal {_ordinal(g['goal'])} in the league. Average age {b['avg_age']}.", ""]
    if b["stars"]:
        out.append("THE CORE: " + ", ".join(player_name(conn, p) for p in b["stars"]) + ".")
    if b["goalies"]:
        out.append("IN GOAL: " + player_name(conn, b["goalies"][0]) + (f", backed up by {player_name(conn, b['goalies'][1])}" if len(b["goalies"]) > 1 else "") + ".")
    if b["captain"]:
        out.append(f"LEADERSHIP: {player_name(conn, b['captain'])} wears the C.")
    if b["cap"]:
        room = b["cap"] - b["payroll"]
        out.append(f"THE CAP: {_money(b['payroll'])} committed against a {_money(b['cap'])} ceiling: "
                   + (f"{_money(room)} of room." if room >= 0 else f"{_money(-room)} over. That has to be fixed."))
    if b["expiring"]:
        out.append("OUT OF CONTRACT THIS SUMMER: " + "; ".join(f"{player_name(conn, p)} ({st}, {_money(c)})" for _, p, st, c in b["expiring"]) + ".")
    if b["prospects"]:
        out.append("THE PIPELINE: " + ", ".join(player_name(conn, p) for p in b["prospects"]) + " are the prospects the staff like most.")
    if b["hc"]:
        out.append(f"BEHIND THE BENCH: {b['hc']['name']}" + (f", a {b['hc']['style']}" if b["hc"]["style"] else "") + ".")
    out += ["", "Everything is on the screens linked above. My door is open."]
    agm = conn.execute("SELECT name FROM pack_staff WHERE team_id=? AND role='AGM' ORDER BY rowid LIMIT 1", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='pack_staff'").fetchone() else None
    add_message(conn, day, f"Club briefing: the state of the {club.split()[-1]}", "\n".join(out),
                sender=f"{agm[0]}, Assistant GM" if agm else _made_up_agm(conn, t),
                actions=[dict(label="Roster", href="#roster", primary=True), dict(label="Contracts and cap", href="#contracts"),
                         dict(label="Prospects", href="#prospects"), dict(label="Staff", href="#staff"), dict(label="Lineup", href="#lines")])
    from . import press
    ctx = dict(expected=exp, expiring=b["expiring"][0][1] if b["expiring"] else None, star=b["stars"][0] if b["stars"] else None,
               prospect=b["prospects"][0] if b["prospects"] else None, hc=b["hc"]["name"] if b["hc"] else None)
    pid = press.schedule(conn, "introduction", day, ctx, team=t)
    if pid:
        add_message(conn, day, "Your introductory press conference", f"The media are waiting to meet the new GM of the {club}. "
                    "They will ask what you expect this season, about the roster and the coach. The owner will be listening.",
                    sender="Media relations", actions=[dict(label="Go to the Press room", href="#press", primary=True)])


def _made_up_agm(conn, t):
    import random
    from .staff import FIRST, LAST
    rng = random.Random(f"{get_state(conn)[1]}-agm-{t}")
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}, Assistant GM"


def stance_effect(expected, said):
    """Board confidence for a promise against the owner's expectation: in line +4, one step off -1, further -6."""
    d = abs(STANCES.index(expected) - STANCES.index(said))
    return 4.0 if d == 0 else -1.0 if d == 1 else -6.0
