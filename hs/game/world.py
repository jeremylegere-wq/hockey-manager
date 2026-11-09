"""The world below and around the NHL: development, ageing, retirement, lower-league seasons and player movement.

Leagues other than the NHL are simulated a season at a time: each player gets a stat line from
his overall versus the league's level, and clubs are kept staffed by moving unsigned players to the level they
can play at and by adding newcomers (fictional youth) each summer.

Career rules (from the design brief):
  * established NHLers (300+ NHL games) who are no longer NHL calibre mostly retire;
  * journeymen keep going in the AHL, ECHL and Europe, retiring by age or when they fall below every level.
League means, roster sizes and age ranges live in rules.json "world" (built by hs.tools.build_world).
"""
from __future__ import annotations

import datetime
import json
import math
import random
import statistics

from ..attributes import ALL_ATTRS
from ..leaguedata.world_2025_26 import NAMES, NATIONALITY_MIX
from ..schema import top_league_sql
from ..worldgen import (FILLER_OFFSET, age_mean_offset, apply_change, class_leagues, filler_profile, gen_player, make_draft_class,
                        make_profile, overall_of, pick_nationality, pick_position, yearly_change, youth_age)
from .state import add_message, get_state, user_team

ESTABLISHED_NHL_GP = 300
RETIRE_BY_AGE = [(29, 0.0), (31, 0.01), (33, 0.03), (35, 0.08), (36, 0.15), (37, 0.25), (38, 0.40), (39, 0.55),
                 (40, 0.75), (99, 0.95)]


# ---------------- helpers

def world_meta(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
    w = (json.loads(r["value"]).get("world") or {}) if r else {}
    return {int(k): v for k, v in (w.get("leagues") or {}).items()}


def has_world(conn):
    return bool(world_meta(conn))


def top_league_id(conn):
    return conn.execute(f"SELECT league_id FROM teams WHERE {top_league_sql()} LIMIT 1").fetchone()[0]


def season_year(conn):
    return conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]


def age_on(birth, on):
    b = datetime.date.fromisoformat(birth)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def _rng(conn, tag):
    return random.Random(f"{get_state(conn)[1]}-{season_year(conn)}-{tag}")


def load_attrs(conn, where="p.status <> 'retired'", args=()):
    """{pid: (row dict of player + attributes)} for players matching where."""
    rows = conn.execute(f"SELECT p.player_id, p.position, p.birth_date, p.team_id, p.club_id, p.status, "
                        f"p.nationality, a.* FROM players p JOIN player_attributes a USING (player_id) WHERE {where}",
                        args).fetchall()
    return {r["player_id"]: dict(r) for r in rows}


def overall(row):
    return overall_of(row, row["position"])


def club_league(conn):
    return {r["team_id"]: r["league_id"] for r in conn.execute("SELECT team_id, league_id FROM teams")}


def nhl_games(conn):
    top = top_league_id(conn)
    out = {}
    for t in ("skater_season_stats", "goalie_season_stats"):
        for pid, gp in conn.execute(f"SELECT player_id, SUM(gp) FROM {t} WHERE split='RS' AND league_id=? "
                                    f"GROUP BY player_id", (top,)):
            out[pid] = out.get(pid, 0) + (gp or 0)
    from . import career as CR                   # v41: NHL games before the save began
    for pid, p in CR.all_prior(conn).items():
        out[pid] = out.get(pid, 0) + (p["gp"] or 0)
    return out


def ensure_profiles(conn):
    """Give every active player a development profile (generated players already have one)."""
    year = season_year(conn)
    have = {r[0] for r in conn.execute("SELECT player_id FROM player_dev")}
    rows = load_attrs(conn)
    seed = get_state(conn)[1] if get_state(conn) else 1
    new = []
    for pid, r in rows.items():
        if pid in have:
            continue
        rng = random.Random(f"{seed}-profile-{pid}")
        age = age_on(r["birth_date"], datetime.date(year, 9, 15))
        prof = make_profile(rng, age, overall(r), r["position"])
        new.append((pid, prof["potential"], prof["peak_age"], prof["decline_age"], prof["growth_rate"],
                    prof["decline_rate"]))
    conn.executemany("INSERT INTO player_dev VALUES (?,?,?,?,?,?)", new)
    return len(new)


