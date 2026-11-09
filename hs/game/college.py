"""College hockey: programs, eligibility, recruiting, enrolment and graduation, the Hobey Baker Award and the college
free-agent market (v46; docs/COLLEGE.md).

Eligibility (NCAA Division I)
  amateurs only     no season in the NHL, AHL or ECHL and no pro contract; CHL players are eligible (since 2025-26)
  old rules         players who enrolled before 2027-28: four seasons, one fewer for each year he enrols past 21
  5-in-5            from the 2027-28 entering class (adopted June 2026): five seasons within five years; the clock
                    starts at enrolment or with the academic year after he turns 19, whichever comes first, so a player
                    who spends two years in junior after 19 enrols with three seasons left
Programs: every NCAA club has a prestige (1-100) from its talent and results (a title, the Frozen Four, the tournament),
a head coach, and a recruiting class that fills the places its seniors and early leavers open up.

Recruiting (rounds on 15 October and 1 March; a last round in the summer)
  who               players 16-20 in junior (USHL, NAHL, BCHL, the CHL, the European junior leagues) who are eligible
                    and college-bound: most USHL, NAHL and BCHL players (85%), Americans in the CHL (30%), Canadians in
                    the CHL (12%), Europeans (5%); a drafted player's NHL club can steer him (path college / junior)
  when              a commit enrols next season if he is ready (his overall within half a point of the NCAA average)
                    or will be 20, otherwise the season after
  where             the program he likes best among those that want him (his quality reaches the program's bar, it has
                    a place at his position): prestige/10 + playing time (places open at his position) + a little luck
  rate              each round 70% of next season's recruits and 35% of the year after's commit, and a program fills
                    at most 55% of its open places (a quarter for the year after); the summer round places everyone
                    left who wants to go
Summer (the start of the off-season): seniors graduate (their eligibility is used up), commits enrol (moving to their
program), and an NHL club's rights to a drafted college player run until the summer after his last college season.

The college free-agent market (when the NCAA season ends): the best undrafted players leaving college (eligibility
used up, or a strong player who turns pro early, 60%; within 0.8 of the AHL average, at most 40) can sign an entry-level deal with any club. AI clubs that need him make
offers over the next days; you can too (College Hockey > Free agents, `college offer <player> [now]`). "Now" starts the
deal this season (he can play at once; a year of it is used up), which players like. Ten days after the market opens
each player picks: playing time at his position + "now" + the club's strength + a little luck. Anyone unsigned goes
back to school (with eligibility left) or into the summer's free agency.

The Hobey Baker Award goes to the best college player when the NCAA season ends.
"""
from __future__ import annotations

import datetime
import json
import math
import random

from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

NEW_RULES_FROM = 2027
OLD_SEASONS, OLD_ENROL_AGE = 4, 21
NEW_SEASONS = 5
P_COLLEGE = {"USHL": 0.85, "NAHL": 0.85, "BCHL": 0.85, "CHL_USA": 0.30, "CHL": 0.12, "EUROPE": 0.05}
CHL = ("OHL", "WHL", "QMJHL")
READY_GAP = 0.5
ROUND_SHARE = 0.55               # a recruiting round fills at most this share of a program's open places
P_COMMIT_NEXT, P_COMMIT_LATER = 0.70, 0.35
P_EARLY_PRO = 0.60
EARLY_PRO_GAP = 0.3                  # overall within 0.3 of the AHL average: good enough to turn pro early
CFA_DAYS = 10
MARKET_GAP, MARKET_MAX = 0.8, 40     # who is a college free agent: within 0.8 of the AHL average, the best 40
CFA_MAX_AI_OFFERS = 2
POWER = ("Boston University", "University of Michigan", "University of Minnesota", "University of Denver",
         "University of North Dakota", "Boston College", "University of Wisconsin", "Michigan State University",
         "Quinnipiac University", "Western Michigan University", "Minnesota State University", "University of Maine")
COACH_FIRST = ["Mike", "Dave", "Bob", "Jeff", "Tom", "Greg", "Brian", "Scott", "Mark", "Jerry", "Nate", "Pat"]
COACH_LAST = ["Hastings", "Berenson", "Lucia", "Carvel", "York", "Quinn", "Parker", "Sanford", "Eaves", "Pecknold",
              "Montgomery", "Leaman", "Bertram", "Gwozdecky", "Umile", "Mazzoleni"]


# ---------------------------------------------------------------- tables, programs
def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS college_programs (team_id INTEGER PRIMARY KEY, prestige REAL, coach TEXT, "
                 "titles INTEGER DEFAULT 0, frozen_fours INTEGER DEFAULT 0, updated INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS college_players (player_id INTEGER PRIMARY KEY, team_id INTEGER, enrolled INTEGER, "
                 "seasons INTEGER, rules TEXT, status TEXT DEFAULT 'enrolled', left_year INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS college_commits (player_id INTEGER PRIMARY KEY, team_id INTEGER, committed TEXT, "
                 "enroll_year INTEGER, status TEXT DEFAULT 'committed')")
    conn.execute("CREATE TABLE IF NOT EXISTS college_paths (player_id INTEGER PRIMARY KEY, team_id INTEGER, path TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS college_fa (player_id INTEGER PRIMARY KEY, season INTEGER, opened TEXT, decide_by TEXT, "
                 "status TEXT DEFAULT 'open', offers TEXT DEFAULT '{}', signed_team INTEGER, reason TEXT)")


def ncaa_league(conn):
    from .world import world_meta
    return next((lid for lid, m in world_meta(conn).items() if m["kind"] == "college"), None)


def active(conn):
    return ncaa_league(conn) is not None


def programs(conn):
    lid = ncaa_league(conn)
    return [r[0] for r in conn.execute("SELECT team_id FROM teams WHERE league_id=? ORDER BY name", (lid,))] if lid else []


