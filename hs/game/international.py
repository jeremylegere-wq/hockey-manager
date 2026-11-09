"""International hockey: national teams, tournaments, the world ranking, medals and the Triple Gold Club
(v51; docs/INTERNATIONAL.md).

Tournaments (each season Y, Oct Y - June Y+1)
  World Junior Championship  26 Dec - 5 Jan; 10 nations; players born in (Y+1) - 20 or later who are not on an NHL
                             roster; two groups of five, quarterfinals (1 v 4, 2 v 3 across the groups), semifinals,
                             bronze and gold
  World Championship         May (played when the NHL playoffs end); 16 nations; NHL players whose clubs missed the
                             playoffs or went out in the first round (65% of North Americans and 35% of Europeans say no), and everyone outside the
                             NHL; two groups of eight, then the same knockout
  World Cup of Hockey        February 2028, 2032, 2036...; the 8 best nations; everyone (the NHL breaks for it);
                             two groups of four, semifinals (1 v 2 across), final
  Olympic Games              February 2030, 2034...; 12 nations (the host qualifies); everyone (the NHL breaks); three
                             groups of four, the four best group records straight to the quarterfinals, 5-12 in a
                             qualification round (5 v 12, 6 v 11, 7 v 10, 8 v 9), re-seeded quarterfinals, semifinals,
                             bronze and gold
Who plays: the nations with enough players, best first by world ranking. Russia and Belarus are excluded (the IIHF
ban, extended in July 2026 for 2026-27; the setting `international_banned` readmits them). A roster is the best
available players of that nationality: 14 forwards, 8 defencemen, 3 goalies (13/7/3 at the World Cup).
The games: the leagues' results model (hs/game/leagues.py) with each nation's dressed lineup, the gaps between nations
narrowed to a fifth (they are all picked from the best) and 2.5 goals a team a game; overtime decides every game (a
shootout in the group stage, sudden death in the knockout). Over 40 runs of the 2026 world: the World Cup and the
Olympics go to Canada or the United States about four times in five; the World Championship about three in five
(Sweden, Czechia, Finland and Latvia the others); the World Juniors spread across six or seven nations.
The world ranking (IIHF style): points by final place at the World Championship and the Olympics (1st 1200, then 20
fewer a place, 40 fewer after 4th, 8th and 12th), the last four years weighted 100/75/50/25%. Before a nation has
four years of results in the save, a seed ranking from the real 2025 order fills in.
Medals are kept per player; the Triple Gold Club is the players with Olympic gold, World Championship gold and an
NHL championship (in this save). Best-on-best seasons: the NHL schedule breaks for two and a half weeks in February.
NHL players at a February tournament run a small risk of injury (1.5% each, 1-3 weeks).
"""
from __future__ import annotations

import datetime
import json
import math
import random
from collections import defaultdict

from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

NATIONS = {"CAN": "Canada", "USA": "United States", "SWE": "Sweden", "FIN": "Finland", "CZE": "Czechia", "SUI": "Switzerland",
           "GER": "Germany", "SVK": "Slovakia", "LAT": "Latvia", "DEN": "Denmark", "NOR": "Norway", "AUT": "Austria", "FRA": "France",
           "KAZ": "Kazakhstan", "SLO": "Slovenia", "GBR": "Great Britain", "HUN": "Hungary", "ITA": "Italy", "POL": "Poland",
           "UKR": "Ukraine", "JPN": "Japan", "KOR": "South Korea", "RUS": "Russia", "BLR": "Belarus", "CRO": "Croatia", "LTU": "Lithuania",
           "EST": "Estonia", "NED": "Netherlands", "CHN": "China"}
BANNED = ("RUS", "BLR")
SEED_ORDER = ["CAN", "USA", "SWE", "FIN", "CZE", "SUI", "GER", "SVK", "LAT", "DEN", "AUT", "NOR", "FRA", "KAZ", "SLO", "HUN",
              "GBR", "ITA", "POL", "UKR", "JPN", "KOR", "RUS", "BLR"]
