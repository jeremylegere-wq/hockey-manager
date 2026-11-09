"""The offseason: expiring contracts, qualifying offers, free agency, arbitration, and the start of the next season.

Phases (pack_info 'season_state'), each entered with `advance(conn, env, skill)`:
  finished      playoffs done (set by dayloop.finish_season)
  rights        25 Jun  expiring contracts listed as RFA/UFA. AI clubs decide qualifying offers and re-sign some
                        UFAs. The user decides for his own players (qualify / decline / extend); undecided RFAs are
                        qualified by default when the phase ends, undecided UFAs go to market.
  free_agency   1 Jul   unqualified RFAs and unsigned UFAs become free agents; AI clubs sign; the user may sign.
  arbitration   5 Jul   qualified RFAs choose: accept the QO, file for arbitration (if eligible) or settle on a
                        2-year deal halfway between QO and asking price. The user may settle (extend) or elect
                        club arbitration (once per player career) before the hearing.
  awards        1 Aug   hearings decided; AI clubs may walk away from large player-elected awards; the user may too.
  preseason     15 Sep  awards signed, walked-away players freed, AI clubs fill rosters.
  regular_season        next season created: new season row, schedule (dates shifted by whole years), clock set.
Not yet modelled: offer sheets, entry draft, ageing/progression, retirements, Group 6 UFAs, signing bonuses,
bidding between clubs for the same free agent (the first interested club in a seeded order gets him).
"""
from __future__ import annotations

from ..schema import top_league_sql

import datetime
import json
import random

from ..league.season import create_schedule, db_rules
from . import arbitration as A
from . import contracts as K
from . import roster as R
from .state import add_message, get_state, user_team

ORDER = ["finished", "draft", "rights", "free_agency", "arbitration", "awards", "preseason", "regular_season"]
PHASE_DAY = {"draft": (6, 26), "rights": (6, 29), "free_agency": (7, 1), "arbitration": (7, 5), "awards": (8, 1), "preseason": (9, 15)}
TARGET_ROSTER = 23


def _set_state(conn, state, day=None):
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('season_state', ?)", (state,))
    if day:
        conn.execute('UPDATE game_state SET "current_date"=? WHERE id=1', (day,))


def _rng(conn, phase):
    seed = get_state(conn)[1]
    return random.Random(f"{seed}-{K.season_year(conn)}-{phase}")


def _name(conn, pid):
    return conn.execute("SELECT first_name||' '||last_name n FROM players WHERE player_id=?", (pid,)).fetchone()["n"]


def _log(conn, day, typ, pid, frm, to, detail):
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                 "VALUES (?,?,?,?,?,?)", (day, typ, pid, frm, to, detail))


