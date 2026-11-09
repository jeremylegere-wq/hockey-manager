"""Owner goals (v56; docs/BOARD.md "Owner goals"): a catalogue of specific things the owner wants this season, each
with a priority and a deadline, on top of the board's season objectives (competitive, financial, development) and the
mid-season directives.

At the start of each season (and the first day of a save from before v56) the owner of your club picks up to three
goals from the catalogue: those that fit the club's situation and leave a month at least to do them, weighted by his
traits. Each has a priority (low,
medium, high) and a deadline. A goal is met the moment its condition holds (some are judged only at the deadline),
and it fails at the deadline otherwise (or at once, for "keep" goals). Board confidence: met +2 / +4 / +6, failed
-2 / -4 / -7, by priority.

The catalogue
  acquire_star     no skater among the league's top 30 (ambition 6+)     acquire one by the trade deadline
  acquire_goalie   no goalie among the league's top 16                   acquire one by the trade deadline
  shed_contract    a veteran (29+, outside the top six) on $3M+ whose value lags his pay most (spending 5 or less)
                   move him by the deadline
  hire_coach       the head coach rated 10 or less in coaching (involvement 5+)   hire one rated 14+ within 75 days
  hire_dev         the development coach rated 9 or less (development 6+)        hire one rated 14+ within 75 days
  prospect_games   the organisation's best prospect, 21 or under, with under 20 NHL games (youth 5+)
                   give him 20 NHL games this season
  keep_first       keep next summer's first-round pick (patience or youth 6+) until the draft
  add_first        a rebuilding club (projected in the bottom third, ambition 5 or less)   add a first-round pick
  beat_rival       the club's fiercest rival                            take the regular-season series
  home_wins        a big market (7+)                                     win 24 home games
  younger          an old roster (average 28.5+, youth 7+)               bring the NHL roster's average age under 28
  canadian_core    a Canadian club (involvement 6+)                       dress 12 or more Canadians (at the deadline)
"""
from __future__ import annotations

import datetime
import json
import random

from . import contracts as K
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

REWARD = {"low": 2, "medium": 4, "high": 6}
PENALTY = {"low": 2, "medium": 4, "high": 7}
MAX_GOALS = 3
CANADIAN = {"TOR", "MTL", "OTT", "WPG", "CGY", "EDM", "VAN"}


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS owner_goals (goal_id INTEGER PRIMARY KEY, team_id INTEGER, season INTEGER, code TEXT, "
                 "description TEXT, priority TEXT, target TEXT, issued TEXT, deadline TEXT, status TEXT DEFAULT 'open', "
                 "result TEXT, resolved TEXT, delta REAL)")


def _owner(conn, t):
    r = conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone() else None
    d = dict(r) if r else {}
    for k, v in dict(spend=5, ambition=5, patience=5, youth_pref=5, development=5, involvement=5, name="The owner").items():
        if d.get(k) is None:
            d[k] = v
    return d


def _dates(conn):
    """(trade deadline, last regular-season day) of this season."""
    from .trades import deadline
    sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    end = conn.execute("SELECT MAX(game_date) FROM games WHERE season_id=? AND game_type='RS'", (sid,)).fetchone()[0]
    return deadline(conn).isoformat(), end, sid


def _ranks(conn, goalies=False):
    """{player_id: league rank by value} for active NHL skaters (or goalies)."""
    from ..schema import top_league_sql
    mv = K.day_values(conn)
    rows = conn.execute(f"SELECT player_id FROM players WHERE status IN ('active','injured') AND position{'=' if goalies else '<>'}'G' AND "
                        f"team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()})").fetchall()
    vals = sorted(((mv.value(r[0]), r[0]) for r in rows), reverse=True)
    return {pid: i + 1 for i, (_, pid) in enumerate(vals)}


def _age(conn, birth, day):
    return K.age_on(birth, datetime.date.fromisoformat(day))


def _roster_ids(conn, t, goalies=None):
    q = "SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')"
    if goalies is True:
        q += " AND position='G'"
    elif goalies is False:
        q += " AND position<>'G'"
    return [r[0] for r in conn.execute(q, (t,))]