OLYMPICS = {2030: "FRA", 2034: "USA", 2038: None}
WORLD_CUP = (2028, 2032, 2036)
KINDS = {"wjc": "World Junior Championship", "worlds": "World Championship", "olympics": "Olympic Winter Games", "worldcup": "World Cup of Hockey"}
ROSTER = {"wjc": (14, 8, 3), "worlds": (14, 8, 3), "olympics": (14, 8, 3), "worldcup": (13, 7, 3)}
FIELD = {"wjc": 10, "worlds": 16, "olympics": 12, "worldcup": 8}
GPG = 2.5
ATTACK_SCALE = 0.2          # national teams are picked from the best, so they sit much closer together than clubs
WORLDS_DECLINE = {"CAN": 0.65, "USA": 0.65}   # NHL players asked to the World Championship who say no (else 0.35)
WORLDS_SCALE = 0.12         # the World Championship is closer still (the best players are in the NHL playoffs)
INJURY_P = 0.015
MIN_PLAYERS = 12


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS intl_tournaments (tid INTEGER PRIMARY KEY, kind TEXT, season INTEGER, name TEXT, start TEXT, "
                 "end TEXT, status TEXT DEFAULT 'selected', host TEXT, places TEXT, mvp INTEGER, top_scorer INTEGER, UNIQUE (kind, season))")
    conn.execute("CREATE TABLE IF NOT EXISTS intl_rosters (tid INTEGER, nation TEXT, player_id INTEGER, club_id INTEGER, PRIMARY KEY (tid, player_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS intl_games (gid INTEGER PRIMARY KEY, tid INTEGER, stage TEXT, home TEXT, away TEXT, hg INTEGER, "
                 "ag INTEGER, ot INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS intl_stats (tid INTEGER, player_id INTEGER, nation TEXT, kind TEXT, gp INTEGER, g INTEGER, a INTEGER, "
                 "pim INTEGER, w INTEGER, ga INTEGER, sa INTEGER, so INTEGER, PRIMARY KEY (tid, player_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS intl_tgc (player_id INTEGER PRIMARY KEY, day TEXT)")


