"""Player development v40 (docs/DEVELOPMENT.md): growth through the season, and what drives it.

Before v40 every player changed once, in the summer, by an amount set by his age, his potential, your development
staff, his coachability and (where it goes) his training focus. v40 keeps that curve as the expected year
(worldgen.yearly_change) and adds:

When
  Young players grow during the season too: IN_SEASON_SHARE (40%) of a growing player's expected year comes in six
  monthly steps (1 November to 1 April), the rest in the summer. Decline (ageing) stays a summer thing.

What drives it (multipliers on growth; the product is clamped to 0.55-1.45)
  ice      NHL players 23 and under: ice time per game played against what a regular at his position gets, and how
           many of the club's games he dressed for (scratched kids stall). Others: 1.0.
  level    Where he plays against how good he is (league mean on the engine scale): challenged (-1.5 to +1.2 of the
           league mean) 1.04; too good for the league 0.90 ("not challenged"); overmatched 0.88. The NHL counts as
           challenging for anyone who dresses.
  character  professionalism and ambition: 1 + 0.015 (prof - 10) + 0.008 (ambition - 10).
  mentor   a mentor you assign (27+, on your NHL roster, professionalism 12+, at most two pupils): 1.10, 1.14 if his
           professionalism is 16+; a pupil 23 or under on the NHL roster with no mentor gets 1.03 from an older
           teammate of good character (one is usually around). A mentor may pass on professionalism (+1, 12% a month,
           never above his own); one with an ego of 15+ may pass on a bad habit instead (-1, 6%).
  training the club's training intensity: light 0.92 (fewer injuries, x0.88), normal 1.0, hard 1.08 (more injuries,
           x1.15).
  injury   time out: 1 - (days out in the period / days in it) x 0.8; a long injury (40+ days) at 27+ can cost a
           point of speed or acceleration.
  staff, coachability: as before (staff.development_multiplier, hidden.coach_factor).
Decline: professionalism slows it (x(1 - 0.02 (prof - 10)), 0.8-1.2); hard training x1.05.

Reports
  Every month your development coach writes: who moved most, and the calls to make: a kid who is not playing, a
  prospect too good for his league, one in over his head, an injury costing him development. dev_log keeps every
  step with its factors (the player's Development tab and the Development screen read it).
"""
from __future__ import annotations

import datetime
import json
import random

from .state import add_message, get_state, user_team

IN_SEASON_SHARE = 0.40
GROWTH_NORM = 1.08          # calibration: growth spread over the year (and the factors) matches v39's yearly growth
TICK_MONTHS = (11, 12, 1, 2, 3, 4)
CLAMP = (0.55, 1.45)
LEVEL = dict(challenged=1.04, easy=0.90, over=0.88)
LEVEL_BAND = (-1.5, 1.2)
INTENSITY = {"light": (0.92, 0.88, 0.97), "normal": (1.0, 1.0, 1.0), "hard": (1.08, 1.15, 1.05)}  # growth, injuries, decline
MENTOR_F, MENTOR_F_TOP, NATURAL_MENTOR_F = 1.10, 1.14, 1.03
MENTOR_MIN_AGE, MENTOR_MIN_PROF, MENTOR_MAX = 27, 12, 2
PUPIL_MAX_AGE = 23
P_RUB_OFF, P_BAD_HABIT = 0.12, 0.06
EXPECTED_TOI = {"F": 15.0 * 60, "D": 19.0 * 60, "G": 60.0 * 60}


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS dev_log (player_id INTEGER, day TEXT, kind TEXT, delta REAL, ca_before REAL, "
                 "ca_after REAL, factors TEXT, PRIMARY KEY (player_id, day, kind))")
    conn.execute("CREATE TABLE IF NOT EXISTS mentors (pupil_id INTEGER PRIMARY KEY, mentor_id INTEGER, team_id INTEGER, since TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS team_training (team_id INTEGER PRIMARY KEY, intensity TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS dev_plan (player_id INTEGER, season INTEGER, base REAL, steps INTEGER DEFAULT 0, "
                 "PRIMARY KEY (player_id, season))")


