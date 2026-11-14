"""The board of the European club you run, and the European job market (v61; docs/EUROPE.md).

Objective   each season the board expects a place from the squad's strength: its rank on paper in the league, plus
            one place of slack ("finish in the top N"); a club strong enough on paper is also told to win the title.
Confidence  0-100, 60 on arrival. On the first of each month in the season it moves by 3 for each place you stand
            above (or below) the target, at most 8 either way, and falls 5 if the wage bill is over budget.
The review  when your league's season is over: target met +15 (a title +25), missed by up to three places -10,
            by more -25. Reputation moves with it (+3 met, +6 title, -3 badly missed). At 20 or below you are
            sacked: the club's AI takes over and you are out of work.
Jobs        each summer clubs that finished three or more places below their strength rank part with their coach
            (four in ten of them) and look for one. A club wants a reputation from 20 (the weakest club of the
            weakest league) to 75 (the strongest club of the strongest); your chance is 50% at that reputation, 3%
            per point either way, between 3% and 97%. Each club interviews you once a month. While you have no
            European job you may take any club (a new career); once you have had one, you apply for openings.
"""
from __future__ import annotations

import datetime
import random

from .state import add_message, get_state


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS eu_board (club_id INTEGER PRIMARY KEY, season INTEGER, target INTEGER, "
                 "title INTEGER DEFAULT 0, confidence REAL, reviewed INTEGER DEFAULT 0, note TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS eu_vacancy (club_id INTEGER PRIMARY KEY, since TEXT)")


def _rank_on_paper(conn, club):
    from .europe import _meta_of_club
    from .world import load_attrs, overall
    _, lid = _meta_of_club(conn, club)
    strength = {}
    for (c,) in conn.execute("SELECT team_id FROM teams WHERE league_id=?", (lid,)):
        rs = load_attrs(conn, "p.club_id=? AND p.status IN ('active','injured')", (c,))
        top = sorted((overall(r) for r in rs.values()), reverse=True)[:20]
        strength[c] = sum(top) / len(top) if top else 0
    order = sorted(strength, key=lambda c: -strength[c])
    return order.index(club) + 1 if club in order else len(order) // 2, len(order), order


def set_objectives(conn, day=None, keep_confidence=True):
    """The board's target for the season (on arrival, and each September)."""
    from .europe import club, season_year, contract_year, _club_name
    me = club(conn)
    if me is None:
        return []
    ensure_tables(conn)
    day = day or get_state(conn)[0]
    rank, n, _ = _rank_on_paper(conn, me)
    target = min(n, rank + 1)
    title = rank == 1
    old = conn.execute("SELECT confidence FROM eu_board WHERE club_id=?", (me,)).fetchone()
    conf = old[0] if old and keep_confidence else 60.0
    season = contract_year(conn)
    conn.execute("INSERT OR REPLACE INTO eu_board (club_id, season, target, title, confidence, reviewed, note) VALUES (?,?,?,?,?,0,?)",
                 (me, season, target, 1 if title else 0, conf, None))
    text = (f"The squad is the strongest in the league on paper: the board expects the title, and at least a top-{target} finish."
            if title else f"The squad is {rank}{'st' if rank == 1 else 'nd' if rank == 2 else 'rd' if rank == 3 else 'th'} of {n} "
            f"on paper. The board expects a finish in the top {target}.")
    add_message(conn, day, "The board's expectations", text + " Keep the wage bill inside the budget.", sender="Club president")
    return [f"{_club_name(conn, me)}: the board wants a top-{target} finish"]


def board(conn):
    from .europe import club
    me = club(conn)
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM eu_board WHERE club_id=?", (me,)).fetchone() if me else None
    return dict(r) if r else None


def _place(conn, me):
    from . import leagues as LG
    from .europe import _meta_of_club, season_year
    _, lid = _meta_of_club(conn, me)
    if lid not in LG.leagues(conn):
        return None, 0
    t = LG.standings(conn, lid, season_year(conn))
    if not t or not any(r["gp"] for r in t):
        return None, len(t)
    return next((r["rank"] for r in t if r["team_id"] == me), None), len(t)


