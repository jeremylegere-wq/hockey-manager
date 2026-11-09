"""Entry-level contract details: signing and performance bonuses, the slide rule, and college picks who will not sign.

Signing bonus and performance bonuses (negotiated when the ELC is signed; settings below)
  P(maximum signing bonus): top-10 pick with leverage 0.95, top-10 without 0.5, picks 11-32 0.25 / 0.1, later 0.02.
  Leverage = an alternative the club fears: college (he can stay in school), a European pro club, the KHL.
  The maximum signing bonus is 10% of his total pay; it sits inside the cap hit (AAV).
  Schedule A performance bonuses (up to $850,000 a season): top-10 picks get the maximum, picks 11-32 half, a
  quarter with leverage in rounds 2-3, none later. They are earned at season end, four equal parts:
    forwards  20 goals · 35 assists · 60 points · 0.73 points a game (42+ games)
    defence   10 goals · 28 assists · 40 points · 20 minutes a game (42+ games)
    goalies   25 games · .910 save % · 22 wins · under 2.75 goals against a game
  Earned bonuses that push a club past the cap become a bonus overage charge on next season's cap.

Slide rule: a player 18 or 19 (on 15 September) who plays fewer than 10 NHL games in a season does not use up
that ELC year: the contract slides a year (at most twice). Sliding pushes back when he becomes an RFA.

College picks who refuse to sign (the NCAA route to free agency): when a college player's rights are about to
lapse (his senior year), the club wants him and he can walk, he refuses with probability
  P = 1 / (1 + e^-(b0 + b1 x congestion + b2 x pipeline - b3 x draft-slot value - b4 x stability + b5 x leverage))
  congestion  NHL players at his position under contract for two more seasons who are better than him (0-1)
  pipeline    the club's prospects 23 and under at his position, against what it wants (0-1)
  slot value  the pick value chart (pick 1 = 1, a 7th-rounder ~0.01)
  stability   the board's confidence in the front office (0-1)
  leverage    1 for a college senior
A club whose pick refuses trades his rights while it can (a 3rd for a first-rounder or second-rounder, otherwise
a 5th) to a club that needs him at his position (pipeline need 0.3+, half of them willing), where he signs; otherwise he walks and becomes a free agent.
"""
from __future__ import annotations

import datetime
import math
import random

from . import contracts as K
from . import roster as R
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

PERF_MAX = 850_000
MAX_BONUS_P = {"top10_lev": 0.95, "top10": 0.5, "r1_lev": 0.25, "r1": 0.10, "late": 0.02}
B0, B_CONG, B_PIPE, B_SLOT, B_STAB, B_LEV = -2.5, 1.5, 1.0, 2.0, 1.0, 1.0
SLIDE_GAMES, MAX_SLIDES = 10, 2
RIGHTS_NEED, RIGHTS_DEAL_P = 0.3, 0.5     # who will trade for a refusing pick's rights


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS elc_terms (player_id INTEGER PRIMARY KEY, signed_year INTEGER, "
                 "signing_bonus INTEGER, perf_max INTEGER, slides INTEGER DEFAULT 0, leverage TEXT, "
                 "earned_total INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS elc_bonus_log (player_id INTEGER, season INTEGER, earned INTEGER, "
                 "parts TEXT, PRIMARY KEY (player_id, season))")


def leverage(conn, pid):
    from .world import world_meta
    r = conn.execute("SELECT t.league_id, p.nationality FROM players p LEFT JOIN teams t ON t.team_id=p.club_id "
                     "WHERE p.player_id=?", (pid,)).fetchone()
    meta = world_meta(conn).get(r[0] if r else None, {})
    if meta.get("kind") == "college":
        return "college"
    if meta.get("abbr") == "KHL":
        return "KHL"
    if meta.get("kind") == "europe":
        return "Europe"
    return ""


