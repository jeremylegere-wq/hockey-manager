"""Advancing time one day at a time. `game_state.current_date` is the last simulated day."""
from __future__ import annotations

from ..schema import top_league_sql

import datetime
import random
from dataclasses import dataclass, field

from ..league import standings
from ..league.playoffs import qualify_conference_top_n, qualify_division_wildcard, run_playoffs
from ..league.season import db_rules, team_rows
from ..sim.loader import load_teams, write_result
from ..sim.engine import simulate_game
from .injuries import heal_injuries, roll_injuries
from .roster import NEED, ai_manage, counts, ensure_dressable
from .state import add_message, get_state, season_state, user_team


@dataclass
class DaySummary:
    day: str
    results: list = field(default_factory=list)      # (game_id, home_id, away_id, hg, ag, went_to_ot)
    injuries: list = field(default_factory=list)     # (player_id, team_id, days)
    returns: list = field(default_factory=list)
    moves: int = 0
    trades: list = field(default_factory=list)       # AI-to-AI trades made today (descriptions)
    waivers: list = field(default_factory=list)      # waiver claims today
    board: list = field(default_factory=list)        # boardroom events today
    user_alerts: list = field(default_factory=list)  # reasons the user is needed
    press: list = field(default_factory=list)        # press conferences scheduled today (hs/game/press.py)
    season_finished: bool = False
    dev: tuple = None                                # v40: the monthly development step (players moved, report lines)
    league_news: list = field(default_factory=list)  # v44: champions crowned around the leagues today


def _next_day(conn):
    cur, seed = get_state(conn)
    return (datetime.date.fromisoformat(cur) + datetime.timedelta(days=1)).isoformat(), seed


