"""The NHL entry draft, draft rights and entry-level contracts.

Eligibility: age 18-20 on 15 September of the draft year, never drafted, not under an NHL contract.
Order: non-playoff clubs worst-first (two lottery draws, a winner may move up at most 10 places), then playoff clubs
by round reached, champion last. Lottery odds are approximately the NHL's current table (settings below).
Clubs rank prospects through hs.game.scouting: a shared league-wide error, their own scouting error (staff quality)
and the biases of their director of amateur scouting (size, European exposure, Russians under KHL contract).
Round 1 is best player available, rounds 2-4 weigh positional need, rounds 5-7 chase upside; goalies wait.
The user drafts with `pick <player>` when on the clock; `offseason` auto-completes the rest.
Rights last until 1 June of draft year + 4 (drafted at 18) or + 3 (19+), the 2027+ rule in the 2026 CBA.
Entry-level contracts: 3 years if signed at 18-21, 2 at 22-23, 1 at 24+ (prior CBA); AAV up to the ELC maximum.
"""
from __future__ import annotations

import datetime
import json
import random

from ..schema import top_league_sql
from . import contracts as K
from .state import add_message, get_state, user_team
from .world import age_on, has_world, load_attrs, overall, season_year, world_meta

ROUNDS = 7
LOTTERY_ODDS = [18.5, 13.5, 11.5, 9.5, 8.5, 7.5, 6.5, 6.0, 5.0, 3.5, 3.0, 2.5, 2.0, 1.5, 0.5, 0.5]
LOTTERY_DRAWS, LOTTERY_MAX_JUMP = 2, 10
SCOUT_SD = 0.45
MAX_MOVE_UPS = 14            # draft-floor trades up per draft (real drafts see roughly 10-20 pick trades)


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS draft_picks (draft_year INTEGER NOT NULL, overall INTEGER NOT NULL, "
                 "round INTEGER NOT NULL, team_id INTEGER NOT NULL, player_id INTEGER, lottery_note TEXT, "
                 "PRIMARY KEY (draft_year, overall))")


def draft_year(conn):
    return season_year(conn) + 1


def perceived(conn, team_id, pid, potential=None, year=None):
    """What this club's scouts believe the player's ceiling is (see hs.game.scouting)."""
    from . import scouting as S
    year = year or draft_year(conn)
    r = load_attrs(conn, "p.player_id=?", (pid,)).get(pid)
    if r is None:
        return potential or 0.0
    h = conn.execute("SELECT height_cm FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    return S.Lens(conn, team_id, year).view(pid, overall(r), age_on(r["birth_date"], datetime.date(year, 9, 15)),
                                            r["position"] == "G", r["nationality"], h)


def eligible_rows(conn, year):
    """Draft-eligible players with what scouts can see: [dict(pid, pot, cur, age, pos, goalie, nat, height)]."""
    on = datetime.date(year, 9, 15)
    drafted = {r[0] for r in conn.execute("SELECT player_id FROM draft_picks WHERE player_id IS NOT NULL")} | \
              {r[0] for r in conn.execute("SELECT player_id FROM draft_rights")}
    signed = {r[0] for r in conn.execute("SELECT DISTINCT player_id FROM contracts")}
    pot = {r[0]: r[1] for r in conn.execute("SELECT player_id, potential FROM player_dev")}
    height = {r[0]: r[1] for r in conn.execute("SELECT player_id, height_cm FROM players WHERE team_id IS NULL AND "
                                               "status IN ('active','injured')")}
    out = []
    for pid, r in load_attrs(conn, "p.status IN ('active','injured') AND p.team_id IS NULL").items():
        if pid in drafted or pid in signed or pid not in pot:
            continue
        age = age_on(r["birth_date"], on)
        if 18 <= age <= 20:
            out.append(dict(pid=pid, pot=pot[pid], cur=overall(r), age=age, pos=r["position"],
                            goalie=r["position"] == "G", nat=r["nationality"], height=height.get(pid)))
    return out


def eligible(conn, year):
    return [(x["pid"], x["pot"], x["cur"]) for x in eligible_rows(conn, year)]


def _drafted_rows(conn, year):
    """This draft's picks so far, in the same shape as eligible_rows (for the pre-draft consensus order)."""
    ids = [r[0] for r in conn.execute("SELECT player_id FROM draft_picks WHERE draft_year=? AND player_id IS NOT NULL",
                                      (year,))]
    if not ids:
        return []
    on = datetime.date(year, 9, 15)
    rows = load_attrs(conn, f"p.player_id IN ({','.join('?' * len(ids))})", ids)
    hts = {r[0]: r[1] for r in conn.execute(f"SELECT player_id, height_cm FROM players WHERE player_id IN "
                                            f"({','.join('?' * len(ids))})", ids)}
    return [dict(pid=pid, pot=None, cur=overall(r), age=age_on(r["birth_date"], on), pos=r["position"],
                 goalie=r["position"] == "G", nat=r["nationality"], height=hts.get(pid)) for pid, r in rows.items()]


