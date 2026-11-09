"""Hockey operations staff: roles, attributes, a staff market, and what each department actually changes.

Roles per NHL club: HC (head coach), AC x2 (assistants), GC (goalie coach), DEV (player development),
SCOUT_DIR + SCOUT x2 (amateur scouting), MED (medical/performance), ANALYTICS.
Attributes (1-20): coaching, development, evaluation, medical, communication, leadership, reputation, plus age,
salary and contract end. Fictional names.

Effects (meaningful but not deterministic; all relative to a neutral 10):
  scouting     draft scouting noise sd = 0.75 - 0.035 * (scouting quality - 10), clipped 0.25-1.0
               (quality = 0.5 director + 0.25 each scout, on 'evaluation')
  development  growth speed of players 24 and under in the organisation x (1 + 0.02 * (quality - 10))
               (quality = 0.5 DEV + 0.3 HC + 0.2 AC average, on 'development'; goalies use GC instead of AC)
  medical      injury length x (1 - 0.025 * (MED medical - 10)), at least 0.6
  head coach   communication and leadership feed trust in coaching and cohesion in the locker room; the coach
               has no direct effect on the match engine yet (that needs recalibration, see the roadmap)
"""
from __future__ import annotations

import random

from ..schema import top_league_sql
from .events import emit, team_abbr
from .state import add_message, get_state, user_team

ROLES = [("HC", 1), ("AC", 2), ("GC", 1), ("DEV", 1), ("SCOUT_DIR", 1), ("SCOUT", 2), ("MED", 1), ("ANALYTICS", 1)]
ROLE_NAMES = {"HC": "Head coach", "AC": "Assistant coach", "GC": "Goaltending coach", "DEV": "Development coach",
              "SCOUT_DIR": "Director of amateur scouting", "SCOUT": "Amateur scout", "MED": "Head of medical",
              "ANALYTICS": "Analytics lead"}
MAIN_ATTR = {"HC": "coaching", "AC": "coaching", "GC": "coaching", "DEV": "development", "SCOUT_DIR": "evaluation",
             "SCOUT": "evaluation", "MED": "medical", "ANALYTICS": "evaluation"}
ATTRS = ["coaching", "development", "evaluation", "medical", "communication", "leadership", "reputation"]
FIRST = ["Rick", "Dave", "Mike", "Paul", "Jon", "Andre", "Luc", "Scott", "Todd", "Glen", "Rob", "Greg", "Dan",
         "Sylvain", "Lars", "Jukka", "Ville", "Sergei", "Mats", "Tony", "Al", "Craig", "Darryl", "Barry"]
LAST = ["Mason", "Quenneville", "Brind'Amour", "Boucher", "Laviolette", "Cassidy", "Sullivan", "Tocchet", "Hextall",
        "Arniel", "Berube", "Carbery", "Hakstol", "Woodcroft", "Lalonde", "Bednar", "Keefe", "Montgomery", "Muller",
        "Granato", "Housley", "Nasreddine", "Ruff", "Gulutzan", "Lambert", "Byrne", "McLean", "Peters", "Tippett",
        "Gilbert"]
MARKET_SIZE = 60


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS staff (staff_id INTEGER PRIMARY KEY, name TEXT, role TEXT, team_id INTEGER, "
                 "age INTEGER, coaching INTEGER, development INTEGER, evaluation INTEGER, medical INTEGER, "
                 "communication INTEGER, leadership INTEGER, reputation INTEGER, salary INTEGER, contract_end INTEGER, "
                 "style TEXT)")


def _gen(rng, role, year, team_id, quality=10.0):
    a = {k: max(1, min(20, round(rng.gauss(quality - 1.5, 2.5)))) for k in ATTRS}
    a[MAIN_ATTR[role]] = max(1, min(20, round(rng.gauss(quality + 1, 2.5))))
    if role == "HC":
        a["communication"] = max(1, min(20, round(rng.gauss(quality, 3))))
        a["leadership"] = max(1, min(20, round(rng.gauss(quality, 3))))
    style = rng.choice(["players' coach", "demanding", "teacher", "tactician", "motivator"]) if role in ("HC", "AC") \
        else ""
    if role == "SCOUT_DIR":
        from .scouting import STYLE_MIX
        style = rng.choices([x for x, _ in STYLE_MIX], [w for _, w in STYLE_MIX])[0]
    salary = int((300_000 if role in ("SCOUT", "ANALYTICS") else 600_000 if role != "HC" else 2_000_000)
                 * (0.6 + a[MAIN_ATTR[role]] / 20))
    return dict(name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", role=role, team_id=team_id,
                age=rng.randint(34, 66), salary=salary, contract_end=year + rng.randint(0, 3), style=style, **a)


