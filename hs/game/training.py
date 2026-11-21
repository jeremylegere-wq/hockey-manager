"""Training (phase E, v36): what each player works on, and potential that moves.

Focus. Every player in your organisation can have a training focus: balanced (the default), offence, defence,
skating, physical, mental, or for goalies positioning or reflexes. Development each summer still moves his overall by
the same amount (age, potential, your coaches, his coachability: hs/game/world.py); a focus decides where it goes:
the focus attributes take 1.6x their share and the rest give it back, so a balanced player and a focused one improve
the same overall but in different places. A player in decline loses less in his focus attributes.

Coaching points by category (v0.62, issue #14). Each club's staff gives it points (1-20, 10 is average) in every
focus category: offence from the best assistant coach and the head coach, defence from the other assistant and the
head coach, skating and physical from the development coach, mental from the head coach's communication and
leadership, positioning and reflexes from the goaltending coach. A focus takes 1.6x its share of a gain at 10 points,
from 1.4x at 5 or less up to 1.8x at 15 or more.

Goalie training slots (v0.62, issue #14). The goaltending coach works one-on-one with a few goalies in the
organisation: two, three with a coaching rating of 14, four with 18. A goalie 24 or younger in a slot develops faster
by his coach's rating (about x1.02 at 6, x1.06 at 10, x1.15 at 19 or more); one who needs a slot and has none develops 3% slower.
You choose who has the slots (Development > Goalie slots, `goalieslot add|remove <player>`); until you do, and at AI
clubs, they go to the youngest goalies with the highest ceilings.

Variable potential. Each summer, a player 24 or younger has his ceiling moved a little (sd 0.2 of a rating point); one
prospect in 25 is a wild card whose ceiling can jump or collapse (sd 0.7). The average stays where it was.
"""
from __future__ import annotations

import hashlib
import random

FOCUS = {
    "balanced": (),
    "offence": ("offensive_awareness", "shot_accuracy", "shot_power", "passing", "puck_control", "net_presence"),
    "defence": ("positioning", "defensive_awareness", "checking", "stick_checking", "shot_blocking"),
    "skating": ("speed", "acceleration", "agility", "balance", "endurance"),
    "physical": ("strength", "hitting", "toughness", "checking", "balance"),
    "mental": ("composure", "determination", "teamwork", "professionalism", "mental_toughness"),
    "positioning": ("goalie_positioning", "rebound_control", "low_shot_save", "recovery"),
    "reflexes": ("reflexes", "glove", "blocker", "poke_check"),
}
GOALIE_FOCUS = ("balanced", "positioning", "reflexes", "mental")
SKATER_FOCUS = ("balanced", "offence", "defence", "skating", "physical", "mental")
BOOST = 1.6
WILD_SHARE = 0.04
DRIFT_SD, WILD_SD = 0.2, 0.7


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS training (player_id INTEGER PRIMARY KEY, focus TEXT)")


def focus_of(conn, pid):
    ensure_table(conn)
    r = conn.execute("SELECT focus FROM training WHERE player_id=?", (pid,)).fetchone()
    return r[0] if r else "balanced"


def all_focus(conn):
    ensure_table(conn)
    return {r[0]: r[1] for r in conn.execute("SELECT player_id, focus FROM training")}


