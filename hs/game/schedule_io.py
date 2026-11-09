"""Schedule export and import (v48; docs/QUICKSTARTS.md "Schedules").

Export (anyone): this season's regular-season schedule as CSV: date, home, away (club abbreviations), and for games
already played the score (home_goals, away_goals, ot).
Import (commissioner mode): a CSV with date, home and away columns (others are ignored) replaces this season's
unplayed regular-season games. Checks, row by row: a real date inside the season (after today, before the regular
season's end plus 30 days), two different NHL clubs, no club twice on one day. Then for the whole schedule: every club's
total (games played plus imported) is reported, and unequal totals are a warning (standings use points percentage only
if you set it so; points tables still work). Preview first; apply writes it.
"""
from __future__ import annotations

import csv
import datetime
import io
from collections import Counter

from .state import get_state


def _season_id(conn):
    return conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]


def _top(conn):
    from ..schema import top_league_sql
    return {r[1].upper(): r[0] for r in conn.execute(f"SELECT team_id, abbr FROM teams WHERE {top_league_sql()}")}


def export_csv(conn):
    sid = _season_id(conn)
    ab = {v: k for k, v in _top(conn).items()}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "home", "away", "home_goals", "away_goals", "ot"])
    for d, h, a, played, hg, ag, ot in conn.execute("SELECT game_date, home_team_id, away_team_id, played, home_goals, away_goals, went_to_ot "
                                                   "FROM games WHERE season_id=? AND game_type='RS' ORDER BY game_date, game_id", (sid,)):
        w.writerow([d, ab.get(h, h), ab.get(a, a)] + ([hg, ag, {0: "", 1: "OT", 2: "SO"}.get(ot or 0, "")] if played else ["", "", ""]))
    return out.getvalue()


def import_csv(conn, text, apply=False):
    """dict(rows, problems [(row, text)], warnings, totals {abbr: games}, applied)."""
    from . import editor
    if apply:
        editor._need(conn)
    teams = _top(conn)
    sid = _season_id(conn)
    today = get_state(conn)[0]
    end = conn.execute("SELECT end_date FROM seasons WHERE season_id=?", (sid,)).fetchone()[0] or f"{int(today[:4]) + 1}-04-30"
    last = (datetime.date.fromisoformat(end) + datetime.timedelta(days=30)).isoformat()
    try:
        rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        rows = list(rd)
        heads = {h.strip().lower(): h for h in (rd.fieldnames or [])}
    except csv.Error as e:
        return dict(rows=0, problems=[(0, f"Not a CSV file: {e}")], warnings=[], totals={}, applied=0)
    need = [h for h in ("date", "home", "away") if h not in heads]
    if need:
        return dict(rows=len(rows), problems=[(1, "Missing column(s): " + ", ".join(need))], warnings=[], totals={}, applied=0)
    problems, games, seen = [], [], set()
    for k, r in enumerate(rows, 2):
        d = (r.get(heads["date"]) or "").strip()[:10]
        h = (r.get(heads["home"]) or "").strip().upper()
        a = (r.get(heads["away"]) or "").strip().upper()
        try:
            datetime.date.fromisoformat(d)
        except ValueError:
            problems.append((k, f"date {d!r} is not YYYY-MM-DD"))
            continue
        if d <= today:
            problems.append((k, f"{d} is not after today ({today})"))
            continue
        if d > last:
            problems.append((k, f"{d} is after the season ({end})"))
            continue
        if h not in teams or a not in teams:
            problems.append((k, f"unknown club {h if h not in teams else a}"))
            continue
        if h == a:
            problems.append((k, f"{h} cannot play itself"))
            continue
        if (d, h) in seen or (d, a) in seen:
            problems.append((k, f"{h if (d, h) in seen else a} already plays on {d}"))
            continue
        seen |= {(d, h), (d, a)}
        games.append((d, teams[h], teams[a]))
    played = Counter()
    for h, a in conn.execute("SELECT home_team_id, away_team_id FROM games WHERE season_id=? AND game_type='RS' AND played=1", (sid,)):
        played[h] += 1
        played[a] += 1
    tot = Counter(played)
    for d, h, a in games:
        tot[h] += 1
        tot[a] += 1
    ab = {v: k for k, v in teams.items()}
    totals = {ab[t]: tot.get(t, 0) for t in teams.values()}
    warnings = []
    if len(set(totals.values())) > 1:
        warnings.append(f"Clubs play different numbers of games ({min(totals.values())} to {max(totals.values())}).")
    # a day the imported games and the clubs' played games overlap is fine: only unplayed games are replaced
    applied = 0
    if apply and not problems:
        conn.execute("DELETE FROM games WHERE season_id=? AND game_type='RS' AND played=0", (sid,))
        conn.executemany("INSERT INTO games (season_id, game_date, home_team_id, away_team_id) VALUES (?,?,?,?)",
                         [(sid, d, h, a) for d, h, a in sorted(games)])
        applied = len(games)
        editor._log(conn, "schedule", f"imported {applied} games")
    return dict(rows=len(rows), games=len(games), problems=problems, warnings=warnings, totals=totals, applied=applied)