def _insert(conn, s):
    cols = list(s)
    cur = conn.execute(f"INSERT INTO staff ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       [s[c] for c in cols])
    return cur.lastrowid


def setup(conn):
    ensure_tables(conn)
    if conn.execute("SELECT 1 FROM staff").fetchone():
        return
    for t in [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")]:
        setup_team(conn, t)
    refill_market(conn)


def setup_team(conn, t):
    """A club's front office and coaching staff (a new game, or an expansion club, v45). Once per club."""
    ensure_tables(conn)
    if conn.execute("SELECT 1 FROM staff WHERE team_id=?", (t,)).fetchone():
        return
    seed = get_state(conn)[1]
    year = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
    rng = random.Random(f"{seed}-staff-{t}")
    q = rng.gauss(10.5, 1.2)                         # some organisations are simply better run
    named = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='pack_staff'").fetchone():   # v38: an imported database's staff
        for name, role, age in conn.execute("SELECT name, role, age FROM pack_staff WHERE team_id=? ORDER BY rowid", (t,)):
            named.setdefault(role, []).append((name, age))
    for role, n in ROLES:
        for _ in range(n):
            s = _gen(rng, role, year, t, q)
            if named.get(role):
                name, age = named[role].pop(0)
                s["name"] = name
                if age and 25 <= age <= 80:
                    s["age"] = age
            _insert(conn, s)


def refill_market(conn):
    seed = get_state(conn)[1]
    year = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
    rng = random.Random(f"{seed}-{year}-staffmarket")
    have = conn.execute("SELECT COUNT(*) FROM staff WHERE team_id IS NULL").fetchone()[0]
    for _ in range(max(0, MARKET_SIZE - have)):
        role = rng.choices([r for r, _ in ROLES], [3, 4, 2, 2, 2, 4, 2, 2])[0]
        _insert(conn, _gen(rng, role, year, None, rng.gauss(9.8, 1.6)))


def members(conn, t, role=None):
    q = "SELECT * FROM staff WHERE team_id=?" + (" AND role=?" if role else "") + " ORDER BY role, staff_id"
    return conn.execute(q, (t, role) if role else (t,)).fetchall()


def _avg(rows, attr, default=10.0):
    return sum(r[attr] for r in rows) / len(rows) if rows else default


def scouting_quality(conn, t):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return 10.0
    d, s = members(conn, t, "SCOUT_DIR"), members(conn, t, "SCOUT")
    return 0.5 * _avg(d, "evaluation") + 0.5 * _avg(s, "evaluation")


def scout_sd(conn, t):
    sd = max(0.25, min(1.0, 0.75 - 0.035 * (scouting_quality(conn, t) - 10)))
    if t is not None:                                     # v34: the scouting budget (neutral at the default)
        from . import finance as FN
        sd *= FN.scouting_effect(conn, t)
    if t is not None and t == user_team(conn):           # your own eye (judging talent) tightens or loosens it
        from . import gm as GMx
        sd *= max(0.7, min(1.3, 1 - 0.03 * (GMx.rating(conn, "judging_talent") - 10)))
    return max(0.2, sd)


def development_multiplier(conn, t, goalie=False):
    if not t or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return 1.0
    q = 0.5 * _avg(members(conn, t, "DEV"), "development") + 0.3 * _avg(members(conn, t, "HC"), "development") + \
        0.2 * _avg(members(conn, t, "GC" if goalie else "AC"), "development")
    from . import finance as FN                       # v34: the development budget (neutral at the default)
    return (1 + 0.02 * (q - 10)) * FN.development_effect(conn, t)


def injury_multiplier(conn, t):
    if not t or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return 1.0
    return max(0.6, 1 - 0.025 * (_avg(members(conn, t, "MED"), "medical") - 10))


def head_coach(conn, t):
    r = members(conn, t, "HC")
    return r[0] if r else None


ROLE_LIMIT = dict(ROLES)


def hire(conn, t, staff_id, day):
    s = conn.execute("SELECT * FROM staff WHERE staff_id=?", (staff_id,)).fetchone()
    if s is None or s["team_id"] is not None:
        raise ValueError("That person is not available.")
    if len(members(conn, t, s["role"])) >= ROLE_LIMIT[s["role"]]:
        raise ValueError(f"You already have the maximum of {ROLE_LIMIT[s['role']]} {ROLE_NAMES[s['role']].lower()}"
                         f"(s); dismiss one first.")
    year = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
    conn.execute("UPDATE staff SET team_id=?, contract_end=? WHERE staff_id=?", (t, year + 2, staff_id))
    if s["role"] == "HC" and t != user_team(conn):
        from . import tactics
        tactics.ai_choose(conn, [t])                  # a new coach brings his own system
    emit(conn, "STAFF_HIRED", day, f"{team_abbr(conn, t)} hire {s['name']} ({ROLE_NAMES[s['role']]})", team_id=t,
         staff_id=staff_id, importance=2 if s["role"] == "HC" else 1)


def dismiss(conn, t, staff_id, day, reason="dismissed"):
    s = conn.execute("SELECT * FROM staff WHERE staff_id=? AND team_id=?", (staff_id, t)).fetchone()
    if s is None:
        raise ValueError("That person is not on your staff.")
    if s["contract_end"] == 9999:
        raise ValueError("That is you: to hand over the bench, step down as coach on the Manager Profile screen.")
    conn.execute("UPDATE staff SET team_id=NULL WHERE staff_id=?", (staff_id,))
    if s["role"] == "HC" and t == user_team(conn):
        from . import boardroom
        relief = boardroom.on_user_coach_fired(conn, t, day)
        if relief:
            from .state import add_message
            add_message(conn, day, "Coaching change", relief)
    emit(conn, "COACH_FIRED" if s["role"] == "HC" else "STAFF_DISMISSED", day,
         f"{team_abbr(conn, t)} {reason} {s['name']} ({ROLE_NAMES[s['role']]})", team_id=t, staff_id=staff_id,
         importance=3 if s["role"] == "HC" else 1)


RENEW_YEARS = 2
AI_KEEP_MAIN = 10               # AI clubs keep staff at least this good at their main job (others half the time)


def renew_contracts(conn, day):
    """Staff contracts that ran out with the season just finished: AI clubs re-sign the good ones (and half of the
    rest) for two years and let the others go to the market; the user's are renewed for two years, with an inbox
    note so he can let someone go instead."""
    import random as _r
    year = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
    me = user_team(conn)
    rng = _r.Random(f"{year}-staff-renewals")
    mine, left = [], 0
    for s in conn.execute("SELECT * FROM staff WHERE team_id IS NOT NULL AND contract_end IS NOT NULL AND "
                          "contract_end<=? ORDER BY staff_id", (year,)).fetchall():
        if s["team_id"] == me:
            conn.execute("UPDATE staff SET contract_end=? WHERE staff_id=?", (year + RENEW_YEARS, s["staff_id"]))
            mine.append(f"{s['name']} ({ROLE_NAMES[s['role']]})")
        elif s[MAIN_ATTR[s["role"]]] >= AI_KEEP_MAIN or rng.random() < 0.5:
            conn.execute("UPDATE staff SET contract_end=? WHERE staff_id=?", (year + RENEW_YEARS, s["staff_id"]))
        else:
            dismiss(conn, s["team_id"], s["staff_id"], day, "let go (contract expired)")
            left += 1
    if mine:
        from .state import add_message
        add_message(conn, day, "Staff contracts renewed",
                    "Renewed for two years: " + ", ".join(mine) + ". To replace someone, `dismiss` him and `hire` "
                    "from the staff market (the Staff screen).")
    return [f"Staff: {left} AI staff contracts not renewed."] if left else []


def ai_offseason(conn, day):
    """AI clubs: an impatient owner with an unhappy board replaces the head coach; every vacancy is filled with
    the best available candidate (by the role's main attribute and reputation)."""
    me = user_team(conn)
    lines = renew_contracts(conn, day)
    for t in [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")]:
        if t == me:
            continue
        b = conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone() else None
        o = conn.execute("SELECT patience FROM owners WHERE team_id=?", (t,)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone() else None
        hc = head_coach(conn, t)
        if hc and b and o and b[0] < 40 and o[0] <= 6:
            dismiss(conn, t, hc["staff_id"], day, "fire head coach")
            lines.append(f"{team_abbr(conn, t)} fired head coach {hc['name']}.")
        for role, n in ROLES:
            while len(members(conn, t, role)) < n:
                c = conn.execute(f"SELECT staff_id FROM staff WHERE team_id IS NULL AND role=? AND staff_id NOT IN "
                                 f"(SELECT staff_id FROM league_events WHERE team_id=? AND staff_id IS NOT NULL AND "
                                 f"event_type IN ('COACH_FIRED','STAFF_DISMISSED')) ORDER BY "
                                 f"{MAIN_ATTR[role]} + reputation / 2.0 DESC, staff_id LIMIT 1", (role, t)).fetchone()
                if c is None:
                    refill_market(conn)
                    c = conn.execute("SELECT staff_id FROM staff WHERE team_id IS NULL AND role=? LIMIT 1",
                                     (role,)).fetchone()
                    if c is None:
                        break
                hire(conn, t, c[0], day)
    refill_market(conn)
    return lines
