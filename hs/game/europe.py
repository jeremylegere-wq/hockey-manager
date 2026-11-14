"""Running a club in a European league (v61; docs/EUROPE.md).

You take a job with a club in any European league that plays game by game. Your NHL seat stays empty (the NHL world
runs on AI, as when you are out of work, and you can still apply for NHL jobs), and you run the club's squad,
contracts, transfers and loans. Its games are played by the leagues' results model (hs/game/leagues.py).

European hockey has no draft and no trades: clubs grow players in their academies and recruit the rest.
  Contracts   one to three seasons, a yearly wage. A player out of contract is a free agent and moves for nothing.
  Transfers   for a player under contract, his club must agree a fee (a buyout of his deal), then he agrees his
              terms. Fee asked ~ his wage x the seasons left (more for the young, more for a key player).
  Loans       a limited transfer: the player plays for you until a date (at the latest the season's end) and goes
              back; you pay a share of his wage. Clubs lend players outside their top lineup, mostly the young.
  The window  international transfers run 1 July - 15 February (IIHF); outside it nobody moves.
  Imports     the league's import limits apply (hs/game/leagues.py Limits).
  Academy     each September a few 16-17-year-olds come up from the club's junior teams.
Money is in euros and approximate: a league's typical wage from its strength, a player's from his ability.
Nothing here runs unless a European career has started, so NHL careers play exactly as before.
"""
from __future__ import annotations

import datetime
import math
import random

from .state import add_message, get_state

KEY = "eu_club"
WINDOW_OPEN, WINDOW_CLOSE = (7, 1), (2, 15)
KEY_SHARE = {"F": 6, "D": 4, "G": 1}          # a club's key players: its top six forwards, four defencemen, starter
MIN_KEEP = {"F": 12, "D": 6, "G": 2}          # a club never lets its squad fall below this at a position
LOANABLE = {"F": 9, "D": 5, "G": 1}           # clubs lend players outside their top 9 F / 5 D / 1 G
ACADEMY = 4
OFFER_DAYS = 7


# ---------------------------------------------------------------- tables and the career
def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS eu_contracts (player_id INTEGER PRIMARY KEY, club_id INTEGER, until INTEGER, "
                 "salary INTEGER, loan_from INTEGER, loan_until TEXT, loan_share REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS eu_offers (offer_id INTEGER PRIMARY KEY, player_id INTEGER, from_club INTEGER, "
                 "to_club INTEGER, kind TEXT, fee INTEGER, wage INTEGER, years INTEGER, day TEXT, status TEXT, note TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS eu_finance (club_id INTEGER PRIMARY KEY, transfer_budget INTEGER, wage_budget INTEGER)")


def club(conn):
    """The European club you run, or None."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='pack_info'").fetchone():
        return None
    r = conn.execute("SELECT value FROM pack_info WHERE key=?", (KEY,)).fetchone()
    return int(r[0]) if r else None


def active(conn):
    return club(conn) is not None


def history(conn):
    """You have run a European club in this career (the European world keeps turning when you are between jobs)."""
    return bool(conn.execute("SELECT 1 FROM pack_info WHERE key='eu_history'").fetchone())


def european_leagues(conn):
    """{league_id: meta} for the European pro leagues that play game by game (the ones a club can be run in)."""
    from .world import world_meta
    from . import leagues as LG
    meta = world_meta(conn)
    playing = LG.leagues(conn)
    return {lid: m for lid, m in meta.items() if m.get("kind") == "europe" and lid in playing}


def clubs_to_run(conn):
    """[dict(team_id, name, league, abbr, strength)] every club you could take."""
    out = []
    for lid, m in european_leagues(conn).items():
        for t, name in conn.execute("SELECT team_id, name FROM teams WHERE league_id=? ORDER BY name", (lid,)):
            out.append(dict(team_id=t, name=name, league=m["abbr"], league_id=lid, level=m.get("level"), mean=m["mean"]))
    out.sort(key=lambda x: (-x["mean"], x["league"], x["name"]))
    return out


def opening_day(conn, team_id):
    """The first day of the regular season in the club's league (this season), or None."""
    from . import leagues as LG
    lid = conn.execute("SELECT league_id FROM teams WHERE team_id=?", (int(team_id),)).fetchone()
    rules = LG.leagues(conn).get(lid[0]) if lid else None
    if not rules or not rules[1].get("start"):
        return None
    return LG._date(season_year(conn), rules[1]["start"]).isoformat()


def opening_in(conn, year):
    """The opening day of your European league's regular season in `year` (a date), or None when you run no club."""
    from . import leagues as LG
    me = club(conn)
    if me is None:
        return None
    lid = conn.execute("SELECT league_id FROM teams WHERE team_id=?", (me,)).fetchone()
    rules = LG.leagues(conn).get(lid[0]) if lid else None
    return LG._date(year, rules[1]["start"]) if rules and rules[1].get("start") else None


def rewind_to_opening(conn, team_id):
    """v61: a new game that starts at a European club starts the day before its league opens (the KHL in early
    September), not the day before the NHL's opener. Only for a world in which nothing has been played yet."""
    first = opening_day(conn, team_id)
    day = get_state(conn)[0]
    if not first:
        return day
    new = (datetime.date.fromisoformat(first) - datetime.timedelta(days=1)).isoformat()
    played = conn.execute("SELECT COUNT(*) FROM games WHERE played=1").fetchone()[0] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='games'").fetchone() else 0
    lg = conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_games'").fetchone() and conn.execute(
        "SELECT COUNT(*) FROM lg_games WHERE played=1").fetchone()[0]
    if new >= day or played or lg:
        return day
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for col in [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]:
            if any(k in col.lower() for k in ("date", "day", "updated", "set_on", "created", "since")):
                conn.execute(f'UPDATE "{t}" SET "{col}"=? WHERE "{col}"=?', (new, day))
    return new


