"""Offer sheets: signing another club's restricted free agent, who keeps the right to match.

CBA mechanics (rules.json "contracts" -> "offer_sheet_comp"; the defaults are the 2025-26 thresholds as we recall
them, unverified for 2026, scaled each season by cap / $95.5M because the thresholds follow the league's average
salary):
  compensation by AAV, where AAV = total value / min(years, 5):
    up to $1.56M none · $2.36M a 3rd · $4.73M a 2nd · $7.09M a 1st and a 3rd · $9.46M a 1st, 2nd and 3rd ·
    $11.82M two 1sts, a 2nd and a 3rd · above that four 1sts
  the offering club must own its own picks in the drafts that pay the compensation (the next draft; consecutive
  drafts for multiple 1sts), have the cap room and a contract slot; the term is at most the maximum for new deals.
  The player's club decides within a week whether to match (same terms) or take the picks.

The offering club's model (from the design notes): P(not matched) from
  cap affordability   can the player's club fit the AAV after its other pending RFAs? If not, it almost cannot match
  compensation delta  if matching is worth less to the owner than the picks, it lets him go
  player premium      overpaying (the "poison pill") makes matching expensive
  owner spite / PR    a club matches a homegrown top-lineup player 20% of the time even when the numbers say no
  stars               a star (perceived 11.3+) is matched 95% of the time if he can be fitted (Weber, Aho, Sakic)
  clearing room       an owner up to $4M short who wants to match trades a lesser contract away to do it
Why sheets fail: the offering GM misjudges the owner (an error of sd 0.2 on its estimate; many forget the owner can
clear room), and in about a third of summers a win-now club gambles on a star at a "reasonable" AAV inside a high
bracket (the 2019 Aho sheet) and is matched. The smart sheets max out a bracket (Broberg 2024: the top dollar before
the next tier) or sit just over what a capped-out owner can fit.
It tries two structures for each target: the "cap leverage" sheet (just above what the owner can fit, as long as
it meets the player's RFA ask) and the "tier jump" sheet (just under a compensation threshold), and makes the one
with the best expected value P(not matched) x (its surplus on the deal + 15% a year for filling a top-lineup hole -
the picks' expected surplus: a 1st $6M, a 2nd $2M, a 3rd $0.8M), if that is positive and P >= 0.4.
Offer sheets are rare: about one in eight clubs looks each summer, at most two sheets are made.

You: `offersheet <player> <aav> <years>` during free agency (before 5 July). If an AI club sheets one of your RFAs,
you have until the arbitration phase to `match <player>`; otherwise he leaves and the picks are yours.
"""
from __future__ import annotations

import json
import random

from . import contracts as K
from . import roster as R
from . import valuation as V
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team
from ..schema import top_league_sql

COMP_DEFAULT = [[1_560_323, []], [2_363_895, [3]], [4_727_793, [2]], [7_091_688, [1, 3]], [9_455_585, [1, 2, 3]],
                [11_819_480, [1, 1, 2, 3]], [None, [1, 1, 1, 1]]]
COMP_CAP_BASE = 95_500_000
PICK_DOLLARS = {1: 6_000_000, 2: 2_000_000, 3: 800_000}        # surplus a club expects from each pick
NEED_PREMIUM = 0.15             # a club filling a top-lineup hole values him 15% a year above market
SPITE = 0.20
STAR_OV = 11.3                  # a star (Tier 1): matched 95% of the time if it can be fitted
STAR_MATCH = 0.95
CLEAR_ROOM_MAX = 4_000_000      # an owner up to $4M short will trade a lesser contract away to match
GM_ERROR_SD = 0.2               # how far an offering GM misjudges the chance the owner walks away
STAR_GAMBLE_P = 0.35            # chance a summer sees a win-now club sheet a star at a "reasonable" price
MIN_P = 0.4
AI_SHEETS_PER_SUMMER = 2
AI_ATTEMPT_P = 0.12
TARGET_GAIN = 0.3


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS offer_sheets (sheet_id INTEGER PRIMARY KEY, season INTEGER, "
                 "player_id INTEGER, from_team INTEGER, owner_team INTEGER, aav INTEGER, years INTEGER, comp TEXT, "
                 "status TEXT, made_on TEXT, note TEXT)")


