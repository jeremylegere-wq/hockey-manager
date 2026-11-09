"""Expansion: new NHL clubs and the expansion draft (v45; docs/EXPANSION.md).

How it happens
  * The league expands on its own (League > Expansion, setting "League expansion": occasional by default): from the
    second season of a career, on 1 February each season it may announce a new club (a 25% chance, up to 36 clubs,
    one at a time) in one of the candidate markets, to join the next season.
  * Or you create one (League > Expansion > Create a club, or `expansion create`): city, nickname, abbreviation,
    colours, conference and division, before the trade deadline. You can choose to become its GM.
  * The new club comes into being when the season ends (its arena, owner, board, staff and an AHL affiliate), the
    clubs submit their protection lists, and the expansion draft is held the day the entry draft phase opens. If you
    are its GM you take it over when the season ends (your old club passes to a new GM) and make its picks.

The rules (the NHL's for Vegas, 2017, and Seattle, 2021)
  protect   7 forwards, 3 defencemen and 1 goalie, or any 8 skaters and 1 goalie
  exempt    first- and second-year pros (two or fewer North American pro seasons of 10+ games) and unsigned draft picks: they cannot be taken
  must      players with a no-movement clause must be protected (they count against the limits)
  expose    at least 2 forwards and 1 defenceman under contract next season who played 40+ games this season or 70+
            over the last two, and 1 goalie under contract next season (or a pending RFA)
  eligible  players under contract next season, or pending RFAs (their rights move)
  the draft exactly one player from each club; the new club must end with 14+ forwards, 9+ defencemen, 3+ goalies,
            20+ under contract, and a payroll between 60% and 100% of the cap
  side deals a club that would lose a valuable player may give the new club a pick to take someone else (AI clubs; up
            to six a draft: a 1st when the gap in trade value is 80+ (three at most), a 2nd when it is 25+)
  the entry draft: the new club gets the lottery odds of the third-worst club
"""
from __future__ import annotations

import datetime
import json
import random

from . import roster as R
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

PROTECT_SCHEMES = {"7-3-1": dict(F=7, D=3, G=1), "8-1": dict(S=8, G=1)}
NEED_F, NEED_D, NEED_G, NEED_CONTRACTS = 14, 9, 3, 20
PAYROLL_RANGE = (0.60, 1.00)
EXPOSE_GP_SEASON, EXPOSE_GP_TWO = 40, 70
MAX_CLUBS = 36
ANNOUNCE_P = 0.25
SIDE_DEALS_MAX, SIDE_GAP_2ND, SIDE_GAP_1ST, SIDE_FIRSTS = 6, 25.0, 80.0, 3   # gaps in trade value (hs/game/trades.py)

# the staff's picks value a position less once the roster has enough there (by how many it already has)
POS_TAPER = {"F": lambda k: 1.0 if k < 14 else 0.85 if k < 18 else 0.6,
             "D": lambda k: 1.0 if k < 9 else 0.7 if k < 11 else 0.35,
             "G": lambda k: 1.0 if k < 3 else 0.35 if k < 4 else 0.05}

# candidate markets: city, the club's nickname the league picks, abbreviation, market (1-10), conference, arena seats
CANDIDATES = [
    ("Houston", "Wildcatters", "HOU", 9, "Western", 18_000), ("Atlanta", "Phoenix", "ATL", 8, "Eastern", 17_500),
    ("Quebec City", "Nordiques", "QUE", 4, "Eastern", 18_250), ("Kansas City", "Scouts", "KCS", 6, "Western", 17_500),
    ("Hartford", "Whalers", "HFD", 5, "Eastern", 15_500), ("Portland", "Rose", "POR", 6, "Western", 18_000),
    ("Milwaukee", "Brewers", "MIL", 5, "Western", 17_000), ("Cleveland", "Barons", "CLE", 6, "Eastern", 18_000),
    ("Austin", "Lonestars", "AUS", 7, "Western", 17_000), ("Hamilton", "Tigers", "HAM", 5, "Eastern", 17_500),
]
AHL_HOMES = [("Boise", "Bandits"), ("Wichita", "Wings"), ("Saskatoon", "Blades"), ("Albuquerque", "Roadrunners"),
             ("Fort Wayne", "Flyers"), ("Halifax", "Mariners"), ("Spokane", "Express"), ("Omaha", "Knights")]
COLOURS = [("#0B3D91", "#C8102E"), ("#00205B", "#B9975B"), ("#111111", "#F2A900"), ("#004C54", "#A5ACAF"),
           ("#5B2B82", "#E0E0E0"), ("#7A0019", "#FFCC33")]