def _season(conn):
    from .contracts import season_year
    return season_year(conn)


def _seed(conn):
    st = get_state(conn)
    return st[1] if st else 1


def _meta(conn, abbr):
    from .world import world_meta
    return next((m for m in world_meta(conn).values() if m["abbr"] == abbr), None)


def _quality(a):
    from .world import overall
    ov = overall(a)
    return 0.6 * ov + 0.4 * min(a.get("potential") or ov, ov + 3.0)


def _roster_attrs(conn, club):
    from .world import load_attrs
    return load_attrs(conn, "p.club_id=? AND p.status<>'retired'", (club,))


def setup(conn):
    """Programs and the players already in college (once; their class is a guess from age)."""
    ensure_tables(conn)
    if not active(conn):
        return
    from .world import age_on, overall
    y = _season(conn)
    have = {r[0] for r in conn.execute("SELECT team_id FROM college_programs")}
    progs = programs(conn)
    qual = {}
    for t in progs:
        a = _roster_attrs(conn, t)
        ovs = sorted((overall(r) for r in a.values()), reverse=True)[:18]
        qual[t] = sum(ovs) / len(ovs) if ovs else 0.0
    order = sorted(progs, key=lambda t: qual[t])
    for t in progs:
        if t in have:
            continue
        rng = random.Random(f"{_seed(conn)}-program-{t}")
        name = conn.execute("SELECT name FROM teams WHERE team_id=?", (t,)).fetchone()[0]
        pct = order.index(t) / max(1, len(order) - 1)
        prestige = 30 + 50 * pct + (10 if any(name.startswith(p) for p in POWER) else 0) + rng.gauss(0, 4)
        conn.execute("INSERT INTO college_programs (team_id, prestige, coach, updated) VALUES (?,?,?,?)",
                     (t, round(max(5, min(99, prestige)), 1), f"{rng.choice(COACH_FIRST)} {rng.choice(COACH_LAST)}", y))
    register(conn)


def register(conn, year=None):
    """Give every player in an NCAA club a college record (players placed there by the world's filler or before v46)."""
    ensure_tables(conn)
    from .world import age_on
    y = _season(conn) if year is None else year
    lid = ncaa_league(conn)
    if lid is None:
        return 0
    known = {r[0] for r in conn.execute("SELECT player_id FROM college_players WHERE status='enrolled'")}
    n = 0
    for pid, club, birth in conn.execute("SELECT p.player_id, p.club_id, p.birth_date FROM players p JOIN teams t ON t.team_id=p.club_id "
                                         "WHERE t.league_id=? AND p.status<>'retired'", (lid,)).fetchall():
        if pid in known:
            continue
        age = age_on(birth, datetime.date(y, 9, 15))
        enrolled = y - max(0, min(3, age - 20))          # 19-20 a freshman, 21 a sophomore, 22 a junior, 23+ a senior
        conn.execute("INSERT OR REPLACE INTO college_players (player_id, team_id, enrolled, seasons, rules, status) VALUES (?,?,?,?,?, 'enrolled')",
                     (pid, club, enrolled, max(1, min(OLD_SEASONS, OLD_SEASONS - max(0, (age - (y - enrolled)) - OLD_ENROL_AGE))) if enrolled < NEW_RULES_FROM
                     else allowed_seasons(birth, enrolled)[0], "old" if enrolled < NEW_RULES_FROM else "5in5"))
        n += 1
    return n


# ---------------------------------------------------------------- eligibility
def clock_start(birth):
    """The academic year the 5-in-5 clock starts without enrolment: the one after his 19th birthday."""
    b = datetime.date.fromisoformat(birth)
    y = b.year + 19
    return y if (b.month, b.day) < (8, 1) else y + 1


def allowed_seasons(birth, enrol_year):
    """(seasons he may play if he enrols in enrol_year, rules)."""
    from .world import age_on
    if enrol_year < NEW_RULES_FROM:
        age = age_on(birth, datetime.date(enrol_year, 9, 15))
        return max(0, OLD_SEASONS - max(0, age - OLD_ENROL_AGE)), "old"
    start = min(enrol_year, clock_start(birth))
    return max(0, NEW_SEASONS - (enrol_year - start)), "5in5"


def _pro(conn):
    """Players who have played professionally in North America or signed a pro contract."""
    pro = {r[0] for r in conn.execute("SELECT DISTINCT player_id FROM contracts")}
    for t in ("skater_season_stats", "goalie_season_stats"):
        pro |= {r[0] for r in conn.execute(f"SELECT DISTINCT s.player_id FROM {t} s JOIN leagues l USING (league_id) WHERE "
                                           "COALESCE(l.level, 1)<=3 AND COALESCE(l.country, 'USA/CAN') IN ('USA/CAN','USA','CAN') "
                                           "AND s.gp>0")}
    return pro


def eligible(conn, pid, enrol_year, pro=None):
    pro = _pro(conn) if pro is None else pro
    if pid in pro:
        return False
    if conn.execute("SELECT 1 FROM college_players WHERE player_id=?", (pid,)).fetchone():
        return False                                     # already been to college (a transfer is not modelled)
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    return bool(b) and allowed_seasons(b[0], enrol_year)[0] >= 1


def status_of(conn, pid):
    """dict(program, enrolled, class_no, seasons, left, rules) for a player in college, or None."""
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM college_players WHERE player_id=? AND status='enrolled'", (pid,)).fetchone()
    if not r:
        return None
    y = _season(conn)
    k = y - r["enrolled"] + 1
    names = {1: "freshman", 2: "sophomore", 3: "junior", 4: "senior", 5: "fifth year"}
    return dict(program=r["team_id"], enrolled=r["enrolled"], class_no=k, class_name=names.get(k, f"year {k}"), seasons=r["seasons"],
                left=max(0, r["seasons"] - k), rules=r["rules"])