def negotiate(conn, pid, pick, total_aav, years, rng=None):
    """(signing bonus per year, performance bonus max per season, leverage)."""
    rng = rng or random.Random(f"{get_state(conn)[1]}-elc-{pid}")
    lev = leverage(conn, pid)
    pick = pick or 999
    key = ("top10" if pick <= 10 else "r1" if pick <= 32 else "late") + ("_lev" if lev and pick <= 32 else "")
    p_max = MAX_BONUS_P.get(key, MAX_BONUS_P["late"])
    share = 0.10 if rng.random() < p_max else (0.05 if pick <= 32 and rng.random() < 0.5 else 0.0)
    bonus = int(round(total_aav * share / 5000) * 5000)
    perf = PERF_MAX if pick <= 10 else PERF_MAX // 2 if pick <= 32 else PERF_MAX // 4 if (lev and pick <= 96) else 0
    return bonus, perf, lev


def record(conn, pid, year, bonus, perf, lev):
    ensure_tables(conn)
    conn.execute("INSERT OR REPLACE INTO elc_terms (player_id, signed_year, signing_bonus, perf_max, slides, leverage, "
                 "earned_total) VALUES (?,?,?,?,0,?,0)", (pid, year, bonus, perf, lev))


def _elc_rows(conn, season):
    return conn.execute("SELECT c.*, e.perf_max, e.slides FROM contracts c JOIN elc_terms e USING (player_id) WHERE "
                        "c.contract_type='entry_level' AND c.start_year<=? AND c.start_year+c.years>?",
                        (season, season)).fetchall()


