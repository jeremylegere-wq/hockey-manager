"""Scouting: how clubs see draft prospects, and how they draft.

Every prospect has a hidden truth (his ceiling, whether he is an early or late physical maturer, whether he will
bloom late) and things anyone can see (height, league, nationality, production). A club's projection of his ceiling is

    what he is now, as its scouts see him  +  the growth an average player has left at his age
      + an error shared by the whole league   (everyone watched the same games; bigger outside North America)
      + the club's own error                   (smaller with better scouting staff)
      - the club's biases                      (set by its director of amateur scouting's philosophy)

Nobody sees late blooming or a player's maturity, so "safe" early maturers get overrated and late developers
underrated. The biases are the human element from the brief:
  size      smaller players are marked down, big ones up (0.07 per cm from 183 cm, capped at 0.7)
  europe    Swedish/Finnish/other European juniors are seen less and discounted
  russia    a Russian under KHL contract is discounted, more for every year left on it
Traditional directors carry the full biases, balanced ones about half, analytics-minded ones little, and analytics
directors also take more upside late. Goalies are much harder to project (1.35x the error).

Drafting (from the brief): round 1 is best player available with a 10% nod to need; rounds 2-4 weigh need more
(60/40); rounds 5-7 chase upside ("boom or bust"); goalies are pushed out of round 1 unless top tier.
"""
from __future__ import annotations

import datetime
import random

from ..worldgen import g_growth_left

STYLES = {
    "traditional": dict(size=1.0, euro=1.0, russia=1.0, upside=0.0),
    "balanced": dict(size=0.55, euro=0.55, russia=0.6, upside=0.08),
    "analytics": dict(size=0.1, euro=0.15, russia=0.25, upside=0.15),
}
STYLE_MIX = [("traditional", 55), ("balanced", 30), ("analytics", 15)]
STYLE_LABEL = {"traditional": "traditional (size, North American exposure)",
               "balanced": "balanced", "analytics": "analytics-driven (skill over size, global)"}
SIZE_PIVOT, GOALIE_SIZE_PIVOT, SIZE_PER_CM, SIZE_CAP = 183, 188, 0.07, 0.7
EURO_DISCOUNT, RUSSIA_DISCOUNT, RUSSIA_PER_YEAR = 0.3, 0.5, 0.15
EXPOSURE_NOISE = {"chl": 1.0, "nordic": 1.25, "europe": 1.3, "russia": 1.35}
COMMON_SD, OWN_SCALE, GOALIE_NOISE = 0.6, 0.55, 1.35
ROUND_NEED = {1: 0.08, 2: 0.4, 3: 0.4, 4: 0.4, 5: 0.1, 6: 0.1, 7: 0.1}
GOALIE_PENALTY = {1: 1.7, 2: 0.4, 3: 0.1}
GOALIE_TOP_TIER = 13.0
NEED_TARGET = {"F": 10, "D": 6, "G": 3}       # org players 23 and under a club wants in its pipeline


def bias(style, height, exposure, khl_years, goalie):
    w = STYLES.get(style, STYLES["balanced"])
    b = 0.0
    pivot = GOALIE_SIZE_PIVOT if goalie else SIZE_PIVOT
    if height:
        b -= w["size"] * max(-SIZE_CAP, min(SIZE_CAP, SIZE_PER_CM * (pivot - height)))
    if exposure in ("nordic", "europe"):
        b -= w["euro"] * EURO_DISCOUNT
    if exposure == "russia" and khl_years > 0:
        b -= w["russia"] * (RUSSIA_DISCOUNT + RUSSIA_PER_YEAR * khl_years)
    return b


def project(current, age, goalie, exposure, common_z, own_z, own_sd, style, height, khl_years):
    """A club's projected ceiling for one prospect (pure; z values are standard normal draws)."""
    f = EXPOSURE_NOISE.get(exposure, 1.3) * (GOALIE_NOISE if goalie else 1.0)
    return (current + g_growth_left(age, goalie) + f * (COMMON_SD * common_z + own_sd * OWN_SCALE * own_z)
            + bias(style, height, exposure, khl_years, goalie))


OVERAGE_DISCOUNT = {19: 0.15, 20: 0.4}   # scouts distrust older players piling up points against kids


def pick_score(proj, current, rnd, need, style, goalie, age=18):
    """How much a club wants a prospect with this pick (higher is better)."""
    s = proj + ROUND_NEED.get(rnd, 0.1) * need - OVERAGE_DISCOUNT.get(age, 0.0)
    up = STYLES.get(style, STYLES["balanced"])["upside"]
    raw = max(0.0, proj - current)                               # growth the club is betting on
    if rnd >= 5:
        s += (0.12 + 0.15 * up) * raw
    elif rnd >= 2:
        s += 0.1 * up * raw
    if goalie and not (rnd == 1 and proj >= GOALIE_TOP_TIER):
        s -= GOALIE_PENALTY.get(rnd, 0.0)
    return s


GOALIE_GRADES = ((12.3, "franchise starter"), (11.6, "starter"), (11.2, "1A"), (10.8, "1B"), (10.3, "backup"),
                 (9.8, "3rd string"), (9.3, "AHL depth"), (0, "long shot"))


