"""Ownership, season objectives, board confidence and GM job security.

Every club has an owner profile (1-10 scales: spend, ambition, patience, risk, youth preference, development
commitment, involvement). Each season the board sets objectives from the owner and the roster's projected rank:
  competitive  (required or preferred)  e.g. win a round / make the playoffs / stay out of the bottom three
  financial    (required for thrifty owners) payroll at or under a budget
  development  (required for youth-minded or rebuilding clubs) young skaters getting real NHL games
  long-term    (rebuilding clubs) make the playoffs within three seasons
Confidence (0-100) moves monthly a little with the points pace, and at season end by objective, scaled by the
owner's patience; every change is stored with its reasons in board_history. Job security labels:
  Meeting objectives is expected, so it earns less than missing them costs; past credit fades 25% a year.
  70+ secure, 50-69 stable, 35-49 under pressure, 20-34 hot seat, below 20 at season end: AI GMs are fired;
  the user gets one warning, then is fired (and can take a vacant job). A rebuilding club that finishes last can
  keep a stable board if it meets its development and financial goals; a contender that misses the playoffs cannot.
"""
from __future__ import annotations

import datetime
import json
import random

from ..schema import top_league_sql
from . import contracts as K
from .events import emit, team_abbr
from .roster import player_value
from .state import add_message, get_state, user_team

GM_FIRST = ["Mark", "Kevin", "Julien", "Brian", "Doug", "Kyle", "Pierre", "Steve", "Ron", "Tom", "Chris", "Eric",
            "Marc", "Bill", "Jim", "Patrik", "Mikael", "Jarmo", "Ken", "Don"]
GM_LAST = ["Holland", "Burke", "Armstrong", "Fletcher", "Gauthier", "Sweeney", "Treliving", "Botterill", "Francis",
           "Guerin", "Waddell", "Zito", "Bowman", "Nill", "Yzerman", "Hughes", "Tallon", "Rutherford", "Lombardi",
           "Sakic"]


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS owners (team_id INTEGER PRIMARY KEY, spend INTEGER, ambition INTEGER, "
                 "patience INTEGER, risk INTEGER, youth_pref INTEGER, development INTEGER, involvement INTEGER, "
                 "summary TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS board (team_id INTEGER PRIMARY KEY, confidence REAL, gm_name TEXT, "
                 "gm_since INTEGER, warnings INTEGER DEFAULT 0, vacancy INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS board_history (team_id INTEGER, review_date TEXT, kind TEXT, "
                 "confidence REAL, delta REAL, reasons TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS objectives (objective_id INTEGER PRIMARY KEY, team_id INTEGER, "
                 "season_start_year INTEGER, category TEXT, code TEXT, description TEXT, target REAL, "
                 "importance TEXT, deadline_season INTEGER, status TEXT DEFAULT 'active', result TEXT)")


def nhl_teams(conn):
    return [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")]


def _seed(conn):
    st = get_state(conn)
    return st[1] if st else 1


def season_year(conn):
    return conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]


def label(conf):
    return ("secure" if conf >= 70 else "stable" if conf >= 50 else "under pressure" if conf >= 35
            else "hot seat" if conf >= 20 else "in danger")


def owner_summary(o):
    parts = ["deep pockets" if o["spend"] >= 8 else "budget-conscious" if o["spend"] <= 4 else "average budget",
             "win-now" if o["ambition"] >= 8 else "long-view" if o["ambition"] <= 4 else "competitive",
             "patient" if o["patience"] >= 7 else "impatient" if o["patience"] <= 3 else "measured patience"]
    if o["youth_pref"] >= 7:
        parts.append("prefers youth")
    if o["involvement"] >= 8:
        parts.append("hands-on")
    return ", ".join(parts)


