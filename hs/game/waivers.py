"""Waivers: sending a non-exempt player to the minors puts him on waivers, where any club may claim him
(docs/WAIVERS.md).

Exemption (from his first NHL contract; waiver age = his age on 15 September of that contract's first season):
  skaters  18: 5 seasons or 160 NHL games, 19: 4/160, 20: 3/160, 21: 3/80, 22: 3/70, 23: 3/60, 24: 2/60, 25+: 1
  goalies  18: 6 seasons or 80 NHL games, 19: 5/80, 20: 4/80, 21: 4/60, 22: 4/60, 23: 3/60, 24: 2/60, 25+: 1
  An 18- or 19-year-old who plays 11+ NHL games in his first season drops to 3 seasons (goalies 4). Seasons are
  counted from the contract's first season, less any slid entry-level years (whichever limit comes first).
  Table: PuckPedia's waiver page. The rest is from memory of the CBA: the waiver period runs from the preseason to
  the end of the regular season; a player is on waivers for one day; claims go to the club lowest in the standings
  (points percentage; on paper strength early in the season); a player who cleared can be recalled and sent down
  again without waivers for 30 days, as long as he plays fewer than 10 NHL games in that time.
A claiming club takes his contract and puts him on its NHL roster (it must waive him again to send him down).
AI clubs claim when the player would improve their weakest position group's depth, they have cap room and a contract
slot, half the time; when they need to send someone down they prefer exempt players.
"""
from __future__ import annotations

import datetime
import random

from . import contracts as K
from . import roster as R
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

SKATERS = {18: (5, 160), 19: (4, 160), 20: (3, 160), 21: (3, 80), 22: (3, 70), 23: (3, 60), 24: (2, 60)}
GOALIES = {18: (6, 80), 19: (5, 80), 20: (4, 80), 21: (4, 60), 22: (4, 60), 23: (3, 60), 24: (2, 60)}
OLD = (1, None)
FIRST_YEAR_GAMES = 11
RECLEAR_DAYS, RECLEAR_GAMES = 30, 10
P_CLAIM, CLAIM_MARGIN = 0.5, 1.0      # v25: claims ran ~60 a season at 0.6 / 0.5 (real NHL ~30-40)
AI_EXEMPT_PREFERENCE = 2.5      # value points: an AI club sends down an exempt player unless he is this much better


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS waivers (waiver_id INTEGER PRIMARY KEY, player_id INTEGER, "
                 "team_id INTEGER, placed TEXT, clears TEXT, outcome TEXT, claimed_by INTEGER, resolved TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS waiver_claims (player_id INTEGER, team_id INTEGER, PRIMARY KEY "
                 "(player_id, team_id))")


def in_period(conn):
    return K.season_state(conn) in ("preseason", "regular_season")


