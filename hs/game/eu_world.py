"""The rest of Europe while you run a club (v61; docs/EUROPE.md): AI clubs doing business in the window, and NHL clubs
signing your best players under the transfer agreements.

Window moves  every Monday in the window: five moves a week in July and August, two a week after that. A buying
              club (the stronger leagues more often) looks for a regular at one position (forwards 55%, defence
              35%, goal 10%): a player in a league no stronger than its own, better by 0.15 than its 9th forward /
              5th defenceman / starting goalie, 31 or younger, whose club can spare him. It pays his fee and the
              going wage in its league. Your club is never a buyer or a seller here (bids for your players come as
              offers you answer).
Loans         every Monday from August to the window's close, three a week: a club lends a player of 22 or under
              from outside its top lineup (9 forwards, 5 defencemen, 1 goalie) to a club a level or two down where
              he would be a regular (league mean 0.2 to 2.0 lower at home, to 1.5 abroad). The borrower pays half
              his wage; he goes home at the season's end. Your club neither lends nor borrows here. Loans stay in
              the country's own system (SHL to HockeyAllsvenskan, National League to Swiss League, KHL to VHL) and
              now and then cross to a neighbour (a Swede to Norway or Denmark, a Czech to Slovakia, a German to
              Austria). Russian clubs lend only to Russian clubs.
NHL signings  on 1 July each of your players 27 or under who is as good as an NHL regular (the 25th percentile of
              NHL roster players) signs in the NHL with a chance of 40% (15% from a KHL club): with the club holding
              his draft rights, else an NHL club with room. Your club gets the transfer-agreement compensation,
              €220,000 (about US$240,000, the Swedish agreement), except from the KHL, which has none.
"""
from __future__ import annotations

import datetime
import random

from .state import add_message

NHL_FEE = 220_000
GROUP_P = (("F", 0.55), ("D", 0.35), ("G", 0.10))
REGULAR = {"F": 9, "D": 5, "G": 1}


def window_moves(conn, day):
    from . import europe as EU
    from .roster import group
    from .world import load_attrs, overall, age_on, world_meta
    d = datetime.date.fromisoformat(day)
    if d.weekday() != 0 or not EU.window_open(day):
        return []
    EU.ensure_tables(conn)
    me = EU.club(conn)
    meta = world_meta(conn)
    playing = EU.european_leagues(conn)
    league_of = {t: lid for t, lid in conn.execute("SELECT team_id, league_id FROM teams")}
    euro = {lid for lid, m in meta.items() if m.get("kind") == "europe"}
    rows = load_attrs(conn, "p.status IN ('active','injured') AND p.team_id IS NULL AND p.club_id IN "
                            f"(SELECT team_id FROM teams WHERE league_id IN ({','.join(map(str, euro)) or '0'}))")
    cons = {r["player_id"]: dict(r) for r in conn.execute("SELECT * FROM eu_contracts")}
    year = EU.contract_year(conn)
    on = datetime.date(EU.season_year(conn), 9, 15)
    by_club = {}
    for pid, r in rows.items():
        by_club.setdefault(r["club_id"], {"F": [], "D": [], "G": []})[group(r["position"])].append((overall(r), pid))
    for g in by_club.values():
        for lst in g.values():
            lst.sort(reverse=True)
    buyers = [t for t, lid in league_of.items() if lid in playing and t != me and t in by_club]
    if not buyers:
        return []
    rng = random.Random(f"eu-window-{day}")
    k = 5 if d.month in (7, 8) else 2
    weights = [max(0.2, (meta[league_of[t]].get("mean") or 8) - 7.0) for t in buyers]
    news, done = [], 0
    for _ in range(k * 4):
        if done >= k:
            break
        t = rng.choices(buyers, weights)[0]
        g = rng.choices([x for x, _ in GROUP_P], [w for _, w in GROUP_P])[0]
        mine = by_club[t][g]
        bar = (mine[REGULAR[g] - 1][0] if len(mine) >= REGULAR[g] else 0.0) + 0.15
        m_buy = meta[league_of[t]]
        cands = []
        for c2, groups in by_club.items():
            if c2 in (t, me) or league_of.get(c2) not in euro:
                continue
            if (meta[league_of[c2]].get("mean") or 8) > (m_buy.get("mean") or 8) + 0.05:
                continue
            if len(groups[g]) - 1 < EU.MIN_KEEP[g]:
                continue
            for ov, pid in groups[g][:6]:
                c = cons.get(pid)
                if ov < bar or c is None or c["loan_from"]:
                    continue
                if age_on(rows[pid]["birth_date"], on) > 31:
                    continue
                cands.append((ov, pid, c2))
        if not cands:
            continue
        cands.sort(reverse=True)
        ov, pid, seller = rng.choice(cands[:5])
        age = age_on(rows[pid]["birth_date"], on)
        place = next(i for i, (_, p) in enumerate(by_club[seller][g]) if p == pid) + 1
        fee = EU._fee(cons[pid], EU.season_year(conn), age, place <= EU.KEY_SHARE[g], day)
        wage = EU.wage_of(m_buy, ov)
        EU._move(conn, pid, t, day, until=year + rng.choice((1, 2, 2, 3)) - 1, salary=wage)
        cons[pid] = dict(cons[pid], club_id=t)
        by_club[seller][g] = [x for x in by_club[seller][g] if x[1] != pid]
        by_club[t][g] = sorted(by_club[t][g] + [(ov, pid)], reverse=True)
        done += 1
        if ov >= (m_buy.get("mean") or 8) + 0.4:
            name = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            text = f"{name} moves from {EU._club_name(conn, seller)} to {EU._club_name(conn, t)} (fee €{fee:,})"
            EU._news(conn, day, text, t, pid, seller)
            news.append(text)
    return news