# ---------------------------------------------------------------- settings
def intensity(conn, team):
    ensure_tables(conn)
    r = conn.execute("SELECT intensity FROM team_training WHERE team_id=?", (team,)).fetchone() if team else None
    return r[0] if r else "normal"


def set_intensity(conn, team, level):
    if level not in INTENSITY:
        raise ValueError("Training intensity: light, normal or hard.")
    ensure_tables(conn)
    conn.execute("INSERT OR REPLACE INTO team_training VALUES (?,?)", (team, level))


def injury_factor(conn, team):
    return INTENSITY[intensity(conn, team)][1] if team else 1.0


def _trait(conn, pid, k, default=10):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone():
        return default
    r = conn.execute(f"SELECT {k} FROM personality WHERE player_id=?", (pid,)).fetchone()
    return r[0] if r and r[0] is not None else default


def _age(conn, pid, on):
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    b = datetime.date.fromisoformat(b)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


# ---------------------------------------------------------------- mentors
def mentor_of(conn, pid):
    ensure_tables(conn)
    r = conn.execute("SELECT mentor_id FROM mentors WHERE pupil_id=?", (pid,)).fetchone()
    return r[0] if r else None


def pupils_of(conn, mid):
    ensure_tables(conn)
    return [r[0] for r in conn.execute("SELECT pupil_id FROM mentors WHERE mentor_id=?", (mid,))]


def assign_mentor(conn, team, pupil, mentor, day):
    from .events import player_name
    ensure_tables(conn)
    on = datetime.date.fromisoformat(day)
    p = conn.execute("SELECT team_id, position FROM players WHERE player_id=?", (pupil,)).fetchone()
    m = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (mentor,)).fetchone()
    if p is None or p[0] != team or m is None or m[0] != team:
        raise ValueError("Both players must be in your organisation.")
    if m[1] not in ("active", "injured"):
        raise ValueError("A mentor must be on your NHL roster.")
    if _age(conn, pupil, on) > PUPIL_MAX_AGE:
        raise ValueError(f"Mentoring is for players {PUPIL_MAX_AGE} and under.")
    if _age(conn, mentor, on) < MENTOR_MIN_AGE:
        raise ValueError(f"A mentor should be {MENTOR_MIN_AGE} or older.")
    if _trait(conn, mentor, "professionalism") < MENTOR_MIN_PROF:
        raise ValueError(f"{player_name(conn, mentor)} is not the example you want (professionalism under {MENTOR_MIN_PROF}).")
    if len([x for x in pupils_of(conn, mentor) if x != pupil]) >= MENTOR_MAX:
        raise ValueError(f"{player_name(conn, mentor)} already mentors {MENTOR_MAX} players.")
    conn.execute("INSERT OR REPLACE INTO mentors VALUES (?,?,?,?)", (pupil, mentor, team, day))
    return f"{player_name(conn, mentor)} will mentor {player_name(conn, pupil)}."


def end_mentor(conn, pupil):
    ensure_tables(conn)
    conn.execute("DELETE FROM mentors WHERE pupil_id=?", (pupil,))


def candidates(conn, team, day):
    """Players on your NHL roster who could mentor: [(pid, professionalism, pupils)]."""
    on = datetime.date.fromisoformat(day)
    out = []
    for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')", (team,)):
        pid = r[0]
        if _age(conn, pid, on) >= MENTOR_MIN_AGE and _trait(conn, pid, "professionalism") >= MENTOR_MIN_PROF:
            out.append((pid, _trait(conn, pid, "professionalism"), len(pupils_of(conn, pid))))
    return sorted(out, key=lambda x: -x[1])