# ---------------------------------------------------------------- who wants to go
def _feeder(conn):
    """{league_id: kind key} of junior leagues that send players to college."""
    from .world import world_meta
    out = {}
    for lid, m in world_meta(conn).items():
        if m["kind"] != "junior":
            continue
        a = m["abbr"]
        out[lid] = a if a in ("USHL", "NAHL", "BCHL") else "CHL" if a in CHL else "EUROPE"
    return out


def college_bound(conn, pid, nat, feeder):
    p = conn.execute("SELECT path FROM college_paths WHERE player_id=?", (pid,)).fetchone()
    if p:
        return p[0] == "college"
    key = "CHL_USA" if feeder == "CHL" and nat == "USA" else feeder
    return random.Random(f"{_seed(conn)}-bound-{pid}").random() < P_COLLEGE.get(key, 0.05)


def recruits(conn, enrol_year, pro=None):
    """Eligible, college-bound, uncommitted junior players who could enrol in enrol_year: [(quality, row)]."""
    from .world import age_on, load_attrs
    feeders = _feeder(conn)
    if not feeders:
        return []
    pro = _pro(conn) if pro is None else pro
    committed = {r[0] for r in conn.execute("SELECT player_id FROM college_commits WHERE status IN ('committed','enrolled')")}
    been = {r[0] for r in conn.execute("SELECT player_id FROM college_players")}
    q = ",".join(map(str, feeders))
    rows = load_attrs(conn, f"p.status IN ('active','injured') AND p.team_id IS NULL AND p.club_id IN "
                            f"(SELECT team_id FROM teams WHERE league_id IN ({q}))")
    league_of = {r[0]: r[1] for r in conn.execute(f"SELECT team_id, league_id FROM teams WHERE league_id IN ({q})")}
    out = []
    for pid, r in rows.items():
        if pid in committed or pid in been or pid in pro:
            continue
        age = age_on(r["birth_date"], datetime.date(enrol_year, 9, 15))
        if not 18 <= age <= 21:
            continue
        if allowed_seasons(r["birth_date"], enrol_year)[0] < 2:
            continue
        if not college_bound(conn, pid, r["nationality"], feeders.get(league_of.get(r["club_id"]))):
            continue
        out.append((_quality(r), r))
    out.sort(key=lambda x: -x[0])
    return out


# ---------------------------------------------------------------- recruiting
def _program_state(conn, year):
    """{program: dict(prestige, bar, open {F,D,G})} for enrol_year `year`: places left when its leavers go."""
    from .world import overall
    lid = ncaa_league(conn)
    roster = _meta(conn, "NCAA")["roster"] if _meta(conn, "NCAA") else 27
    out = {}
    cp = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT player_id, enrolled, seasons FROM college_players WHERE status='enrolled'")}
    commits = {}
    for pid, t, pos in conn.execute("SELECT c.player_id, c.team_id, p.position FROM college_commits c JOIN players p USING (player_id) "
                                    "WHERE c.status='committed' AND c.enroll_year=?", (year,)):
        commits.setdefault(t, {"F": 0, "D": 0, "G": 0})
        commits[t]["G" if pos == "G" else "D" if pos == "D" else "F"] += 1
    for t, prestige in conn.execute("SELECT team_id, prestige FROM college_programs").fetchall():
        a = _roster_attrs(conn, t)
        stay = {"F": 0, "D": 0, "G": 0}
        ovs = []
        for pid, r in a.items():
            e = cp.get(pid)
            if e and (year - e[0] + 1) > e[1]:
                continue                                  # gone by then
            g = "G" if r["position"] == "G" else "D" if r["position"] == "D" else "F"
            stay[g] += 1
            ovs.append(overall(r))
        c = commits.get(t, {"F": 0, "D": 0, "G": 0})
        want = {"G": 3, "D": round(roster * 0.34), "F": roster - 3 - round(roster * 0.34)}
        open_ = {g: max(0, want[g] - stay[g] - c[g]) for g in want}
        ovs.sort()
        bar = ovs[len(ovs) // 5] - 0.8 if ovs else 0.0
        out[t] = dict(prestige=prestige, bar=bar, open=open_)
    return out


def recruit_round(conn, day, final=False):
    """Commitments for next season and the season after. Returns the number of commits."""
    ensure_tables(conn)
    if not active(conn):
        return 0
    nxt = _next_season(conn)
    pro = _pro(conn)
    rng = random.Random(f"{_seed(conn)}-recruit-{day}")
    n = 0
    years = [nxt] if final else [nxt, nxt + 1]
    from .world import age_on
    me = user_team(conn)
    for ey in years:
        st = _program_state(conn, ey)
        if not final:                                      # a program keeps places for later rounds
            share = ROUND_SHARE if ey == nxt else ROUND_SHARE / 2
            for v in st.values():
                v["open"] = {g: (math.ceil(k * share) if k else 0) for g, k in v["open"].items()}
        for qual, r in recruits(conn, ey, pro):
            pid = r["player_id"]
            age = age_on(r["birth_date"], datetime.date(ey, 9, 15))
            ncaa_mean = (_meta(conn, "NCAA") or {}).get("mean", 8.2)
            ready = qual >= ncaa_mean - READY_GAP or age >= 20
            if ey == nxt and not ready and not final:
                continue                                   # he would enrol the year after
            if ey == nxt + 1 and ready:
                continue
            p = 1.0 if final else (P_COMMIT_NEXT if ey == nxt else P_COMMIT_LATER)
            if rng.random() >= p:
                continue
            g = "G" if r["position"] == "G" else "D" if r["position"] == "D" else "F"
            best = None
            for t, s in st.items():
                if s["open"][g] <= 0 or qual < s["bar"] - (0.6 if final else 0.0):
                    continue
                u = s["prestige"] / 10.0 + min(3, s["open"][g]) * 0.6 + rng.gauss(0, 1.2)
                if best is None or u > best[0]:
                    best = (u, t)
            if best is None:
                continue
            t = best[1]
            st[t]["open"][g] -= 1
            conn.execute("INSERT OR REPLACE INTO college_commits VALUES (?,?,?,?, 'committed')", (pid, t, day, ey))
            n += 1
            holder = conn.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (pid,)).fetchone()
            imp = 2 if qual >= ncaa_mean + 1.0 else 1
            emit(conn, "RUMOUR", day, f"{player_name(conn, pid)} commits to {_short(conn, t)} for {ey}-{(ey + 1) % 100:02d}",
                 player_id=pid, team_id=holder[0] if holder else None, importance=imp, kind="college_commit", program=t)
            if holder and holder[0] == me:
                add_message(conn, day, f"{player_name(conn, pid)} commits to {_short(conn, t)}",
                            f"Our prospect {player_name(conn, pid)} has committed to {_name(conn, t)} and will enrol for "
                            f"{ey}-{(ey + 1) % 100:02d}. We keep his rights while he is in college (until the summer after his "
                            "last season there). College Hockey > Our prospects.", sender="Director of Player Development")
    return n