TOP_COUNTRY = {"KHL": "RUS", "SHL": "SWE", "NL": "SUI", "LIIGA": "FIN", "ELH": "CZE", "DEL": "GER"}
NEAR = {"SWE": ("NOR", "DEN"), "FIN": ("SWE",), "CZE": ("SVK",), "SVK": ("CZE",), "GER": ("AUT",), "AUT": ("GER",),
        "SUI": ("AUT",), "NOR": ("SWE",), "DEN": ("SWE",)}


def country(m):
    return m.get("country") or TOP_COUNTRY.get((m.get("abbr") or "").upper())


def window_loans(conn, day, k=3):
    """AI clubs lending their young players down a level or two (see the module doc)."""
    from . import europe as EU
    from .roster import group
    from .world import load_attrs, overall, age_on, world_meta
    d = datetime.date.fromisoformat(day)
    if d.weekday() != 0 or not EU.window_open(day) or d.month == 7:
        return []
    EU.ensure_tables(conn)
    me = EU.club(conn)
    meta = world_meta(conn)
    playing = EU.european_leagues(conn)
    league_of = {t: lid for t, lid in conn.execute("SELECT team_id, league_id FROM teams")}
    rows = load_attrs(conn, "p.status IN ('active','injured') AND p.team_id IS NULL AND p.club_id IN "
                            f"(SELECT team_id FROM teams WHERE league_id IN ({','.join(map(str, playing)) or '0'}))")
    cons = {r["player_id"]: dict(r) for r in conn.execute("SELECT * FROM eu_contracts")}
    on = datetime.date(EU.season_year(conn), 9, 15)
    by_club = {}
    for pid, r in rows.items():
        by_club.setdefault(r["club_id"], {"F": [], "D": [], "G": []})[group(r["position"])].append((overall(r), pid))
    for g in by_club.values():
        for lst in g.values():
            lst.sort(reverse=True)
    mean = {t: (meta[league_of[t]].get("mean") or 8) for t in by_club}
    land = {t: country(meta[league_of[t]]) for t in by_club}
    lenders = [t for t in by_club if t != me]
    rng = random.Random(f"eu-loans-{day}")
    until = EU.season_end(conn)
    news, done = [], 0
    for _ in range(k * 6):
        if done >= k or not lenders:
            break
        t = rng.choice(lenders)
        g = rng.choices([x for x, _ in GROUP_P], [w for _, w in GROUP_P])[0]
        spare = [(ov, pid) for ov, pid in by_club[t][g][EU.LOANABLE[g]:]
                 if pid in cons and not cons[pid]["loan_from"] and age_on(rows[pid]["birth_date"], on) <= 22]
        if not spare or len(by_club[t][g]) - 1 < EU.MIN_KEEP[g]:
            continue
        ov, pid = rng.choice(spare[:4])
        fits = [b for b in by_club if b not in (t, me) and 0.2 <= mean[t] - mean[b] <= (2.0 if land[b] == land[t] else 1.5)
                and (len(by_club[b][g]) < REGULAR[g] or by_club[b][g][REGULAR[g] - 1][0] < ov)]
        homes = [b for b in fits if land[b] == land[t]]
        if (not homes and rng.random() < 0.5) or rng.random() < 0.15:
            homes = [b for b in fits if land[b] in NEAR.get(land[t], ())] or homes
        if not homes:
            continue
        b = rng.choice(homes)
        conn.execute("UPDATE eu_contracts SET club_id=?, loan_from=?, loan_until=?, loan_share=0.5 WHERE player_id=?",
                     (b, t, until, pid))
        conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (b, pid))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES "
                     "(?, 'loan', ?, ?, ?, ?)", (day, pid, t, b, f"on loan until {until}"))
        cons[pid] = dict(cons[pid], club_id=b, loan_from=t)
        by_club[t][g] = [x for x in by_club[t][g] if x[1] != pid]
        by_club[b][g] = sorted(by_club[b][g] + [(ov, pid)], reverse=True)
        done += 1
        if ov >= mean[b] + 0.3:
            name = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            text = f"{name} goes on loan from {EU._club_name(conn, t)} to {EU._club_name(conn, b)} until {until}"
            EU._news(conn, day, text, b, pid, t)
            news.append(text)
    return news


