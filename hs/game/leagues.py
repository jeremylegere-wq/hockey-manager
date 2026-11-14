"""The leagues around the NHL, played for real (v44; docs/LEAGUES.md).

Every league in the world with rules (hs/leaguedata/league_rules.py) plays a real season: a schedule from its
alignment and game count, games day by day, standings by its points system, playoffs in its own format, a champion,
and the Memorial Cup. You still manage an NHL club; these run alongside.

The results model (not the NHL match engine, which would make a season six times slower): each club's lineup (its
best twelve forwards and six defencemen, the starter in about seven games of ten) gives an attack and a goalie; goals
are Poisson around the league's scoring rate, tilted by the attack gap and the goalie; ties go to overtime and a
shootout (or stand, NCAA). Every goal gets a scorer and up to two assists among the dressed players (weighted by
overall, line and position), shots and penalty minutes are spread the same way, and the goalies get their saves.
The lines go into the season tables (source='league'), so player pages, the draft board and development see them.
"""
from __future__ import annotations

import datetime
import math
import random
from collections import defaultdict

from ..leaguedata.league_rules import COUNTRY, MEMORIAL, RULES
from .events import emit, team_abbr
from .state import add_message, get_state, user_team

DOMESTIC = {"KHL": {"RUS", "BLR", "KAZ"}, "OHL": {"CAN", "USA"}, "WHL": {"CAN", "USA"}, "QMJHL": {"CAN", "USA"},
            "USHL": {"USA", "CAN"}, "NL": {"SUI"}, "DEL": {"GER"}}
ATTACK_K = 0.55          # goals x exp(K x attack gap): a club 0.5 better scores about 30% more
GOALIE_K = 0.22          # and each point of goalie overall above the league's takes about 20% off
HOME = 0.04
OT_GOAL = 0.55           # chance a 3-on-3 overtime produces a goal
MEMORIAL_ID = -1
PROREL_BASE = -1000      # v61: promotion and relegation with the league above is its own little competition, -1000 - upper


# ---------------------------------------------------------------- import and over-age limits (used when clubs sign)
class Limits:
    """Who a club may still add under its league's rules: at most `imports` players from outside the league's
    countries (no import goalies where the rule says so), and at most `overage` 20-year-olds in junior leagues."""

    def __init__(self, conn, on_date):
        from .world import age_on
        self.rules = {lid: (abbr, r) for lid, (abbr, r) in leagues(conn).items() if r.get("imports") or r.get("overage")}
        self.club_league = {}
        self.imports, self.over = defaultdict(int), defaultdict(int)
        if not self.rules:
            return
        q = ",".join(str(l) for l in self.rules)
        for t, lid in conn.execute(f"SELECT team_id, league_id FROM teams WHERE league_id IN ({q})"):
            self.club_league[t] = lid
        for club, nat, born in conn.execute(f"SELECT p.club_id, p.nationality, p.birth_date FROM players p JOIN teams t ON "
                                            f"t.team_id=p.club_id WHERE t.league_id IN ({q}) AND p.status<>'retired'"):
            lid = self.club_league[club]
            if self.foreign(lid, nat):
                self.imports[club] += 1
            if born and age_on(born, on_date) >= 20:
                self.over[club] += 1
        self.on = on_date

    def domestic(self, lid):
        abbr = self.rules[lid][0]
        return DOMESTIC.get(abbr) or {COUNTRY.get(abbr)}

    def foreign(self, lid, nat):
        return lid in self.rules and (nat or "") not in self.domestic(lid)

    def ok(self, club, nat, age, pos=None):
        lid = self.club_league.get(club)
        if lid is None:
            return True
        r = self.rules[lid][1]
        if self.foreign(lid, nat):
            if r.get("imports") is not None and self.imports[club] >= r["imports"]:
                return False
            if r.get("no_import_goalies") and pos == "G":
                return False
        if r.get("overage") and age >= 20 and self.over[club] >= r["overage"]:
            return False
        return True

    def add(self, club, nat, age):
        lid = self.club_league.get(club)
        if lid is None:
            return
        if self.foreign(lid, nat):
            self.imports[club] += 1
        if age >= 20:
            self.over[club] += 1


# ---------------------------------------------------------------- tables
def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS lg_games (game_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER, "
                 "day TEXT, home INTEGER, away INTEGER, hg INTEGER, ag INTEGER, ot INTEGER DEFAULT 0, stage TEXT DEFAULT 'RS', "
                 "series_id INTEGER, played INTEGER DEFAULT 0)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_lg_games_day ON lg_games(played, day)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_lg_games_league ON lg_games(league_id, season, stage)")
    conn.execute("CREATE TABLE IF NOT EXISTS lg_series (series_id INTEGER PRIMARY KEY, league_id INTEGER, season INTEGER, "
                 "round INTEGER, idx INTEGER, a INTEGER, b INTEGER, seed_a INTEGER, seed_b INTEGER, grp TEXT, best_of INTEGER, "
                 "kind TEXT DEFAULT 'series', wins_a INTEGER DEFAULT 0, wins_b INTEGER DEFAULT 0, pts_a INTEGER DEFAULT 0, "
                 "pts_b INTEGER DEFAULT 0, games INTEGER DEFAULT 0, next_day TEXT, winner INTEGER, label TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS lg_seasons (league_id INTEGER, season INTEGER, phase TEXT, champion INTEGER, "
                 "runner_up INTEGER, finished TEXT, PRIMARY KEY (league_id, season))")


def leagues(conn, every=False):
    """{league_id: (abbr, rules)} for the leagues in the world that have rules (not the top league) and are in play
    (v60: a league switched off in League > World leagues is left out unless `every`)."""
    out = {}
    off = set() if every else _off(conn)
    for lid, name, abbr, level in conn.execute("SELECT league_id, name, abbr, level FROM leagues"):
        if (level or 1) == 1 or lid in off:
            continue
        for k in (abbr, name):
            key = (k or "").upper().replace(" ", "")
            if key in RULES:
                out[lid] = (key, RULES[key])
                break
    return out