def insert_generated(conn, player, attrs, prof, club_id, team_id=None, status="active"):
    cur = conn.execute("INSERT INTO players (first_name, last_name, birth_date, position, shoots, height_cm, weight_kg, "
                       "nationality, team_id, status, club_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (player["first_name"], player["last_name"], player["birth_date"], player["position"],
                        player["shoots"], player["height_cm"], player["weight_kg"], player["nationality"], team_id,
                        status, club_id))
    pid = cur.lastrowid
    cols = ["player_id"] + ALL_ATTRS + ["potential"]
    vals = [pid] + [attrs.get(a) if attrs.get(a) != "" else None for a in ALL_ATTRS] + \
           [max(1, min(20, round(prof["potential"])))]
    conn.execute(f"INSERT INTO player_attributes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    conn.execute("INSERT INTO player_dev VALUES (?,?,?,?,?,?)", (pid, prof["potential"], prof["peak_age"],
                                                               prof["decline_age"], prof["growth_rate"],
                                                               prof["decline_rate"]))
    from . import ratings as RT                      # v38: the native ratings, from the generated engine attributes
    RT.ensure_table(conn)
    scale, ca = RT.scale_of(conn)
    from ..attributes import RATING_COLS, ratings_from_engine
    rt = ratings_from_engine(attrs, player["position"], scale, ca, overall=overall_of(attrs, player["position"]),
                             potential=prof["potential"])
    conn.execute(f"INSERT OR REPLACE INTO player_ratings (player_id, {', '.join(RATING_COLS)}) VALUES "
                 f"({', '.join('?' * (len(RATING_COLS) + 1))})", [pid] + [rt.get(c) for c in RATING_COLS])
    if scale:                                       # an imported world: the engine attributes follow the ratings
        RT.write(conn, pid, rt, player["position"])
    return pid


# ---------------- development

