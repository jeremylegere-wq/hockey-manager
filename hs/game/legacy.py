"""What a career leaves behind (phase F, v37): the Hall of Fame, GM leaders and the GM score, your achievements.

Hall of Fame (v45: the Career Legacy Score, hs/game/legacy_score.py and docs/HALL_OF_FAME.md). Each summer (when the
re-signing phase opens) the class is inducted from the ballot: retired players three years on, with a CLS of 250 or
more, for up to ten years; the best four by CLS go in. Career option hof (hs/game/exhibitions.py): committee, where you
get the ballot in your inbox and may back up to four (CLI `hof vote <player> [<player> ...]`; a backed candidate passes
unbacked ones within 15 points), or auto. (Before v45 an 18-member committee voted on a simpler case score.)

GM score and GM leaders. Every season each club's GM (you, or the AI GM on the board's books, hs/game/boardroom.py)
earns a season score: (points % - .500) x 100, +5 for each playoff round reached, +10 more for the championship,
+8 for the GM of the year award. A GM's career score is the sum; GM leaders ranks them, with seasons, clubs, record,
playoffs and championships. The save keeps it from its first finished season.

Achievements: milestones of your career as a GM (the list in ACHIEVEMENTS), checked weekly and at season end; each one
once, dated, with an inbox note and a news line.
"""
from __future__ import annotations

import json
import math
import random

from ..schema import top_league_sql
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

WAIT = 3
COMMITTEE = 18
MAX_IN = 4
BAR = 0.75
CENTRE, SPREAD = 82.0, 7.0
TROPHY = {"hart": 10, "vezina": 8, "norris": 8, "art_ross": 6, "conn_smythe": 6, "richard": 4, "calder": 2}


from . import career as CR

def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS hall_of_fame (player_id INTEGER PRIMARY KEY, year INTEGER, votes INTEGER, of INTEGER, "
                 "score REAL, line TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS hof_ballot (year INTEGER, player_id INTEGER, score REAL, my_vote INTEGER DEFAULT 0, "
                 "votes INTEGER, inducted INTEGER, PRIMARY KEY (year, player_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS gm_seasons (season_start_year INTEGER, team_id INTEGER, gm_name TEXT, is_user INTEGER, "
                 "pts_pct REAL, w INTEGER, l INTEGER, otl INTEGER, playoff_round INTEGER, score REAL, PRIMARY KEY (season_start_year, team_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS achievements (key TEXT PRIMARY KEY, day TEXT, detail TEXT)")


def _top(conn):
    return conn.execute("SELECT league_id FROM leagues ORDER BY level, league_id LIMIT 1").fetchone()[0] \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='leagues'").fetchone() else 1


def _year(conn):
    from . import contracts as K
    return K.season_year(conn)


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