def _clean_mentors(conn):
    """Pairs end when either player leaves the club, or the mentor leaves the NHL roster."""
    for pupil, mentor, team in conn.execute("SELECT pupil_id, mentor_id, team_id FROM mentors").fetchall():
        p = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pupil,)).fetchone()
        m = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (mentor,)).fetchone()
        if not p or not m or p[0] != team or m[0] != team or m[1] not in ("active", "injured"):
            conn.execute("DELETE FROM mentors WHERE pupil_id=?", (pupil,))


# ---------------------------------------------------------------- the factors
def _league_mean(conn, pid, meta, nhl_mean):
    """Mean overall of the league he plays in this season (engine scale), and its name."""
    r = conn.execute("SELECT p.status, p.team_id, p.club_id, t.league_id, l.abbr, l.level FROM players p LEFT JOIN teams t "
                     "ON t.team_id=COALESCE(p.club_id, p.team_id) LEFT JOIN leagues l ON l.league_id=t.league_id WHERE "
                     "p.player_id=?", (pid,)).fetchone()
    if r is None or r["league_id"] is None:
        return None, None
    if r["status"] in ("active", "injured") and r["team_id"] is not None and r["club_id"] in (None, r["team_id"]) \
            and (r["level"] in (None, 1)):
        return nhl_mean, "NHL"
    m = meta.get(r["league_id"])
    return (m.get("mean") if m else None), r["abbr"]


def _nhl_usage(conn, pid, team, since, until):
    """(games dressed share, mean ice time in seconds) in the club's NHL games between since and until."""
    if team is None:
        return None, None
    tg = conn.execute("SELECT COUNT(*) FROM games WHERE played=1 AND game_type='RS' AND game_date>? AND game_date<=? AND "
                      "(home_team_id=? OR away_team_id=?)", (since, until, team, team)).fetchone()[0]
    if not tg:
        return None, None
    r = conn.execute("SELECT COUNT(*), AVG(s.toi_sec) FROM player_game_stats s JOIN games g USING (game_id) WHERE s.player_id=? "
                     "AND g.game_date>? AND g.game_date<=? AND g.game_type='RS' AND s.team_id=?",
                     (pid, since, until, team)).fetchone()
    return (r[0] or 0) / tg, r[1] or 0.0


def _days_out(conn, pid, since, until):
    tot = 0
    a, b = datetime.date.fromisoformat(since), datetime.date.fromisoformat(until)
    for s, e in conn.execute("SELECT start_date, expected_return FROM injuries WHERE player_id=? AND expected_return>? AND "
                             "start_date<=?", (pid, since, until)):
        s, e = max(a, datetime.date.fromisoformat(s[:10])), min(b, datetime.date.fromisoformat(e[:10]))
        tot += max(0, (e - s).days)
    return tot


def factors(conn, pid, row, age, since, until, ctx):
    """{name: multiplier} for a growing player over [since, until]."""
    from ..game.roster import group
    f = {}
    team, g = row["team_id"], group(row["position"])
    period = max(1, (datetime.date.fromisoformat(until) - datetime.date.fromisoformat(since)).days)
    mean, where = _league_mean(conn, pid, ctx["meta"], ctx["nhl_mean"])
    if where == "NHL":
        share, toi = _nhl_usage(conn, pid, team, since, until)
        if share is not None and age <= 23:
            dressed = 0.6 + 0.4 * min(1.0, share / 0.8)
            minutes = 0.85 + 0.25 * min(1.0, (toi or 0) / EXPECTED_TOI[g]) if share > 0 else 0.85
            f["ice"] = round(dressed * minutes, 3)
        f["level"] = LEVEL["challenged"]
    elif mean is not None:
        d = ctx["overall"](row) - mean
        f["level"] = LEVEL["over"] if d < LEVEL_BAND[0] else LEVEL["easy"] if d > LEVEL_BAND[1] else LEVEL["challenged"]
    f["character"] = round(max(0.85, min(1.15, 1 + 0.015 * (_trait(conn, pid, "professionalism") - 10)
                                         + 0.008 * (_trait(conn, pid, "ambition") - 10))), 3)
    m = ctx["mentors"].get(pid)
    if m is not None:
        f["mentor"] = MENTOR_F_TOP if _trait(conn, m, "professionalism") >= 16 else MENTOR_F
    elif where == "NHL" and age <= PUPIL_MAX_AGE and ctx["natural"].get(team):
        f["mentor"] = NATURAL_MENTOR_F
    f["training"] = INTENSITY[intensity(conn, team)][0] if team else 1.0
    out = _days_out(conn, pid, since, until)
    if out:
        f["injury"] = round(max(0.2, 1 - 0.8 * out / period), 3)
    return f