def develop(conn, day):
    """One summer of development/ageing for every active player. Snapshots attributes into attribute_history
    first. Returns (number changed, notable lines for the user's players)."""
    ensure_profiles(conn)
    year = season_year(conn)                # the season just finished; ages are for the next one
    on = datetime.date(year + 1, 9, 15)
    rows = load_attrs(conn)
    prof = {r[0]: dict(potential=r[1], peak_age=r[2], decline_age=r[3], growth_rate=r[4], decline_rate=r[5])
            for r in conn.execute("SELECT * FROM player_dev")}
    hist_cols = ["player_id", "season_start_year"] + ALL_ATTRS + ["potential"]
    conn.executemany(f"INSERT OR IGNORE INTO attribute_history ({', '.join(hist_cols)}) VALUES "
                     f"({', '.join('?' * len(hist_cols))})",
                     [[pid, year] + [r.get(a) for a in ALL_ATTRS] + [r.get("potential")] for pid, r in rows.items()])
    seed = get_state(conn)[1]
    me = user_team(conn)
    notes, updates = [], []
    dev_mult = {}
    from . import training as TR                     # v36: ceilings move a little each summer; training focus
    moved = TR.drift_potential(conn, year, seed)
    for pid, pot in conn.execute("SELECT player_id, potential FROM player_dev"):
        if pid in prof:
            prof[pid]["potential"] = pot
    if me is not None:
        for pid, d in moved:
            if rows.get(pid, {}).get("team_id") == me:
                n = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
                add_message(conn, day, "Scouting: a new read", f"Our development staff have changed their view of {n}: his ceiling "
                            + ("looks a lot higher than we thought." if d > 0 else "looks lower than we hoped."))
    focus = TR.all_focus(conn)
    from . import ratings as RT                      # v38: the native ratings layer
    from ..attributes import COMPOSITES, RATING_COLS, ability_of, derive, own_engine, ratings_from_engine
    RT.backfill(conn)
    scale, ca = RT.scale_of(conn)
    kscale = {False: RT.engine_delta_scale(conn, "C"), True: RT.engine_delta_scale(conn, "G")}
    native = {r[0]: {c: r[c] for c in RATING_COLS} for r in RT._q(conn, "SELECT * FROM player_ratings")}
    native_updates = []
    from . import development as DV                  # v40: the season's factors and the in-season share
    dctx = DV._context(conn, day)
    for pid, r in rows.items():
        p = prof.get(pid)
        if p is None:
            continue
        rng = random.Random(f"{seed}-{year}-develop-{pid}")
        age = age_on(r["birth_date"], on)
        before = overall(r)
        delta = yearly_change(age, before, p, rng)
        if (delta > 0 and age <= 27) or delta < 0:
            delta *= DV.summer_multiplier(conn, pid, r, age, delta, year, dctx)
        if delta > 0 and age <= 24 and r["team_id"]:
            key = (r["team_id"], r["position"] == "G")
            if key not in dev_mult:
                from .staff import development_multiplier
                dev_mult[key] = development_multiplier(conn, *key)
            delta *= dev_mult[key]
            from . import hidden as HD                   # v35: coachability
            delta *= HD.coach_factor(HD.of(conn, pid)["coachability"])
        fz = TR.FOCUS.get(focus.get(pid, "balanced"), ())
        nat = native.get(pid)
        if nat is not None and scale:                # v38, imported worlds: the ratings develop; the engine attributes follow
            pos = r["position"]
            prev = nat
            nat = RT.develop(nat, pos, delta, rng, age, RT.focus_ratings(fz), kscale[pos == "G"])
            nat["current_ability"] = RT.carry_ability(prev, nat, pos, scale, ca)
            new = derive(nat, pos, scale, ca)
            pot = p.get("potential")
            if pot is not None:
                nat["potential_ability"] = max(nat["current_ability"], ability_of(pot, ca, pos))
            native_updates.append([nat.get(c) for c in RATING_COLS] + [pid])
        else:                                        # worlds built on engine attributes: they develop; the ratings mirror them
            new = apply_change(r, r["position"], delta, rng, age, fz)
            if nat is not None:
                pos = r["position"]
                mirror = ratings_from_engine(new, pos, None, ca, overall=overall_of(new, pos), potential=p.get("potential"))
                fed = {k for e in own_engine(pos) for k in COMPOSITES[e]}
                nat.update({k: mirror[k] for k in fed | {"current_ability", "potential_ability"} if k in mirror})
                native_updates.append([nat.get(c) for c in RATING_COLS] + [pid])
        updates.append([new.get(a) if new.get(a) != "" else None for a in ALL_ATTRS] + [pid])
        if me and r["team_id"] == me:
            after = overall_of(new, r["position"])
            if abs(after - before) >= 0.3:
                notes.append((after - before, pid))
    conn.executemany(f"UPDATE player_attributes SET {', '.join(f'{a}=?' for a in ALL_ATTRS)} WHERE player_id=?",
                     updates)
    conn.executemany(f"UPDATE player_ratings SET {', '.join(f'{c}=?' for c in RATING_COLS)} WHERE player_id=?", native_updates)
    lines = []
    for d, pid in sorted(notes, key=lambda x: -abs(x[0]))[:8]:
        n = conn.execute("SELECT first_name||' '||last_name n FROM players WHERE player_id=?", (pid,)).fetchone()["n"]
        lines.append(f"{n} {'improved' if d > 0 else 'declined'} ({d:+.1f} overall)")
    if lines:
        add_message(conn, day, "Development report", "; ".join(lines))
    return len(updates), lines


# ---------------- retirement