def monthly(conn, day):
    """The first of each month in the season: confidence follows the table and the budget."""
    from .europe import club, wage_bill, _budget
    me = club(conn)
    b = board(conn)
    if me is None or b is None or day[8:10] != "01" or day[5:7] in ("06", "07", "08"):
        return []
    place, n = _place(conn, me)
    if place is None:
        return []
    delta = max(-8.0, min(8.0, 3.0 * (b["target"] - place)))
    if wage_bill(conn, me) > _budget(conn, me)["wage_budget"]:
        delta -= 5
    conf = max(0.0, min(100.0, b["confidence"] + delta))
    conn.execute("UPDATE eu_board SET confidence=? WHERE club_id=?", (conf, me))
    if conf < 30 <= b["confidence"]:
        add_message(conn, day, "A word from the board", f"We are {place} of {n} and we expected the top {b['target']}. Results must "
                    "improve.", sender="Club president")
    return []


def review(conn, day):
    """When your league's season is over (champion crowned): the board's verdict."""
    from .europe import club, _meta_of_club, season_year, _club_name, leave
    from . import gm as GM
    me = club(conn)
    b = board(conn)
    if me is None or b is None or b["reviewed"]:
        return []
    _, lid = _meta_of_club(conn, me)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='lg_seasons'").fetchone():
        return []                                             # (a new save: the leagues have not played a day yet)
    r = conn.execute("SELECT phase, champion FROM lg_seasons WHERE league_id=? AND season=?", (lid, season_year(conn))).fetchone()
    if not r or r[0] != "done":
        return []
    place, n = _place(conn, me)
    champ = r[1] == me
    if place is None:
        return []
    if champ:
        d, rep, verdict = 25, 6, "Champions. The board is delighted."
    elif place <= b["target"]:
        d, rep, verdict = 15, 3, f"{place} of {n}: the target (top {b['target']}) was met."
    elif place <= b["target"] + 3:
        d, rep, verdict = -10, 0, f"{place} of {n}: short of the top {b['target']} the board wanted."
    else:
        d, rep, verdict = -25, -3, f"{place} of {n}: well short of the top {b['target']}."
    if b["title"] and not champ and place > 1:
        d -= 5
    conf = max(0.0, min(100.0, b["confidence"] + d))
    conn.execute("UPDATE eu_board SET confidence=?, reviewed=1, note=? WHERE club_id=?", (conf, verdict, me))
    if rep:
        GM.change_reputation(conn, rep, "European season")
    name = _club_name(conn, me)
    if conf <= 20:
        leave(conn)
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('gm_status', 'fired')")
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('eu_sacked', ?)", (f"{me}:{day}",))
        GM.change_reputation(conn, -5, "sacked")
        conn.execute("INSERT OR REPLACE INTO eu_vacancy VALUES (?,?)", (me, day))
        add_message(conn, day, "Relieved of your duties", f"{verdict} The board has decided to make a change. Thank you for your "
                    f"work at {name}. (European openings are on the Job Centre's Manage in Europe panel.)", sender="Club president")
        return [f"{name} sack their coach"]
    add_message(conn, day, "The season under review", f"{verdict} Board confidence: {round(conf)}/100.", sender="Club president")
    _expiring_reminder(conn, me, day)
    return []


def _expiring_reminder(conn, me, day):
    """With the season over: whose contract runs out on 1 July, and what each wants to stay (extend on the Squad tab)."""
    from .europe import renew_ask, contract_year
    year = contract_year(conn)
    rows = conn.execute("SELECT c.player_id, p.first_name||' '||p.last_name, p.position, c.salary FROM eu_contracts c JOIN players p "
                        "USING (player_id) WHERE c.club_id=? AND c.loan_from IS NULL AND c.until<=? ORDER BY c.salary DESC",
                        (me, year)).fetchall()
    if not rows:
        return
    add_message(conn, day, "Contracts running out",
                "These contracts end on 1 July. Extend the ones you want to keep before then (Club > Squad > Extend), or they "
                "leave as free agents:\n" + "\n".join(f"- {r[1]} ({r[2]}): earns €{r[3]:,}, wants about €{renew_ask(conn, r[0]):,}"
                                                     for r in rows), sender="Sporting director")


# ---------------------------------------------------------------- the European job market
def demand(conn, club_id):
    """The reputation a club wants: 20 for the weakest club of the weakest league .. 75 for the best of the best."""
    from .europe import european_leagues, _meta_of_club
    means = sorted(m["mean"] for m in european_leagues(conn).values())
    m, _ = _meta_of_club(conn, club_id)
    lp = means.index(m["mean"]) / max(1, len(means) - 1) if m.get("mean") in means else 0.5
    rank, n, _ = _rank_on_paper(conn, club_id)
    cp = 1 - (rank - 1) / max(1, n - 1)
    return round(20 + 55 * (0.65 * lp + 0.35 * cp))


def chance(rep, need):
    return round(max(0.03, min(0.97, 0.5 + (rep - need) * 0.03)), 2)