def comp_table(conn):
    cr = K.crules(conn)
    table = cr.get("offer_sheet_comp") or COMP_DEFAULT
    f = (cr["cap_ceiling"] or COMP_CAP_BASE) / COMP_CAP_BASE
    return [[None if lim is None else int(lim * f), rounds] for lim, rounds in table]


def compensation(conn, aav, years):
    basis = aav * years / min(years, 5)
    for lim, rounds in comp_table(conn):
        if lim is None or basis <= lim:
            return list(rounds)
    return [1, 1, 1, 1]


def comp_dollars(rounds):
    return sum(PICK_DOLLARS[r] for r in rounds)


def comp_picks(conn, club, rounds):
    """The concrete picks: (draft year, round, original club) — own picks, consecutive drafts for repeated 1sts."""
    from .draft import draft_year
    first = draft_year(conn)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_picks'").fetchone() and \
            conn.execute("SELECT 1 FROM draft_picks WHERE draft_year=?", (first,)).fetchone():
        first += 1                                       # this summer's draft is done
    out, k1 = [], 0
    for r in rounds:
        if r == 1:
            out.append((first + k1, 1, club))
            k1 += 1
        else:
            out.append((first, r, club))
    return out


def owns_picks(conn, club, picks):
    from .trades import ensure_tables as tt, pick_owner
    tt(conn)
    return all(pick_owner(conn, y, r, o) == club for y, r, o in picks)


def describe(rounds):
    if not rounds:
        return "no compensation"
    nth = {1: "1st", 2: "2nd", 3: "3rd"}
    ones = rounds.count(1)
    parts = ([f"{ones} 1sts" if ones > 1 else "a 1st"] if ones else []) + [f"a {nth[r]}" for r in rounds if r != 1]
    return ", ".join(parts)


def _pending_rfa(conn, pid):
    year = K.season_year(conn)
    return conn.execute("SELECT * FROM offseason_rights WHERE season_start_year=? AND player_id=? AND status='RFA' AND "
                        "COALESCE(qualified, 1)=1 AND outcome IS NULL", (year, pid)).fetchone()


def _owner_room(conn, owner, pid):
    year = K.signing_year(conn)
    room = K.cap_room(conn, owner, year)
    if room is None:
        return 1e12
    own = max((_pending_rfa(conn, pid) or {"qo": 0})["qo"] or 0, K.asking(conn, pid, "RFA"))
    return room - (K.pending_rfa_cost(conn, owner) - own)


def _top_lineup(conn, owner, pid, m):
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = R.group(pos)
    vals = sorted((V.overall_of_value(m.values.value(r["player_id"])) for r in R.roster(conn, owner)
                   if R.group(r["position"]) == g), reverse=True)
    n = {"F": 6, "D": 4, "G": 1}[g]
    return len(vals) < n or V.overall_of_value(m.values.value(pid)) >= vals[n - 1]


def _star(conn, pid, m):
    return V.overall_of_value(m.values.value(pid)) >= STAR_OV


def owner_matches(conn, owner, pid, aav, years, rng, m=None):
    """Does the player's club match? (AI owners.) Returns (matched, reason, player traded away to clear room)."""
    m = m or V.market(conn)
    rounds = compensation(conn, aav, years)
    ev = V.evaluate(conn, pid, aav, years, K.signing_year(conn), sims=50, m=m)
    star = _star(conn, pid, m)
    if star:
        wants = rng.random() < STAR_MATCH                 # losing a star for picks ruins franchises (Weber, Aho)
        why = "matched: a star is not let go for picks"
    elif ev["surplus"] + comp_dollars(rounds) >= 0:
        wants, why = True, "matched: worth keeping at that price"
    elif _top_lineup(conn, owner, pid, m) and rng.random() < SPITE:
        wants, why = True, "matched out of pride (a homegrown top player)"
    else:
        return False, f"took the picks ({describe(rounds)}) rather than pay that", None
    short = aav - _owner_room(conn, owner, pid)
    if short <= 0:
        return wants, why, None
    if wants and short <= CLEAR_ROOM_MAX:                 # cannibalise the roster to keep him
        cleared = _clear_room(conn, owner, short, pid, m)
        if cleared:
            return True, why + f", clearing room by moving {player_name(conn, cleared)}", cleared
    return False, "could not fit the cap hit", None