def retirements(conn, day):
    """End-of-season retirements. Returns list of (pid, reason)."""
    year = season_year(conn)
    on = datetime.date(year + 1, 7, 1)
    rng = _rng(conn, "retire")
    rows = load_attrs(conn)
    gp = nhl_games(conn)
    meta = world_meta(conn)
    lvl_mean = sorted(v["mean"] for v in meta.values() if v["kind"] in ("farm", "minor", "europe")) or [8.3]
    floor_level = lvl_mean[0] - 1.0                      # below the weakest pro league
    nhl_vals = sorted(overall(r) for r in rows.values() if r["team_id"] and r["status"] in ("active", "injured"))
    replacement = nhl_vals[int(0.10 * len(nhl_vals))] if nhl_vals else 9.6
    under_contract = {r[0] for r in conn.execute("SELECT player_id FROM contracts WHERE start_year+years>?", (year + 1,))}
    out = []
    scheduled = set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='scheduled_retirements'").fetchone():
        scheduled = {r[0] for r in conn.execute("SELECT player_id FROM scheduled_retirements WHERE retire_on<=?",
                                                (datetime.date(year + 1, 9, 1).isoformat(),))}
    for pid, r in sorted(rows.items()):
        age = age_on(r["birth_date"], on)
        if pid in scheduled:
            out.append((pid, "announced retirement"))
            continue
        if age < 24:
            continue
        p = next(pr for a, pr in RETIRE_BY_AGE if age <= a)
        ov = overall(r)
        if gp.get(pid, 0) >= ESTABLISHED_NHL_GP and pid not in under_contract and ov < replacement:
            p = max(p, 0.65 if age >= 31 else 0.3)        # long-time NHLer no longer good enough: usually retires
            reason = "no longer NHL calibre"
        elif ov < floor_level and pid not in under_contract:
            p = max(p, 0.6)
            reason = "no more pro offers"
        else:
            reason = "age"
        if pid in under_contract and age < 39:
            p *= 0.15
        if rng.random() < p:
            out.append((pid, reason))
    me = user_team(conn)
    for pid, reason in out:
        team = rows[pid]["team_id"]
        conn.execute("UPDATE players SET status='retired', team_id=NULL, club_id=NULL WHERE player_id=?", (pid,))
        conn.execute("DELETE FROM contracts WHERE player_id=? AND start_year>?", (pid, year))
        conn.execute("UPDATE contracts SET years=? - start_year + 1 WHERE player_id=? AND start_year+years>?",
                     (year, pid, year + 1))
        conn.execute("DELETE FROM draft_rights WHERE player_id=?", (pid,))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                     "VALUES (?, 'retire', ?, ?, NULL, ?)", (day, pid, team, f"retired ({reason})"))
        from .events import emit, player_name
        emit(conn, "PLAYER_RETIRED", day, f"{player_name(conn, pid)} retired ({reason})", team_id=team, player_id=pid,
             importance=3 if gp.get(pid, 0) >= 800 else 2 if gp.get(pid, 0) >= ESTABLISHED_NHL_GP else 1,
             nhl_games=gp.get(pid, 0), reason=reason)
        if me and team == me:
            n = conn.execute("SELECT first_name||' '||last_name n FROM players WHERE player_id=?", (pid,)).fetchone()["n"]
            add_message(conn, day, "Retirement", f"{n} has retired ({reason}).")
    return out


# ---------------- lower-league seasons

# points a game for an average regular forward in each league (defencemen half); LOWER_Z per standard deviation of
# overall within the league. The best (z ~3) then score about: juniors 2.2, NCAA 1.6, AHL/ECHL 1.3-1.5, Europe 1.1-1.2
# points a game, which is where real league leaders sit (v27; before, a good NCAA player could score 4 a game).
LOWER_PPG = {"AHL": 0.45, "ECHL": 0.50, "KHL": 0.38, "SHL": 0.37, "NL": 0.42, "LIIGA": 0.40, "ELH": 0.40, "DEL": 0.40,
             "NCAA": 0.55, "OHL": 0.75, "WHL": 0.75, "QMJHL": 0.75}
LOWER_PPG_KIND = {"farm": 0.45, "minor": 0.50, "europe": 0.40, "college": 0.55, "junior": 0.75}
LOWER_Z = 0.36