def set_focus(conn, team, pid, focus):
    ensure_table(conn)
    p = conn.execute("SELECT position, team_id FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] != team:
        raise ValueError("He is not in your organisation.")
    ok = GOALIE_FOCUS if p["position"] == "G" else SKATER_FOCUS
    if focus not in ok:
        raise ValueError("Focus: " + ", ".join(ok) + ".")
    if focus == "balanced":
        conn.execute("DELETE FROM training WHERE player_id=?", (pid,))
    else:
        conn.execute("INSERT OR REPLACE INTO training VALUES (?,?)", (pid, focus))


# ---------------------------------------------------------------- v0.62 (#14): coaching points and goalie slots
CATEGORY_OF = {"offence": "offence", "defence": "defence", "skating": "skating", "physical": "physical", "mental": "mental",
               "positioning": "positioning", "reflexes": "reflexes"}
BOOST_RANGE = (1.4, 1.8)
SLOT_AGE = 24


def _staff(conn, team, role):
    if not team or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return []
    return conn.execute("SELECT * FROM staff WHERE team_id=? AND role=? ORDER BY coaching DESC, staff_id", (team, role)).fetchall()


def category_points(conn, team):
    """{category: points 1-20} from the club's staff (10 when a post is empty)."""
    hc = _staff(conn, team, "HC")
    ac = _staff(conn, team, "AC")
    dev = _staff(conn, team, "DEV")
    gc = _staff(conn, team, "GC")
    h = hc[0]["coaching"] if hc else 10.0
    a1 = ac[0]["coaching"] if ac else 10.0
    a2 = ac[1]["coaching"] if len(ac) > 1 else a1
    d = dev[0]["development"] if dev else 10.0
    g = gc[0]["coaching"] if gc else 10.0
    m = (hc[0]["communication"] + hc[0]["leadership"]) / 2 if hc else 10.0
    pts = dict(offence=0.6 * a1 + 0.4 * h, defence=0.6 * a2 + 0.4 * h, skating=d, physical=d, mental=m,
               positioning=g, reflexes=g)
    return {k: round(max(1.0, min(20.0, v)), 1) for k, v in pts.items()}


def boost(conn, team, focus):
    """How much more of a gain the focus attributes take: 1.6 at 10 points, 1.4-1.8 across the range."""
    if not focus or focus == "balanced" or not team:
        return 1.6
    pts = category_points(conn, team).get(CATEGORY_OF.get(focus, ""), 10.0)
    return round(max(BOOST_RANGE[0], min(BOOST_RANGE[1], 1.6 + 0.04 * (pts - 10))), 3)


def ensure_slots(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS goalie_slots (team_id INTEGER, player_id INTEGER PRIMARY KEY)")


def slot_count(conn, team):
    gc = _staff(conn, team, "GC")
    c = gc[0]["coaching"] if gc else 10
    return 2 + (c >= 14) + (c >= 18)


def _org_goalies(conn, team):
    return conn.execute("SELECT p.player_id, p.birth_date, COALESCE(d.potential, 0) pot FROM players p LEFT JOIN player_dev d "
                        "USING (player_id) WHERE p.team_id=? AND p.position='G' AND p.status IN ('active','injured','prospect')",
                        (team,)).fetchall()


def goalie_slots(conn, team):
    """The goalies in the goaltending coach's slots: the ones chosen, then (for open slots) the youngest with the
    highest ceilings."""
    ensure_slots(conn)
    n = slot_count(conn, team)
    org = {r[0]: r for r in _org_goalies(conn, team)}
    chosen = [r[0] for r in conn.execute("SELECT player_id FROM goalie_slots WHERE team_id=? ORDER BY rowid", (team,)) if r[0] in org][:n]
    rest = sorted((r for p, r in org.items() if p not in chosen), key=lambda r: (r[1] or "", r[2] or 0),
                  reverse=True)                                           # youngest first, then the higher ceiling
    auto = [r[0] for r in rest][:max(0, n - len(chosen))]
    return chosen, auto


def set_goalie_slot(conn, team, pid, on=True):
    ensure_slots(conn)
    p = conn.execute("SELECT position, team_id FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] != team or p["position"] != "G":
        raise ValueError("He is not a goalie in your organisation.")
    if not on:
        conn.execute("DELETE FROM goalie_slots WHERE player_id=?", (pid,))
        return
    chosen, _ = goalie_slots(conn, team)
    if pid in chosen:
        return
    if len(chosen) >= slot_count(conn, team):
        raise ValueError(f"Your goaltending coach has {slot_count(conn, team)} slots and they are all taken: free one first.")
    conn.execute("INSERT OR REPLACE INTO goalie_slots VALUES (?,?)", (team, pid))


def goalie_slot_factor(conn, team, pid):
    """Development factor for a young goalie from the goaltending coach's slots."""
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    if b is None or not b[0]:
        return 1.0
    from . import contracts as K
    if K.season_year(conn) - int(b[0][:4]) > SLOT_AGE:
        return 1.0
    chosen, auto = goalie_slots(conn, team)
    if pid not in chosen and pid not in auto:
        return 0.97
    gc = _staff(conn, team, "GC")
    c = gc[0]["coaching"] if gc else 10
    return round(max(1.0, min(1.15, 1.06 + 0.0107 * (c - 10))), 3)


def is_wild(pid):
    return int(hashlib.md5(f"wild-{pid}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < WILD_SHARE


def drift_potential(conn, year, seed):
    """Summer: ceilings of players 24 and under move a little (wild cards a lot). Returns [(pid, change)] of the big moves."""
    import datetime
    on = datetime.date(year + 1, 9, 15)
    big = []
    rows = conn.execute("SELECT d.player_id, d.potential, p.birth_date FROM player_dev d JOIN players p USING (player_id) "
                        "WHERE p.status<>'retired' AND p.birth_date>?", (f"{on.year - 25}-09-15",)).fetchall()
    upd = []
    for pid, pot, birth in rows:
        rng = random.Random(f"{seed}-{year}-potential-{pid}")
        d = rng.gauss(0, WILD_SD if is_wild(pid) else DRIFT_SD)
        upd.append((round(max(3.0, pot + d), 3), pid))
        if abs(d) >= 1.0:
            big.append((pid, d))
    conn.executemany("UPDATE player_dev SET potential=? WHERE player_id=?", upd)
    return big