def product(f):
    p = 1.0
    for v in f.values():
        p *= v
    return max(CLAMP[0], min(CLAMP[1], p))


def _context(conn, day):
    from . import world as W
    from ..worldgen import overall_of
    meta = W.world_meta(conn)
    rows = W.load_attrs(conn, f"p.status IN ('active','injured') AND p.team_id IN (SELECT team_id FROM teams WHERE "
                              f"{__import__('hs.schema', fromlist=['x']).top_league_sql()})")
    vals = [overall_of(r, r["position"]) for r in rows.values()]
    natural = {}
    on = datetime.date.fromisoformat(day)
    for pid, r in rows.items():
        if _age(conn, pid, on) >= 28 and _trait(conn, pid, "professionalism") >= 14:
            natural[r["team_id"]] = True
    ensure_tables(conn)
    _clean_mentors(conn)
    return dict(meta=meta, nhl_mean=sum(vals) / len(vals) if vals else 10.5, natural=natural,
                mentors={r[0]: r[1] for r in conn.execute("SELECT pupil_id, mentor_id FROM mentors")},
                overall=lambda r: overall_of(r, r["position"]))


# ---------------------------------------------------------------- applying a change
def _apply(conn, pid, row, delta, rng, age, ctx_scale):
    """Move one player by `delta` on the engine overall (the native ratings when the world has them)."""
    from . import ratings as RT
    from . import training as TR
    from ..attributes import RATING_COLS, derive
    from ..worldgen import apply_change, overall_of
    fz = TR.FOCUS.get(TR.focus_of(conn, pid), ())
    scale, ca, kscale = ctx_scale
    nat = RT.of(conn, pid) if scale else None
    before = overall_of(row, row["position"])
    if nat is not None:
        pos = row["position"]
        prev = dict(nat)
        nat = RT.develop(nat, pos, delta, rng, age, RT.focus_ratings(fz), kscale[pos == "G"], noise=0.0)
        nat["current_ability"] = RT.carry_ability(prev, nat, pos, scale, ca)
        nat["potential_ability"] = max(nat.get("potential_ability") or 0, nat["current_ability"])
        RT.write(conn, pid, nat, pos, prev=prev)
        new = {**row, **dict(conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone())}
        ca_b, ca_a = prev.get("current_ability"), nat.get("current_ability")
    else:
        from ..attributes import ALL_ATTRS
        new = apply_change(row, row["position"], delta, rng, age, fz)
        conn.execute(f"UPDATE player_attributes SET {', '.join(f'{a}=?' for a in ALL_ATTRS)} WHERE player_id=?",
                     [new.get(a) if new.get(a) != "" else None for a in ALL_ATTRS] + [pid])
        ca_b = ca_a = None
    after = overall_of(new, new["position"])
    return before, after, ca_b, ca_a


def _scale_ctx(conn):
    from . import ratings as RT
    scale, ca = RT.scale_of(conn)
    return scale, ca, {False: RT.engine_delta_scale(conn, "C"), True: RT.engine_delta_scale(conn, "G")} if scale else None