def lower_league_season(conn, season_id):
    """Stat lines for every player in a non-NHL club this season (season-level simulation)."""
    year = conn.execute("SELECT start_year FROM seasons WHERE season_id=?", (season_id,)).fetchone()[0]
    key = f"lower_stats_{year}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return 0
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    meta = world_meta(conn)
    if not meta:
        return 0
    leagues = club_league(conn)
    rng = random.Random(f"{get_state(conn)[1]}-{year}-lower")
    rows = load_attrs(conn, "p.status <> 'retired' AND p.club_id IS NOT NULL")
    from . import leagues as LGS                     # v44: leagues that play real games have their own lines
    real = set(LGS.leagues(conn)) if LGS.active(conn) else set()
    by_club = {}
    for pid, r in rows.items():
        lid = leagues.get(r["club_id"])
        if lid in meta and lid not in real:
            by_club.setdefault(r["club_id"], []).append(r)
    sk, gl = [], []
    # scoring is relative to the league: each skater's overall as standard deviations from his league's skaters
    # (clipped), so a player far better than his league scores like that league's best, not like a cartoon
    spread = {}
    for club, members in by_club.items():
        lid = leagues[club]
        spread.setdefault(lid, []).extend(overall(r) for r in members if r["position"] != "G")
    spread = {lid: (statistics.fmean(v), statistics.pstdev(v) or 1.0) for lid, v in spread.items() if v}
    for club, members in sorted(by_club.items()):
        m = meta[leagues[club]]
        games = m["games"]
        mu, sd = spread.get(leagues[club], (m["mean"], 1.0))
        base = LOWER_PPG.get(m["abbr"], LOWER_PPG_KIND.get(m["kind"], 0.45))
        goalies = sorted([r for r in members if r["position"] == "G"], key=lambda r: -overall(r))
        starts = [0.65, 0.30, 0.05]
        for i, g in enumerate(goalies):
            gp = int(games * (starts[i] if i < 3 else 0.0) * rng.uniform(0.85, 1.1))
            if gp <= 0:
                continue
            sa = int(gp * rng.gauss(28, 1.5))
            sv = min(0.945, max(0.860, 0.902 + 0.012 * (overall(g) - m["mean"]) + rng.gauss(0, 0.006)))
            gl.append((g["player_id"], year, club, leagues[club], "RS", gp, gp * 3600, int(round(sa * (1 - sv))), sa))
        skaters = sorted([r for r in members if r["position"] != "G"], key=lambda r: -overall(r))
        for i, s in enumerate(skaters):
            share = 1.0 if i < 18 else 0.45 if i < 22 else 0.15
            gp = int(games * share * rng.uniform(0.75, 1.0))
            if gp <= 0:
                continue
            d = s["position"] == "D"
            z = max(-2.5, min(3.0, (overall(s) - mu) / sd))
            rate = base * (0.5 if d else 1.0) * math.exp(LOWER_Z * z) * (1.0 if i < 12 else 0.6)
            pts = max(0, int(round(rng.gauss(rate * gp, (rate * gp) ** 0.5 + 0.5))))
            g = int(round(pts * (0.25 if d else 0.45) * rng.uniform(0.7, 1.3)))
            g = min(g, pts)
            toi = int(gp * (60 * (20 if d else 15)) * (1.15 if i < 12 else 0.8))
            sk.append((s["player_id"], year, club, leagues[club], "RS", gp, g, pts - g, int(gp * rng.uniform(1.5, 3)), toi))
    _sim_champions(conn, by_club, leagues, meta, year, rng)
    conn.executemany("INSERT INTO goalie_season_stats (player_id, season_start_year, team_id, league_id, split, gp, "
                     "toi_sec, ga, sa) VALUES (?,?,?,?,?,?,?,?,?)", gl)
    conn.executemany("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, "
                     "a, sog, toi_sec) VALUES (?,?,?,?,?,?,?,?,?,?)", sk)
    return len(sk) + len(gl)


CHAMPION_K = 2.2        # v44: a season-at-a-time league's champion: P ~ exp(K x the club's strength), strength the mean
                        # overall of its best 12 forwards, 6 defencemen and starter (a club 0.3 better wins about twice as often)


