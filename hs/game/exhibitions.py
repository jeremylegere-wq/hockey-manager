"""The calendar's exhibitions (phase F, v37): pre-season games, the prospects tournaments, all-star weekend.

All three are played by the real game engine, but none of them touches the standings, the season's statistics or the
box-score tables (games, player_game_stats): they live in their own tables, `exhibitions` (one row a game, or a
skills competition) and `exhibition_stats` (each player's line and his 1-10 game rating).

Pre-season (each club plays `preseason_games`, default 6, in the two weeks before opening night; played when the
regular season is scheduled, `advance` from the pre-season phase). Clubs play nearby clubs (same conference first).
Your camp's prospects (status 'prospect', the best three forwards, two defencemen and a goalie) take the fourth line,
the third pair and every second start in goal for the first half of the games, so the games are an audition. What
pre-season does: line chemistry (hs/game/chemistry.py: lines that play together get better together, relative to the
league, so league totals do not move), injuries at half the regular-season rate, and the camp report in your inbox
(record, who stood out, how the prospects did).

Prospects tournaments (in mid-September, when the pre-season phase opens): one per division, each club's prospects
(22 or younger: signed prospects and unsigned draft picks; tryout invitees from the unattached fill the gaps) play three
group games, then the top two meet in the final. Your scouts watch your tournament: every player in it is better known
(+10 knowledge points, hs/game/scout_net.py).

All-star weekend (the first Saturday of February; none in a season with an Olympic break). Formats (the career option
`allstar`): conference (East against West), draft (the two leading vote-getters pick their teams, alternating), world
(North America against the World). Twenty per side: twelve forwards, six defencemen and two goalies, chosen on this
season's scoring and ability, with every club represented (except in the world format). Defence is optional: every
skater's defensive play and every goalie's saving are lowered
for the game (about a dozen goals, as in the real one). The skills competition the same day: fastest skater, hardest shot,
accuracy shooting, stickhandling and the goalies' save streak, from the players' attributes plus the night.

Career options (pack_info 'calendar_options', CLI `events set <key> <value>`): preseason_games 0-10, allstar
conference|draft|world|off, prospects on|off, hof committee|auto (hs/game/legacy.py).
"""
from __future__ import annotations

import copy
import datetime
import json
import random

from ..schema import top_league_sql
from ..sim.engine import Player, Team, simulate_game
from ..sim.loader import GOALIE_INDICES, SKATER_INDICES, game_ratings, load_teams
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

OPTIONS = {"preseason_games": 6, "allstar": "conference", "prospects": "on", "hof": "committee"}
CHOICES = {"allstar": ("conference", "draft", "world", "off"), "prospects": ("on", "off"), "hof": ("committee", "auto")}
NORTH_AMERICA = {"CAN", "USA"}
DEFENCE_OPTIONAL = 1.2      # all-star game: every skater's defensive play (sup) lowered by this, in the engine's units
GOALIE_OPEN = 0.4           # and every goalie's saving: about a dozen goals a game, as in the real one
SKILLS = {"fastest": ("Fastest skater", "s", True), "hardest": ("Hardest shot", "mph", False),
          "accuracy": ("Accuracy shooting", "s", True), "stickhandling": ("Stickhandling", "s", True),
          "save_streak": ("Save streak", "saves", False)}


# ---------------------------------------------------------------- tables and options
def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS exhibitions (ex_id INTEGER PRIMARY KEY, kind TEXT, season_start_year INTEGER, day TEXT, "
                 "event TEXT, round TEXT, home_id INTEGER, away_id INTEGER, home_name TEXT, away_name TEXT, home_goals INTEGER, "
                 "away_goals INTEGER, ot INTEGER, seed INTEGER, notes TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS exhibition_stats (ex_id INTEGER, player_id INTEGER, team_id INTEGER, side INTEGER, "
                 "toi INTEGER, g INTEGER, a INTEGER, sog INTEGER, saves INTEGER, sa INTEGER, rating REAL, PRIMARY KEY (ex_id, player_id))")