def setup(conn, day):
    """Owners and boards for every NHL club (once), then this season's objectives."""
    ensure_tables(conn)
    seed = _seed(conn)
    for t in nhl_teams(conn):
        if conn.execute("SELECT 1 FROM owners WHERE team_id=?", (t,)).fetchone():
            continue
        rng = random.Random(f"{seed}-owner-{t}")
        g = lambda m=5.5, s=2.0: max(1, min(10, round(rng.gauss(m, s))))
        o = dict(spend=g(), ambition=g(6, 2), patience=g(5, 2), risk=g(), youth_pref=g(), development=g(),
                 involvement=g(4.5, 2))
        conn.execute("INSERT INTO owners (team_id, spend, ambition, patience, risk, youth_pref, development, involvement, "
                     "summary) VALUES (?,?,?,?,?,?,?,?,?)",
                     (t, o["spend"], o["ambition"], o["patience"], o["risk"], o["youth_pref"], o["development"],
                      o["involvement"], owner_summary(o)))
        gm = None
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='pack_staff'").fetchone():   # v38: an imported database's GM
            r = conn.execute("SELECT name FROM pack_staff WHERE team_id=? AND role='GM' ORDER BY rowid LIMIT 1", (t,)).fetchone()
            gm = r[0] if r else None
        conn.execute("INSERT INTO board (team_id, confidence, gm_name, gm_since) VALUES (?,?,?,?)",
                     (t, 60.0, gm or f"{rng.choice(GM_FIRST)} {rng.choice(GM_LAST)}", season_year(conn)))
    me = user_team(conn)
    if me:
        conn.execute("UPDATE board SET gm_name='You', confidence=MAX(confidence, 60) WHERE team_id=? AND gm_name<>'You'",
                     (me,))
    from . import boardroom, tactics
    boardroom.ensure_tables(conn)                     # owner names, vocalness, analytics, identity, archetype
    tactics.ensure_table(conn)
    if not conn.execute("SELECT 1 FROM team_tactics").fetchone():
        tactics.ai_choose(conn)                       # AI clubs pick a system for their roster and coach
    set_objectives(conn, day)


def owner(conn, t):
    return conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone()


def strength(conn, t):
    vals = sorted((player_value(conn, r[0]) for r in conn.execute(
        "SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')", (t,))), reverse=True)
    return sum(vals[:19]) / max(1, len(vals[:19]))


def projected_ranks(conn):
    teams = nhl_teams(conn)
    order = sorted(teams, key=lambda t: -strength(conn, t))
    return {t: i + 1 for i, t in enumerate(order)}