# ---------------------------------------------------------------- the Hall of Fame
def career(conn, pid):
    """A player's NHL career in the save: totals, trophies, championships, last season, and his Hall of Fame score."""
    lg = 1
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
    pos = pos[0] if pos else "C"
    out = dict(player_id=pid, pos=pos)
    if pos == "G":
        r = conn.execute("SELECT SUM(gp), SUM(sa), SUM(ga), SUM(w), SUM(so), MIN(season_start_year), MAX(season_start_year) FROM goalie_season_stats "
                         "WHERE player_id=? AND league_id=? AND split='RS'", (pid, lg)).fetchone()
        gp, sa, ga = r[0] or 0, r[1] or 0, r[2] or 0
        sv = (sa - ga) / sa if sa else 0.0
        pr = CR.prior(conn, pid) or {}
        out.update(gp=gp + (pr.get("gp") or 0), sv=round(sv, 3), w=(r[3] or 0) + (pr.get("w") or 0),
                   so=(r[4] or 0) + (pr.get("so") or 0), first=r[5], last=r[6], prior=bool(pr))
        gp = out["gp"]
        base = 0.1 * gp + 1500 * (sv - 0.905) * min(1.0, gp / 300) if gp else 0.0
    else:
        r = conn.execute("SELECT SUM(gp), SUM(g), SUM(a), MIN(season_start_year), MAX(season_start_year) FROM skater_season_stats "
                         "WHERE player_id=? AND league_id=? AND split='RS'", (pid, lg)).fetchone()
        po = conn.execute("SELECT SUM(g), SUM(a) FROM skater_season_stats WHERE player_id=? AND league_id=? AND split='PO'", (pid, lg)).fetchone()
        pr = CR.prior(conn, pid) or {}             # v41: the career before the save began
        gp, g, a = (r[0] or 0) + (pr.get("gp") or 0), (r[1] or 0) + (pr.get("g") or 0), (r[2] or 0) + (pr.get("a") or 0)
        pg, pa = po[0] or 0, po[1] or 0
        out["prior"] = bool(pr)
        out.update(gp=gp, g=g, a=a, pts=g + a, po_pts=pg + pa, first=r[3], last=r[4])
        base = (0.06 * (g + a + pg + pa) + 0.02 * (g + pg) + 0.01 * gp) * (1.25 if pos == "D" else 1.0)
    if out["last"] is None:                               # goalies may have their last season in either table
        out["last"] = conn.execute("SELECT MAX(season_start_year) FROM skater_season_stats WHERE player_id=? AND league_id=?", (pid, lg)).fetchone()[0]
    tro = {}
    if _has(conn, "awards"):
        for k, n in conn.execute("SELECT award, COUNT(*) FROM awards WHERE player_id=? GROUP BY award", (pid,)):
            tro[k] = n
    cups = 0
    if _has(conn, "team_seasons"):
        tbl = "goalie_season_stats" if pos == "G" else "skater_season_stats"
        cups = conn.execute(f"SELECT COUNT(DISTINCT s.season_start_year) FROM {tbl} s JOIN team_seasons t ON t.season_start_year=s.season_start_year "
                            f"AND t.team_id=s.team_id WHERE s.player_id=? AND s.league_id=? AND t.playoff_round=5", (pid, lg)).fetchone()[0]
    score = base + sum(TROPHY.get(k, 0) * n for k, n in tro.items()) + 3 * cups
    out.update(trophies=tro, cups=cups, score=round(score, 1))
    return out


def line_of(c):
    if c["pos"] == "G":
        s = f"{c['gp']} games, {c['sv']:.3f} save %".replace("0.", ".")
    else:
        s = f"{c['gp']} games, {c['g']} goals, {c['pts']} points"
    t = [f"{n} {k.replace('_', ' ').title()}" for k, n in sorted(c["trophies"].items()) if k in TROPHY]
    if c["cups"]:
        t.append(f"{c['cups']} championship{'s' if c['cups'] > 1 else ''}")
    return s + (" · " + ", ".join(t) if t else "")


def eligible(conn, year):
    """[(score, career)] of retired players whose last NHL season was WAIT or more seasons before `year`."""
    ensure_tables(conn)
    held = {r[0] for r in conn.execute("SELECT player_id FROM hall_of_fame")}
    ids = [r[0] for r in conn.execute(
        "SELECT p.player_id FROM players p WHERE p.status='retired' AND EXISTS (SELECT 1 FROM skater_season_stats s WHERE s.player_id=p.player_id "
        "AND s.league_id=1 AND s.split='RS' GROUP BY s.player_id HAVING MAX(s.season_start_year)<=? AND SUM(s.gp)>=300) "
        "UNION SELECT p.player_id FROM players p WHERE p.status='retired' AND p.position='G' AND EXISTS (SELECT 1 FROM goalie_season_stats s "
        "WHERE s.player_id=p.player_id AND s.league_id=1 AND s.split='RS' GROUP BY s.player_id HAVING MAX(s.season_start_year)<=? AND SUM(s.gp)>=150)",
        (year - WAIT, year - WAIT))]
    out = []
    for pid in ids:
        if pid in held:
            continue
        c = career(conn, pid)
        if c["last"] is not None and c["last"] <= year - WAIT:
            out.append((c["score"], c))
    out.sort(key=lambda x: (-x[0], x[1]["player_id"]))
    return out