GOALIE_NEED = 0.34          # v46: a club drafts a goalie when it has two or fewer young goalies in the system


def _goalie_round(conn, year, team_id):
    """A club with enough young goalies may still take one it likes: from its own round (2-7), or not at all (30%)."""
    rng = random.Random(f"{get_state(conn)[1]}-{year}-goalie-round-{team_id}")
    return None if rng.random() < 0.3 else rng.randint(2, 7)


class _Board:
    """The draft as one club sees it: projections computed once per club, needs updated as it picks."""

    def __init__(self, conn, year, pool):
        from . import scouting as S
        self.S, self.conn, self.year, self.pool = S, conn, year, pool
        self.views, self.need, self.goalies, self.g_round = {}, {}, {}, {}
        seed = S._seed(conn)
        everyone = pool + _drafted_rows(conn, year)
        for x in everyone:
            x["consensus"] = S.consensus(conn, x, year, seed)
        for k, x in enumerate(sorted(everyone, key=lambda x: (-x["consensus"], x["pid"]))):
            x["expected_slot"] = k + 1           # where the league's consensus had him before the draft

    def proj(self, team_id):
        if team_id not in self.views:
            lens = self.S.Lens(self.conn, team_id, self.year)
            self.views[team_id] = (lens.style, {x["pid"]: lens.view(x["pid"], x["cur"], x["age"], x["goalie"], x["nat"],
                                                                     x["height"]) for x in self.pool})
            self.need[team_id] = self.S.needs(self.conn, team_id, self.year)
        return self.views[team_id]

    def choose(self, team_id, rnd, available):
        from .roster import group
        style, view = self.proj(team_id)
        need = self.need[team_id]
        took = self.goalies.setdefault(team_id, 0)
        # v46: a club takes a goalie only if it needs one (or he is a top-tier talent), and at most one a draft;
        # goalie projections are noisier and have more growth left, so unchecked they crowded out skaters
        def ok(x):
            if not x["goalie"]:
                return True
            if took:
                return False
            top = view[x["pid"]] >= self.S.GOALIE_TOP_TIER
            if rnd == 1:
                return top and need["G"] >= GOALIE_NEED
            if need["G"] >= GOALIE_NEED:
                return True
            gr = self.g_round.setdefault(team_id, _goalie_round(self.conn, self.year, team_id))
            return gr is not None and rnd >= gr and view[x["pid"]] >= self.S.GOALIE_TOP_TIER - 1.0
        pool = [x for x in available if ok(x)] or available
        best = max(pool, key=lambda x: (self.S.pick_score(view[x["pid"]], x["cur"], rnd, need[group(x["pos"])],
                                                          style, x["goalie"], x["age"]), -x["pid"]))
        if best["goalie"]:
            self.goalies[team_id] = took + 1
        g = group(best["pos"])
        target = self.S.NEED_TARGET[g]
        need[g] = max(0.0, need[g] - 1.0 / target)
        return best


def po_depth(conn, season_id):
    """{team: deepest playoff round reached} (1 = made it; the final counts as 9)."""
    po = {}
    for r in conn.execute("SELECT home_team_id, away_team_id, series_id FROM games WHERE game_type='PO' AND "
                          "season_id=?", (season_id,)):
        sid = r[2] or ""
        rnd = 9 if sid.startswith("Final") else int(sid[1]) if sid[:1] == "R" and sid[1:2].isdigit() else 1
        for t in (r[0], r[1]):
            po[t] = max(po.get(t, 0), rnd)
    return po


def order(conn):
    """Draft order for this summer: list of team ids, plus lottery notes."""
    from ..league import standings
    from ..league.season import db_rules
    season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    rules = db_rules(conn)
    rec, h2h = standings.table(conn, season_id)
    ranked = standings.rank(rec, h2h, rules)           # best first
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    ranked += [t for t in teams if t not in ranked]
    po = po_depth(conn, season_id)
    champ = conn.execute("SELECT value FROM pack_info WHERE key='champion'").fetchone()
    champ = int(champ["value"]) if champ else None
    from . import expansion as EX
    new = [t for t in EX.draft_slot_teams(conn, draft_year(conn)) if t in ranked]
    ranked = [t for t in ranked if t not in new]
    non_po = [t for t in reversed(ranked) if t not in po]           # worst first
    for t in new:                                                   # v45: an expansion club drafts with the third-worst odds
        non_po.insert(min(2, len(non_po)), t)
    playoff = sorted([t for t in ranked if t in po], key=lambda t: (po[t], -ranked.index(t)))
    if champ in playoff:
        playoff.remove(champ)
        playoff.append(champ)
    rng = random.Random(f"{get_state(conn)[1]}-{draft_year(conn)}-lottery")
    notes = []
    lottery = list(non_po)
    for draw in range(min(LOTTERY_DRAWS, len(lottery))):
        pool = lottery[draw:]
        odds = LOTTERY_ODDS[draw:draw + len(pool)] + [0.5] * max(0, len(pool) - len(LOTTERY_ODDS[draw:]))
        win = rng.choices(pool, odds[:len(pool)])[0]
        orig = lottery.index(win)
        target = max(draw, orig - LOTTERY_MAX_JUMP)
        lottery.insert(target, lottery.pop(orig))
        notes.append((target + 1, win, orig + 1))
    return lottery + playoff, notes