def start(conn, team_id, day=None, hired=False):
    """Take the job at a European club: any club for a new European career, an opening you were hired for after that."""
    from . import gm as GM
    from . import eu_board as EB
    team_id = int(team_id)
    lid = conn.execute("SELECT league_id FROM teams WHERE team_id=?", (team_id,)).fetchone()
    if lid is None or lid[0] not in european_leagues(conn):
        raise ValueError("That club is not in a European league played game by game (League > World Leagues > Leagues in play).")
    EB.ensure_tables(conn)
    if not hired and not EB.free_choice(conn):
        raise ValueError("Once you have run a European club you apply for openings (Job Centre, Manage in Europe).")
    day = day or get_state(conn)[0]
    GM.lose_job(conn, day, "europe")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('gm_status', 'europe')")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (KEY, str(team_id)))
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('eu_history', ?)", (str(team_id),))
    conn.execute("DELETE FROM eu_vacancy WHERE club_id=?", (team_id,))
    ensure_contracts(conn)
    _budget(conn, team_id, reset=True)
    EB.set_objectives(conn, day, keep_confidence=False)
    name = conn.execute("SELECT name FROM teams WHERE team_id=?", (team_id,)).fetchone()[0]
    m = european_leagues(conn)[lid[0]]
    add_message(conn, day, f"Welcome to {name}",
                f"You run {name} in the {m['abbr']}. European hockey has no draft and no trades: you recruit. Players out of "
                "contract move for nothing; for a player under contract his club must agree a fee first. Loans bring in "
                "young players for part of the season. The window is open from 1 July to 15 February.\n"
                "The Club screen has your squad, the transfer market and offers for your players. Your games are played "
                "with the league's schedule (World Leagues).", sender="Club president")
    return name


def leave(conn):
    """You took an NHL job: the European club's AI takes over."""
    conn.execute("DELETE FROM pack_info WHERE key=?", (KEY,))


# ---------------------------------------------------------------- money
def _meta_of_club(conn, t):
    from .world import world_meta
    lid = conn.execute("SELECT league_id FROM teams WHERE team_id=?", (t,)).fetchone()
    return world_meta(conn).get(lid[0] if lid else None, {}), (lid[0] if lid else None)


def league_wage(m):
    """The typical (median) wage in a league, in euros, from its strength; the KHL pays far more."""
    w = 25_000 * math.exp(1.15 * ((m.get("mean") or 8.0) - 7.6))
    return w * (2.5 if m.get("abbr") == "KHL" else 1.0)


def wage_of(m, ov):
    return int(min(3_000_000, max(15_000, league_wage(m) * math.exp(0.55 * (ov - (m.get("mean") or 8.0))))) / 1000) * 1000


def _attrs(conn, pid):
    from .world import load_attrs, overall
    r = load_attrs(conn, "p.player_id=?", (pid,)).get(pid)
    return (overall(r), r) if r else (0.0, None)


def season_year(conn):
    from . import contracts as K
    return K.season_year(conn)


def contract_year(conn):
    """The season a deal signed today starts in (next season once this one is over)."""
    from . import contracts as K
    return K.signing_year(conn)


def ensure_contracts(conn):
    """Contracts for every player at a European pro club who has none (and is not held by an NHL organisation)."""
    ensure_tables(conn)
    from .world import load_attrs, overall, world_meta
    meta = world_meta(conn)
    leagues = {t: lid for t, lid in conn.execute("SELECT team_id, league_id FROM teams")}
    year = contract_year(conn)
    _sync(conn)
    have = {r[0] for r in conn.execute("SELECT player_id FROM eu_contracts")}
    rows = load_attrs(conn, "p.status IN ('active','injured') AND p.team_id IS NULL AND p.club_id IS NOT NULL")
    add = []
    for pid, r in rows.items():
        m = meta.get(leagues.get(r["club_id"]))
        if pid in have or not m or m.get("kind") != "europe":
            continue
        rng = random.Random(f"eu-contract-{pid}")
        until = year + rng.choices((0, 1, 2, 3), (0.35, 0.35, 0.2, 0.1))[0]
        add.append((pid, r["club_id"], until, wage_of(m, overall(r))))
    conn.executemany("INSERT INTO eu_contracts (player_id, club_id, until, salary) VALUES (?,?,?,?)", add)
    return len(add)


def contract(conn, pid):
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM eu_contracts WHERE player_id=?", (pid,)).fetchone()
    return dict(r) if r else None


def _budget(conn, t, reset=False):
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM eu_finance WHERE club_id=?", (t,)).fetchone()
    if r and not reset:
        return dict(r)
    m, _ = _meta_of_club(conn, t)
    bill = wage_bill(conn, t)
    rank = _rank(conn, t)
    big = 1.0 + 0.25 * (1 - rank)                       # the bigger clubs of a league have more to spend
    tb = int(league_wage(m) * 2.0 * big / 10000) * 10000
    wb = int(max(bill * 1.08 + league_wage(m) * 1.5 * big, league_wage(m) * 22 * big) / 10000) * 10000
    conn.execute("INSERT OR REPLACE INTO eu_finance VALUES (?,?,?)", (t, tb, wb))
    return dict(club_id=t, transfer_budget=tb, wage_budget=wb)