# ---------------------------------------------------------------- tables and settings
def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS expansion (exp_id INTEGER PRIMARY KEY, city TEXT, nickname TEXT, abbr TEXT, "
                 "conference TEXT, division TEXT, market INTEGER, capacity INTEGER, color1 TEXT, color2 TEXT, announced TEXT, "
                 "draft_year INTEGER, first_season INTEGER, status TEXT DEFAULT 'announced', by_user INTEGER DEFAULT 0, "
                 "user_gm INTEGER DEFAULT 0, team_id INTEGER, affiliate_id INTEGER, drafted TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS expansion_protect (exp_id INTEGER, team_id INTEGER, scheme TEXT, players TEXT, "
                 "by_user INTEGER DEFAULT 0, PRIMARY KEY (exp_id, team_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS expansion_picks (exp_id INTEGER, from_team INTEGER, player_id INTEGER, pick_no INTEGER, "
                 "by_user INTEGER DEFAULT 0, side_deal TEXT, PRIMARY KEY (exp_id, from_team))")


def mode(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='expansion_mode'").fetchone()
    return r[0] if r else "occasional"


def set_mode(conn, m):
    if m not in ("occasional", "off"):
        raise ValueError("League expansion: occasional or off.")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('expansion_mode', ?)", (m,))


def pending(conn):
    ensure_tables(conn)
    return conn.execute("SELECT * FROM expansion WHERE status IN ('announced','protecting') ORDER BY exp_id LIMIT 1").fetchone()


def _top(conn):
    from ..schema import top_league_sql
    return [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")]


def _top_abbrs(conn):
    from ..schema import top_league_sql
    return {r[0].upper() for r in conn.execute(f"SELECT abbr FROM teams WHERE {top_league_sql()}")}


def _season(conn):
    from .contracts import season_year
    return season_year(conn)


def _state(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='season_state'").fetchone()
    return r[0] if r else "regular_season"


# ---------------------------------------------------------------- announcing
def _alignment(conn, conference=None):
    """(conference, division) for a new club: the given conference (else the one with fewer clubs), and its division
    with the fewest clubs."""
    rows = conn.execute(f"SELECT conference, division, COUNT(*) FROM teams WHERE team_id IN ({','.join(map(str, _top(conn)))}) "
                        "GROUP BY conference, division").fetchall()
    confs = {}
    for c, d, n in rows:
        confs.setdefault(c, {})[d] = n
    if not confs:
        return conference or "", ""
    if conference not in confs:
        conference = min(confs, key=lambda c: (sum(confs[c].values()), c != "Western"))
    div = min(confs[conference], key=lambda d: (confs[conference][d], d))
    return conference, div


def announce(conn, day, city, nickname, abbr, conference=None, division=None, market=None, capacity=None, colors=None,
             by_user=False, user_gm=False):
    """Announce a club to join next season. Returns the expansion row id."""
    ensure_tables(conn)
    if pending(conn):
        raise ValueError("An expansion club is already on its way; one at a time.")
    if len(_top(conn)) >= MAX_CLUBS:
        raise ValueError(f"The league is at its limit ({MAX_CLUBS} clubs).")
    if _state(conn) != "regular_season":
        raise ValueError("A club can be added during the regular season (it joins next season, after an expansion draft in June).")
    from . import trades as T
    if datetime.date.fromisoformat(day) > T.deadline(conn):
        raise ValueError("Too late this season: a new club must be announced before the trade deadline.")
    city, nickname, abbr = (city or "").strip(), (nickname or "").strip(), (abbr or "").strip().upper()
    if not city or not nickname or not (2 <= len(abbr) <= 4) or not abbr.isalpha():
        raise ValueError("Give a city, a nickname and a 2-4 letter abbreviation.")
    if abbr in _top_abbrs(conn) or conn.execute("SELECT 1 FROM expansion WHERE abbr=? AND status<>'cancelled'", (abbr,)).fetchone():
        raise ValueError(f"{abbr} is already taken.")
    conf, div = _alignment(conn, conference)
    if division:
        div = division
    if not conf:
        raise ValueError("No conference to put the club in.")
    rng = random.Random(f"{get_state(conn)[1]}-exp-{abbr}")
    c1, c2 = colors or rng.choice(COLOURS)
    y = _season(conn)
    cur = conn.execute("INSERT INTO expansion (city, nickname, abbr, conference, division, market, capacity, color1, color2, announced, "
                       "draft_year, first_season, by_user, user_gm) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (city, nickname, abbr, conf, div, int(market or 5), int(capacity or 17_500), c1, c2, day, y + 1, y + 1,
                        int(bool(by_user)), int(bool(user_gm))))
    text = f"The league announces an expansion club: the {city} {nickname} ({abbr}) join the {div} Division next season"
    emit(conn, "MEDIA_STORY", day, text, importance=3, headline=text,
         body="An expansion draft in June will stock the roster: every club protects 7 forwards, 3 defencemen and a goalie (or "
              "8 skaters and a goalie) and loses one player.", tag="expansion", kind="expansion")
    add_message(conn, day, f"Expansion: the {city} {nickname}",
                f"{text}.\nWhen our season ends we submit a protection list: 7 forwards, 3 defencemen and a goalie, or any 8 "
                "skaters and a goalie. Players with a no-movement clause must be protected; first- and second-year pros are "
                "exempt. We must expose two forwards and a defenceman who played enough this season, and a goalie. The "
                "expansion draft takes one player from every club. League > Expansion has the details."
                + ("\nYou take over as the new club's GM when the season ends." if user_gm else ""),
                sender="League office")
    return cur.lastrowid


def maybe_announce(conn, day, seed=0):
    """League-run expansion: on (the first sim day from) 1 February, now and then."""
    if not ("02-01" <= day[5:] < "06-01") or _state(conn) != "regular_season":
        return None
    key = f"expansion_checked_{_season(conn)}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return None
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    if mode(conn) == "off" or pending(conn) or len(_top(conn)) >= MAX_CLUBS:
        return None
    ensure_tables(conn)
    seasons = conn.execute("SELECT COUNT(DISTINCT start_year) FROM seasons WHERE league_id=(SELECT league_id FROM teams WHERE "
                           "team_id=?)", (_top(conn)[0],)).fetchone()[0]
    if seasons < 2:                                       # never in a career's first season
        return None
    rng = random.Random(f"{seed}-expansion-{day}")
    if rng.random() >= ANNOUNCE_P:
        return None
    taken = _top_abbrs(conn) | {r[0] for r in conn.execute("SELECT abbr FROM expansion")}
    taken_cities = {r[0] for r in conn.execute("SELECT city FROM expansion")}
    options = [c for c in CANDIDATES if c[2] not in taken and c[0] not in taken_cities]
    if not options:
        return None
    city, nick, abbr, market, conf, cap = rng.choice(options)
    conf_counts = {}
    for c in conn.execute(f"SELECT conference FROM teams WHERE team_id IN ({','.join(map(str, _top(conn)))})"):
        conf_counts[c[0]] = conf_counts.get(c[0], 0) + 1
    if conf_counts and conf_counts.get(conf, 0) > min(conf_counts.values()):
        conf = min(conf_counts, key=conf_counts.get)       # balance the conferences
    return announce(conn, day, city, nick, abbr, conf, market=market, capacity=cap)


# ---------------------------------------------------------------- the club comes into being
def _create_club(conn, e, day):
    tid = conn.execute("SELECT COALESCE(MAX(team_id), 0) + 1 FROM teams").fetchone()[0]
    top_league = conn.execute("SELECT league_id FROM teams WHERE team_id=?", (_top(conn)[0],)).fetchone()[0]
    conn.execute("INSERT INTO teams (team_id, league_id, name, nickname, abbr, conference, division, primary_color, secondary_color, "
                 "parent_team_id) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                 (tid, top_league, e["city"], e["nickname"], e["abbr"], e["conference"], e["division"], e["color1"], e["color2"]))
    conn.execute("CREATE TABLE IF NOT EXISTS club_profile (team_id INTEGER PRIMARY KEY, capacity INTEGER, market INTEGER, "
                 "arena TEXT, reputation INTEGER, founded INTEGER, city TEXT)")
    conn.execute("INSERT OR REPLACE INTO club_profile VALUES (?,?,?,?,?,?,?)",
                 (tid, e["capacity"], e["market"], f"{e['city']} Arena", 8, e["first_season"], e["city"]))
    # an AHL affiliate (a new club in the AHL's smallest division)
    aff = None
    ahl = conn.execute("SELECT league_id FROM leagues WHERE UPPER(abbr)='AHL' OR UPPER(name)='AHL'").fetchone()
    if ahl:
        used = {r[0] for r in conn.execute("SELECT name FROM teams")}
        rng = random.Random(f"{get_state(conn)[1]}-exp-aff-{e['abbr']}")
        homes = [h for h in AHL_HOMES if h[0] not in used] or [(e["city"], "Reserves")]
        city, nick = rng.choice(homes)
        div = conn.execute("SELECT division, conference, COUNT(*) n FROM teams WHERE league_id=? AND division IS NOT NULL GROUP BY "
                           "division, conference ORDER BY n, division LIMIT 1", (ahl[0],)).fetchone()
        aff = tid + 1
        ab = (city[:3]).upper()
        while conn.execute("SELECT 1 FROM teams WHERE UPPER(abbr)=?", (ab,)).fetchone():
            ab = ab[:2] + chr(ord("A") + rng.randrange(26))
        conn.execute("INSERT INTO teams (team_id, league_id, name, nickname, abbr, conference, division, primary_color, "
                     "secondary_color, parent_team_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (aff, ahl[0], f"{city} {nick}", "", ab, div[1] if div else None, div[0] if div else None, e["color1"],
                      e["color2"], tid))
    # the front office: owner and board, finances, staff
    from . import finance, org, staff
    org.setup(conn, day)
    from . import boardroom
    boardroom.ensure_tables(conn)                          # the owner's profile
    finance.setup(conn)
    staff.setup_team(conn, tid)
    from . import people
    people.setup(conn, day)
    conn.execute("UPDATE expansion SET team_id=?, affiliate_id=? WHERE exp_id=?", (tid, aff, e["exp_id"]))
    return tid, aff


def season_over(conn, day):
    """The season has ended: the expansion club comes into being and the protection lists are drawn up (yours too,
    as your assistant would; change it on League > Expansion before the expansion draft)."""
    e = pending(conn)
    if e is None or e["status"] != "announced" or e["draft_year"] != _season(conn) + 1:
        return []
    tid, aff = _create_club(conn, e, day)
    conn.execute("UPDATE expansion SET status='protecting' WHERE exp_id=?", (e["exp_id"],))
    me = user_team(conn)
    if e["user_gm"] and me:
        _take_over(conn, me, tid, day)
        me = tid
    for t in _top(conn):
        if t == tid:
            continue
        scheme, pids = auto_protect(conn, t)
        conn.execute("INSERT OR REPLACE INTO expansion_protect VALUES (?,?,?,?,0)", (e["exp_id"], t, scheme, json.dumps(pids)))
    name = f"{e['city']} {e['nickname']}"
    if me == tid:
        add_message(conn, day, f"Welcome to the {name}",
                    f"You are now the general manager of the {name}. Every club has drawn up its protection list; the expansion "
                    "draft is held when the entry draft phase opens. Pick one player from each club on League > Expansion "
                    f"(you need {NEED_F} forwards, {NEED_D} defencemen and {NEED_G} goalies, {NEED_CONTRACTS} under contract, and "
                    "a payroll of 60-100% of the cap). Any club you have not picked from, your staff will pick for you.",
                    sender="Owner")
    elif me:
        add_message(conn, day, "Expansion: our protection list",
                    f"Our list for the {name}'s expansion draft is in, as I would draw it up. Review it on League > Expansion "
                    "before the draft (it is held when the entry draft phase opens).", sender="Assistant GM")
    return [f"The {name} are in the league; protection lists are in."]


def _take_over(conn, old, new, day):
    from . import gm as GMx
    from . import org
    GMx.ensure_tables(conn)
    rng = random.Random(f"{get_state(conn)[1]}-exp-gm-{old}")
    conn.execute("UPDATE gm_career SET end_date=?, how_ended='expansion' WHERE end_date IS NULL", (day,))
    conn.execute("UPDATE board SET gm_name=? WHERE team_id=?", (f"{rng.choice(org.GM_FIRST)} {rng.choice(org.GM_LAST)}", old))
    conn.execute("UPDATE manager SET team_id=? WHERE id=1", (new,))
    conn.execute("UPDATE board SET gm_name='You', confidence=70, warnings=0, vacancy=0 WHERE team_id=?", (new,))
    conn.execute("INSERT INTO gm_career VALUES (?,?,NULL,NULL)", (new, day))
    emit(conn, "GM_HIRED", day, f"{team_abbr(conn, new)} name you their first general manager", team_id=new, importance=3)


# ---------------------------------------------------------------- protection
def _contract_end(conn, pid):
    r = conn.execute("SELECT MAX(start_year+years-1) FROM contracts WHERE player_id=?", (pid,)).fetchone()
    return r[0]


def _gp(conn, pid, year):
    """(NHL games this season, NHL games this season and last)."""
    from ..schema import top_league_sql
    top = conn.execute(f"SELECT league_id FROM teams WHERE {top_league_sql()} LIMIT 1").fetchone()[0]
    rows = dict(conn.execute("SELECT season_start_year, SUM(gp) FROM (SELECT season_start_year, gp FROM skater_season_stats WHERE "
                             "player_id=? AND league_id=? AND split='RS' UNION ALL SELECT season_start_year, gp FROM "
                             "goalie_season_stats WHERE player_id=? AND league_id=? AND split='RS') WHERE season_start_year>=? "
                             "GROUP BY season_start_year", (pid, top, pid, top, year - 1)).fetchall())
    now = rows.get(year) or 0
    if not now:                                           # the season not yet folded into the season tables
        now = conn.execute("SELECT COUNT(*) FROM player_game_stats s JOIN games g USING (game_id) JOIN seasons x USING (season_id) "
                           "WHERE s.player_id=? AND x.start_year=? AND g.game_type='RS'", (pid, year)).fetchone()[0]
    return now, now + (rows.get(year - 1) or 0)


def _na_pro_seasons(conn, pid):
    """Professional seasons in North America (10+ games in the NHL, AHL or ECHL), as the exemption counts them."""
    lgs = [r[0] for r in conn.execute("SELECT league_id FROM leagues WHERE COALESCE(level, 1)<=3 AND (country IS NULL OR "
                                      "country IN ('USA/CAN','USA','CAN','North America'))")]
    if not lgs:
        return 0
    q = ",".join(map(str, lgs))
    return conn.execute(f"SELECT COUNT(*) FROM (SELECT season_start_year FROM (SELECT season_start_year, gp FROM skater_season_stats "
                        f"WHERE player_id=? AND league_id IN ({q}) AND split='RS' UNION ALL SELECT season_start_year, gp FROM "
                        f"goalie_season_stats WHERE player_id=? AND league_id IN ({q}) AND split='RS') GROUP BY season_start_year "
                        "HAVING SUM(gp)>=10)", (pid, pid)).fetchone()[0]


def pool(conn, team):
    """The club's players for the expansion draft: {pid: dict(name, pos, group, value, exempt, nmc, eligible, qualifies)}."""
    from . import clauses as CL
    from . import contracts as K
    from . import trades as T
    year = _season(conn)
    out = {}
    for r in conn.execute("SELECT player_id, first_name||' '||last_name n, position, status FROM players WHERE team_id=? AND "
                          "status IN ('active','injured','ltir','prospect')", (team,)).fetchall():
        pid = r[0]
        end = _contract_end(conn, pid)
        exempt = _na_pro_seasons(conn, pid) <= 2
        under = end is not None and end >= year + 1
        rfa = end == year and K.rights_status(conn, pid, year) == "RFA"
        cl = CL.of(conn, pid)
        gp_now, gp_two = _gp(conn, pid, year)
        g = "G" if r[2] == "G" else "D" if r[2] == "D" else "F"
        out[pid] = dict(player_id=pid, name=r[1], pos=r[2], group=g, value=round(T.asset_value(conn, pid), 1), exempt=exempt,
                        nmc=bool(cl and cl.get("kind") == "NMC"), eligible=(under or rfa) and not exempt, under=under,
                        qualifies=under and (gp_now >= EXPOSE_GP_SEASON or gp_two >= EXPOSE_GP_TWO) if g != "G" else (under or rfa),
                        gp=gp_now, status=r[3])
    return out


def validate(conn, team, scheme, pids, pl=None):
    """Problems with a protection list (empty when it is legal)."""
    pl = pl or pool(conn, team)
    if scheme not in PROTECT_SCHEMES:
        return ["Choose 7-3-1 or 8-1."]
    lim = PROTECT_SCHEMES[scheme]
    prot = [pl[p] for p in pids if p in pl and (pl[p]["eligible"] or pl[p]["nmc"])]
    n = {g: sum(1 for x in prot if x["group"] == g) for g in "FDG"}
    out = []
    if scheme == "7-3-1":
        if n["F"] > 7 or n["D"] > 3:
            out.append(f"7-3-1 protects at most 7 forwards and 3 defencemen ({n['F']} and {n['D']} chosen).")
    elif n["F"] + n["D"] > 8:
        out.append(f"8-1 protects at most 8 skaters ({n['F'] + n['D']} chosen).")
    if n["G"] > 1:
        out.append("Only one goalie can be protected.")
    miss = [x["name"] for x in pl.values() if x["nmc"] and x["eligible"] and x["player_id"] not in pids]
    if miss:
        out.append("Players with a no-movement clause must be protected: " + ", ".join(miss) + ".")
    exposed = [x for x in pl.values() if x["player_id"] not in pids and not x["exempt"]]
    if sum(1 for x in exposed if x["group"] == "F" and x["qualifies"]) < 2:
        out.append("You must expose two forwards under contract next season who played 40+ games this season or 70+ over two.")
    if sum(1 for x in exposed if x["group"] == "D" and x["qualifies"]) < 1:
        out.append("You must expose a defenceman under contract next season who played 40+ games this season or 70+ over two.")
    if sum(1 for x in exposed if x["group"] == "G" and x["qualifies"]) < 1:
        out.append("You must expose a goalie under contract next season (or a pending RFA).")
    return out


def auto_protect(conn, team, pl=None):
    """(scheme, [pids]) an assistant would submit: the scheme that protects the most value, no-movement players first,
    then made to meet the exposure rules where the roster allows."""
    pl = pl or pool(conn, team)
    cands = sorted((x for x in pl.values() if x["eligible"] or x["nmc"]), key=lambda x: -x["value"])
    best = None
    for scheme, lim in PROTECT_SCHEMES.items():
        chosen, n = [], {"F": 0, "D": 0, "G": 0, "S": 0}
        def fits(x):
            if x["group"] == "G":
                return n["G"] < 1
            return n[x["group"]] < lim[x["group"]] if "S" not in lim else n["S"] < lim["S"]
        def add(x):
            chosen.append(x["player_id"])
            n[x["group"]] += 1
            if x["group"] != "G":
                n["S"] += 1
        for x in [c for c in cands if c["nmc"]] + [c for c in cands if not c["nmc"]]:
            if x["player_id"] not in chosen and fits(x):
                add(x)
        # exposure: if a required player cannot be left unprotected, swap the least valuable protected one that qualifies
        for g, need in (("F", 2), ("D", 1), ("G", 1)):
            for _ in range(3):
                exposed = [x for x in pl.values() if x["player_id"] not in chosen and not x["exempt"]]
                if sum(1 for x in exposed if x["group"] == g and x["qualifies"]) >= need:
                    break
                drop = [pl[p] for p in chosen if pl[p]["group"] == g and pl[p]["qualifies"] and not pl[p]["nmc"]]
                if not drop:
                    break
                d = min(drop, key=lambda x: x["value"])
                chosen.remove(d["player_id"])
                n[g] -= 1
                if g != "G":
                    n["S"] -= 1
                repl = next((x for x in cands if x["player_id"] not in chosen and x["group"] == g and not x["qualifies"]
                             and x["player_id"] != d["player_id"]), None)
                if repl and fits(repl):
                    add(repl)
        val = sum(pl[p]["value"] for p in chosen)
        if best is None or val > best[0]:
            best = (val, scheme, chosen)
    return best[1], best[2]


def protection(conn, team):
    e = pending(conn)
    if not e:
        return None
    r = conn.execute("SELECT scheme, players, by_user FROM expansion_protect WHERE exp_id=? AND team_id=?", (e["exp_id"], team)).fetchone()
    return dict(scheme=r[0], players=json.loads(r[1]), by_user=bool(r[2])) if r else None


def set_protection(conn, team, scheme, pids):
    e = pending(conn)
    if not e or e["status"] != "protecting":
        raise ValueError("Protection lists are drawn up when the season ends, before the expansion draft.")
    if team == e["team_id"]:
        raise ValueError("The expansion club does not protect anyone.")
    probs = validate(conn, team, scheme, pids)
    if probs:
        raise ValueError(" ".join(probs))
    conn.execute("INSERT OR REPLACE INTO expansion_protect VALUES (?,?,?,?,1)", (e["exp_id"], team, scheme, json.dumps(list(pids))))


def exposed(conn, team, pl=None):
    pl = pl or pool(conn, team)
    p = protection(conn, team) or {"players": []}
    return [x for x in pl.values() if x["eligible"] and x["player_id"] not in p["players"]]


# ---------------------------------------------------------------- the draft
def _cap(conn):
    from . import contracts as K
    return K.crules(conn).get("cap_ceiling") or 0


def _hit(conn, pid, year):
    r = conn.execute("SELECT cap_hit FROM contracts WHERE player_id=? AND start_year<=? AND start_year+years>?", (pid, year, year)).fetchone()
    return r[0] if r else 0


def _shortfalls(sel, year_hits, cap):
    g = {"F": 0, "D": 0, "G": 0}
    under = 0
    pay = 0
    for x in sel.values():
        g[x["group"]] += 1
        under += 1 if x["under"] else 0
        pay += year_hits.get(x["player_id"], 0)
    out = {}
    if g["F"] < NEED_F:
        out["F"] = NEED_F - g["F"]
    if g["D"] < NEED_D:
        out["D"] = NEED_D - g["D"]
    if g["G"] < NEED_G:
        out["G"] = NEED_G - g["G"]
    if under < NEED_CONTRACTS:
        out["under"] = NEED_CONTRACTS - under
    if cap and pay < PAYROLL_RANGE[0] * cap:
        out["pay_low"] = PAYROLL_RANGE[0] * cap - pay
    if cap and pay > PAYROLL_RANGE[1] * cap:
        out["pay_high"] = pay - PAYROLL_RANGE[1] * cap
    return out


def plan(conn, fixed=None):
    """The expansion club's picks: {team: player dict}. fixed: {team: pid} already chosen (by you). AI picks take the
    most valuable exposed player from each club, then swap picks at least cost until the roster rules are met."""
    e = pending(conn)
    fixed = fixed or {}
    year = e["first_season"]
    cap = _cap(conn)
    pools = {t: exposed(conn, t) for t in _top(conn) if t != e["team_id"]}
    sel = {}
    for t, xs in pools.items():
        xs.sort(key=lambda x: -x["value"])
        if t in fixed:
            sel[t] = next((x for x in xs if x["player_id"] == fixed[t]), None)
    sel = {t: x for t, x in sel.items() if x}
    # the staff's picks: the best player available, with less for a position the roster already has enough of
    n = {"F": 0, "D": 0, "G": 0}
    for x in sel.values():
        n[x["group"]] += 1
    left = [t for t in pools if t not in sel and pools[t]]
    while left:
        best = None
        for t in left:
            for x in pools[t][:12]:
                v = x["value"] * POS_TAPER[x["group"]](n[x["group"]])
                if best is None or v > best[0]:
                    best = (v, t, x)
        _, t, x = best
        sel[t] = x
        n[x["group"]] += 1
        left.remove(t)
    hits = {x["player_id"]: _hit(conn, x["player_id"], year) for xs in pools.values() for x in xs}
    for _ in range(300):
        short = _shortfalls(sel, hits, cap)
        if not short:
            break
        best = None
        for t, xs in pools.items():
            if t in fixed or t not in sel:
                continue
            cur = sel[t]
            for alt in xs:
                if alt is cur:
                    continue
                trial = dict(sel)
                trial[t] = alt
                s2 = _shortfalls(trial, hits, cap)
                gain = _score(short) - _score(s2)
                if gain <= 0:
                    continue
                cost = (cur["value"] - alt["value"]) / gain
                if best is None or cost < best[0]:
                    best = (cost, t, alt)
        if best is None:
            break
        sel[best[1]] = best[2]
    return sel, pools


def _score(short):
    w = {"F": 10, "D": 10, "G": 12, "under": 6, "pay_low": 1e-6 * 2, "pay_high": 1e-6 * 2}
    return sum(w[k] * v for k, v in short.items())


def choose(conn, from_team, pid):
    """You (the expansion club's GM) take a player from a club."""
    e = pending(conn)
    if not e or e["status"] != "protecting":
        raise ValueError("The expansion draft is not open.")
    if user_team(conn) != e["team_id"]:
        raise ValueError("Only the expansion club's GM picks.")
    if pid not in {x["player_id"] for x in exposed(conn, from_team)}:
        raise ValueError("He is not available from that club.")
    conn.execute("INSERT OR REPLACE INTO expansion_picks (exp_id, from_team, player_id, pick_no, by_user) VALUES (?,?,?,NULL,1)",
                 (e["exp_id"], from_team, pid))


def unchoose(conn, from_team):
    e = pending(conn)
    if e:
        conn.execute("DELETE FROM expansion_picks WHERE exp_id=? AND from_team=? AND by_user=1", (e["exp_id"], from_team))


def run_draft(conn, day):
    """Hold the expansion draft (the day the entry draft phase opens). Returns message lines."""
    e = pending(conn)
    if e is None or e["status"] != "protecting":
        return []
    new = e["team_id"]
    me = user_team(conn)
    fixed = {r[0]: r[1] for r in conn.execute("SELECT from_team, player_id FROM expansion_picks WHERE exp_id=? AND by_user=1",
                                               (e["exp_id"],))}
    sel, pools = plan(conn, fixed)
    # side deals: AI clubs about to lose a valuable player pay a pick to steer the pick elsewhere (not with your club,
    # and not when you run the expansion club: you pick for yourself)
    deals = {}
    if me != new:
        from . import trades as T
        from .draft import draft_year
        dy = draft_year(conn)
        rng = random.Random(f"{get_state(conn)[1]}-exp-side-{e['exp_id']}")
        order = sorted(sel.items(), key=lambda kv: -kv[1]["value"])
        for t, x in order:
            if len(deals) >= SIDE_DEALS_MAX or t == me or t in fixed:
                continue
            alts = [a for a in pools[t] if a is not x and a["group"] == x["group"]] or [a for a in pools[t] if a is not x]
            if not alts:
                continue
            alt = max(alts, key=lambda a: a["value"])
            gap = x["value"] - alt["value"]
            if gap < SIDE_GAP_2ND or rng.random() < 0.35:
                continue
            trial = dict(sel)
            trial[t] = alt
            if _shortfalls(trial, {a["player_id"]: _hit(conn, a["player_id"], e["first_season"]) for a in trial.values()}, _cap(conn)):
                continue
            firsts = sum(1 for d in deals.values() if " 1st-round" in d)
            rnd = 1 if gap >= SIDE_GAP_1ST and firsts < SIDE_FIRSTS else 2
            for y in (dy, dy + 1):
                if T.pick_owner(conn, y, rnd, t) == t and not T.encumbered(conn, y, rnd, t):
                    conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)", (y, rnd, t, new, f"expansion side deal {day}"))
                    sel[t] = alt
                    deals[t] = f"{team_abbr(conn, t)} gave a {y} {'1st' if rnd == 1 else '2nd'}-round pick so that {alt['name']} was taken instead of {x['name']}"
                    break
    # make the picks
    lines = []
    from . import contracts as K
    for k, (t, x) in enumerate(sorted(sel.items(), key=lambda kv: -kv[1]["value"]), 1):
        pid = x["player_id"]
        conn.execute("UPDATE players SET team_id=?, club_id=CASE WHEN status='prospect' THEN ? ELSE ? END WHERE player_id=?",
                     (new, R.affiliate(conn, new) or new, new, pid))
        conn.execute("UPDATE contracts SET team_id=? WHERE player_id=? AND start_year+years>?", (new, pid, K.season_year(conn)))
        for tbl in ("trade_block", "leadership"):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tbl,)).fetchone():
                conn.execute(f"DELETE FROM {tbl} WHERE player_id=?", (pid,))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES (?,?,?,?,?,?)",
                     (day, "expansion", pid, t, new, f"taken in the expansion draft by {e['abbr']}"))
        conn.execute("INSERT OR REPLACE INTO expansion_picks (exp_id, from_team, player_id, pick_no, by_user, side_deal) VALUES (?,?,?,?,?,?)",
                     (e["exp_id"], t, pid, k, int(t in fixed), deals.get(t)))
        emit(conn, "EXPANSION_PICK", day, f"{e['abbr']} take {x['name']} from {team_abbr(conn, t)} in the expansion draft",
             team_id=new, other_team_id=t, player_id=pid, importance=2 if x["value"] >= 50 else 1)
        if t == me:
            add_message(conn, day, f"Expansion draft: {e['abbr']} take {x['name']}",
                        f"The {e['city']} {e['nickname']} took {x['name']} from us in the expansion draft.", sender="Assistant GM")
    for t in _top(conn):
        R.ensure_dressable(conn, t, day)
    from . import people
    people.setup(conn, day)                                # the new club's leadership group
    conn.execute("UPDATE expansion SET status='drafted', drafted=? WHERE exp_id=?", (day, e["exp_id"]))
    picks = conn.execute("SELECT p.first_name||' '||p.last_name, t.abbr, x.side_deal FROM expansion_picks x JOIN players p USING "
                         "(player_id) JOIN teams t ON t.team_id=x.from_team WHERE x.exp_id=? ORDER BY x.pick_no", (e["exp_id"],)).fetchall()
    head = f"The {e['city']} {e['nickname']} expansion draft: " + ", ".join(f"{n} ({a})" for n, a, _ in picks[:8]) + (" ..." if len(picks) > 8 else "")
    emit(conn, "MEDIA_STORY", day, head[:180], importance=3, headline=f"The {e['nickname']} are stocked", body=head
         + (". Side deals: " + "; ".join(deals.values()) if deals else ""), tag="expansion", kind="expansion_draft")
    add_message(conn, day, "The expansion draft", "\n".join([f"{k}. {n} (from {a})" + (f" - {d}" if d else "") for k, (n, a, d) in enumerate(picks, 1)]),
                sender="League office")
    lines.append(f"Expansion draft: the {e['city']} {e['nickname']} took {len(picks)} players" + (f"; {len(deals)} side deals" if deals else "") + ".")
    return lines