def start_draft(conn, day):
    """Create this year's pick list and run AI picks up to the user's first pick."""
    ensure_tables(conn)
    year = draft_year(conn)
    if conn.execute("SELECT 1 FROM draft_picks WHERE draft_year=?", (year,)).fetchone():
        return advance_picks(conn, day, stop_for_user=True)
    teams, notes = order(conn)
    from . import trades as TR
    sid = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    cond_lines = TR.resolve_conditions(conn, year, po_depth(conn, sid), day)       # v41: conditional picks
    owners = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='draft_pick_owners'").fetchone():
        owners = {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT round, original_team_id, owner_team_id FROM draft_pick_owners WHERE draft_year=?", (year,))}
    rows = []
    rolled = []
    from . import trades as TR
    TR.ensure_tables(conn)
    for rnd in range(ROUNDS):
        for k, t in enumerate(teams):
            owner = owners.get((rnd + 1, t), t)        # traded picks: the slot stays, the owner changes
            top = TR.protection(conn, year, rnd + 1, t) if owner != t else 0
            if top and k + 1 <= top and TR.pick_owner(conn, year + 1, rnd + 1, t) == t:
                # v39: protected - the original club keeps it, and next year's pick in that round goes instead
                conn.execute("INSERT OR REPLACE INTO draft_pick_owners VALUES (?,?,?,?,?)",
                             (year + 1, rnd + 1, t, owner, f"top-{top} protected {year} pick rolled over"))
                rolled.append((t, owner, rnd + 1, k + 1, top))
                owner = t
            rows.append((year, rnd * len(teams) + k + 1, rnd + 1, owner, None,
                         None if owner == t else f"from {t}"))
    conn.executemany("INSERT INTO draft_picks VALUES (?,?,?,?,?,?)", rows)
    abbr = {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}
    lines = [f"Lottery: {abbr[t]} moves from {f} to pick {p}." for p, t, f in notes]
    lines += cond_lines
    lines += [f"{abbr[t]}'s pick landed at {slot} (top-{top} protected): {abbr[t]} keep it and {abbr[o]} get their "
              f"{year + 1} round-{r} pick instead." for t, o, r, slot, top in rolled]
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)",
                 (f"draft_lottery_{year}", json.dumps([dict(pick=p, team=abbr[t], team_id=t, from_slot=f) for p, t, f in notes])))
    from .draft_floor import consolidate
    lines += consolidate(conn, year, day)
    rankings(conn, year)                                 # the outside views are fixed before the first pick
    # lottery night is its own event (defect 18): a story and a full message
    from .events import emit
    me = user_team(conn)
    mine = [x for x in notes if x[1] == me]
    if notes:
        top = min(notes)
        hl = f"Lottery night: {abbr[top[1]]} jump from {top[2]} to pick {top[0]}"
        body = " ".join(f"{abbr[t]} move from {f} to {p}." for p, t, f in sorted(notes))
        emit(conn, "MEDIA_STORY", day, hl, team_id=top[1], importance=3, headline=hl, body=body, tag="draft", kind="lottery")
    r1 = [r for r in conn.execute("SELECT overall, team_id FROM draft_picks WHERE draft_year=? AND round=1 ORDER BY overall", (year,))]
    my_first = [o for o, t in r1 if t == me]
    msg = ["The draft lottery has been drawn."] + [f"- {abbr[t]} move from {f} to pick {p}" for p, t, f in sorted(notes)]
    if me is not None:
        msg.append(f"Your first-round pick{'s' if len(my_first) != 1 else ''}: {', '.join('#' + str(o) for o in my_first) or 'none (traded)'}."
                   + (" You won a lottery draw." if mine else ""))
    msg.append("The top of the first round: " + ", ".join(f"{o}. {abbr[t]}" for o, t in r1[:8]) + ".")
    msg += [l for l in lines if not l.startswith("Lottery:")]
    msg.append("The draft room opens next: your scouts' board is on the Draft screen.")
    add_message(conn, day, "Draft lottery", "\n".join(msg))
    if live_draft(conn):
        return lines + ["The draft room is open: picks are made as you watch (Draft screen)."]
    return lines + advance_picks(conn, day, stop_for_user=True)