def _rank(conn, t):
    """0 (the league's strongest club on paper) .. 1 (its weakest)."""
    from .world import load_attrs, overall
    _, lid = _meta_of_club(conn, t)
    strength = {}
    for (c,) in conn.execute("SELECT team_id FROM teams WHERE league_id=?", (lid,)):
        rs = load_attrs(conn, "p.club_id=? AND p.status IN ('active','injured')", (c,))
        top = sorted((overall(r) for r in rs.values()), reverse=True)[:18]
        strength[c] = sum(top) / len(top) if top else 0
    order = sorted(strength, key=lambda c: -strength[c])
    return order.index(t) / max(1, len(order) - 1) if t in order else 0.5


def wage_bill(conn, t):
    ensure_tables(conn)
    own = conn.execute("SELECT COALESCE(SUM(salary), 0) FROM eu_contracts WHERE club_id=? AND loan_from IS NULL", (t,)).fetchone()[0]
    loaned_in = conn.execute("SELECT COALESCE(SUM(salary * loan_share), 0) FROM eu_contracts WHERE club_id=? AND loan_from IS NOT NULL",
                             (t,)).fetchone()[0]
    loaned_out = conn.execute("SELECT COALESCE(SUM(salary * (1 - loan_share)), 0) FROM eu_contracts WHERE loan_from=?", (t,)).fetchone()[0]
    return int(own + loaned_in + loaned_out)


# ---------------------------------------------------------------- the window, values, asks
def window_open(day):
    d = datetime.date.fromisoformat(day)
    return (d.month, d.day) >= WINDOW_OPEN or (d.month, d.day) <= WINDOW_CLOSE


def _squad(conn, t):
    from .world import load_attrs, overall
    rs = load_attrs(conn, "p.club_id=? AND p.status IN ('active','injured')", (t,))
    from .roster import group
    out = {"F": [], "D": [], "G": []}
    for pid, r in rs.items():
        out[group(r["position"])].append((overall(r), pid))
    for g in out:
        out[g].sort(reverse=True)
    return out, rs


def _place(conn, t, pid):
    """(group, his place in the club's order at his position, 1 = best)."""
    sq, rs = _squad(conn, t)
    for g, lst in sq.items():
        for i, (_, p) in enumerate(lst):
            if p == pid:
                return g, i + 1, len(lst)
    return None, 99, 0


def fee_value(conn, pid, day=None):
    """What his club asks to let him go (0 for a free agent; None if he cannot be bought: NHL-held, or on loan)."""
    c = contract(conn, pid)
    p = conn.execute("SELECT team_id, club_id, birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] is not None:
        return None
    if p["club_id"] is None:
        return 0
    if c is None:
        return None
    if c["loan_from"]:
        return None
    from .world import age_on
    age = age_on(p["birth_date"], datetime.date(season_year(conn), 9, 15))
    g, place, _ = _place(conn, p["club_id"], pid)
    return _fee(c, season_year(conn), age, g is not None and place <= KEY_SHARE.get(g, 0), day)


def _fee(c, year, age, key, day):
    left = max(0, c["until"] - year) + (0.5 if day is None or not _late(day) else 0.25)
    young = 1.6 if age <= 21 else 1.3 if age <= 24 else 1.0 if age <= 30 else 0.7
    return int(c["salary"] * 0.8 * left * young * (1.5 if key else 1.0) / 5000) * 5000


def _late(day):
    d = datetime.date.fromisoformat(day)
    return d.month in (1, 2, 3, 4, 5, 6)                  # past the turn of the year, a contract has less left to run


def wage_ask(conn, pid, to_club):
    """The wage he wants to sign with `to_club`: at least what he earns, the market wage in your league, less to step
    up to a stronger league, more to step down."""
    ov, r = _attrs(conn, pid)
    m_to, _ = _meta_of_club(conn, to_club)
    c = contract(conn, pid)
    base = max(c["salary"] if c else 0, wage_of(m_to, ov))
    m_from, _ = _meta_of_club(conn, r["club_id"]) if r and r["club_id"] else ({}, None)
    step = (m_to.get("mean") or 8) - (m_from.get("mean") or (m_to.get("mean") or 8))
    factor = 0.9 if step > 0.3 else 1.25 if step < -0.3 else 1.05
    return int(base * factor / 1000) * 1000


# ---------------------------------------------------------------- the market
def market(conn, pos=None, age_max=None, fee_max=None, free_only=False, limit=200):
    """Players you could sign: free agents and European players under contract, best first."""
    me = club(conn)
    from .world import load_attrs, overall, age_on, world_meta
    meta = world_meta(conn)
    leagues = {t: lid for t, lid in conn.execute("SELECT team_id, league_id FROM teams")}
    names = {t: n for t, n in conn.execute("SELECT team_id, name FROM teams")}
    year = season_year(conn)
    on = datetime.date(year, 9, 15)
    day = get_state(conn)[0]
    rows = load_attrs(conn, "p.status IN ('active','injured') AND (p.team_id IS NULL OR p.club_id IS NOT NULL)")
    from .roster import group
    ovs = {pid: overall(r) for pid, r in rows.items()}
    depth = {}                                            # each club's order at each position, once
    for pid, r in rows.items():
        if r["club_id"]:
            depth.setdefault((r["club_id"], group(r["position"])), []).append((ovs[pid], pid))
    place = {}
    for k, lst in depth.items():
        lst.sort(reverse=True)
        for i, (_, pid) in enumerate(lst):
            place[pid] = i + 1
    ensure_tables(conn)
    cons = {r["player_id"]: dict(r) for r in conn.execute("SELECT * FROM eu_contracts")}
    cand = []
    for pid, r in rows.items():
        if r["club_id"] == me or r["team_id"] is not None:
            continue
        m = meta.get(leagues.get(r["club_id"])) if r["club_id"] else None
        if r["club_id"] and (not m or m.get("kind") != "europe"):
            continue                                      # juniors and college players are not for sale
        if free_only and r["club_id"]:
            continue
        age = age_on(r["birth_date"], on)
        if age < 18 or (age_max and age > age_max):
            continue
        if pos and r["position"] != pos and not (pos == "F" and r["position"] in ("C", "LW", "RW")):
            continue
        c = cons.get(pid)
        if r["club_id"] and (c is None or c["loan_from"]):
            continue
        g = group(r["position"])
        fee = _fee(c, year, age, place.get(pid, 99) <= KEY_SHARE[g], day) if r["club_id"] else 0
        if fee_max is not None and fee > fee_max:
            continue
        cand.append(dict(player_id=pid, pos=r["position"], age=age, nat=r["nationality"], overall=round(ovs[pid], 2),
                         club=names.get(r["club_id"]) if r["club_id"] else "Free agent", club_id=r["club_id"],
                         league=m["abbr"] if m else None, fee=fee, wage=c["salary"] if c else None,
                         until=c["until"] if c else None, loanable=bool(r["club_id"]) and place.get(pid, 0) > LOANABLE[g]))
    cand.sort(key=lambda x: -x["overall"])
    out = cand[:limit]
    for x in out:
        x["name"] = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (x["player_id"],)).fetchone()[0]
        x["ask"] = wage_ask(conn, x["player_id"], me) if me else None
    return out