def sim_day(conn, env, skill, user_team_id=None):
    """Play every unplayed regular-season game dated tomorrow; roll injuries; AI roster moves; commit."""
    user_team_id = user_team_id if user_team_id is not None else user_team(conn)
    day, seed = _next_day(conn)
    s = DaySummary(day)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='waivers'").fetchone():
        from . import waivers as W
        s.waivers = W.process(conn, day)
    from . import development as DV                    # v40: a long injury can cost an older player some speed
    DV.long_injury_cost(conn, day)
    s.returns = heal_injuries(conn, day)
    if DV.is_tick(conn, day):                            # v40: young players grow through the season, monthly
        s.dev = DV.monthly(conn, day)
    from . import finance as FN                       # v34: the months' revenue and costs
    FN.catch_up(conn, day)
    from . import owner_goals as OG                    # v56: the owner's goals: issued in the regular season, resolved
    OG.daily(conn, day)
    from . import ltir as LT
    LT.daily(conn, day)
    from . import pto as PTO                             # v39: tryouts end after opening week
    PTO.daily(conn, day)
    before = counts(conn, user_team_id)
    games = conn.execute("SELECT game_id, home_team_id, away_team_id FROM games WHERE game_date=? AND played=0 "
                         "AND game_type='RS' ORDER BY game_id", (day,)).fetchall()
    if games:
        # every team playing today must be able to dress a lineup, including the user's
        for tid in sorted({t for g in games for t in (g["home_team_id"], g["away_team_id"])}):
            ensure_dressable(conn, tid, day)
        from . import lineups as LUP                     # v52: your priority lists rebuild your lines for today
        LUP.before_games(conn, day)
        from . import troles as TR                       # v55: the AI clubs' tactical roles
        TR.ensure_ai(conn, day)
        teams = load_teams(conn)           # once per day
        overtime = (db_rules(conn) or {}).get("overtime")
        from . import rivalry as RV                      # v37: rivalry games are big games
        rivals = RV.all_points(conn)
        played = []
        for g in games:
            gid, h, a = g["game_id"], g["home_team_id"], g["away_team_id"]
            if h not in teams or a not in teams:
                raise RuntimeError(f"Team {h if h not in teams else a} cannot dress a lineup and no free agents "
                                   f"are available.")
            gseed = seed * 1_000_003 + gid
            res = simulate_game(teams[h], teams[a], env, skill, gseed, events=True, overtime=overtime, big=RV.is_big(rivals, h, a))
            write_result(conn, gid, h, a, res, gseed, teams)
            RV.after_game(conn, gid, h, a, res.goals[0], res.goals[1], res.went_to_ot or res.shootout, user_team_id, rivals)
            from . import chemistry as CH                # v33: lines that play together get better together
            CH.record(conn, teams[h], day)
            CH.record(conn, teams[a], day)
            FN.home_game(conn, gid, day)                 # the gate, concessions, the arena and travel
            s.results.append((gid, h, a, res.goals[0], res.goals[1], 2 if res.shootout else int(res.went_to_ot)))
            played += [(pid, st["toi"]) for pid, st in res.stats.items()]
        s.injuries = roll_injuries(conn, day, played, random.Random(f"{seed}-{day}-injury"))
        from . import discipline as DSC                  # v53: suspensions from today's games, and games served
        DSC.after_games(conn, day, [(g["game_id"], g["home_team_id"], g["away_team_id"]) for g in games], seed)
        from . import welfare                            # v35: players playing through an injury may make it worse
        welfare.after_games(conn, day, [pid for pid, _ in played])
    from . import leagues as LGS                         # v44: the leagues around the NHL play their games today
    try:
        s.league_news = LGS.day(conn, day, seed)
    except Exception as e:                               # a lower league never stops the NHL season
        import sys
        print(f"league day skipped: {e!r}", file=sys.stderr)
        import traceback; traceback.print_exc() if __import__("os").environ.get("HS_TRACE") else None
    from . import expansion as XP                        # v45: the league may announce an expansion club
    XP.maybe_announce(conn, day, seed)
    from . import challenge as CHL                       # v47: cap hell is judged on the first day simulated
    CHL.opening_night(conn, day)
    from . import numbers as NUM                         # v49: newcomers get a number; clashes after moves are settled
    NUM.fix(conn, day)
    from . import international as INTL                  # v51: the World Juniors, the Olympics, the World Cup
    try:
        for line in INTL.daily(conn, day):
            s.league_news = list(s.league_news or []) + [line]
    except Exception as e:                               # international hockey never stops the NHL season
        import sys
        print(f"international day skipped: {e!r}", file=sys.stderr)
        import traceback; traceback.print_exc() if __import__("os").environ.get("HS_TRACE") else None
    from . import college as CO                          # v46: recruiting, the Hobey Baker, college free agents
    try:
        for line in CO.daily(conn, day, seed):
            if "signs with" in line or "Hobey" in line:
                s.league_news = list(s.league_news or []) + [line]
    except Exception as e:                               # college hockey never stops the NHL season
        import sys
        print(f"college day skipped: {e!r}", file=sys.stderr)
        import traceback; traceback.print_exc() if __import__("os").environ.get("HS_TRACE") else None
    from . import exhibitions as EX                      # v37: all-star weekend on its day
    try:
        EX.daily(conn, env, skill, day)
    except Exception as e:                               # an exhibition never stops the season
        import sys
        print(f"all-star weekend skipped: {e!r}", file=sys.stderr)
    rng = random.Random(f"{seed}-{day}-ai")
    for t in sorted(r["team_id"] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")):
        if t != user_team_id:
            s.moves += ai_manage(conn, t, day, rng)
    from . import trades
    s.trades = trades.ai_day(conn, day, random.Random(f"{seed}-{day}-trades"))
    if user_team_id is not None:                      # an AI club may call with an offer (hs/game/gm_trades.py)
        from . import gm_trades
        dl = trades.deadline(conn)
        rush = 0 <= (dl - datetime.date.fromisoformat(day)).days < trades.DEADLINE_RUSH_DAYS
        if gm_trades.ai_offers(conn, day, random.Random(f"{seed}-{day}-offers"), rush):
            s.user_alerts.append("trade_offer")
        from . import shop                            # v42: calls about a player you are shopping
        if shop.daily(conn, day, seed):
            s.user_alerts.append("trade_offer")
    # the organisation: weekly locker room and boardroom (hot-seat score, ultimatums, directives, leaks)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        from . import people
        if datetime.date.fromisoformat(day).weekday() == 0:
            people.weekly(conn, day)
            FN.weekly(conn, day)
            from . import harmony                        # v35: cliques, clashes and incidents
            harmony.weekly(conn, day)
            from . import scout_net                      # v36: your scouts' week, trips, central scouting's lists
            scout_net.weekly(conn, day)
            if user_team_id is not None:                 # v37: achievements
                from . import legacy
                legacy.check_achievements(conn, day)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone():
        from . import boardroom as BR
        board_lines = BR.daily(conn, day)
        if datetime.date.fromisoformat(day).weekday() == 0:
            board_lines += BR.weekly(conn, day)
        s.board = board_lines
        if user_team_id is not None and conn.execute(
                "SELECT 1 FROM inbox WHERE date=? AND read=0 AND subject IN ('URGENT: from the owner''s office', "
                "'Dismissed', 'A directive from the owner', 'Directive missed')", (day,)).fetchone():
            s.user_alerts.append("board")
    if user_team_id is not None:                      # the press room (post-game, availability, deadline, stories)
        from . import press
        s.press = press.daily(conn, day, s)
        if any(k in press.MAJOR for k in s.press):
            s.user_alerts.append("press")
    # alerts for the user
    s.user_alerts += [f"injury:{pid}" for pid, t, d in s.injuries if t == user_team_id]
    c = counts(conn, user_team_id)
    for g, n in NEED.items():
        if c[g] < n <= before[g]:      # only newly short, so an unfixed gap does not stop every sim
            s.user_alerts.append(f"short:{g}")
    conn.execute('UPDATE game_state SET "current_date"=? WHERE id=1', (day,))
    conn.commit()
    return s


def remaining(conn):
    return conn.execute("SELECT COUNT(*) FROM games WHERE played=0 AND game_type='RS'").fetchone()[0]


def last_game_date(conn):
    return conn.execute("SELECT MAX(game_date) FROM games WHERE game_type='RS'").fetchone()[0]


def user_game_dates(conn, team_id, after):
    return [r[0] for r in conn.execute(
        "SELECT game_date FROM games WHERE game_type='RS' AND played=0 AND game_date>? AND (home_team_id=? OR "
        "away_team_id=?) ORDER BY game_date", (after, team_id, team_id))]


def sim_until(conn, env, skill, user_team_id=None, until_date=None, days=None, through_user_game=False,
              before_user_game=False, to_end=False, on_day=None):
    """Repeat sim_day until a stop condition. Returns list of DaySummary. Stops early (after that day) if the user
    is needed (user injury or too few players at a position), or when the regular season ends (playoffs are then run)."""
    user_team_id = user_team_id if user_team_id is not None else user_team(conn)
    out = []
    while remaining(conn):
        cur, _ = get_state(conn)
        nxt = (datetime.date.fromisoformat(cur) + datetime.timedelta(days=1)).isoformat()
        if until_date and nxt > until_date:
            break
        if days is not None and len(out) >= days:
            break
        if before_user_game and out and nxt in user_game_dates(conn, user_team_id, cur)[:1]:
            break
        s = sim_day(conn, env, skill, user_team_id)
        out.append(s)
        if on_day:
            on_day(s)
        if through_user_game and any(user_team_id in (r[1], r[2]) for r in s.results):
            break
        if s.user_alerts and not to_end:
            break
    if not remaining(conn) and season_state(conn) == "regular_season":
        finish_season(conn, env, skill)
        if out:
            out[-1].season_finished = True
    return out


def finish_season(conn, env, skill):
    """Run the playoffs once, mark the season finished, tell the user who won. Idempotent."""
    if season_state(conn) != "regular_season" or remaining(conn):
        return None
    rules = db_rules(conn)
    info = {t["team_id"]: t for t in team_rows(conn)}
    season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    day, seed = get_state(conn)
    for tid in sorted(info):
        ensure_dressable(conn, tid, day)
    record_season_stats(conn, season_id)
    from . import ltir as LT
    LT.end_of_season(conn, day)
    from . import elc as E
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    for line in E.season_end(conn, year, day):
        add_message(conn, day, "Entry-level bonuses", line)
    from . import world as Wd
    from . import leagues as LGS                         # v44: finish the leagues' year (late playoffs, the Memorial Cup)
    if LGS.leagues(conn):
        LGS.finish_year(conn)
    Wd.lower_league_season(conn, season_id)             # (only for worlds whose leagues have no rules)
    teams = load_teams(conn)
    rec, h2h = standings.table(conn, season_id)
    order = standings.rank(rec, h2h, rules)
    po = rules["playoffs"]
    q = (qualify_division_wildcard if po["format"] == "division_wildcard" else qualify_conference_top_n)(
        order, list(info.values()), po)
    start = datetime.date.fromisoformat(last_game_date(conn)) + datetime.timedelta(days=3)
    rounds, champ = run_playoffs(conn, q, teams, env, skill, rules, order, season_id, start, seed)
    from . import rivalry as RV                          # v37: playoff meetings make rivalries; then the summer cools them
    RV.season_end(conn, season_id)
    from . import finance as FN
    FN.playoff_gates(conn, season_id, day)
    FN.season_close(conn, year, day)
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state','finished')")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('champion', ?)", (str(champ),))
    fin = [r for r in conn.execute("SELECT home_team_id, away_team_id, home_goals, away_goals FROM games WHERE season_id=? AND "
                                   "game_type='PO' AND series_id='Final' AND played=1", (season_id,))]
    wins = {}
    for h, a, hg, ag in fin:
        w = h if hg > ag else a
        wins[w] = wins.get(w, 0) + 1
    loser = next((t for t in wins if t != champ), None) or next((x for g in fin for x in g[:2] if x != champ), None)
    cname = f"{info[champ]['name']} {info[champ]['nickname'] or ''}".strip()
    add_message(conn, day, "Season over",
                f"The {cname} are the champions" + (f", beating the {info[loser]['name']} {info[loser]['nickname'] or ''} "
                f"{wins.get(champ, 4)}-{wins.get(loser, 0)} in the final" if loser in info else "") + ".\n"
                "The champions screen has their path, the final game by game and the playoff MVP (League > Champions). "
                "Awards night follows (League > Awards Night).")
    from .events import emit
    emit(conn, "CHAMPIONSHIP", day, f"{info[champ]['name']} {info[champ]['nickname'] or ''} win the championship",
         team_id=champ, importance=3)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone():
        from . import boardroom as BR, org
        BR.end_of_season(conn, day)
        org.season_review(conn, day, season_id)
    check_records(conn, season_id, day)
    from . import history as H
    H.season_end(conn, season_id, day)
    from . import legacy                                 # v37: GM scores, the Hall of Fame ballot, achievements
    legacy.season_end(conn, season_id, day)
    try:                                                  # your reputation follows your results (phase A2)
        from . import gm as GMx
        GMx.season_reputation(conn, year)
    except Exception:
        pass
    from . import expansion as XP                        # v45: an announced club comes into being; protection lists
    for line in XP.season_over(conn, day):
        add_message(conn, day, "Expansion", line, sender="League office")
    from . import challenge as CHL                       # v47: the challenge's goal is checked
    CHL.season_end(conn, day)
    from . import international as INTL                  # v51: the World Championship, once the NHL playoffs are over
    try:
        INTL.season_over(conn, day)
    except Exception as e:
        import sys
        print(f"world championship skipped: {e!r}", file=sys.stderr)
        import traceback; traceback.print_exc() if __import__("os").environ.get("HS_TRACE") else None
    from . import press
    press.schedule(conn, "season_end", day)
    conn.commit()
    return champ


def record_season_stats(conn, season_id):
    """Fold this season's regular-season box scores into skater/goalie_season_stats (feeds next season's depth
    charts, rights status and arbitration). Runs once per season. If the pack already had stats for the season
    just simulated (a 2025-26 pack holds the real 2025-26), the simulated season replaces them: they move to
    replaced_*_season_stats, so no career counts a season twice."""
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    league = conn.execute("SELECT league_id FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    key = f"stats_recorded_{year}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    for t in ("skater_season_stats", "goalie_season_stats"):
        conn.execute(f"CREATE TABLE IF NOT EXISTS replaced_{t} AS SELECT * FROM {t} WHERE 0")
        conn.execute(f"INSERT INTO replaced_{t} SELECT * FROM {t} WHERE season_start_year=? AND league_id=? AND "
                     "split='RS'", (year, league))
        conn.execute(f"DELETE FROM {t} WHERE season_start_year=? AND league_id=? AND split='RS'", (year, league))
    rows = conn.execute(
        "SELECT s.player_id, s.team_id, p.position, COUNT(*) gp, SUM(s.goals) g, SUM(s.assists) a, SUM(s.shots) sog, "
        "SUM(s.toi_sec) toi, SUM(s.saves) sv, SUM(s.shots_against) sa FROM player_game_stats s "
        "JOIN games g USING (game_id) JOIN players p USING (player_id) WHERE g.season_id=? AND g.game_type='RS' "
        "GROUP BY s.player_id, s.team_id", (season_id,)).fetchall()
    for r in rows:
        if r["position"] == "G":
            conn.execute("INSERT INTO goalie_season_stats (player_id, season_start_year, team_id, league_id, split, gp, "
                         "toi_sec, ga, sa) VALUES (?,?,?,?, 'RS', ?,?,?,?)",
                         (r["player_id"], year, r["team_id"], league, r["gp"], r["toi"], r["sa"] - r["sv"], r["sa"]))
        else:
            conn.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, "
                         "a, sog, toi_sec) VALUES (?,?,?,?, 'RS', ?,?,?,?,?)",
                         (r["player_id"], year, r["team_id"], league, r["gp"], r["g"], r["a"], r["sog"], r["toi"]))


SEASON_RECORDS = {"REC_GOALS_SEASON": "g", "REC_ASSISTS_SEASON": "a", "REC_POINTS_SEASON": "g + a"}


def check_records(conn, season_id, day):
    """Flag top-league single-season scoring records broken this season (needs league_records from a records
    file, from the legacy importers in tools/). Returns list of summaries."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='league_records'").fetchone():
        return []
    from .events import emit, player_name
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    top = conn.execute(f"SELECT league_id FROM teams WHERE {top_league_sql()} LIMIT 1").fetchone()[0]
    out = []
    for rtype, expr in SEASON_RECORDS.items():
        rec = conn.execute("SELECT MAX(value), holder FROM league_records WHERE scope='COMP_RECORD' AND rtype=? AND "
                           "league='National Hockey League'", (rtype,)).fetchone()
        if not rec or rec[0] is None:
            continue
        best = conn.execute(f"SELECT player_id, {expr} v FROM skater_season_stats WHERE season_start_year=? AND "
                            f"league_id=? AND split='RS' ORDER BY v DESC LIMIT 1", (year, top)).fetchone()
        if best and best[1] > rec[0]:
            text = f"{player_name(conn, best[0])} sets a league record: {best[1]} ({rtype.split('_')[1].lower()}), " \
                   f"previous {rec[0]:.0f} by {rec[1]}"
            emit(conn, "RECORD_BROKEN", day, text, player_id=best[0], importance=3, rtype=rtype, value=best[1])
            out.append(text)
    return out