def nhl_threshold(conn):
    from ..schema import top_league_sql
    from .world import load_attrs, overall
    vals = sorted(overall(r) for r in load_attrs(conn, f"p.status IN ('active','injured') AND p.team_id IN "
                                                       f"(SELECT team_id FROM teams WHERE {top_league_sql()})").values())
    return vals[len(vals) // 4] if vals else 99.0


def nhl_signings(conn, day):
    """1 July: NHL clubs sign your best young players; you get the transfer-agreement fee (none from the KHL)."""
    from . import europe as EU
    from . import contracts as K
    from .roster import RosterError
    from ..schema import top_league_sql
    from .world import load_attrs, overall, age_on
    me = EU.club(conn)
    if me is None:
        return []
    m, _ = EU._meta_of_club(conn, me)
    khl = m.get("abbr") == "KHL"
    bar = nhl_threshold(conn)
    rng = random.Random(f"eu-nhl-{day[:4]}-{me}")
    on = datetime.date(EU.contract_year(conn), 9, 15)
    nhl = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    gone = []
    for pid, r in load_attrs(conn, "p.club_id=? AND p.team_id IS NULL AND p.status IN ('active','injured')", (me,)).items():
        c = EU.contract(conn, pid)
        if c is None or c["loan_from"] or age_on(r["birth_date"], on) > 27 or overall(r) < bar:
            continue
        if rng.random() >= (0.15 if khl else 0.4):
            continue
        rights = conn.execute("SELECT team_id FROM draft_rights WHERE player_id=?", (pid,)).fetchone()
        order = ([rights[0]] if rights else []) + sorted(nhl, key=lambda t: -K.cap_room(conn, t))[:6]
        cr = K.crules(conn)
        for t in order:
            try:
                K.sign_contract(conn, pid, t, rng.choice((1, 2)), int(cr["min_salary"] * rng.uniform(1.0, 1.6) / 5000) * 5000, day,
                                detail="signed from Europe")
            except (RosterError, ValueError):
                if conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0] is None:
                    continue                              # (a refusal that got as far as the contract still counts)
            t = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            conn.execute("DELETE FROM eu_contracts WHERE player_id=?", (pid,))
            fee = 0 if khl else NHL_FEE
            conn.execute("UPDATE eu_finance SET transfer_budget=transfer_budget+? WHERE club_id=?", (fee, me))
            name = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            from .events import team_abbr
            gone.append(f"{name} ({team_abbr(conn, t)}{', €' + format(fee, ',') + ' compensation' if fee else ', no compensation from the KHL'})")
            break
    if gone:
        add_message(conn, day, "Off to the NHL", "These players have signed NHL contracts:\n" + "\n".join(f"- {g}" for g in gone)
                    + ("\nThe transfer agreement pays your club compensation for each." if not khl else ""), sender="Sporting director")
    return [f"NHL signings from {EU._club_name(conn, me)}: {len(gone)}"] if gone else []