def _short(conn, t):
    n = conn.execute("SELECT name FROM teams WHERE team_id=?", (t,)).fetchone()
    s = n[0] if n else "?"
    for a, b in (("University of ", ""), (" University", ""), ("College of ", ""), (" College", "")):
        s = s.replace(a, b)
    return " ".join(s.split()[:3])


def _name(conn, t):
    n = conn.execute("SELECT name FROM teams WHERE team_id=?", (t,)).fetchone()
    return n[0] if n else "?"


def _state(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='season_state'").fetchone()
    return r[0] if r else "regular_season"


def _next_season(conn):
    """The season the next college year belongs to (the season row for it is created when the pre-season ends)."""
    return _season(conn) + 1


def set_path(conn, pid, path):
    """Your drafted prospect's route: college, junior (stay out of college), or none (his own choice)."""
    ensure_tables(conn)
    me = user_team(conn)
    r = conn.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (pid,)).fetchone()
    if not r or r[0] != me:
        raise ValueError("You can steer only prospects whose rights you hold.")
    if path not in ("college", "junior", "none"):
        raise ValueError("Path: college, junior or none.")
    if conn.execute("SELECT 1 FROM college_players WHERE player_id=? AND status='enrolled'", (pid,)).fetchone():
        raise ValueError("He is already in college.")
    if path == "none":
        conn.execute("DELETE FROM college_paths WHERE player_id=?", (pid,))
    else:
        conn.execute("INSERT OR REPLACE INTO college_paths VALUES (?,?,?)", (pid, me, path))
    if path == "junior":
        c = conn.execute("SELECT team_id FROM college_commits WHERE player_id=? AND status='committed'", (pid,)).fetchone()
        if c:
            conn.execute("UPDATE college_commits SET status='decommitted' WHERE player_id=?", (pid,))
            emit(conn, "RUMOUR", get_state(conn)[0], f"{player_name(conn, pid)} decommits from {_short(conn, c[0])}", player_id=pid,
                 team_id=me, importance=1, kind="college_decommit")
            return f"{player_name(conn, pid)} will stay in junior; he has withdrawn his commitment to {_short(conn, c[0])}."
        return f"{player_name(conn, pid)} will stay in junior."
    return f"{player_name(conn, pid)}: path {path}."


# ---------------------------------------------------------------- the summer
def summer(conn, day):
    """Seniors graduate, commits enrol, a last recruiting round, and college picks' rights run with their eligibility.
    Runs once a summer (at the start of the off-season's world moves). Returns message lines."""
    ensure_tables(conn)
    if not active(conn):
        return []
    y = _season(conn) + 1                                 # the coming season
    key = f"college_summer_{y}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return []
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    setup(conn)
    register(conn, y - 1)
    _update_prestige(conn, y - 1)
    lid = ncaa_league(conn)
    grads = left = 0
    for pid, t, enrolled, seasons in conn.execute("SELECT player_id, team_id, enrolled, seasons FROM college_players WHERE status='enrolled'").fetchall():
        p = conn.execute("SELECT p.club_id, t.league_id, p.status FROM players p LEFT JOIN teams t ON t.team_id=p.club_id WHERE p.player_id=?",
                         (pid,)).fetchone()
        if p is None or p[2] == "retired":
            conn.execute("UPDATE college_players SET status='left', left_year=? WHERE player_id=?", (y - 1, pid))
            continue
        if p[1] != lid:                                   # signed pro or moved on during the year
            conn.execute("UPDATE college_players SET status='left', left_year=? WHERE player_id=?", (y - 1, pid))
            left += 1
            continue
        if y - enrolled + 1 > seasons:                    # eligibility used up
            conn.execute("UPDATE college_players SET status='graduated', left_year=? WHERE player_id=?", (y - 1, pid))
            conn.execute("UPDATE players SET club_id=NULL WHERE player_id=? AND team_id IS NULL", (pid,))
            conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, detail) VALUES (?, 'graduate', ?, ?, ?)",
                         (day, pid, t, f"graduated from {_short(conn, t)}"))
            grads += 1
    # a last round for the coming season, then enrolment
    recruit_round(conn, day, final=True)
    pro = _pro(conn)
    enrolled = void = 0
    me = user_team(conn)
    for pid, t in conn.execute("SELECT player_id, team_id FROM college_commits WHERE status='committed' AND enroll_year=?", (y,)).fetchall():
        if pid in pro or not eligible(conn, pid, y, pro):
            conn.execute("UPDATE college_commits SET status='void' WHERE player_id=?", (pid,))
            void += 1
            continue
        b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        seasons, rules = allowed_seasons(b, y)
        frm = conn.execute("SELECT club_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (t, pid))
        conn.execute("INSERT OR REPLACE INTO college_players (player_id, team_id, enrolled, seasons, rules, status) VALUES (?,?,?,?,?, 'enrolled')",
                     (pid, t, y, seasons, rules))
        conn.execute("UPDATE college_commits SET status='enrolled' WHERE player_id=?", (pid,))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES (?, 'enrol', ?, ?, ?, ?)",
                     (day, pid, frm, t, f"enrols at {_short(conn, t)} ({seasons} seasons of eligibility)"))
        # an NHL club's rights to a college player run until the summer after his last college season
        conn.execute("UPDATE draft_rights SET expires_year=MAX(COALESCE(expires_year, 0), ?) WHERE player_id=?", (y + seasons, pid))
        enrolled += 1
    lines = [f"College: {grads} graduated, {left} left early, {enrolled} enrolled" + (f", {void} commitments void" if void else "") + "."]
    mine = [r[0] for r in conn.execute("SELECT c.player_id FROM college_commits c JOIN draft_rights d USING (player_id) WHERE "
                                       "c.status='enrolled' AND c.enroll_year=? AND d.team_id=?", (y, me))] if me else []
    if mine:
        add_message(conn, day, "Our prospects in college", "Enrolling this season:\n" + "\n".join(
            f"- {player_name(conn, p)} ({_name(conn, conn.execute('SELECT team_id FROM college_players WHERE player_id=?', (p,)).fetchone()[0])})"
            for p in mine) + "\nWe hold their rights until the summer after their last college season.", sender="Director of Player Development")
    return lines