def _hof_columns(conn):
    ensure_tables(conn)
    for t, cols in (("hall_of_fame", (("cls", "REAL"), ("tier", "TEXT"), ("ballot_years", "INTEGER"))),
                    ("hof_ballot", (("ballot_years", "INTEGER"), ("tier", "TEXT")))):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        for c, ty in cols:
            if c not in have:
                conn.execute(f"ALTER TABLE {t} ADD COLUMN {c} {ty}")


def open_ballot(conn, day):
    """At the end of the season: this summer's ballot (everyone eligible with a CLS of 250+, best first)."""
    from . import legacy_score as LS
    _hof_columns(conn)
    year = _year(conn) + 1                                  # inducted in the summer after the season
    if conn.execute("SELECT 1 FROM hof_ballot WHERE year=?", (year,)).fetchone():
        return []
    rows = LS.candidates(conn, year)
    conn.executemany("INSERT INTO hof_ballot (year, player_id, score, ballot_years, tier) VALUES (?,?,?,?,?)",
                     [(year, s["player_id"], s["cls"], s["years_on_ballot"], s["tier"]) for s in rows])
    from .exhibitions import options
    if rows and options(conn)["hof"] == "committee" and user_team(conn) is not None:
        txt = "\n".join(f"- {player_name(conn, s['player_id'])}: CLS {s['cls']:.1f} ({s['tier']}), year {s['years_on_ballot']} on the ballot"
                        for s in rows[:15])
        add_message(conn, day, "Hall of Fame ballot", f"You sit on the Hall of Fame selection committee. This year's ballot:\n{txt}\n"
                    f"The four best Career Legacy Scores go in. Back up to four (League > Hall of Fame, or `hof vote <player> ...`): "
                    "a candidate you back passes any unbacked candidate within 15 points. The class is named when the re-signing "
                    "phase opens.")
    return [(s["cls"], s) for s in rows]


def vote(conn, pids):
    ensure_tables(conn)
    year = _year(conn) + 1
    on = {r[0] for r in conn.execute("SELECT player_id FROM hof_ballot WHERE year=? AND inducted IS NULL", (year,))}
    if not on:
        raise ValueError("There is no open Hall of Fame ballot.")
    pids = list(dict.fromkeys(pids))
    if len(pids) > MAX_IN:
        raise ValueError(f"Vote for up to {MAX_IN}.")
    bad = [p for p in pids if p not in on]
    if bad:
        raise ValueError(f"{player_name(conn, bad[0])} is not on the ballot.")
    conn.execute("UPDATE hof_ballot SET my_vote=0 WHERE year=?", (year,))
    conn.executemany("UPDATE hof_ballot SET my_vote=1 WHERE year=? AND player_id=?", [(year, p) for p in pids])
    return pids


def _support(score):
    return 1 / (1 + math.exp(-(score - CENTRE) / SPREAD))