def _loanable(conn, pid):
    p = conn.execute("SELECT club_id, birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    if not p or not p["club_id"]:
        return False
    c = contract(conn, pid)
    if c is None or c["loan_from"]:
        return False
    g, place, _ = _place(conn, p["club_id"], pid)
    return g is not None and place > LOANABLE[g]


def _check_common(conn, pid, me, day):
    from .leagues import Limits
    if not window_open(day):
        raise ValueError("The transfer window is shut (it runs 1 July to 15 February).")
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["status"] not in ("active", "injured"):
        raise ValueError("No such player.")
    if p["team_id"] is not None:
        raise ValueError("He belongs to an NHL organisation.")
    if p["club_id"] == me:
        raise ValueError("He already plays for you.")
    from .world import age_on
    lim = Limits(conn, datetime.date(season_year(conn), 9, 15))
    if not lim.ok(me, p["nationality"] or "", age_on(p["birth_date"], datetime.date(season_year(conn), 9, 15)), p["position"]):
        raise ValueError("Your import places are full: he would be one import too many for your league.")
    return p


def bid(conn, pid, fee, wage, years, day=None):
    """A transfer: his club agrees a fee (or he is a free agent), then he agrees terms. Returns (ok, text)."""
    me = club(conn)
    if me is None:
        raise ValueError("You do not run a European club.")
    day = day or get_state(conn)[0]
    p = _check_common(conn, pid, me, day)
    if not 1 <= years <= 4:
        raise ValueError("Contracts run one to four seasons.")
    fin = _budget(conn, me)
    ask_fee = fee_value(conn, pid, day)
    if ask_fee is None:
        raise ValueError("He is not for sale (on loan, or held by an NHL organisation).")
    fee = int(fee or 0) if ask_fee else 0
    if fee > fin["transfer_budget"]:
        raise ValueError(f"That fee is more than your transfer budget (€{fin['transfer_budget']:,}).")
    old = contract(conn, pid)
    if wage_bill(conn, me) - 0 + wage > fin["wage_budget"]:
        raise ValueError(f"His wage would take you past your wage budget (€{fin['wage_budget']:,}).")
    name = f"{p['first_name']} {p['last_name']}"
    seller = p["club_id"]
    if seller:
        g, place, n = _place(conn, seller, pid)
        if n - 1 < MIN_KEEP.get(g, 0):
            return _log(conn, pid, seller, me, "transfer", fee, wage, years, day, "refused",
                        f"{_club_name(conn, seller)} cannot spare him: they would be short at his position.")
        rng = random.Random(f"eu-bid-{pid}-{day}-{fee}")
        if fee < ask_fee * 0.97:
            note = (f"{_club_name(conn, seller)} want €{ask_fee:,} for him." if fee >= ask_fee * 0.6 else
                    f"{_club_name(conn, seller)} laugh it off. He is worth far more to them (they want €{ask_fee:,}).")
            return _log(conn, pid, seller, me, "transfer", fee, wage, years, day, "refused", note)
        if place <= 2 and rng.random() < 0.35:
            return _log(conn, pid, seller, me, "transfer", fee, wage, years, day, "refused",
                        f"{_club_name(conn, seller)} will not sell one of their best players at any price this season.")
    ask = wage_ask(conn, pid, me)
    if wage < ask * 0.98:
        return _log(conn, pid, seller, me, "transfer", fee, wage, years, day, "refused",
                    f"{name} turns down the terms: he wants €{ask:,} a season with you.")
    _move(conn, pid, me, day, until=contract_year(conn) + years - 1, salary=wage)
    conn.execute("UPDATE eu_finance SET transfer_budget=transfer_budget-? WHERE club_id=?", (fee, me))
    if seller:
        conn.execute("INSERT OR IGNORE INTO eu_finance (club_id, transfer_budget, wage_budget) VALUES (?,0,0)", (seller,))
        conn.execute("UPDATE eu_finance SET transfer_budget=transfer_budget+? WHERE club_id=?", (fee, seller))
    text = (f"{name} joins from {_club_name(conn, seller)} for €{fee:,}" if seller else f"{name} signs as a free agent") + \
        f": {years} season{'s' if years > 1 else ''} at €{wage:,}."
    _news(conn, day, text, me, pid, seller)
    return _log(conn, pid, seller, me, "transfer", fee, wage, years, day, "done", text)


def _before_season(day):
    d = datetime.date.fromisoformat(day)
    return 6 <= d.month <= 9


def loan(conn, pid, share=0.5, until=None, day=None):
    """Borrow a player until `until` (ISO date; default the season's end), paying `share` of his wage."""
    me = club(conn)
    if me is None:
        raise ValueError("You do not run a European club.")
    day = day or get_state(conn)[0]
    p = _check_common(conn, pid, me, day)
    if p["club_id"] is None:
        raise ValueError("He is a free agent: sign him instead.")
    c = contract(conn, pid)
    if c is None or c["loan_from"]:
        raise ValueError("He cannot be loaned (he is on loan already, or has no European contract).")
    end = season_end(conn)
    until = until or end
    if until > end:
        until = end
    share = max(0.0, min(1.0, float(share)))
    name = f"{p['first_name']} {p['last_name']}"
    lender = p["club_id"]
    if wage_bill(conn, me) + c["salary"] * share > _budget(conn, me)["wage_budget"]:
        raise ValueError("His share of wage would take you past your wage budget.")
    if not _loanable(conn, pid):
        return _log(conn, pid, lender, me, "loan", 0, int(c["salary"] * share), 0, day, "refused",
                    f"{_club_name(conn, lender)} need {name} in their lineup: no loan.")
    from .world import age_on
    age = age_on(p["birth_date"], datetime.date(season_year(conn), 9, 15))
    want = 0.5 if age <= 23 else 0.75                     # clubs lend the young cheaply: they want them to play
    if share < want:
        return _log(conn, pid, lender, me, "loan", 0, int(c["salary"] * share), 0, day, "refused",
                    f"{_club_name(conn, lender)} want you to pay {int(want * 100)}% of his wage.")
    m_me, _ = _meta_of_club(conn, me)
    m_him, _ = _meta_of_club(conn, lender)
    if (m_me.get("mean") or 8) < (m_him.get("mean") or 8) - 1.5 and age > 23:
        return _log(conn, pid, lender, me, "loan", 0, int(c["salary"] * share), 0, day, "refused",
                    f"{name} will not drop that far down for a loan.")
    conn.execute("UPDATE eu_contracts SET club_id=?, loan_from=?, loan_until=?, loan_share=? WHERE player_id=?",
                 (me, lender, until, share, pid))
    conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (me, pid))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES "
                 "(?, 'loan', ?, ?, ?, ?)", (day, pid, lender, me, f"on loan until {until}"))
    text = f"{name} joins on loan from {_club_name(conn, lender)} until {until} ({int(share * 100)}% of his wage)."
    _news(conn, day, text, me, pid, lender)
    return _log(conn, pid, lender, me, "loan", 0, int(c["salary"] * share), 0, day, "done", text)