def _clear_room(conn, owner, need, keep, m):
    """Trade away the club's least valuable veteran depth contract that covers `need` to a club with room, for nothing."""
    year = K.signing_year(conn)
    cands = []
    for r in R.roster(conn, owner):
        pid = r["player_id"]
        c = K.current_contract(conn, pid, year)
        if pid == keep or c is None or c["no_trade"] or c["cap_hit"] < need or c["contract_type"] == "entry_level":
            continue
        birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        if V._age(birth, year) <= 23 or _top_lineup(conn, owner, pid, m):
            continue                                       # not the kids, not the core: a veteran depth contract
        cands.append((m.values.value(pid) / max(c["cap_hit"], 1), pid, c["cap_hit"]))
    for _, pid, hit in sorted(cands):
        takers = [t for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} AND team_id<>?",
                                             (owner,)) if t != user_team(conn)
                  and (K.cap_room(conn, t, year) or 0) - K.pending_rfa_cost(conn, t) >= hit + 2_000_000]
        for t in sorted(takers, key=lambda t: -(K.cap_room(conn, t, year) or 0)):
            conn.execute("SAVEPOINT clear")
            try:
                R.trade(conn, owner, [pid], t, [], K.today(conn))
                conn.execute("RELEASE clear")
                return pid
            except R.RosterError:
                conn.execute("ROLLBACK TO clear")
                conn.execute("RELEASE clear")
    return None


def p_not_matched(conn, owner, pid, aav, years, m, gm_error=0.0):
    """The offering club's estimate (with its GM's misjudgement)."""
    star = _star(conn, pid, m)
    short = aav - _owner_room(conn, owner, pid)
    if star:
        p = 0.3 if short > CLEAR_ROOM_MAX else 0.1
    elif short > 0:
        p = 0.9                                         # many GMs forget the owner can clear room
    else:
        ev = V.evaluate(conn, pid, aav, years, K.signing_year(conn), sims=30, m=m)
        if ev["surplus"] + comp_dollars(compensation(conn, aav, years)) >= 0:
            p = 0.1
        else:
            p = 1 - SPITE * (1 if _top_lineup(conn, owner, pid, m) else 0.3)
    return max(0.0, min(1.0, p + gm_error))


def validate(conn, club, pid, aav, years):
    cr = K.crules(conn)
    r = _pending_rfa(conn, pid)
    if r is None:
        raise ValueError("Offer sheets go to qualified restricted free agents who have not signed.")
    if r["team_id"] == club:
        raise ValueError("He is your own RFA.")
    if not 1 <= years <= cr["max_term_new"]:
        raise ValueError(f"Term must be 1-{cr['max_term_new']} years.")
    if aav < max(cr["min_salary"], r["qo"] or 0):
        raise ValueError("An offer sheet must at least match his qualifying offer.")
    if cr["cap_ceiling"] and aav > cr["max_salary_pct"] * cr["cap_ceiling"]:
        raise ValueError("Above the maximum salary.")
    K.check_cap(conn, club, aav, K.signing_year(conn), what="The offer sheet")
    K.check_contract_limit(conn, club, K.signing_year(conn))
    rounds = compensation(conn, aav, years)
    picks = comp_picks(conn, club, rounds)
    if not owns_picks(conn, club, picks):
        raise ValueError(f"The compensation would be {describe(rounds)} and you do not own all of those picks.")
    return r, rounds, picks


def _record(conn, pid, club, owner, aav, years, rounds, status, day, note):
    ensure_tables(conn)
    conn.execute("INSERT INTO offer_sheets (season, player_id, from_team, owner_team, aav, years, comp, status, made_on, "
                 "note) VALUES (?,?,?,?,?,?,?,?,?,?)", (K.season_year(conn), pid, club, owner, aav, years,
                                                         json.dumps(rounds), status, day, note))