def joined(conn):
    """A new season has begun: the club is a full member."""
    ensure_tables(conn)
    conn.execute("UPDATE expansion SET status='joined' WHERE status='drafted' AND first_season<=?", (_season(conn),))


def draft_slot_teams(conn, year):
    """Clubs that join with this entry draft (they get the third-worst club's lottery odds)."""
    ensure_tables(conn)
    return [r[0] for r in conn.execute("SELECT team_id FROM expansion WHERE draft_year=? AND team_id IS NOT NULL", (year,))]


# ---------------------------------------------------------------- the screen
def view(conn):
    ensure_tables(conn)
    me = user_team(conn)
    e = pending(conn)
    out = dict(mode=mode(conn), clubs=len(_top(conn)), max=MAX_CLUBS, state=_state(conn), me=me,
               candidates=[dict(city=c[0], nickname=c[1], abbr=c[2], market=c[3], conference=c[4], capacity=c[5]) for c in CANDIDATES
                           if c[2] not in _top_abbrs(conn)],
               conferences=sorted({r[0] for r in conn.execute(f"SELECT conference FROM teams WHERE team_id IN ({','.join(map(str, _top(conn)))})")}),
               divisions={c: sorted({r[0] for r in conn.execute(f"SELECT division FROM teams WHERE conference=? AND team_id IN ({','.join(map(str, _top(conn)))})", (c,))})
                          for c in {r[0] for r in conn.execute(f"SELECT conference FROM teams WHERE team_id IN ({','.join(map(str, _top(conn)))})")}},
               history=[dict(r) for r in conn.execute("SELECT city, nickname, abbr, first_season, status, drafted FROM expansion ORDER BY exp_id DESC")])
    if e:
        out["pending"] = dict(e)
        if e["status"] == "protecting":
            if me == e["team_id"]:
                fixed = {r[0]: r[1] for r in conn.execute("SELECT from_team, player_id FROM expansion_picks WHERE exp_id=? AND by_user=1", (e["exp_id"],))}
                sel, pools = plan(conn, fixed)
                out["draft"] = [dict(team_id=t, abbr=team_abbr(conn, t), mine=t in fixed, pick=sel.get(t),
                                     exposed=sorted(xs, key=lambda x: -x["value"])[:25]) for t, xs in sorted(pools.items(), key=lambda kv: team_abbr(conn, kv[0]))]
                out["shortfalls"] = _shortfalls({t: x for t, x in sel.items() if t in fixed},
                                                {x["player_id"]: _hit(conn, x["player_id"], e["first_season"]) for t, x in sel.items()}, _cap(conn))
                out["plan_shortfalls"] = _shortfalls(sel, {x["player_id"]: _hit(conn, x["player_id"], e["first_season"]) for x in sel.values()}, _cap(conn))
            elif me:
                pl = pool(conn, me)
                p = protection(conn, me) or {}
                out["protect"] = dict(scheme=p.get("scheme"), players=p.get("players", []), by_user=p.get("by_user"),
                                      pool=sorted(pl.values(), key=lambda x: ("FDG".index(x["group"]), -x["value"])),
                                      problems=validate(conn, me, p.get("scheme"), p.get("players", []), pl) if p else [])
    done = conn.execute("SELECT * FROM expansion WHERE status IN ('drafted','joined') ORDER BY exp_id DESC LIMIT 1").fetchone()
    if done:
        out["last_draft"] = dict(club=f"{done['city']} {done['nickname']}", picks=[dict(name=r[0], pos=r[1], frm=r[2], side=r[3], player_id=r[4]) for r in conn.execute(
            "SELECT p.first_name||' '||p.last_name, p.position, t.abbr, x.side_deal, p.player_id FROM expansion_picks x JOIN players p USING (player_id) "
            "JOIN teams t ON t.team_id=x.from_team WHERE x.exp_id=? ORDER BY x.pick_no", (done["exp_id"],))])
    return out