def election(conn, day):
    """The class is named (when the re-signing phase opens). Returns the summary lines."""
    from . import legacy_score as LS
    _hof_columns(conn)
    year = _year(conn) + 1 if conn.execute("SELECT 1 FROM hof_ballot WHERE year=? AND inducted IS NULL", (_year(conn) + 1,)).fetchone() \
        else _year(conn)
    rows = conn.execute("SELECT player_id, score, my_vote, ballot_years FROM hof_ballot WHERE year=? AND inducted IS NULL", (year,)).fetchall()
    if not rows:
        return []
    from .exhibitions import options
    you = options(conn)["hof"] == "committee" and user_team(conn) is not None
    cands = [dict(player_id=r[0], cls=r[1], years_on_ballot=r[3] or 1) for r in rows]
    ranked = LS.order(cands, [r[0] for r in rows if r[2]] if you else ())
    ins = [c["player_id"] for c in ranked[:LS.MAX_IN]]
    for k, c in enumerate(ranked, 1):
        conn.execute("UPDATE hof_ballot SET votes=?, inducted=? WHERE year=? AND player_id=?", (k, int(c["player_id"] in ins), year, c["player_id"]))
    lines = []
    for c in ranked[:LS.MAX_IN]:
        pid = c["player_id"]
        cr = career(conn, pid)
        t = LS.tier(c["cls"])
        n = c["years_on_ballot"]
        conn.execute("INSERT OR REPLACE INTO hall_of_fame (player_id, year, votes, of, score, line, cls, tier, ballot_years) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (pid, year, None, None, c["cls"], line_of(cr), c["cls"], t, n))
        nth = "th" if 11 <= n <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        emit(conn, "HALL_OF_FAME", day, f"{player_name(conn, pid)} is elected to the Hall of Fame ({t}, CLS {c['cls']:.0f})",
             player_id=pid, importance=3 if n == 1 and c["cls"] >= 350 else 2, cls=c["cls"], tier=t, ballot_year=n)
        lines.append(f"{player_name(conn, pid)} ({cr['pos']}): CLS {c['cls']:.1f}, {t}, {n}{nth} year on the ballot · {line_of(cr)}")
    if user_team(conn) is not None:
        add_message(conn, day, "Hall of Fame class", (f"The {year} Hall of Fame class:\n" + "\n".join(f"- {x}" for x in lines)) if lines
                    else "Nobody was eligible with a Career Legacy Score of 250: no Hall of Fame class this year.")
    return lines


def hof_view(conn):
    from . import legacy_score as LS
    _hof_columns(conn)
    members = [dict(player_id=r["player_id"], name=player_name(conn, r["player_id"]), year=r["year"], score=r["cls"] if r["cls"] is not None else r["score"],
                    cls=r["cls"], tier=r["tier"] or (LS.tier(r["cls"]) if r["cls"] else ""), ballot_years=r["ballot_years"], line=r["line"],
                    votes=r["votes"], of=r["of"],
                    pos=(conn.execute("SELECT position FROM players WHERE player_id=?", (r["player_id"],)).fetchone() or ["?"])[0])
               for r in conn.execute("SELECT * FROM hall_of_fame ORDER BY year DESC, COALESCE(cls, score) DESC")]
    ballot = []
    open_ = False
    for r in conn.execute("SELECT * FROM hof_ballot WHERE year=(SELECT MAX(year) FROM hof_ballot) ORDER BY score DESC"):
        c = career(conn, r["player_id"])
        open_ = open_ or r["inducted"] is None
        ballot.append(dict(player_id=r["player_id"], name=player_name(conn, r["player_id"]), pos=c["pos"], score=r["score"], line=line_of(c),
                           my_vote=bool(r["my_vote"]), rank=r["votes"], inducted=r["inducted"], last=c["last"],
                           ballot_years=r["ballot_years"], tier=r["tier"] or LS.tier(r["score"] or 0)))
    by = conn.execute("SELECT MAX(year) FROM hof_ballot").fetchone()[0]
    from .exhibitions import options
    return dict(members=members, ballot=ballot, ballot_year=by, open=open_, mode=options(conn)["hof"], max=LS.MAX_IN, wait=LS.WAIT,
                threshold=LS.THRESHOLD, ballot_life=LS.BALLOT_YEARS, tiers=[dict(bar=b, name=n) for b, n in LS.TIERS])


def legacy_view(conn, pid=None, active=True):
    """The CLS tracker (the best careers, active or all) or one player's breakdown."""
    from . import legacy_score as LS
    if pid:
        s = LS.score(conn, int(pid))
        s["name"] = player_name(conn, int(pid))
        s["items"] = [dict(label=a, pts=b) for a, b in s["items"]]
        return s
    rows = LS.tracker(conn, 40, active=active)
    return dict(rows=[dict(player_id=s["player_id"], name=player_name(conn, s["player_id"]), group=s["group"], cls=s["cls"], tier=s["tier"],
                           peak=s["peak"], longevity=s["longevity"], pvl=s["pvl"], hardware=s["hardware"], seasons=s["seasons"]) for s in rows],
                active=active)


# ---------------------------------------------------------------- GM score and GM leaders
def gm_season_score(pts_pct, rnd, gm_year=False):
    return round((pts_pct - 0.5) * 100 + 5 * min(rnd, 4) + (10 if rnd >= 5 else 0) + (8 if gm_year else 0), 1)


def record_gm_season(conn, year):
    """After awards night: each club's GM for the season, and his season score. Idempotent."""
    ensure_tables(conn)
    if conn.execute("SELECT 1 FROM gm_seasons WHERE season_start_year=?", (year,)).fetchone():
        return 0
    me = user_team(conn)
    try:
        you = conn.execute("SELECT name FROM manager WHERE id=1").fetchone()[0] or "You"
    except Exception:
        you = "You"
    names = {r[0]: r[1] for r in conn.execute("SELECT team_id, gm_name FROM board")} if _has(conn, "board") else {}
    gmy = conn.execute("SELECT team_id FROM awards WHERE season_start_year=? AND award='gm_year'", (year,)).fetchone() if _has(conn, "awards") else None
    n = 0
    for r in conn.execute("SELECT * FROM team_seasons WHERE season_start_year=? AND league_id=?", (year, _top(conn))):
        t = r["team_id"]
        gp = r["gp"] or 1
        ppct = (r["pts"] or 0) / (2 * gp)
        user = t == me
        name = you if user else (names.get(t) or f"{team_abbr(conn, t)} GM")
        conn.execute("INSERT OR REPLACE INTO gm_seasons VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (year, t, name, int(user), round(ppct, 3), r["w"], r["l"], r["otl"], r["playoff_round"] or 0,
                      gm_season_score(ppct, r["playoff_round"] or 0, bool(gmy and gmy[0] == t))))
        n += 1
    return n


