"""Play a whole season (schedule, regular season, standings, playoffs) from a game database.

    python -m hs.league.season <game.db> <env.json> [--seed 1] [--events] [--schedule-only]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from ..sim.engine import Skill, simulate_game
from ..sim.loader import load_teams, write_result
from . import standings
from .playoffs import qualify_conference_top_n, qualify_division_wildcard, run_playoffs
from .rules import check_rules, merged
from .schedule import build_schedule, schedule_stats


def db_rules(conn, season=None, base=False):
    """The league's rules for a season (the latest season by default), with rule eras applied (hs/league/eras.py).
    base=True: the pack's rules as stored, before eras."""
    row = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    if not row:
        return None
    rules = merged(json.loads(row[0]))
    if base:
        return rules
    if season is None:
        r = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()
        season = r[0] if r else None
    from .eras import for_season
    return for_season(rules, season) if season is not None else rules


def team_rows(conn):
    conn.row_factory = sqlite3.Row
    from ..schema import top_league_sql
    return [dict(r) for r in conn.execute("SELECT team_id, abbr, name, nickname, conference, division FROM teams "
                                          f"WHERE {top_league_sql()}")]


def create_schedule(conn, rules, seed):
    teams = team_rows(conn)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='expansion'").fetchone() and \
            conn.execute("SELECT 1 FROM expansion WHERE team_id IS NOT NULL").fetchone():
        rules = dict(rules, schedule=dict(rules["schedule"], balance=True))   # v45: a league that has expanded
    problems = check_rules(rules, teams)
    if problems:
        raise ValueError("; ".join(problems))
    season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    sched = build_schedule(teams, rules, seed)
    conn.executemany("INSERT INTO games (season_id, game_date, home_team_id, away_team_id) VALUES (?,?,?,?)",
                     [(season_id, d.isoformat(), h, a) for d, h, a in sched])
    conn.commit()
    return season_id, sched


def play_regular_season(conn, teams, env, skill, seed, store_events=False, overtime=None):
    games = conn.execute("SELECT game_id, home_team_id, away_team_id FROM games WHERE played=0 AND game_type='RS' "
                         "ORDER BY game_date, game_id").fetchall()
    for gid, h, a in games:
        s = seed * 1_000_003 + gid
        res = simulate_game(teams[h], teams[a], env, skill, s, events=store_events, overtime=overtime)
        write_result(conn, gid, h, a, res, s, teams)
    conn.commit()
    return len(games)


def format_standings(conn, rules, season_id, info):
    rec, h2h = standings.table(conn, season_id)
    order = standings.rank(rec, h2h, rules)
    lines = []
    by_div = defaultdict(list)
    for t in order:
        by_div[(info[t]["conference"], info[t]["division"])].append(t)
    pts = rules["points"]
    for (conf, div), members in sorted(by_div.items()):
        lines.append(f"\n{conf} - {div}\n  {'':<5}{'GP':>3}{'W':>4}{'L':>4}{'OTL':>4}{'PTS':>5}{'RW':>4}{'GF':>5}{'GA':>5}{'DIFF':>6}")
        for t in members:
            r = rec[t]
            lines.append(f"  {info[t]['abbr']:<5}{r['gp']:>3}{r['w']:>4}{r['l']:>4}{r['otl']:>4}{standings.points(r, pts):>5}"
                         f"{r['rw']:>4}{r['gf']:>5}{r['ga']:>5}{r['gf'] - r['ga']:>+6}")
    return order, rec, "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db")
    ap.add_argument("env")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--events", action="store_true", help="store every event of every regular-season game (bigger db)")
    ap.add_argument("--schedule-only", action="store_true")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db)
    rules = db_rules(conn)
    if rules is None:
        raise SystemExit("This pack has no rules.json; add one (see docs/LEAGUES_AND_SCHEDULES.md).")
    if not conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]:
        season_id, sched = create_schedule(conn, rules, a.seed)
        st = schedule_stats(sched)
        b2b = sum(t["b2b"] for t in st["teams"]) / len(st["teams"])
        print(f"Schedule: {len(sched)} games, {st['first']} to {st['last']}, {st['game_days']} game days, "
              f"back-to-backs/team {b2b:.1f}, longest home/away run {max(max(t['longest_home'], t['longest_away']) for t in st['teams'])}")
    else:
        season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    if a.schedule_only:
        conn.close()
        return
    env = json.load(open(a.env))
    from ..sim.engine import skill_for
    skill = skill_for(rules)
    teams = load_teams(conn)
    conn.row_factory = None
    info = {t["team_id"]: t for t in team_rows(conn)}
    conn.row_factory = None
    t0 = time.time()
    n = play_regular_season(conn, teams, env, skill, a.seed, a.events, rules.get("overtime"))
    print(f"Played {n} regular-season games in {time.time() - t0:.0f}s")
    order, rec, text = format_standings(conn, rules, season_id, info)
    print(text)
    po = rules["playoffs"]
    q = (qualify_division_wildcard if po["format"] == "division_wildcard" else qualify_conference_top_n)(
        order, list(info.values()), po)
    last = date.fromisoformat(conn.execute("SELECT MAX(game_date) FROM games WHERE game_type='RS'").fetchone()[0])
    rounds, champ = run_playoffs(conn, q, teams, env, skill, rules, order, season_id, last + timedelta(days=3), a.seed)
    conn.commit()
    print("\nPLAYOFFS")
    for i, rd in enumerate(rounds, 1):
        print(f" Round {i}")
        for s in rd:
            print(f"   {s['series']:<34} {info[s['winner']]['abbr']} def. {info[s['loser']]['abbr']} {s['wins'][0]}-{s['wins'][1]}")
    print(f"\nChampion: {info[champ]['name']} {info[champ]['nickname'] or ''}")
    conn.close()


if __name__ == "__main__":
    main()