def _get(conn, key, default=None):
    r = conn.execute("SELECT value FROM pack_info WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def banned(conn):
    return () if _get(conn, "international_banned") == "readmitted" else BANNED


def _season(conn):
    from .contracts import season_year
    return season_year(conn)


def best_on_best(year_feb):
    """'olympics' / 'worldcup' / None for the February of this calendar year."""
    return "olympics" if year_feb in OLYMPICS else "worldcup" if year_feb in WORLD_CUP else None


def calendar(season):
    """[(kind, start, end)] for the season starting in `season`."""
    y = season
    out = [("wjc", f"{y}-12-26", f"{y + 1}-01-05")]
    bob = best_on_best(y + 1)
    if bob == "olympics":
        out.append(("olympics", f"{y + 1}-02-10", f"{y + 1}-02-22"))
    elif bob == "worldcup":
        out.append(("worldcup", f"{y + 1}-02-09", f"{y + 1}-02-20"))
    out.append(("worlds", f"{y + 1}-05-08", f"{y + 1}-05-24"))
    return out


def schedule_break(season):
    """The NHL's February break for a best-on-best season, or None."""
    if best_on_best(season + 1):
        return {"start": f"{season + 1}-02-06", "end": f"{season + 1}-02-23"}
    return None


# ---------------------------------------------------------------- ranking
PLACE_POINTS = {}
_p = 1200
for _k in range(1, 41):
    PLACE_POINTS[_k] = _p
    _p -= 40 if _k in (4, 8, 12) else 20


def ranking(conn, year=None):
    """[(nation, points)] best first: World Championship and Olympic places over the last four years (100/75/50/25%)."""
    ensure_tables(conn)
    year = year or (_season(conn) + 1)
    pts = defaultdict(float)
    have = set()
    for kind, season, places in conn.execute("SELECT kind, season, places FROM intl_tournaments WHERE kind IN ('worlds','olympics') AND "
                                             "status='done' AND places IS NOT NULL").fetchall():
        end_year = season + 1
        age = year - end_year
        if not 0 <= age <= 3:
            continue
        w = (1.0, 0.75, 0.5, 0.25)[age]
        for k, n in enumerate(json.loads(places), 1):
            pts[n] += w * PLACE_POINTS.get(k, 600)
            have.add(end_year)
    years = len(have)
    if years < 4:                                          # the seed fills the years the save has not played
        fill = (4 - years) * 0.625
        for k, n in enumerate(SEED_ORDER, 1):
            pts[n] += fill * PLACE_POINTS.get(k, 600)
    return sorted(pts.items(), key=lambda kv: -kv[1])


# ---------------------------------------------------------------- selection
def _available(conn, kind, season):
    """{nation: [attr row]} of players who can play this tournament."""
    from .world import load_attrs
    year_end = season + 1
    rows = load_attrs(conn, "p.status IN ('active','prospect') AND p.nationality IS NOT NULL")
    nhl = {r[0] for r in conn.execute("SELECT team_id FROM teams WHERE league_id=(SELECT league_id FROM leagues ORDER BY COALESCE(level, 1), "
                                      "league_id LIMIT 1)")}
    out = defaultdict(list)
    if kind == "worlds":
        late = {r[0] for r in conn.execute("SELECT team_id FROM team_seasons WHERE season_start_year=? AND playoff_round>=2", (season,))} \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_seasons'").fetchone() else set()
    injured = {r[0] for r in conn.execute("SELECT player_id FROM players WHERE status IN ('injured','ltir')")}
    for pid, r in rows.items():
        nat = r["nationality"]
        if nat not in NATIONS or pid in injured:
            continue
        on_nhl = r["club_id"] in nhl and r["status"] == "active"
        if kind == "wjc":
            if int(r["birth_date"][:4]) < year_end - 20 or on_nhl:     # the 2027 WJC: born in 2007 or later
                continue
        elif kind == "worlds":
            if on_nhl and r["club_id"] in late:
                continue
            if on_nhl and random.Random(f"{get_state(conn)[1]}-worlds-{season}-{pid}").random() < WORLDS_DECLINE.get(nat, 0.35):
                continue
        out[nat].append(r)
    return out


def _pick(rows, kind):
    from .world import overall
    nf, nd, ng = ROSTER[kind]
    rows = sorted(rows, key=lambda r: -overall(r))
    f = [r for r in rows if r["position"] in ("C", "LW", "RW")][:nf]
    d = [r for r in rows if r["position"] == "D"][:nd]
    g = [r for r in rows if r["position"] == "G"][:ng]
    return f + d + g


def select(conn, kind, season, day):
    """Name the field and the rosters. Returns the tournament id."""
    ensure_tables(conn)
    if conn.execute("SELECT 1 FROM intl_tournaments WHERE kind=? AND season=?", (kind, season)).fetchone():
        return None
    start, end = next((s, e) for k, s, e in calendar(season) if k == kind)
    pool = _available(conn, kind, season)
    order = [n for n, _ in ranking(conn, season + 1)]
    order += [n for n in NATIONS if n not in order]
    out = set(banned(conn))
    host = OLYMPICS.get(season + 1) if kind == "olympics" else None
    field = []
    if host and host not in out and len(pool.get(host, [])) >= MIN_PLAYERS:
        field.append(host)
    for n in order:
        if len(field) >= FIELD[kind]:
            break
        if n in out or n in field or len(pool.get(n, [])) < MIN_PLAYERS:
            continue
        field.append(n)
    name = f"{season + 1} {KINDS[kind]}" if kind != "wjc" else f"{season + 1} {KINDS[kind]}"
    cur = conn.execute("INSERT INTO intl_tournaments (kind, season, name, start, end, status, host) VALUES (?,?,?,?,?, 'selected', ?)",
                       (kind, season, name, start, end, host))
    tid = cur.lastrowid
    me = user_team(conn)
    mine = []
    for n in field:
        for r in _pick(pool[n], kind):
            conn.execute("INSERT OR REPLACE INTO intl_rosters VALUES (?,?,?,?)", (tid, n, r["player_id"], r["club_id"]))
            if me and (r["team_id"] == me):
                mine.append((r["player_id"], n))
    emit(conn, "MEDIA_STORY", day, f"{name}: the rosters are named", importance=2, headline=f"{name}: rosters named",
         body=f"{len(field)} nations: " + ", ".join(NATIONS[n] for n in field) + ".", tag="international", kind="intl_rosters", tid=tid)
    if mine:
        add_message(conn, day, f"{name}: our players selected",
                    "\n".join(f"- {player_name(conn, p)} ({NATIONS[n]})" for p, n in mine)
                    + f"\nThe tournament runs {start} to {end}." + (" The NHL breaks for it." if kind in ("olympics", "worldcup") else ""),
                    sender="Hockey operations")
    return tid


# ---------------------------------------------------------------- playing
def _clubs(conn, tid, scale=None):
    from .leagues import Club
    from .world import load_attrs, overall
    rows = conn.execute("SELECT nation, player_id FROM intl_rosters WHERE tid=?", (tid,)).fetchall()
    attrs = load_attrs(conn, f"p.player_id IN (SELECT player_id FROM intl_rosters WHERE tid={int(tid)})")
    by = defaultdict(list)
    for n, pid in rows:
        if pid in attrs:
            by[n].append(attrs[pid])
    sk = [overall(r) for rs in by.values() for r in rs if r["position"] != "G"]
    gk = [overall(r) for rs in by.values() for r in rs if r["position"] == "G"]
    mean = sum(sk) / len(sk) if sk else 9.0
    gmean = sum(gk) / len(gk) if gk else 9.0
    clubs = {n: Club(n, rs, mean) for n, rs in by.items()}
    for cl in clubs.values():                              # national teams sit closer together than clubs do
        cl.attack = mean + (cl.attack - mean) * (ATTACK_SCALE if scale is None else scale)
    return clubs, gmean


def _table(results, teams):
    t = {n: dict(nation=n, gp=0, pts=0, w=0, l=0, gf=0, ga=0) for n in teams}
    for h, a, hg, ag, ot in results:
        for me, op, gf, ga in ((h, a, hg, ag), (a, h, ag, hg)):
            x = t[me]
            x["gp"] += 1
            x["gf"] += gf
            x["ga"] += ga
            if gf > ga:
                x["w"] += 1
                x["pts"] += 3 if ot == 0 else 2
            else:
                x["l"] += 1
                x["pts"] += 1 if ot else 0
    return sorted(t.values(), key=lambda x: (-x["pts"], -(x["gf"] - x["ga"]), -x["gf"], x["nation"]))


def play(conn, tid, day):
    """Play the whole tournament. Returns news lines."""
    from . import leagues as LG
    ensure_tables(conn)
    t = conn.execute("SELECT * FROM intl_tournaments WHERE tid=?", (tid,)).fetchone()
    if t is None or t["status"] != "selected":
        return []
    kind = t["kind"]
    clubs, gmean = _clubs(conn, tid, WORLDS_SCALE if kind == "worlds" else None)
    seed = get_state(conn)[1]
    rng = random.Random(f"{seed}-intl-{tid}")
    rank = {n: k for k, (n, _) in enumerate(ranking(conn, t["season"] + 1))}
    nations = sorted(clubs, key=lambda n: rank.get(n, 99))
    stats = {}
    games = []

    def game(stage, h, a, ko=False):
        hg, ag, ot = LG.play(rng, clubs[h], clubs[a], GPG, gmean, playoff=ko, stats=stats, split="PO" if ko else "RS")
        games.append((stage, h, a, hg, ag, ot))
        return (h if hg > ag else a), (a if hg > ag else h), (h, a, hg, ag, ot)

    if len(nations) < 2:
        conn.execute("UPDATE intl_tournaments SET status='done', places=? WHERE tid=?", (json.dumps(nations), tid))
        return []
    short = len(nations) < (4 if kind == "worldcup" else 8)
    # groups (serpentine by ranking); a short field plays one round robin and medal games
    ng = 1 if short else {"wjc": 2, "worlds": 2, "worldcup": 2, "olympics": 3}[kind]
    groups = [[] for _ in range(ng)]
    for k, n in enumerate(nations):
        r = k // ng
        groups[k % ng if r % 2 == 0 else ng - 1 - k % ng].append(n)
    tables = []
    for gi, grp in enumerate(groups):
        res = []
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                h, a = (grp[i], grp[j]) if rng.random() < 0.5 else (grp[j], grp[i])
                res.append(game(f"Group {'ABC'[gi]}", h, a)[2])
        tables.append(_table(res, grp))
    placed = []                                            # final order, best first
    if short:
        order_ = [x["nation"] for x in tables[0]]
        if len(order_) >= 4:
            gold, silver, _ = game("Gold medal game", order_[0], order_[1], True)
            bronze, fourth, _ = game("Bronze medal game", order_[2], order_[3], True)
            placed = [gold, silver, bronze, fourth] + order_[4:]
        else:
            gold, silver, _ = game("Gold medal game", order_[0], order_[1], True)
            placed = [gold, silver] + order_[2:]
            bronze = placed[2] if len(placed) > 2 else None
        qf_pairs, sf_pairs, five_eight, bottom = [], [], [], []
    elif kind == "olympics":
        overall_t = sorted([dict(x, pos=k) for tb in tables for k, x in enumerate(tb)],
                           key=lambda x: (x["pos"], -x["pts"], -(x["gf"] - x["ga"]), -x["gf"]))
        seeds = [x["nation"] for x in overall_t]
        q_win, q_lose = [], []
        for a, b in ((4, 11), (5, 10), (6, 9), (7, 8)):
            if b < len(seeds):
                w, l, _ = game("Qualification", seeds[a], seeds[b], True)
                q_win.append(w)
                q_lose.append(l)
        qf_teams = seeds[:4] + sorted(q_win, key=lambda n: seeds.index(n))
        qf_pairs = [(qf_teams[0], qf_teams[7]), (qf_teams[1], qf_teams[6]), (qf_teams[2], qf_teams[5]), (qf_teams[3], qf_teams[4])] \
            if len(qf_teams) == 8 else []
        if not qf_pairs:                                   # a short field: the top four go to the semifinals
            sf_pairs = [(seeds[0], seeds[3]), (seeds[1], seeds[2])]
        bottom = sorted(q_lose, key=lambda n: seeds.index(n)) + [n for n in seeds[4:] if n not in q_win and n not in q_lose]
    else:
        nq = 2 if kind == "worldcup" else 4
        A, B = tables[0], tables[1]
        if kind == "worldcup":
            qf_pairs = []
            sf_pairs = [(A[0]["nation"], B[1]["nation"]), (B[0]["nation"], A[1]["nation"])]
        else:
            qf_pairs = [(A[0]["nation"], B[3]["nation"]), (B[1]["nation"], A[2]["nation"]), (B[0]["nation"], A[3]["nation"]),
                        (A[1]["nation"], B[2]["nation"])]
        rest = [x for tb in tables for x in tb[nq:]]
        bottom = [x["nation"] for x in sorted(rest, key=lambda x: (tables[0].index(x) if x in tables[0] else tables[1].index(x),
                                                                   -x["pts"], -(x["gf"] - x["ga"])))]
    group_rank = {x["nation"]: (k, -x["pts"], -(x["gf"] - x["ga"])) for tb in tables for k, x in enumerate(tb)}
    if qf_pairs:
        qf_w, qf_l = [], []
        for h, a in qf_pairs:
            w, l, _ = game("Quarterfinal", h, a, True)
            qf_w.append(w)
            qf_l.append(l)
        if kind == "olympics":                             # re-seeded
            qf_w.sort(key=lambda n: seeds.index(n))
            sf_pairs = [(qf_w[0], qf_w[3]), (qf_w[1], qf_w[2])]
        else:
            sf_pairs = [(qf_w[0], qf_w[1]), (qf_w[2], qf_w[3])]
        five_eight = sorted(qf_l, key=lambda n: group_rank[n])
    else:
        five_eight = []
    sf_w, sf_l = [], []
    for h, a in ([] if short else sf_pairs):
        w, l, _ = game("Semifinal", h, a, True)
        sf_w.append(w)
        sf_l.append(l)
    if not short:
        gold, silver, _ = game("Gold medal game", sf_w[0], sf_w[1], True)
        if kind == "worldcup":
            bronze, fourth = sorted(sf_l, key=lambda n: group_rank[n])
        else:
            bronze, fourth, _ = game("Bronze medal game", sf_l[0], sf_l[1], True)
        placed = [gold, silver, bronze, fourth] + five_eight + [n for n in bottom if n not in (gold, silver, bronze, fourth) and n not in five_eight]
    placed += [n for n in nations if n not in placed]
    # store games and stats
    conn.executemany("INSERT INTO intl_games (tid, stage, home, away, hg, ag, ot) VALUES (?,?,?,?,?,?,?)",
                     [(tid, *g) for g in games])
    agg = {}
    for (pid, nation, kind_, split), v in stats.items():
        a = agg.setdefault(pid, dict(nation=nation, kind=kind_, gp=0, g=0, a=0, pim=0, w=0, ga=0, sa=0, so=0))
        if kind_ == "S":
            a["gp"] += v[0]
            a["g"] += v[1]
            a["a"] += v[2]
            a["pim"] += v[3]
        else:
            a["gp"] += v[0]
            a["w"] += v[1]
            a["so"] += v[4]
            a["ga"] += v[5]
            a["sa"] += v[6]
    conn.executemany("INSERT OR REPLACE INTO intl_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     [(tid, pid, a["nation"], a["kind"], a["gp"], a["g"], a["a"], a["pim"], a["w"], a["ga"], a["sa"], a["so"]) for pid, a in agg.items()])
    skaters = [(pid, a) for pid, a in agg.items() if a["kind"] == "S"]
    top = max(skaters, key=lambda x: (x[1]["g"] + x[1]["a"], x[1]["g"]))[0] if skaters else None
    champs = [(pid, a) for pid, a in agg.items() if a["nation"] == gold]
    mvp = max(champs, key=lambda x: (x[1]["g"] + x[1]["a"]) if x[1]["kind"] == "S" else (x[1]["sa"] - x[1]["ga"] - 0.905 * x[1]["sa"]) * 0.8 + 3)[0] \
        if champs else top
    conn.execute("UPDATE intl_tournaments SET status='done', places=?, mvp=?, top_scorer=? WHERE tid=?", (json.dumps(placed), mvp, top, tid))
    name = t["name"]
    text = f"{NATIONS[gold]} win the {name}, beating {NATIONS[silver]} in the gold medal game" + (f"; {NATIONS[bronze]} take bronze" if bronze else "")
    emit(conn, "MEDIA_STORY", day, text, importance=3 if kind in ("olympics", "worldcup") else 2, headline=f"{NATIONS[gold]} win gold",
         body=text + (f". Tournament MVP: {player_name(conn, mvp)}." if mvp else "."), tag="international", kind="intl_result", tid=tid)
    lines = [text + "."]
    _after(conn, tid, kind, day, gold, silver, bronze or "")
    return lines


def _after(conn, tid, kind, day, gold, silver, bronze):
    """Injuries from February tournaments, morale for medallists, your inbox, the Triple Gold Club."""
    me = user_team(conn)
    rng = random.Random(f"{get_state(conn)[1]}-intl-inj-{tid}")
    nhl_inj = []
    if kind in ("olympics", "worldcup"):
        for pid, club in conn.execute("SELECT r.player_id, p.team_id FROM intl_rosters r JOIN players p USING (player_id) WHERE r.tid=? AND "
                                      "p.status='active' AND p.team_id IS NOT NULL", (tid,)).fetchall():
            if rng.random() < INJURY_P:
                days = rng.randint(7, 21)
                back = (datetime.date.fromisoformat(day) + datetime.timedelta(days=days)).isoformat()
                conn.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)",
                             (pid, day, back, f"injured at the {KINDS[kind]}"))
                conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (pid,))
                nhl_inj.append((pid, club, back))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        conn.execute("UPDATE morale SET morale=MIN(100, morale+4) WHERE player_id IN (SELECT player_id FROM intl_rosters WHERE tid=? AND "
                     "nation IN (?,?,?))", (tid, gold, silver, bronze))
    t = conn.execute("SELECT name FROM intl_tournaments WHERE tid=?", (tid,)).fetchone()[0]
    if me:
        mine = conn.execute("SELECT r.player_id, r.nation FROM intl_rosters r JOIN players p USING (player_id) WHERE r.tid=? AND p.team_id=?",
                            (tid, me)).fetchall()
        if mine:
            medal = {gold: "gold", silver: "silver", bronze: "bronze"}
            body = "\n".join(f"- {player_name(conn, p)} ({NATIONS[n]}): " + (f"{medal[n]} medal" if n in medal else "no medal")
                             for p, n in mine)
            hurt = [x for x in nhl_inj if x[1] == me]
            if hurt:
                body += "\nInjured: " + "; ".join(f"{player_name(conn, p)} (back about {b})" for p, _, b in hurt)
            add_message(conn, day, f"{t}: how our players did", body, sender="Hockey operations")
    if kind in ("olympics", "worlds"):
        _triple_gold(conn, day)