def live_draft(conn):
    """True when the UI runs the draft pick by pick (pack_info 'live_draft', set by the UI server)."""
    r = conn.execute("SELECT value FROM pack_info WHERE key='live_draft'").fetchone()
    return bool(r and r[0] == "1")


def draft_room(conn):
    """Everything the draft room shows."""
    ensure_tables(conn)
    year = draft_year(conn)
    me = user_team(conn)
    ab = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT team_id, abbr, name FROM teams")}
    picks = []
    for r in conn.execute("SELECT overall, round, team_id, player_id, lottery_note FROM draft_picks WHERE draft_year=? ORDER BY overall",
                          (year,)):
        d = dict(overall=r[0], round=r[1], team_id=r[2], abbr=ab.get(r[2], ("?",))[0], team=ab.get(r[2], ("", "?"))[1],
                 note=r[4], mine=r[2] == me)
        if r[3]:
            p = conn.execute("SELECT first_name||' '||last_name, position, nationality, birth_date FROM players WHERE "
                             "player_id=?", (r[3],)).fetchone()
            d.update(player_id=r[3], name=p[0], pos=p[1], nat=p[2],
                     age=age_on(p[3], datetime.date(year, 9, 15)) if p[3] else None)
        picks.append(d)
    nxt = next((p for p in picks if not p.get("player_id")), None)
    lot = conn.execute("SELECT value FROM pack_info WHERE key=?", (f"draft_lottery_{year}",)).fetchone()
    return dict(year=year, picks=picks, on_clock=nxt, mine_on_clock=bool(nxt and nxt["mine"]),
                my_picks=[p for p in picks if p["mine"]], my_left=sum(1 for p in picks if p["mine"] and not p.get("player_id")),
                lottery=json.loads(lot[0]) if lot else [], started=bool(picks), done=bool(picks) and nxt is None)


def make_pick(conn, year, overall_no, team_id, pid, day):
    conn.execute("UPDATE draft_picks SET player_id=? WHERE draft_year=? AND overall=?", (pid, year, overall_no))
    age = age_on(conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                 datetime.date(year, 9, 15))
    from .scouting import khl_years_left
    expires = year + (4 if age <= 18 else 3)
    khl = khl_years_left(conn, pid, year)
    if khl:
        expires = max(expires, year + khl + 1)        # rights held while he sees out his KHL contract
    conn.execute("INSERT OR REPLACE INTO draft_rights VALUES (?,?,?,?,?)", (pid, team_id, year, overall_no, expires))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, to_team_id, detail) VALUES "
                 "(?, 'draft', ?, ?, ?)", (day, pid, team_id, f"drafted {overall_no} overall ({year})"))
    from .events import emit, player_name, team_abbr
    emit(conn, "PLAYER_DRAFTED", day, f"{team_abbr(conn, team_id)} select {player_name(conn, pid)} "
         f"{overall_no} overall", team_id=team_id, player_id=pid, importance=2 if overall_no <= 32 else 1,
         overall=overall_no, draft_year=year)


def advance_picks(conn, day, stop_for_user=True, max_picks=None):
    """Make AI picks in order; stop when the user's club is on the clock (if stop_for_user), or after max_picks
    picks (the draft room shows them one at a time). Returns lines."""
    year = draft_year(conn)
    me = user_team(conn)
    pool = eligible_rows(conn, year)
    brd = _Board(conn, year, pool)
    available = list(pool)
    taken = 0
    lines = []
    done = conn.execute("SELECT payload FROM league_events WHERE event_type='TRADE_COMPLETED' AND payload LIKE "
                        "'%draft_move_up%' AND event_date=?", (day,)).fetchall()
    moves = len(done)
    round_moves = {}
    for (pl,) in done:
        slot = json.loads(pl).get("slot", 0)
        r = conn.execute("SELECT round FROM draft_picks WHERE draft_year=? AND overall=?", (year, slot)).fetchone()
        if r:
            round_moves[r[0]] = round_moves.get(r[0], 0) + 1
    floor_rng = random.Random(f"{get_state(conn)[1]}-{year}-floor-{taken}-{moves}-"
                              f"{conn.execute('SELECT COUNT(*) FROM draft_picks WHERE draft_year=? AND player_id IS NOT NULL', (year,)).fetchone()[0]}")
    for p in conn.execute("SELECT overall, round, team_id FROM draft_picks WHERE draft_year=? AND player_id IS NULL "
                          "ORDER BY overall", (year,)).fetchall():
        if not available:
            break
        owner = p["team_id"]
        from .draft_floor import MAX_PER_ROUND
        in_round = round_moves.get(p["round"], 0)
        if owner != me and moves < MAX_MOVE_UPS and in_round < MAX_PER_ROUND.get(p["round"], 1):
            from .draft_floor import try_move_up
            text = try_move_up(conn, year, p["overall"], owner, brd, available, day, floor_rng)
            if text:
                moves += 1
                round_moves[p["round"]] = in_round + 1
                lines.append(text)
                owner = conn.execute("SELECT team_id FROM draft_picks WHERE draft_year=? AND overall=?",
                                     (year, p["overall"])).fetchone()[0]
        if owner == me and stop_for_user:
            lines.append(f"You are on the clock with pick {p['overall']}: `draftboard` to see prospects, "
                         "`pick <player>` to choose.")
            break
        if max_picks is not None and taken >= max_picks:
            break
        choice = brd.choose(owner, p["round"], available)
        make_pick(conn, year, p["overall"], owner, choice["pid"], day)
        available.remove(choice)
        taken += 1
        if owner == me:
            n = conn.execute("SELECT first_name||' '||last_name||' ('||position||')' n FROM players WHERE player_id=?",
                             (choice["pid"],)).fetchone()["n"]
            lines.append(f"Auto-picked for you at {p['overall']}: {n}.")
    conn.commit()
    return [f"{taken} picks made."] + lines