def options(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='calendar_options'").fetchone()
    out = dict(OPTIONS)
    if r:
        try:
            out.update({k: v for k, v in json.loads(r[0]).items() if k in OPTIONS})
        except ValueError:
            pass
    return out


def set_option(conn, key, value):
    if key not in OPTIONS:
        raise ValueError(f"Options: {', '.join(OPTIONS)}.")
    if key == "preseason_games":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError("preseason_games is a number, 0 to 10.")
        if not 0 <= value <= 10:
            raise ValueError("preseason_games is 0 to 10.")
    elif value not in CHOICES[key]:
        raise ValueError(f"{key}: {' | '.join(CHOICES[key])}.")
    o = options(conn)
    o[key] = value
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('calendar_options', ?)", (json.dumps(o),))
    return o


def _seed(conn):
    return get_state(conn)[1]


def _season(conn):
    from . import contracts as K
    return K.season_year(conn)


def _overtime(conn):
    from ..league.season import db_rules
    return (db_rules(conn) or {}).get("overtime")


# ---------------------------------------------------------------- engine players outside a club's lineup
def _attrs(conn, pids):
    if not pids:
        return {}
    q = ",".join(str(int(p)) for p in pids)
    return {r["player_id"]: dict(r) for r in conn.execute(
        f"SELECT p.player_id, p.position, p.first_name||' '||p.last_name name, p.nationality, a.* FROM players p JOIN player_attributes a "
        f"USING (player_id) WHERE p.player_id IN ({q})")}


def raw_means(conn, teams):
    """The league's mean of each engine index over dressed players, before load_teams centred them: subtracting it
    puts a player who is not in a lineup on the same scale as everyone loaded."""
    sk = [p.pid for t in teams.values() for p in t.skaters]
    gl = [t.goalies[0].pid for t in teams.values() if t.goalies]
    at = _attrs(conn, sk + gl)
    raw_s = [Player.from_attrs(p, at[p]["position"], at[p]) for p in sk if p in at]
    raw_g = [Player.from_attrs(p, "G", at[p]) for p in gl if p in at]
    m = {n: sum(getattr(p, n) for p in raw_s) / max(1, len(raw_s)) for n in SKATER_INDICES}
    m.update({n: sum(getattr(p, n) for p in raw_g) / max(1, len(raw_g)) for n in GOALIE_INDICES})
    return m


def make_player(a, means, toi=0.0):
    pos = a["position"]
    p = Player.from_attrs(a["player_id"], pos, a, a.get("name", ""), toi, 0)
    for n in (GOALIE_INDICES if pos == "G" else SKATER_INDICES):
        setattr(p, n, getattr(p, n) - means.get(n, 0.0))
    p.toi = toi or (1000 * (p.gen + p.sup + p.qual) / 3 + 5000)
    return p


def _ovr(p):
    return p.save if p.pos == "G" else (p.gen + p.qual + p.fin + p.sup) / 4


def _play(conn, kind, day, event, rnd, home, away, names, env, skill, seed, clubs=None):
    """Simulate one exhibition and store it. clubs: {pid: real club} for the stats rows (default: the side's id)."""
    ensure_tables(conn)
    res = simulate_game(home, away, env, skill, seed, events=True, overtime=_overtime(conn))
    ot = 2 if res.shootout else int(res.went_to_ot)
    cur = conn.execute("INSERT INTO exhibitions (kind, season_start_year, day, event, round, home_id, away_id, home_name, away_name, "
                       "home_goals, away_goals, ot, seed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (kind, int(day[:4]) if kind in ("PS", "PROSPECTS") else _season(conn), day, event, rnd, home.team_id,
                        away.team_id, names[0], names[1], res.goals[0], res.goals[1], ot, seed))
    ex = cur.lastrowid
    goalies = {g.pid for t in (home, away) for g in t.goalies}
    rt = game_ratings(res, goalies)
    pos = {p.pid: p.pos for t in (home, away) for p in t.skaters + t.goalies}
    rows = []
    for pid, s in res.stats.items():
        side = s["team"]
        team = (home, away)[side].team_id
        off, de, ov = rt.get(pid, (None, None, None))
        if ov is None and off is not None:
            ov = round(0.4 * off + 0.6 * de, 1) if pos.get(pid) == "D" else round(0.6 * off + 0.4 * de, 1)
        rows.append((ex, pid, (clubs or {}).get(pid, team), side, s["toi"], s["g"], s["a"], s["sog"], s["saves"], s["sa"], ov))
    conn.executemany("INSERT OR REPLACE INTO exhibition_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return ex, res


# ---------------------------------------------------------------- pre-season
def _pairings(clubs, conf, rng):
    by = {}
    for t in clubs:
        by.setdefault(conf.get(t), []).append(t)
    pairs, left = [], []
    for c in sorted(by, key=str):
        lst = by[c][:]
        rng.shuffle(lst)
        while len(lst) >= 2:
            pairs.append((lst.pop(), lst.pop()))
        left += lst
    while len(left) >= 2:
        pairs.append((left.pop(), left.pop()))
    return [(a, b) if rng.random() < 0.5 else (b, a) for a, b in pairs]


def _camp_prospects(conn, t, means):
    rows = conn.execute("SELECT player_id FROM players WHERE team_id=? AND status='prospect'", (t,)).fetchall()
    at = _attrs(conn, [r[0] for r in rows])
    pl = sorted((make_player(a, means) for a in at.values()), key=lambda p: -_ovr(p))
    f = [p for p in pl if p.pos in ("C", "LW", "RW")][:3]
    d = [p for p in pl if p.pos == "D"][:2]
    g = [p for p in pl if p.pos == "G"][:1]
    return f, d, g


def _camp_team(team, pros, use_pros, goalie_turn):
    t = copy.copy(team)
    t.lines = [list(x) for x in team.lines]
    t.pairs = [list(x) for x in team.pairs]
    t.goalies = list(team.goalies)
    f, d, g = pros
    if use_pros:
        if f and len(t.lines) >= 4:
            t.lines[3] = (f + t.lines[3])[:max(3, len(t.lines[3]))][:3]
        if d and len(t.pairs) >= 3:
            t.pairs[2] = (d + t.pairs[2])[:2]
    if goalie_turn:
        if use_pros and g:
            t.goalies = g + t.goalies
        elif len(t.goalies) >= 2:
            t.goalies = [t.goalies[1], t.goalies[0]] + t.goalies[2:]
    dressed = {p.pid for ln in t.lines for p in ln} | {p.pid for pr in t.pairs for p in pr}
    t.pp = [u for u in team.pp if all(p.pid in dressed for p in u)]
    t.pk = [u for u in team.pk if all(p.pid in dressed for p in u)]
    t.ot3 = [u for u in team.ot3 if all(p.pid in dressed for p in u)]
    t.ot4 = [u for u in team.ot4 if all(p.pid in dressed for p in u)]
    t.skaters = [p for ln in t.lines for p in ln] + [p for pr in t.pairs for p in pr]
    t.by_id = {p.pid: p for p in t.skaters + t.goalies}
    return t


def preseason_dates(first_game, n):
    first = datetime.date.fromisoformat(first_game)
    return [(first - datetime.timedelta(days=3 + 2 * (n - 1 - i))).isoformat() for i in range(n)]


def play_preseason(conn, env, skill):
    """Every club's pre-season games, dated before opening night. Idempotent per season."""
    ensure_tables(conn)
    n = int(options(conn)["preseason_games"])
    year = _season(conn)
    first = conn.execute("SELECT MIN(game_date) FROM games WHERE game_type='RS' AND played=0").fetchone()[0]
    if n <= 0 or not first or conn.execute("SELECT 1 FROM exhibitions WHERE kind='PS' AND season_start_year=?", (int(first[:4]),)).fetchone():
        return []
    from .roster import ensure_dressable
    from .injuries import roll_injuries
    from . import chemistry as CH
    clubs_all = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")]
    dates = preseason_dates(first, n)
    for t in clubs_all:
        ensure_dressable(conn, t, dates[0])
    teams = load_teams(conn)
    clubs = [t for t in clubs_all if t in teams]
    conf = {r[0]: r[1] for r in conn.execute("SELECT team_id, conference FROM teams")}
    means = raw_means(conn, teams)
    pros = {t: _camp_prospects(conn, t, means) for t in clubs}
    seed = _seed(conn)
    rng = random.Random(f"{seed}-{year}-preseason")
    me = user_team(conn)
    mine = []
    for i, day in enumerate(dates):
        played = []
        for h, a in _pairings(clubs, conf, rng):
            use = i < (n + 1) // 2
            ht = _camp_team(teams[h], pros[h], use, i % 2 == 1)
            at = _camp_team(teams[a], pros[a], use, i % 2 == 1)
            gseed = seed * 1_000_003 + 7_000_000 + i * 100 + h
            ex, res = _play(conn, "PS", day, "Pre-season", str(i + 1), ht, at, (team_abbr(conn, h), team_abbr(conn, a)), env, skill, gseed)
            CH.record(conn, ht, day)
            CH.record(conn, at, day)
            played += [(pid, st["toi"] * 0.5) for pid, st in res.stats.items()]   # half the regular-season injury rate
            if me in (h, a):
                mine.append(ex)
        roll_injuries(conn, day, played, random.Random(f"{seed}-{day}-ps-injury"))
    if me is not None and mine:
        camp_report(conn, me, mine, dates[-1])
    day0 = (datetime.date.fromisoformat(first) - datetime.timedelta(days=1)).isoformat()
    for t in clubs_all:                               # a camp injury must not leave an AI club short on opening night
        if t != me:
            ensure_dressable(conn, t, day0)
    return [f"Pre-season: {n} games a club, {dates[0]} to {dates[-1]}."]


def _lines(conn, exs, team):
    q = ",".join(str(x) for x in exs)
    return conn.execute(f"SELECT s.player_id, COUNT(*) gp, SUM(g) g, SUM(a) a, AVG(rating) r, p.status, p.position FROM exhibition_stats s "
                        f"JOIN players p USING (player_id) WHERE ex_id IN ({q}) AND s.team_id=? GROUP BY s.player_id ORDER BY r DESC",
                        (team,)).fetchall()


def _r(x):
    return "-" if x is None else f"{x:.1f}"


def camp_report(conn, me, exs, day):
    w = l = 0
    for r in conn.execute(f"SELECT home_id, home_goals, away_goals FROM exhibitions WHERE ex_id IN ({','.join(map(str, exs))})"):
        mine = (r[1] > r[2]) == (r[0] == me)
        w, l = w + mine, l + (not mine)
    rows = _lines(conn, exs, me)
    best = [r for r in rows if r["gp"] >= 2][:3]
    pros = [r for r in rows if r["status"] == "prospect"]
    lines = [f"Pre-season record: {w}-{l}."]
    if best:
        lines.append("Stood out: " + "; ".join(f"{player_name(conn, r['player_id'])} ({r['g']}+{r['a']}, rating {_r(r['r'])})" for r in best) + ".")
    if pros:
        good = [r for r in pros if (r["r"] or 0) >= 6.3]
        poor = [r for r in pros if (r["r"] or 0) < 5.5]
        lines.append("Your prospects in camp: " + "; ".join(f"{player_name(conn, r['player_id'])} {r['g']}+{r['a']} in {r['gp']}, "
                                                             f"rating {_r(r['r'])}" for r in pros) + ".")
        if good:
            lines.append("Pushing for a job: " + ", ".join(player_name(conn, r["player_id"]) for r in good) + ".")
        if poor:
            lines.append("Not ready yet: " + ", ".join(player_name(conn, r["player_id"]) for r in poor) + ".")
    lines.append("Pre-season results do not count: League > Exhibitions has every game.")
    add_message(conn, day, "Camp report", "\n".join(lines))


# ---------------------------------------------------------------- prospects tournaments
def _age(birth, on):
    b = datetime.date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def _prospect_roster(conn, t, on, means, invitees):
    rows = conn.execute("SELECT player_id, birth_date FROM players WHERE team_id=? AND status='prospect' UNION "
                        "SELECT p.player_id, p.birth_date FROM draft_rights d JOIN players p USING (player_id) WHERE d.team_id=? "
                        "AND p.status<>'retired'", (t, t)).fetchall() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='draft_rights'").fetchone() else \
        conn.execute("SELECT player_id, birth_date FROM players WHERE team_id=? AND status='prospect'", (t,)).fetchall()
    ids = [r[0] for r in rows if r[1] and _age(r[1], on) <= 22]
    at = _attrs(conn, ids)
    pl = sorted((make_player(a, means) for a in at.values()), key=lambda p: -_ovr(p))
    need = {"F": 12, "D": 6, "G": 2}
    grp = lambda p: "G" if p.pos == "G" else "D" if p.pos == "D" else "F"
    out, inv = [], []
    for k, n in need.items():
        mine = [p for p in pl if grp(p) == k][:n]
        while len(mine) < n and invitees[k]:
            p = invitees[k].pop(0)
            mine.append(p)
            inv.append(p.pid)
        out += mine
    return out, inv


def _invitees(conn, on, means, taken):
    rows = conn.execute("SELECT player_id, birth_date FROM players WHERE team_id IS NULL AND status<>'retired' AND birth_date IS NOT NULL").fetchall()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_rights'").fetchone():
        held = {r[0] for r in conn.execute("SELECT player_id FROM draft_rights")}
    else:
        held = set()
    ids = [r[0] for r in rows if r[0] not in held and r[0] not in taken and 19 <= _age(r[1], on) <= 22]
    at = _attrs(conn, ids)
    pl = sorted((make_player(a, means) for a in at.values()), key=lambda p: -_ovr(p))
    out = {"F": [], "D": [], "G": []}
    for p in pl:
        out["G" if p.pos == "G" else "D" if p.pos == "D" else "F"].append(p)
    return out


def _circle(teams, rounds):
    lst = list(teams) + ([None] if len(teams) % 2 else [])
    n = len(lst)
    out = []
    for r in range(min(rounds, n - 1)):
        out.append([(lst[i], lst[n - 1 - i]) for i in range(n // 2) if lst[i] is not None and lst[n - 1 - i] is not None])
        lst = [lst[0]] + [lst[-1]] + lst[1:-1]
    return out


def prospects_tournaments(conn, env, skill, day):
    """Mid-September: one tournament per division. Idempotent per year."""
    ensure_tables(conn)
    if options(conn)["prospects"] != "on":
        return []
    on = datetime.date.fromisoformat(day)
    if conn.execute("SELECT 1 FROM exhibitions WHERE kind='PROSPECTS' AND season_start_year=?", (on.year,)).fetchone():
        return []
    teams = load_teams(conn)
    if not teams:
        return []
    means = raw_means(conn, teams)
    clubs = conn.execute(f"SELECT team_id, abbr, division FROM teams WHERE {top_league_sql()} ORDER BY division, team_id").fetchall()
    rosters, inv_of = {}, {}
    invitees = _invitees(conn, on, means, set())
    for c in clubs:
        r, inv = _prospect_roster(conn, c["team_id"], on, means, invitees)
        if sum(p.pos == "G" for p in r) >= 1 and sum(p.pos != "G" for p in r) >= 12:
            rosters[c["team_id"]] = r
            inv_of[c["team_id"]] = set(inv)
    groups = {}
    for c in clubs:
        if c["team_id"] in rosters:
            groups.setdefault(c["division"] or "League", []).append(c["team_id"])
    seed = _seed(conn)
    me = user_team(conn)
    dates = [(on - datetime.timedelta(days=k)).isoformat() for k in (4, 3, 1, 0)]
    out = []
    for gname, ids in sorted(groups.items()):
        if len(ids) < 2:
            continue
        event = f"{gname} prospects tournament"
        rec = {t: [0, 0, 0] for t in ids}           # points, goal difference, goals for
        built = {t: Team(t, team_abbr(conn, t), rosters[t]) for t in ids}
        clubs_of = {p.pid: t for t in ids for p in rosters[t]}
        exs = []
        for r, pairs in enumerate(_circle(ids, 3)):
            for h, a in pairs:
                ex, res = _play(conn, "PROSPECTS", dates[r], event, f"Game {r + 1}", built[h], built[a],
                                (team_abbr(conn, h), team_abbr(conn, a)), env, skill, seed * 1_000_003 + 8_000_000 + r * 100 + h, clubs_of)
                exs.append(ex)
                hg, ag = res.goals
                for t, gf, ga in ((h, hg, ag), (a, ag, hg)):
                    rec[t][0] += 2 if gf > ga else (1 if res.went_to_ot or res.shootout else 0)
                    rec[t][1] += gf - ga
                    rec[t][2] += gf
        order = sorted(ids, key=lambda t: (-rec[t][0], -rec[t][1], -rec[t][2], t))
        f1, f2 = order[0], order[1]
        ex, res = _play(conn, "PROSPECTS", dates[3], event, "Final", built[f1], built[f2], (team_abbr(conn, f1), team_abbr(conn, f2)),
                        env, skill, seed * 1_000_003 + 8_900_000 + f1, clubs_of)
        exs.append(ex)
        champ = f1 if res.goals[0] > res.goals[1] else f2
        conn.execute("UPDATE exhibitions SET notes=? WHERE ex_id=?", (json.dumps(dict(champion=champ, table={str(t): rec[t] for t in ids})), ex))
        q = ",".join(map(str, exs))
        stars = conn.execute(f"SELECT player_id, team_id, SUM(g) g, SUM(a) a, AVG(rating) r FROM exhibition_stats WHERE ex_id IN ({q}) "
                             "GROUP BY player_id ORDER BY SUM(g)+SUM(a) DESC, AVG(rating) DESC LIMIT 3").fetchall()
        star_txt = "; ".join(f"{player_name(conn, s[0])} ({team_abbr(conn, s[1])}, {s[2]}+{s[3]})" for s in stars)
        emit(conn, "EXHIBITION", dates[3], f"{team_abbr(conn, champ)} prospects win the {event}", team_id=champ, importance=1,
             kind="prospects", event=event, stars=star_txt)
        out.append(f"{event}: {team_abbr(conn, champ)} win the final {max(res.goals)}-{min(res.goals)}. Top scorers: {star_txt}.")
        if me in ids:
            _scouts_watch(conn, [p.pid for t in ids for p in rosters[t] if t != me], dates[3])
            mine = conn.execute(f"SELECT player_id, COUNT(*) gp, SUM(g) g, SUM(a) a, AVG(rating) r FROM exhibition_stats WHERE ex_id IN ({q}) "
                                "AND team_id=? GROUP BY player_id ORDER BY AVG(rating) DESC", (me,)).fetchall()
            pos = order.index(me) + 1
            txt = [f"Your prospects finished {pos} of {len(ids)} in the group" + (" and won the tournament." if champ == me else
                   (", and lost the final." if me in (f1, f2) else ".")),
                   "Best: " + "; ".join(f"{player_name(conn, r[0])} {r[2]}+{r[3]}, rating {_r(r[4])}" for r in mine[:4]) + "."]
            if inv_of.get(me):
                txt.append("Tryout invitees on your roster: " + ", ".join(player_name(conn, x) for x in sorted(inv_of[me])) +
                           " (unattached; you can sign them).")
            txt.append(f"Your scouts watched the whole tournament: every player in it is better known. Top scorers: {star_txt}.")
            add_message(conn, dates[3], f"{event}", "\n".join(txt))
    return out


def _scouts_watch(conn, pids, day, pts=10.0):
    try:
        from . import scout_net as SN
        SN.ensure_tables(conn)
        for pid in pids:
            cur = conn.execute("SELECT points FROM scout_knowledge WHERE player_id=?", (pid,)).fetchone()
            conn.execute("INSERT OR REPLACE INTO scout_knowledge VALUES (?,?,?)", (pid, min(100.0, (cur[0] if cur else SN.START) + pts), day))
    except Exception:
        pass


# ---------------------------------------------------------------- all-star weekend
def allstar_date(conn, year=None):
    """The first Saturday of February of the season; None in a season with an Olympic break, or with the option off."""
    if options(conn)["allstar"] == "off":
        return None
    from ..league.season import db_rules
    year = year if year is not None else _season(conn)
    d = datetime.date(year + 1, 2, 1)
    d += datetime.timedelta(days=(5 - d.weekday()) % 7)
    rules = db_rules(conn) or {}
    for b in (rules.get("season") or {}).get("breaks") or []:
        if "olympic" in str(b.get("name", "")).lower() and str(b.get("start", ""))[:4] == str(year + 1):
            return None
        if b.get("all_star") is False and str(b.get("start", ""))[:4] == str(year + 1):
            return None
    return d.isoformat()


def _season_lines(conn, year):
    sid = conn.execute("SELECT season_id FROM seasons WHERE start_year=?", (year,)).fetchone()
    if not sid:
        return {}
    return {r[0]: dict(gp=r[1], g=r[2], a=r[3], sv=r[4], sa=r[5]) for r in conn.execute(
        "SELECT s.player_id, COUNT(*), SUM(s.goals), SUM(s.assists), SUM(s.saves), SUM(s.shots_against) FROM player_game_stats s JOIN games g "
        "USING (game_id) WHERE g.season_id=? AND g.game_type='RS' GROUP BY s.player_id", (sid[0],))}


def select_allstars(conn, fmt=None):
    """{"sides": [name, name], "players": [[pid...], [pid...]], "captains": [pid, pid] or None}."""
    fmt = fmt or options(conn)["allstar"]
    year = _season(conn)
    st = _season_lines(conn, year)
    teams = load_teams(conn)
    means = raw_means(conn, teams)
    pool = conn.execute("SELECT p.player_id, p.team_id, p.position, p.nationality, t.conference FROM players p JOIN teams t ON "
                        f"t.team_id=p.team_id WHERE p.status='active' AND t.team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()})").fetchall()
    at = _attrs(conn, [r[0] for r in pool])
    info = {}
    for r in pool:
        if r[0] not in at:
            continue
        p = make_player(at[r[0]], means)
        s = st.get(r[0], dict(gp=0, g=0, a=0, sv=0, sa=0))
        if r[2] == "G":
            sv = (s["sv"] / s["sa"]) if s["sa"] else 0.9
            score = (sv - 0.900) * 400 + 4 * _ovr(p) + min(s["gp"], 20) * 0.3
        else:
            gp = max(1, s["gp"])
            score = ((s["g"] + s["a"]) / gp) * 30 + (s["g"] / gp) * 10 + 6 * _ovr(p) + (8 if r[2] == "D" else 0) + min(s["gp"], 20) * 0.2
        info[r[0]] = dict(pid=r[0], team=r[1], pos=r[2], grp="G" if r[2] == "G" else "D" if r[2] == "D" else "F",
                          nat=r[3], conf=r[4], score=score, pts=s["g"] + s["a"])
    need = {"F": 12, "D": 6, "G": 2}
    ranked = sorted(info.values(), key=lambda x: -x["score"])
    if fmt == "world":
        sides = ["North America", "World"]
        side_of = lambda x: 0 if (x["nat"] or "") in NORTH_AMERICA else 1
        picks = [[], []]
        for k, n in need.items():
            for s in (0, 1):
                picks[s] += [x for x in ranked if x["grp"] == k and side_of(x) == s][:n]
        return dict(format=fmt, sides=sides, players=[[x["pid"] for x in p] for p in picks], captains=None, info=info)
    if fmt == "conference":
        confs = sorted({x["conf"] for x in info.values() if x["conf"]})[:2]
        if len(confs) < 2:
            fmt = "draft"
    chosen = []
    if fmt == "conference":
        for c in confs:
            side = []
            for k, n in need.items():
                side += [x for x in ranked if x["grp"] == k and x["conf"] == c][:n]
            chosen.append(side)
    else:
        allp = []
        for k, n in need.items():
            allp += [x for x in ranked if x["grp"] == k][:2 * n]
        chosen = [allp]
    # every club represented: its best player replaces the lowest-ranked pick of his group from a club with several
    clubs = {x["team"] for x in info.values()}
    flat = [x for s in chosen for x in s]
    have = {x["team"] for x in flat}
    for t in sorted(clubs - have):
        best = next((x for x in ranked if x["team"] == t), None)
        if not best:
            continue
        si = next((i for i, s in enumerate(chosen) if fmt != "conference" or (s and s[0]["conf"] == best["conf"])), 0)
        side = chosen[si]
        counts = {}
        for x in side:
            counts[x["team"]] = counts.get(x["team"], 0) + 1
        cands = [x for x in side if x["grp"] == best["grp"] and counts[x["team"]] > 1]
        if not cands:
            cands = [x for x in side if x["grp"] != "G" and best["grp"] != "G" and counts[x["team"]] > 1]
        if not cands:
            continue
        out = min(cands, key=lambda x: x["score"])
        side[side.index(out)] = best
    if fmt == "conference":
        return dict(format=fmt, sides=[f"{c}" for c in confs], players=[[x["pid"] for x in s] for s in chosen], captains=None, info=info)
    # the fantasy draft: the two leading vote-getters (the best scores) are captains and pick in turn, by group
    allp = sorted(chosen[0], key=lambda x: -x["score"])
    caps = [x for x in allp if x["grp"] != "G"][:2]
    teams_ = [[caps[0]], [caps[1]]]
    rest = [x for x in allp if x not in caps]
    rng = random.Random(f"{_seed(conn)}-{year}-asg-draft")
    turn = 0
    while rest:
        side = teams_[turn]
        want = {k: n - sum(1 for x in side if x["grp"] == k) for k, n in need.items()}
        opts = [x for x in rest if want[x["grp"]] > 0]
        if not opts:
            turn = 1 - turn
            if not [x for x in rest if {k: n - sum(1 for y in teams_[turn] if y["grp"] == k) for k, n in need.items()}[x["grp"]] > 0]:
                break
            continue
        pick = opts[0] if rng.random() < 0.8 else opts[min(len(opts) - 1, 1)]
        side.append(pick)
        rest.remove(pick)
        turn = 1 - turn
    names = [f"Team {player_name(conn, c['pid']).split()[-1]}" for c in caps]
    return dict(format="draft", sides=names, players=[[x["pid"] for x in s] for s in teams_], captains=[c["pid"] for c in caps], info=info)


def run_allstar(conn, env, skill, day):
    """All-star weekend: the selection, the skills competition, the game. Idempotent per season."""
    ensure_tables(conn)
    year = _season(conn)
    if conn.execute("SELECT 1 FROM exhibitions WHERE kind='ASG' AND season_start_year=?", (year,)).fetchone():
        return []
    sel = select_allstars(conn)
    if not all(sel["players"]):
        return []
    teams = load_teams(conn)
    means = raw_means(conn, teams)
    at = _attrs(conn, [p for s in sel["players"] for p in s])
    sides = []
    for i, pids in enumerate(sel["players"]):
        pl = []
        for pid in pids:
            p = make_player(at[pid], means, toi=1000 + sel["info"][pid]["score"] * 10)
            if p.pos != "G":
                p.sup -= DEFENCE_OPTIONAL
                p.blk -= DEFENCE_OPTIONAL * 0.5
            else:
                p.save -= GOALIE_OPEN
            pl.append(p)
        sides.append(Team(-(i + 1), sel["sides"][i], pl))
    clubs = {pid: sel["info"][pid]["team"] for s in sel["players"] for pid in s}
    skills = skills_competition(conn, sel, at, day)
    ex, res = _play(conn, "ASG", day, "All-Star Game", sel["format"], sides[0], sides[1], tuple(sel["sides"]), env, skill,
                    _seed(conn) * 1_000_003 + 9_000_000 + year, clubs)
    win = 0 if res.goals[0] > res.goals[1] else 1
    rows = conn.execute("SELECT player_id, side, g, a, rating FROM exhibition_stats WHERE ex_id=?", (ex,)).fetchall()
    goalies = {p for s in sel["players"] for p in s if sel["info"][p]["grp"] == "G"}
    mvp = max(rows, key=lambda r: ((r[4] or 0) * (0.6 if r[0] in goalies else 1.0) + (0.5 if r[1] == win else 0) + 0.4 * (r[2] + r[3]), -r[0]))[0]
    conn.execute("UPDATE exhibitions SET notes=? WHERE ex_id=?", (json.dumps(dict(players=sel["players"], captains=sel["captains"], mvp=mvp,
                                                                                  format=sel["format"])), ex))
    score = f"{sel['sides'][win]} {max(res.goals)}-{min(res.goals)}"
    emit(conn, "ALL_STAR", day, f"All-Star Game: {score}; {player_name(conn, mvp)} is the MVP", player_id=mvp, team_id=clubs.get(mvp),
         importance=2, mvp=mvp, score=score)
    me = user_team(conn)
    mine = [pid for s in sel["players"] for pid in s if clubs.get(pid) == me]
    txt = [f"The All-Star Game ({ {'conference': 'conference against conference', 'draft': 'the captains picked their teams', 'world': 'North America against the World'}[sel['format']] }): {score}.",
           f"MVP: {player_name(conn, mvp)} ({team_abbr(conn, clubs.get(mvp))})."]
    txt += [f"{SKILLS[k][0]}: {player_name(conn, v['winner'])} ({v['best']} {SKILLS[k][1]})" for k, v in skills.items()]
    if mine:
        txt.append("Your all-stars: " + ", ".join(player_name(conn, p) for p in mine) + ".")
        try:
            from . import people
            for p in mine:
                people.log_event(conn, p, day, "role", 2, "named an all-star")
                conn.execute("UPDATE morale SET role=MIN(100, role+2) WHERE player_id=?", (p,))
        except Exception:
            pass
    if me is not None:
        add_message(conn, day, "All-star weekend", "\n".join(txt) + "\nLeague > All-Star Weekend has the rosters and the box score.")
    return txt


def _skill_value(key, a, rng):
    if key == "fastest":
        return round(max(11.8, 15.4 - 0.07 * ((a["speed"] or 8) + (a["acceleration"] or 8)) + rng.gauss(0, 0.18)), 3)
    if key == "hardest":
        return round(80 + 1.6 * (a["shot_power"] or 8) + 0.3 * (a["strength"] or 8) + rng.gauss(0, 1.5), 1)
    if key == "accuracy":
        return round(max(7.0, 17.0 - 0.6 * (a["shot_accuracy"] or 8) + rng.gauss(0, 1.3)), 3)
    if key == "stickhandling":
        return round(max(18.0, 36.0 - 0.6 * (a["puck_control"] or 8) - 0.3 * (a["agility"] or 8) + rng.gauss(0, 1.4)), 3)
    if key == "save_streak":
        p = min(0.94, 0.65 + 0.02 * ((a["reflexes"] or 8) + (a["glove"] or 8) + (a["blocker"] or 8)) / 3)
        n = 0
        while rng.random() < p and n < 40:
            n += 1
        return n
    raise KeyError(key)


def skills_competition(conn, sel, at, day):
    """Four entrants an event, the best at what it tests among the all-stars; the night decides."""
    rng = random.Random(f"{_seed(conn)}-{day}-skills")
    allp = [pid for s in sel["players"] for pid in s]
    test = {"fastest": lambda a: (a["speed"] or 0) + (a["acceleration"] or 0), "hardest": lambda a: a["shot_power"] or 0,
            "accuracy": lambda a: a["shot_accuracy"] or 0, "stickhandling": lambda a: (a["puck_control"] or 0) + (a["agility"] or 0) / 2,
            "save_streak": lambda a: (a["reflexes"] or 0) + (a["glove"] or 0)}
    out = {}
    for key, (name, unit, low) in SKILLS.items():
        cand = [p for p in allp if (at[p]["position"] == "G") == (key == "save_streak")]
        cand = sorted(cand, key=lambda p: -test[key](at[p]))[:4]
        if not cand:
            continue
        res = sorted(((p, _skill_value(key, at[p], rng)) for p in cand), key=lambda x: x[1] if low else -x[1])
        out[key] = dict(name=name, unit=unit, winner=res[0][0], best=res[0][1],
                        results=[dict(player_id=p, name=player_name(conn, p), team=team_abbr(conn, sel["info"][p]["team"]), value=v)
                                 for p, v in res])
    conn.execute("INSERT INTO exhibitions (kind, season_start_year, day, event, round, notes) VALUES ('SKILLS', ?, ?, 'Skills competition', '', ?)",
                 (_season(conn), day, json.dumps(out)))
    return out


def daily(conn, env, skill, day):
    """From the day loop: all-star weekend on its day."""
    if day == allstar_date(conn):
        return run_allstar(conn, env, skill, day)
    return []


# ---------------------------------------------------------------- views
def exhibitions_view(conn, kind=None, year=None):
    ensure_tables(conn)
    years = [r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM exhibitions WHERE kind IN ('PS','PROSPECTS') ORDER BY 1 DESC")]
    year = int(year) if year else (years[0] if years else None)
    me = user_team(conn)
    games = []
    for r in conn.execute("SELECT * FROM exhibitions WHERE kind IN ('PS','PROSPECTS') AND season_start_year=? " + ("AND kind=? " if kind else "")
                          + "ORDER BY kind DESC, event, day, ex_id", (year,) + ((kind,) if kind else ())):
        games.append(dict(ex_id=r["ex_id"], kind=r["kind"], day=r["day"], event=r["event"], round=r["round"], home=r["home_name"],
                          away=r["away_name"], home_id=r["home_id"], away_id=r["away_id"], score=f"{r['home_goals']}-{r['away_goals']}",
                          ot={0: "", 1: "OT", 2: "SO"}.get(r["ot"] or 0, ""), mine=me in (r["home_id"], r["away_id"]),
                          notes=json.loads(r["notes"]) if r["notes"] else None))
    champs = [dict(event=g["event"], champion=g["notes"]["champion"], abbr=team_abbr(conn, g["notes"]["champion"]))
              for g in games if g["kind"] == "PROSPECTS" and g["round"] == "Final" and g["notes"]]
    camp = []
    if me is not None and year:
        exs = [g["ex_id"] for g in games if g["mine"] and g["kind"] == "PS"]
        if exs:
            camp = [dict(player_id=r["player_id"], name=player_name(conn, r["player_id"]), pos=r["position"], gp=r["gp"], g=r["g"], a=r["a"],
                         rating=round(r["r"], 1) if r["r"] is not None else None, prospect=r["status"] == "prospect") for r in _lines(conn, exs, me)]
    return dict(years=years, year=year, games=games, champions=champs, camp=camp, options=options(conn))


def boxscore(conn, ex_id):
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM exhibitions WHERE ex_id=?", (ex_id,)).fetchone()
    if r is None:
        return dict(ex_id=ex_id, missing=True)
    rows = conn.execute("SELECT s.*, p.first_name||' '||p.last_name name, p.position FROM exhibition_stats s JOIN players p USING (player_id) "
                        "WHERE ex_id=? ORDER BY side, (p.position='G'), g+a DESC, rating DESC", (ex_id,)).fetchall()
    sides = [[], []]
    for x in rows:
        sides[x["side"]].append(dict(player_id=x["player_id"], name=x["name"], pos=x["position"], club=team_abbr(conn, x["team_id"]) if x["team_id"] and x["team_id"] > 0 else "",
                                     g=x["g"], a=x["a"], sog=x["sog"], saves=x["saves"], sa=x["sa"], toi=x["toi"], rating=x["rating"]))
    return dict(ex_id=ex_id, kind=r["kind"], day=r["day"], event=r["event"], round=r["round"], names=[r["home_name"], r["away_name"]],
                score=[r["home_goals"], r["away_goals"]], ot={0: "", 1: "OT", 2: "SO"}.get(r["ot"] or 0, ""), sides=sides,
                notes=json.loads(r["notes"]) if r["notes"] else None)


def allstar_view(conn, year=None):
    ensure_tables(conn)
    years = [r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM exhibitions WHERE kind='ASG' ORDER BY 1 DESC")]
    cur = _season(conn)
    year = int(year) if year else (years[0] if years else cur)
    g = conn.execute("SELECT ex_id FROM exhibitions WHERE kind='ASG' AND season_start_year=?", (year,)).fetchone()
    sk = conn.execute("SELECT notes FROM exhibitions WHERE kind='SKILLS' AND season_start_year=?", (year,)).fetchone()
    date = allstar_date(conn, cur)
    out = dict(years=years, year=year, date=date if year == cur else None, format=options(conn)["allstar"],
               game=boxscore(conn, g[0]) if g else None, skills=json.loads(sk[0]) if sk and sk[0] else None)
    if out["game"] and out["game"]["notes"]:
        m = out["game"]["notes"].get("mvp")
        out["mvp"] = dict(player_id=m, name=player_name(conn, m)) if m else None
    if not g and year == cur and date and conn.execute("SELECT 1 FROM seasons WHERE start_year=?", (cur,)).fetchone():
        try:
            sel = select_allstars(conn)                    # the current vote: who would go if it were today
            out["projected"] = dict(sides=sel["sides"], players=[[dict(player_id=p, name=player_name(conn, p), pos=sel["info"][p]["pos"],
                                                                       club=team_abbr(conn, sel["info"][p]["team"]), pts=sel["info"][p]["pts"])
                                                                  for p in s] for s in sel["players"]])
        except Exception:
            out["projected"] = None
    return out


# ---------------------------------------------------------------- the calendar's dates
def league_dates(conn):
    """[(date, label)] for the calendar: the season's events beyond your own games (v37)."""
    ensure_tables(conn)
    from . import offseason as OS
    year = _season(conn)
    me = user_team(conn)
    out = []
    a = allstar_date(conn, year)
    if a:
        out.append((a, "All-star weekend"))
    for r in conn.execute("SELECT day, event, round, home_id, away_id, home_name, away_name, home_goals, away_goals FROM exhibitions "
                          "WHERE kind IN ('PS','PROSPECTS') AND season_start_year IN (?, ?) AND (home_id=? OR away_id=?)", (year, year + 1, me, me)):
        mine_home = r[3] == me
        gf, ga = (r[7], r[8]) if mine_home else (r[8], r[7])
        opp = r[6] if mine_home else r[5]
        tag = "Pre-season" if r[1] == "Pre-season" else "Prospects"
        out.append((r[0], f"{tag}: {'W' if gf > ga else 'L'} {gf}-{ga} {'vs' if mine_home else '@'} {opp}"))
    end = year + 1
    for key, (mo, d) in OS.PHASE_DAY.items():
        label = {"draft": "Entry draft", "rights": "Re-signing opens; Hall of Fame vote", "free_agency": "Free agency opens",
                 "arbitration": "Arbitration", "awards": "Arbitration awards", "preseason": "Training camp; prospects tournaments"}[key]
        out.append((f"{end}-{mo:02d}-{d:02d}", label))
    try:
        from . import scout_net as SN
        for key, (name, (mo, d), days, *_rest) in SN.TOURNAMENTS.items():
            y = year if mo >= 8 else end
            out.append((f"{y}-{mo:02d}-{d:02d}", name))
    except Exception:
        pass
    return out
