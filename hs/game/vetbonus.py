"""Performance bonuses for veterans on one-year deals (v61; NHL CBA 50.2(b)(i)(B); docs/CONTRACTS.md).

Besides entry-level contracts, two kinds of contract may carry performance bonuses:
  35+        a one-year contract for a player 35 or older on 30 June before the season it covers
  injured    a one-year contract for a player with 400+ NHL games who spent 100+ days injured last season
The bonuses sit outside the cap hit until they are earned. A club may go over the cap by up to the bonus cushion
(7.5% of the ceiling) through performance bonuses, and what its earned bonuses push it past the ceiling is charged
to next season's cap (a bonus overage, the same as entry-level bonuses: hs/game/elc.py).

The bonus is earned at season end in four equal parts:
  skaters  10 NHL games · 41 games · 25 points (forwards) or 15 (defencemen) · the club makes the playoffs
  goalies  10 games · 25 games · a .905 save percentage (10+ games) · the club makes the playoffs
A player values bonus money at PERF_VALUE of guaranteed money (he may not earn it), so a bonus-heavy deal costs a
club more in total but less against the cap at signing. AI clubs use it for 35+ veterans when the cap is tight.
"""
from __future__ import annotations

import datetime
import random

from . import contracts as K

CUSHION = 0.075          # of the cap ceiling
PERF_VALUE = 0.6         # a dollar of bonus is worth this much guaranteed money to him
MAX_SHARE = 0.75         # at most this share of the deal's total value in bonuses
VET_AGE, INJ_GAMES, INJ_DAYS = 35, 400, 100
AI_P = 0.55              # an AI club tight against the cap turns part of a 35+ deal into bonuses this often


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS vet_bonus (contract_id INTEGER PRIMARY KEY, player_id INTEGER, team_id INTEGER, "
                 "season INTEGER, kind TEXT, max_amount INTEGER, earned INTEGER, parts TEXT)")


