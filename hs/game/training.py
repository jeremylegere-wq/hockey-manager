"""Training (phase E, v36): what each player works on, and potential that moves.

Focus. Every player in your organisation can have a training focus: balanced (the default), offence, defence,
skating, physical, mental, or for goalies positioning or reflexes. Development each summer still moves his overall by
the same amount (age, potential, your coaches, his coachability: hs/game/world.py); a focus decides where it goes:
the focus attributes take 1.6x their share and the rest give it back, so a balanced player and a focused one improve
the same overall but in different places. A player in decline loses less in his focus attributes.

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