# ---------------------------------------------------------------- the monthly step
def is_tick(conn, day):
    from . import contracts as K
    d = datetime.date.fromisoformat(day)
    return d.day == 1 and d.month in TICK_MONTHS and K.season_state(conn) == "regular_season"


def monthly(conn, day):
    """1 Nov - 1 Apr: a sixth of IN_SEASON_SHARE of each growing player's expected year, times his factors.
    Returns (players moved, report lines)."""
    from . import world as W
    from . import contracts as K
    from ..worldgen import yearly_change
    ensure_tables(conn)
    W.ensure_profiles(conn)
    season = K.season_year(conn)
    seed = get_state(conn)[1]
    on = datetime.date(season + 1, 9, 15)
    d = datetime.date.fromisoformat(day)
    since = (d.replace(day=1) - datetime.timedelta(days=1)).replace(day=1).isoformat()
    ctx = _context(conn, day)
    sc = _scale_ctx(conn)
    prof = {r[0]: dict(potential=r[1], peak_age=r[2], decline_age=r[3], growth_rate=r[4], decline_rate=r[5])
            for r in conn.execute("SELECT * FROM player_dev")}
    rows = W.load_attrs(conn, "p.status IN ('active','injured','prospect') OR (p.team_id IS NULL AND p.club_id IS NOT NULL "
                              "AND p.status='active')")
    from .staff import development_multiplier
    from . import hidden as HD
    me = user_team(conn)
    dev_mult, logs, mine = {}, [], []
    for pid, r in rows.items():
        p = prof.get(pid)
        if p is None:
            continue
        age = W.age_on(r["birth_date"], on)
        if age > 26:
            continue
        plan = conn.execute("SELECT base, steps FROM dev_plan WHERE player_id=? AND season=?", (pid, season)).fetchone()
        if plan is None:
            rng0 = random.Random(f"{seed}-{season}-plan-{pid}")
            base = yearly_change(age, W.overall(r), p, rng0)
            conn.execute("INSERT INTO dev_plan VALUES (?,?,?,0)", (pid, season, base))
            plan = (base, 0)
        base, steps = plan
        if base <= 0 or steps >= len(TICK_MONTHS):
            continue
        f = factors(conn, pid, r, age, since, day, ctx)
        if r["team_id"] and age <= 24:
            key = (r["team_id"], r["position"] == "G")
            if key not in dev_mult:
                dev_mult[key] = development_multiplier(conn, *key)
            f["staff"] = round(dev_mult[key], 3)
            f["coachability"] = round(HD.coach_factor(HD.of(conn, pid)["coachability"]), 3)
        delta = base * IN_SEASON_SHARE / len(TICK_MONTHS) * product(f) * GROWTH_NORM
        rng = random.Random(f"{seed}-{day}-tick-{pid}")
        b, a, cab, caa = _apply(conn, pid, r, delta, rng, age, sc)
        conn.execute("UPDATE dev_plan SET steps=steps+1 WHERE player_id=? AND season=?", (pid, season))
        logs.append((pid, day, "month", a - b, cab, caa, json.dumps(f)))
        if me is not None and r["team_id"] == me:
            mine.append((pid, a - b, f, r, age))
    _mentor_rub_off(conn, day)
    conn.executemany("INSERT OR REPLACE INTO dev_log VALUES (?,?,?,?,?,?,?)", logs)
    lines = report(conn, day, mine) if me is not None else []
    return len(logs), lines


def _mentor_rub_off(conn, day):
    for pupil, mentor in conn.execute("SELECT pupil_id, mentor_id FROM mentors").fetchall():
        rng = random.Random(f"rub-{pupil}-{mentor}-{day}")
        mp, pp = _trait(conn, mentor, "professionalism"), _trait(conn, pupil, "professionalism")
        if _trait(conn, mentor, "ego") >= 15 and rng.random() < P_BAD_HABIT:
            conn.execute("UPDATE personality SET professionalism=MAX(1, professionalism-1) WHERE player_id=?", (pupil,))
        elif mp > pp and rng.random() < P_RUB_OFF:
            conn.execute("UPDATE personality SET professionalism=MIN(?, professionalism+1) WHERE player_id=?", (mp, pupil))