def _complete(conn, pid, club, owner, aav, years, rounds, day, matched, note):
    year = K.season_year(conn)
    if matched:
        K.sign_contract(conn, pid, owner, years, aav, day, start_year=year + 1, resign=True,
                        detail="matched an offer sheet", check=False)
        outcome = "matched an offer sheet"
    else:
        picks = comp_picks(conn, club, rounds)
        R._release(conn, owner, pid, day, f"signed an offer sheet with {team_abbr(conn, club)}")
        K.sign_contract(conn, pid, club, years, aav, day, start_year=year + 1, resign=False,
                        detail=f"signed an offer sheet (from {team_abbr(conn, owner)})", check=False)
        for y, r, o in picks:
            conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                         (y, r, o, owner, f"offer sheet compensation {day}"))
        outcome = f"left on an offer sheet ({team_abbr(conn, club)})"
    conn.execute("UPDATE offseason_rights SET outcome=? WHERE season_start_year=? AND player_id=?", (outcome, year, pid))
    text = (f"{team_abbr(conn, club)} sign {team_abbr(conn, owner)} RFA {player_name(conn, pid)} to an offer sheet "
            f"({years} yr x ${aav / 1e6:.2f}M, compensation {describe(rounds)}): "
            + (f"{team_abbr(conn, owner)} match" if matched else f"{team_abbr(conn, owner)} take the picks")
            + (f" ({note})" if note else ""))
    emit(conn, "TRADE_COMPLETED", day, text, team_id=club, other_team_id=owner, player_id=pid, importance=3,
         kind="offer_sheet", matched=matched, comp=rounds, aav=aav, years=years)
    return text


def make(conn, club, pid, aav, years, day, rng=None):
    """An offer sheet from `club`. AI owners decide at once; the user's club decides by the arbitration phase."""
    if K.season_state(conn) != "free_agency":
        raise ValueError("Offer sheets are made once free agency opens (the free_agency phase).")
    r, rounds, picks = validate(conn, club, pid, aav, years)
    owner = r["team_id"]
    rng = rng or random.Random(f"{get_state(conn)[1]}-{day}-sheet-{pid}")
    if owner == user_team(conn):
        _record(conn, pid, club, owner, aav, years, rounds, "pending", day, "")
        conn.execute("UPDATE offseason_rights SET decided_by='offer sheet pending' WHERE season_start_year=? AND "
                     "player_id=?", (K.season_year(conn), pid))
        add_message(conn, day, "Offer sheet", f"{team_abbr(conn, club)} have signed {player_name(conn, pid)} to an offer "
                    f"sheet: {years} yr x ${aav:,.0f}. Match it with `match {pid}` before the arbitration phase, or "
                    f"let him go for {describe(rounds)}.")
        return f"{player_name(conn, pid)} signed {team_abbr(conn, club)}'s offer sheet; you have until 5 July to match."
    matched, note, _cleared = owner_matches(conn, owner, pid, aav, years, rng)
    _record(conn, pid, club, owner, aav, years, rounds, "matched" if matched else "accepted", day, note)
    return _complete(conn, pid, club, owner, aav, years, rounds, day, matched, note)


def match(conn, me, pid, day):
    ensure_tables(conn)
    s = conn.execute("SELECT * FROM offer_sheets WHERE player_id=? AND owner_team=? AND status='pending'",
                     (pid, me)).fetchone()
    if s is None:
        raise ValueError("No pending offer sheet for that player.")
    K.check_cap(conn, me, s["aav"], K.signing_year(conn), what="Matching")
    conn.execute("UPDATE offer_sheets SET status='matched' WHERE sheet_id=?", (s["sheet_id"],))
    return _complete(conn, pid, s["from_team"], me, s["aav"], s["years"], json.loads(s["comp"]), day, True,
                     "you matched")


def resolve_pending(conn, day):
    """Entering the arbitration phase: sheets the user did not match go through."""
    ensure_tables(conn)
    out = []
    for s in conn.execute("SELECT * FROM offer_sheets WHERE status='pending'").fetchall():
        conn.execute("UPDATE offer_sheets SET status='accepted' WHERE sheet_id=?", (s["sheet_id"],))
        out.append(_complete(conn, s["player_id"], s["from_team"], s["owner_team"], s["aav"], s["years"],
                             json.loads(s["comp"]), day, False, "not matched"))
    return out


