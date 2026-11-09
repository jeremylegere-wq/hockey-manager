"""You, the general manager (docs/SETUP.md): a profile made at game setup and a career record that follows you.

Backgrounds give a small start, not a different game:
  former player   the dressing room gives you the benefit of the doubt: +5 trust in you for every player
  scout           owners who prefer youth (7+) like it: +3 board confidence
  analytics       owners with an analytics bias (0.6+) like it: +3 board confidence
  coach           the room settles faster: +3 cohesion
  business        budget-minded owners (spending 4 or less) like it: +3 board confidence
"""
from __future__ import annotations

import json

from .state import get_state, user_team

BACKGROUNDS = {
    "former_player": ("Former player", "Fifteen years in the league. The room gives you the benefit of the doubt."),
    "scout": ("Scout", "You came up through amateur scouting. Owners who build through the draft trust your eye."),
    "analytics": ("Analytics", "You ran a hockey analytics department. Data-minded owners speak your language."),
    "coach": ("Coach", "You coached in junior and the AHL. Players settle quickly under you."),
    "business": ("Business", "You ran the business side of a club. Budget-minded owners love you."),
}


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS gm_profile (id INTEGER PRIMARY KEY, name TEXT, nationality TEXT, background TEXT, "
                 "age INTEGER, created TEXT, extra TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS gm_career (team_id INTEGER, start_date TEXT, end_date TEXT, how_ended TEXT)")


def profile(conn):
    ensure_tables(conn)
    r = conn.execute("SELECT * FROM gm_profile WHERE id=1").fetchone()
    return dict(r) if r else None


def create(conn, name, nationality="", background="former_player", age=45):
    ensure_tables(conn)
    if background not in BACKGROUNDS:
        raise ValueError(f"Backgrounds: {', '.join(BACKGROUNDS)}.")
    day = get_state(conn)[0]
    name = (name or "").strip()[:40] or "The GM"
    conn.execute("INSERT OR REPLACE INTO gm_profile VALUES (1,?,?,?,?,?,?)", (name, nationality, background, int(age or 45), day, "{}"))
    conn.execute("UPDATE manager SET name=? WHERE id=1", (name,))
    t = user_team(conn)
    if t is not None and not conn.execute("SELECT 1 FROM gm_career").fetchone():
        conn.execute("INSERT INTO gm_career VALUES (?,?,NULL,NULL)", (t, day))
    _perk(conn, t, background, day)
    conn.commit()


def _perk(conn, t, bg, day):
    if t is None:
        return
    has = lambda tb: conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tb,)).fetchone()
    o = conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone() if has("owners") else None
    if bg == "former_player" and has("morale"):
        conn.execute("UPDATE morale SET trust_mgmt=MIN(100, trust_mgmt+5) WHERE player_id IN (SELECT player_id FROM players WHERE team_id=?)", (t,))
    elif bg == "coach" and has("team_room"):
        conn.execute("UPDATE team_room SET cohesion=MIN(100, cohesion+3) WHERE team_id=?", (t,))
    elif o is not None and has("board") and ((bg == "scout" and (o["youth_pref"] or 0) >= 7) or
                                             (bg == "analytics" and (o["analytics"] or 0) >= 0.6) or
                                             (bg == "business" and (o["spend"] or 10) <= 4)):
        from . import org
        org._apply(conn, t, 3, "gm_background", day, [f"the owner likes your {BACKGROUNDS[bg][0].lower()} background"])