# ---------------------------------------------------------------- v60: which leagues are in play
def _off(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_select'").fetchone():
        return set()
    return {r[0] for r in conn.execute("SELECT league_id FROM lg_select WHERE play=0")}


def selection(conn):
    """Every league with rules, in play or not: [dict(league_id, abbr, name, level, clubs, play, approximate, started)]."""
    from ..leaguedata.league_rules import APPROXIMATE
    ensure_tables(conn)
    off = _off(conn)
    year = _season_year(conn)
    out = []
    for lid, (abbr, rules) in leagues(conn, every=True).items():
        name, level = conn.execute("SELECT name, level FROM leagues WHERE league_id=?", (lid,)).fetchone()
        n = conn.execute("SELECT COUNT(*) FROM teams WHERE league_id=?", (lid,)).fetchone()[0]
        row = conn.execute("SELECT phase FROM lg_seasons WHERE league_id=? AND season=?", (lid, year)).fetchone()
        out.append(dict(league_id=lid, abbr=abbr, name=name, level=level, clubs=n, play=lid not in off, games=rules["games"],
                        approximate=abbr in APPROXIMATE, phase=row[0] if row else None, affiliates=abbr in ("AHL", "ECHL")))
    out.sort(key=lambda x: (x["level"] or 9, x["abbr"]))
    return out


def set_play(conn, lid, on):
    """Play a league game by game, or not (v60). Off: the league goes back to the season-at-a-time model (hs/game/
    world.py: a line for every player and a champion when the year ends), which costs no time during the season;
    what it had played of this season is taken back so the year is not counted twice. On: it is scheduled at once and
    catches up to today. Returns a line for the user."""
    ensure_tables(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS lg_select (league_id INTEGER PRIMARY KEY, play INTEGER)")
    every = leagues(conn, every=True)
    if lid not in every:
        raise ValueError("That league has no season to play.")
    abbr = every[lid][0]
    year = _season_year(conn)
    conn.execute("INSERT OR REPLACE INTO lg_select VALUES (?,?)", (lid, 1 if on else 0))
    if on:
        return f"{abbr} now plays game by game."
    row = conn.execute("SELECT phase FROM lg_seasons WHERE league_id=? AND season=?", (lid, year)).fetchone()
    if row and row[0] == "done":
        return f"{abbr} is simulated a season at a time from next season (this one is finished)."
    conn.execute("DELETE FROM lg_games WHERE league_id=? AND season=?", (lid, year))
    conn.execute("DELETE FROM lg_series WHERE league_id=? AND season=?", (lid, year))
    conn.execute("DELETE FROM lg_seasons WHERE league_id=? AND season=?", (lid, year))
    for t in ("skater_season_stats", "goalie_season_stats"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if "source" in cols:
            conn.execute(f"DELETE FROM {t} WHERE league_id=? AND season_start_year=? AND source='league'", (lid, year))
    return f"{abbr} is now simulated a season at a time."


def active(conn):
    """The leagues play for real once a save has scheduled them (v44 on)."""
    ensure_tables(conn)
    return bool(conn.execute("SELECT 1 FROM lg_games LIMIT 1").fetchone())


def _clubs(conn, lid):
    return [dict(team_id=r[0], division=(r[1] or "").strip(), conference=(r[2] or "").strip())
            for r in conn.execute("SELECT team_id, division, conference FROM teams WHERE league_id=? ORDER BY team_id", (lid,))]


def _season_clubs(conn, lid, year):
    """The clubs that played in a league that season (v61: clubs can go up or down between seasons), or its clubs
    now if it has not played yet."""
    ids = {r[0] for r in conn.execute("SELECT home FROM lg_games WHERE league_id=? AND season=? AND stage='RS' UNION "
                                      "SELECT away FROM lg_games WHERE league_id=? AND season=? AND stage='RS'",
                                      (lid, year, lid, year))}
    if not ids:
        return _clubs(conn, lid)
    q = ",".join("?" * len(ids))
    return [dict(team_id=r[0], division=(r[1] or "").strip(), conference=(r[2] or "").strip())
            for r in conn.execute(f"SELECT team_id, division, conference FROM teams WHERE team_id IN ({q}) ORDER BY team_id",
                                  sorted(ids))]


def _season_year(conn):
    return conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]


def _date(year, mmdd, wrap_from=7):
    m, d = (int(x) for x in mmdd.split("-"))
    return datetime.date(year + (1 if m < wrap_from else 0), m, d)


def conference_of(rules, club):
    if club["conference"]:
        return club["conference"]
    for conf, divs in (rules.get("conferences") or {}).items():
        if club["division"] in divs:
            return conf
    return club["division"] or "League"


# ---------------------------------------------------------------- schedule
def _pair_counts(clubs, games, rng, fill=False):
    """{(i, j): games} for every pair: more games inside the division (or the whole league when there is none),
    as close to `games` each as the alignment allows."""
    n = len(clubs)
    groups = defaultdict(list)
    for i, c in enumerate(clubs):
        groups[c["division"] or "all"].append(i)
    extra = 0
    if len(groups) == 1 and fill and n > 2:              # v60: whole rounds, then part of one more to reach the count
        a, b = games // (n - 1), 0
        extra = games - a * (n - 1)
        if n % 2 and extra % 2:
            extra -= 1                                   # an odd number of clubs cannot all play an odd number more
    elif len(groups) == 1:
        a, b = round(games / max(1, n - 1)), 0
    elif n - 1 > games:                                  # more clubs than games (NCAA): each conference plays itself,
        counts = {}                                      # as often as fits, and the rest are one-off games
        for i in range(n):
            for j in range(i + 1, n):
                gi = groups[clubs[i]["division"] or "all"]
                same = (clubs[i]["division"] or "all") == (clubs[j]["division"] or "all")
                counts[(i, j)] = max(1, int(games * 0.8) // max(1, len(gi) - 1)) if same else 0
        a = b = None
    else:
        best = None
        for a in range(0, 12):
            for b in range(0, a + 1):
                tot = [a * (len(groups[c["division"] or "all"]) - 1) + b * (n - len(groups[c["division"] or "all"])) for c in clubs]
                err = sum(abs(t - games) for t in tot)
                if best is None or err < best[0]:
                    best = (err, a, b)
        _, a, b = best
    if a is not None:
        counts = {}
        for i in range(n):
            for j in range(i + 1, n):
                same = (clubs[i]["division"] or "all") == (clubs[j]["division"] or "all")
                counts[(i, j)] = a if same else b
    if extra:                                            # every club plays `extra` more, against different opponents
        order = list(range(n))
        rng.shuffle(order)
        for d in range(1, extra // 2 + 1):
            for i in range(n):
                x, y = order[i], order[(i + d) % n]
                counts[(min(x, y), max(x, y))] += 1
        if extra % 2:
            for i in range(n // 2):
                x, y = order[i], order[i + n // 2]
                counts[(min(x, y), max(x, y))] += 1
    # when a league has more clubs than games (NCAA), b is 0 and a fills the conference; top up to the target with
    # one-off games against other clubs, chosen at random among those still short
    need = [games - sum(v for (i, j), v in counts.items() if k in (i, j)) for k in range(n)]
    short = [k for k in range(n) if need[k] > 0]
    rng.shuffle(short)
    for k in short:
        others = [j for j in range(n) if j != k and need[j] > 0 and counts[(min(k, j), max(k, j))] == 0]
        rng.shuffle(others)
        for j in others:
            if need[k] <= 0:
                break
            counts[(min(k, j), max(k, j))] += 1
            need[k] -= 1
            need[j] -= 1
    return counts


def make_schedule(conn, lid, year, rng):
    abbr, rules = leagues(conn)[lid]
    clubs = _clubs(conn, lid)
    if len(clubs) < 4:
        return 0
    from ..leaguedata.league_rules import APPROXIMATE
    counts = _pair_counts(clubs, rules["games"], rng, fill=bool(rules.get("fill")) or abbr in APPROXIMATE)
    # v60: home and away are shared out. Each pair splits its meetings evenly; an odd one goes to the club with fewer
    # home games so far. (Before, every game's host was a coin toss, and a club could get 17 home games of 52.)
    games, homes, odd = [], defaultdict(int), []
    for (i, j), k in counts.items():
        for h, a in ((i, j), (j, i)):
            homes[h] += k // 2
            games += [(clubs[h]["team_id"], clubs[a]["team_id"])] * (k // 2)
        if k % 2:
            odd.append((i, j))
    rng.shuffle(odd)                                       # in a random order, or the last clubs listed host them all
    total = defaultdict(int)
    for (i, j), k in counts.items():
        total[i] += k
        total[j] += k
    tilt = lambda c: 2 * homes[c] - total[c]               # home games minus away games, once everything is placed
    hosts = []
    for i, j in odd:
        h, a = (i, j) if homes[i] < homes[j] or (homes[i] == homes[j] and rng.random() < 0.5) else (j, i)
        homes[h] += 1
        hosts.append([h, a])
    for _ in range(30):                                    # then swap hosts wherever that evens two clubs out
        moved = False
        for g in hosts:
            h, a = g
            if tilt(h) - tilt(a) > 2:
                g[0], g[1] = a, h
                homes[h] -= 1
                homes[a] += 1
                moved = True
        if not moved:
            break
    games += [(clubs[h]["team_id"], clubs[a]["team_id"]) for h, a in hosts]
    rng.shuffle(games)
    start, end = _date(year, rules["start"]), _date(year, rules["end"])
    days = [(start + datetime.timedelta(days=d)) for d in range((end - start).days + 1)]
    # spread evenly over the season's dates: by day k at most (k + 1) / days of the schedule has been played (plus a
    # little slack), so the last games fall near the real end date rather than weeks early
    total, last, done = len(games), {}, 0
    out, pending = [], games
    for k, d in enumerate(days):
        busy, keep, today = set(), [], 0
        cap = max(1, math.ceil(total * (k + 1) / len(days) * 1.02) - done)
        for h, a in pending:
            if today >= cap or h in busy or a in busy or \
                    last.get(h) == d - datetime.timedelta(days=1) and rng.random() < 0.7:
                keep.append((h, a))
                continue
            busy |= {h, a}
            last[h] = last[a] = d
            out.append((d, h, a))
            today += 1
        done += today
        pending = keep
        if not pending:
            break
    d = end
    for h, a in pending:                                   # anything left over goes at the end
        d += datetime.timedelta(days=1)
        out.append((d, h, a))
    conn.executemany("INSERT INTO lg_games (league_id, season, day, home, away, stage) VALUES (?,?,?,?,?,'RS')",
                     [(lid, year, d.isoformat(), h, a) for d, h, a in out])
    return len(out)


def ensure_season(conn, year=None, seed=None):
    """Schedule this season for every league with rules (once)."""
    ensure_tables(conn)
    from ..schema import migrate
    migrate(conn)                                        # the season tables' source column
    year = year or _season_year(conn)
    seed = seed if seed is not None else get_state(conn)[1]
    made = 0
    apply_moves(conn, year)                              # v61: last season's promoted and relegated clubs change leagues
    for lid, (abbr, rules) in sorted(leagues(conn).items()):
        if conn.execute("SELECT 1 FROM lg_seasons WHERE league_id=? AND season=?", (lid, year)).fetchone():
            continue
        made += make_schedule(conn, lid, year, random.Random(f"{seed}-{year}-{abbr}-schedule"))
        conn.execute("INSERT INTO lg_seasons (league_id, season, phase) VALUES (?,?,'RS')", (lid, year))
    _ensure_prorel(conn, year)
    return made


# ---------------------------------------------------------------- the results model
class Club:
    __slots__ = ("team_id", "fwd", "dmen", "goalies", "attack", "ghosts", "t_for", "t_against", "starter")

    def __init__(self, team_id, rows, mean):
        from .world import overall as _ov
        overall = lambda r: r["overall"] if "overall" in r else _ov(r)
        sk = sorted(((overall(r), r["player_id"], r["position"]) for r in rows if r["position"] != "G"), reverse=True)
        self.team_id = team_id
        self.fwd = [(v, p) for v, p, pos in sk if pos != "D"][:12]
        self.dmen = [(v, p) for v, p, pos in sk if pos == "D"][:6]
        self.goalies = sorted(((overall(r), r["player_id"]) for r in rows if r["position"] == "G"), reverse=True)[:3]
        vals = [v for v, _ in self.fwd] + [mean - 1.5] * (12 - len(self.fwd)) + \
               [v * 0.8 + mean * 0.2 for v, _ in self.dmen] + [mean - 1.5] * (6 - len(self.dmen))
        self.attack = sum(vals) / len(vals)
        self.ghosts = 18 - len(self.fwd) - len(self.dmen)
        self.t_for = self.t_against = 1.0                  # v61: tactics (the European club you run)
        self.starter = 0.7

    def goalie(self, rng, mean):
        if not self.goalies:
            return None, mean - 1.5
        g = self.goalies[0] if rng.random() < self.starter or len(self.goalies) == 1 else self.goalies[1]
        return g[1], g[0]


def _weights(club):
    w = []
    for k, (v, pid) in enumerate(club.fwd):
        w.append((pid, math.exp(0.45 * (v - club.attack)) * (1.25 if k < 6 else 0.8), 1.0))
    for k, (v, pid) in enumerate(club.dmen):
        w.append((pid, math.exp(0.45 * (v - club.attack)) * 0.35 * (1.2 if k < 4 else 0.8), 2.2))
    return w


def _pick(rng, items, weights, exclude=()):
    pool = [(i, w) for i, w in zip(items, weights) if i not in exclude]
    if not pool:
        return None
    tot = sum(w for _, w in pool)
    x = rng.random() * tot
    for i, w in pool:
        x -= w
        if x <= 0:
            return i
    return pool[-1][0]


def play(rng, home, away, gpg, g_mean, playoff=False, ties=False, stats=None, split="RS", lid=None, year=None, agg=None):
    """One game: (home goals, away goals, ot) with ot 0 regulation, 1 overtime, 2 shootout, 3 tie. Adds player
    lines to `stats` ({(pid, team, kind): [...]}). v61 `agg`, for a two-game series on aggregate goals: "first" (a
    level first game stands, no overtime) or (home's goals so far, away's goals so far) for the second game (only an
    aggregate that is level after regulation goes to overtime, played until a goal)."""
    gh_id, gh = home.goalie(rng, g_mean)
    ga_id, ga_ = away.goalie(rng, g_mean)
    lam_h = gpg * math.exp(ATTACK_K * (home.attack - away.attack) - GOALIE_K * (ga_ - g_mean) + HOME) * home.t_for * away.t_against
    lam_a = gpg * math.exp(ATTACK_K * (away.attack - home.attack) - GOALIE_K * (gh - g_mean) - HOME) * away.t_for * home.t_against
    def pois(lam):
        k, p, l = 0, 1.0, math.exp(-lam)
        while True:
            p *= rng.random()
            if p < l:
                return k
            k += 1
    hg, ag = pois(lam_h), pois(lam_a)
    ot = 0
    winner_extra = None
    p_home = lam_h / (lam_h + lam_a)
    if agg is not None:
        if agg != "first" and hg + agg[0] == ag + agg[1]:
            ot, winner_extra = 1, "h" if rng.random() < p_home else "a"
        elif hg == ag:
            ot = 3
    elif hg == ag:
        if playoff:
            ot, winner_extra = 1, "h" if rng.random() < p_home else "a"
        elif rng.random() < OT_GOAL:
            ot, winner_extra = 1, "h" if rng.random() < p_home else "a"
        elif ties:
            ot = 3
        else:
            ot, winner_extra = 2, "h" if rng.random() < 0.5 + 0.06 * (gh - ga_) else "a"
    if stats is not None:
        _lines(rng, home, hg + (1 if winner_extra == "h" and ot == 1 else 0), ag, gh_id, stats, ot, winner_extra == "h", split)
        _lines(rng, away, ag + (1 if winner_extra == "a" and ot == 1 else 0), hg, ga_id, stats, ot, winner_extra == "a", split)
    if winner_extra == "h":
        hg += 1
    elif winner_extra == "a":
        ag += 1
    return hg, ag, ot


def _lines(rng, club, goals, against, goalie, stats, ot, won, split):
    w = _weights(club)
    ids = [p for p, _, _ in w]
    gw = [x for _, x, _ in w]
    aw = [x * a for _, x, a in w]
    line = {pid: [1, 0, 0, 0, 0, 0] for pid in ids}        # gp g a pim sog toi
    for k, (v, pid) in enumerate(club.fwd):
        line[pid][5] = (17 if k < 6 else 12) * 60
    for k, (v, pid) in enumerate(club.dmen):
        line[pid][5] = (22 if k < 4 else 16) * 60
    for _ in range(goals):
        s = _pick(rng, ids, gw) if ids else None
        if s is None:
            continue
        line[s][1] += 1
        a1 = _pick(rng, ids, aw, (s,)) if rng.random() < 0.88 else None
        if a1:
            line[a1][2] += 1
            a2 = _pick(rng, ids, aw, (s, a1)) if rng.random() < 0.68 else None
            if a2:
                line[a2][2] += 1
    shots = max(goals, int(rng.gauss(29, 4)))
    for _ in range(shots):
        s = _pick(rng, ids, gw)
        if s:
            line[s][4] += 1
    for _ in range(max(0, int(rng.gauss(4, 1.6)))):
        s = _pick(rng, ids, [1.0] * len(ids))
        if s:
            line[s][3] += 2
    for pid, v in line.items():
        key = (pid, club.team_id, "S", split)
        cur = stats.setdefault(key, [0, 0, 0, 0, 0, 0])
        for i in range(6):
            cur[i] += v[i]
    if goalie:
        sa = max(against, int(rng.gauss(29, 4)))
        key = (goalie, club.team_id, "G", split)
        cur = stats.setdefault(key, [0, 0, 0, 0, 0, 0, 0])   # gp w l otl so ga sa
        cur[0] += 1
        cur[1] += 1 if won or (ot == 0 and goals > against) else 0
        cur[2] += 1 if (ot == 0 and goals < against) else 0
        cur[3] += 1 if (ot in (1, 2) and not won) else 0
        cur[4] += 1 if against == 0 else 0
        cur[5] += against
        cur[6] += sa


def _flush(conn, year, stats, league_of):
    if not stats:
        return
    sk = conn.execute("SELECT player_id, team_id, split FROM skater_season_stats WHERE season_start_year=? AND source='league'",
                      (year,)).fetchall()
    gk = conn.execute("SELECT player_id, team_id, split FROM goalie_season_stats WHERE season_start_year=? AND source='league'",
                      (year,)).fetchall()
    have = {("S", r[0], r[1], r[2]) for r in sk} | {("G", r[0], r[1], r[2]) for r in gk}
    up_s, ins_s, up_g, ins_g = [], [], [], []
    for (pid, team, kind, split), v in stats.items():
        if kind == "S":
            if ("S", pid, team, split) in have:
                up_s.append((*v, pid, year, team, split))
            else:
                ins_s.append((pid, year, team, league_of[team], split, *v, 0, "league"))
        else:
            if ("G", pid, team, split) in have:
                up_g.append((*v, v[0] * 3600, pid, year, team, split))
            else:
                ins_g.append((pid, year, team, league_of[team], split, *v, v[0] * 3600, "league"))
    conn.executemany("UPDATE skater_season_stats SET gp=gp+?, g=g+?, a=a+?, pim=pim+?, sog=sog+?, toi_sec=toi_sec+? WHERE "
                     "player_id=? AND season_start_year=? AND team_id=? AND split=? AND source='league'", up_s)
    conn.executemany("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a, pim, "
                     "sog, toi_sec, plus_minus, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ins_s)
    conn.executemany("UPDATE goalie_season_stats SET gp=gp+?, w=w+?, l=l+?, otl=otl+?, so=so+?, ga=ga+?, sa=sa+?, toi_sec=toi_sec+? "
                     "WHERE player_id=? AND season_start_year=? AND team_id=? AND split=? AND source='league'", up_g)
    conn.executemany("INSERT INTO goalie_season_stats (player_id, season_start_year, team_id, league_id, split, gp, w, l, otl, so, "
                     "ga, sa, toi_sec, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ins_g)


def _load_clubs(conn, team_ids):
    """The clubs playing today and each league's average skater and goalie. (v60: reads only the ratings the overall is
    made of, not every column of every player: with every league in play this was the slowest part of a day.)"""
    from ..worldgen import GOALIE_KEYS, SKATER_KEYS, overall_of
    if not team_ids:
        return {}, {}
    team_ids = list(team_ids)
    keys = list(dict.fromkeys(list(SKATER_KEYS) + list(GOALIE_KEYS)))
    q = ",".join("?" * len(team_ids))
    cur = conn.execute(f"SELECT p.player_id, p.position, p.club_id, {', '.join('a.' + k for k in keys)} FROM players p "
                       f"JOIN player_attributes a USING (player_id) WHERE p.club_id IN ({q}) AND p.status IN ('active','prospect')",
                       team_ids)
    by = defaultdict(list)
    si = [3 + keys.index(k) for k in SKATER_KEYS]
    gi = [3 + keys.index(k) for k in GOALIE_KEYS]
    for r in cur:
        pos = r[1]
        vals = [float(r[i]) if r[i] not in (None, "") else 10.0 for i in (gi if pos == "G" else si)]     # = worldgen.overall_of
        by[r[2]].append(dict(player_id=r[0], position=pos, overall=sum(vals) / len(vals)))
    lg = {r[0]: r[1] for r in conn.execute(f"SELECT team_id, league_id FROM teams WHERE team_id IN ({q})", team_ids)}
    means, gmeans = defaultdict(list), defaultdict(list)
    for t, rs in by.items():
        for r in rs:
            (gmeans if r["position"] == "G" else means)[lg[t]].append(r["overall"])
    mean = {l: sum(v) / len(v) for l, v in means.items() if v}
    gmean = {l: sum(v) / len(v) for l, v in gmeans.items() if v}
    clubs = {t: Club(t, by.get(t, []), mean.get(lg[t], 8.5)) for t in team_ids}
    from .europe import club as _managed                  # v61: the European club you run dresses your lineup
    if _managed(conn) in clubs:
        from .eu_lineup import apply_to
        apply_to(conn, clubs, by, lambda t: mean.get(lg[t], 8.5))
    return clubs, {l: (mean.get(l, 8.5), gmean.get(l, 8.5)) for l in set(lg.values())}


# ---------------------------------------------------------------- the day
def day(conn, today, seed=None, env=None, skill=None):
    """Play every league game due on or before today; move the playoffs on. Returns news lines. v61: with the engine's
    env and skill, the European club you run plays its games with the real engine (hs/game/eu_match.py)."""
    ensure_tables(conn)
    if not leagues(conn):
        return []
    ensure_season(conn)
    seed = seed if seed is not None else get_state(conn)[1]
    news = []
    for _ in range(400):                                  # catch up day by day (a save that jumped ahead)
        nxt = conn.execute("SELECT MIN(day) FROM lg_games WHERE played=0 AND day<=?", (today,)).fetchone()[0]
        due_series = conn.execute("SELECT MIN(next_day) FROM lg_series WHERE winner IS NULL AND next_day<=?", (today,)).fetchone()[0]
        d = min(x for x in (nxt, due_series) if x) if (nxt or due_series) else None
        if d is None:
            break
        news += _play_day(conn, d, seed, env, skill)
        news += _advance(conn, d, seed)
    return news


def _play_day(conn, d, seed, env=None, skill=None):
    for s in conn.execute("SELECT * FROM lg_series WHERE winner IS NULL AND next_day=?", (d,)).fetchall():
        _schedule_series_game(conn, s, d)
    games = conn.execute("SELECT * FROM lg_games WHERE played=0 AND day=?", (d,)).fetchall()
    if not games:
        return []
    lg_rules = leagues(conn)
    teams = {t for g in games for t in (g["home"], g["away"])}
    clubs, means = _load_clubs(conn, teams)
    league_of = {r[0]: r[1] for r in conn.execute("SELECT team_id, league_id FROM teams")}
    stats = {}
    year = games[0]["season"]
    me = None
    if env is not None and skill is not None:            # v61: your European club's games go to the engine
        from . import europe as EU
        me = EU.club(conn) if EU.active(conn) else None
    for g in games:
        lid = g["league_id"]
        rules = lg_rules.get(lid, (None, {}))[1] if lid != MEMORIAL_ID else dict(gpg=3.4, ot="so")
        rng = random.Random(f"{seed}-lg-{g['game_id']}")
        po = g["stage"] == "PO"
        mean, gmean = means.get(league_of.get(g["home"]), (8.5, 8.5))
        agg_first = bool(g["series_id"]) and _is_agg(conn, g["series_id"])     # a two-game play-in's first game can be drawn
        legs = _legs(conn, g["series_id"], g["home"]) if g["series_id"] else None    # v61: two games on aggregate goals
        done = None
        if me in (g["home"], g["away"]) and legs in (None, "first") and lid != MEMORIAL_ID:
            from . import eu_match as EM
            ties = (rules.get("ot") == "tie" and not po) or agg_first or legs == "first"
            done = EM.play(conn, g, env, skill, seed, playoff=po and not ties, ties=ties, split="PO" if po else "RS")
            if done:
                hg, ag, ot, lines = done
                for k, v in lines.items():
                    cur = stats.setdefault(k, [0] * len(v))
                    for i, x in enumerate(v):
                        cur[i] += x
        if done is None:
            hg, ag, ot = play(rng, clubs[g["home"]], clubs[g["away"]], rules.get("gpg", 3.0), gmean, playoff=po and not agg_first,
                              ties=(rules.get("ot") == "tie" and not po) or agg_first, stats=stats, split="PO" if po else "RS",
                              agg=legs)
        conn.execute("UPDATE lg_games SET hg=?, ag=?, ot=?, played=1 WHERE game_id=?", (hg, ag, ot, g["game_id"]))
        if g["series_id"]:
            _series_result(conn, g["series_id"], g["home"], hg, ag, ot)
    _flush(conn, year, stats, league_of)
    return []


def _legs(conn, sid, home):
    """For a game of a two-game series on aggregate goals: "first", or (home's goals so far, away's) for the second."""
    r = conn.execute("SELECT kind, games, a, pts_a, pts_b FROM lg_series WHERE series_id=?", (sid,)).fetchone()
    if not r or r[0] != "leg2":
        return None
    if r[1] == 0:
        return "first"
    return (r[3], r[4]) if home == r[2] else (r[4], r[3])


def _is_agg(conn, sid):
    r = conn.execute("SELECT kind, games FROM lg_series WHERE series_id=?", (sid,)).fetchone()
    return bool(r and r[0] == "agg" and r[1] == 0)          # the first game of a two-game play-in can be drawn


# ---------------------------------------------------------------- standings
POINTS = {"2pt": (2, 2, 2, 1, 1), "3pt": (3, 2, 2, 1, 1)}    # regulation win, OT win, SO win, OT/SO loss, tie


def standings(conn, lid, year):
    """[dict(team_id, gp, w, l, otl, t, pts, gf, ga, rw)] best first."""
    ensure_tables(conn)
    abbr, rules = leagues(conn).get(lid, (None, {"points": "2pt"}))
    pw, otw, sow, otl, tie = POINTS[rules.get("points", "2pt")]
    rec = {c["team_id"]: dict(team_id=c["team_id"], division=c["division"], conference=conference_of(rules, c), gp=0, w=0,
                              l=0, otl=0, t=0, pts=0, gf=0, ga=0, rw=0) for c in _season_clubs(conn, lid, year)}
    for h, a, hg, ag, ot in conn.execute("SELECT home, away, hg, ag, ot FROM lg_games WHERE league_id=? AND season=? AND "
                                         "stage='RS' AND played=1", (lid, year)):
        for t, gf, ga in ((h, hg, ag), (a, ag, hg)):
            r = rec.get(t)
            if r is None:
                continue
            r["gp"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if ot == 3:
                r["t"] += 1
                r["pts"] += tie
            elif gf > ga:
                r["w"] += 1
                r["rw"] += 1 if ot == 0 else 0
                r["pts"] += pw if ot == 0 else otw if ot == 1 else sow
            elif ot in (1, 2):
                r["otl"] += 1
                r["pts"] += otl
            else:
                r["l"] += 1
    rows = list(rec.values())
    rows.sort(key=lambda r: (-r["pts"] / max(1, r["gp"]) if r["gp"] else 0, -r["rw"], -(r["gf"] - r["ga"]), -r["gf"], r["team_id"]))
    rows.sort(key=lambda r: -r["pts"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------------------------------------------------------- playoffs
def _advance(conn, d, seed):
    """End regular seasons that are done; build the next round where one has finished; crown champions."""
    news = []
    for lid, season, phase in conn.execute("SELECT league_id, season, phase FROM lg_seasons WHERE phase IN ('RS','PO')").fetchall():
        if phase == "RS":
            left = conn.execute("SELECT COUNT(*) FROM lg_games WHERE league_id=? AND season=? AND stage IN ('RS','R2') AND played=0",
                                (lid, season)).fetchone()[0]
            if left:
                continue
            po = (leagues(conn).get(lid, (None, {}))[1].get("playoffs") or {})
            if po.get("phase2") and not conn.execute("SELECT 1 FROM lg_games WHERE league_id=? AND season=? AND stage='R2' LIMIT 1",
                                                     (lid, season)).fetchone():
                news += _schedule_phase2(conn, lid, season, d)
                continue
            news += _rs_title(conn, lid, season, d)
            conn.execute("UPDATE lg_seasons SET phase='PO' WHERE league_id=? AND season=?", (lid, season))
            news += _next_round(conn, lid, season, d, seed)
        else:
            cur = conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (lid, season)).fetchone()[0]
            if cur is None:
                news += _next_round(conn, lid, season, d, seed)
                continue
            if conn.execute("SELECT 1 FROM lg_series WHERE league_id=? AND season=? AND round=? AND winner IS NULL",
                            (lid, season, cur)).fetchone():
                continue
            news += _next_round(conn, lid, season, d, seed)
    return news


# ---------------------------------------------------------------- v61: the regular-season title, the Alps' second phase
def _rs_title(conn, lid, season, d):
    """A league that crowns its regular-season winner as well (the Elite League's league title)."""
    abbr, rules = leagues(conn).get(lid, (None, {}))
    if not rules or not rules.get("rs_title"):
        return []
    tbl = standings(conn, lid, season)
    if not tbl:
        return []
    t = tbl[0]["team_id"]
    name = conn.execute("SELECT name FROM teams WHERE team_id=?", (t,)).fetchone()[0]
    text = f"{name} win the {rules['rs_title']} ({tbl[0]['pts']} points)"
    emit(conn, "LEAGUE_CHAMPION", d, text, team_id=t, importance=1, league_id=lid, trophy=rules["rs_title"])
    return [text]


PHASE2_BONUS = {"master": [4, 3, 2, 1, 0], "qual": [3, 2, 1, 0]}


def _phase2_groups(table):
    """The Alps split: the top five into the Master Round, the rest dealt into two Qualification Rounds (6, 9, 10,
    13 / 7, 8, 11, 12), each with its bonus by regular-season place."""
    master = [r["team_id"] for r in table[:5]]
    rest = [r["team_id"] for r in table[5:]]
    a, b = [], []
    for i, t in enumerate(rest):
        (a if i % 4 in (0, 3) else b).append(t)
    out = {"Master Round": [(t, PHASE2_BONUS["master"][i] if i < 5 else 0) for i, t in enumerate(master)]}
    for name, g in (("Qualification Round A", a), ("Qualification Round B", b)):
        out[name] = [(t, PHASE2_BONUS["qual"][i] if i < 4 else 0) for i, t in enumerate(g)]
    return out


def _round_robin(teams):
    """Rounds of a single round robin (the circle method; an odd group has a bye each round)."""
    t = list(teams) + ([None] if len(teams) % 2 else [])
    n, rounds = len(t), []
    for r in range(n - 1):
        rounds.append([(t[i], t[n - 1 - i]) for i in range(n // 2) if t[i] is not None and t[n - 1 - i] is not None])
        t = [t[0]] + [t[-1]] + t[1:-1]
    return rounds


def _schedule_phase2(conn, lid, season, d):
    """After the regular season: each group plays each other twice, a round every other day."""
    conn.execute("CREATE TABLE IF NOT EXISTS lg_groups (league_id INTEGER, season INTEGER, grp TEXT, team_id INTEGER, "
                 "bonus INTEGER, PRIMARY KEY (league_id, season, team_id))")
    table = standings(conn, lid, season)
    groups = _phase2_groups(table)
    day0 = datetime.date.fromisoformat(d) + datetime.timedelta(days=3)
    rows = []
    for grp, members in groups.items():
        for t, bonus in members:
            conn.execute("INSERT OR REPLACE INTO lg_groups VALUES (?,?,?,?,?)", (lid, season, grp, t, bonus))
        rr = _round_robin([t for t, _ in members])
        for leg in (0, 1):
            for k, rnd in enumerate(rr):
                day = (day0 + datetime.timedelta(days=2 * (leg * len(rr) + k))).isoformat()
                for x, y in rnd:
                    h, a = (x, y) if (leg + k) % 2 == 0 else (y, x)
                    rows.append((lid, season, day, h, a))
    conn.executemany("INSERT INTO lg_games (league_id, season, day, home, away, stage) VALUES (?,?,?,?,?,'R2')", rows)
    abbr = leagues(conn)[lid][0]
    return [f"{abbr}: the regular season is over; the Master Round and the Qualification Rounds begin"]


def group_tables(conn, lid, season):
    """{group: [dict(team_id, bonus, gp, w, l, otl, pts, gf, ga, total)]} for a league's second phase, best first."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_groups'").fetchone():
        return {}
    abbr, rules = leagues(conn, every=True).get(lid, (None, {"points": "3pt"}))
    pw, otw, sow, otl, tie = POINTS[rules.get("points", "3pt")]
    out = {}
    rec = {}
    for grp, t, bonus in conn.execute("SELECT grp, team_id, bonus FROM lg_groups WHERE league_id=? AND season=?", (lid, season)):
        rec[t] = dict(team_id=t, grp=grp, bonus=bonus, gp=0, w=0, l=0, otl=0, pts=0, gf=0, ga=0)
    for h, a, hg, ag, ot in conn.execute("SELECT home, away, hg, ag, ot FROM lg_games WHERE league_id=? AND season=? AND "
                                         "stage='R2' AND played=1", (lid, season)):
        for t, gf, ga in ((h, hg, ag), (a, ag, hg)):
            r = rec.get(t)
            if r is None:
                continue
            r["gp"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf > ga:
                r["w"] += 1
                r["pts"] += pw if ot == 0 else otw if ot == 1 else sow
            elif ot in (1, 2):
                r["otl"] += 1
                r["pts"] += otl
            else:
                r["l"] += 1
    for r in rec.values():
        r["total"] = r["pts"] + r["bonus"]
        out.setdefault(r["grp"], []).append(r)
    for g in out.values():
        g.sort(key=lambda r: (-r["total"], -r["bonus"]))
    return dict(sorted(out.items()))


def _phase2_first_round(conn, lid, season, po, start):
    """After the second phase: the Master Round's five go through (seeded 1-5 in its order); the top three of each
    Qualification Round meet in pre-playoffs (A1 v B3, B1 v A3, A2 v B2)."""
    g = group_tables(conn, lid, season)
    master = g.get("Master Round", [])
    qa, qb = g.get("Qualification Round A", []), g.get("Qualification Round B", [])
    top = [dict(team_id=r["team_id"], seed=i, grp="") for i, r in enumerate(master, 1)]
    seed = len(top)
    q = {}
    for place in range(3):                                  # the group winners rank above the runners-up, and so on
        both = sorted([x for x in (qa[place:place + 1] + qb[place:place + 1])], key=lambda r: -r["total"])
        for r in both:
            seed += 1
            q[r["team_id"]] = dict(team_id=r["team_id"], seed=seed, grp="")
    A = [q[r["team_id"]] for r in qa[:3]]
    B = [q[r["team_id"]] for r in qb[:3]]
    if len(A) < 3 or len(B) < 3:
        _store_byes(conn, lid, season, top + A + B)
        return []
    pairs = [(A[0], B[2]), (B[0], A[2]), tuple(sorted((A[1], B[1]), key=lambda x: x["seed"]))]
    _round(conn, lid, season, 1, pairs, po.get("pre", 3), start, label="pre-playoffs")
    _store_byes(conn, lid, season, top)
    return []


def _seeds(conn, lid, season):
    abbr, rules = leagues(conn)[lid]
    return abbr, rules, standings(conn, lid, season)


def _pairs_high_low(teams):
    """[(a, b)] highest seed v lowest, next v next (teams already sorted best first)."""
    out = []
    while len(teams) >= 2:
        out.append((teams[0], teams[-1]))
        teams = teams[1:-1]
    return out


def _round(conn, lid, season, rnd, pairs, best, d, kind="series", label=None, idx0=0):
    for i, (a, b) in enumerate(pairs, idx0):
        conn.execute("INSERT INTO lg_series (league_id, season, round, idx, a, b, seed_a, seed_b, grp, best_of, kind, next_day, label) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (lid, season, rnd, i, a["team_id"], b["team_id"], a.get("seed"), b.get("seed"),
                                                            a.get("grp", ""), best, kind, d, label))


def _survivors(conn, lid, season, rnd):
    """Winners of a round as participant dicts (their original seed and group), in seed order."""
    out = []
    for r in conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=? ORDER BY idx", (lid, season, rnd)):
        win_a = r["winner"] == r["a"]
        out.append(dict(team_id=r["winner"], seed=r["seed_a"] if win_a else r["seed_b"], grp=r["grp"], label=r["label"]))
    return out


def _next_round(conn, lid, season, d, seed):
    """Create the next round of this league's playoffs, or crown the champion. Returns news lines."""
    start = (datetime.date.fromisoformat(d) + datetime.timedelta(days=2)).isoformat()
    if lid == MEMORIAL_ID:
        return _memorial_next(conn, season, start)
    if lid <= PROREL_BASE:
        return _prorel_next(conn, lid, season, d, start, seed)
    abbr, rules, table = _seeds(conn, lid, season)
    po = rules["playoffs"]
    kind = po["kind"]
    rnd = (conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (lid, season)).fetchone()[0] or 0) + 1
    best = po.get("best", [7, 7, 7, 7])
    bo = lambda k: best[min(k, len(best) - 1)]
    seed_of = {r["team_id"]: r["rank"] for r in table}
    part = lambda r, grp="": dict(team_id=r["team_id"], seed=r["rank"], grp=grp)

    need = {"europe": 13 if po.get("phase2") else po.get("direct", 6) + po.get("wild", 4), "conference": 2 * po.get("per_conf", 8),
            "division": 8, "ncaa": 4, "top": po.get("teams", 8)}.get(kind, 4)
    if len(table) < need or kind not in ("europe", "conference", "division", "ncaa", "top"):
        return _small_bracket(conn, lid, season, rnd, table, best, start, d)

    if kind == "top":                                      # v60: the best N of the table, highest v lowest, re-seeded
        alive = [part(r) for r in table[:po.get("teams", 8)]] if rnd == 1 else _alive(conn, lid, season)
        alive.sort(key=lambda x: x["seed"])
        if len(alive) == 1:
            return _crown(conn, lid, season, alive[0]["team_id"], d)
        label = {2: "final", 4: "semifinals", 8: "quarterfinals"}.get(len(alive), "first round")
        _round(conn, lid, season, rnd, _pairs_high_low(alive), bo(rnd - 1), start, label=label)
        return []

    if kind == "europe":
        return _europe(conn, lid, season, rnd, po, table, start, d, random.Random(f"{seed}-{lid}-{season}-{rnd}-pick"))

    if kind == "conference":
        n, byes = po.get("per_conf", 8), po.get("byes", 0)
        confs = defaultdict(list)
        for r in table:
            confs[r["conference"]].append(r)
        if rnd == 1:
            pairs, rest = [], []
            for c, rows in sorted(confs.items()):
                q = [part(r, c) for r in rows[:n]]
                rest += q[:byes]
                pairs += _pairs_high_low(q[byes:])
            _round(conn, lid, season, 1, pairs, bo(0), start, label="first round")
            _store_byes(conn, lid, season, rest)
            return []
        alive = _alive(conn, lid, season)
        if len(alive) == 1:
            return _crown(conn, lid, season, alive[0]["team_id"], d)
        if po.get("reseed_league") or len({a["grp"] for a in alive}) == len(alive):
            alive.sort(key=lambda x: x["seed"])
            pairs = _pairs_high_low(alive)
            label = "final" if len(alive) == 2 else "league round"
        else:
            pairs = []
            for c in sorted({a["grp"] for a in alive}):
                grp = sorted([a for a in alive if a["grp"] == c], key=lambda x: x["seed"])
                pairs += _pairs_high_low(grp)
            label = "conference round"
        _round(conn, lid, season, rnd, pairs, bo(rnd - 1), start, label=label)
        return []

    if kind == "division":
        if rnd == 1:
            divs = defaultdict(list)
            for r in table:
                divs[r["division"] or "League"].append(r)
            pairs, rest = [], []
            for dv, rows in sorted(divs.items()):
                q = po.get("quota") or max(5, min(8, round(0.7 * len(rows))))
                q = min(q, len(rows))
                qual = [part(r, dv) for r in rows[:q]]
                b = max(0, 8 - q) if q > 4 else q
                rest += qual[:b]
                pairs += _pairs_high_low(qual[b:])
            if pairs:
                _round(conn, lid, season, 1, pairs, bo(0), start, label="first round")
                _store_byes(conn, lid, season, rest)
                return []
            _store_byes(conn, lid, season, rest)                  # (ECHL: no first round)
            return _next_round(conn, lid, season, d, seed)
        alive = _alive(conn, lid, season)
        if len(alive) == 1:
            return _crown(conn, lid, season, alive[0]["team_id"], d)
        groups = {a["grp"] for a in alive}
        confs = rules.get("conferences") or {}
        conf_of = {dv: c for c, ds in confs.items() for dv in ds}
        k = sum(1 for x in conn.execute("SELECT DISTINCT round FROM lg_series WHERE league_id=? AND season=? AND label<>'byes'",
                                        (lid, season)))
        if len(alive) > len(groups):                        # still inside the divisions
            pairs = []
            for g in sorted(groups):
                pairs += _pairs_high_low(sorted([a for a in alive if a["grp"] == g], key=lambda x: x["seed"]))
            _round(conn, lid, season, rnd, pairs, bo(min(k, len(best) - 3)), start, label="division round")
        elif len(alive) > 2:                                # division champions meet within the conference
            for a in alive:
                a["grp"] = conf_of.get(a["grp"], a["grp"])
            pairs = []
            for g in sorted({a["grp"] for a in alive}):
                pairs += _pairs_high_low(sorted([a for a in alive if a["grp"] == g], key=lambda x: x["seed"]))
            if any(len([a for a in alive if a["grp"] == g]) != 2 for g in {a["grp"] for a in alive}):
                pairs = _pairs_high_low(sorted(alive, key=lambda x: x["seed"]))
            _round(conn, lid, season, rnd, pairs, best[-2], start, label="conference finals")
        else:
            _round(conn, lid, season, rnd, [tuple(sorted(alive, key=lambda x: x["seed"]))], best[-1], start, label="final")
        return []

    if kind == "ncaa":
        if rnd == 1:
            order = [part(r) for r in sorted(table, key=lambda r: (-(r["pts"] / max(1, r["gp"])), -r["w"]))][:po.get("teams", 16)]
            for i, p in enumerate(order, 1):
                p["seed"] = i
            n = len(order)
            bracket = [1, 16, 8, 9, 5, 12, 4, 13, 3, 14, 6, 11, 7, 10, 2, 15] if n == 16 else list(range(1, n + 1))
            by = {p["seed"]: p for p in order}
            pairs = [(by[bracket[i]], by[bracket[i + 1]]) for i in range(0, len(bracket), 2) if bracket[i] in by and bracket[i + 1] in by]
            _round(conn, lid, season, 1, pairs, 1, start, label="regionals")
            return []
        alive = _survivors(conn, lid, season, rnd - 1)
        if len(alive) == 1:
            return _crown(conn, lid, season, alive[0]["team_id"], d)
        pairs = [(alive[i], alive[i + 1]) for i in range(0, len(alive) - 1, 2)]
        _round(conn, lid, season, rnd, pairs, 1, start, label={4: "Frozen Four", 2: "final"}.get(len(alive), "regionals"))
        return []
    return []


def _choose(rng, options, pts_of):
    """A club picking its playoff opponent: usually the one with the fewest points, now and then the other (form,
    the matchup, a grudge)."""
    opts = sorted(options, key=lambda x: (pts_of.get(x["team_id"], 0), -x["seed"]))
    return opts[0] if len(opts) == 1 or rng.random() < 0.75 else opts[1]


def _europe(conn, lid, season, rnd, po, table, start, d, rng):
    """The European formats (v61): a first round for the clubs below the `direct` places (or the Swiss play-in, or the
    Alps' second phase), then quarterfinals, semifinals and a final; picks, a fixed bracket, two-game rounds on
    aggregate goals and a third-place game as the league plays them."""
    best = po.get("best", [7, 7, 7])
    bo = lambda k: best[min(k, len(best) - 1)]
    part = lambda r, grp="": dict(team_id=r["team_id"], seed=r["rank"], grp=grp)
    seed_of = {r["team_id"]: r["rank"] for r in table}
    pts_of = {r["team_id"]: r["pts"] for r in table}
    nl = po.get("play_in") == "nl"
    if rnd == 1:
        if po.get("phase2"):
            return _phase2_first_round(conn, lid, season, po, start)
        direct, wild = po.get("direct", 6), po.get("wild", 4)
        top = [part(r) for r in table[:direct]]
        pre = [part(r) for r in table[direct:direct + wild]]
        if nl:
            _round(conn, lid, season, 1, [(pre[0], pre[1]), (pre[2], pre[3])], 2, start, "leg2", "play-in")
            _store_byes(conn, lid, season, top)
            return []
        if not pre:
            return _europe_round(conn, lid, season, rnd, po, top, start, d, rng, pts_of)
        if po.get("pre_pick") and len(pre) == 4:            # the best of the four chooses between the two lowest
            pickd = _choose(rng, pre[2:], pts_of)
            rest = [x for x in pre[1:] if x is not pickd]
            pairs = [(pre[0], pickd), (rest[0], rest[1])]
        else:
            pairs = _pairs_high_low(pre)
        _round(conn, lid, season, 1, pairs, po.get("pre", 3), start, label="pre-playoffs" if wild <= 4 else "wild-card round")
        _store_byes(conn, lid, season, top)
        return []
    if nl and rnd == 2 and conn.execute("SELECT 1 FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='play-in'",
                                        (lid, season)).fetchone() and not conn.execute(
            "SELECT 1 FROM lg_series WHERE league_id=? AND season=? AND round=2", (lid, season)).fetchone():
        r1 = conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='play-in' ORDER BY idx",
                          (lid, season)).fetchall()
        loser78 = r1[0]["b"] if r1[0]["winner"] == r1[0]["a"] else r1[0]["a"]
        win910 = r1[1]["winner"]
        kind = "leg2" if r1[0]["kind"] == "leg2" else "agg"
        _round(conn, lid, season, 2, [(dict(team_id=loser78, seed=seed_of[loser78]), dict(team_id=win910, seed=seed_of[win910]))],
               2, start, kind, "play-in")
        return []
    if nl and rnd == 3 and conn.execute("SELECT 1 FROM lg_series WHERE league_id=? AND season=? AND round=2 AND label='play-in'",
                                        (lid, season)).fetchone():
        alive = [dict(team_id=r["winner"], seed=r["seed_a"], grp="") for r in conn.execute(
            "SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='byes'", (lid, season))]
        r1 = conn.execute("SELECT winner FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='play-in' "
                          "ORDER BY idx LIMIT 1", (lid, season)).fetchone()[0]
        r2 = conn.execute("SELECT winner FROM lg_series WHERE league_id=? AND season=? AND round=2", (lid, season)).fetchone()[0]
        alive += [dict(team_id=r1, seed=7, grp=""), dict(team_id=r2, seed=8, grp="")]
    else:
        alive = _alive(conn, lid, season)
    return _europe_round(conn, lid, season, rnd, po, alive, start, d, rng, pts_of)


def _europe_round(conn, lid, season, rnd, po, alive, start, d, rng, pts_of):
    best = po.get("best", [7, 7, 7])
    alive = sorted(alive, key=lambda x: x["seed"])
    if len(alive) == 1:
        return _crown(conn, lid, season, alive[0]["team_id"], d)
    k = {8: 0, 4: 1, 2: 2}.get(len(alive), 0)
    pick = po.get("pick")
    if pick == "top3" and len(alive) == 8:                  # the top three choose from the four below the fourth
        pool, pairs = alive[4:], []
        for picker in alive[:3]:
            o = _choose(rng, pool, pts_of)
            pool.remove(o)
            pairs.append((picker, o))
        pairs.append((alive[3], pool[0]))
    elif pick == "low2":                                    # the best left picks from the two lowest, and so on
        left, pairs = list(alive), []
        while len(left) >= 2:
            picker = left.pop(0)
            o = _choose(rng, left[-2:], pts_of) if len(left) >= 2 else left[0]
            left.remove(o)
            pairs.append((picker, o))
    elif po.get("bracket") and len(alive) in (8, 4) and (len(alive) == 8 or all(a["grp"].startswith("B") for a in alive)):
        if len(alive) == 8:                                 # 1 v 8, 2 v 7, 3 v 6, 4 v 5; the 1/8 and 4/5 winners meet
            pairs = [(alive[i], alive[7 - i]) for i in range(4)]
            for i, (x, y) in enumerate(pairs):
                x["grp"] = y["grp"] = f"B{i}"
        else:
            by = {a["grp"]: a for a in alive}
            pairs = [tuple(sorted((by["B0"], by["B3"]), key=lambda x: x["seed"])),
                     tuple(sorted((by["B1"], by["B2"]), key=lambda x: x["seed"]))]
            for x, y in pairs:
                x["grp"] = y["grp"] = ""
    else:
        pairs = _pairs_high_low(alive)
    legs = k in (po.get("legs") or [])
    label = ["quarterfinals", "semifinals", "final"][k]
    _round(conn, lid, season, rnd, pairs, 2 if legs else best[min(k, len(best) - 1)], start, "leg2" if legs else "series", label)
    if len(alive) == 2 and po.get("bronze"):               # the semifinal losers play for third place
        losers = []
        for r in conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=? AND kind<>'bye' AND "
                              "COALESCE(label,'')<>'bronze'", (lid, season, rnd - 1)):
            lo = r["b"] if r["winner"] == r["a"] else r["a"]
            losers.append(dict(team_id=lo, seed=r["seed_b"] if lo == r["b"] else r["seed_a"], grp=""))
        if len(losers) == 2:
            _round(conn, lid, season, rnd, [tuple(sorted(losers, key=lambda x: x["seed"] or 99))], po["bronze"], start,
                   label="bronze", idx0=1)
    return []


def _small_bracket(conn, lid, season, rnd, table, best, start, d):
    """A league too small for its format (a test world, a league that lost clubs): the best half (a power of two, two
    to eight clubs) in a straight bracket, highest seed v lowest."""
    if rnd == 1:
        n = 2
        while n * 2 <= min(8, max(2, len(table) // 2)):
            n *= 2
        if len(table) < 2:
            return _crown(conn, lid, season, table[0]["team_id"], d) if table else []
        _round(conn, lid, season, 1, _pairs_high_low([dict(team_id=r["team_id"], seed=r["rank"], grp="") for r in table[:n]]),
               best[0], start, label="final" if n == 2 else "playoffs")
        return []
    alive = sorted(_alive(conn, lid, season), key=lambda x: x["seed"])
    if len(alive) == 1:
        return _crown(conn, lid, season, alive[0]["team_id"], d)
    _round(conn, lid, season, rnd, _pairs_high_low(alive), best[min(rnd - 1, len(best) - 1)], start,
           label="final" if len(alive) == 2 else "playoffs")
    return []


def _store_byes(conn, lid, season, parts):
    """Teams resting a round are stored as a finished pseudo-series (label 'byes') so the next round sees them."""
    rnd = conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (lid, season)).fetchone()[0] or 1
    for i, p in enumerate(parts):
        conn.execute("INSERT INTO lg_series (league_id, season, round, idx, a, b, seed_a, seed_b, grp, best_of, kind, winner, label) "
                     "VALUES (?,?,?,?,?,NULL,?,NULL,?,0,'bye',?, 'byes')", (lid, season, rnd, 100 + i, p["team_id"], p["seed"],
                                                                           p.get("grp", ""), p["team_id"]))


def _alive(conn, lid, season):
    """Teams still in: winners of the last round plus any resting on a bye in it."""
    rnd = conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (lid, season)).fetchone()[0]
    out = []
    for r in conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=? AND COALESCE(label,'')<>'bronze'",
                          (lid, season, rnd)):
        win_a = r["winner"] == r["a"]
        out.append(dict(team_id=r["winner"], seed=r["seed_a"] if win_a else r["seed_b"], grp=r["grp"] or ""))
    return out


def _schedule_series_game(conn, s, d):
    """Put the next game of a series on today's card (once)."""
    if conn.execute("SELECT 1 FROM lg_games WHERE series_id=? AND played=0", (s["series_id"],)).fetchone():
        return
    n = s["games"]
    home_a = n in (0, 1, 4, 6) if s["best_of"] >= 5 else n in (0, 2) if s["kind"] != "agg" else n == 1
    if s["kind"] in ("agg", "leg2"):
        home_a = n == 1                                    # the better seed hosts the return game
    h, a = (s["a"], s["b"]) if home_a else (s["b"], s["a"])
    conn.execute("INSERT INTO lg_games (league_id, season, day, home, away, stage, series_id) VALUES (?,?,?,?,?,'PO',?)",
                 (s["league_id"], s["season"], d, h, a, s["series_id"]))


def _series_result(conn, sid, home, hg, ag, ot):
    s = conn.execute("SELECT * FROM lg_series WHERE series_id=?", (sid,)).fetchone()
    a_home = home == s["a"]
    ga, gb = (hg, ag) if a_home else (ag, hg)
    games = s["games"] + 1
    if s["kind"] == "agg":                                 # two games on points (3 a win, 1 a draw); a tie after two: OT goal
        pa = s["pts_a"] + (3 if ga > gb else 1 if ga == gb else 0)
        pb = s["pts_b"] + (3 if gb > ga else 1 if ga == gb else 0)
        winner = None
        if games >= 2:
            winner = s["a"] if pa > pb or (pa == pb and ga > gb) else s["b"]
        conn.execute("UPDATE lg_series SET pts_a=?, pts_b=?, games=?, winner=?, next_day=? WHERE series_id=?",
                     (pa, pb, games, winner, _after(conn, sid, 2), sid))
        return
    if s["kind"] == "leg2":                                # v61: two games, aggregate goals (the second leg's overtime
        pa, pb = s["pts_a"] + ga, s["pts_b"] + gb          # settles a level aggregate)
        winner = (s["a"] if pa > pb else s["b"]) if games >= 2 else None
        conn.execute("UPDATE lg_series SET pts_a=?, pts_b=?, wins_a=?, wins_b=?, games=?, winner=?, next_day=? WHERE series_id=?",
                     (pa, pb, s["wins_a"] + (ga > gb), s["wins_b"] + (gb > ga), games, winner, _after(conn, sid, 1), sid))
        return
    wa, wb = s["wins_a"] + (ga > gb), s["wins_b"] + (gb > ga)
    need = s["best_of"] // 2 + 1
    winner = s["a"] if wa >= need else s["b"] if wb >= need else None
    conn.execute("UPDATE lg_series SET wins_a=?, wins_b=?, games=?, winner=?, next_day=? WHERE series_id=?",
                 (wa, wb, games, winner, _after(conn, sid, 1 + (games % 2)), sid))


def _after(conn, sid, k):
    d = conn.execute("SELECT MAX(day) FROM lg_games WHERE series_id=?", (sid,)).fetchone()[0]
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=k)).isoformat()


def _crown(conn, lid, season, champ, d):
    last = conn.execute("SELECT a, b FROM lg_series WHERE league_id=? AND season=? AND kind<>'bye' AND COALESCE(label,'')<>'bronze' "
                        "ORDER BY round DESC, idx LIMIT 1", (lid, season)).fetchone()
    runner = (last[1] if last[0] == champ else last[0]) if last else None
    conn.execute("UPDATE lg_seasons SET phase='done', champion=?, runner_up=?, finished=? WHERE league_id=? AND season=?",
                 (champ, runner, d, lid, season))
    if lid == MEMORIAL_ID:
        name = MEMORIAL["name"]
    else:
        abbr, rules = leagues(conn)[lid]
        name = rules["trophy"]
    team = conn.execute("SELECT name, nickname FROM teams WHERE team_id=?", (champ,)).fetchone()
    tname = f"{team[0]} {team[1] or ''}".strip() if team else "?"
    text = f"{tname} win the {name}" + (f", beating {conn.execute('SELECT name FROM teams WHERE team_id=?', (runner,)).fetchone()[0]} in the final" if runner else "")
    emit(conn, "LEAGUE_CHAMPION", d, text, team_id=champ, other_team_id=runner, importance=2, league_id=lid, trophy=name)
    me = user_team(conn)
    parent = conn.execute("SELECT parent_team_id FROM teams WHERE team_id=?", (champ,)).fetchone()
    if me and parent and parent[0] == me:
        add_message(conn, d, f"Our affiliate wins the {name}", f"{tname} have won the {name}. A good sign for the kids in the system.",
                    sender="Director of player development")
    if lid != MEMORIAL_ID and leagues(conn)[lid][0] in MEMORIAL["leagues"]:
        _memorial_maybe(conn, season, d)
    return [text]


# ---------------------------------------------------------------- v61: promotion and relegation
def _ensure_moves(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS lg_moves (season INTEGER, team_id INTEGER, from_lid INTEGER, to_lid INTEGER, "
                 "reason TEXT, applied INTEGER DEFAULT 0, up INTEGER DEFAULT 0, PRIMARY KEY (season, team_id))")
    if "up" not in {r[1] for r in conn.execute("PRAGMA table_info(lg_moves)")}:
        conn.execute("ALTER TABLE lg_moves ADD COLUMN up INTEGER DEFAULT 0")


def prorel_pairs(conn):
    """[(upper league id, lower league id, the lower league's promote rule)] for the pairs both in the world and in play."""
    lg = leagues(conn)
    by_abbr = {abbr: lid for lid, (abbr, _) in lg.items()}
    out = []
    for lid, (abbr, rules) in lg.items():
        pr = rules.get("promote")
        if pr and pr.get("into") in by_abbr:
            out.append((by_abbr[pr["into"]], lid, pr))
    return out


def _ensure_prorel(conn, year):
    for up, low, pr in prorel_pairs(conn):
        pid = PROREL_BASE - up
        if not conn.execute("SELECT 1 FROM lg_seasons WHERE league_id=? AND season=?", (pid, year)).fetchone():
            conn.execute("INSERT INTO lg_seasons (league_id, season, phase) VALUES (?,?,'PO')", (pid, year))


def apply_moves(conn, year):
    """At the start of a season: clubs that went up or down last season change leagues (with their players)."""
    _ensure_moves(conn)
    out = []
    for season, t, a, b, reason in conn.execute("SELECT season, team_id, from_lid, to_lid, reason FROM lg_moves WHERE applied=0 "
                                                "AND season<?", (year,)).fetchall():
        conn.execute("UPDATE teams SET league_id=? WHERE team_id=? AND league_id=?", (b, t, a))
        conn.execute("UPDATE lg_moves SET applied=1 WHERE season=? AND team_id=?", (season, t))
        out.append((t, a, b))
    return out


def _move(conn, season, team, frm, to, reason, d, up):
    _ensure_moves(conn)
    conn.execute("INSERT OR REPLACE INTO lg_moves (season, team_id, from_lid, to_lid, reason, up) VALUES (?,?,?,?,?,?)",
                 (season, team, frm, to, reason, 1 if up else 0))
    name = conn.execute("SELECT name FROM teams WHERE team_id=?", (team,)).fetchone()[0]
    la, lb = (conn.execute("SELECT abbr FROM leagues WHERE league_id=?", (x,)).fetchone()[0] for x in (frm, to))
    text = f"{name} {'are promoted to the' if up else 'are relegated to the'} {lb} for next season ({reason})"
    emit(conn, "LEAGUE_MOVE", d, text, team_id=team, importance=2 if up else 1, league_id=frm)
    return text


def _prorel_next(conn, pid, season, d, start, seed):
    """The upper league's playout and the qualification with the lower league's champion, as each pair plays it."""
    up = PROREL_BASE - pid
    pair = next(((u, l, pr) for u, l, pr in prorel_pairs(conn) if u == up), None)
    done = lambda: conn.execute("UPDATE lg_seasons SET phase='over', finished=? WHERE league_id=? AND season=?", (d, pid, season)) and []
    if pair is None:
        return done()
    _, low, pr = pair
    how = pr.get("how")
    ph = lambda lid: (conn.execute("SELECT phase FROM lg_seasons WHERE league_id=? AND season=?", (lid, season)).fetchone() or [None])[0]
    up_rs_over = ph(up) in ("PO", "done")
    low_champ = conn.execute("SELECT champion FROM lg_seasons WHERE league_id=? AND season=? AND phase='done'", (low, season)).fetchone()
    low_champ = low_champ[0] if low_champ else None
    series = conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? ORDER BY round", (pid, season)).fetchall()
    if series and series[-1]["winner"] is None:
        return []
    up_abbr = leagues(conn)[up][0]
    up_rules = leagues(conn)[up][1]
    rng = random.Random(f"{seed}-{season}-{up}-prorel")
    applies = rng.random() < pr.get("apply", 1.0)
    if not up_rs_over:
        return []
    table = standings(conn, up, season)
    if len(table) < 3:
        return done()
    seed_of = {r["team_id"]: r["rank"] for r in table}
    part = lambda t: dict(team_id=t, seed=seed_of.get(t), grp="")
    news = []
    if how in ("playout", "playout_series") and not series:      # the two last above play out, best-of-7
        a, b = table[-2]["team_id"], table[-1]["team_id"]
        _round(conn, pid, season, 1, [(part(a), part(b))], up_rules.get("playout", 7), start, label="play-out")
        return [f"{up_abbr} play-out: {conn.execute('SELECT name FROM teams WHERE team_id=?', (a,)).fetchone()[0]} v "
                f"{conn.execute('SELECT name FROM teams WHERE team_id=?', (b,)).fetchone()[0]}"]
    if low_champ is None:
        return []
    champ_name = conn.execute("SELECT name FROM teams WHERE team_id=?", (low_champ,)).fetchone()[0]
    low_abbr = leagues(conn)[low][0]
    if how == "playout":
        loser = series[0]["b"] if series[0]["winner"] == series[0]["a"] else series[0]["a"]
        if applies:
            news.append(_move(conn, season, low_champ, low, up, f"{low_abbr} champions", d, True))
            news.append(_move(conn, season, loser, up, low, "lost the play-out", d, False))
        return done() or news
    if how == "direct":
        if applies:
            news.append(_move(conn, season, low_champ, low, up, f"{low_abbr} champions", d, True))
            news.append(_move(conn, season, table[-1]["team_id"], up, low, f"last in the {up_abbr}", d, False))
        else:
            news.append(f"{champ_name} win the {low_abbr} but have no licence for the {up_abbr}: nobody goes up or down")
        return done() or news
    # a series between the club above and the champion below
    if len(series) == (1 if how == "playout_series" else 0):
        if not applies:
            news.append(f"{champ_name} do not apply for promotion: no qualification series with the {up_abbr}")
            return done() or news
        top = table[-1]["team_id"] if how == "series" else \
            (series[0]["b"] if series[0]["winner"] == series[0]["a"] else series[0]["a"])
        _round(conn, pid, season, len(series) + 1, [(part(top), dict(team_id=low_champ, seed=None, grp=""))], 7, start,
               label="league qualification")
        return [f"League qualification: {conn.execute('SELECT name FROM teams WHERE team_id=?', (top,)).fetchone()[0]} "
                f"({up_abbr}) v {champ_name} ({low_abbr})"]
    q = series[-1]
    if q["winner"] == low_champ:
        news.append(_move(conn, season, low_champ, low, up, "won the league qualification", d, True))
        news.append(_move(conn, season, q["a"], up, low, "lost the league qualification", d, False))
    else:
        news.append(f"{conn.execute('SELECT name FROM teams WHERE team_id=?', (q['a'],)).fetchone()[0]} keep their {up_abbr} place")
    return done() or news


# ---------------------------------------------------------------- the Memorial Cup
def _memorial_maybe(conn, season, d):
    ids = {abbr: lid for lid, (abbr, _) in leagues(conn).items()}
    champs = {}
    for ab in MEMORIAL["leagues"]:
        lid = ids.get(ab)
        r = conn.execute("SELECT champion FROM lg_seasons WHERE league_id=? AND season=? AND phase='done'", (lid, season)).fetchone() if lid else None
        if not r:
            return
        champs[ab] = r[0]
    if conn.execute("SELECT 1 FROM lg_seasons WHERE league_id=? AND season=?", (MEMORIAL_ID, season)).fetchone():
        return
    host_league = MEMORIAL["leagues"][season % 3]
    table = standings(conn, ids[host_league], season)
    host = next((r["team_id"] for r in table if r["team_id"] not in champs.values()), None)
    field = list(champs.values()) + ([host] if host else [])
    conn.execute("INSERT INTO lg_seasons (league_id, season, phase) VALUES (?,?,'PO')", (MEMORIAL_ID, season))
    start = (datetime.date.fromisoformat(d) + datetime.timedelta(days=7)).isoformat()
    pairs = [(field[i], field[j]) for i in range(len(field)) for j in range(i + 1, len(field))]
    for k, (a, b) in enumerate(pairs):
        day_k = (datetime.date.fromisoformat(start) + datetime.timedelta(days=k)).isoformat()
        conn.execute("INSERT INTO lg_series (league_id, season, round, idx, a, b, seed_a, seed_b, grp, best_of, kind, next_day, label) "
                     "VALUES (?,?,1,?,?,?,?,?,'',1,'series',?,'round robin')", (MEMORIAL_ID, season, k, a, b, field.index(a) + 1,
                                                                               field.index(b) + 1, day_k))


def _memorial_next(conn, season, start):
    rnd = conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (MEMORIAL_ID, season)).fetchone()[0]
    if rnd == 1:
        rec = defaultdict(lambda: [0, 0])
        for r in conn.execute("SELECT s.winner, g.home, g.away, g.hg, g.ag FROM lg_series s JOIN lg_games g USING (series_id) "
                              "WHERE s.league_id=? AND s.season=? AND s.round=1", (MEMORIAL_ID, season)):
            rec[r[0]][0] += 1
            for t, gf, ga in ((r[1], r[3], r[4]), (r[2], r[4], r[3])):
                rec[t][1] += gf - ga
        teams = {x for r in conn.execute("SELECT a, b FROM lg_series WHERE league_id=? AND season=? AND round=1",
                                          (MEMORIAL_ID, season)) for x in r}
        order = sorted(teams, key=lambda t: (-rec[t][0], -rec[t][1], t))
        if len(order) < 3:
            return _crown(conn, MEMORIAL_ID, season, order[0], start)
        conn.execute("INSERT INTO lg_series (league_id, season, round, idx, a, b, seed_a, seed_b, grp, best_of, kind, next_day, label) "
                     "VALUES (?,?,2,0,?,?,2,3,'',1,'series',?,'semifinal')", (MEMORIAL_ID, season, order[1], order[2], start))
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (f"memorial_top_{season}", str(order[0])))
        return []
    if rnd == 2:
        top = int(conn.execute("SELECT value FROM pack_info WHERE key=?", (f"memorial_top_{season}",)).fetchone()[0])
        sf = conn.execute("SELECT winner FROM lg_series WHERE league_id=? AND season=? AND round=2", (MEMORIAL_ID, season)).fetchone()[0]
        conn.execute("INSERT INTO lg_series (league_id, season, round, idx, a, b, seed_a, seed_b, grp, best_of, kind, next_day, label) "
                     "VALUES (?,?,3,0,?,?,1,2,'',1,'series',?,'final')", (MEMORIAL_ID, season, top, sf, start))
        return []
    w = conn.execute("SELECT winner FROM lg_series WHERE league_id=? AND season=? AND round=3", (MEMORIAL_ID, season)).fetchone()[0]
    return _crown(conn, MEMORIAL_ID, season, w, start)


def finish_year(conn, seed=None):
    """Before the season rolls over: play out anything left (late playoffs, the Memorial Cup)."""
    if not active(conn):
        return []
    return day(conn, "9999-12-31", seed)


# ---------------------------------------------------------------- views
def champions(conn, lid=None):
    ensure_tables(conn)
    q = "SELECT s.league_id, s.season, s.champion, s.runner_up, s.finished FROM lg_seasons s WHERE s.phase='done'"
    rows = conn.execute(q + (" AND s.league_id=?" if lid is not None else "") + " ORDER BY s.season DESC, s.league_id",
                        (lid,) if lid is not None else ()).fetchall()
    return [dict(league_id=r[0], season=r[1], champion=r[2], runner_up=r[3], finished=r[4]) for r in rows]


# ---------------------------------------------------------------- the World Leagues screen (v44)
KIND_GROUP = {"farm": "North American pro", "minor": "North American pro", "europe": "Europe", "junior": "Junior",
              "college": "College"}
POINTS_TEXT = {"2pt": "2 points a win, 1 for an overtime or shootout loss",
               "3pt": "3 points a regulation win, 2 an overtime or shootout win, 1 an overtime or shootout loss"}
PLAYOFF_TEXT = {"europe": "1-6 straight to the quarterfinals, 7-10 in a pre-playoff; then highest seed v lowest",
                "conference": "the best of each conference; then within the conference, highest seed v lowest",
                "division": "a quota from each division; division rounds, conference finals and the final",
                "ncaa": "the 16 best records, single games: regionals, the Frozen Four and the final"}


def _playoff_words(po):
    kind = po.get("kind")
    if kind == "top":
        return f"the best {po.get('teams', 8)} of the table, highest seed v lowest, re-seeded each round"
    if kind != "europe":
        txt = PLAYOFF_TEXT.get(kind, "")
        if po.get("byes"):
            txt = f"the best {po.get('per_conf')} of each conference, the top {po['byes']} resting a round; " + txt.split("; ", 1)[-1]
        return txt
    if po.get("play_in") == "nl":
        return ("1-6 straight to the quarterfinals; a play-in for 7-10: 7 v 8 and 9 v 10 over two games on aggregate goals, "
                "the 7/8 loser then plays the 9/10 winner; then highest seed v lowest")
    if po.get("phase2"):
        txt = ("after the regular season the top five play a Master Round (bonus points 4-3-2-1-0) and the rest two "
               "Qualification Rounds (3-2-1-0); the top three of each Qualification Round meet in pre-playoffs "
               f"(best-of-{po.get('pre', 3)})")
    else:
        direct, wild = po.get("direct", 6), po.get("wild", 4)
        if wild:
            txt = (f"1-{direct} straight to the quarterfinals, {direct + 1}-{direct + wild} in a "
                   f"{'pre-playoff' if wild <= 4 else 'wild-card round'} (best-of-{po.get('pre', 3)})")
            if po.get("pre_pick"):
                txt += f", the {direct + 1}th choosing its opponent"
        else:
            txt = f"the top {direct}"
    if po.get("pick") == "top3":
        txt += "; the top three choose their quarterfinal opponents"
    elif po.get("pick") == "low2":
        txt += "; each round the best club left picks from the two lowest"
    elif po.get("bracket"):
        txt += "; a fixed bracket (1 v 8, 2 v 7, 3 v 6, 4 v 5)"
    else:
        txt += "; then highest seed v lowest"
    if po.get("legs"):
        names = ["quarterfinals", "semifinals", "final"]
        b = po.get("best", [7, 7, 7])
        parts = [f"{names[i]} {'over two games on aggregate goals' if i in po['legs'] else 'a single game' if b[i] == 1 else 'best-of-%d' % b[i]}"
                 for i in range(min(3, len(b)))]
        txt += "; " + ", ".join(parts)
    if po.get("bronze"):
        txt += "; a third-place game"
    return txt


def rules_text(abbr, rules, meta):
    """A league's rules in words (for the screen)."""
    out = []
    if rules:
        out.append(f"{rules['games']} games a club, {POINTS_TEXT.get(rules.get('points'), '')}")
        out.append("ties stand after a 3-on-3 overtime" if rules.get("ot") == "tie" else "3-on-3 overtime, then a shootout")
        po = rules.get("playoffs") or {}
        txt = _playoff_words(po)
        out.append("Playoffs: " + txt + (f"; series best-of-{'/'.join(str(b) for b in po['best'])}" if po.get("best") and
                                         not po.get("legs") else ""))
        if rules.get("rs_title"):
            out.append(f"the regular season's winner takes the {rules['rs_title']}")
        if rules.get("playout"):
            out.append(f"the two last clubs play out (best-of-{rules['playout']}) for their place")
        pr = rules.get("promote")
        if pr:
            out.append({"playout": f"the champion goes up to the {pr['into']} for the loser of its play-out",
                        "direct": f"the champion goes up to the {pr['into']} if it holds the licence; the {pr['into']}'s last club comes down",
                        "series": f"the champion plays the {pr['into']}'s last club, best-of-7, for its place",
                        "playout_series": f"the champion, if it applies, plays the {pr['into']} play-out loser, best-of-7, for its place"}
                       .get(pr.get("how"), f"promotion to the {pr['into']}"))
        if rules.get("imports"):
            out.append(f"at most {rules['imports']} imports a club" + (" (no import goalies)" if rules.get("no_import_goalies") else ""))
        if rules.get("overage"):
            out.append(f"at most {rules['overage']} 20-year-olds a club")
        out.append(f"the champion wins the {rules['trophy']}")
    else:
        out.append(f"{meta.get('games', '?')} games a club (from the database's last season); simulated a season at a time")
        out.append("the champion is the club that comes out on top over the season (no schedule or playoffs are played)")
    if meta:
        if meta.get("kind") == "junior" or meta.get("age_max", 40) < 30:
            out.append(f"players aged {meta.get('age_min', 15)}-{meta.get('age_max')}")
    return out


def world_leagues_view(conn, lid=None, season=None):
    from .world import world_meta
    ensure_tables(conn)
    meta = world_meta(conn)
    real = leagues(conn)
    year = _season_year(conn)
    names = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT team_id, name, abbr FROM teams")}
    champs = {}
    for c in champions(conn):
        champs.setdefault(c["league_id"], c)
    rows = []
    for l, name, abbr, country, level in conn.execute("SELECT league_id, name, abbr, country, level FROM leagues "
                                                      "ORDER BY COALESCE(level, 1), league_id").fetchall():
        if (level or 1) == 1 and l not in meta:
            continue
        m = meta.get(l, {})
        c = champs.get(l)
        rows.append(dict(league_id=l, name=name, abbr=abbr, country=country or m.get("country") or "", level=level,
                         group=KIND_GROUP.get(m.get("kind"), "Other"), clubs=conn.execute(
                             "SELECT COUNT(*) FROM teams WHERE league_id=?", (l,)).fetchone()[0],
                         mode="games" if l in real else "season", strength=m.get("mean"),
                         champion=dict(season=c["season"], team_id=c["champion"], name=names.get(c["champion"], ("?",))[0]) if c else None))
    out = dict(leagues=rows, season=year)
    if lid is None and rows:
        lid = rows[0]["league_id"]
    if lid is None:
        return out
    lid = int(lid)
    season = int(season) if season else year
    abbr, rules = real.get(lid, (None, None))
    m = meta.get(lid, {})
    out.update(league_id=lid, mode="games" if rules else "season", rules=rules_text(abbr, rules, m),
               seasons=sorted({r[0] for r in conn.execute("SELECT DISTINCT season FROM lg_seasons WHERE league_id=?", (lid,))} | {year},
                              reverse=True), shown=season)
    if rules:
        tbl = standings(conn, lid, season)
        for r in tbl:
            r["name"], r["abbr"] = names.get(r["team_id"], ("?", ""))
        out["standings"] = tbl
        ser = []
        for s in conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND kind<>'bye' ORDER BY round, idx",
                              (lid, season)):
            ser.append(dict(round=s["round"], label=s["label"] or "", a=names.get(s["a"], ("?",))[0], b=names.get(s["b"], ("?",))[0],
                            seed_a=s["seed_a"], seed_b=s["seed_b"], wins_a=s["wins_a"], wins_b=s["wins_b"], pts_a=s["pts_a"],
                            pts_b=s["pts_b"], kind=s["kind"], best_of=s["best_of"], winner=names.get(s["winner"], (None,))[0]))
        out["series"] = ser
        groups = group_tables(conn, lid, season)
        for rows in groups.values():
            for r in rows:
                r["name"], r["abbr"] = names.get(r["team_id"], ("?", ""))
        out["groups"] = groups
        pro = []                                           # v61: the play-out and the qualification with the next tier
        for up, low, pr in prorel_pairs(conn):
            if lid not in (up, low):
                continue
            for x in conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? ORDER BY round", (PROREL_BASE - up, season)):
                pro.append(dict(label=x["label"], a=names.get(x["a"], ("?",))[0], b=names.get(x["b"], ("?",))[0], wins_a=x["wins_a"],
                                wins_b=x["wins_b"], best_of=x["best_of"], winner=names.get(x["winner"], (None,))[0]))
        _ensure_moves(conn)
        out["prorel"] = pro
        out["moves"] = [dict(name=names.get(t, ("?",))[0], up=bool(u), reason=r)
                        for t, u, r in conn.execute("SELECT team_id, up, reason FROM lg_moves WHERE season=? AND "
                                                    "(from_lid=? OR to_lid=?)", (season, lid, lid))]
        nxt = conn.execute("SELECT MIN(day) FROM lg_games WHERE league_id=? AND season=? AND played=0", (lid, season)).fetchone()[0]
        out["next_game"] = nxt
    else:
        from .world import load_attrs, overall
        clubs = []
        for t, name in conn.execute("SELECT team_id, name FROM teams WHERE league_id=? ORDER BY name", (lid,)).fetchall():
            rs = load_attrs(conn, "p.club_id=? AND p.status<>'retired'", (t,))
            sk = sorted((overall(r) for r in rs.values() if r["position"] != "G"), reverse=True)[:18]
            clubs.append(dict(team_id=t, name=name, players=len(rs), strength=round(sum(sk) / len(sk), 2) if sk else None))
        clubs.sort(key=lambda c: -(c["strength"] or 0))
        out["clubs"] = clubs
    sy = season if conn.execute("SELECT 1 FROM skater_season_stats WHERE league_id=? AND season_start_year=? AND split='RS' "
                                "AND COALESCE(source,'')<>'history'", (lid, season)).fetchone() else season - 1
    out["leaders_season"] = sy
    out["leaders"] = [dict(player_id=r[0], name=r[1], team=names.get(r[2], ("",))[0], gp=r[3], g=r[4], a=r[5], p=r[4] + r[5])
                      for r in conn.execute(
        "SELECT s.player_id, p.first_name||' '||p.last_name, s.team_id, s.gp, s.g, s.a FROM skater_season_stats s JOIN players p "
        "USING (player_id) WHERE s.league_id=? AND s.season_start_year=? AND s.split='RS' ORDER BY s.g+s.a DESC, s.g DESC LIMIT 20",
        (lid, sy))]
    out["champions"] = [dict(season=c["season"], champion=names.get(c["champion"], ("?",))[0], champion_id=c["champion"],
                             runner_up=names.get(c["runner_up"], (None,))[0]) for c in champions(conn, lid)]
    return out