def user_pick(conn, pid, day):
    ensure_tables(conn)
    year = draft_year(conn)
    me = user_team(conn)
    nxt = conn.execute("SELECT overall, team_id FROM draft_picks WHERE draft_year=? AND player_id IS NULL ORDER BY "
                       "overall LIMIT 1", (year,)).fetchone()
    if nxt is None or nxt["team_id"] != me:
        raise ValueError("You are not on the clock.")
    if pid not in {x[0] for x in eligible(conn, year)}:
        raise ValueError("That player is not available in this draft.")
    make_pick(conn, year, nxt["overall"], me, pid, day)
    if live_draft(conn):
        conn.commit()
        return [f"You selected {conn.execute('SELECT first_name||chr(32)||last_name FROM players WHERE player_id=?', (pid,)).fetchone()[0]}."]
    return advance_picks(conn, day, stop_for_user=True)


def finish_draft(conn, day):
    ensure_tables(conn)
    if conn.execute("SELECT 1 FROM draft_picks WHERE draft_year=?", (draft_year(conn),)).fetchone():
        return advance_picks(conn, day, stop_for_user=False)
    return []


def board(conn, team_id, limit=30):
    """Available prospects as this club's scouts see them: (pid, projected ceiling, current overall)."""
    return [(x["pid"], x["proj"], x["cur"]) for x in board_rows(conn, team_id, limit)]


def board_rows(conn, team_id, limit=30):
    """The club's draft board with what its scouts can see: projection, height, league, last season's numbers and
    the flags that make other clubs nervous (small, KHL contract, European exposure)."""
    from . import scouting as S
    year = draft_year(conn)
    pool = eligible_rows(conn, year)
    lens = S.Lens(conn, team_id, year)
    for x in pool:
        x["proj"] = lens.view(x["pid"], x["cur"], x["age"], x["goalie"], x["nat"], x["height"])
        # v36: ranked the way the club would pick in the first round (goalies need to be top tier to go that high)
        x["score"] = S.pick_score(x["proj"], x["cur"], 1, 0.0, lens.style, x["goalie"], x["age"])
    pool.sort(key=lambda x: (-x["score"], x["pid"]))
    out = []
    season = season_year(conn)
    for k, x in enumerate(pool[:limit]):
        last = "(SELECT MAX(season_start_year) FROM {t} WHERE player_id=? AND split='RS' AND season_start_year<=?)"
        st = conn.execute("SELECT SUM(gp), SUM(g), SUM(a) FROM skater_season_stats WHERE player_id=? AND split='RS' "
                          f"AND season_start_year={last.format(t='skater_season_stats')}",
                          (x["pid"], x["pid"], season)).fetchone()
        gst = conn.execute("SELECT SUM(gp), SUM(ga), SUM(sa) FROM goalie_season_stats WHERE player_id=? AND split='RS' "
                           f"AND season_start_year={last.format(t='goalie_season_stats')}",
                           (x["pid"], x["pid"], season)).fetchone()
        khl = S.khl_years_left(conn, x["pid"], year)
        flags = []
        if x["height"] and x["height"] <= 178 and not x["goalie"]:
            flags.append("undersized")
        if khl:
            flags.append(f"KHL contract to {year + khl}")
        exp = S.exposure_of(conn, x["pid"], x["nat"])
        if exp in ("nordic", "europe"):
            flags.append("seen less (Europe)")
        if x["age"] >= 19:
            flags.append("re-entry" if x["age"] == 19 else "overage")
        line = None
        if x["goalie"] and gst and gst[0]:
            line = f"{gst[0]} GP, {1 - (gst[1] or 0) / gst[2]:.3f}" if gst[2] else f"{gst[0]} GP"
        elif st and st[0]:
            line = f"{st[0]} GP, {st[1]}-{st[2]}-{st[1] + st[2]} ({(st[1] + st[2]) / st[0]:.2f}/gm)"
        out.append(dict(rank=k + 1, pid=x["pid"], proj=x["proj"], cur=x["cur"], age=x["age"], pos=x["pos"],
                        height=x["height"], nat=x["nat"], grade=S.grade(x["proj"], x["goalie"]), flags=flags, line=line))
    return out