def _staff(conn, t, role):
    r = conn.execute("SELECT coaching, development FROM staff WHERE team_id=? AND role=? ORDER BY coaching DESC LIMIT 1", (t, role)).fetchone()
    return (r[0] or 0, r[1] or 0) if r else (0, 0)


def _top_rival(conn, t):
    try:
        from . import rivalry as RV
        best = None
        for (x,) in conn.execute("SELECT team_id FROM teams WHERE team_id<>?", (t,)).fetchall():
            p = RV.points(conn, t, x)
            if p and (best is None or p > best[0]):
                best = (p, x)
        return best[1] if best and best[0] >= 30 else None
    except Exception:
        return None


def candidates(conn, t, day):
    """[(code, description, target dict, deadline, weight, priority)] that fit the club now."""
    o = _owner(conn, t)
    dl, end, sid = _dates(conn)
    year = K.season_year(conn)
    out = []
    pr = lambda trait: "high" if trait >= 8 else "medium" if trait >= 6 else "low"
    sk = _ranks(conn)
    mine = _roster_ids(conn, t, goalies=False)
    if o["ambition"] >= 6 and not any(sk.get(p, 999) <= 30 for p in mine):
        out.append(("acquire_star", "Acquire a star: one of the league's top 30 skaters", dict(rank=30, since=day), dl,
                    o["ambition"], pr(o["ambition"])))
    gr = _ranks(conn, goalies=True)
    if min((gr.get(p, 999) for p in _roster_ids(conn, t, goalies=True)), default=999) > 16:
        out.append(("acquire_goalie", "Acquire a starting goaltender: one of the league's top 16", dict(rank=16, since=day), dl,
                    5 + o["ambition"] / 2, pr(o["ambition"])))
    if o["spend"] <= 5:
        mv = K.day_values(conn)
        top6 = set(sorted(mine, key=lambda p: -mv.value(p))[:6])          # never the club's best players
        worst = None
        for p in mine:
            if p in top6:
                continue
            b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (p,)).fetchone()[0]
            c = K.current_contract(conn, p, year)
            if c and c["cap_hit"] >= 3_000_000 and _age(conn, b, day) >= 29 and c["start_year"] + c["years"] - 1 > year:
                ratio = mv.value(p) / (c["cap_hit"] / 1e6)
                if worst is None or ratio < worst[0]:
                    worst = (ratio, p, c["cap_hit"])
        if worst:
            out.append(("shed_contract", f"Move {player_name(conn, worst[1])}'s contract (${worst[2] / 1e6:.2f}M)", dict(player_id=worst[1]),
                        dl, 11 - o["spend"], pr(11 - o["spend"])))
    in75 = (datetime.date.fromisoformat(day) + datetime.timedelta(days=75)).isoformat()
    hc = _staff(conn, t, "HC")[0]
    if o["involvement"] >= 5 and hc and hc <= 10:
        out.append(("hire_coach", "Hire a head coach rated 14 or better in coaching", dict(role="HC", attr="coaching", min=14), in75,
                    o["involvement"], pr(o["involvement"])))
    dv = _staff(conn, t, "DEV")[1]
    if o["development"] >= 6 and dv <= 9:
        out.append(("hire_dev", "Hire a development coach rated 14 or better in development", dict(role="DEV", attr="development", min=14),
                    in75, o["development"], pr(o["development"])))
    if o["youth_pref"] >= 5:
        best = None
        mv = K.day_values(conn)
        for pid, b in conn.execute("SELECT player_id, birth_date FROM players WHERE team_id=? AND status IN ('active','prospect') AND "
                                   "position<>'G'", (t,)).fetchall():
            if _age(conn, b, day) > 21:
                continue
            gp = conn.execute("SELECT COALESCE(SUM(gp), 0) FROM skater_season_stats WHERE player_id=? AND split='RS' AND "
                              "league_id IN (SELECT league_id FROM teams WHERE team_id=?)", (pid, t)).fetchone()[0]
            if gp >= 20:
                continue
            v = mv.value(pid)
            if best is None or v > best[0]:
                best = (v, pid)
        if best:
            out.append(("prospect_games", f"Give {player_name(conn, best[1])} 20 NHL games this season", dict(player_id=best[1], games=20, since=day),
                        end, o["youth_pref"], pr(o["youth_pref"])))
    from .trades import pick_owner
    nxt = year + 1
    if max(o["patience"], o["youth_pref"]) >= 6 and pick_owner(conn, nxt, 1, t) == t:
        out.append(("keep_first", f"Keep our {nxt} first-round pick", dict(year=nxt), end, max(o["patience"], o["youth_pref"]) - 1,
                    pr(max(o["patience"], o["youth_pref"]) - 1)))
    from . import org
    ranks = org.projected_ranks(conn)
    if ranks.get(t, 0) > len(ranks) * 2 // 3 and o["ambition"] <= 5:
        n = sum(1 for (orig,) in conn.execute("SELECT team_id FROM teams") if pick_owner(conn, nxt, 1, orig) == t)
        out.append(("add_first", f"Add a first-round pick for the {nxt} draft", dict(year=nxt, have=n), dl, 7, "medium"))
    rv = _top_rival(conn, t)
    if rv:
        out.append(("beat_rival", f"Take the season series against {team_abbr(conn, rv)}", dict(rival=rv, season_id=sid), end, 6, "medium"))
    try:
        from . import finance as FN
        if FN.profile(conn, t)["market"] >= 7:
            out.append(("home_wins", "Win 24 home games", dict(wins=24, season_id=sid), end, 3, "low"))
    except Exception:
        pass
    ages = [_age(conn, b, day) for (b,) in conn.execute("SELECT birth_date FROM players WHERE team_id=? AND status IN ('active','injured')", (t,))]
    if ages and o["youth_pref"] >= 7 and sum(ages) / len(ages) >= 28.5:
        out.append(("younger", "Bring the NHL roster's average age under 28", dict(age=28.0), end, o["youth_pref"], pr(o["youth_pref"])))
    if team_abbr(conn, t) in CANADIAN and o["involvement"] >= 6:
        out.append(("canadian_core", "Keep 12 or more Canadians on the NHL roster", dict(n=12), end, 4, "low"))
    return out


