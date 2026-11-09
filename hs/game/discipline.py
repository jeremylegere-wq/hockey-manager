"""Supplementary discipline: suspensions (v53; docs/DISCIPLINE.md).

Incidents: about 3.5% of NHL games produce a play the league's player-safety office suspends for (the NHL hands out
roughly 40-50 a season). The player is drawn from the two lineups, weighted by aggression and hitting (the
toughest, angriest players most often). Length: 1 game 35%, 2 25%, 3 15%, 4-5 12%, 6-10 10%, 11-20 3%; a repeat
offender (suspended in the last 18 months) gets half as many games again. The kinds: an illegal check to the head,
boarding, charging, cross-checking, slashing, high-sticking, elbowing, kneeing, interference, leaving the bench.
Serving it: the suspension starts with his club's next game; he cannot dress until it is served (games left carry
over into the playoffs and the next season). He forfeits his pay for those days (his cap hit / 82 a game); it does
not count against the cap.
Appeals: a suspension of six or more games can be appealed once (your club: `discipline appeal <player>`); the
commissioner cuts it by a third 25% of the time, otherwise upholds it.
Data packs can preset suspensions (suspensions.csv: player_id, games[, reason]) and injuries (injuries.csv:
player_id, days or return_date[, description]).
"""
from __future__ import annotations

import datetime
import random

from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

P_INCIDENT = 0.035
LENGTHS = [(1, 0.35), (2, 0.25), (3, 0.15), (4, 0.07), (5, 0.05), (6, 0.03), (7, 0.02), (8, 0.02), (10, 0.03), (15, 0.02), (20, 0.01)]
REPEAT_MONTHS = 18
APPEAL_MIN, APPEAL_P = 6, 0.25
KINDS = ["an illegal check to the head", "boarding", "charging", "cross-checking", "slashing", "high-sticking", "elbowing", "kneeing",
         "interference", "leaving the bench to start an altercation"]


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS suspensions (susp_id INTEGER PRIMARY KEY, player_id INTEGER, team_id INTEGER, day TEXT, "
                 "games INTEGER, games_left INTEGER, reason TEXT, forfeit INTEGER, appealed INTEGER DEFAULT 0, appeal_result TEXT, "
                 "game_id INTEGER, source TEXT)")


def suspended(conn):
    """Player ids who cannot dress today."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='suspensions'").fetchone():
        return set()
    return {r[0] for r in conn.execute("SELECT player_id FROM suspensions WHERE games_left>0")}


def games_left(conn, pid):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='suspensions'").fetchone():
        return 0
    r = conn.execute("SELECT COALESCE(SUM(games_left), 0) FROM suspensions WHERE player_id=?", (pid,)).fetchone()
    return r[0] or 0


def _length(rng):
    x = rng.random()
    for n, p in LENGTHS:
        x -= p
        if x <= 0:
            return n
    return 1


def suspend(conn, pid, games, reason, day, team=None, game_id=None, source="league"):
    ensure_tables(conn)
    team = team if team is not None else conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    from . import contracts as K
    c = K.current_contract(conn, pid, K.season_year(conn))
    forfeit = int((c["cap_hit"] if c else 0) / 82 * games)
    conn.execute("INSERT INTO suspensions (player_id, team_id, day, games, games_left, reason, forfeit, game_id, source) VALUES (?,?,?,?,?,?,?,?,?)",
                 (pid, team, day, games, games, reason, forfeit, game_id, source))
    return forfeit


def after_games(conn, day, game_rows, seed=0):
    """Today's NHL games are played: suspensions from them, and games served. game_rows: [(game_id, home, away)]."""
    ensure_tables(conn)
    played = {t for _, h, a in game_rows for t in (h, a)}
    # serving: a suspension issued before today counts each of his club's games
    for sid, pid, team in conn.execute("SELECT susp_id, player_id, team_id FROM suspensions WHERE games_left>0 AND day<?", (day,)).fetchall():
        cur = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()
        club = cur[0] if cur else None
        if club in played:
            conn.execute("UPDATE suspensions SET games_left=games_left-1, team_id=? WHERE susp_id=?", (club, sid))
            if conn.execute("SELECT games_left FROM suspensions WHERE susp_id=?", (sid,)).fetchone()[0] == 0 and club == user_team(conn):
                add_message(conn, day, f"{player_name(conn, pid)} is eligible again", f"{player_name(conn, pid)} has served his suspension "
                            "and can play in our next game.", sender="Hockey operations")
    me = user_team(conn)
    out = []
    for gid, h, a in game_rows:
        rng = random.Random(f"{seed}-incident-{gid}")
        if rng.random() >= P_INCIDENT:
            continue
        dressed = conn.execute("SELECT s.player_id, s.team_id, COALESCE(a.aggression, 10), COALESCE(a.hitting, 10) FROM player_game_stats s "
                               "JOIN players p USING (player_id) LEFT JOIN player_attributes a USING (player_id) WHERE s.game_id=? AND "
                               "p.position<>'G'", (gid,)).fetchall()
        if not dressed:
            continue
        w = [max(1.0, (ag - 6) + 0.6 * (ht - 6)) ** 2 for _, _, ag, ht in dressed]
        x = rng.random() * sum(w)
        for (pid, team, _, _), wt in zip(dressed, w):
            x -= wt
            if x <= 0:
                break
        n = _length(rng)
        since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=REPEAT_MONTHS * 30)).isoformat()
        repeat = conn.execute("SELECT COUNT(*) FROM suspensions WHERE player_id=? AND day>=?", (pid, since)).fetchone()[0]
        if repeat:
            n = int(round(n * 1.5))
        kind = rng.choice(KINDS)
        opp = a if team == h else h
        forfeit = suspend(conn, pid, n, kind, day, team, gid)
        text = f"{player_name(conn, pid)} ({team_abbr(conn, team)}) suspended {n} game{'s' if n != 1 else ''} for {kind}"
        emit(conn, "MEDIA_STORY", day, text + (" (repeat offender)" if repeat else ""), team_id=team, player_id=pid, other_team_id=opp,
             importance=3 if n >= 6 else 2, headline=f"{player_name(conn, pid)} suspended", tag="discipline", kind="suspension",
             body=text + f" against {team_abbr(conn, opp)}. He forfeits ${forfeit:,.0f}." + (" He has been suspended before." if repeat else ""))
        if team == me:
            add_message(conn, day, f"{player_name(conn, pid)} suspended {n} game{'s' if n != 1 else ''}",
                        f"The league has suspended {player_name(conn, pid)} for {n} game{'s' if n != 1 else ''} for {kind} against "
                        f"{team_abbr(conn, opp)}. He forfeits ${forfeit:,.0f} in pay." + (" He is a repeat offender." if repeat else "")
                        + (f"\nWe can appeal a suspension of {APPEAL_MIN}+ games once: `discipline appeal {pid}`." if n >= APPEAL_MIN else ""),
                        sender="Hockey operations")
        out.append(text)
    return out