def _triple_gold(conn, day):
    olymp = {r[0] for r in conn.execute("SELECT r.player_id FROM intl_rosters r JOIN intl_tournaments t USING (tid) WHERE t.kind='olympics' "
                                        "AND t.status='done' AND r.nation=json_extract(t.places, '$[0]')")}
    worlds = {r[0] for r in conn.execute("SELECT r.player_id FROM intl_rosters r JOIN intl_tournaments t USING (tid) WHERE t.kind='worlds' "
                                         "AND t.status='done' AND r.nation=json_extract(t.places, '$[0]')")}
    both = olymp & worlds
    if not both:
        return
    have = {r[0] for r in conn.execute("SELECT player_id FROM intl_tgc")}
    cups = set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_seasons'").fetchone():
        for t in ("skater_season_stats", "goalie_season_stats"):
            cups |= {r[0] for r in conn.execute(f"SELECT DISTINCT s.player_id FROM {t} s JOIN team_seasons ts ON ts.season_start_year="
                                                "s.season_start_year AND ts.team_id=s.team_id WHERE ts.playoff_round=5 AND s.split='RS'")}
    for pid in (both & cups) - have:
        conn.execute("INSERT INTO intl_tgc VALUES (?,?)", (pid, day))
        emit(conn, "ACHIEVEMENT", day, f"{player_name(conn, pid)} joins the Triple Gold Club", player_id=pid, importance=3,
             kind="triple_gold")