def nhl_games(conn, pid):
    top = conn.execute("SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    past = 0
    for t in ("skater_season_stats", "goalie_season_stats"):
        past += conn.execute(f"SELECT COALESCE(SUM(gp), 0) FROM {t} WHERE player_id=? AND league_id=? AND split='RS'",
                             (pid, top)).fetchone()[0]
    year = K.season_year(conn)
    if not conn.execute("SELECT 1 FROM pack_info WHERE key=?", (f"stats_recorded_{year}",)).fetchone():
        past += conn.execute("SELECT COUNT(*) FROM player_game_stats s JOIN games g USING (game_id) JOIN seasons x "
                             "USING (season_id) WHERE s.player_id=? AND x.start_year=? AND g.game_type='RS'",
                             (pid, year)).fetchone()[0]
    from . import career as CR                   # v41: NHL games before the save began
    return past + CR.nhl_gp(conn, pid)


def _first_contract(conn, pid):
    return conn.execute("SELECT MIN(start_year) FROM contracts WHERE player_id=?", (pid,)).fetchone()[0]


def status(conn, pid):
    """dict(exempt, waiver_age, seasons, season_limit, games, game_limit, why)."""
    p = conn.execute("SELECT birth_date, position FROM players WHERE player_id=?", (pid,)).fetchone()
    first = _first_contract(conn, pid)
    year = K.season_year(conn)
    if first is None:
        return dict(exempt=True, why="no NHL contract")
    age = K.age_on(p["birth_date"], datetime.date(first, 9, 15))
    table = GOALIES if p["position"] == "G" else SKATERS
    seasons_lim, games_lim = table.get(min(max(age, 18), 25), OLD) if age < 25 else OLD
    slides = 0
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='elc_terms'").fetchone():
        r = conn.execute("SELECT slides FROM elc_terms WHERE player_id=?", (pid,)).fetchone()
        slides = (r[0] or 0) if r else 0
    gp = nhl_games(conn, pid)
    if age <= 19:
        top = conn.execute("SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
        first_gp = sum(conn.execute(f"SELECT COALESCE(SUM(gp), 0) FROM {t} WHERE player_id=? AND league_id=? AND "
                                    "season_start_year=? AND split='RS'", (pid, top, first)).fetchone()[0]
                       for t in ("skater_season_stats", "goalie_season_stats"))
        if first_gp >= FIRST_YEAR_GAMES:
            seasons_lim = min(seasons_lim, 4 if p["position"] == "G" else 3)
    used = year - first + 1 - slides
    exempt = used <= seasons_lim and (games_lim is None or gp < games_lim)
    if exempt:
        why = (f"exempt: season {max(1, used)} of {seasons_lim}" + (f", {gp} of {games_lim} NHL games" if games_lim
                                                                   else ""))
    else:
        why = ("needs waivers: " + (f"past {seasons_lim} seasons" if used > seasons_lim else f"{gp} NHL games "
                                    f"(limit {games_lim})"))
    return dict(exempt=exempt, waiver_age=age, seasons=used, season_limit=seasons_lim, games=gp, game_limit=games_lim,
                why=why)


def recently_cleared(conn, pid, day):
    ensure_tables(conn)
    r = conn.execute("SELECT resolved FROM waivers WHERE player_id=? AND outcome='cleared' ORDER BY waiver_id DESC "
                     "LIMIT 1", (pid,)).fetchone()
    if not r:
        return False
    since = r[0]
    if (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(since)).days > RECLEAR_DAYS:
        return False
    games = conn.execute("SELECT COUNT(*) FROM player_game_stats s JOIN games g USING (game_id) WHERE s.player_id=? "
                         "AND g.game_date>=?", (pid, since)).fetchone()[0]
    return games < RECLEAR_GAMES


def needs_waivers(conn, pid, day):
    if not in_period(conn):
        return False
    claimed = conn.execute("SELECT 1 FROM waivers WHERE player_id=? AND outcome='claimed' AND claimed_by=(SELECT "
                           "team_id FROM players WHERE player_id=?) ORDER BY waiver_id DESC LIMIT 1",
                           (pid, pid)).fetchone() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='waivers'").fetchone() else None
    if claimed:
        return True                                   # a claimed player must be waived again
    return not status(conn, pid)["exempt"] and not recently_cleared(conn, pid, day)


def place(conn, team, pid, day, detail="placed on waivers"):
    ensure_tables(conn)
    clears = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
    conn.execute("INSERT INTO waivers (player_id, team_id, placed, clears) VALUES (?,?,?,?)", (pid, team, day, clears))
    conn.execute("UPDATE players SET status='waivers' WHERE player_id=?", (pid,))
    R._log(conn, day, "waivers", pid, team, team, detail)
    emit(conn, "PLAYER_RELEASED", day, f"{team_abbr(conn, team)} place {player_name(conn, pid)} on waivers",
         team_id=team, player_id=pid, importance=1, kind="waivers")


def on_wire(conn):
    ensure_tables(conn)
    return conn.execute("SELECT * FROM waivers WHERE outcome IS NULL ORDER BY waiver_id").fetchall()


def claim_order(conn, exclude):
    from .trades import standings_rank
    rank = standings_rank(conn)
    return [t for t in sorted(rank, key=lambda t: -rank[t]) if t != exclude]   # worst first


def user_claim(conn, pid, on=True):
    ensure_tables(conn)
    me = user_team(conn)
    if not conn.execute("SELECT 1 FROM waivers WHERE player_id=? AND outcome IS NULL", (pid,)).fetchone():
        raise R.RosterError("He is not on waivers.")
    if conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0] == me:
        raise R.RosterError("He is your own player.")
    if on:
        conn.execute("INSERT OR IGNORE INTO waiver_claims VALUES (?,?)", (pid, me))
    else:
        conn.execute("DELETE FROM waiver_claims WHERE player_id=? AND team_id=?", (pid, me))


def _ai_wants(conn, team, pid, rng):
    g = R.group(conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0])
    mv = K.day_values(conn)
    vals = sorted(mv.value(r["player_id"]) for r in R.roster(conn, team) if R.group(r["position"]) == g)
    v = mv.value(pid)
    if vals and v < vals[0] + CLAIM_MARGIN:
        return False
    return rng.random() < P_CLAIM