# ---------------------------------------------------------------- the summer
def summer_multiplier(conn, pid, row, age, delta, year, ctx):
    """For world.develop: the summer's share of a growing player's year, times the season's factors (the average of
    his monthly ones when he had any, else measured over the whole season); decline slowed by professionalism."""
    if delta < 0:
        prof = _trait(conn, pid, "professionalism")
        m = max(0.8, min(1.2, 1 - 0.02 * (prof - 10)))
        return m * INTENSITY[intensity(conn, row["team_id"])][2] if row["team_id"] else m
    share = 1.0
    plan = conn.execute("SELECT steps FROM dev_plan WHERE player_id=? AND season=?", (pid, year)).fetchone()
    if plan and plan[0]:
        share = 1 - IN_SEASON_SHARE * plan[0] / len(TICK_MONTHS)
    logs = [json.loads(r[0]) for r in conn.execute("SELECT factors FROM dev_log WHERE player_id=? AND kind='month' AND "
                                                    "day>=? AND day<=?", (pid, f"{year}-10-01", f"{year + 1}-06-30"))]
    if logs:
        f = {k: sum(x.get(k, 1.0) for x in logs) / len(logs) for k in set().union(*logs) if k not in ("staff", "coachability")}
    else:
        f = factors(conn, pid, row, age, f"{year}-10-01", f"{year + 1}-04-30", ctx)
    # injuries do not stop the summer's training
    f.pop("injury", None)
    return share * product(f) * GROWTH_NORM


def summer_log(conn, pid, day, delta, before, after):
    conn.execute("INSERT OR REPLACE INTO dev_log VALUES (?,?,?,?,?,?,?)", (pid, day, "summer", after - before, None, None, None))


def long_injury_cost(conn, day):
    """A long injury (40+ days) at 27 or older may cost a point of speed or acceleration when he comes back."""
    from . import ratings as RT
    out = []
    for pid, s, e in conn.execute("SELECT i.player_id, i.start_date, i.expected_return FROM injuries i JOIN players p "
                                  "USING (player_id) WHERE i.expected_return=? AND p.status='injured'", (day,)).fetchall():
        days = (datetime.date.fromisoformat(e[:10]) - datetime.date.fromisoformat(s[:10])).days
        if days < 40 or _age(conn, pid, datetime.date.fromisoformat(day)) < 27:
            continue
        rng = random.Random(f"injcost-{pid}-{day}")
        if rng.random() < min(0.6, days / 150):
            nat = RT.of(conn, pid)
            pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            if nat is not None and RT.scale_of(conn)[0]:
                k = rng.choice(("speed", "acceleration"))
                if nat.get(k):
                    prev = dict(nat)
                    nat[k] = max(1, nat[k] - 1)
                    RT.write(conn, pid, nat, pos, prev=prev)
                    out.append(pid)
    return out