def loan_out(conn, pid, to_club, share=0.5, until=None, day=None):
    """Lend one of your players to another European club (it takes him if it has room and he would play there)."""
    me = club(conn)
    day = day or get_state(conn)[0]
    if not window_open(day):
        raise ValueError("The transfer window is shut (it runs 1 July to 15 February).")
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["club_id"] != me or p["team_id"] is not None:
        raise ValueError("He is not one of your players.")
    c = contract(conn, pid)
    if c is None or c["loan_from"]:
        raise ValueError("He is on loan to you; he cannot be loaned on.")
    to_club = int(to_club)
    if to_club not in {x["team_id"] for x in clubs_to_run(conn)} and not _meta_of_club(conn, to_club)[0].get("kind") == "europe":
        raise ValueError("Loans go to European clubs.")
    sq, rs = _squad(conn, to_club)
    ov, _ = _attrs(conn, pid)
    from .roster import group
    g = group(p["position"])
    better = sum(1 for o, _ in sq[g] if o > ov)
    if better >= {"F": 12, "D": 6, "G": 2}[g]:
        return _log(conn, pid, me, to_club, "loan out", 0, 0, 0, day, "refused",
                    f"{_club_name(conn, to_club)} have no place for him in their lineup.")
    until = min(until or season_end(conn), season_end(conn))
    conn.execute("UPDATE eu_contracts SET club_id=?, loan_from=?, loan_until=?, loan_share=? WHERE player_id=?",
                 (to_club, me, until, share, pid))
    conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (to_club, pid))
    text = f"{p['first_name']} {p['last_name']} goes on loan to {_club_name(conn, to_club)} until {until}."
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES "
                 "(?, 'loan', ?, ?, ?, ?)", (day, pid, me, to_club, f"on loan until {until}"))
    return _log(conn, pid, me, to_club, "loan out", 0, 0, 0, day, "done", text)


def recall(conn, pid, day=None):
    """Bring a player you lent back early."""
    me = club(conn)
    c = contract(conn, pid)
    if c is None or c["loan_from"] != me:
        raise ValueError("He is not out on loan from you.")
    _return_loan(conn, pid, day or get_state(conn)[0])
    return "He is back."