def career(conn):
    """Your record: every club, season by season from the record book, and what you did there."""
    ensure_tables(conn)
    from .history import ensure_tables as he
    he(conn)
    stints = [dict(r) for r in conn.execute("SELECT * FROM gm_career ORDER BY start_date")]
    if not stints and user_team(conn) is not None:
        stints = [dict(team_id=user_team(conn), start_date=None, end_date=None, how_ended=None)]
    out = []
    for s in stints:
        t = s["team_id"]
        nm = conn.execute("SELECT name, nickname, abbr FROM teams WHERE team_id=?", (t,)).fetchone()
        y0 = int((s["start_date"] or "0000")[:4]) - (1 if (s["start_date"] or "0000-12")[5:7] < "07" else 0) if s["start_date"] else 0
        seasons = [dict(r) for r in conn.execute("SELECT * FROM team_seasons WHERE team_id=? AND season_start_year>=? ORDER BY season_start_year",
                                                 (t, y0))]
        trades = conn.execute("SELECT COUNT(*) FROM league_events WHERE event_type='TRADE_COMPLETED' AND team_id=? AND payload LIKE '%\"user\": true%'"
                              + (" AND event_date>=?" if s["start_date"] else ""), (t, s["start_date"]) if s["start_date"] else (t,)).fetchone()[0]
        out.append(dict(team_id=t, team=f"{nm[0]} {nm[1] or ''}".strip(), abbr=nm[2], start=s["start_date"], end=s["end_date"],
                        how_ended=s["how_ended"], seasons=seasons, trades=trades,
                        playoffs=sum(1 for x in seasons if x["playoff_round"]), cups=sum(1 for x in seasons if x["playoff_round"] == 5),
                        w=sum(x["w"] for x in seasons), l=sum(x["l"] for x in seasons), otl=sum(x["otl"] for x in seasons)))
    p = profile(conn)
    return dict(profile=p, background=BACKGROUNDS.get((p or {}).get("background") or "", (None, None)), stints=out,
                backgrounds={k: dict(label=v[0], text=v[1]) for k, v in BACKGROUNDS.items()})


# ================================================================ v32 (phase A2): your manager
# Ratings 1-20 with points to spend, a reputation, the role (GM only, or GM and head coach), a career that cannot end
# in a firing (an option), and life without a job (start unemployed, or after a firing: the job market).
RATINGS = {
    "negotiation": ("Negotiation", "What players and agents settle for in contract talks (about 0.5% of the ask per point from 10)"),
    "judging_talent": ("Judging talent", "How far off your own read of a prospect is (your scouts' estimates tighten about 3% a point)"),
    "motivation": ("Motivation", "The room's trust in you drifts up (or down) each week; as coach, your communication"),
    "media_handling": ("Media handling", "How much a bad answer at the podium costs (3% a point from 10)"),
    "coaching": ("Coaching", "Only as GM and head coach: you are the coach the engine and the room see"),
    "development": ("Youth development", "Only as GM and head coach: your development rating for the young players"),
}
POOL, R_MIN, R_MAX = 66, 4, 18
TEMPLATES = {
    "balanced": ("Balanced", dict(negotiation=11, judging_talent=11, motivation=11, media_handling=11, coaching=11, development=11)),
    "dealmaker": ("Dealmaker", dict(negotiation=17, judging_talent=11, motivation=10, media_handling=12, coaching=8, development=8)),
    "talent_hound": ("Talent hound", dict(negotiation=10, judging_talent=17, motivation=9, media_handling=8, coaching=9, development=13)),
    "players_gm": ("Players' GM", dict(negotiation=9, judging_talent=10, motivation=17, media_handling=11, coaching=10, development=9)),
    "tactician": ("Tactician (for GM and coach)", dict(negotiation=8, judging_talent=9, motivation=12, media_handling=8, coaching=17, development=12)),
    "media_darling": ("Media darling", dict(negotiation=11, judging_talent=9, motivation=11, media_handling=17, coaching=9, development=9)),
}
REPUTATIONS = {"unknown": ("Unknown", 25), "respected": ("Respected", 50), "renowned": ("Renowned", 75)}
ROLES_GM = {"gm": "General manager", "gm_coach": "General manager and head coach"}


def _extra(conn):
    p = profile(conn)
    try:
        return json.loads((p or {}).get("extra") or "{}")
    except ValueError:
        return {}


def _save_extra(conn, x):
    ensure_tables(conn)
    if not conn.execute("SELECT 1 FROM gm_profile WHERE id=1").fetchone():
        conn.execute("INSERT INTO gm_profile VALUES (1, 'The GM', '', 'former_player', 45, ?, '{}')", (get_state(conn)[0],))
    conn.execute("UPDATE gm_profile SET extra=? WHERE id=1", (json.dumps(x),))