def gm_leaders(conn):
    ensure_tables(conn)
    cur = {r[0]: r[1] for r in conn.execute("SELECT team_id, gm_name FROM board")} if _has(conn, "board") else {}
    me = user_team(conn)
    rows = {}
    for r in conn.execute("SELECT * FROM gm_seasons ORDER BY season_start_year"):
        key = "__you__" if r["is_user"] else r["gm_name"]
        d = rows.setdefault(key, dict(name=r["gm_name"], you=bool(r["is_user"]), seasons=0, clubs=[], w=0, l=0, otl=0, playoffs=0,
                                      finals=0, cups=0, score=0.0, best=None))
        d["seasons"] += 1
        ab = team_abbr(conn, r["team_id"])
        if ab not in d["clubs"]:
            d["clubs"].append(ab)
        d["w"] += r["w"] or 0
        d["l"] += r["l"] or 0
        d["otl"] += r["otl"] or 0
        d["playoffs"] += int((r["playoff_round"] or 0) > 0)
        d["finals"] += int((r["playoff_round"] or 0) >= 4)
        d["cups"] += int((r["playoff_round"] or 0) >= 5)
        d["score"] = round(d["score"] + r["score"], 1)
        if d["best"] is None or r["score"] > d["best"]["score"]:
            d["best"] = dict(year=r["season_start_year"], club=ab, score=r["score"])
    for k, d in rows.items():
        d["current"] = (d["you"] and me is not None) or d["name"] in cur.values()
        d["club_now"] = team_abbr(conn, me) if d["you"] and me is not None else next((team_abbr(conn, t) for t, n in cur.items() if n == d["name"]), None)
        g = d["w"] + d["l"] + d["otl"]
        d["pts_pct"] = round((2 * d["w"] + d["otl"]) / (2 * g), 3) if g else None
    out = sorted(rows.values(), key=lambda d: (-d["score"], d["name"]))
    for i, d in enumerate(out):
        d["rank"] = i + 1
    return dict(leaders=out, seasons=[r[0] for r in conn.execute("SELECT DISTINCT season_start_year FROM gm_seasons ORDER BY 1")])


def my_gm_score(conn):
    lead = gm_leaders(conn)["leaders"]
    me = next((d for d in lead if d["you"]), None)
    return dict(score=me["score"] if me else 0.0, rank=me["rank"] if me else None, of=len(lead))