def release(conn, pid, day=None):
    """Let a player go: the rest of his contract is paid out (it comes off your transfer budget)."""
    me = club(conn)
    day = day or get_state(conn)[0]
    c = contract(conn, pid)
    if c is None or c["club_id"] != me or c["loan_from"]:
        raise ValueError("He is not one of your contracted players.")
    left = max(1, c["until"] - contract_year(conn) + 1)
    cost = int(c["salary"] * left * 0.5)
    conn.execute("UPDATE eu_finance SET transfer_budget=transfer_budget-? WHERE club_id=?", (cost, me))
    conn.execute("DELETE FROM eu_contracts WHERE player_id=?", (pid,))
    conn.execute("UPDATE players SET club_id=NULL WHERE player_id=?", (pid,))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, detail) VALUES (?, 'release', ?, ?, ?)",
                 (day, pid, me, f"released (paid €{cost:,})"))
    return f"Released. Paying out half of what was left on his deal: €{cost:,}."


def renew(conn, pid, wage, years, day=None):
    """Extend one of your players: he signs if the wage is what he wants (his market wage, more if he is your best)."""
    me = club(conn)
    c = contract(conn, pid)
    if c is None or c["club_id"] != me or c["loan_from"]:
        raise ValueError("He is not one of your contracted players.")
    if not 1 <= years <= 4:
        raise ValueError("Contracts run one to four seasons.")
    ask = renew_ask(conn, pid)
    if wage < ask * 0.98:
        return False, f"He wants €{ask:,} a season."
    if wage_bill(conn, me) - c["salary"] + wage > _budget(conn, me)["wage_budget"]:
        raise ValueError("That would take you past your wage budget.")
    conn.execute("UPDATE eu_contracts SET until=?, salary=? WHERE player_id=?",
                 (max(c["until"], contract_year(conn) - 1) + years, int(wage), pid))
    return True, f"Extended: {years} more season{'s' if years > 1 else ''} at €{int(wage):,}."


def renew_ask(conn, pid):
    me = club(conn)
    ov, _ = _attrs(conn, pid)
    m, _ = _meta_of_club(conn, me)
    c = contract(conn, pid)
    g, place, _ = _place(conn, me, pid)
    return int(max(c["salary"] if c else 0, wage_of(m, ov)) * (1.15 if place <= 2 else 1.0) / 1000) * 1000


# ---------------------------------------------------------------- offers for your players (AI clubs)
def respond(conn, offer_id, accept, day=None):
    me = club(conn)
    day = day or get_state(conn)[0]
    o = conn.execute("SELECT * FROM eu_offers WHERE offer_id=?", (offer_id,)).fetchone()
    if o is None or o["from_club"] != me or o["status"] != "open":
        raise ValueError("No such open offer.")
    if not accept:
        conn.execute("UPDATE eu_offers SET status='rejected' WHERE offer_id=?", (offer_id,))
        return "You turn it down."
    if not window_open(day):
        conn.execute("UPDATE eu_offers SET status='expired' WHERE offer_id=?", (offer_id,))
        raise ValueError("The window has shut; the offer has lapsed.")
    pid = o["player_id"]
    _move(conn, pid, o["to_club"], day, until=contract_year(conn) + o["years"] - 1, salary=o["wage"])
    conn.execute("UPDATE eu_finance SET transfer_budget=transfer_budget+? WHERE club_id=?", (o["fee"], me))
    conn.execute("UPDATE eu_offers SET status='accepted' WHERE offer_id=?", (offer_id,))
    name = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    text = f"{name} leaves for {_club_name(conn, o['to_club'])}: €{o['fee']:,} to you."
    _news(conn, day, text, o["to_club"], pid, me)
    return text


def ai_offers(conn, day):
    """In the window, clubs from leagues as strong or stronger come in for your best players (about one offer every
    three weeks); an offer stands for a week."""
    me = club(conn)
    if me is None:
        return []
    conn.execute("UPDATE eu_offers SET status='expired' WHERE status='open' AND day<?",
                 ((datetime.date.fromisoformat(day) - datetime.timedelta(days=OFFER_DAYS)).isoformat(),))
    if not window_open(day):
        return []
    rng = random.Random(f"eu-offer-{day}")
    if rng.random() > 1 / 21:
        return []
    sq, rs = _squad(conn, me)
    pool = [pid for g in sq for _, pid in sq[g][:KEY_SHARE[g] + 2] if contract(conn, pid) and not contract(conn, pid)["loan_from"]]
    if not pool:
        return []
    pid = rng.choice(pool)
    m_me, lid_me = _meta_of_club(conn, me)
    buyers = [x for x in clubs_to_run(conn) if x["team_id"] != me and x["mean"] >= (m_me.get("mean") or 8) - 0.2]
    if not buyers:
        return []
    b = rng.choice(buyers)
    fee = int((fee_value(conn, pid, day) or 0) * rng.uniform(0.85, 1.45) / 5000) * 5000
    if fee <= 0:
        return []
    wage = wage_ask(conn, pid, b["team_id"])
    years = rng.choice((1, 2, 2, 3))
    conn.execute("INSERT INTO eu_offers (player_id, from_club, to_club, kind, fee, wage, years, day, status) VALUES "
                 "(?,?,?,'transfer',?,?,?,?,'open')", (pid, me, b["team_id"], fee, wage, years, day))
    name = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    add_message(conn, day, f"Offer for {name}", f"{b['name']} ({b['league']}) offer €{fee:,} for {name}, and would pay him "
                f"€{wage:,} a season. The offer stands for a week (Club > Offers).", sender="Sporting director")
    return [f"{b['name']} bid €{fee:,} for {name}"]


# ---------------------------------------------------------------- the calendar
def season_end(conn):
    """The last day of the current season's loans (30 April of the season's second year)."""
    return f"{season_year(conn) + 1}-04-30"