# ---------------- rights and ELCs

def elc_terms(conn, pid, overall_pick, year):
    cr = K.crules(conn)
    age = age_on(conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0],
                 datetime.date(year, 9, 15))
    years = 3 if age <= 21 else 2 if age <= 23 else 1
    elc_max = cr.get("elc_max") or (1_000_000 if year <= 2026 else cr["min_salary"] + 175_000)
    pick = overall_pick or 200
    aav = elc_max if pick <= 10 else int(cr["min_salary"] + (elc_max - cr["min_salary"]) * max(0.0, 1 - pick / 100))
    return years, max(cr["min_salary"], int(round(aav / 5000) * 5000))


KHL_SEASON_END = (3, 1)       # the KHL regular season is over by March: players are freer to leave then
NCAA_SEASON_END = (3, 25)     # the college season ends in late March (the Frozen Four is in April)
P_KHL_IN_SEASON, P_KHL_AFTER = 0.3, 0.8


def sign_elc(conn, pid, team_id, day, khl_buyout=False):
    """Sign a draft pick to his entry-level deal. Defect 11:
    * a pick under a KHL contract can buy himself out of it, at a price: only with khl_buyout (the maximum entry-level
      deal and signing bonus, since he pays the KHL club), and he says yes far more often once the KHL regular
      season is over (March) than during it (30% / 80%; one ask a month);
    * an NCAA pick finishes his college season first (late March); signing after it, during the NHL season, starts
      his entry-level deal this season, so a year of it is used up at once."""
    r = conn.execute("SELECT * FROM draft_rights WHERE player_id=? AND team_id=?", (pid, team_id)).fetchone()
    if r is None:
        raise ValueError("Your club does not hold that player's rights.")
    year = K.signing_year(conn)
    d = datetime.date.fromisoformat(day)
    in_season = K.season_state(conn) in ("regular_season", "playoffs")
    from .scouting import khl_years_left
    khl = khl_years_left(conn, pid, year)
    club = conn.execute("SELECT l.abbr FROM players p JOIN teams t ON t.team_id=p.club_id JOIN leagues l ON l.league_id=t.league_id "
                        "WHERE p.player_id=?", (pid,)).fetchone()
    league = club[0] if club else ""
    ncaa_done = (d.month, d.day) >= NCAA_SEASON_END and d.month <= 8
    if league == "NCAA" and in_season and not ncaa_done:
        raise ValueError("He is finishing his college season (it ends in late March). Ask again then: signing after his "
                         "season starts his entry-level deal this year, so one year of it is used up.")
    premium = False
    if khl:
        if not khl_buyout:
            raise ValueError(f"He is under contract in the KHL until {year + khl}. He can buy himself out, but only for the "
                             "maximum entry-level deal: make the KHL buyout offer (more likely to work once the KHL season ends in March).")
        key = f"khl_ask_{pid}_{day[:7]}"
        if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
            raise ValueError("He has already answered this month. Ask again next month.")
        conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
        after = (d.month, d.day) >= KHL_SEASON_END and d.month <= 8
        if random.Random(f"khl-{pid}-{day[:7]}").random() > (P_KHL_AFTER if after else P_KHL_IN_SEASON):
            raise ValueError("He thanked you but is staying in the KHL for now" + ("" if after else ": he wants to finish the KHL season first")
                             + ". Ask again next month.")
        premium = True
    years, aav = elc_terms(conn, pid, r["overall_pick"], year)
    if premium:
        cr = K.crules(conn)
        aav = cr.get("elc_max") or max(aav, 975_000)
    # junior-age players go back to their junior club (and do not count against the contract limit);
    # everyone else turns pro with the AHL affiliate
    meta = world_meta(conn)
    p = conn.execute("SELECT p.birth_date, t.league_id FROM players p LEFT JOIN teams t ON t.team_id=p.club_id "
                     "WHERE p.player_id=?", (pid,)).fetchone()
    kind = meta.get(p["league_id"], {}).get("kind")
    age = age_on(p["birth_date"], datetime.date(year, 9, 15))
    from .roster import affiliate
    stay = kind == "junior" and age < 20
    K.sign_contract(conn, pid, team_id, years, aav, day, start_year=year, kind="entry_level", resign=False,
                    check=False, limit=not stay, detail="entry-level contract")
    conn.execute("UPDATE players SET status='prospect', club_id=CASE WHEN ? THEN club_id ELSE ? END WHERE player_id=?",
                 (int(stay), affiliate(conn, team_id), pid))
    from . import elc as E
    bonus, perf, lev = E.negotiate(conn, pid, r["overall_pick"], aav, years)
    E.record(conn, pid, year, bonus, perf, lev)
    if premium:
        conn.execute("UPDATE prospect_info SET khl_until=NULL WHERE player_id=?", (pid,))
        from .events import emit, player_name, team_abbr
        emit(conn, "PLAYER_SIGNED", day, f"{player_name(conn, pid)} buys out his KHL contract and signs his entry-level deal with "
             f"{team_abbr(conn, team_id)}", team_id=team_id, player_id=pid, importance=2, kind="khl_buyout", aav=aav, years=years)
    return years, aav