def _sim_champions(conn, by_club, leagues, meta, year, rng):
    """v44: leagues simulated a season at a time still crown a champion (and a runner-up) each spring, drawn by club
    strength, so every league in the world has a champions list."""
    from . import leagues as LGS
    LGS.ensure_tables(conn)
    by_league = {}
    for club, members in by_club.items():
        sk = sorted((overall(r) for r in members if r["position"] != "G"), reverse=True)[:18]
        gk = max((overall(r) for r in members if r["position"] == "G"), default=None)
        if len(sk) < 10:
            continue
        s = sum(sk) / len(sk) + (0.15 * (gk - meta[leagues[club]]["mean"]) if gk is not None else -0.3)
        by_league.setdefault(leagues[club], []).append((s, club))
    day = f"{year + 1}-04-10"
    for lid, clubs in by_league.items():
        if len(clubs) < 2 or conn.execute("SELECT 1 FROM lg_seasons WHERE league_id=? AND season=?", (lid, year)).fetchone():
            continue
        best = max(s for s, _ in clubs)
        w = [math.exp(CHAMPION_K * (s - best)) for s, _ in clubs]
        champ = rng.choices([c for _, c in clubs], w)[0]
        rest = [(x, c) for x, c in zip(w, [c for _, c in clubs]) if c != champ]
        runner = rng.choices([c for _, c in rest], [x for x, _ in rest])[0]
        conn.execute("INSERT INTO lg_seasons (league_id, season, phase, champion, runner_up, finished) VALUES (?,?,'done',?,?,?)",
                     (lid, year, champ, runner, day))
        name = conn.execute("SELECT name FROM teams WHERE team_id=?", (champ,)).fetchone()[0]
        lname = meta[lid].get("short") or meta[lid]["abbr"]
        from .events import emit
        emit(conn, "LEAGUE_CHAMPION", day, f"{name} win the {lname} title", team_id=champ, other_team_id=runner,
             importance=1, league_id=lid, trophy=f"{lname} champions")


# ---------------- moving players to the level they can play at

def club_rosters(conn):
    out = {}
    for r in conn.execute("SELECT club_id, COUNT(*) n FROM players WHERE club_id IS NOT NULL AND status <> 'retired' "
                          "GROUP BY club_id"):
        out[r["club_id"]] = r["n"]
    return out


def age_out(conn, day):
    """Players too old for their junior/college league leave their club (they become unattached unless an NHL
    organisation holds them). Returns count."""
    meta = world_meta(conn)
    leagues = club_league(conn)
    on = datetime.date(season_year(conn) + 1, 9, 15)
    n = 0
    for r in conn.execute("SELECT player_id, birth_date, club_id, team_id, status FROM players WHERE club_id IS NOT NULL "
                          "AND status <> 'retired'").fetchall():
        m = meta.get(leagues.get(r["club_id"]))
        if not m or m["kind"] not in ("junior", "college"):
            continue
        if age_on(r["birth_date"], on) > m["age_max"]:
            new_club = None
            if r["team_id"]:            # signed by an NHL organisation: turns pro with its AHL club
                from .roster import affiliate
                new_club = affiliate(conn, r["team_id"])
            conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (new_club, r["player_id"]))
            conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) "
                         "VALUES (?, 'graduate', ?, ?, ?, ?)", (day, r["player_id"], r["club_id"], new_club,
                                                                 f"left {m['abbr']} (age)"))
            n += 1
    return n