def vacancies(conn):
    ensure_tables(conn)
    from .europe import european_leagues
    lids = set(european_leagues(conn))
    return [r[0] for r in conn.execute("SELECT v.club_id FROM eu_vacancy v JOIN teams t ON t.team_id=v.club_id") if
            conn.execute("SELECT league_id FROM teams WHERE team_id=?", (r[0],)).fetchone()[0] in lids]


def sacked_by(conn, day=None):
    """The European club that sacked you, while it will not have you back (a year), else None."""
    r = conn.execute("SELECT value FROM pack_info WHERE key='eu_sacked'").fetchone()
    if not r:
        return None
    t, _, since = r[0].partition(":")
    day = day or get_state(conn)[0]
    if since:
        try:
            if (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(since)).days > 365:
                return None
        except ValueError:
            pass
    return int(t)


def free_choice(conn):
    """A new European career may take any club; once you have run one (or been sacked), you apply for openings."""
    from .europe import club
    if club(conn) is not None:
        return False
    return not conn.execute("SELECT 1 FROM pack_info WHERE key IN ('eu_sacked', 'eu_history')").fetchone()


def jobs(conn):
    from . import gm as GM
    from .europe import _club_name, _meta_of_club
    rep = GM.settings(conn)["reputation"]
    out = []
    burned = sacked_by(conn)
    for c in vacancies(conn):
        if c == burned:                                   # not the club that just sacked you
            continue
        need = demand(conn, c)
        tried = conn.execute("SELECT value FROM pack_info WHERE key=?", (f"eu_apply_{c}",)).fetchone()
        out.append(dict(team_id=c, name=_club_name(conn, c), league=_meta_of_club(conn, c)[0].get("abbr"), demand=need,
                        chance=chance(rep, need), last_applied=tried[0] if tried else None))
    out.sort(key=lambda x: -x["chance"])
    return dict(reputation=rep, jobs=out, free_choice=free_choice(conn))


def apply(conn, club_id, day=None):
    """Apply for a European opening: the club interviews you and decides at once (once a month per club)."""
    from . import gm as GM
    from . import europe as EU
    day = day or get_state(conn)[0]
    club_id = int(club_id)
    if club_id not in vacancies(conn):
        raise ValueError("That club is not looking for a coach.")
    if EU.club(conn) == club_id:
        raise ValueError("You already run that club.")
    if club_id == sacked_by(conn, day):
        raise ValueError(f"{EU._club_name(conn, club_id)} sacked you less than a year ago. They will not take you back.")
    key = f"eu_apply_{club_id}"
    last = conn.execute("SELECT value FROM pack_info WHERE key=?", (key,)).fetchone()
    if last and last[0][:7] == day[:7]:
        raise ValueError("They already interviewed you this month.")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (key, day))
    need = demand(conn, club_id)
    rep = GM.settings(conn)["reputation"]
    if random.Random(f"eu-job-{club_id}-{day[:7]}").random() >= chance(rep, need):
        add_message(conn, day, f"{EU._club_name(conn, club_id)} said no", f"They wanted a coach with a reputation around {need}; yours is "
                    f"{rep:.0f}. You can try again next month.", sender="Agent")
        return False
    old = EU.club(conn)
    if old is not None:
        conn.execute("INSERT OR REPLACE INTO eu_vacancy VALUES (?,?)", (old, day))
    conn.execute("DELETE FROM eu_vacancy WHERE club_id=?", (club_id,))
    EU.start(conn, club_id, day, hired=True)
    return True


def summer_vacancies(conn, day):
    """Each summer some underachieving clubs part with their coach and look for a new one."""
    from . import leagues as LG
    from .europe import european_leagues, club, contract_year
    ensure_tables(conn)
    me = club(conn)
    rng = random.Random(f"eu-vacancies-{day[:4]}")
    year = contract_year(conn) - 1                       # the season just over
    made = 0
    for lid in european_leagues(conn):
        table = LG.standings(conn, lid, year)
        if not table:
            continue
        _, _, order = _rank_on_paper(conn, table[0]["team_id"])
        for r in table:
            t = r["team_id"]
            if t == me or t not in order:
                continue
            if r["rank"] - (order.index(t) + 1) >= 3 and rng.random() < 0.4:
                conn.execute("INSERT OR IGNORE INTO eu_vacancy VALUES (?,?)", (t, day))
                made += 1
    if made and me is None:
        add_message(conn, day, "European openings", f"{made} European clubs are looking for a coach (Job Centre, Manage in "
                    "Europe).", sender="Agent")
    return made