def rights_summer(conn, day):
    """AI clubs sign draftees who are ready (or whose rights are about to lapse and are worth keeping);
    lapsed rights are dropped. The user's expiring rights get the same treatment so nothing is lost silently."""
    if not has_world(conn):
        return []
    from . import college as CO                            # v46: rights to college players run with their eligibility
    CO.setup(conn)
    CO.extend_rights(conn)
    year = K.signing_year(conn)
    meta = world_meta(conn)
    ahl = next((m["mean"] for m in meta.values() if m["abbr"] == "AHL"), 9.2)
    echl = next((m["mean"] for m in meta.values() if m["abbr"] == "ECHL"), 8.3)
    me = user_team(conn)
    from .scouting import khl_years_left
    rows = conn.execute("SELECT * FROM draft_rights").fetchall()
    attrs = load_attrs(conn, "p.player_id IN (SELECT player_id FROM draft_rights)")
    signed = lapsed = 0
    from . import elc as E
    E.ensure_tables(conn)
    walk_rows = [r for r in rows if r["expires_year"] is not None and r["expires_year"] <= year
                 and E.leverage(conn, r["player_id"]) == "college" and r["player_id"] in attrs
                 and not khl_years_left(conn, r["player_id"], year)]

    def wants(r):
        return overall(attrs[r["player_id"]]) >= ahl - 0.8
    walked, walk_lines = E.college_refusals(conn, walk_rows, day, wants)
    E.warn_user(conn, day)
    for r in rows:
        if r["player_id"] in walked:
            continue
        a = attrs.get(r["player_id"])
        if a is None:
            continue
        ov = overall(a)
        age = age_on(a["birth_date"], datetime.date(year, 9, 15))
        expiring = r["expires_year"] is not None and r["expires_year"] <= year
        pick = r["overall_pick"] or 999
        from .scouting import khl_years_left
        if khl_years_left(conn, r["player_id"], year):
            continue                                  # still under KHL contract: rights are held, nothing to sign
        ready = (age >= 20 and ov >= ahl - 0.4) or (pick <= 32 and ov >= ahl - 1.2) or pick <= 3
        if r["team_id"] == me and not expiring:
            continue                                  # user decides with `elc` until the deadline
        if ready or (expiring and ov >= ahl - 0.8):
            try:
                sign_elc(conn, r["player_id"], r["team_id"], day)
            except (ValueError, K.CapError):
                if expiring:                          # at the contract limit: the rights lapse
                    conn.execute("DELETE FROM draft_rights WHERE player_id=?", (r["player_id"],))
                    lapsed += 1
                continue
            signed += 1
            if r["team_id"] == me:
                add_message(conn, day, "Prospect signed", f"Player #{r['player_id']} signed his entry-level contract "
                                                         "before his rights lapsed.")
        elif expiring:
            conn.execute("DELETE FROM draft_rights WHERE player_id=?", (r["player_id"],))
            lapsed += 1
    return [f"Prospects: {signed} entry-level contracts signed, {lapsed} sets of rights lapsed."] + walk_lines


# ---------------- v30 (defect 23): central scouting, the media mock and the consensus range
NA_NATIONS = {"CAN", "USA"}