def season_end(conn, season, day):
    """Performance bonuses and slides for the season just finished. Returns summary lines."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='elc_terms'").fetchone():
        return []
    top = conn.execute("SELECT league_id FROM seasons WHERE start_year=?", (season,)).fetchone()
    top = top[0] if top else 1
    earned_by_team, slid, paid = {}, 0, 0
    for c in _elc_rows(conn, season):
        pid = c["player_id"]
        pos = conn.execute("SELECT position, birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
        sk = conn.execute("SELECT SUM(gp), SUM(g), SUM(a), SUM(toi_sec) FROM skater_season_stats WHERE player_id=? AND "
                          "season_start_year=? AND league_id=? AND split='RS'", (pid, season, top)).fetchone()
        gl = conn.execute("SELECT SUM(gp), SUM(w), SUM(ga), SUM(sa) FROM goalie_season_stats WHERE player_id=? AND "
                          "season_start_year=? AND league_id=? AND split='RS'", (pid, season, top)).fetchone()
        gp = (sk[0] or 0) + (gl[0] or 0)
        # slide rule
        age = K.age_on(pos["birth_date"], datetime.date(season, 9, 15))
        if c["start_year"] == season and age <= 19 and gp < SLIDE_GAMES and (c["slides"] or 0) < MAX_SLIDES:
            conn.execute("UPDATE contracts SET start_year=start_year+1 WHERE contract_id=?", (c["contract_id"],))
            conn.execute("UPDATE elc_terms SET slides=slides+1 WHERE player_id=?", (pid,))
            slid += 1
            continue
        if not c["perf_max"] or gp == 0:
            continue
        parts = []
        if pos["position"] == "G":
            ga, sa, w = gl[2] or 0, gl[3] or 0, gl[1] or 0
            parts = [gp >= 25, sa and 1 - ga / sa >= 0.910, w >= 22, gp and ga / gp < 2.75]
        else:
            g, a = sk[1] or 0, sk[2] or 0
            if pos["position"] == "D":
                parts = [g >= 10, a >= 28, g + a >= 40, gp >= 42 and (sk[3] or 0) / gp >= 1200]
            else:
                parts = [g >= 20, a >= 35, g + a >= 60, gp >= 42 and (g + a) / gp >= 0.73]
        n = sum(1 for x in parts if x)
        if not n:
            continue
        earned = int(c["perf_max"] * n / 4)
        conn.execute("INSERT OR REPLACE INTO elc_bonus_log VALUES (?,?,?,?)", (pid, season, earned,
                                                                              "".join("1" if x else "0" for x in parts)))
        conn.execute("UPDATE elc_terms SET earned_total=earned_total+? WHERE player_id=?", (earned, pid))
        earned_by_team[c["team_id"]] = earned_by_team.get(c["team_id"], 0) + earned
        paid += earned
    cap = K.crules(conn)["cap_ceiling"]
    overages = 0
    for t, earned in earned_by_team.items():
        if cap is None:
            continue
        over = K.payroll(conn, t, season) + earned - cap
        if over > 0:
            amount = min(over, earned)
            conn.execute("INSERT INTO cap_charges (team_id, season_start_year, amount, reason) VALUES (?,?,?,?)",
                         (t, season + 1, amount, "bonus overage"))
            overages += 1
    lines = []
    if paid or slid:
        lines.append(f"Entry-level contracts: ${paid:,.0f} in performance bonuses earned"
                     + (f" ({overages} clubs carry a bonus overage into next season)" if overages else "")
                     + f"; {slid} contracts slid a year (under 10 NHL games at 18-19).")
    return lines


# ---------------------------------------------------------------- college picks who will not sign

def _sigmoid(x):
    return 1 / (1 + math.exp(-x))


def refusal_probability(conn, team, pid, pick):
    from .draft_floor import chart
    from .valuation import overall_of_value
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = R.group(pos)
    me_ov = overall_of_value(R.player_value(conn, pid))
    year = K.signing_year(conn)
    ahead = 0
    for r in R.roster(conn, team):
        if R.group(r["position"]) != g:
            continue
        c = K.current_contract(conn, r["player_id"], year + 1)
        if c and overall_of_value(R.player_value(conn, r["player_id"])) > me_ov:
            ahead += 1
    target = {"F": 9, "D": 6, "G": 2}[g]
    congestion = min(1.0, ahead / target)
    from .scouting import needs
    pipeline = 1.0 - needs(conn, team, year).get(g, 0.5)
    slot = chart(pick or 224) / 1000.0
    stability = 0.6
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone():
        b = conn.execute("SELECT confidence FROM board WHERE team_id=?", (team,)).fetchone()
        stability = (b[0] / 100.0) if b else 0.6
    x = B0 + B_CONG * congestion + B_PIPE * pipeline - B_SLOT * slot - B_STAB * stability + B_LEV * 1.0
    return _sigmoid(x), dict(congestion=round(congestion, 2), pipeline=round(pipeline, 2), slot=round(slot, 3),
                             stability=round(stability, 2))


def college_refusals(conn, rows, day, wants):
    """rows: draft_rights rows of college players whose rights lapse now; wants(row) -> the club wants to sign him.
    Returns (set of player ids handled, lines)."""
    from .trades import ensure_tables as tt, pick_owner
    tt(conn)
    me = user_team(conn)
    done, lines = set(), []
    for r in rows:
        if not wants(r):
            continue
        pid, team = r["player_id"], r["team_id"]
        p, why = refusal_probability(conn, team, pid, r["overall_pick"])
        if random.Random(f"{get_state(conn)[1]}-refuse-{pid}").random() >= p:
            continue
        done.add(pid)
        name = player_name(conn, pid)
        new = _rights_trade(conn, team, pid, r, day) if team != me else None
        if new:
            lines.append(f"{name} would not sign with {team_abbr(conn, team)}; his rights went to "
                         f"{team_abbr(conn, new[0])} for a {new[1]}")
            continue
        conn.execute("DELETE FROM draft_rights WHERE player_id=?", (pid,))
        conn.execute("UPDATE players SET team_id=NULL, club_id=NULL, status='active' WHERE player_id=?", (pid,))
        emit(conn, "PLAYER_RELEASED", day, f"{name} refuses to sign with {team_abbr(conn, team)} and will become a free "
             "agent (college route)", team_id=team, player_id=pid, importance=2, kind="college_walk",
             p_refusal=round(p, 2), **why)
        if team == me:
            add_message(conn, day, "Prospect refuses to sign", f"{name} has told us he will not sign and will become "
                        f"a free agent ({int(p * 100)}% risk: crowded at his position {why['congestion']}, pipeline "
                        f"{why['pipeline']}). Next time, shop his rights first with `shoprights {pid}`.")
        lines.append(f"{name} walks away from {team_abbr(conn, team)} to free agency")
    return done, lines


def warn_user(conn, day):
    """A year ahead: tell the user which of their college picks might refuse to sign."""
    me = user_team(conn)
    year = K.signing_year(conn)
    for r in conn.execute("SELECT * FROM draft_rights WHERE team_id=? AND expires_year=?", (me, year + 1)).fetchall():
        if leverage(conn, r["player_id"]) != "college":
            continue
        p, why = refusal_probability(conn, me, r["player_id"], r["overall_pick"])
        if p >= 0.25:
            add_message(conn, day, "College pick may not sign",
                        f"{player_name(conn, r['player_id'])} has one college season left and there is a "
                        f"{int(p * 100)}% chance he refuses to sign next summer (crowded at his position "
                        f"{why['congestion']}, our pipeline {why['pipeline']}). Sign him now with `elc "
                        f"{r['player_id']}` or move his rights with `shoprights {r['player_id']}`.")


def _rights_trade(conn, team, pid, r, day, to=None):
    """Move a refusing pick's rights to a club with room at his position, for a late pick; he signs there."""
    from .draft import draft_year, sign_elc
    from .trades import pick_owner
    me = user_team(conn)
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = R.group(pos)
    rnd = 3 if (r["overall_pick"] or 999) <= 64 else 5
    year = draft_year(conn) + 1
    from .scouting import needs
    clubs = [t for (t,) in conn.execute("SELECT DISTINCT team_id FROM contracts") if t not in (team, me)] if to is None \
        else [to]
    if to is None:                    # only a club that needs him at his position, and half of those will deal
        rng = random.Random(f"{get_state(conn)[1]}-rights-{pid}")
        nd = {t: needs(conn, t, K.signing_year(conn)).get(g, 0) for t in clubs}
        clubs = [t for t in sorted(clubs, key=lambda t: -nd[t]) if nd[t] >= RIGHTS_NEED and rng.random() < RIGHTS_DEAL_P]
    for t in clubs:
        if pick_owner(conn, year, rnd, t) != t:
            continue
        conn.execute("SAVEPOINT rights")
        try:
            conn.execute("UPDATE draft_rights SET team_id=? WHERE player_id=?", (t, pid))
            if t != me:
                sign_elc(conn, pid, t, day)
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                         (year, rnd, t, team, f"rights trade {day}"))
            conn.execute("RELEASE rights")
        except (ValueError, K.RosterError):
            conn.execute("ROLLBACK TO rights")
            conn.execute("RELEASE rights")
            continue
        nth = {3: "3rd", 5: "5th"}[rnd]
        emit(conn, "TRADE_COMPLETED", day, f"{team_abbr(conn, team)} trade the rights to {player_name(conn, pid)} "
             f"(who would not sign) to {team_abbr(conn, t)} for a {year} {nth}", team_id=team, other_team_id=t,
             player_id=pid, importance=2, kind="rights_trade")
        return t, f"{year} {nth}"
    return None


def shop_rights(conn, me, pid, day):
    """The user moves a drafted player's rights for a late pick (e.g. a college senior who will not sign)."""
    r = conn.execute("SELECT * FROM draft_rights WHERE player_id=? AND team_id=?", (pid, me)).fetchone()
    if r is None:
        raise ValueError("You do not hold that player's rights.")
    out = _rights_trade(conn, me, pid, r, day)
    if out is None:
        raise ValueError("No club will give a pick for his rights right now.")
    return f"{player_name(conn, pid)}'s rights go to {team_abbr(conn, out[0])} for a {out[1]}."