def _nhl_games(conn, pid):
    top = conn.execute("SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
    top = top[0] if top else 1
    n = 0
    for t in ("skater_season_stats", "goalie_season_stats"):
        n += conn.execute(f"SELECT COALESCE(SUM(gp), 0) FROM {t} WHERE player_id=? AND league_id=? AND split='RS'",
                          (pid, top)).fetchone()[0]
    return n


def _days_injured(conn, pid, season):
    """Days on the injury list in the season that ended before `season` (1 July to 30 June)."""
    a, b = datetime.date(season - 1, 7, 1), datetime.date(season, 6, 30)
    days = 0
    for s, e in conn.execute("SELECT start_date, expected_return FROM injuries WHERE player_id=?", (pid,)):
        try:
            s, e = datetime.date.fromisoformat(s[:10]), datetime.date.fromisoformat(e[:10])
        except (TypeError, ValueError):
            continue
        lo, hi = max(s, a), min(e, b)
        if hi > lo:
            days += (hi - lo).days
    return days


def eligible(conn, pid, years, season=None):
    """'35+', 'injured' or None: may a contract of `years` starting in `season` carry performance bonuses?"""
    if years != 1:
        return None
    season = K.signing_year(conn) if season is None else season
    r = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    if r and r[0] and K.age_on(r[0], datetime.date(season, 6, 30)) >= VET_AGE:
        return "35+"
    if _nhl_games(conn, pid) >= INJ_GAMES and _days_injured(conn, pid, season) >= INJ_DAYS:
        return "injured"
    return None


def pending(conn, team, season):
    """Bonuses a club could still owe for `season`: veterans' and entry-level maximums."""
    ensure_tables(conn)
    n = conn.execute("SELECT COALESCE(SUM(max_amount), 0) FROM vet_bonus WHERE team_id=? AND season=? AND earned IS NULL",
                     (team, season)).fetchone()[0]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='elc_terms'").fetchone():
        n += conn.execute("SELECT COALESCE(SUM(e.perf_max), 0) FROM elc_terms e JOIN contracts c USING (player_id) WHERE "
                          "c.team_id=? AND c.contract_type='entry_level' AND c.start_year<=? AND c.start_year+c.years>?",
                          (team, season, season)).fetchone()[0]
    return n


def check_cushion(conn, team, amount, season=None, base=0):
    """Raise RosterError unless the club's cap hit, its possible bonuses and this one fit under ceiling + cushion."""
    season = K.signing_year(conn) if season is None else season
    cap = K.crules(conn)["cap_ceiling"]
    if not cap:
        return
    room = cap * (1 + CUSHION) - K.payroll(conn, team, season) - base - pending(conn, team, season)
    if amount > room:
        raise K.RosterError(f"Performance bonuses can take you past the cap by the bonus cushion (7.5%, "
                            f"${cap * CUSHION:,.0f}) at most; there is ${max(0, room):,.0f} of it left.")


def record(conn, contract_id, kind, amount):
    ensure_tables(conn)
    c = conn.execute("SELECT player_id, team_id, start_year FROM contracts WHERE contract_id=?", (contract_id,)).fetchone()
    conn.execute("INSERT OR REPLACE INTO vet_bonus (contract_id, player_id, team_id, season, kind, max_amount) VALUES (?,?,?,?,?,?)",
                 (contract_id, c[0], c[1], c[2], kind, int(amount)))


def of_contract(conn, contract_id):
    ensure_tables(conn)
    r = conn.execute("SELECT kind, max_amount, earned, parts FROM vet_bonus WHERE contract_id=?", (contract_id,)).fetchone()
    return dict(kind=r[0], max=r[1], earned=r[2], parts=r[3]) if r else None


def ai_restructure(conn, pid, team, contract_id, rng=None):
    """An AI club against the cap turns part of a 35+ veteran's one-year deal into performance bonuses: the cap hit
    falls and the bonuses (worth less to him, so a little more of them) come out of the cushion."""
    c = conn.execute("SELECT * FROM contracts WHERE contract_id=?", (contract_id,)).fetchone()
    if c is None or c["years"] != 1:
        return None
    kind = eligible(conn, pid, 1, c["start_year"])
    if kind != "35+":
        return None
    rng = rng or random.Random(f"vet-{pid}-{contract_id}")
    cap = K.crules(conn)["cap_ceiling"]
    if not cap or K.cap_room(conn, team, c["start_year"]) > 0.04 * cap or rng.random() > AI_P:
        return None
    floor = K.crules(conn)["min_salary"]
    move = int(max(0, c["cap_hit"] - floor) * rng.uniform(0.3, 0.6) / 5000) * 5000
    if move < 250_000:
        return None
    bonus = int(move / PERF_VALUE * 0.85 / 5000) * 5000
    try:
        check_cushion(conn, team, bonus, c["start_year"], base=-move)
    except K.RosterError:
        return None
    conn.execute("UPDATE contracts SET cap_hit=cap_hit-? WHERE contract_id=?", (move, contract_id))
    from . import ledger as LG
    LG.write(conn, contract_id)
    record(conn, contract_id, kind, bonus)
    return bonus


def season_end(conn, season):
    """Score this season's veteran bonuses. Returns {team_id: earned}."""
    ensure_tables(conn)
    top = conn.execute("SELECT league_id, season_id FROM seasons WHERE start_year=?", (season,)).fetchone()
    if top is None:
        return {}
    lid, sid = top
    out = {}
    for b in conn.execute("SELECT * FROM vet_bonus WHERE season=? AND earned IS NULL", (season,)).fetchall():
        pid, team = b["player_id"], b["team_id"]
        pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()
        pos = pos[0] if pos else "F"
        po = bool(conn.execute("SELECT 1 FROM games WHERE season_id=? AND game_type='PO' AND (home_team_id=? OR away_team_id=?) LIMIT 1",
                               (sid, team, team)).fetchone())
        if pos == "G":
            gp, ga, sa = conn.execute("SELECT COALESCE(SUM(gp),0), COALESCE(SUM(ga),0), COALESCE(SUM(sa),0) FROM goalie_season_stats "
                                      "WHERE player_id=? AND season_start_year=? AND league_id=? AND split='RS'", (pid, season, lid)).fetchone()
            parts = [gp >= 10, gp >= 25, gp >= 10 and sa > 0 and 1 - ga / sa >= 0.905, po and gp > 0]
        else:
            gp, pts = conn.execute("SELECT COALESCE(SUM(gp),0), COALESCE(SUM(g+a),0) FROM skater_season_stats WHERE player_id=? AND "
                                   "season_start_year=? AND league_id=? AND split='RS'", (pid, season, lid)).fetchone()
            parts = [gp >= 10, gp >= 41, pts >= (15 if pos == "D" else 25), po and gp > 0]
        earned = int(b["max_amount"] * sum(1 for x in parts if x) / 4)
        conn.execute("UPDATE vet_bonus SET earned=?, parts=? WHERE contract_id=?",
                     (earned, "".join("1" if x else "0" for x in parts), b["contract_id"]))
        if earned:
            out[team] = out.get(team, 0) + earned
    return out