def daily(conn, day):
    """Name rosters on a tournament's first day and play it on its last (the World Championship: see season_over)."""
    ensure_tables(conn)
    season = _season(conn)
    out = []
    for kind, start, end in calendar(season):
        if kind == "worlds":
            continue
        if day >= start:
            tid = conn.execute("SELECT tid FROM intl_tournaments WHERE kind=? AND season=?", (kind, season)).fetchone()
            if tid is None:
                select(conn, kind, season, day)
                tid = conn.execute("SELECT tid FROM intl_tournaments WHERE kind=? AND season=?", (kind, season)).fetchone()
            if day >= end and tid:
                out += play(conn, tid[0], day)
    return out


def season_over(conn, day):
    """The NHL playoffs are done: the World Championship (and anything the season skipped) is played."""
    ensure_tables(conn)
    season = _season(conn)
    out = []
    for kind, start, end in calendar(season):
        tid = conn.execute("SELECT tid FROM intl_tournaments WHERE kind=? AND season=?", (kind, season)).fetchone()
        if tid is None:
            tid = (select(conn, kind, season, day),)
        if tid and tid[0]:
            out += play(conn, tid[0], end if kind == "worlds" else day)
    return out


# ---------------------------------------------------------------- the screen
def set_banned(conn, readmit):
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('international_banned', ?)", ("readmitted" if readmit else "banned",))


