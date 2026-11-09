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


def leagues(conn):
    """{league_id: (abbr, rules)} for leagues in the world that have rules (not the top league)."""
    out = {}
    for lid, name, abbr, level in conn.execute("SELECT league_id, name, abbr, level FROM leagues"):
        if (level or 1) == 1:
            continue
        for k in (abbr, name):
            key = (k or "").upper().replace(" ", "")
            if key in RULES:
                out[lid] = (key, RULES[key])
                break
    return out


def active(conn):
    """The leagues play for real once a save has scheduled them (v44 on)."""
    ensure_tables(conn)
    return bool(conn.execute("SELECT 1 FROM lg_games LIMIT 1").fetchone())


def _clubs(conn, lid):
    return [dict(team_id=r[0], division=(r[1] or "").strip(), conference=(r[2] or "").strip())
            for r in conn.execute("SELECT team_id, division, conference FROM teams WHERE league_id=? ORDER BY team_id", (lid,))]


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
def _pair_counts(clubs, games, rng):
    """{(i, j): games} for every pair: more games inside the division (or the whole league when there is none),
    as close to `games` each as the alignment allows."""
    n = len(clubs)
    groups = defaultdict(list)
    for i, c in enumerate(clubs):
        groups[c["division"] or "all"].append(i)
    if len(groups) == 1:
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
    counts = _pair_counts(clubs, rules["games"], rng)
    games = []
    for (i, j), k in counts.items():
        for g in range(k):
            h, a = (i, j) if (g % 2 == 0) == (rng.random() < 0.5) else (j, i)
            games.append((clubs[h]["team_id"], clubs[a]["team_id"]))
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
    for lid, (abbr, rules) in sorted(leagues(conn).items()):
        if conn.execute("SELECT 1 FROM lg_seasons WHERE league_id=? AND season=?", (lid, year)).fetchone():
            continue
        made += make_schedule(conn, lid, year, random.Random(f"{seed}-{year}-{abbr}-schedule"))
        conn.execute("INSERT INTO lg_seasons (league_id, season, phase) VALUES (?,?,'RS')", (lid, year))
    return made


# ---------------------------------------------------------------- the results model
class Club:
    __slots__ = ("team_id", "fwd", "dmen", "goalies", "attack", "ghosts")

    def __init__(self, team_id, rows, mean):
        from .world import overall
        sk = sorted(((overall(r), r["player_id"], r["position"]) for r in rows if r["position"] != "G"), reverse=True)
        self.team_id = team_id
        self.fwd = [(v, p) for v, p, pos in sk if pos != "D"][:12]
        self.dmen = [(v, p) for v, p, pos in sk if pos == "D"][:6]
        self.goalies = sorted(((overall(r), r["player_id"]) for r in rows if r["position"] == "G"), reverse=True)[:3]
        vals = [v for v, _ in self.fwd] + [mean - 1.5] * (12 - len(self.fwd)) + \
               [v * 0.8 + mean * 0.2 for v, _ in self.dmen] + [mean - 1.5] * (6 - len(self.dmen))
        self.attack = sum(vals) / len(vals)
        self.ghosts = 18 - len(self.fwd) - len(self.dmen)

    def goalie(self, rng, mean):
        if not self.goalies:
            return None, mean - 1.5
        g = self.goalies[0] if rng.random() < 0.7 or len(self.goalies) == 1 else self.goalies[1]
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


def play(rng, home, away, gpg, g_mean, playoff=False, ties=False, stats=None, split="RS", lid=None, year=None):
    """One game: (home goals, away goals, ot) with ot 0 regulation, 1 overtime, 2 shootout, 3 tie. Adds player
    lines to `stats` ({(pid, team, kind): [...]})."""
    gh_id, gh = home.goalie(rng, g_mean)
    ga_id, ga_ = away.goalie(rng, g_mean)
    lam_h = gpg * math.exp(ATTACK_K * (home.attack - away.attack) - GOALIE_K * (ga_ - g_mean) + HOME)
    lam_a = gpg * math.exp(ATTACK_K * (away.attack - home.attack) - GOALIE_K * (gh - g_mean) - HOME)
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
    if hg == ag:
        p_home = lam_h / (lam_h + lam_a)
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
    from .world import load_attrs, overall
    if not team_ids:
        return {}, {}
    q = ",".join("?" * len(team_ids))
    rows = load_attrs(conn, f"p.club_id IN ({q}) AND p.status IN ('active','prospect')", list(team_ids))
    by = defaultdict(list)
    for r in rows.values():
        by[r["club_id"]].append(r)
    lg = {r[0]: r[1] for r in conn.execute(f"SELECT team_id, league_id FROM teams WHERE team_id IN ({q})", list(team_ids))}
    means, gmeans = defaultdict(list), defaultdict(list)
    for t, rs in by.items():
        for r in rs:
            (gmeans if r["position"] == "G" else means)[lg[t]].append(overall(r))
    mean = {l: sum(v) / len(v) for l, v in means.items() if v}
    gmean = {l: sum(v) / len(v) for l, v in gmeans.items() if v}
    clubs = {t: Club(t, by.get(t, []), mean.get(lg[t], 8.5)) for t in team_ids}
    return clubs, {l: (mean.get(l, 8.5), gmean.get(l, 8.5)) for l in set(lg.values())}