def issue(conn, t, day, seed=None):
    """The owner picks up to MAX_GOALS goals for the season (once a season)."""
    ensure_table(conn)
    year = K.season_year(conn)
    if conn.execute("SELECT 1 FROM owner_goals WHERE team_id=? AND season=?", (t, year)).fetchone():
        return []
    soon = (datetime.date.fromisoformat(day) + datetime.timedelta(days=30)).isoformat()
    cand = [c for c in candidates(conn, t, day) if c[3] and c[3] >= soon]      # a month at least to do it
    rng = random.Random(f"{seed if seed is not None else get_state(conn)[1]}-goals-{t}-{year}")
    picked = []
    while cand and len(picked) < MAX_GOALS:
        x = rng.choices(cand, weights=[max(0.5, c[4]) for c in cand])[0]
        cand.remove(x)
        picked.append(x)
    o = _owner(conn, t)
    for code, desc, target, dl, _, prio in picked:
        conn.execute("INSERT INTO owner_goals (team_id, season, code, description, priority, target, issued, deadline) VALUES (?,?,?,?,?,?,?,?)",
                     (t, year, code, desc, prio, json.dumps(target), day, dl))
    if picked and t == user_team(conn):
        add_message(conn, day, "The owner's goals for the season",
                    f"{o['name']} has set out what he wants from you this season, beyond the board's objectives:\n"
                    + "\n".join(f"- {d} ({p} priority, by {dl})" for _, d, _, dl, _, p in picked)
                    + f"\nMet: board confidence +{REWARD['low']} / +{REWARD['medium']} / +{REWARD['high']} by priority; missed: "
                      f"-{PENALTY['low']} / -{PENALTY['medium']} / -{PENALTY['high']}.",
                    sender=f"{o['name']}, Owner", actions=[{"label": "The board", "href": "#board"}])
    return picked