def check_ratings(r):
    r = {k: int(r.get(k, 10)) for k in RATINGS}
    bad = [k for k, v in r.items() if not R_MIN <= v <= R_MAX]
    if bad:
        raise ValueError(f"Each rating is {R_MIN} to {R_MAX}.")
    if sum(r.values()) > POOL:
        raise ValueError(f"You have {POOL} points to spend; that is {sum(r.values())}.")
    return r


def settings(conn):
    """Your ratings, reputation, role and options (defaults for careers made before v32)."""
    x = _extra(conn)
    return dict(ratings=x.get("ratings") or dict(TEMPLATES["balanced"][1]), reputation=float(x.get("reputation", 50)),
                role=x.get("role", "gm"), unfireable=bool(x.get("unfireable")), template=x.get("template", "balanced"),
                points=int(x.get("points", 0)), rep_log=x.get("rep_log") or [])


def rating(conn, key):
    return settings(conn)["ratings"].get(key, 10)


def setup_manager(conn, ratings=None, template=None, reputation="respected", role="gm", unfireable=False):
    """At game setup (after create): ratings (or a template), the starting reputation, the role and the option."""
    if template and not ratings:
        ratings = TEMPLATES.get(template, TEMPLATES["balanced"])[1]
    r = check_ratings(ratings or TEMPLATES["balanced"][1])
    rep = REPUTATIONS.get(reputation, REPUTATIONS["respected"])[1] if isinstance(reputation, str) else float(reputation)
    if role not in ROLES_GM:
        raise ValueError("The role is gm or gm_coach.")
    x = _extra(conn)
    x.update(ratings=r, reputation=rep, role="gm", unfireable=bool(unfireable), template=template or "custom")
    _save_extra(conn, x)
    t = user_team(conn)
    if t is not None:
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE name='board'").fetchone()
        if has:                                            # a name opens doors: reputation moves the board's first view of you
            conn.execute("UPDATE board SET confidence=MAX(5, MIN(95, confidence+?)) WHERE team_id=?", ((rep - 50) / 10, t))
        if role == "gm_coach":
            become_coach(conn, get_state(conn)[0])
    conn.commit()


def _staff_row(conn):
    x = _extra(conn)
    sid = x.get("coach_staff_id")
    if sid and conn.execute("SELECT 1 FROM staff WHERE staff_id=?", (sid,)).fetchone():
        return sid
    return None


def is_coach(conn):
    return settings(conn)["role"] == "gm_coach" and _staff_row(conn) is not None


def become_coach(conn, day):
    """You take the bench as well: the head coach goes to the market and you fill his place (a staff row with your
    coaching, development and motivation). Your coaching then counts wherever the head coach's does."""
    from . import staff as S
    from .events import emit, team_abbr
    t = user_team(conn)
    if t is None:
        raise ValueError("You need a club first.")
    S.ensure_tables(conn)
    x = _extra(conn)
    if _staff_row(conn):
        return
    p = profile(conn) or {}
    r = settings(conn)["ratings"]
    for hc in S.members(conn, t, "HC"):
        conn.execute("UPDATE staff SET team_id=NULL WHERE staff_id=?", (hc["staff_id"],))
        emit(conn, "STAFF_DISMISSED", day, f"{team_abbr(conn, t)}: {hc['name']} steps aside as the GM takes the bench",
             team_id=t, staff_id=hc["staff_id"], importance=2)
    sid = S._insert(conn, dict(name=p.get("name") or "The GM", role="HC", team_id=t, age=p.get("age") or 45,
                               coaching=r["coaching"], development=r["development"], evaluation=r["judging_talent"], medical=5,
                               communication=r["motivation"], leadership=r["motivation"], reputation=int(settings(conn)["reputation"] / 5),
                               salary=0, contract_end=9999, style="the GM"))
    x.update(role="gm_coach", coach_staff_id=sid)
    _save_extra(conn, x)
    emit(conn, "STAFF_HIRED", day, f"{team_abbr(conn, t)}: general manager {p.get('name') or ''} will also coach the team".replace("  ", " "),
         team_id=t, staff_id=sid, importance=2)


def step_down_as_coach(conn, day):
    """Back to GM only: the bench is empty until you hire a head coach (Staff)."""
    x = _extra(conn)
    sid = _staff_row(conn)
    if sid:
        conn.execute("DELETE FROM staff WHERE staff_id=?", (sid,))
    x.update(role="gm", coach_staff_id=None)
    _save_extra(conn, x)