# ---------------------------------------------------------------- achievements
def _my_seasons(conn):
    return conn.execute("SELECT * FROM gm_seasons WHERE is_user=1 ORDER BY season_start_year").fetchall()


def _since(conn):
    r = conn.execute("SELECT MIN(start_date) FROM gm_career").fetchone() if _has(conn, "gm_career") else None
    return r[0] if r and r[0] else "0000"


def _my_games(conn):
    """(won, date) of your club's games since you took over, in order (the club you ran at the time)."""
    out = []
    if not _has(conn, "gm_career"):
        return out
    for st in conn.execute("SELECT team_id, start_date, COALESCE(end_date, '9999') FROM gm_career").fetchall():
        for h, a, hg, ag, d, typ in conn.execute("SELECT home_team_id, away_team_id, home_goals, away_goals, game_date, game_type FROM games "
                                                 "WHERE played=1 AND (home_team_id=? OR away_team_id=?) AND game_date>=? AND game_date<=? ORDER BY game_date",
                                                 (st[0], st[0], st[1], st[2])):
            out.append(((hg > ag) == (h == st[0]), d, typ))
    out.sort(key=lambda x: x[1])
    return out


def _streak(games, n):
    run = 0
    for w, d, typ in games:
        if typ != "RS":
            continue
        run = run + 1 if w else 0
        if run >= n:
            return True
    return False


def _award_mine(conn, keys):
    if not _has(conn, "awards"):
        return False
    for st in conn.execute("SELECT team_id, start_date FROM gm_career").fetchall() if _has(conn, "gm_career") else []:
        if conn.execute(f"SELECT 1 FROM awards WHERE team_id=? AND award IN ({','.join('?' * len(keys))}) AND season_start_year>=?",
                        (st[0], *keys, int(st[1][:4]))).fetchone():
            return True
    return False


def _count_txn(conn, kind):
    me = user_team(conn)
    if me is None:
        return 0
    return conn.execute("SELECT COUNT(DISTINCT txn_date||detail) FROM transactions WHERE txn_type=? AND (from_team_id=? OR to_team_id=?) AND txn_date>=?",
                        (kind, me, me, _since(conn))).fetchone()[0]


def _first_overall(conn):
    me = user_team(conn)
    if me is None or not _has(conn, "draft_rights"):
        return False
    return bool(conn.execute("SELECT 1 FROM draft_rights WHERE team_id=? AND overall_pick=1 AND draft_year>=?", (me, int(_since(conn)[:4]))).fetchone())