def offseason_calendar_year(conn):
    """Calendar year of the summer after the current season (from the season's own end date)."""
    r = conn.execute("SELECT start_year, end_date FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
    return int(r["end_date"][:4]) if r["end_date"] else r["start_year"] + 1


def rights_rows(conn, team_id=None):
    year = K.season_year(conn)
    q = "SELECT * FROM offseason_rights WHERE season_start_year=?" + (" AND team_id=?" if team_id else "")
    return conn.execute(q + " ORDER BY team_id, player_id", (year, team_id) if team_id else (year,)).fetchall()


def advance(conn, env, skill):
    """Move to the next offseason phase. Returns a list of summary lines for the user."""
    state = K.season_state(conn)
    if state not in ORDER[:-1]:
        raise ValueError("The offseason starts once the playoffs are over.")
    nxt = ORDER[ORDER.index(state) + 1]
    pre = []
    if state == "free_agency":
        pre = finish_live_auction(conn)
    if nxt == "regular_season":
        lines = _start_next_season(conn)
        from . import pto as PTO                          # v39: the head coach's camp reports on your tryouts
        lines += PTO.camp_reports(conn, get_state(conn)[0])
        from . import exhibitions as EX                   # v37: the pre-season games, dated before opening night
        lines += EX.play_preseason(conn, env, skill)
    else:
        mo, d = PHASE_DAY[nxt]
        day = datetime.date(offseason_calendar_year(conn), mo, d).isoformat()
        _set_state(conn, nxt, day)
        lines = {"draft": _enter_draft, "rights": _enter_rights, "free_agency": _enter_free_agency, "arbitration": _enter_arbitration,
                 "awards": _enter_awards, "preseason": _enter_preseason}[nxt](conn, day)
        if nxt == "rights":                               # v37: the Hall of Fame vote
            from . import legacy
            lines += legacy.election(conn, day)
        elif nxt == "preseason":                          # v37: the prospects tournaments of mid-September
            from . import troles as TR                    # v55: the AI clubs' tactical roles for the new roster
            TR.ai_assign(conn)
            from . import arena as AR                     # v57: new arenas open for the new season
            AR.on_preseason(conn, day)
            from . import exhibitions as EX
            lines += EX.prospects_tournaments(conn, env, skill, day)
    from . import numbers as NUM                          # v49: numbers for newcomers, clashes after the summer's moves
    NUM.fix(conn, get_state(conn)[0])
    try:                                              # v34: the offseason months' revenue and costs
        from . import finance as FN
        FN.catch_up(conn, get_state(conn)[0])
    except Exception:
        pass
    conn.commit()
    return pre + lines


def finish_live_auction(conn):
    """Close a war-room auction that is still open: run the remaining rounds, then the depth market."""
    r = conn.execute("SELECT value FROM pack_info WHERE key='fa_live_pending'").fetchone()
    if not r:
        return []
    from . import free_agency as FA
    if FA.live_state(conn) is None:                   # the server restarted mid-auction: run it from the current pool
        FA.live_start(conn, r[0])
    lines = FA.live_finish(conn)
    return lines + after_auction(conn, r[0])


# ---------------- phases

def _enter_draft(conn, day):
    """Retirements are announced, then the entry draft opens (AI picks run until the user is on the clock)."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='waivers'").fetchone():
        from . import waivers as W
        W.process(conn, "9999-12-31")              # anyone still on the wire at season's end is resolved
    from . import draft as D
    from . import world as Wd
    gone = Wd.retirements(conn, day)
    lines = [f"Retirements: {len(gone)} players retired."]
    notable = conn.execute("SELECT player_id, payload, team_id FROM league_events WHERE event_type='PLAYER_RETIRED' AND event_date=? "
                           "AND importance>=2 ORDER BY importance DESC, event_id", (day,)).fetchall()
    if notable:                                          # retirements are their own story (defect 18)
        from .events import emit, player_name
        names = []
        for r in notable[:12]:
            pl = json.loads(r[1] or "{}")
            names.append(f"{player_name(conn, r[0])} ({pl.get('nhl_games', 0)} NHL games)")
        hl = f"End of an era: {player_name(conn, notable[0][0])} leads this summer's retirements"
        emit(conn, "MEDIA_STORY", day, hl, importance=2, headline=hl, body="Retiring: " + "; ".join(names) + ".", tag="retirements",
             kind="retirements")
        add_message(conn, day, "Retirements", "These players have announced their retirement:\n" + "\n".join(f"- {n}" for n in names)
                    + f"\n{len(gone)} players retired in all, across every league.")
    from . import staff
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        lines += staff.ai_offseason(conn, day)
    from . import expansion as XP                        # v45: the expansion draft comes before draft-day trades
    lines += XP.run_draft(conn, day)
    from . import trades
    made = trades.ai_window(conn, day, "draft")
    if made:
        lines.append(f"Draft-day trades ({len(made)}): " + "; ".join(made))
    if Wd.has_world(conn):
        lines += D.start_draft(conn, day)
    return lines


def _enter_rights(conn, day):
    from . import draft as D
    from . import regret
    pre = D.finish_draft(conn, day) + D.rights_summer(conn, day)
    outs = regret.ai_buyouts(conn, day)
    dumps = regret.ai_salary_dumps(conn, day)
    if outs:
        pre.append(f"Buyout window: {'; '.join(outs)}.")
    if dumps:
        pre.append("Salary dumps: " + "; ".join(dumps) + ".")
    year = K.season_year(conn)
    me = user_team(conn)
    rng = _rng(conn, "rights")
    ctx = A.market_context(conn)
    rows = conn.execute("SELECT player_id, team_id FROM players WHERE team_id IS NOT NULL AND status IN "
                        "('active','injured','prospect') ORDER BY player_id").fetchall()
    n_rfa = n_ufa = 0
    for r in rows:
        pid, team = r["player_id"], r["team_id"]
        if K.current_contract(conn, pid, year + 1):
            continue                                    # under contract next season
        last = K.last_contract(conn, pid)
        prev = last["cap_hit"] if last else K.crules(conn)["min_salary"]
        status = K.rights_status(conn, pid, year)
        qo = K.qualifying_offer(conn, prev) if status == "RFA" else None
        conn.execute("INSERT OR REPLACE INTO offseason_rights (season_start_year, player_id, team_id, status, prev_aav, "
                     "qo, qualified, decided_by, arb_eligible, outcome) VALUES (?,?,?,?,?,?,NULL,NULL,?,NULL)",
                     (year, pid, team, status, prev, qo, int(status == "RFA" and K.arbitration_eligible(conn, pid))))
        n_rfa += status == "RFA"
        n_ufa += status == "UFA"
        if team == me:
            continue
        # AI club decisions
        if status == "RFA":
            ask = K.asking(conn, pid, "RFA")
            keep = ask >= 0.8 * qo and (R.player_value(conn, pid) >= 40 or rng.random() < 0.5)
            conn.execute("UPDATE offseason_rights SET qualified=?, decided_by='ai' WHERE season_start_year=? AND "
                         "player_id=?", (int(keep), year, pid))
        else:
            value = R.player_value(conn, pid)
            mates = sorted(R.player_value(conn, q["player_id"]) for q in R.roster(conn, team))
            median = mates[len(mates) // 2] if mates else 50
            ask = K.asking(conn, pid, "UFA")
            room = K.cap_room(conn, team, year + 1)
            if value >= median and (room is None or ask <= room) and rng.random() < 0.6:
                years = K.term_wanted(conn, pid, rng, K.crules(conn)["max_term_resign"])
                try:
                    K.sign_contract(conn, pid, team, years, ask, day, start_year=year + 1, resign=True,
                                    detail="re-signed")
                except R.RosterError:
                    continue
                conn.execute("UPDATE offseason_rights SET outcome='re-signed', decided_by='ai' WHERE "
                             "season_start_year=? AND player_id=?", (year, pid))
    mine = rights_rows(conn, me) if me is not None else []
    out = [f"Offseason: {n_rfa} RFAs and {n_ufa} UFAs league-wide have expiring contracts."]
    if mine:
        out.append(f"You have {len(mine)} expiring players: use `rights` to review, then qualify / decline / extend.")
    if me is not None:
        add_message(conn, day, "Contract decisions", f"{len(mine)} of your players have expiring contracts. "
                                                     "Undecided RFAs will be qualified; undecided UFAs go to market.")
    from . import rfa
    for r in mine:                                   # an overpaid RFA will simply take his qualifying offer
        if r["status"] != "RFA" or not r["qo"]:
            continue
        ask = K.asking(conn, r["player_id"], "RFA")
        if r["qo"] < ask:
            continue
        deal = rfa.security_deal(conn, r["player_id"], r["qo"])
        tips = []
        if deal:
            tips.append(f"he would take {deal[0]} years at ${deal[1]:,.0f} (`extend {r['player_id']} {deal[1]} {deal[0]}`)")
        if r["arb_eligible"] and not A.club_elected_before(conn, r["player_id"]):
            tips.append(f"you can take him to arbitration (`arbitrate {r['player_id']}`; the award can be as low as "
                        "85% of his salary)")
        tips.append("or decline to qualify him and let him go")
        add_message(conn, day, "Qualifying offer above his value",
                    f"{_name(conn, r['player_id'])}'s qualifying offer (${r['qo']:,.0f}, his current cap hit) is above "
                    f"what he would ask (${ask:,.0f}). If qualified he will take it for one year and be in the same "
                    "spot next summer. Instead: " + "; ".join(tips) + ".")
    return pre + out


def _enter_free_agency(conn, day):
    year = K.season_year(conn)
    me = user_team(conn)
    for r in rights_rows(conn):
        if r["outcome"]:
            continue
        if r["status"] == "RFA" and r["qualified"] is None:
            conn.execute("UPDATE offseason_rights SET qualified=1, decided_by='default' WHERE season_start_year=? "
                         "AND player_id=?", (year, r["player_id"]))
            continue
        if r["status"] == "RFA" and r["qualified"]:
            continue
        reason = "unqualified RFA" if r["status"] == "RFA" else "UFA"
        R._release(conn, r["team_id"], r["player_id"], day, f"became a free agent ({reason})")
        conn.execute("UPDATE offseason_rights SET outcome='free agent' WHERE season_start_year=? AND player_id=?",
                     (year, r["player_id"]))
    from . import free_agency as FA
    from .draft import live_draft
    if live_draft(conn):                             # the UI's war room runs the auction round by round
        FA.live_start(conn, day)
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('fa_live_pending', ?)", (day,))
        return ["Free agency opens at noon. The war room is open (Offseason: free agency)."]
    auction = FA.run_auction(conn, day)
    return auction + after_auction(conn, day)


def after_auction(conn, day):
    """The rest of free agency's first day: offer sheets, the depth market, a trade window."""
    from . import offer_sheets as OS
    auction = []
    sheets = OS.ai_offer_sheets(conn, day)
    auction += [f"  Offer sheet: {t}" for t in sheets]
    signed = _ai_free_agency(conn, day, "fa1")
    from . import trades
    made = trades.ai_window(conn, day, "free_agency")
    n_fa = len(R.free_agents(conn))
    conn.execute("DELETE FROM pack_info WHERE key='fa_live_pending'")
    return auction + [f"Depth market: AI clubs signed {signed} more players; {n_fa} free agents remain."
            + (f" Trades: {'; '.join(made)}." if made else ""),
            "Use `fa` and `sign <player> [aav] [years]`; `cap` shows your room for next season."]


def _ai_free_agency(conn, day, tag, limit_per_team=6):
    """AI clubs sign free agents best-first: a club is interested if it is short at his position or below the
    target roster size, or he beats its worst player at that position by 3+, and his price fits its cap room."""
    year = K.signing_year(conn)
    me = user_team(conn)
    rng = _rng(conn, tag)
    ctx = A.market_context(conn)
    teams = [r["team_id"] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id") if r["team_id"] != me]
    taken = {t: 0 for t in teams}
    signed = 0
    _, mx = R.limits(conn)

    def team_state(t):                        # cached per club, refreshed only after that club signs someone
        worst = {}
        for g in ("F", "D", "G"):
            w = R._lowest_healthy(conn, t, [g])
            worst[g] = w[0] if w else None
        room = K.cap_room(conn, t, year)
        if room is not None and tag == "fa1":
            room -= K.pending_rfa_cost(conn, t)      # keep room for qualified RFAs still to sign
        return dict(room=room, counts=R.counts(conn, t, healthy_only=False),
                    size=len(R.roster(conn, t)), worst=worst)
    state = {t: team_state(t) for t in teams}
    for v, pid, pos in R.free_agents(conn):
        g = R.group(pos)
        if not any(st["counts"][g] < R.NEED[g] + (g != "G") or st["size"] < TARGET_ROSTER or
                   (st["worst"][g] is not None and v >= st["worst"][g] + 3) for st in state.values()):
            continue
        ask = K.asking(conn, pid, "UFA")
        cands = []
        for t in teams:
            st = state[t]
            if taken[t] >= limit_per_team or (st["room"] is not None and ask > st["room"]):
                continue
            short = st["counts"][g] < R.NEED[g] + (1 if g != "G" else 0)
            upgrade = st["worst"][g] is not None and v >= st["worst"][g] + 3
            if short or st["size"] < TARGET_ROSTER or upgrade:
                cands.append((0 if short else 1 if st["size"] < TARGET_ROSTER else 2, -(st["room"] or 0), t))
        if not cands:
            continue
        best = min(c[:2] for c in cands)
        t = rng.choice(sorted(c[2] for c in cands if c[:2] == best))
        years = K.term_wanted(conn, pid, rng, K.crules(conn)["max_term_new"])
        from .free_agency import asking_price
        if asking_price(conn, pid) is not None:
            years = rng.randint(1, 2)                  # left over from the auction: a prove-it deal
        try:
            K.sign_contract(conn, pid, t, years, ask, day, start_year=year, resign=False, detail="signed as free agent")
        except R.RosterError:
            continue
        _log(conn, day, "sign", pid, None, t, "signed as free agent")
        taken[t] += 1
        signed += 1
        while len(R.roster(conn, t)) > mx:
            low = R._lowest_healthy(conn, t)
            R.send_down(conn, t, low[1], day, "assigned to the minors (roster full)")
        state[t] = team_state(t)
    return signed


def _enter_arbitration(conn, day):
    year = K.season_year(conn)
    me = user_team(conn)
    ctx = A.market_context(conn)
    filed = settled = accepted = 0
    mine = []
    from . import offer_sheets as OS
    unmatched = OS.resolve_pending(conn, day)
    from . import rfa
    bridges, longs = rfa.ai_rfa_deals(conn, day, rights_rows(conn),
                                      lambda r, aav, years, outcome: _finish(conn, r, aav, years, day, outcome))
    terms, club_arbs = rfa.ai_overpaid(conn, day, rights_rows(conn),
                                       lambda r, aav, years, outcome: _finish(conn, r, aav, years, day, outcome),
                                       lambda r: _file_club(conn, r, day))
    for r in rights_rows(conn):
        if r["status"] != "RFA" or not r["qualified"] or r["outcome"] or r["arb_elected_by"]:
            continue
        pid, team = r["player_id"], r["team_id"]
        ask = K.asking(conn, pid, "RFA")
        if r["qo"] >= ask:
            _finish(conn, r, r["qo"], 1, day, "accepted qualifying offer", check=False)   # the club tendered it
            accepted += 1
        elif r["arb_eligible"]:
            sub = A.submissions(conn, pid, r["prev_aav"], r["qo"], "player", ctx)
            conn.execute("UPDATE offseason_rights SET arb_elected_by='player', player_ask=?, team_offer=? WHERE "
                         "season_start_year=? AND player_id=?", (sub["ask"], sub["offer"], year, pid))
            _log(conn, day, "arbitration", pid, team, team,
                 f"player-elected: asks ${sub['ask']:,.0f}, club offers ${sub['offer']:,.0f}")
            filed += 1
            if team == me:
                mine.append(f"  {_name(conn, pid)} filed: asks ${sub['ask']:,.0f}, your offer ${sub['offer']:,.0f}")
        else:
            aav = int(round((r["qo"] + ask) / 2 / 5000) * 5000)
            try:
                _finish(conn, r, aav, 2, day, "settled (2-year deal)")
            except R.RosterError:
                _finish(conn, r, r["qo"], 1, day, "accepted qualifying offer (club out of cap room)", check=False)
            settled += 1
    out = [f"Offer sheet you did not match: {t}" for t in unmatched] + [f"RFAs: {bridges} bridge deals, {longs} long-term deals buying UFA years, {terms} overpaid RFAs "
           f"traded a year at the QO for term, {club_arbs} taken to club arbitration. Arbitration filing: {filed} "
           f"filed, {accepted} accepted qualifying offers, {settled} settled."]
    if mine:
        out += ["Your cases (settle with `extend <player> <aav> [years]` before the hearing):"] + mine
    return out


def _enter_awards(conn, day):
    year = K.season_year(conn)
    me = user_team(conn)
    seed = get_state(conn)[1]
    ctx = A.market_context(conn)
    lines, walked = [], 0
    for r in rights_rows(conn):
        if not r["arb_elected_by"] or r["outcome"]:
            continue
        pid = r["player_id"]
        sub = dict(market=K.market_aav(conn, pid, ctx["values"], v=A.hearing_value(conn, pid, ctx)),
                   comparables=A.comparables(conn, pid, ctx)[0],
                   ask=r["player_ask"], offer=r["team_offer"])
        amt = A.award(conn, pid, sub, seed, year)
        term = A.choose_term(conn, pid, amt, sub["market"], r["arb_elected_by"], year)
        conn.execute("UPDATE offseason_rights SET award=?, award_years=? WHERE season_start_year=? AND player_id=?",
                     (amt, term, year, pid))
        _log(conn, day, "arbitration", pid, r["team_id"], r["team_id"],
             f"{r['arb_elected_by']}-elected award: {term} yr x ${amt:,.0f}")
        from .events import emit
        emit(conn, "ARBITRATION_AWARD", day, f"{_name(conn, pid)} awarded {term} yr x ${amt:,.0f} in arbitration",
             team_id=r["team_id"], player_id=pid, importance=2, amount=amt, years=term,
             elected_by=r["arb_elected_by"], ask=r["player_ask"], offer=r["team_offer"])
        if r["team_id"] == me:
            walk = " (you may `walkaway`)" if A.can_walk_away(conn, amt, r["arb_elected_by"]) else ""
            lines.append(f"  {_name(conn, pid)}: awarded {term} yr x ${amt:,.0f}{walk}")
        elif A.can_walk_away(conn, amt, r["arb_elected_by"]) and amt > 1.15 * sub["market"]:
            conn.execute("UPDATE offseason_rights SET outcome='walked away' WHERE season_start_year=? AND player_id=?",
                         (year, pid))
            walked += 1
    return [f"Arbitration awards issued; AI clubs walked away from {walked}."] + (
        ["Your awards:"] + lines if lines else [])


def _enter_preseason(conn, day):
    from . import world as Wd
    year = K.season_year(conn)
    developed, notes = Wd.develop(conn, day)
    from . import tactics
    tactics.ai_choose(conn)                           # rosters and coaches changed over the summer
    signed = 0
    for r in rights_rows(conn):
        if r["arb_elected_by"] and r["award"] and not r["outcome"]:
            _finish(conn, r, r["award"], r["award_years"], day, "arbitration award", check=False)
            signed += 1
        elif r["outcome"] == "walked away":
            R._release(conn, r["team_id"], r["player_id"], day, "club walked away from arbitration award: UFA")
    n = _ai_free_agency(conn, day, "fa2")
    me = user_team(conn)
    promoted = 0
    for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id").fetchall():
        R.ensure_dressable(conn, t, day)
        if t != me:
            promoted += R.ai_promote(conn, t, day)
    lines = [f"Preseason ({promoted} prospects promoted by AI clubs): {developed} players developed or aged; {signed} arbitration awards signed; "
             f"AI clubs signed {n} more free agents."]
    if notes:
        lines.append("Your notable changes: " + "; ".join(notes))
    if Wd.has_world(conn):
        from . import college as CO                        # v46: seniors graduate, commits enrol
        lines += CO.summer(conn, day)
        grads = Wd.age_out(conn, day)
        Wd.trim_clubs(conn, day)
        placed, retired = Wd.place_unattached(conn, day)
        cohort = Wd.create_draft_class(conn, day)
        made = Wd.fill_clubs(conn, day)
        CO.register(conn, K.season_year(conn) + 1)        # anyone the world placed in a college club this summer
        lines.append(f"World: {grads} juniors/collegians moved on, {placed} players found clubs, {retired} retired "
                     f"without offers, a class of {cohort} 17-year-olds arrived, {made} other newcomers joined clubs.")
    from . import press
    press.schedule(conn, "media_day", day)
    return lines


def _finish(conn, r, aav, years, day, outcome, check=True):
    year = K.season_year(conn)
    K.sign_contract(conn, r["player_id"], r["team_id"], years, aav, day, start_year=year + 1, resign=True,
                    detail=outcome, check=check)
    conn.execute("UPDATE offseason_rights SET outcome=? WHERE season_start_year=? AND player_id=?",
                 (outcome, year, r["player_id"]))


# ---------------- user decisions

def _my_row(conn, pid):
    year = K.season_year(conn)
    r = conn.execute("SELECT * FROM offseason_rights WHERE season_start_year=? AND player_id=? AND team_id=?",
                     (year, pid, user_team(conn))).fetchone()
    if r is None:
        raise R.RosterError("That player is not one of your expiring contracts this offseason.")
    return r


def qualify(conn, pid, yes=True):
    if K.season_state(conn) != "rights":
        raise R.RosterError("Qualifying offers are made in the rights phase (before 1 July).")
    r = _my_row(conn, pid)
    if r["status"] != "RFA":
        raise R.RosterError("Only restricted free agents get qualifying offers.")
    conn.execute("UPDATE offseason_rights SET qualified=?, decided_by='user' WHERE season_start_year=? AND "
                 "player_id=?", (int(yes), r["season_start_year"], pid))
    conn.commit()
    return r["qo"]


def extend(conn, pid, aav, years, day):
    """Re-sign one of your expiring players: during the season (final contract year), or in the offseason before
    free agency (UFAs) / before the hearing (RFAs). Players who distrust you want 10% more; a player who has asked
    for a trade will not talk."""
    state = K.season_state(conn)
    if state == "regular_season":
        return _extend_in_season(conn, pid, aav, years, day)
    r = _my_row(conn, pid)
    need = extension_floor(conn, pid, years)
    if aav < 0.95 * need:
        raise R.RosterError(f"He wants at least ${need:,.0f} a year.")
    _finish(conn, r, aav, years, day, "extended")
    conn.commit()


def extension_floor(conn, pid, years):
    """The least AAV he will re-sign for at this term (extend accepts 95% of it). Raises if he cannot be extended
    now. Used by extend and by contract talks (hs/game/negotiation.py)."""
    state = K.season_state(conn)
    if state == "regular_season":
        me = user_team(conn)
        year = K.season_year(conn)
        c = K.current_contract(conn, pid)
        p = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()
        if p is None or p["team_id"] != me or c is None:
            raise R.RosterError("He is not under contract with your club.")
        if c["start_year"] + c["years"] - 1 != year:
            raise R.RosterError("Extensions can be signed in the final year of a contract.")
        if K.current_contract(conn, pid, year + 1):
            raise R.RosterError("He is already signed for next season.")
        mood = _mood(conn, pid)
        if mood and mood["trade_request"]:
            raise R.RosterError("He has asked for a trade and will not discuss an extension.")
        need = K.asking(conn, pid, K.rights_status(conn, pid, year))
        if mood and mood["trust_mgmt"] < 35:
            need = int(need * 1.10)
        return need
    r = _my_row(conn, pid)
    if r["outcome"]:
        raise R.RosterError(f"Already settled: {r['outcome']}.")
    if state not in ("finished", "rights", "arbitration"):
        raise R.RosterError("Extensions are possible until free agency (UFAs) or until the hearing (RFAs).")
    if r["status"] == "UFA" and state == "arbitration":
        raise R.RosterError("He is already a free agent; use `sign`.")
    need = K.asking(conn, pid, r["status"])
    if r["status"] == "RFA" and r["qualified"] != 0 and (r["qo"] or 0) >= need:
        # overpaid RFA: his alternative is a year at the QO, so term is worth money to him (hs/game/rfa.py)
        from . import rfa
        from .valuation import _age
        birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        need = int(rfa.min_for_term(r["qo"], years, _age(birth, K.signing_year(conn))))
        if years == 1:
            need = r["qo"]
    if r["arb_elected_by"]:
        need = int(0.5 * (r["player_ask"] + r["team_offer"]))
    return need


def _mood(conn, pid):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        return None
    return conn.execute("SELECT trust_mgmt, trade_request FROM morale WHERE player_id=?", (pid,)).fetchone()


def _extend_in_season(conn, pid, aav, years, day):
    me = user_team(conn)
    year = K.season_year(conn)
    c = K.current_contract(conn, pid)
    p = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] != me or c is None:
        raise R.RosterError("He is not under contract with your club.")
    if c["start_year"] + c["years"] - 1 != year:
        raise R.RosterError("Extensions can be signed in the final year of a contract.")
    need = extension_floor(conn, pid, years)
    if aav < 0.95 * need:
        raise R.RosterError(f"He wants at least ${need:,.0f} a year.")
    K.sign_contract(conn, pid, me, years, aav, day, start_year=year + 1, resign=True, detail="extended")
    conn.commit()


def club_elect(conn, pid, day):
    if K.season_state(conn) not in ("rights", "arbitration"):
        raise R.RosterError("Club-elected arbitration is filed in the rights or arbitration phase.")
    r = _my_row(conn, pid)
    if r["status"] != "RFA" or not r["arb_eligible"]:
        raise R.RosterError("Only arbitration-eligible RFAs can be taken to arbitration.")
    if A.club_elected_before(conn, pid):
        raise R.RosterError("A player can only be taken to club-elected arbitration once in his career.")
    sub = _file_club(conn, r, day)
    conn.commit()
    return sub


def _file_club(conn, r, day):
    pid = r["player_id"]
    sub = A.submissions(conn, pid, r["prev_aav"], r["qo"] or 0, "club")
    conn.execute("UPDATE offseason_rights SET qualified=1, arb_elected_by='club', player_ask=?, team_offer=? WHERE "
                 "season_start_year=? AND player_id=?", (sub["ask"], sub["offer"], r["season_start_year"], pid))
    _log(conn, day, "arbitration", pid, r["team_id"], r["team_id"],
         f"club-elected: asks ${sub['ask']:,.0f}, club offers ${sub['offer']:,.0f}")
    return sub


def walk_away(conn, pid):
    if K.season_state(conn) != "awards":
        raise R.RosterError("You can only walk away after an award (awards phase).")
    r = _my_row(conn, pid)
    if not r["award"] or not A.can_walk_away(conn, r["award"], r["arb_elected_by"]):
        raise R.RosterError("Walk-away applies only to player-elected awards at or above the threshold.")
    conn.execute("UPDATE offseason_rights SET outcome='walked away' WHERE season_start_year=? AND player_id=?",
                 (r["season_start_year"], pid))
    conn.commit()


# ---------------- next season

def _shift(d, years):
    if not d:
        return d
    x = datetime.date.fromisoformat(d)
    try:
        return x.replace(year=x.year + years).isoformat()
    except ValueError:          # 29 Feb
        return x.replace(year=x.year + years, day=28).isoformat()


def rules_for_year(rules, k):
    """The rules with every season date moved k years later."""
    out = json.loads(json.dumps(rules))
    s = out["season"]
    s["start"], s["end"] = _shift(s.get("start"), k), _shift(s.get("end"), k)
    s["breaks"] = [{"start": _shift(b["start"], k), "end": _shift(b["end"], k)} for b in s.get("breaks", [])]
    return out


def _start_next_season(conn):
    year = K.season_year(conn) + 1
    first = conn.execute("SELECT start_date FROM seasons ORDER BY start_year LIMIT 1").fetchone()[0]
    base_rules = db_rules(conn, base=True)
    k = offseason_calendar_year(conn) - int((base_rules["season"]["start"] or first)[:4])
    from ..league.eras import for_season
    rules = rules_for_year(for_season(base_rules, year), k)      # this season's era (e.g. 84 games from 2026-27)
    league = conn.execute("SELECT league_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO seasons (league_id, start_year, label, start_date, end_date) VALUES (?,?,?,?,?)",
                 (league, year, f"{year}-{(year + 1) % 100:02d}", rules["season"]["start"], rules["season"]["end"]))
    from . import international as INTL                  # v51: the NHL breaks for the Olympics and the World Cup
    brk = INTL.schedule_break(year)
    if brk:
        rules = dict(rules, season=dict(rules["season"], breaks=list(rules["season"].get("breaks") or []) + [brk]))
    seed = get_state(conn)[1]
    create_schedule(conn, rules, seed + year)
    first = conn.execute("SELECT MIN(game_date) FROM games WHERE played=0 AND game_type='RS'").fetchone()[0]
    start = (datetime.date.fromisoformat(first) - datetime.timedelta(days=1)).isoformat()
    _set_state(conn, "regular_season", start)
    conn.execute("DELETE FROM pack_info WHERE key='champion'")
    from . import expansion as XP                        # v45: an expansion club plays its first season
    XP.joined(conn)
    from . import challenge as CHL                       # v47: cap hell is judged on opening night
    CHL.opening_night(conn, start)
    from . import org
    org.clear_vacancies(conn)
    org.set_objectives(conn, start)
    from .roster import ensure_dressable              # every AI club opens the season able to dress a full lineup
    from ..schema import top_league_sql
    me_ = user_team(conn)
    for (t_,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}").fetchall():
        if t_ != me_:
            ensure_dressable(conn, t_, start)
    add_message(conn, start, "New season", f"The {year}-{(year + 1) % 100:02d} season begins on {first}.")
    from ..league.eras import describe
    out = [f"The {year}-{(year + 1) % 100:02d} season is scheduled; first games on {first}."]
    prev = for_season(base_rules, year - 1)
    if (prev["schedule"], prev["overtime"], prev["points"]) != (rules["schedule"], rules["overtime"], rules["points"]):
        out.append("New rules this season: " + describe(base_rules, year) + ".")
        add_message(conn, start, "Rule change", "New rules this season: " + describe(base_rules, year) + ".")
    return out