def rankings(conn, year=None):
    """Three outside views of the class, computed once per draft year and kept (pack_info): central scouting (ranks
    within North American / international, skaters and goalies separately, as the league's bureau does), the media
    mock (one list, leans on production), and the consensus (the average of the bureau's combined order, the mock and
    the league's clubs) with a range in words. {pid: dict(csb, csb_list, media, consensus, range)}"""
    year = year or draft_year(conn)
    key = f"draft_rankings_{year}"
    r = conn.execute("SELECT value FROM pack_info WHERE key=?", (key,)).fetchone()
    if r:
        return {int(k): v for k, v in json.loads(r[0]).items()}
    pool = eligible_rows(conn, year)
    if not pool:
        return {}
    seed = get_state(conn)[1]
    rng_b, rng_m = random.Random(f"{seed}-csb-{year}"), random.Random(f"{seed}-media-{year}")
    from . import scouting as S
    season = season_year(conn)
    ppg = {}
    for x in pool:
        st = conn.execute("SELECT SUM(gp), SUM(g)+SUM(a) FROM skater_season_stats WHERE player_id=? AND split='RS' AND season_start_year="
                          "(SELECT MAX(season_start_year) FROM skater_season_stats WHERE player_id=? AND season_start_year<=?)",
                          (x["pid"], x["pid"], season)).fetchone()
        ppg[x["pid"]] = (st[1] or 0) / st[0] if st and st[0] else 0
    # the bureau sees the truth with modest noise; the media add production; clubs average their own lenses
    bureau = {x["pid"]: x["pot"] * 0.75 + x["cur"] * 0.25 + rng_b.gauss(0, 0.8) for x in pool}
    media = {x["pid"]: x["pot"] * 0.6 + x["cur"] * 0.2 + (1.0 if x["goalie"] else min(2.5, ppg[x["pid"]] * 1.6)) + rng_m.gauss(0, 1.1)
             for x in pool}
    clubs = [t for (t,) in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")][:12]
    club_view = {x["pid"]: 0.0 for x in pool}
    for t in clubs:
        lens = S.Lens(conn, t, year)
        for x in pool:
            club_view[x["pid"]] += lens.view(x["pid"], x["cur"], x["age"], x["goalie"], x["nat"], x["height"]) / max(1, len(clubs))
    order = lambda sc: {pid: i + 1 for i, pid in enumerate(sorted(sc, key=lambda p: (-sc[p], p)))}
    b_all, m_all, c_all = order(bureau), order(media), order(club_view)
    lists = {}
    for x in pool:
        lists.setdefault(("NA" if x["nat"] in NA_NATIONS else "INT", "G" if x["goalie"] else "S"), []).append(x["pid"])
    csb = {}
    for (region, kind), pids in lists.items():
        for i, pid in enumerate(sorted(pids, key=lambda p: (-bureau[p], p))):
            csb[pid] = (i + 1, f"{'North American' if region == 'NA' else 'International'} {'goalies' if kind == 'G' else 'skaters'}")
    avg = {x["pid"]: (b_all[x["pid"]] + m_all[x["pid"]] + c_all[x["pid"]]) / 3 for x in pool}
    cons = order({p: -v for p, v in avg.items()})
    out = {}
    for x in pool:
        pid = x["pid"]
        c = cons[pid]
        rng_txt = ("consensus 1st overall" if c == 1 else "consensus 2nd overall" if c == 2 else "top 3" if c <= 3 else "top 5" if c <= 5
                   else "top 10" if c <= 10 else "mid first round" if c <= 20 else "late first round" if c <= 32
                   else "second round" if c <= 64 else "third round" if c <= 96 else "later rounds")
        out[pid] = dict(csb=csb[pid][0], csb_list=csb[pid][1], media=m_all[pid], consensus=c, range=rng_txt)
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (key, json.dumps(out)))
    return out


# ---------------- v30 (defect 22): deals on draft day
def pick_deals(conn):
    """For the user, while the draft runs: what it would take to get the pick on the clock (from your picks, at the
    chart), and when you are on the clock, trade-down offers from clubs picking soon after (their pick plus another
    to make up the chart). Executed with pickswap (hs.game.draft_floor)."""
    from .draft_floor import chart
    year = draft_year(conn)
    me = user_team(conn)
    rows = conn.execute("SELECT overall, team_id FROM draft_picks WHERE draft_year=? AND player_id IS NULL ORDER BY overall", (year,)).fetchall()
    if not rows or me is None:
        return dict(buy=None, down=[])
    now, owner = rows[0]
    mine = [o for o, t in rows if t == me]
    out = dict(buy=None, down=[])
    if owner != me and mine:
        need = chart(now) * 1.1                              # they want a little more to give up the pick they are on
        singles = [o for o in mine if chart(o) >= need]
        if singles:
            give = [max(singles)]
        else:
            give = None
            for i, a in enumerate(mine):
                for b in mine[i + 1:]:
                    if chart(a) + chart(b) >= need and (give is None or chart(a) + chart(b) < sum(chart(x) for x in give)):
                        give = [a, b]
        if give:
            out["buy"] = dict(team_id=owner, abbr=team_abbr_(conn, owner), get=[now], give=give,
                              value_in=round(sum(chart(x) for x in give)), value_out=round(chart(now)))
    if owner == me:
        val = chart(now)
        seen = set()
        for o, t in rows[1:14]:
            if t == me or t in seen:
                continue
            seen.add(t)
            theirs = sorted((x for x, tt in rows if tt == t and x != o), reverse=True)   # their latest pick that covers it
            add = next((x for x in theirs if chart(o) + chart(x) >= val), None)
            if add:
                out["down"].append(dict(team_id=t, abbr=team_abbr_(conn, t), give=[now], get=[o, add],
                                        value_in=round(chart(o) + chart(add)), value_out=round(val)))
            if len(out["down"]) >= 4:
                break
    return out


def team_abbr_(conn, t):
    r = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()
    return r[0] if r else "?"
