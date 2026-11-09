"""Seed a small fictional league (no real NHL names/likenesses) plus a round-robin schedule."""
import random
from datetime import date, timedelta
from itertools import combinations

FIRST = ["Alex", "Sam", "Jordan", "Riley", "Casey", "Morgan", "Drew", "Jamie", "Taylor", "Quinn",
         "Logan", "Blake", "Cameron", "Avery", "Reese", "Parker", "Dylan", "Hayden", "Rowan", "Skyler"]
LAST = ["Larsen", "Beaumont", "Kowalski", "Tremblay", "Novak", "Sutter", "Mercer", "Haldane", "Okafor",
        "Lindqvist", "Brandt", "Castellan", "Dufour", "Ellery", "Fairbanks", "Garrity", "Holloway",
        "Ivanov", "Jarvis", "Keane", "Lachance", "Moreau", "Nilsson", "Orlov", "Pelletier"]
TEAMS = [("Northern Lights", "NLT"), ("Harbour Kings", "HBK"), ("Prairie Wolves", "PRW"),
         ("Granite Peaks", "GRP"), ("Lakeshore Storm", "LKS"), ("Iron Ridge", "IRR"),
         ("Coastal Gulls", "CGL"), ("Maple Valley", "MPV")]
# 12 forwards (C/LW/RW), 6 D, 2 G
ROSTER = ["C"] * 4 + ["LW"] * 4 + ["RW"] * 4 + ["D"] * 6 + ["G"] * 2


def _attr(rng, pos, base):
    def r(bias=0):
        return max(1, min(20, int(rng.gauss(base + bias, 2.5))))
    a = dict(shooting=r(), passing=r(), skating=r(), stickhandling=r(), checking=r(),
             defense=r(), faceoffs=r(), goaltending=r(-8), stamina=r(), potential=r(1))
    if pos == "G":
        a["goaltending"] = r(0)
        a["shooting"] = a["passing"] = a["checking"] = 3
    elif pos == "D":
        a["defense"] = r(3); a["checking"] = r(2); a["shooting"] = r(-2)
    else:
        a["shooting"] = r(2); a["passing"] = r(1)
        if pos != "C":
            a["faceoffs"] = r(-4)
    return a


def seed(conn, seed=42, start="2026-10-01"):
    rng = random.Random(seed)
    cur = conn.cursor()
    cur.execute("INSERT INTO leagues (name, country) VALUES ('Demo Hockey League', 'XX')")
    league_id = cur.lastrowid
    cur.execute("INSERT INTO seasons (league_id, label, start_date) VALUES (?, '2026-27', ?)", (league_id, start))
    season_id = cur.lastrowid

    team_ids = []
    for name, abbrev in TEAMS:
        cur.execute("INSERT INTO teams (league_id, name, abbrev) VALUES (?,?,?)", (league_id, name, abbrev))
        tid = cur.lastrowid
        team_ids.append(tid)
        base = rng.uniform(9, 12)  # team quality varies
        for pos in ROSTER:
            age = rng.randint(19, 36)
            birth = date(2026 - age, rng.randint(1, 12), rng.randint(1, 28)).isoformat()
            cur.execute(
                "INSERT INTO players (first_name, last_name, birth_date, position, team_id) VALUES (?,?,?,?,?)",
                (rng.choice(FIRST), rng.choice(LAST), birth, pos, tid))
            pid = cur.lastrowid
            a = _attr(rng, pos, base)
            cols = ", ".join(a)
            ph = ", ".join("?" * len(a))
            cur.execute(f"INSERT INTO player_attributes (player_id, {cols}, updated_on) VALUES (?, {ph}, ?)",
                        (pid, *a.values(), start))
            cur.execute(f"INSERT INTO attribute_history (player_id, season_id, {cols}) VALUES (?, ?, {ph})",
                        (pid, season_id, *a.values()))
            cur.execute("INSERT INTO contracts (player_id, team_id, start_season, years, cap_hit) VALUES (?,?,?,?,?)",
                        (pid, tid, season_id, rng.randint(1, 5), rng.randint(750, 9000) * 1000))

    # double round robin, one game-day per "round"
    pairs = list(combinations(team_ids, 2))
    rng.shuffle(pairs)
    d = date.fromisoformat(start)
    games_today, used = 0, set()
    for home, away in pairs + [(b, a) for a, b in pairs]:
        while home in used or away in used:
            d += timedelta(days=1)
            used = set()
        used.update([home, away])
        cur.execute("INSERT INTO games (season_id, game_date, home_team_id, away_team_id) VALUES (?,?,?,?)",
                    (season_id, d.isoformat(), home, away))
        if len(used) >= len(team_ids):
            d += timedelta(days=1)
            used = set()

    cur.execute("INSERT INTO game_state (id, current_date, current_season_id, rng_seed) VALUES (1, ?, ?, ?)",
                (start, season_id, seed))
    conn.commit()
    return season_id
