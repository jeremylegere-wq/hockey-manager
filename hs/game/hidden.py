"""Hidden attributes and special abilities (phase D, v35).

Seven attributes nobody sees directly, 1-20 like the rest, generated once per player (stable, from the player's id)
and centred on 10.5 so that across the league they never move the totals the engine was calibrated to:

  consistency       how much his game swings from night to night: each game his offence is shifted by a random
                    amount, sd 0.30 for the least consistent down to 0.06 for the most (mean zero)
  big_games         playoff finishing: +-0.10 sd at the extremes, playoffs only
  injury_proneness  injury risk x (1 + 0.04 x (rating - 10.5)): x0.62 at 1, x1.38 at 20
  temperament       who takes the penalties: weight x (1 + 0.06 x (10.5 - rating)); the hot-headed take more
  sportsmanship     with temperament and ego, decides who clashes in the room (hs/game/harmony.py)
  coachability      young players' development x (0.95 + 0.01 x rating) (x0.96-x1.15... centred: about x1.0 at 10)
  greed             contract asks x (1 + 0.006 x (rating - 10)): +-6%

Your scouts read them roughly: the player profile shows what your scouts say (a phrase, never the number) when an
attribute is far from average, and they are surer about your own players.

Special abilities are badges read from the ratings and the hidden attributes: big hitter, iron man, playoff
performer, sniper, magician (puck skills), wall (shot blocker), workhorse, clutch, malcontent, homebody...
Display only, apart from what the underlying attributes already do.
"""
from __future__ import annotations

import hashlib
import random

HIDDEN = ("consistency", "big_games", "injury_proneness", "temperament", "sportsmanship", "coachability", "greed")
CENTRE = 10.5


def ensure_table(conn):
    conn.execute(f"CREATE TABLE IF NOT EXISTS hidden (player_id INTEGER PRIMARY KEY, {', '.join(h + ' INTEGER' for h in HIDDEN)})")


def _gen(pid):
    rng = random.Random(int(hashlib.md5(f"hidden-{pid}".encode()).hexdigest()[:12], 16))
    return {h: max(1, min(20, round(rng.gauss(CENTRE, 3.2)))) for h in HIDDEN}


def fill(conn):
    """Make the hidden attributes for every player who has none (cheap: one query, one insert batch)."""
    ensure_table(conn)
    missing = [r[0] for r in conn.execute("SELECT player_id FROM players WHERE player_id NOT IN (SELECT player_id FROM hidden)")]
    if missing:
        rows = [(pid, *[_gen(pid)[h] for h in HIDDEN]) for pid in missing]
        conn.executemany(f"INSERT INTO hidden VALUES (?, {', '.join('?' * len(HIDDEN))})", rows)


def of(conn, pid):
    ensure_table(conn)
    r = conn.execute("SELECT * FROM hidden WHERE player_id=?", (pid,)).fetchone()
    if r is None:
        g = _gen(pid)
        conn.execute(f"INSERT OR IGNORE INTO hidden VALUES (?, {', '.join('?' * len(HIDDEN))})", (pid, *[g[h] for h in HIDDEN]))
        return g
    return {h: r[h] for h in HIDDEN}


def all_of(conn):
    fill(conn)
    return {r[0]: dict(zip(HIDDEN, r[1:])) for r in conn.execute(f"SELECT player_id, {', '.join(HIDDEN)} FROM hidden")}


# ---------------------------------------------------------------- effects
def consistency_sd(v):
    return 0.30 - 0.24 * (v - 1) / 19


def big_games_fin(v):
    return 0.10 * (v - CENTRE) / 9.5


def injury_factor(v):
    return 1 + 0.04 * (v - CENTRE)


def temper_weight(v):
    return max(0.4, 1 + 0.06 * (CENTRE - v))


def coach_factor(v):
    return 0.95 + 0.0048 * v                     # 0.955 at 1, 1.0 at ~10.4, 1.046 at 20


def greed_factor(v):
    return 1 + 0.006 * (v - 10)


# ---------------------------------------------------------------- what the scouts say
PHRASES = {
    "consistency": ("streaky: you never know which version shows up", "steady as they come, night after night"),
    "big_games": ("shrinks when the stakes rise", "a big-game player"),
    "injury_proneness": ("never seems to get hurt", "injury-prone"),
    "temperament": ("a short fuse", "keeps his cool"),
    "sportsmanship": ("plays on the edge, and over it", "a gentleman on the ice"),
    "coachability": ("hard to coach", "a sponge: takes coaching well"),
    "greed": ("cares more about winning than money", "chases the money"),
}


def scout_read(conn, pid, mine=False):
    """Phrases for the attributes your scouts are sure of: the extremes (sure of 3 or less / 18 or more, or 5 / 16 for
    your own players, whom they see every day)."""
    h = of(conn, pid)
    lo, hi = (5, 16) if mine else (3, 18)
    out = []
    for k, (low, high) in PHRASES.items():
        v = h[k]
        if v <= lo:
            out.append(low if k != "injury_proneness" else low)
        elif v >= hi:
            out.append(high)
    return out


# ---------------------------------------------------------------- special abilities
def abilities(a, h, pos, personality=None):
    """Badges from the ratings (a), the hidden attributes (h) and the personality."""
    g = lambda k: (a.get(k) or 10)
    out = []
    if pos == "G":
        if g("reflexes") >= 17:
            out.append("Cat-like reflexes")
        if g("goalie_positioning") >= 17:
            out.append("Always square")
        if g("goalie_stamina") >= 17:
            out.append("Workhorse")
    else:
        if g("hitting") >= 17 and g("strength") >= 14:
            out.append("Big hitter")
        if g("shot_accuracy") >= 17 and g("shot_power") >= 15:
            out.append("Sniper")
        if g("puck_control") >= 17 and g("agility") >= 15:
            out.append("Magician")
        if g("shot_blocking") >= 17:
            out.append("The wall")
        if g("faceoffs") >= 17:
            out.append("Faceoff ace")
        if g("speed") >= 18:
            out.append("Burner")
        if g("passing") >= 18:
            out.append("Playmaker's vision")
        if g("toughness") >= 17 and g("aggression") >= 15:
            out.append("Enforcer")
        if g("endurance") >= 17:
            out.append("Workhorse")
    if h["injury_proneness"] <= 4 and g("endurance") >= 13:
        out.append("Iron man")
    if h["injury_proneness"] >= 17:
        out.append("Glass")
    if h["big_games"] >= 17:
        out.append("Playoff performer")
    if h["consistency"] >= 17:
        out.append("Mr. Reliable")
    if personality:
        if personality.get("ego", 10) >= 16 and personality.get("professionalism", 10) <= 7:
            out.append("Malcontent")
        if personality.get("loyalty", 10) >= 17:
            out.append("Homebody")
        if personality.get("leadership", 10) >= 17:
            out.append("Natural leader")
    return out