def view(conn, tid=None):
    ensure_tables(conn)
    from .world import load_attrs, overall
    me = user_team(conn)
    season = _season(conn)
    tours = [dict(r) for r in conn.execute("SELECT tid, kind, season, name, start, end, status, host, places, mvp, top_scorer FROM "
                                           "intl_tournaments ORDER BY start DESC")]
    for t in tours:
        p = json.loads(t["places"]) if t["places"] else []
        t["podium"] = [NATIONS.get(n, n) for n in p[:3]]
        t["mvp_name"] = player_name(conn, t["mvp"]) if t["mvp"] else None
    upcoming = [dict(kind=k, name=KINDS[k], start=s, end=e) for k, s, e in calendar(season)
                if not conn.execute("SELECT 1 FROM intl_tournaments WHERE kind=? AND season=? AND status='done'", (k, season)).fetchone()]
    medals = defaultdict(lambda: [0, 0, 0])
    for kind, places in conn.execute("SELECT kind, places FROM intl_tournaments WHERE status='done' AND places IS NOT NULL"):
        p = json.loads(places)
        for k in range(min(3, len(p))):
            medals[p[k]][k] += 1
    table = sorted(([NATIONS.get(n, n), *m] for n, m in medals.items()), key=lambda x: (-x[1], -x[2], -x[3]))
    rk = [dict(rank=k, nation=NATIONS.get(n, n), code=n, points=round(p), banned=n in banned(conn)) for k, (n, p) in enumerate(ranking(conn), 1)]
    tgc = [dict(player_id=r[0], name=player_name(conn, r[0]), day=r[1]) for r in conn.execute("SELECT player_id, day FROM intl_tgc ORDER BY day")]
    ours = []
    if me:
        for r in conn.execute("SELECT t.name, t.kind, r.nation, r.player_id, t.places FROM intl_rosters r JOIN intl_tournaments t USING (tid) "
                              "JOIN players p USING (player_id) WHERE p.team_id=? ORDER BY t.start DESC LIMIT 80", (me,)):
            p = json.loads(r[4]) if r[4] else []
            place = p.index(r[2]) + 1 if r[2] in p else None
            ours.append(dict(tournament=r[0], nation=NATIONS.get(r[2], r[2]), player_id=r[3], name=player_name(conn, r[3]),
                             result={1: "gold", 2: "silver", 3: "bronze"}.get(place, f"{place}th" if place else "to play")))
    out = dict(tournaments=tours, upcoming=upcoming, medals=table, ranking=rk, tgc=tgc, ours=ours, banned=[NATIONS[n] for n in banned(conn)])
    if tid:
        t = conn.execute("SELECT * FROM intl_tournaments WHERE tid=?", (int(tid),)).fetchone()
        if t:
            games = [dict(stage=g[0], home=NATIONS.get(g[1], g[1]), away=NATIONS.get(g[2], g[2]), hg=g[3], ag=g[4], ot=g[5])
                     for g in conn.execute("SELECT stage, home, away, hg, ag, ot FROM intl_games WHERE tid=? ORDER BY gid", (t["tid"],))]
            leaders = [dict(player_id=r[0], name=player_name(conn, r[0]), nation=NATIONS.get(r[1], r[1]), gp=r[2], g=r[3], a=r[4], p=r[3] + r[4])
                       for r in conn.execute("SELECT player_id, nation, gp, g, a FROM intl_stats WHERE tid=? AND kind='S' ORDER BY g+a DESC, g DESC "
                                             "LIMIT 15", (t["tid"],))]
            attrs = load_attrs(conn, f"p.player_id IN (SELECT player_id FROM intl_rosters WHERE tid={int(t['tid'])})")
            rosters = defaultdict(list)
            for n, pid, club in conn.execute("SELECT nation, player_id, club_id FROM intl_rosters WHERE tid=?", (t["tid"],)):
                a = attrs.get(pid)
                rosters[NATIONS.get(n, n)].append(dict(player_id=pid, name=player_name(conn, pid), pos=a["position"] if a else "",
                                                       club=team_abbr(conn, club) if club else "", ovr=round(overall(a), 1) if a else None,
                                                       mine=bool(a and a.get("team_id") == me)))
            for v in rosters.values():
                v.sort(key=lambda x: ("CLWRWDG".find(x["pos"]) // 2 if x["pos"] in ("C", "LW", "RW") else 3 if x["pos"] == "D" else 4, -(x["ovr"] or 0)))
            p = json.loads(t["places"]) if t["places"] else []
            out["detail"] = dict(tid=t["tid"], name=t["name"], status=t["status"], start=t["start"], end=t["end"], games=games, leaders=leaders,
                                 rosters=dict(rosters), places=[NATIONS.get(n, n) for n in p],
                                 mvp=dict(player_id=t["mvp"], name=player_name(conn, t["mvp"])) if t["mvp"] else None)
    return out