def appeal(conn, pid, day=None):
    ensure_tables(conn)
    day = day or get_state(conn)[0]
    r = conn.execute("SELECT susp_id, games, games_left, appealed, team_id FROM suspensions WHERE player_id=? AND games_left>0 ORDER BY susp_id DESC LIMIT 1",
                     (pid,)).fetchone()
    if r is None:
        raise ValueError("He is not suspended.")
    if r[4] != user_team(conn):
        raise ValueError("Only his club can appeal.")
    if r[1] < APPEAL_MIN:
        raise ValueError(f"Only a suspension of {APPEAL_MIN} or more games can be appealed.")
    if r[3]:
        raise ValueError("This suspension has already been appealed.")
    rng = random.Random(f"{get_state(conn)[1]}-appeal-{r[0]}")
    if rng.random() < APPEAL_P:
        cut = max(1, round(r[1] / 3))
        new_left = max(0, r[2] - cut)
        conn.execute("UPDATE suspensions SET appealed=1, appeal_result=?, games=games-?, games_left=? WHERE susp_id=?",
                     (f"reduced by {cut}", cut, new_left, r[0]))
        msg = f"The appeal succeeds: {player_name(conn, pid)}'s suspension is cut by {cut} game{'s' if cut != 1 else ''} ({new_left} left)."
    else:
        conn.execute("UPDATE suspensions SET appealed=1, appeal_result='upheld' WHERE susp_id=?", (r[0],))
        msg = f"The commissioner upholds {player_name(conn, pid)}'s suspension ({r[2]} game{'s' if r[2] != 1 else ''} left)."
    emit(conn, "MEDIA_STORY", day, msg, team_id=r[4], player_id=pid, importance=2, headline="Suspension appeal", body=msg, tag="discipline",
         kind="appeal")
    return msg


def view(conn):
    ensure_tables(conn)
    from .contracts import season_year
    y = season_year(conn)
    rows = conn.execute("SELECT s.*, p.first_name||' '||p.last_name name FROM suspensions s JOIN players p USING (player_id) "
                        "ORDER BY s.day DESC, s.susp_id DESC LIMIT 200").fetchall()
    me = user_team(conn)
    out = [dict(player_id=r["player_id"], name=r["name"], team=team_abbr(conn, r["team_id"]) if r["team_id"] else "", day=r["day"], games=r["games"],
                left=r["games_left"], reason=r["reason"], forfeit=r["forfeit"], appeal=r["appeal_result"],
                can_appeal=r["team_id"] == me and r["games"] >= APPEAL_MIN and not r["appealed"] and r["games_left"] > 0) for r in rows]
    return dict(active=[x for x in out if x["left"] > 0], log=out, appeal_min=APPEAL_MIN)


def load_pack(conn, tables, season_start):
    """Preset suspensions and injuries from a data pack (at world build)."""
    ensure_tables(conn)
    n = 0
    for r in tables.get("suspensions.csv", []):
        try:
            pid, g = int(r["player_id"]), int(r["games"])
        except (KeyError, ValueError, TypeError):
            continue
        if g > 0:
            conn.execute("INSERT INTO suspensions (player_id, team_id, day, games, games_left, reason, forfeit, source) VALUES "
                         "(?, (SELECT team_id FROM players WHERE player_id=?), ?, ?, ?, ?, 0, 'pack')",
                         (pid, pid, f"{season_start}-09-01", g, g, (r.get("reason") or "carried over from last season").strip()))
            n += 1
    for r in tables.get("injuries.csv", []):
        try:
            pid = int(r["player_id"])
        except (KeyError, ValueError, TypeError):
            continue
        back = (r.get("return_date") or "").strip()
        if not back and (r.get("days") or "").strip().isdigit():
            back = (datetime.date(season_start, 10, 1) + datetime.timedelta(days=int(r["days"]))).isoformat()
        if not back:
            continue
        conn.execute("INSERT INTO injuries (player_id, start_date, expected_return, description) VALUES (?,?,?,?)",
                     (pid, f"{season_start}-09-01", back, (r.get("description") or "injured").strip()))
        conn.execute("UPDATE players SET status='injured' WHERE player_id=? AND status='active'", (pid,))
        n += 1
    return n