def progress(conn, g, day):
    """(status 'met' | 'failed' | None, progress text)."""
    t = g["team_id"]
    tg = json.loads(g["target"] or "{}")
    code = g["code"]
    due = day >= g["deadline"]
    if code in ("acquire_star", "acquire_goalie"):
        ranks = _ranks(conn, goalies=code == "acquire_goalie")
        got = [pid for (pid,) in conn.execute("SELECT DISTINCT player_id FROM transactions WHERE to_team_id=? AND txn_date>=? AND "
                                              "txn_type IN ('trade','sign','waiver_claim','contract')", (t, tg["since"]))
               if conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0] == t and ranks.get(pid, 999) <= tg["rank"]]
        if got:
            return "met", f"{player_name(conn, got[0])} (#{ranks[got[0]]})"
        return ("failed" if due else None), "nobody yet"
    if code == "shed_contract":
        on = conn.execute("SELECT team_id FROM players WHERE player_id=?", (tg["player_id"],)).fetchone()
        if not on or on[0] != t:
            return "met", "moved"
        return ("failed" if due else None), "still here"
    if code in ("hire_coach", "hire_dev"):
        v = _staff(conn, t, tg["role"])[0 if tg["attr"] == "coaching" else 1]
        if v >= tg["min"]:
            return "met", f"rated {v}"
        return ("failed" if due else None), f"rated {v}"
    if code == "prospect_games":
        n = conn.execute("SELECT COUNT(*) FROM player_game_stats s JOIN games g USING (game_id) WHERE s.player_id=? AND g.game_date>=? AND "
                         "g.game_type='RS'", (tg["player_id"], tg["since"])).fetchone()[0]
        if n >= tg["games"]:
            return "met", f"{n} games"
        return ("failed" if due else None), f"{n} of {tg['games']} games"
    if code == "keep_first":
        from .trades import pick_owner
        if pick_owner(conn, tg["year"], 1, t) != t:
            return "failed", "traded"
        return ("met" if due else None), "still ours"
    if code == "add_first":
        from .trades import pick_owner
        n = sum(1 for (orig,) in conn.execute("SELECT team_id FROM teams") if pick_owner(conn, tg["year"], 1, orig) == t)
        if n > tg["have"]:
            return "met", f"{n} first-round picks"
        return ("failed" if due else None), f"{n} first-round pick{'s' if n != 1 else ''}"
    if code == "beat_rival":
        r = tg["rival"]
        us = them = 0
        left = 0
        for h, a, hg, ag, ot, played in conn.execute("SELECT home_team_id, away_team_id, home_goals, away_goals, went_to_ot, played FROM games "
                                                     "WHERE season_id=? AND game_type='RS' AND ((home_team_id=? AND away_team_id=?) OR "
                                                     "(home_team_id=? AND away_team_id=?))", (tg["season_id"], t, r, r, t)):
            if not played:
                left += 1
                continue
            mine, theirs = (hg, ag) if h == t else (ag, hg)
            us += 2 if mine > theirs else 1 if ot else 0
            them += 2 if theirs > mine else 1 if ot else 0
        txt = f"{us}-{them} in points" + (f", {left} to play" if left else "")
        if not left and (us or them):
            return ("met" if us > them else "failed"), txt
        if left and us > them + 2 * left:
            return "met", txt
        if left and them > us + 2 * left:
            return "failed", txt
        return ("failed" if due and us <= them else "met" if due else None), txt
    if code == "home_wins":
        n = conn.execute("SELECT COUNT(*) FROM games WHERE season_id=? AND game_type='RS' AND played=1 AND home_team_id=? AND home_goals>away_goals",
                         (tg["season_id"], t)).fetchone()[0]
        if n >= tg["wins"]:
            return "met", f"{n} home wins"
        return ("failed" if due else None), f"{n} of {tg['wins']} home wins"
    if code == "younger":
        ages = [_age(conn, b, day) for (b,) in conn.execute("SELECT birth_date FROM players WHERE team_id=? AND status IN ('active','injured')", (t,))]
        a = sum(ages) / len(ages) if ages else 0
        if due:
            return ("met" if a < tg["age"] else "failed"), f"average {a:.1f}"
        return None, f"average {a:.1f}"
    if code == "canadian_core":
        n = conn.execute("SELECT COUNT(*) FROM players WHERE team_id=? AND status IN ('active','injured') AND nationality='CAN'", (t,)).fetchone()[0]
        if due:
            return ("met" if n >= tg["n"] else "failed"), f"{n} Canadians"
        return None, f"{n} Canadians"
    return ("failed" if due else None), ""