def _can_take(conn, team, pid):
    c = K.current_contract(conn, pid)
    year = K.season_year(conn)
    if c is not None and K.crules(conn)["cap_ceiling"]:
        room = K.cap_room(conn, team, year)
        if room is not None and room < c["cap_hit"]:
            return False
    mx = K.crules(conn).get("max_contracts")
    if mx and K.contract_count(conn, team, year) >= mx:
        return False
    return True


def process(conn, day):
    """Resolve waivers that clear today: the first club in claim order that claims him gets him. Returns lines."""
    ensure_tables(conn)
    me = user_team(conn)
    rng = random.Random(f"{get_state(conn)[1]}-{day}-waivers")
    lines = []
    for w in conn.execute("SELECT * FROM waivers WHERE outcome IS NULL AND clears<=? ORDER BY waiver_id",
                          (day,)).fetchall():
        pid, frm = w["player_id"], w["team_id"]
        if conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0] != frm:
            conn.execute("UPDATE waivers SET outcome='withdrawn', resolved=? WHERE waiver_id=?", (day, w["waiver_id"]))
            continue
        claimer = None
        user_wants = conn.execute("SELECT 1 FROM waiver_claims WHERE player_id=? AND team_id=?", (pid, me)).fetchone()
        for t in claim_order(conn, frm):
            wants = bool(user_wants) if t == me else _ai_wants(conn, t, pid, rng)
            if wants and _can_take(conn, t, pid):
                claimer = t
                break
        name = player_name(conn, pid)
        if claimer is None:
            conn.execute("UPDATE players SET status='prospect', club_id=? WHERE player_id=?",
                         (R.affiliate(conn, frm), pid))
            conn.execute("UPDATE waivers SET outcome='cleared', resolved=? WHERE waiver_id=?", (day, w["waiver_id"]))
            R._log(conn, day, "assign", pid, frm, frm, "cleared waivers; assigned to the minors")
            if frm == me:
                add_message(conn, day, "Cleared waivers", f"{name} cleared waivers and is in the minors. You can recall "
                            f"him without waivers for {RECLEAR_DAYS} days or {RECLEAR_GAMES} games.",
                            actions=[dict(label=f"Open {name}", href=f"#player/{pid}")])
        else:
            _, mx = R.limits(conn)
            if claimer != me and len(R.roster(conn, claimer)) >= mx:
                R.make_room(conn, claimer, day, None)
            conn.execute("UPDATE players SET team_id=?, club_id=?, status='active' WHERE player_id=?",
                         (claimer, claimer, pid))
            conn.execute("UPDATE contracts SET team_id=? WHERE player_id=? AND start_year+years>?",
                         (claimer, pid, K.season_year(conn)))
            conn.execute("UPDATE waivers SET outcome='claimed', claimed_by=?, resolved=? WHERE waiver_id=?",
                         (claimer, day, w["waiver_id"]))
            R._log(conn, day, "waiver_claim", pid, frm, claimer, "claimed on waivers")
            emit(conn, "PLAYER_SIGNED", day, f"{team_abbr(conn, claimer)} claim {name} off waivers from "
                 f"{team_abbr(conn, frm)}", team_id=claimer, other_team_id=frm, player_id=pid, importance=2,
                 kind="waiver_claim")
            lines.append(f"{team_abbr(conn, claimer)} claim {name} from {team_abbr(conn, frm)}")
            if frm == me:
                add_message(conn, day, "Lost on waivers", f"{team_abbr(conn, claimer)} claimed {name} off waivers.",
                            actions=[dict(label=f"Open {name}", href=f"#player/{pid}")])
            if claimer == me:
                add_message(conn, day, "Waiver claim", f"You claimed {name} from {team_abbr(conn, frm)}; he is on "
                            "your NHL roster (send him down and he goes back on waivers).",
                            actions=[dict(label=f"Open {name}", href=f"#player/{pid}")])
        conn.execute("DELETE FROM waiver_claims WHERE player_id=?", (pid,))
    return lines


def ai_send_down_choice(conn, team_id, candidates):
    """candidates: [(value, pid, pos)] lowest first. An AI club prefers an exempt player unless he is clearly better."""
    if not candidates or not in_period(conn):
        return candidates[0] if candidates else None
    day = get_state(conn)[0]
    best = None
    for v, pid, pos in candidates[:6]:
        cost = v + (0 if not needs_waivers(conn, pid, day) else AI_EXEMPT_PREFERENCE)
        if best is None or cost < best[0]:
            best = (cost, (v, pid, pos))
    return best[1]