def extend_rights(conn):
    """An NHL club's rights to a drafted college player run until the summer after his last college season."""
    ensure_tables(conn)
    conn.execute("UPDATE draft_rights SET expires_year=(SELECT c.enrolled + c.seasons FROM college_players c WHERE c.player_id="
                 "draft_rights.player_id) WHERE player_id IN (SELECT player_id FROM college_players WHERE status='enrolled') AND "
                 "COALESCE(expires_year, 0) < (SELECT c.enrolled + c.seasons FROM college_players c WHERE c.player_id=draft_rights.player_id)")


def no_college(conn):
    """Players the world must not place in a college club (pros, graduates, anyone who has left college)."""
    ensure_tables(conn)
    return _pro(conn) | {r[0] for r in conn.execute("SELECT player_id FROM college_players WHERE status<>'enrolled'")}


def _update_prestige(conn, season):
    """Prestige drifts towards the program's talent and results."""
    from .world import overall
    lid = ncaa_league(conn)
    if lid is None:
        return
    progs = [r[0] for r in conn.execute("SELECT team_id FROM college_programs WHERE COALESCE(updated, 0)<?", (season + 1,))]
    if not progs:
        return
    qual = {}
    for t in programs(conn):
        a = _roster_attrs(conn, t)
        ovs = sorted((overall(r) for r in a.values()), reverse=True)[:18]
        qual[t] = sum(ovs) / len(ovs) if ovs else 0.0
    order = sorted(qual, key=qual.get)
    champ = conn.execute("SELECT champion FROM lg_seasons WHERE league_id=? AND season=?", (lid, season)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_seasons'").fetchone() else None
    ff = set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_series'").fetchone():
        cols = {r[1] for r in conn.execute("PRAGMA table_info(lg_series)")}
        if {"league_id", "season", "round", "a", "b"} <= cols:
            mx = conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (lid, season)).fetchone()[0]
            if mx:
                for a, b in conn.execute("SELECT a, b FROM lg_series WHERE league_id=? AND season=? AND round>=?", (lid, season, mx - 1)):
                    ff |= {a, b}
    for t in progs:
        if t not in qual:
            continue
        pct = order.index(t) / max(1, len(order) - 1)
        target = 30 + 55 * pct
        p = conn.execute("SELECT prestige FROM college_programs WHERE team_id=?", (t,)).fetchone()[0]
        new = 0.8 * p + 0.2 * target + (8 if champ and champ[0] == t else 0) + (3 if t in ff else 0)
        conn.execute("UPDATE college_programs SET prestige=?, updated=?, titles=titles+?, frozen_fours=frozen_fours+? WHERE team_id=?",
                     (round(max(5, min(99, new)), 1), season + 1, int(bool(champ and champ[0] == t)), int(t in ff), t))