def sync_coach(conn):
    """Keep your staff row in step with your ratings (after a change)."""
    sid = _staff_row(conn)
    if sid:
        r = settings(conn)["ratings"]
        conn.execute("UPDATE staff SET coaching=?, development=?, evaluation=?, communication=?, leadership=? WHERE staff_id=?",
                     (r["coaching"], r["development"], r["judging_talent"], r["motivation"], r["motivation"], sid))


# ---------------------------------------------------------------- reputation
def reputation_label(rep):
    return ("unknown" if rep < 30 else "journeyman" if rep < 45 else "respected" if rep < 60 else "highly regarded" if rep < 75
            else "renowned" if rep < 90 else "legendary")


def change_reputation(conn, delta, why=""):
    x = _extra(conn)
    rep = max(1.0, min(100.0, float(x.get("reputation", 50)) + delta))
    x["reputation"] = round(rep, 1)
    log = x.get("rep_log") or []
    log.append([get_state(conn)[0], round(delta, 1), why])
    x["rep_log"] = log[-30:]
    _save_extra(conn, x)
    return rep


def season_reputation(conn, year):
    """At the end of a season: playoff rounds won, a championship, where the board stands. Returns the change."""
    t = user_team(conn)
    if t is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_seasons'").fetchone():
        return 0
    r = conn.execute("SELECT playoff_round, league_rank FROM team_seasons WHERE team_id=? AND season_start_year=?", (t, year)).fetchone()
    if r is None:
        return 0
    rnd, rank = r[0] or 0, r[1] or 16
    d = {0: -2, 1: 1, 2: 3, 3: 5, 4: 7, 5: 12}.get(rnd, 0) + (16 - rank) * 0.25
    change_reputation(conn, d, f"the {year}-{(year + 1) % 100:02d} season")
    x = _extra(conn)                                        # a season's experience: one point to spend on your ratings
    x["points"] = int(x.get("points", 0)) + 1
    _save_extra(conn, x)
    return d


def improve(conn, key):
    """Spend an experience point (one per season completed) on a rating, up to 20."""
    if key not in RATINGS:
        raise ValueError("Ratings: " + ", ".join(RATINGS) + ".")
    x = _extra(conn)
    if int(x.get("points", 0)) < 1:
        raise ValueError("No points to spend: you earn one for each season you complete.")
    r = x.get("ratings") or dict(TEMPLATES["balanced"][1])
    if r.get(key, 10) >= 20:
        raise ValueError("That rating is already 20.")
    r[key] = r.get(key, 10) + 1
    x.update(ratings=r, points=int(x["points"]) - 1)
    _save_extra(conn, x)
    sync_coach(conn)
    return r[key]