def place_unattached(conn, day):
    """Unsigned players find the best level they can play at (journeymen bounce around the lower leagues);
    those below every level, or old, retire. Returns (placed, retired)."""
    meta = world_meta(conn)
    if not meta:
        return 0, 0
    year = season_year(conn)
    on = datetime.date(year + 1, 9, 15)
    rng = _rng(conn, "place")
    leagues = club_league(conn)
    clubs_by_league = {}
    for t, lid in leagues.items():
        if lid in meta:
            clubs_by_league.setdefault(lid, []).append(t)
    sizes = club_rosters(conn)
    rows = load_attrs(conn, "p.status IN ('active','injured') AND p.team_id IS NULL AND p.club_id IS NULL AND "
                            "p.player_id NOT IN (SELECT player_id FROM draft_rights)")
    pro = {r[0] for r in conn.execute("SELECT DISTINCT player_id FROM skater_season_stats s JOIN leagues l USING "
                                      "(league_id) WHERE COALESCE(l.level, 1) <= 3 UNION SELECT DISTINCT player_id "
                                      "FROM goalie_season_stats s JOIN leagues l USING (league_id) WHERE "
                                      "COALESCE(l.level, 1) <= 3")}
    lowest = min(m["mean"] for m in meta.values())
    from .leagues import Limits                        # v44: import and over-age limits
    limits = Limits(conn, on)
    placed = retired = 0
    from . import college as CO                        # v46: graduates and pros are not placed in college
    no_college = CO.no_college(conn)
    for pid, r in sorted(rows.items(), key=lambda kv: -overall(kv[1])):
        ov, age, nat = overall(r), age_on(r["birth_date"], on), r["nationality"] or ""
        options = []
        for lid, m in meta.items():
            if not (m["age_min"] <= age <= m["age_max"]):
                continue
            if m["kind"] in ("junior", "college") and (pid in pro or age > (20 if m["kind"] == "junior" else 22)):
                continue
            if m["kind"] == "college" and pid in no_college:
                continue
            if ov < m["mean"] - 1.0:
                continue
            open_clubs = [c for c in clubs_by_league[lid] if sizes.get(c, 0) < m["roster"]
                          and limits.ok(c, nat, age, r["position"])]
            if not open_clubs:
                continue
            home = m.get("nat") or NATIONALITY_MIX.get(m["abbr"], {})
            weight = (1.0 + m["mean"] - 7.0) * (3.0 if home and max(home, key=home.get) == nat else 1.0)
            options.append((weight, lid, open_clubs))
        if not options and age < 23 and ov >= lowest - 1.5:      # young pros get a development spot somewhere
            pro_leagues = [(lid, m) for lid, m in meta.items() if m["kind"] in ("minor", "farm", "europe")
                           and m["age_min"] <= age <= m["age_max"]]
            for lid, m in sorted(pro_leagues, key=lambda x: x[1]["mean"]):
                open_clubs = [c for c in clubs_by_league[lid] if sizes.get(c, 0) < m["roster"] + 2]
                if open_clubs:
                    options = [(1.0, lid, open_clubs)]
                    break
        if not options:
            if age >= 23 or ov < lowest - 1.5:
                conn.execute("UPDATE players SET status='retired' WHERE player_id=?", (pid,))
                conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, detail) VALUES (?, 'retire', ?, "
                             "'retired (no offers)')", (day, pid))
                retired += 1
            continue
        _, lid, open_clubs = rng.choices(options, [o[0] for o in options])[0]
        club = min(open_clubs, key=lambda c: (sizes.get(c, 0), rng.random()))
        sizes[club] = sizes.get(club, 0) + 1
        limits.add(club, nat, age)
        conn.execute("UPDATE players SET club_id=? WHERE player_id=?", (club, pid))
        conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, to_team_id, detail) VALUES "
                     "(?, 'club', ?, ?, ?)", (day, pid, club, f"signed with a {meta[lid]['abbr']} club"))
        placed += 1
    return placed, retired


def trim_clubs(conn, day):
    """Clubs carrying more than roster + 2 players release their weakest players who are not NHL-contracted."""
    meta = world_meta(conn)
    leagues = club_league(conn)
    sizes = club_rosters(conn)
    cut = 0
    for club, n in sorted(sizes.items()):
        m = meta.get(leagues.get(club))
        if not m or n <= m["roster"] + 2:
            continue
        own = load_attrs(conn, "p.club_id=? AND p.team_id IS NULL AND p.status<>'retired'", (club,))
        protected = _class_prospects(conn)
        on = datetime.date(season_year(conn) + 1, 9, 15)
        own = {pid: r for pid, r in own.items() if not (pid in protected and age_on(r["birth_date"], on) <= 20)}
        for pid, _ in sorted(own.items(), key=lambda kv: overall(kv[1]))[: n - m["roster"]]:
            conn.execute("UPDATE players SET club_id=NULL WHERE player_id=?", (pid,))
            cut += 1
    return cut