# ---------------------------------------------------------------- spring: the Hobey Baker and college free agents
def daily(conn, day, seed=0):
    """Recruiting rounds, and the spring market once the NCAA season is over."""
    ensure_tables(conn)
    if not active(conn) or _state(conn) not in ("regular_season", "playoffs", "finished"):
        return []
    out = []
    md = day[5:]
    y = _season(conn)
    for mmdd, tag in (("10-15", "fall"), ("03-01", "spring")):
        if md >= mmdd and (tag == "fall" or md < "08-01"):
            key = f"recruit_{y}_{tag}"
            if not conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
                conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
                setup(conn)
                out.append(f"College recruiting: {recruit_round(conn, day)} commitments.")
    lid = ncaa_league(conn)
    done = conn.execute("SELECT finished FROM lg_seasons WHERE league_id=? AND season=?", (lid, y)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_seasons'").fetchone() else None
    if (done and done[0]) or md >= "04-15" and md < "08-01":
        key = f"cfa_open_{y}"
        if not conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
            conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
            setup(conn)
            out += hobey(conn, day, y)
            out += open_market(conn, day, y)
    out += _ai_offers(conn, day, seed)
    out += decide(conn, day)
    return out


def hobey(conn, day, y):
    from .history import _award, ensure_tables as ht
    ht(conn)
    lid = ncaa_league(conn)
    rows = conn.execute("SELECT s.player_id, s.team_id, SUM(s.gp) gp, SUM(s.g) g, SUM(s.a) a FROM skater_season_stats s WHERE "
                        "s.league_id=? AND s.season_start_year=? AND s.split='RS' GROUP BY s.player_id HAVING SUM(s.gp)>=20", (lid, y)).fetchall()
    if not rows:
        return []
    champ = conn.execute("SELECT champion FROM lg_seasons WHERE league_id=? AND season=?", (lid, y)).fetchone()
    prest = {r[0]: r[1] for r in conn.execute("SELECT team_id, prestige FROM college_programs")}
    best = max(rows, key=lambda r: (r["g"] + r["a"]) / r["gp"] * (1 + 0.002 * prest.get(r["team_id"], 50))
               * (1.05 if champ and champ[0] == r["team_id"] else 1.0))
    if conn.execute("SELECT 1 FROM awards WHERE season_start_year=? AND award='hobey'", (y,)).fetchone():
        return []
    _award(conn, y, "hobey", day, best["player_id"], best["team_id"],
           detail=f"{best['g'] + best['a']} points in {best['gp']} games for {_short(conn, best['team_id'])}")
    return [f"Hobey Baker Award: {player_name(conn, best['player_id'])} ({_short(conn, best['team_id'])})."]


def open_market(conn, day, y):
    """The NCAA season is over: undrafted players leaving college become free agents for an entry-level deal."""
    from .world import load_attrs, overall
    lid = ncaa_league(conn)
    ahl = (_meta(conn, "AHL") or {}).get("mean", 9.2)
    rights = {r[0] for r in conn.execute("SELECT player_id FROM draft_rights")}
    rows = load_attrs(conn, "p.status<>'retired' AND p.team_id IS NULL AND p.club_id IN (SELECT team_id FROM teams WHERE league_id=?)", (lid,))
    cp = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT player_id, enrolled, seasons FROM college_players WHERE status='enrolled'")}
    rng = random.Random(f"{_seed(conn)}-cfa-{y}")
    decide_by = (datetime.date.fromisoformat(day) + datetime.timedelta(days=CFA_DAYS)).isoformat()
    n = 0
    names = []
    for pid, r in sorted(rows.items(), key=lambda kv: -overall(kv[1])):
        if pid in rights or conn.execute("SELECT 1 FROM college_fa WHERE player_id=?", (pid,)).fetchone():
            continue
        e = cp.get(pid)
        last = e is not None and (y - e[0] + 1) >= e[1]
        ov = overall(r)
        if ov < ahl - MARKET_GAP or n >= MARKET_MAX:
            continue                                       # not a pro prospect (he graduates into the summer's market)
        early = not last and ov >= ahl - EARLY_PRO_GAP and rng.random() < P_EARLY_PRO
        if not (last or early):
            continue
        conn.execute("INSERT INTO college_fa (player_id, season, opened, decide_by, status, offers, reason) VALUES (?,?,?,?, 'open', '{}', ?)",
                     (pid, y, day, decide_by, "senior" if last else "turning pro early"))
        n += 1
        if len(names) < 8:
            names.append(f"{player_name(conn, pid)} ({r['position']}, {_short(conn, r['club_id'])}{'' if last else ', leaving early'})")
    if n and user_team(conn):
        add_message(conn, day, "College free agents",
                    f"The college season is over and {n} undrafted players are leaving school to turn pro. The best:\n"
                    + "\n".join(f"- {x}" for x in names) + f"\nThey decide on {decide_by}. Offer an entry-level deal on College Hockey "
                    "> Free agents (or `college offer <player> [now]`); starting the deal now lets him play for us this season.",
                    sender="Director of Amateur Scouting")
    return [f"College free agents: {n} on the market until {decide_by}."] if n else []


def _offers(conn, pid):
    r = conn.execute("SELECT offers FROM college_fa WHERE player_id=?", (pid,)).fetchone()
    return json.loads(r[0] or "{}") if r else {}


def offer(conn, pid, team, now=False, day=None):
    """Make (or update) an entry-level offer. now: the deal starts this season."""
    ensure_tables(conn)
    r = conn.execute("SELECT status, decide_by FROM college_fa WHERE player_id=?", (pid,)).fetchone()
    if not r or r[0] != "open":
        raise ValueError("He is not on the college free-agent market.")
    if now and _state(conn) not in ("regular_season", "playoffs"):
        raise ValueError("The season is over: the deal starts next season.")
    from . import contracts as K
    K.check_contract_limit(conn, team, K.signing_year(conn) if not now else _season(conn))
    o = _offers(conn, pid)
    o[str(team)] = dict(now=bool(now), day=day or get_state(conn)[0])
    conn.execute("UPDATE college_fa SET offers=? WHERE player_id=?", (json.dumps(o), pid))
    return f"Offer made to {player_name(conn, pid)}" + (" (starting this season)" if now else "") + f"; he decides by {r[1]}."


def withdraw(conn, pid, team):
    o = _offers(conn, pid)
    o.pop(str(team), None)
    conn.execute("UPDATE college_fa SET offers=? WHERE player_id=?", (json.dumps(o), pid))


def _depth_ahead(conn, team, pid):
    """How many on the club's NHL roster at his position are better than him."""
    from .roster import group, player_value
    from .valuation import overall_of_value
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = group(pos)
    me = overall_of_value(player_value(conn, pid))
    from . import roster as R
    return sum(1 for r in R.roster(conn, team) if group(r["position"]) == g and overall_of_value(player_value(conn, r["player_id"])) > me)


def _ai_offers(conn, day, seed):
    """AI clubs make their offers the day after the market opens (each to at most two players it needs)."""
    rows = conn.execute("SELECT player_id, opened FROM college_fa WHERE status='open' AND opened<?", (day,)).fetchall()
    if not rows:
        return []
    key = f"cfa_ai_{rows[0][1]}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return []
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    from ..schema import top_league_sql
    from .world import load_attrs, overall
    me = user_team(conn)
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}") if r[0] != me]
    attrs = load_attrs(conn, "p.player_id IN (SELECT player_id FROM college_fa WHERE status='open')")
    rng = random.Random(f"{seed}-cfa-ai-{day}")
    made = {t: 0 for t in teams}
    from . import contracts as K
    from . import roster as R
    n = 0
    for pid, _ in sorted(rows, key=lambda r: -overall(attrs[r[0]]) if r[0] in attrs else 0):
        if pid not in attrs:
            continue
        pos = attrs[pid]["position"]
        cands = []
        for t in teams:
            if made[t] >= CFA_MAX_AI_OFFERS:
                continue
            ahead = _depth_ahead(conn, t, pid)
            need = {"F": 12, "D": 7, "G": 2}[R.group(pos)]
            if ahead >= need + 2:
                continue
            cands.append((rng.random() + (need + 2 - ahead) * 0.2, t))
        k = 1 + int(overall(attrs[pid]) >= (_meta(conn, "AHL") or {}).get("mean", 9.2)) * 3
        o = _offers(conn, pid)
        for _, t in sorted(cands, reverse=True)[:k]:
            try:
                K.check_contract_limit(conn, t, K.signing_year(conn))
            except Exception:
                continue
            o[str(t)] = dict(now=_state(conn) == "regular_season" and ahead_ok(conn, t, pid), day=day)
            made[t] += 1
            n += 1
        conn.execute("UPDATE college_fa SET offers=? WHERE player_id=?", (json.dumps(o), pid))
    return [f"College free agents: {n} offers from NHL clubs."] if n else []