def ai_offer_sheets(conn, day):
    """AI clubs look for RFAs worth an offer sheet (rarely). Returns lines."""
    ensure_tables(conn)
    me = user_team(conn)
    year = K.signing_year(conn)
    m = V.market(conn)
    rng = random.Random(f"{get_state(conn)[1]}-{year}-offersheets")
    rfas = [r for r in conn.execute("SELECT * FROM offseason_rights WHERE season_start_year=? AND status='RFA' AND "
                                    "COALESCE(qualified, 1)=1 AND outcome IS NULL", (K.season_year(conn),)).fetchall()]
    infos = []
    for r in rfas:
        ov = V.overall_of_value(m.values.value(r["player_id"]))
        birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (r["player_id"],)).fetchone()[0]
        if ov >= 10.5 and V._age(birth, year) <= 26:
            infos.append((r, ov))
    clubs = [t for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")
             if t != me]
    rng.shuffle(clubs)
    made = []
    for club in clubs:
        if len(made) >= AI_SHEETS_PER_SUMMER or rng.random() > AI_ATTEMPT_P:
            continue
        room = (K.cap_room(conn, club, year) or 0) - K.pending_rfa_cost(conn, club)
        gm_err = rng.gauss(0, GM_ERROR_SD)            # this GM's read of how the owner will react
        lineup = {}
        for r in R.roster(conn, club):
            lineup.setdefault(R.group(r["position"]), []).append(V.overall_of_value(m.values.value(r["player_id"])))
        best = None
        for r, ov in infos:
            if r["team_id"] == club or r["outcome"]:
                continue
            pid = r["player_id"]
            pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            g = R.group(pos)
            have = sorted(lineup.get(g, []), reverse=True)
            n = {"F": 6, "D": 4, "G": 1}[g]
            cut = have[n - 1] if len(have) >= n else 9.0
            if ov - cut < TARGET_GAIN:
                continue
            years = min(5, K.crules(conn)["max_term_new"])          # five years walks him to unrestricted status
            fair = V.fair_aav(conn, pid, years, year, m)
            owner_room = _owner_room(conn, r["team_id"], pid)
            options = [int(owner_room) + 250_000]                       # cap leverage
            for lim, _ in comp_table(conn):                             # tier jump
                if lim is not None and 0.85 * fair <= lim <= 1.25 * fair:
                    options.append(lim - 1)
            for aav in options:
                aav = int(round(aav / 1000) * 1000)
                floor = max(r["qo"] or 0, K.asking(conn, pid, "RFA"))     # he signs at his RFA ask or better
                if not floor <= aav <= 1.3 * fair or aav > room:
                    continue
                rounds = compensation(conn, aav, years)
                if not owns_picks(conn, club, comp_picks(conn, club, rounds)):
                    continue
                p = p_not_matched(conn, r["team_id"], pid, aav, years, m, gm_err)
                gain = (V.evaluate(conn, pid, aav, years, year, sims=30, m=m)["surplus"] + NEED_PREMIUM * fair * years
                        - comp_dollars(rounds))
                ev = p * gain
                if p >= MIN_P and ev > 0 and (best is None or ev > best[0]):
                    best = (ev, pid, aav, years)
        if best:
            _, pid, aav, years = best
            try:
                made.append(make(conn, club, pid, aav, years, day, rng))
            except (ValueError, K.RosterError):
                continue
            infos = [(r, ov) for r, ov in infos if r["player_id"] != pid]
    # the Aho mistake: a win-now club sheets a star at a "reasonable" AAV inside a high bracket; usually matched
    if len(made) < AI_SHEETS_PER_SUMMER and rng.random() < STAR_GAMBLE_P:
        stars = [(r, ov) for r, ov in infos if ov >= STAR_OV and not r["outcome"]]
        from .trades import posture, standings_rank
        rank = standings_rank(conn)
        bold = [t for t in clubs if posture(rank.get(t, 16), len(rank)) == "contender"]
        rng.shuffle(bold)
        for r, ov in stars[:3]:
            for club in bold:
                if club == r["team_id"]:
                    continue
                years = min(5, K.crules(conn)["max_term_new"])
                aav = int(round(V.fair_aav(conn, r["player_id"], years, year, m) * 1.05 / 1000) * 1000)
                try:
                    made.append(make(conn, club, r["player_id"], aav, years, day, rng))
                    break
                except (ValueError, K.RosterError):
                    continue
            else:
                continue
            break
    return made


def sheets(conn, season=None):
    ensure_tables(conn)
    season = season or K.season_year(conn)
    return conn.execute("SELECT * FROM offer_sheets WHERE season=? ORDER BY sheet_id", (season,)).fetchall()