# ---------------------------------------------------------------- the report
def report(conn, day, mine):
    """The development coach's monthly note on your organisation."""
    from .events import player_name
    from .state import staff_sender
    me = user_team(conn)
    if not mine:
        return []
    up = sorted(mine, key=lambda x: -x[1])[:3]
    down = [x for x in sorted(mine, key=lambda x: x[1]) if x[1] < 0][:2]
    calls = []
    for pid, d, f, r, age in mine:
        n = player_name(conn, pid)
        if f.get("ice") is not None and f["ice"] < 0.8:
            calls.append(f"{n} ({age}) is barely playing for us; at his age he needs minutes. A spell in the AHL would do more.")
        elif f.get("level") == LEVEL["easy"] and r["status"] == "prospect":
            calls.append(f"{n} ({age}) is too good for his league and is coasting. Worth a look with the big club?")
        elif f.get("level") == LEVEL["over"]:
            calls.append(f"{n} ({age}) is in over his head where he plays; a level down would help him grow.")
        if f.get("injury") is not None and f["injury"] < 0.6:
            calls.append(f"{n} lost most of the month to injury; it is costing him development.")
    lines = [f"{player_name(conn, pid)} {d:+.2f}" for pid, d, *_ in up if d > 0]
    body = "Our young players this month (overall on the 1-20 scale; 0.1 is a normal month for a prospect):\n" + \
        ("Most improved: " + "; ".join(lines) + ".\n" if lines else "") + \
        ("Going the wrong way: " + "; ".join(f"{player_name(conn, pid)} {d:+.2f}" for pid, d, *_ in down) + ".\n" if down else "") + \
        ("\nThings to decide:\n" + "\n".join("- " + c for c in calls[:6]) if calls else "\nNothing needs your call this month.") + \
        f"\n\nTraining intensity is {intensity(conn, me)}."
    add_message(conn, day, f"Development report: {datetime.date.fromisoformat(day).strftime('%B')}", body,
                sender=staff_sender(conn, "DEV", me), actions=[dict(label="Development centre", href="#development", primary=True)])
    return lines


# ---------------------------------------------------------------- views
def player_view(conn, pid):
    ensure_tables(conn)
    rows = [dict(day=r[0], kind=r[1], delta=round(r[2], 3), ca_before=r[3], ca_after=r[4],
                 factors=json.loads(r[5]) if r[5] else None)
            for r in conn.execute("SELECT day, kind, delta, ca_before, ca_after, factors FROM dev_log WHERE player_id=? "
                                  "ORDER BY day DESC LIMIT 24", (pid,))]
    return dict(log=rows, mentor=mentor_of(conn, pid), pupils=pupils_of(conn, pid))


FACTOR_WORDS = {"ice": "ice time", "level": "level of play", "character": "character", "mentor": "mentor",
                "training": "training", "injury": "injury", "staff": "coaches", "coachability": "coachability"}


def org_view(conn, day):
    """Every player 26 and under in your organisation: this season's change, the factors now, mentor."""
    from . import world as W
    from ..worldgen import overall_of
    from . import contracts as K
    ensure_tables(conn)
    me = user_team(conn)
    season = K.season_year(conn)
    on = datetime.date.fromisoformat(day)
    ctx = _context(conn, day)
    since = (on - datetime.timedelta(days=30)).isoformat()
    rows = W.load_attrs(conn, "p.team_id=? AND p.status IN ('active','injured','prospect')", (me,))
    out = []
    for pid, r in rows.items():
        age = W.age_on(r["birth_date"], on)
        if age > 26:
            continue
        f = factors(conn, pid, r, age, since, day, ctx)
        season_d = conn.execute("SELECT SUM(delta) FROM dev_log WHERE player_id=? AND kind='month' AND day>=?",
                                (pid, f"{season}-10-01")).fetchone()[0]
        last = conn.execute("SELECT delta FROM dev_log WHERE player_id=? AND kind='month' ORDER BY day DESC LIMIT 1",
                            (pid,)).fetchone()
        m = mentor_of(conn, pid)
        from .events import player_name
        out.append(dict(player_id=pid, age=age, overall=round(overall_of(r, r["position"]), 2),
                        month=round(last[0], 3) if last else None, season=round(season_d, 3) if season_d else None,
                        factors={k: v for k, v in f.items()}, outlook=round(product(f), 2),
                        mentor=dict(player_id=m, name=player_name(conn, m)) if m else None))
    return dict(players={x["player_id"]: x for x in out}, intensity=intensity(conn, me),
                mentors=[dict(player_id=p, name=__import__("hs.game.events", fromlist=["x"]).player_name(conn, p), professionalism=pr,
                              pupils=n) for p, pr, n in candidates(conn, me, day)], words=FACTOR_WORDS)
