"""Restricted free agents coming off their deals: bridge or long-term (AI clubs; runs as the arbitration phase opens).

  no arbitration rights   the RFA squeeze: no leverage, so a 2-year bridge at the higher of the qualifying offer
                          and 80% of his fair 2-year value
  arbitration rights, 25 or younger, a regular (perceived 10.5+), and the club can afford it
                          buy his UFA years now: up to the re-signing maximum, at
                          AAV = (RFA years x 85% of fair + UFA years x 110% of fair) / total years,
                          where RFA years run until he would be a UFA (age 27 or 7 NHL seasons)
  otherwise               the existing path: accept the qualifying offer, file for arbitration, or settle

Overpaid RFAs (qualifying offer at or above what he would ask; v20). A qualifying offer is 100% of his last cap hit
above $1.75M, so a player paid more than he is worth could take it every summer and stay an overpaid RFA forever.
Clubs get out of it the way real ones do:
  term for money   (QO $1.5M+; cheaper RFAs simply sign the QO) the club offers 2-6 years and he takes them when
                   they beat a year at his QO:
                   utility = AAV x years^s (s = 0.15 under 30, the free-agent security exponent), so a five-year deal
                   at 79% of the QO is worth as much to him as the QO for one year; the club pays at most 110% of his
                   fair value for that term, and picks the term that saves it the most
  club arbitration otherwise, if the QO is $1.5M+, he is arbitration-eligible, has not been taken before and the QO is 5%+ over his
                   ask, the club elects arbitration (the award can be as low as 85% of his salary)
  QO               otherwise he signs the one-year qualifying offer
A long-term deal (above) never pays less than the player would accept against his QO.
"""
from __future__ import annotations

import random

from . import contracts as K
from . import free_agency as FA
from . import valuation as V
from .state import get_state, user_team

BRIDGE_SHARE = 0.80
RFA_SHARE, UFA_PREMIUM = 0.85, 1.10
LONG_TERM_OV = 10.5
LONG_TERM_AGE = 25
LONG_TERM_P = 0.7
CLUB_PAY_MAX = 1.10          # term-for-money: the most a club pays over his fair value
MIN_TERM, MAX_TERM = 2, 6
TERM_MIN_QO = 1_500_000      # below this a depth RFA simply signs his qualifying offer, as most do
ARB_OVER_ASK = 1.05          # club elects arbitration when the QO is this far over his ask


def min_for_term(qo, years, age):
    """The lowest AAV over `years` that he prefers to a one-year qualifying offer."""
    return qo / years ** FA.security(age) * 1.02


def security_deal(conn, pid, qo, m=None):
    """(years, aav) trading a one-year overpay for term, or None if no term works for both sides."""
    m = m or V.market(conn)
    birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    age = V._age(birth, m.year)
    best = None
    if (qo or 0) < TERM_MIN_QO:
        return None
    for years in range(MIN_TERM, min(MAX_TERM, K.crules(conn)["max_term_resign"]) + 1):
        need = min_for_term(qo, years, age)
        fair = V.fair_aav(conn, pid, years, m.year, m)
        if need > CLUB_PAY_MAX * fair:
            continue
        saving = (qo - need) * 1 + (fair - need) * (years - 1)      # against a year at the QO, then fair value
        if best is None or saving > best[0]:
            best = (saving, years, need)
    if best is None:
        return None
    _, years, need = best
    return years, max(m.min_salary, int(round(need / 5000 + 0.5) * 5000))


def ai_overpaid(conn, day, rows, finish, elect):
    """AI clubs' qualified RFAs whose QO is at or above their ask. finish(r, aav, years, outcome); elect(r).
    Returns (term deals, club arbitrations)."""
    from .arbitration import club_elected_before
    me = user_team(conn)
    m = V.market(conn)
    terms = arbs = 0
    for r in rows:
        if r["status"] != "RFA" or not r["qualified"] or r["outcome"] or r["arb_elected_by"] or r["team_id"] == me:
            continue
        qo, ask = r["qo"] or 0, K.asking(conn, r["player_id"], "RFA")
        if qo < ask:
            continue
        deal = security_deal(conn, r["player_id"], qo, m)
        if deal:
            years, aav = deal
            try:
                finish(r, aav, years, f"{years}-year deal instead of the qualifying offer")
                terms += 1
                continue
            except K.RosterError:
                pass
        if (r["arb_eligible"] and qo >= TERM_MIN_QO and qo > ARB_OVER_ASK * ask
                and not club_elected_before(conn, r["player_id"])):
            elect(r)
            arbs += 1
    return terms, arbs


def bridge_terms(conn, pid, qo, m=None):
    m = m or V.market(conn)
    fair2 = V.fair_aav(conn, pid, 2, m.year, m)
    return 2, max(qo or 0, int(round(BRIDGE_SHARE * fair2 / 5000) * 5000), m.min_salary)


def long_term_terms(conn, pid, m=None):
    m = m or V.market(conn)
    cr = K.crules(conn)
    years = cr["max_term_resign"]
    birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    age = V._age(birth, m.year)
    rfa_years = max(0, min(years, cr["ufa_age"] - age))
    ufa_years = years - rfa_years
    fair = V.fair_aav(conn, pid, years, m.year, m)
    aav = (rfa_years * RFA_SHARE * fair + ufa_years * UFA_PREMIUM * fair) / years
    if m.max_salary:
        aav = min(aav, m.max_salary)
    return years, max(m.min_salary, int(round(aav / 5000) * 5000)), rfa_years


def ai_rfa_deals(conn, day, rows, finish):
    """rows: offseason_rights rows; finish(r, aav, years, outcome) signs. Returns (bridges, long_terms)."""
    me = user_team(conn)
    m = V.market(conn)
    rng = random.Random(f"{get_state(conn)[1]}-{m.year}-rfa")
    bridges = longs = 0
    for r in rows:
        if r["status"] != "RFA" or not r["qualified"] or r["outcome"] or r["team_id"] == me:
            continue
        pid = r["player_id"]
        ov = V.overall_of_value(m.values.value(pid))
        birth = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        age = V._age(birth, m.year)
        try:
            if not r["arb_eligible"]:
                years, aav = bridge_terms(conn, pid, r["qo"], m)
                if aav <= (r["qo"] or 0):
                    continue                          # the QO is the deal; the normal path handles it
                finish(r, aav, years, "bridge deal (no arbitration rights)")
                bridges += 1
            elif age <= LONG_TERM_AGE and ov >= LONG_TERM_OV and rng.random() < LONG_TERM_P:
                years, aav, rfa_years = long_term_terms(conn, pid, m)
                aav = max(aav, int(round(min_for_term(r["qo"] or 0, years, age) / 5000 + 0.5) * 5000))
                finish(r, aav, years, f"long-term deal ({rfa_years} RFA + {years - rfa_years} UFA years)")
                longs += 1
        except K.RosterError:
            continue
    return bridges, longs