def ahead_ok(conn, t, pid):
    return _depth_ahead(conn, t, pid) <= 8


def decide(conn, day):
    """Players whose decision day has come pick a club (or go back to school / into the summer's free agency)."""
    rows = conn.execute("SELECT * FROM college_fa WHERE status='open' AND decide_by<=?", (day,)).fetchall()
    out = []
    me = user_team(conn)
    for r in rows:
        pid = r["player_id"]
        o = json.loads(r["offers"] or "{}")
        rng = random.Random(f"{_seed(conn)}-cfa-pick-{pid}")
        best = None
        for t, x in o.items():
            t = int(t)
            ahead = _depth_ahead(conn, t, pid)
            strength = conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone() if \
                conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone() else None
            u = -0.25 * ahead + (1.0 if x.get("now") and _state(conn) == "regular_season" else 0.0) + rng.gauss(0, 0.6)
            if best is None or u > best[0]:
                best = (u, t, bool(x.get("now")))
        if best is None:
            st = status_of(conn, pid)
            back = st and st["left"] > 0 and r["reason"] != "senior"
            conn.execute("UPDATE college_fa SET status=? WHERE player_id=?", ("returned" if back else "unsigned", pid))
            continue
        _, t, now = best
        try:
            _sign(conn, pid, t, now, day)
        except Exception as e:                               # a club over its contract limit since: next best
            conn.execute("UPDATE college_fa SET status='unsigned', reason=? WHERE player_id=?", (str(e)[:120], pid))
            continue
        conn.execute("UPDATE college_fa SET status='signed', signed_team=? WHERE player_id=?", (t, pid))
        out.append(f"{player_name(conn, pid)} signs with {team_abbr(conn, t)}")
        if me and str(me) in o:
            add_message(conn, day, f"College free agent: {player_name(conn, pid)}",
                        f"{player_name(conn, pid)} has " + ("signed with us" if t == me else f"chosen {team_abbr(conn, t)}") + ".",
                        sender="Director of Amateur Scouting")
    return out


def _sign(conn, pid, team, now, day):
    from . import contracts as K
    from . import elc as E
    from .draft import elc_terms
    from .roster import affiliate, limits, roster
    year = _season(conn) if now else K.signing_year(conn)
    years, aav = elc_terms(conn, pid, 60, year)
    K.sign_contract(conn, pid, team, years, aav, day, start_year=year, kind="entry_level", resign=False, check=False, limit=True,
                    detail="entry-level contract (college free agent)")
    mx = limits(conn)[1]
    on_roster = now and len(roster(conn, team)) < mx
    conn.execute("UPDATE players SET team_id=?, status=?, club_id=? WHERE player_id=?",
                 (team, "active" if on_roster else "prospect", team if on_roster else affiliate(conn, team), pid))
    conn.execute("UPDATE college_players SET status='left', left_year=? WHERE player_id=?", (_season(conn), pid))
    bonus, perf, lev = E.negotiate(conn, pid, 60, aav, years)
    E.record(conn, pid, year, bonus, perf, None)
    emit(conn, "PLAYER_SIGNED", day, f"{team_abbr(conn, team)} sign college free agent {player_name(conn, pid)}"
         + (" (he joins the club now)" if on_roster else ""), team_id=team, player_id=pid, importance=2, kind="college_fa", aav=aav, years=years)