def _profit(conn):
    if not _has(conn, "finance_season"):
        return False
    me = user_team(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(finance_season)")}
    col = "profit" if "profit" in cols else None
    return bool(col and conn.execute(f"SELECT 1 FROM finance_season WHERE team_id=? AND {col}>0", (me,)).fetchone())


def _exhib(conn, kind, test):
    if not _has(conn, "exhibitions"):
        return False
    me = user_team(conn)
    for r in conn.execute("SELECT notes FROM exhibitions WHERE kind=? AND notes IS NOT NULL", (kind,)):
        n = json.loads(r[0])
        if test(n, me):
            return True
    return False


def _rival_sweep(conn):
    from . import rivalry as RV
    me = user_team(conn)
    m = RV.main_rival(conn, me) if me is not None else None
    if not m:
        return False
    o = m["team_id"]
    for (sid,) in conn.execute("SELECT DISTINCT season_id FROM games WHERE played=1 AND game_type='RS'"):
        rows = conn.execute("SELECT home_team_id, home_goals, away_goals FROM games WHERE season_id=? AND game_type='RS' AND ((home_team_id=? "
                            "AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))", (sid, me, o, o, me)).fetchall()
        unplayed = conn.execute("SELECT COUNT(*) FROM games WHERE season_id=? AND game_type='RS' AND played=0 AND ((home_team_id=? "
                                "AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))", (sid, me, o, o, me)).fetchone()[0]
        played = [r for r in rows if r[1] is not None]
        if len(played) >= 3 and not unplayed and all((r[1] > r[2]) == (r[0] == me) for r in played):
            return True
    return False


ACHIEVEMENTS = [  # key, name, description, check(conn, ctx) -> bool
    ("first_win", "First win", "Win a game as GM.", lambda c, x: any(w for w, d, t in x["games"])),
    ("streak5", "On a roll", "Win five straight regular-season games.", lambda c, x: _streak(x["games"], 5)),
    ("streak10", "Unstoppable", "Win ten straight regular-season games.", lambda c, x: _streak(x["games"], 10)),
    ("playoffs", "Playoff hockey", "Make the playoffs.", lambda c, x: any(r["playoff_round"] >= 1 for r in x["seasons"])),
    ("series", "Moving on", "Win a playoff series.", lambda c, x: any(r["playoff_round"] >= 2 for r in x["seasons"])),
    ("final", "Final four... and two", "Reach the final.", lambda c, x: any(r["playoff_round"] >= 4 for r in x["seasons"])),
    ("cup", "Champions", "Win the championship.", lambda c, x: any(r["playoff_round"] >= 5 for r in x["seasons"])),
    ("dynasty", "Dynasty", "Win three championships.", lambda c, x: sum(r["playoff_round"] >= 5 for r in x["seasons"]) >= 3),
    ("hundred", "Hundred-point club", "A 100-point season.", lambda c, x: any((r["w"] or 0) * 2 + (r["otl"] or 0) >= 100 for r in x["seasons"])),
    ("presidents", "Best in the league", "Win the Presidents' Trophy.", lambda c, x: _award_mine(c, ["presidents"])),
    ("gm_year", "GM of the year", "Win the GM of the year award.", lambda c, x: _award_mine(c, ["gm_year"])),
    ("mvp", "We have the MVP", "One of your players wins the Hart Trophy.", lambda c, x: _award_mine(c, ["hart"])),
    ("scoring", "Scoring champion", "One of your players wins the Art Ross Trophy.", lambda c, x: _award_mine(c, ["art_ross"])),
    ("five_seasons", "Settled in", "Five seasons in charge.", lambda c, x: len(x["seasons"]) >= 5),
    ("ten_seasons", "Institution", "Ten seasons in charge.", lambda c, x: len(x["seasons"]) >= 10),
    ("trader", "Wheeler-dealer", "Make ten trades.", lambda c, x: _count_txn(c, "trade") >= 10),
    ("first_overall", "First overall", "Make the first pick in the draft.", lambda c, x: _first_overall(c)),
    ("profit", "In the black", "Turn a profit over a season.", lambda c, x: _profit(c)),
    ("prospects", "Next generation", "Your prospects win their tournament.",
     lambda c, x: _exhib(c, "PROSPECTS", lambda n, me: n.get("champion") == me)),
    ("allstar_mvp", "Star of the stars", "One of your players is the All-Star Game MVP.",
     lambda c, x: _exhib(c, "ASG", lambda n, me: n.get("mvp") and c.execute("SELECT 1 FROM exhibition_stats s JOIN exhibitions e USING (ex_id) "
                                                                             "WHERE e.kind='ASG' AND s.player_id=? AND s.team_id=?", (n["mvp"], me)).fetchone())),
    ("rival_sweep", "Bragging rights", "Beat your main rival in every meeting of a season (three or more).", lambda c, x: _rival_sweep(c)),
    ("hall", "Builder", "A player you had on your club is elected to the Hall of Fame.",
     lambda c, x: bool(c.execute("SELECT 1 FROM hall_of_fame h JOIN skater_season_stats s ON s.player_id=h.player_id WHERE s.team_id IN "
                                 "(SELECT team_id FROM gm_career) AND s.season_start_year>=? LIMIT 1", (int(_since(c)[:4]),)).fetchone())),
]


def check_achievements(conn, day):
    """Award what has been earned and not yet awarded. Returns the new keys."""
    ensure_tables(conn)
    if user_team(conn) is None and not _has(conn, "gm_career"):
        return []
    have = {r[0] for r in conn.execute("SELECT key FROM achievements")}
    todo = [a for a in ACHIEVEMENTS if a[0] not in have]
    if not todo:
        return []
    ctx = dict(games=_my_games(conn), seasons=_my_seasons(conn))
    new = []
    for key, name, desc, test in todo:
        try:
            ok = test(conn, ctx)
        except Exception:
            ok = False
        if ok:
            conn.execute("INSERT INTO achievements VALUES (?,?,?)", (key, day, desc))
            emit(conn, "ACHIEVEMENT", day, f"Achievement: {name}", team_id=user_team(conn), importance=1, key=key)
            new.append(key)
    if new:
        _achievement_mail(conn, day, new, ctx, have)
    return new


def _last_game_line(conn):
    """'a 4-1 win over the Maple Leafs on 18 Oct' for your club's latest game."""
    me = user_team(conn)
    g = conn.execute("SELECT home_team_id, away_team_id, home_goals, away_goals, game_date, went_to_ot FROM games WHERE played=1 "
                     "AND (home_team_id=? OR away_team_id=?) ORDER BY game_date DESC LIMIT 1", (me, me)).fetchone() if me else None
    if not g:
        return ""
    home = g[0] == me
    gf, ga = (g[2], g[3]) if home else (g[3], g[2])
    opp = conn.execute("SELECT COALESCE(nickname, name) FROM teams WHERE team_id=?", (g[1] if home else g[0],)).fetchone()[0]
    import datetime as _dt
    d = _dt.date.fromisoformat(g[4][:10])
    return (f"a {gf}-{ga}{' overtime' if g[5] else ''} {'win over' if gf > ga else 'loss to'} the {opp} on "
            f"{d.day} {d.strftime('%b')}")


def _achievement_mail(conn, day, new, ctx, had):
    """v39 (#2): an achievement is a proper note from the league office: what you did, when, and what is next."""
    names = {k: (n, d) for k, n, d, t in ACHIEVEMENTS}
    games = ctx.get("games") or []
    rs = [g for g in games if g[2] == "RS"]
    w = sum(1 for g in rs if g[0])
    lines = []
    for k in new:
        n, d = names[k]
        why = {"first_win": f"It came with {_last_game_line(conn)}.",
               "streak5": f"Five in a row, the latest {_last_game_line(conn)}.",
               "streak10": f"Ten in a row, the latest {_last_game_line(conn)}. Streaks like that are rare in a 32-team league."}.get(k, "")
        lines.append(f"{n}. {d} {why}".strip())
    total = len(had) + len(new)
    left = [names[k] for k, *_ in ACHIEVEMENTS if k not in had and k not in new][:3]
    body = ("Congratulations from the league office.\n\n" + "\n".join("- " + x for x in lines)
            + (f"\n\nYour record as GM: {w}-{len(rs) - w} in regular-season games." if rs else "")
            + f"\n\nYou have earned {total} of {len(ACHIEVEMENTS)} achievements."
            + ("\nStill to come: " + "; ".join(f"{n} ({d.rstrip('.').lower()})" for n, d in left) + "." if left else "")
            + "\n\nManager > Achievements has the full list.")
    subject = ("Achievement unlocked: " + names[new[0]][0]) if len(new) == 1 else f"{len(new)} achievements unlocked"
    add_message(conn, day, subject, body, sender="League office",
                actions=[dict(label="See your achievements", href="#achievements")])


def achievements_view(conn):
    ensure_tables(conn)
    got = {r[0]: r[1] for r in conn.execute("SELECT key, day FROM achievements")}
    rows = [dict(key=k, name=n, desc=d, day=got.get(k)) for k, n, d, t in ACHIEVEMENTS]
    return dict(achievements=rows, earned=len(got), total=len(ACHIEVEMENTS), gm=my_gm_score(conn))


# ---------------------------------------------------------------- hooks
def season_end(conn, season_id, day):
    """From finish_season, after the record book: the GM season scores, the Hall of Fame ballot, achievements."""
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    record_gm_season(conn, year)
    open_ballot(conn, day)
    check_achievements(conn, day)