# ---------------------------------------------------------------- the day
def day(conn, today, seed=None):
    """Play every league game due on or before today; move the playoffs on. Returns news lines."""
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
        news += _play_day(conn, d, seed)
        news += _advance(conn, d, seed)
    return news


def _play_day(conn, d, seed):
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
    for g in games:
        lid = g["league_id"]
        rules = lg_rules.get(lid, (None, {}))[1] if lid != MEMORIAL_ID else dict(gpg=3.4, ot="so")
        rng = random.Random(f"{seed}-lg-{g['game_id']}")
        po = g["stage"] == "PO"
        mean, gmean = means.get(league_of.get(g["home"]), (8.5, 8.5))
        agg_first = bool(g["series_id"]) and _is_agg(conn, g["series_id"])     # a two-game play-in's first game can be drawn
        hg, ag, ot = play(rng, clubs[g["home"]], clubs[g["away"]], rules.get("gpg", 3.0), gmean, playoff=po and not agg_first,
                          ties=(rules.get("ot") == "tie" and not po) or agg_first, stats=stats, split="PO" if po else "RS")
        conn.execute("UPDATE lg_games SET hg=?, ag=?, ot=?, played=1 WHERE game_id=?", (hg, ag, ot, g["game_id"]))
        if g["series_id"]:
            _series_result(conn, g["series_id"], g["home"], hg, ag, ot)
    _flush(conn, year, stats, league_of)
    return []


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
                              l=0, otl=0, t=0, pts=0, gf=0, ga=0, rw=0) for c in _clubs(conn, lid)}
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
            left = conn.execute("SELECT COUNT(*) FROM lg_games WHERE league_id=? AND season=? AND stage='RS' AND played=0",
                                (lid, season)).fetchone()[0]
            if left:
                continue
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