# ---------------------------------------------------------------- the screen
def view(conn, program=None):
    ensure_tables(conn)
    if not active(conn):
        return dict(active=False)
    setup(conn)
    from .world import load_attrs, overall
    me = user_team(conn)
    y = _season(conn)
    nxt = _next_season(conn)
    lid = ncaa_league(conn)
    progs = []
    counts = {r[0]: r[1] for r in conn.execute("SELECT club_id, COUNT(*) FROM players WHERE club_id IN (SELECT team_id FROM teams WHERE "
                                               "league_id=?) AND status<>'retired' GROUP BY club_id", (lid,))}
    drafted = {r[0]: r[1] for r in conn.execute("SELECT p.club_id, COUNT(*) FROM draft_rights d JOIN players p USING (player_id) WHERE "
                                                "p.club_id IN (SELECT team_id FROM teams WHERE league_id=?) GROUP BY p.club_id", (lid,))}
    commits = {r[0]: r[1] for r in conn.execute("SELECT team_id, COUNT(*) FROM college_commits WHERE status='committed' GROUP BY team_id")}
    for r in conn.execute("SELECT p.*, t.name, t.conference, t.division FROM college_programs p JOIN teams t USING (team_id) ORDER BY p.prestige DESC"):
        progs.append(dict(team_id=r["team_id"], name=r["name"], short=_short(conn, r["team_id"]), prestige=r["prestige"], coach=r["coach"],
                          titles=r["titles"], frozen_fours=r["frozen_fours"], players=counts.get(r["team_id"], 0),
                          nhl_picks=drafted.get(r["team_id"], 0), commits=commits.get(r["team_id"], 0),
                          conference=r["division"] or r["conference"] or ""))
    out = dict(active=True, season=y, next=nxt, programs=progs, me=me, rules=dict(new_from=NEW_RULES_FROM))
    # the recruiting board: the best uncommitted recruits and the latest commitments
    board = []
    for q, r in recruits(conn, nxt)[:40]:
        holder = conn.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (r["player_id"],)).fetchone()
        board.append(dict(player_id=r["player_id"], name=player_name(conn, r["player_id"]), pos=r["position"], nat=r["nationality"],
                          club=_short(conn, r["club_id"]) if r["club_id"] else "", quality=round(q, 2),
                          rights=team_abbr(conn, holder[0]) if holder else ""))
    out["board"] = board
    out["commits"] = [dict(player_id=r[0], name=player_name(conn, r[0]), program=_short(conn, r[1]), program_id=r[1], day=r[2], year=r[3],
                           pos=r[4], rights=team_abbr(conn, r[5]) if r[5] else "")
                      for r in conn.execute("SELECT c.player_id, c.team_id, c.committed, c.enroll_year, p.position, d.team_id FROM college_commits c "
                                            "JOIN players p USING (player_id) LEFT JOIN draft_rights d USING (player_id) WHERE c.status='committed' "
                                            "ORDER BY c.committed DESC, c.player_id LIMIT 60")]
    # your prospects: in college, committed, or who could go
    mine = []
    if me:
        for r in conn.execute("SELECT d.player_id, d.expires_year, d.overall_pick, d.draft_year, p.position, p.club_id FROM draft_rights d "
                              "JOIN players p USING (player_id) WHERE d.team_id=? ORDER BY d.draft_year DESC, d.overall_pick", (me,)).fetchall():
            pid = r[0]
            st = status_of(conn, pid)
            c = conn.execute("SELECT team_id, enroll_year FROM college_commits WHERE player_id=? AND status='committed'", (pid,)).fetchone()
            path = conn.execute("SELECT path FROM college_paths WHERE player_id=?", (pid,)).fetchone()
            mine.append(dict(player_id=pid, name=player_name(conn, pid), pos=r[4], pick=r[2], draft_year=r[3], expires=r[1],
                             where=_short(conn, r[5]) if r[5] else "unattached",
                             college=st and dict(program=_short(conn, st["program"]), class_name=st["class_name"], left=st["left"], rules=st["rules"]),
                             commit=c and dict(program=_short(conn, c[0]), year=c[1]), path=path[0] if path else None))
    out["mine"] = mine
    # the free-agent market
    fa = []
    attrs = load_attrs(conn, "p.player_id IN (SELECT player_id FROM college_fa WHERE season=?)", (y,))
    for r in conn.execute("SELECT * FROM college_fa WHERE season=? ORDER BY status='open' DESC, player_id", (y,)).fetchall():
        a = attrs.get(r["player_id"])
        o = json.loads(r["offers"] or "{}")
        fa.append(dict(player_id=r["player_id"], name=player_name(conn, r["player_id"]), pos=a["position"] if a else "",
                       overall=round(overall(a), 2) if a else None, reason=r["reason"], decide_by=r["decide_by"], status=r["status"],
                       offers=len(o), mine=str(me) in o, mine_now=bool(o.get(str(me), {}).get("now")),
                       signed=team_abbr(conn, r["signed_team"]) if r["signed_team"] else ""))
    fa.sort(key=lambda x: (x["status"] != "open", -(x["overall"] or 0)))
    out["fa"] = fa
    out["can_now"] = _state(conn) in ("regular_season", "playoffs")
    hob = conn.execute("SELECT season_start_year, player_id, detail FROM awards WHERE award='hobey' ORDER BY season_start_year DESC LIMIT 10").fetchall() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='awards'").fetchone() else []
    out["hobey"] = [dict(season=h[0], player_id=h[1], name=player_name(conn, h[1]), detail=h[2]) for h in hob]
    if program:
        t = int(program)
        a = _roster_attrs(conn, t)
        rows = []
        for pid, r in a.items():
            st = status_of(conn, pid)
            holder = conn.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (pid,)).fetchone()
            rows.append(dict(player_id=pid, name=player_name(conn, pid), pos=r["position"], overall=round(overall(r), 2),
                             class_name=st["class_name"] if st else "", left=st["left"] if st else None, rights=team_abbr(conn, holder[0]) if holder else ""))
        rows.sort(key=lambda x: ("FDG".index("G" if x["pos"] == "G" else "D" if x["pos"] == "D" else "F"), -x["overall"]))
        p = next((x for x in progs if x["team_id"] == t), None)
        out["program"] = dict(info=p, roster=rows, commits=[dict(player_id=r[0], name=player_name(conn, r[0]), pos=r[1], year=r[2]) for r in conn.execute(
            "SELECT c.player_id, p.position, c.enroll_year FROM college_commits c JOIN players p USING (player_id) WHERE c.team_id=? AND c.status='committed' "
            "ORDER BY c.enroll_year, c.player_id", (t,))])
    return out