def grade(proj, goalie=False):
    """Words for a projected ceiling (the same scale as player overall). v42 (register v39 #8): goalies in the words
    goalies are talked about: starter, 1A / 1B, backup, 3rd string, AHL depth."""
    scale = GOALIE_GRADES if goalie else ((12.3, "franchise talent"), (11.6, "top-line / top-pair"),
                                          (11.0, "top-six / top-four"), (10.5, "NHL regular"), (10.0, "depth NHLer"),
                                          (9.5, "fringe / AHL"), (0, "long shot"))
    for cut, word in scale:
        if proj >= cut:
            return word
    return "long shot"


# ---------------------------------------------------------------- database side

def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS prospect_info (player_id INTEGER PRIMARY KEY, hidden_bloom REAL, "
                 "maturity REAL, archetype TEXT, exposure TEXT, khl_until INTEGER, class_year INTEGER)")


def save_info(conn, pid, info, year):
    ensure_tables(conn)
    khl_until = year + info["khl_years"] - 1 if info.get("khl_years") else None
    conn.execute("INSERT OR REPLACE INTO prospect_info VALUES (?,?,?,?,?,?,?)",
                 (pid, info["hidden_bloom"], info["maturity"], info["archetype"], info["exposure"], khl_until,
                  info.get("class_year")))


def _seed(conn):
    from .state import get_state
    s = get_state(conn)
    return s[1] if s else 1


def club_style(conn, team_id):
    """Philosophy of the club's director of amateur scouting (balanced when there is none)."""
    if team_id is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return "balanced"
    r = conn.execute("SELECT staff_id, style FROM staff WHERE team_id=? AND role='SCOUT_DIR' ORDER BY staff_id LIMIT 1",
                     (team_id,)).fetchone()
    if r is None:
        return "balanced"
    if r[1] not in STYLES:                       # saves from before v13: give the director a philosophy once
        rng = random.Random(f"{_seed(conn)}-scoutstyle-{r[0]}")
        style = rng.choices([x for x, _ in STYLE_MIX], [w for _, w in STYLE_MIX])[0]
        conn.execute("UPDATE staff SET style=? WHERE staff_id=?", (style, r[0]))
        return style
    return r[1]


def club_sd(conn, team_id):
    from .staff import scout_sd
    if team_id is None:
        return 0.75
    return scout_sd(conn, team_id)


def khl_years_left(conn, pid, year):
    r = conn.execute("SELECT khl_until FROM prospect_info WHERE player_id=?", (pid,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='prospect_info'").fetchone() else None
    if not r or r[0] is None:
        return 0
    return max(0, r[0] - year + 1)


def exposure_of(conn, pid, nationality):
    r = conn.execute("SELECT exposure FROM prospect_info WHERE player_id=?", (pid,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='prospect_info'").fetchone() else None
    if r and r[0]:
        return r[0]
    return {"CAN": "chl", "USA": "chl", "SWE": "nordic", "FIN": "nordic", "RUS": "russia"}.get(nationality or "",
                                                                                            "europe")


def common_z(seed, year, pid):
    """The league-wide error for this player this year (what everybody gets wrong)."""
    return random.Random(f"{seed}-{year}-scout-common-{pid}").gauss(0, 1)


def consensus(conn, x, year, seed=None):
    """The league's consensus projection (shared error, average biases): used to say where a player 'should' go."""
    seed = seed if seed is not None else _seed(conn)
    return project(x["cur"], x["age"], x["goalie"], exposure_of(conn, x["pid"], x["nat"]), common_z(seed, year, x["pid"]),
                   0.0, 0.0, "balanced", x["height"], khl_years_left(conn, x["pid"], year))


class Lens:
    """One club's view of a draft class, computed once (shared and own errors are fixed per player and year)."""

    def __init__(self, conn, team_id, year):
        self.conn, self.team_id, self.year = conn, team_id, year
        self.style = club_style(conn, team_id)
        self.sd = club_sd(conn, team_id)
        self.seed = _seed(conn)
        self.levels = None                       # v36: your knowledge level of each prospect sharpens or blurs your own error
        from .state import user_team
        if team_id is not None and team_id == user_team(conn) and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='scout_knowledge'").fetchone():
            from . import scout_net as SN
            self.levels = {p: SN.FACTOR[SN.level_of(v)] for p, v in SN.knowledge(conn).items()}

    def view(self, pid, current, age, goalie, nationality, height):
        common = common_z(self.seed, self.year, pid)
        own = random.Random(f"{self.seed}-{self.year}-scout-{self.team_id}-{pid}").gauss(0, 1)
        khl = khl_years_left(self.conn, pid, self.year)
        sd = self.sd * (self.levels.get(pid, 1.0) if self.levels is not None else 1.0)
        return project(current, age, goalie, exposure_of(self.conn, pid, nationality), common, own, sd,
                       self.style, height, khl)


def needs(conn, team_id, year):
    """0-1 need per position group from the club's pipeline (org players and rights holders 23 and under)."""
    from .roster import group
    on = datetime.date(year, 9, 15).isoformat()
    cut = f"{year - 23}-09-15"
    have = {"F": 0, "D": 0, "G": 0}
    for (pos,) in conn.execute("SELECT position FROM players WHERE team_id=? AND status<>'retired' AND birth_date>? "
                               "UNION ALL SELECT p.position FROM draft_rights d JOIN players p USING (player_id) "
                               "WHERE d.team_id=? AND p.birth_date>?", (team_id, cut, team_id, cut)):
        have[group(pos)] += 1
    del on
    return {g: max(0.0, (NEED_TARGET[g] - have[g]) / NEED_TARGET[g]) for g in have}