def daily(conn, day):
    """Each day of a European career: loans that end go home, AI clubs bid for your players, the board watches, and
    the rest of Europe does business in the window (also while you are between European jobs)."""
    if not active(conn) and not history(conn):
        return []
    ensure_tables(conn)
    for (pid,) in conn.execute("SELECT player_id FROM eu_contracts WHERE loan_from IS NOT NULL AND loan_until<?", (day,)).fetchall():
        _return_loan(conn, pid, day)
    from . import eu_world as EW
    if not active(conn):
        return EW.window_moves(conn, day) + EW.window_loans(conn, day)
    news = []
    news += ai_offers(conn, day)
    from . import eu_board as EB                              # the board, the review; the rest of Europe dealing
    news += EB.monthly(conn, day)
    news += EB.review(conn, day)
    news += EW.window_moves(conn, day)
    news += EW.window_loans(conn, day)
    return news


def summer(conn, day):
    out = _summer(conn, day)
    from . import eu_board as EB, eu_world as EW
    out += EW.nhl_signings(conn, day)                     # NHL clubs take your best under the transfer agreements
    EB.summer_vacancies(conn, day)
    return out


def _summer(conn, day):
    """1 July: contracts that ended run out. Your players without a new deal leave; AI clubs keep most of theirs (a
    new deal at the market wage) and let the rest go. New contracts for anyone who joined a club during the year."""
    if not active(conn) and not history(conn):
        return []
    ensure_tables(conn)
    for (pid,) in conn.execute("SELECT player_id FROM eu_contracts WHERE loan_from IS NOT NULL").fetchall():
        _return_loan(conn, pid, day)
    me = club(conn)
    _sync(conn)
    year = contract_year(conn) - 1              # the season that just ended
    from .world import world_meta, age_on, overall, load_attrs
    meta = world_meta(conn)
    gone_mine, gone, kept = [], 0, 0
    rows = conn.execute("SELECT * FROM eu_contracts WHERE until<=?", (year,)).fetchall()
    for c in rows:
        pid = c["player_id"]
        if c["club_id"] == me:
            gone_mine.append(conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0])
            _free(conn, pid, day, "out of contract")
            continue
        rng = random.Random(f"eu-renew-{pid}-{year}")
        r = load_attrs(conn, "p.player_id=?", (pid,)).get(pid)
        m, _ = _meta_of_club(conn, c["club_id"])
        if r is None or not m:
            conn.execute("DELETE FROM eu_contracts WHERE player_id=?", (pid,))
            continue
        old = age_on(r["birth_date"], datetime.date(year + 1, 9, 15)) >= 33
        weak = overall(r) < (m.get("mean") or 8) - 0.8
        if rng.random() < (0.45 if old or weak else 0.8):
            conn.execute("UPDATE eu_contracts SET until=?, salary=? WHERE player_id=?",
                         (year + rng.choice((1, 1, 2, 2, 3)), wage_of(m, overall(r)), pid))
            kept += 1
        else:
            _free(conn, pid, day, "out of contract")
            gone += 1
    ensure_contracts(conn)
    if me is not None:
        _budget(conn, me, reset=True)
    out = [f"European contracts: {kept} re-signed, {gone} free agents."]
    if gone_mine:
        add_message(conn, day, "Out of contract", "These players' contracts ran out and they have left:\n"
                    + "\n".join(f"- {n}" for n in gone_mine), sender="Sporting director")
    return out


def academy(conn, day):
    """Mid-September: a few 16-17-year-olds come up from the academy to your club."""
    me = club(conn)
    if me is None:
        return []
    from .world import gen_player, insert_generated, overall_of, pick_position, pick_nationality, _gen_mix, NAMES
    from .world import world_meta
    m, lid = _meta_of_club(conn, me)
    rng = random.Random(f"eu-academy-{me}-{day[:4]}")
    year = season_year(conn) + 1
    names = []
    for i in range(ACADEMY):
        pos = "G" if i == 0 and rng.random() < 0.3 else pick_position(rng)
        age = rng.choice((16, 17, 17))
        nat = pick_nationality(rng, _gen_mix(m))
        pl, at, prof = gen_player(rng, NAMES, nat, pos, age, year, (m.get("mean") or 8) - 1.6 + rng.uniform(-0.4, 0.6))
        pid = insert_generated(conn, pl, at, prof, me)
        conn.execute("INSERT OR REPLACE INTO eu_contracts (player_id, club_id, until, salary) VALUES (?,?,?,?)",
                     (pid, me, year + 2, 15_000))
        names.append(f"{pl['first_name']} {pl['last_name']} ({pos}, {age})")
    from . import eu_board as EB                        # September: the board's target for the new season
    EB.set_objectives(conn, day)
    add_message(conn, day, "The academy's new faces", "Up from the junior teams this season, on three-year academy deals:\n"
                + "\n".join(f"- {n}" for n in names) + "\nThey develop with the club; young players grow most with ice time "
                "(lend them to a lower league if they will not play).", sender="Academy director")
    return [f"Academy: {len(names)} youngsters join {_club_name(conn, me)}"]


# ---------------------------------------------------------------- helpers
def _sync(conn):
    """Contracts follow the world: retired players' deals end; a player the world moved (a junior who aged out, a
    player placed at a new club) is re-papered at his new club when the next contracts are written."""
    ensure_tables(conn)
    conn.execute("DELETE FROM eu_contracts WHERE player_id IN (SELECT player_id FROM players WHERE status='retired' OR "
                 "team_id IS NOT NULL OR club_id IS NULL)")
    conn.execute("DELETE FROM eu_contracts WHERE loan_from IS NULL AND club_id <> (SELECT club_id FROM players p WHERE "
                 "p.player_id=eu_contracts.player_id)")