def fill_clubs(conn, day):
    """Top every non-NHL club up to its roster size with newcomers (youth for junior/college/European clubs)."""
    meta = world_meta(conn)
    if not meta:
        return 0
    year = season_year(conn) + 1
    rng = _rng(conn, "intake")
    leagues = club_league(conn)
    sizes = club_rosters(conn)
    made = 0
    for club in sorted(t for t, lid in leagues.items() if lid in meta):
        m = meta[leagues[club]]
        goalies = conn.execute("SELECT COUNT(*) FROM players WHERE club_id=? AND position='G' AND status<>'retired'",
                               (club,)).fetchone()[0]
        for _ in range(max(0, m["roster"] - sizes.get(club, 0))):
            pos = "G" if goalies < 3 else pick_position(rng)
            if pos == "G" and goalies >= 3:
                pos = "D"
            goalies += pos == "G"
            age = max(m["age_min"], min(m["age_max"], youth_age(rng, m["kind"])))
            nat = pick_nationality(rng, _gen_mix(m))
            youth = age <= 19 and m["kind"] in ("junior", "college", "europe")
            pl, at, prof = gen_player(rng, NAMES, nat, pos, age, year, m["mean"] + age_mean_offset(age, m["kind"])
                                      + (FILLER_OFFSET if youth else 0.0))
            if youth:
                prof = filler_profile(rng, age, overall_of(at, pos), pos)    # the draft classes carry the talent
            insert_generated(conn, pl, at, prof, club)
            made += 1
    return made


def _gen_mix(m):
    """Nationalities new players for this league are drawn from: its mix, limited to nations the name lists cover."""
    mix = m.get("nat") or NATIONALITY_MIX.get(m["abbr"]) or {}
    mix = {k: v for k, v in mix.items() if k in NAMES and v > 0}
    return mix or ({m.get("country"): 100} if m.get("country") in NAMES else {"CAN": 100})


def _class_prospects(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='prospect_info'").fetchone():
        return set()
    return {r[0] for r in conn.execute("SELECT player_id FROM prospect_info")}


def create_draft_class(conn, day):
    """Each summer a new birth-year cohort of 17-year-olds joins junior, college-bound and European clubs. They are
    the players the draft a year later is about (see hs.worldgen.make_draft_class and docs/DRAFT.md)."""
    from . import scouting as S
    meta = world_meta(conn)
    if not meta:
        return 0
    year = season_year(conn) + 1
    key = f"draft_class_{year}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        return 0
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    S.ensure_tables(conn)
    rng = _rng(conn, "draftclass")
    placed = place_class(conn, make_draft_class(rng, NAMES, year), year, rng)
    return placed


def place_class(conn, cohort, year, rng):
    """Put cohort players in clubs of their home league with the most room (juniors may run a little over size)."""
    from . import scouting as S
    meta = world_meta(conn)
    leagues = club_league(conn)
    by_abbr = {}
    for t, lid in leagues.items():
        if lid in meta:
            by_abbr.setdefault(meta[lid]["abbr"], []).append(t)
    sizes = club_rosters(conn)
    from .leagues import Limits                        # v44: import limits (a cohort is 17, so over-age never bites)
    limits = Limits(conn, datetime.date(year, 9, 15))
    n = 0
    for pl, at, prof, info in cohort:
        age = year - int(pl["birth_date"][:4]) - (1 if pl["birth_date"][5:] > "09-15" else 0)
        club = None
        for abbr in class_leagues(pl["nationality"], age, rng):
            lid = next((l for l, m in meta.items() if m["abbr"] == abbr), None)
            if lid is None or not (meta[lid]["age_min"] <= age <= meta[lid]["age_max"]):
                continue
            clubs = [c for c in by_abbr.get(abbr, []) if limits.ok(c, pl["nationality"], age, pl["position"])]
            if clubs:
                club = min(clubs, key=lambda c: (sizes.get(c, 0), rng.random()))
                limits.add(club, pl["nationality"], age)
                break
        if club is None:
            continue
        sizes[club] = sizes.get(club, 0) + 1
        pid = insert_generated(conn, pl, at, prof, club)
        S.save_info(conn, pid, info, year)
        n += 1
    return n


def nhl_ready_juniors_leave(conn):
    """Nothing to do yet: CHL players under 20 stay in junior unless on an NHL roster (handled by roster moves)."""
    return 0


def where_is(conn, pid):
    r = conn.execute("SELECT t.name, l.abbr FROM players p JOIN teams t ON t.team_id=p.club_id JOIN leagues l "
                     "ON l.league_id=t.league_id WHERE p.player_id=?", (pid,)).fetchone()
    return f"{r['name']} ({r['abbr']})" if r else "unattached"