# ---------------------------------------------------------------- out of work: the job market
def unemployed(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone()
    return bool(r) and user_team(conn) is None


def lose_job(conn, day, how="fired"):
    """You no longer run a club: the club's AI takes over, your coach's chair (if you coached) is emptied, your
    reputation takes the hit. The world goes on; Continue keeps playing while you look for work."""
    t = user_team(conn)
    if t is None:
        return
    sid = _staff_row(conn)
    if sid:
        conn.execute("DELETE FROM staff WHERE staff_id=?", (sid,))
        x = _extra(conn)
        x["coach_staff_id"] = None
        _save_extra(conn, x)
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('gm_status', ?)", (how,))
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('last_team', ?)", (str(t),))
    conn.execute("UPDATE manager SET team_id=NULL WHERE id=1")
    if how == "fired":
        change_reputation(conn, -8, "fired")


def can_be_fired(conn):
    return not settings(conn)["unfireable"]


def start_unemployed(conn, day, n=3):
    """A career that starts without a club: a few clubs (most of them weaker ones) are looking for a GM."""
    import random as _r
    t = user_team(conn)
    lose_job(conn, day, "unemployed")
    conn.execute("DELETE FROM gm_career")
    from . import org
    ranks = org.projected_ranks(conn)
    pool = sorted(ranks, key=lambda x: -ranks[x])
    rng = _r.Random(f"{get_state(conn)[1] if len(get_state(conn)) > 1 else 0}-jobs-{day}")
    picks = rng.sample(pool[:12], min(n - 1, len(pool[:12]))) + rng.sample(pool[12:], 1 if len(pool) > 12 else 0)
    for c in picks:
        conn.execute("UPDATE board SET vacancy=1, gm_name='(vacant)' WHERE team_id=?", (c,))
    from .state import add_message
    from .events import team_abbr
    add_message(conn, day, "Looking for work",
                "You start this career without a club. Clubs looking for a general manager:\n"
                + "\n".join(f"- {team_abbr(conn, c)}" for c in picks)
                + "\nApply on the Job Centre screen. A club only hires a GM whose reputation fits what it expects; "
                  "more jobs open as GMs are fired around the league. Continue plays on while you wait.")


def club_demand(conn, t, ranks=None):
    """The reputation a club wants in its GM: the better the club, the more it expects."""
    from . import org
    ranks = ranks or org.projected_ranks(conn)
    n = max(2, len(ranks))
    rank = ranks.get(t, n // 2)
    return round(20 + 50 * (n - rank) / (n - 1))          # the best club wants 70, the worst 20


def job_market(conn):
    from . import org
    from .events import team_abbr
    rep = settings(conn)["reputation"]
    ranks = org.projected_ranks(conn)
    out = []
    for t in org.vacancies(conn):
        o = conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone() if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='owners'").fetchone() else None
        nm = conn.execute("SELECT name, nickname, abbr FROM teams WHERE team_id=?", (t,)).fetchone()
        need = club_demand(conn, t, ranks)
        tried = conn.execute("SELECT value FROM pack_info WHERE key=?", (f"job_apply_{t}",)).fetchone()
        out.append(dict(team_id=t, abbr=nm["abbr"], name=f"{nm['name']} {nm['nickname'] or ''}".strip(), projected=ranks.get(t),
                        owner=dict(name=o["name"], summary=o["summary"], archetype=o["archetype"], patience=o["patience"]) if o else None,
                        demand=need, chance=_chance(rep, need), last_applied=tried[0] if tried else None))
    return dict(reputation=rep, label=reputation_label(rep), jobs=sorted(out, key=lambda x: -x["chance"]), unemployed=unemployed(conn))


def _chance(rep, need):
    return round(max(0.03, min(0.97, 0.5 + (rep - need) / 30)), 2)


def apply_job(conn, t, day):
    """Apply for a vacancy: the club interviews you and says yes or no, by your reputation against what it expects.
    One application per club a month."""
    import random as _r
    from . import org
    from .state import add_message
    from .events import team_abbr
    if not unemployed(conn):
        raise ValueError("You already run a club. (You can see the job market, but you apply once you are out of work.)")
    if t not in org.vacancies(conn):
        raise ValueError("That club is not looking for a GM.")
    key = f"job_apply_{t}"
    last = conn.execute("SELECT value FROM pack_info WHERE key=?", (key,)).fetchone()
    if last and last[0][:7] == day[:7]:
        raise ValueError(f"{team_abbr(conn, t)} already interviewed you this month.")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES (?, ?)", (key, day))
    rep = settings(conn)["reputation"]
    need = club_demand(conn, t)
    yes = _r.Random(f"job-{t}-{day[:7]}").random() < _chance(rep, need)
    if not yes:
        add_message(conn, day, f"{team_abbr(conn, t)} said no",
                    f"Thank you for coming in. We have decided to go in a different direction. (They wanted a GM with a reputation "
                    f"around {need}; yours is {rep:.0f}.) You can try again next month.")
        return False
    org.take_job(conn, t, day)
    conn.execute("DELETE FROM pack_info WHERE key IN ('gm_status', 'last_team')")
    for k in [r[0] for r in conn.execute("SELECT key FROM pack_info WHERE key LIKE 'job_apply_%'")]:
        conn.execute("DELETE FROM pack_info WHERE key=?", (k,))
    if settings(conn)["role"] == "gm_coach" or _extra(conn).get("wants_coach"):
        x = _extra(conn)
        x["role"] = "gm_coach"
        _save_extra(conn, x)
        become_coach(conn, day)
    from . import welcome                            # v38: the owner's welcome, the club briefing, the introductory press conference
    welcome.start_career(conn, day, t)
    return True