def _round(conn, lid, season, rnd, pairs, best, d, kind="series", label=None):
    for i, (a, b) in enumerate(pairs):
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
    abbr, rules, table = _seeds(conn, lid, season)
    po = rules["playoffs"]
    kind = po["kind"]
    rnd = (conn.execute("SELECT MAX(round) FROM lg_series WHERE league_id=? AND season=?", (lid, season)).fetchone()[0] or 0) + 1
    best = po.get("best", [7, 7, 7, 7])
    bo = lambda k: best[min(k, len(best) - 1)]
    seed_of = {r["team_id"]: r["rank"] for r in table}
    part = lambda r, grp="": dict(team_id=r["team_id"], seed=r["rank"], grp=grp)

    need = {"europe": 10, "conference": 2 * po.get("per_conf", 8), "division": 8, "ncaa": 4}.get(kind, 4)
    if len(table) < need or kind not in ("europe", "conference", "division", "ncaa"):
        return _small_bracket(conn, lid, season, rnd, table, best, start, d)

    if kind == "europe":
        if rnd == 1:
            top = [part(r) for r in table[:6]]
            pre = [part(r) for r in table[6:10]]
            if po.get("play_in") == "nl":
                _round(conn, lid, season, 1, [(pre[0], pre[1]), (pre[2], pre[3])], 2, start, "agg", "play-in")
                _store_byes(conn, lid, season, top)
                return []
            _round(conn, lid, season, 1, [(pre[0], pre[3]), (pre[1], pre[2])], po.get("pre", 3), start, label="pre-playoffs")
            _store_byes(conn, lid, season, top)
            return []
        if po.get("play_in") == "nl" and rnd == 2:
            r1 = conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='play-in' ORDER BY idx",
                              (lid, season)).fetchall()
            loser78 = r1[0]["b"] if r1[0]["winner"] == r1[0]["a"] else r1[0]["a"]
            win910 = r1[1]["winner"]
            _round(conn, lid, season, 2, [(dict(team_id=loser78, seed=seed_of[loser78]), dict(team_id=win910, seed=seed_of[win910]))],
                   2, start, "agg", "play-in")
            return []
        if po.get("play_in") == "nl" and rnd == 3:          # the six who rested, the 7/8 winner, the play-in's last winner
            alive = [dict(team_id=r["winner"], seed=r["seed_a"], grp="") for r in conn.execute(
                "SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='byes'", (lid, season))]
            r1 = conn.execute("SELECT winner FROM lg_series WHERE league_id=? AND season=? AND round=1 AND label='play-in' "
                              "ORDER BY idx LIMIT 1", (lid, season)).fetchone()[0]
            r2 = conn.execute("SELECT winner FROM lg_series WHERE league_id=? AND season=? AND round=2", (lid, season)).fetchone()[0]
            alive += [dict(team_id=r1, seed=7, grp=""), dict(team_id=r2, seed=8, grp="")]
        else:
            alive = _alive(conn, lid, season)
        alive.sort(key=lambda x: x["seed"])
        if len(alive) == 1:
            return _crown(conn, lid, season, alive[0]["team_id"], d)
        k = {8: 0, 4: 1, 2: 2}.get(len(alive), 0)
        _round(conn, lid, season, rnd, _pairs_high_low(alive), bo(k), start, label=["quarterfinals", "semifinals", "final"][k])
        return []

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
    for r in conn.execute("SELECT * FROM lg_series WHERE league_id=? AND season=? AND round=?", (lid, season, rnd)):
        win_a = r["winner"] == r["a"]
        out.append(dict(team_id=r["winner"], seed=r["seed_a"] if win_a else r["seed_b"], grp=r["grp"]))
    return out


def _schedule_series_game(conn, s, d):
    """Put the next game of a series on today's card (once)."""
    if conn.execute("SELECT 1 FROM lg_games WHERE series_id=? AND played=0", (s["series_id"],)).fetchone():
        return
    n = s["games"]
    home_a = n in (0, 1, 4, 6) if s["best_of"] >= 5 else n in (0, 2) if s["kind"] != "agg" else n == 1
    if s["kind"] == "agg":
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
    wa, wb = s["wins_a"] + (ga > gb), s["wins_b"] + (gb > ga)
    need = s["best_of"] // 2 + 1
    winner = s["a"] if wa >= need else s["b"] if wb >= need else None
    conn.execute("UPDATE lg_series SET wins_a=?, wins_b=?, games=?, winner=?, next_day=? WHERE series_id=?",
                 (wa, wb, games, winner, _after(conn, sid, 1 + (games % 2)), sid))


def _after(conn, sid, k):
    d = conn.execute("SELECT MAX(day) FROM lg_games WHERE series_id=?", (sid,)).fetchone()[0]
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=k)).isoformat()


def _crown(conn, lid, season, champ, d):
    last = conn.execute("SELECT a, b FROM lg_series WHERE league_id=? AND season=? AND kind<>'bye' ORDER BY round DESC, idx LIMIT 1",
                        (lid, season)).fetchone()
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


def rules_text(abbr, rules, meta):
    """A league's rules in words (for the screen)."""
    out = []
    if rules:
        out.append(f"{rules['games']} games a club, {POINTS_TEXT.get(rules.get('points'), '')}")
        out.append("ties stand after a 3-on-3 overtime" if rules.get("ot") == "tie" else "3-on-3 overtime, then a shootout")
        po = rules.get("playoffs") or {}
        txt = PLAYOFF_TEXT.get(po.get("kind"), "")
        if po.get("play_in") == "nl":
            txt = "1-6 straight to the quarterfinals, 7-10 in a two-game play-in; then highest seed v lowest"
        if po.get("pre"):
            txt += f" (pre-playoff best-of-{po['pre']})"
        if po.get("byes"):
            txt = f"the best {po.get('per_conf')} of each conference, the top {po['byes']} resting a round; " + txt.split("; ", 1)[-1]
        out.append("Playoffs: " + txt + (f"; series best-of-{'/'.join(str(b) for b in po['best'])}" if po.get("best") else ""))
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