def _club_name(conn, t):
    if not t:
        return "free agency"
    r = conn.execute("SELECT name FROM teams WHERE team_id=?", (t,)).fetchone()
    return r[0] if r else "?"


def _move(conn, pid, to, day, until, salary):
    frm = conn.execute("SELECT club_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (to, pid))
    conn.execute("INSERT OR REPLACE INTO eu_contracts (player_id, club_id, until, salary) VALUES (?,?,?,?)",
                 (pid, to, until, int(salary)))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES "
                 "(?, 'transfer', ?, ?, ?, ?)", (day, pid, frm, to, f"transfer (to {until})"))


def _free(conn, pid, day, why):
    frm = conn.execute("SELECT club_id FROM players WHERE player_id=?", (pid,)).fetchone()
    conn.execute("DELETE FROM eu_contracts WHERE player_id=?", (pid,))
    conn.execute("UPDATE players SET club_id=NULL WHERE player_id=? AND team_id IS NULL", (pid,))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, detail) VALUES (?, 'release', ?, ?, ?)",
                 (day, pid, frm[0] if frm else None, why))


def _return_loan(conn, pid, day):
    c = contract(conn, pid)
    if not c or not c["loan_from"]:
        return
    conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (c["loan_from"], pid))
    conn.execute("UPDATE eu_contracts SET club_id=loan_from, loan_from=NULL, loan_until=NULL, loan_share=NULL WHERE player_id=?", (pid,))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES "
                 "(?, 'loan', ?, ?, ?, 'loan over')", (day, pid, c["club_id"], c["loan_from"]))


def _news(conn, day, text, team, pid, other):
    from .events import emit
    emit(conn, "PLAYER_SIGNED", day, text, team_id=team, player_id=pid, other_team_id=other, importance=1, europe=True)


def _log(conn, pid, frm, to, kind, fee, wage, years, day, status, note):
    conn.execute("INSERT INTO eu_offers (player_id, from_club, to_club, kind, fee, wage, years, day, status, note) VALUES "
                 "(?,?,?,?,?,?,?,?,?,?)", (pid, frm, to, kind, fee, wage, years, day, status, note))
    return status == "done", note


# ---------------------------------------------------------------- the Club screen
def view(conn):
    me = club(conn)
    from . import eu_board as EB
    if me is None:
        return dict(active=False, clubs=clubs_to_run(conn), jobs=EB.jobs(conn))
    ensure_contracts(conn)
    from .world import load_attrs, overall, age_on
    from . import leagues as LG
    day = get_state(conn)[0]
    year = season_year(conn)
    m, lid = _meta_of_club(conn, me)
    fin = _budget(conn, me)
    rs = load_attrs(conn, "p.club_id=? AND p.status IN ('active','injured')", (me,))
    squad = []
    for pid, r in rs.items():
        c = contract(conn, pid) or {}
        nm = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        squad.append(dict(player_id=pid, name=nm, pos=r["position"], age=age_on(r["birth_date"], datetime.date(year, 9, 15)),
                          renew_ask=renew_ask(conn, pid) if c and not c.get("loan_from") else None,
                          nat=r["nationality"], overall=round(overall(r), 2), wage=c.get("salary"), until=c.get("until"),
                          loan_from=_club_name(conn, c["loan_from"]) if c.get("loan_from") else None, loan_until=c.get("loan_until"),
                          nhl=r["team_id"] is not None, status=r["status"]))
    order = {"G": 0, "D": 1}
    squad.sort(key=lambda x: (order.get(x["pos"], 2), -x["overall"]))
    out_on_loan = [dict(player_id=r[0], name=r[1], club=_club_name(conn, r[2]), until=r[3]) for r in conn.execute(
        "SELECT c.player_id, p.first_name||' '||p.last_name, c.club_id, c.loan_until FROM eu_contracts c JOIN players p USING (player_id) "
        "WHERE c.loan_from=?", (me,))]
    table = LG.standings(conn, lid, year) if lid in LG.leagues(conn) else []
    pos = next((r["rank"] for r in table if r["team_id"] == me), None) if any(r["gp"] for r in table) else None
    offers = [dict(offer_id=o["offer_id"], player=conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?",
                                                                (o["player_id"],)).fetchone()[0], player_id=o["player_id"],
                   club=_club_name(conn, o["to_club"]), fee=o["fee"], wage=o["wage"], years=o["years"], day=o["day"])
              for o in conn.execute("SELECT * FROM eu_offers WHERE from_club=? AND status='open' ORDER BY day DESC", (me,))]
    history = [dict(day=o["day"], kind=o["kind"], status=o["status"], note=o["note"]) for o in conn.execute(
        "SELECT * FROM eu_offers WHERE (to_club=? OR from_club=?) AND note IS NOT NULL ORDER BY offer_id DESC LIMIT 25", (me, me))]
    lend_to = [dict(team_id=x["team_id"], name=x["name"], league=x["league"]) for x in clubs_to_run(conn)
               if x["team_id"] != me and x["mean"] <= (m.get("mean") or 8)]
    return dict(active=True, club_id=me, name=_club_name(conn, me), league=m.get("abbr"), league_id=lid, place=pos, lend_to=lend_to,
                board=EB.board(conn), jobs=EB.jobs(conn),
                clubs_in_league=len(table), window=window_open(day), budget=fin, wage_bill=wage_bill(conn, me), squad=squad,
                out_on_loan=out_on_loan, offers=offers, history=history, season=year)