def daily(conn, day):
    """Resolve your club's open goals; issue this season's if there are none yet (in the regular season)."""
    t = user_team(conn)
    if t is None:
        return []
    ensure_table(conn)
    if K.season_state(conn) == "regular_season" and not conn.execute(
            "SELECT 1 FROM owner_goals WHERE team_id=? AND season=?", (t, K.season_year(conn))).fetchone():
        issue(conn, t, day)
    out = []
    o = _owner(conn, t)
    monday = datetime.date.fromisoformat(day).weekday() == 0
    for g in conn.execute("SELECT * FROM owner_goals WHERE team_id=? AND status='open'", (t,)).fetchall():
        if g["code"] in ("acquire_star", "acquire_goalie") and not monday and day < g["deadline"]:
            continue                                     # the league's values are costly: checked on Mondays and at the deadline
        st, txt = progress(conn, g, day)
        if st is None:
            continue
        delta = REWARD[g["priority"]] if st == "met" else -PENALTY[g["priority"]]
        conn.execute("UPDATE owner_goals SET status=?, result=?, resolved=?, delta=? WHERE goal_id=?", (st, txt, day, delta, g["goal_id"]))
        if conn.execute("SELECT 1 FROM board WHERE team_id=?", (t,)).fetchone():
            from . import org
            org._apply(conn, t, delta, "owner_goal", day, [f"{g['description']}: {'met' if st == 'met' else 'missed'} ({txt}) {delta:+d}"])
        emit(conn, "OBJECTIVE_MET" if st == "met" else "OBJECTIVE_FAILED", day, f"{team_abbr(conn, t)}: {g['description']} - {txt}",
             team_id=t, importance=2 if g["priority"] == "high" else 1)
        add_message(conn, day, f"Owner's goal {'met' if st == 'met' else 'missed'}: {g['description']}",
                    f"{o['name']}: \"" + (f"Well done. {g['description']}: {txt}." if st == "met" else
                                          f"{g['description']}. That did not happen ({txt}). I noticed.") + f"\"\nBoard confidence {delta:+d}.",
                    sender=f"{o['name']}, Owner")
        out.append((g["code"], st))
    return out


def view(conn, t=None):
    t = t or user_team(conn)
    ensure_table(conn)
    day = get_state(conn)[0]
    rows = []
    for g in conn.execute("SELECT * FROM owner_goals WHERE team_id=? ORDER BY season DESC, goal_id", (t,)).fetchall():
        d = dict(g)
        if g["status"] == "open":
            d["progress"] = progress(conn, g, day)[1]
        rows.append(d)
    return dict(goals=rows, reward=REWARD, penalty=PENALTY, catalogue=[c for c in _CATALOGUE])


_CATALOGUE = [
    ("acquire_star", "Acquire one of the league's top 30 skaters", "the club has none, the owner's ambition is 6+", "trade deadline"),
    ("acquire_goalie", "Acquire one of the league's top 16 goalies", "the club has none", "trade deadline"),
    ("shed_contract", "Move a veteran's contract", "29+, $3M+, value lagging pay; the owner spends 5 or less", "trade deadline"),
    ("hire_coach", "Hire a head coach rated 14+ in coaching", "the coach is rated 10 or less; involvement 5+", "75 days"),
    ("hire_dev", "Hire a development coach rated 14+", "the development coach is rated 9 or less; development 6+", "75 days"),
    ("prospect_games", "Give the best prospect 20 NHL games", "21 or under, under 20 NHL games; youth 5+", "end of the season"),
    ("keep_first", "Keep next summer's first-round pick", "patience or youth 6+", "end of the season"),
    ("add_first", "Add a first-round pick", "projected in the bottom third, ambition 5 or less", "trade deadline"),
    ("beat_rival", "Take the season series against the fiercest rival", "a rivalry of 30+ points", "end of the season"),
    ("home_wins", "Win 24 home games", "a market of 7+", "end of the season"),
    ("younger", "Bring the roster's average age under 28", "average 28.5+, youth 7+", "end of the season"),
    ("canadian_core", "Keep 12 or more Canadians on the roster", "a Canadian club, involvement 6+", "end of the season"),
]