def set_objectives(conn, day):
    year = season_year(conn)
    if conn.execute("SELECT 1 FROM objectives WHERE season_start_year=? AND category<>'long-term'", (year,)).fetchone():
        return
    ranks = projected_ranks(conn)
    n = len(ranks)
    cap = K.crules(conn)["cap_ceiling"]
    for t, rank in ranks.items():
        o = owner(conn, t)
        rows = []
        if rank <= max(2, n // 8) and o["ambition"] >= 6:
            rows.append(("competitive", "playoff_round", "Reach the conference final", 3, "required"))
        elif rank <= n // 3:
            rows.append(("competitive", "playoff_round", "Win a playoff round", 2,
                         "required" if o["ambition"] >= 7 else "preferred"))
        elif rank <= int(n * 0.55):
            rows.append(("competitive", "playoff_round", "Make the playoffs", 1, "required"))
        elif rank <= int(n * 0.75):
            rows.append(("competitive", "playoff_gap", "Stay in the playoff race (within 6 points of a spot)", 6,
                         "preferred"))
        else:
            rows.append(("competitive", "not_bottom", "Finish outside the bottom three", 3, "preferred"))
        if cap:
            budget = min(cap, cap * (0.80 + 0.025 * o["spend"]))
            rows.append(("financial", "payroll", f"Keep payroll at or under ${budget:,.0f}", budget,
                         "required" if o["spend"] <= 4 else "preferred"))
        try:                                                        # v34: the gate and the books
            from . import finance as FN
            f = FN.profile(conn, t)
            if f and o["spend"] <= 4:
                rows.append(("financial", "profit", "Make a profit this season", 0, "preferred"))
            if f and f["market"] <= 5:
                goal = 0.90 if f["market"] <= 3 else 0.93
                rows.append(("financial", "attendance", f"Fill {goal * 100:.0f}% of the building on average", goal, "preferred"))
        except Exception:
            pass
        rebuilding = rank > int(n * 0.65)
        young = 4 if rebuilding or o["youth_pref"] >= 8 else 2
        rows.append(("development", "young_games", f"Give at least {young} skaters aged 23 or under 40+ NHL games",
                     young, "required" if rebuilding or o["development"] >= 8 else "preferred"))
        for cat, code, desc, target, imp in rows:
            conn.execute("INSERT INTO objectives (team_id, season_start_year, category, code, description, target, "
                         "importance, deadline_season) VALUES (?,?,?,?,?,?,?,?)", (t, year, cat, code, desc, target, imp,
                                                                                  year))
        if rebuilding and not conn.execute("SELECT 1 FROM objectives WHERE team_id=? AND category='long-term' AND "
                                           "status='active'", (t,)).fetchone():
            conn.execute("INSERT INTO objectives (team_id, season_start_year, category, code, description, target, "
                         "importance, deadline_season) VALUES (?,?,'long-term','playoffs_by',"
                         "'Return to the playoffs within three seasons',1,'long-term',?)", (t, year, year + 2))
        emit(conn, "OBJECTIVES_SET", day, f"{team_abbr(conn, t)} board sets {len(rows)} objectives "
             f"(projected {rank} of {n})", team_id=t, projected_rank=rank)


# ---------------- measuring

def season_results(conn, season_id):
    """{team: dict(points, playoff_round reached (0 = missed), rank_from_bottom, gap_to_playoffs)}"""
    from ..league import standings
    from ..league.season import db_rules
    rules = db_rules(conn)
    rec, h2h = standings.table(conn, season_id)
    order = standings.rank(rec, h2h, rules)
    pts = {t: standings.points(rec[t], rules["points"]) for t in rec}
    reached = {}
    for r in conn.execute("SELECT home_team_id, away_team_id, series_id FROM games WHERE game_type='PO' AND "
                          "season_id=?", (season_id,)):
        sid = r["series_id"] or ""
        rnd = 4 if sid.startswith("Final") else int(sid[1]) if sid[:1] == "R" and sid[1:2].isdigit() else 1
        for t in (r["home_team_id"], r["away_team_id"]):
            reached[t] = max(reached.get(t, 0), rnd)
    champ = conn.execute("SELECT value FROM pack_info WHERE key='champion'").fetchone()
    if champ:
        reached[int(champ[0])] = 5
    qualified = [t for t in order if t in reached]
    cutoff = min((pts[t] for t in qualified), default=0)
    out = {}
    for i, t in enumerate(order):
        out[t] = dict(points=pts[t], round=reached.get(t, 0), from_bottom=len(order) - i,
                      gap=cutoff - pts[t] if t not in reached else 0)
    return out


def young_games(conn, t, season_id):
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    on = datetime.date(year, 9, 15)
    n = 0
    for r in conn.execute("SELECT s.player_id, p.birth_date, p.position, COUNT(*) gp FROM player_game_stats s "
                          "JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE s.team_id=? AND "
                          "g.season_id=? AND g.game_type='RS' GROUP BY s.player_id", (t, season_id)):
        b = datetime.date.fromisoformat(r["birth_date"])
        age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
        if r["position"] != "G" and age <= 23 and r["gp"] >= 40:
            n += 1
    return n


def _evaluate(conn, obj, res, t, season_id):
    """(met: bool, result text)"""
    code = obj["code"]
    if code == "playoff_round":
        need = int(obj["target"])
        got = res["round"]
        return got >= need + (0 if need == 1 else 0), ("missed the playoffs" if got == 0 else f"reached round {min(got, 4)}"
                                                       + (" and won the championship" if got == 5 else ""))
    if code == "playoff_gap":
        return res["round"] > 0 or res["gap"] <= obj["target"], (
            "made the playoffs" if res["round"] else f"finished {res['gap']} points out")
    if code == "not_bottom":
        return res["from_bottom"] > 3, f"finished {res['from_bottom']} from the bottom"
    if code == "payroll":
        pay = K.payroll(conn, t)
        return pay <= obj["target"], f"payroll ${pay:,.0f}"
    if code == "young_games":
        n = young_games(conn, t, season_id)
        return n >= obj["target"], f"{n} young skaters played 40+ games"
    if code in ("profit", "attendance"):
        year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
        r = conn.execute("SELECT profit, fill FROM finance_season WHERE team_id=? AND season=?", (t, year)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='finance_season'").fetchone() else None
        if r is None:
            return True, "no books kept"
        if code == "profit":
            return r[0] >= obj["target"], f"{'profit' if r[0] >= 0 else 'loss'} ${abs(r[0]) / 1e6:.1f}M"
        return r[1] >= obj["target"], f"{r[1] * 100:.1f}% full on average"
    if code == "playoffs_by":
        return res["round"] > 0, "made the playoffs" if res["round"] else "missed the playoffs"
    return True, ""


WEIGHTS = {"required": (5, 14), "preferred": (2, 5), "long-term": (8, 12)}     # (gain if met, loss if missed)


def _apply(conn, t, delta, kind, day, reasons):
    conf = conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]
    new = max(0.0, min(100.0, conf + delta))
    conn.execute("UPDATE board SET confidence=? WHERE team_id=?", (new, t))
    conn.execute("INSERT INTO board_history VALUES (?,?,?,?,?,?)", (t, day, kind, new, new - conf, json.dumps(reasons)))
    return conf, new


def monthly(conn, day):
    """Small in-season drift: points pace against the competitive objective."""
    year = season_year(conn)
    season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    from ..league import standings
    from ..league.season import db_rules
    rules = db_rules(conn)
    rec, h2h = standings.table(conn, season_id)
    if not rec:
        return
    order = standings.rank(rec, h2h, rules)
    n = len(order)
    playoff_spots = 16 if n >= 24 else max(2, n // 2)
    for t in nhl_teams(conn):
        if t not in rec or rec[t]["gp"] < 10:
            continue
        obj = conn.execute("SELECT * FROM objectives WHERE team_id=? AND season_start_year=? AND category='competitive'",
                           (t, year)).fetchone()
        if obj is None:
            continue
        place = order.index(t) + 1
        want = {"playoff_round": playoff_spots - 4 * (int(obj["target"]) - 1) if obj["code"] == "playoff_round" else None,
                "playoff_gap": playoff_spots + 4, "not_bottom": n - 3}.get(obj["code"]) or playoff_spots
        o = owner(conn, t)
        impatience = 1.2 - o["patience"] / 10
        delta = (1.0 if place <= want else -1.5 * impatience * min(3, (place - want) / 3 + 0.5))
        _apply(conn, t, delta, "monthly", day, [f"{place} in the league against a target of about {want}"])


def season_review(conn, day, season_id):
    """Season-end review: objectives met/failed move confidence; firings; long-term goals checked."""
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    results = season_results(conn, season_id)
    me = user_team(conn)
    lines = []
    for t in nhl_teams(conn):
        res = results.get(t, dict(points=0, round=0, from_bottom=0, gap=99))
        o = owner(conn, t)
        impatience = 1.2 - o["patience"] / 10
        conf_now = conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]
        drift = round((55 - conf_now) * 0.25, 1)                  # last year's credit (or blame) fades a little
        delta, reasons = drift, [f"memory fades {drift:+.1f}"] if abs(drift) >= 0.5 else []
        objs = conn.execute("SELECT * FROM objectives WHERE team_id=? AND status='active' AND deadline_season<=?",
                            (t, year)).fetchall()
        for obj in objs:
            met, text = _evaluate(conn, obj, res, t, season_id)
            up, down = WEIGHTS.get(obj["importance"], (4, 5))
            d = up if met else -down * impatience * (1.2 if obj["category"] == "competitive" else 1.0)
            delta += d
            reasons.append(f"{obj['description']}: {'met' if met else 'missed'} ({text}) {d:+.0f}")
            conn.execute("UPDATE objectives SET status=?, result=? WHERE objective_id=?",
                         ("met" if met else "failed", text, obj["objective_id"]))
            emit(conn, "OBJECTIVE_MET" if met else "OBJECTIVE_FAILED", day, f"{team_abbr(conn, t)}: "
                 f"{obj['description']} - {text}", team_id=t, importance=2 if obj["importance"] == "required" else 1)
        if res["round"] == 5:
            delta += 15
            reasons.append("won the championship +15")
        fin = conn.execute("SELECT profit, fill FROM finance_season WHERE team_id=? AND season=?", (t, year)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='finance_season'").fetchone() else None
        if fin and o["spend"] <= 5:                                 # v34: budget-minded owners read the books
            if fin[0] < -15_000_000:
                delta -= 4
                reasons.append(f"the club lost ${-fin[0] / 1e6:.0f}M -4")
            elif fin[0] > 15_000_000:
                delta += 2
                reasons.append(f"the club made ${fin[0] / 1e6:.0f}M +2")
        cohesion = conn.execute("SELECT cohesion FROM team_room WHERE team_id=?", (t,)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_room'").fetchone() else None
        if cohesion and cohesion[0] is not None and cohesion[0] < 35:
            delta -= 3
            reasons.append("dressing room in poor shape -3")
        before, after = _apply(conn, t, delta, "season", day, reasons)
        emit(conn, "BOARD_REVIEW", day, f"{team_abbr(conn, t)} board review: confidence {before:.0f} -> {after:.0f}",
             team_id=t, importance=2 if t == me else 1, before=before, after=after)
        if t == me:
            lines += [f"Board review: confidence {before:.0f} -> {after:.0f} ({label(after)})"] + ["  " + r for r in reasons]
            oname = o["name"] if o and "name" in o.keys() else "The owner"
            verdict = ("I'm pleased. Keep going." if after - before >= 5 else "We expected more. I want to see a plan." if after < before - 5
                       else "A mixed year. Next season has to move us forward.")
            add_message(conn, day, "Board review",
                        f"From {oname}, after the season's review.\nConfidence in you went from {before:.0f} to {after:.0f} ({label(after)}).\n"
                        "What the board weighed:\n" + "\n".join(f"- {r[0].upper() + r[1:]}" for r in reasons) + f"\n\"{verdict}\""
                        + ("\nYour position is at risk: the board will watch the first weeks of next season closely." if after < 35 else ""))
        lines += _job_security(conn, t, after, day, me, o)
    return lines


def _job_security(conn, t, conf, day, me, o):
    threshold = 15 + (10 - o["patience"])          # impatient owners fire sooner
    if conf >= threshold:
        if t == me:
            conn.execute("UPDATE board SET warnings=0 WHERE team_id=?", (t,))
        return []
    b = conn.execute("SELECT * FROM board WHERE team_id=?", (t,)).fetchone()
    if t == me and b["warnings"] == 0:
        conn.execute("UPDATE board SET warnings=1 WHERE team_id=?", (t,))
        add_message(conn, day, "Final warning", "Ownership has lost patience. Another season like this will cost you "
                                                "your job.")
        return ["The owner has issued a final warning."]
    rng = random.Random(f"{_seed(conn)}-{season_year(conn)}-gm-{t}")
    from . import gm as GMx
    if t == me and not GMx.can_be_fired(conn):           # a career option: the owner fumes, you stay
        conn.execute("UPDATE board SET warnings=0, confidence=MAX(confidence, 25) WHERE team_id=?", (t,))
        add_message(conn, day, "Still in the chair", "The owner wanted a change at general manager. In this career you "
                                                       "cannot be fired, so you stay on; his confidence is reset to 25.")
        return ["The owner would have fired you (you cannot be fired in this career)."]
    if t == me:
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('gm_status', 'fired')")
        add_message(conn, day, "Dismissed", "You have been relieved of your duties. The Job Centre lists the clubs looking "
                                            "for a GM; Continue plays on while you look.")
        try:
            from . import gm as GMx
            GMx.ensure_tables(conn)
            conn.execute("UPDATE gm_career SET end_date=?, how_ended='fired' WHERE end_date IS NULL", (day,))
        except Exception:
            pass
    emit(conn, "GM_FIRED", day, f"{team_abbr(conn, t)} fire general manager {b['gm_name']}", team_id=t, importance=3)
    new = f"{rng.choice(GM_FIRST)} {rng.choice(GM_LAST)}"
    conn.execute("UPDATE board SET gm_name=?, gm_since=?, confidence=62, warnings=0, vacancy=? WHERE team_id=?",
                 (new, season_year(conn) + 1, 1, t))
    emit(conn, "GM_HIRED", day, f"{team_abbr(conn, t)} hire {new} as general manager", team_id=t, importance=2)
    if t == me:
        GMx.lose_job(conn, day, "fired")
    return [f"{team_abbr(conn, t)} fired their GM."] if t != me else ["You have been fired."]


def vacancies(conn):
    return [r[0] for r in conn.execute("SELECT team_id FROM board WHERE vacancy=1 ORDER BY team_id")]


def take_job(conn, t, day):
    if t not in vacancies(conn):
        raise ValueError("That club has no vacancy (clubs that changed GM this offseason are listed by `jobs`).")
    conn.execute("UPDATE manager SET team_id=? WHERE id=1", (t,))
    conn.execute("UPDATE board SET gm_name='You', confidence=60, warnings=0, vacancy=0 WHERE team_id=?", (t,))
    conn.execute("DELETE FROM pack_info WHERE key='gm_status'")
    emit(conn, "GM_HIRED", day, f"{team_abbr(conn, t)} hire you as general manager", team_id=t, importance=3)
    from . import gm as GMx
    GMx.ensure_tables(conn)
    conn.execute("INSERT INTO gm_career VALUES (?,?,NULL,NULL)", (t, day))


def clear_vacancies(conn):
    """A new season: openings are filled by the interim GMs, unless you are out of work (then they stay open to you)."""
    from . import gm as GMx
    if GMx.unemployed(conn):
        return
    conn.execute("UPDATE board SET vacancy=0")


def board_status(conn, t):
    b = conn.execute("SELECT * FROM board WHERE team_id=?", (t,)).fetchone()
    return b, owner(conn, t)
