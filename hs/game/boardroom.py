"""The boardroom: owner personality, a weekly hot-seat score, ultimatums, owner directives and media leaks
(docs/BOARD.md). Builds on hs/game/org.py (owners, objectives, season reviews), which it does not replace.

Owner profile (added to `owners`): a name, vocalness VOC (0-1, how much he talks to the media), analytics bias ANA
(0-1), a preferred identity for the team, and an archetype derived from all traits.

Weekly, for every NHL club with 5+ games played:
  drift        confidence moves with the points pace against the competitive objective (the old monthly drift, a
               quarter of it each week)
  velocity v   the four-week change in confidence, /100, clamped to -0.5..0.5
  pressure mp  market size (0.10-0.40) plus 0.03 per game of a losing streak beyond three, at most 0.40
  trigger T    = confidence/100 + v x P - mp x VOC, P = (1.1 - patience) when v < 0, patience when v >= 0
               (patience as 0-1)
  T <= 0.25    the owner issues an ultimatum: 3 games (patience under 0.3) or 5, and the points to take from them
               (2 x games x 0.55, rounded up; 0.60 for impatient owners). Met: +6 confidence, the warning lifts
               and no new ultimatum for 14 days. Missed: the GM is fired, there and then.
  T <= 0.33    an AI club whose owner is involved (4+) fires its head coach first, once a season, if he was not
               hired this season: +8 confidence (the high-vocalness leak at 0.40 says it is coming). The user can do the
               same (dismiss the head coach while an ultimatum is open): +8 and three more games.
Directives (the user's club only): mandates the owner hands down with a deadline, at most one open at a time,
  issued weekly with probability 0.1 + involvement/40:
  move_veteran   move a named veteran (30+, $4M+ cap hit) by the trade deadline (budget owners or a club over its
                 payroll objective)
  add_forward    add a top-six forward by the trade deadline (ambitious owners whose club is below target)
  keep_youth     trade nobody 23 or under this season (youth-minded owners; fails on the day it is broken)
  extend_core    extend a named core player in his final year by the end of the regular season
  A met directive is worth +3. A missed one costs 8 x (1.2 - patience/10) x (1 + involvement/20) and the trigger
  score is recalculated at once, so a failed mandate can bring the ultimatum the same day.
Media (fictional accounts; see hs/game/media.py): when T drops to 0.40 or below, and again at an ultimatum:
  VOC > 0.8      specific leaks the same day (the owner's preferred identity, the window and the points)
  0.3-0.8        vague leaks, two to four days later, ultimatums only
  VOC < 0.3      silence; the firing, when it comes, is reported as a surprise
"""
from __future__ import annotations

import datetime
import json
import math
import random

from . import contracts as K
from . import org
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

WARN, RUMOUR, COACH_AT = 0.25, 0.40, 0.33
MIN_GP_COACH, MIN_GP_ULTIMATUM = 15, 20
AI_ULTIMATUM_PATIENCE = 4    # AI owners this impatient or worse act mid-season; the rest wait for the summer review
AFTER_COACH_DAYS = 30        # a new coach gets this long before anyone issues an ultimatum
COACH_INVOLVEMENT = 4        # AI owners this involved fire the head coach first
PACE, PACE_TYRANT = 0.55, 0.60
COOLDOWN_DAYS = 14
VELOCITY_DAYS = 28
WEEKLY_SHARE = 0.5           # weekly drift as a share of the old monthly drift
IDENTITY_BONUS, IDENTITY_COST = 0.25, 0.15   # a week of playing (or not playing) the owner's preferred identity
MET_BONUS, COACH_RELIEF = 6.0, 8.0
DIRECTIVE_LOSS, DIRECTIVE_GAIN = 8.0, 3.0
MARKETS = {"TOR": .40, "MTL": .40, "NYR": .35, "VAN": .30, "EDM": .30, "BOS": .30, "CHI": .30, "PHI": .30,
           "CGY": .25, "OTT": .25, "DET": .25, "LAK": .25, "PIT": .25, "WPG": .20, "NYI": .20, "NJD": .20, "WSH": .20}
IDENTITIES = ["heavy forecheck", "puck possession", "defensive structure", "speed and transition"]
IDENTITY_WORDS = {"heavy forecheck": ["a heavy-forecheck engine", "a north-south, heavy forechecking team",
                                      "a hard, forechecking identity"],
                  "puck possession": ["a skill-first, possession game", "a puck-management system",
                                      "a team that controls the puck"],
                  "defensive structure": ["a structured, defence-first team", "a tighter defensive shell",
                                          "a team that is hard to play against"],
                  "speed and transition": ["a high-tempo transition game", "a track-meet pace",
                                           "a team that plays fast through the neutral zone"]}
COACH_FITS = {"demanding": "defensive structure", "tactician": "puck possession", "motivator": "heavy forecheck",
              "teacher": "speed and transition", "players' coach": "speed and transition"}
OWNER_FIRST = ["Victor", "Harold", "Dana", "Richard", "Elaine", "Marcus", "Gerald", "Nadia", "Conrad", "Leonard",
               "Miriam", "Stellan", "Bernard", "Ingrid", "Warren", "Celeste", "Douglas", "Renata", "Clifford", "Opal"]
OWNER_LAST = ["Ashcombe", "Velloway", "Carrow", "Dunmore", "Halberg", "Kessling", "Marchetti", "Oberlin", "Pryce",
              "Rothwell", "Stavros", "Thornquist", "Vandermeer", "Whitlock", "Yarrow", "Brannigan", "Castellan",
              "Esterbrook", "Fairholm", "Grisdale"]


def ensure_tables(conn):
    org.ensure_tables(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(owners)")}
    for c, t in (("name", "TEXT"), ("vocalness", "REAL"), ("analytics", "REAL"), ("identity", "TEXT"),
                 ("archetype", "TEXT")):
        if c not in cols:
            conn.execute(f"ALTER TABLE owners ADD COLUMN {c} {t}")
    conn.execute("CREATE TABLE IF NOT EXISTS board_trend (team_id INTEGER, date TEXT, confidence REAL, velocity REAL, "
                 "pressure REAL, trigger REAL, PRIMARY KEY (team_id, date))")
    conn.execute("CREATE TABLE IF NOT EXISTS ultimatums (ultimatum_id INTEGER PRIMARY KEY, team_id INTEGER, "
                 "season INTEGER, issued TEXT, games INTEGER, points_needed INTEGER, gp_at_issue INTEGER, "
                 "pts_at_issue INTEGER, status TEXT DEFAULT 'open', resolved TEXT, result TEXT, trigger REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS directives (directive_id INTEGER PRIMARY KEY, team_id INTEGER, "
                 "season INTEGER, code TEXT, description TEXT, target TEXT, issued TEXT, deadline TEXT, "
                 "status TEXT DEFAULT 'open', result TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS board_flags (team_id INTEGER, season INTEGER, flag TEXT, value TEXT, "
                 "PRIMARY KEY (team_id, season, flag))")
    _profiles(conn)


def _seed(conn):
    st = get_state(conn)
    return st[1] if st else 1


def archetype(o):
    pat, inv, spend = o["patience"], o["involvement"], o["spend"]
    ana, voc = o["analytics"] or 0.5, o["vocalness"] or 0.5
    if pat <= 3 and (inv >= 6 or voc >= 0.7):
        return "The Impatient Tyrant"
    if ana >= 0.7:
        return "The Moneyballer"
    if spend <= 3:
        return "The Penny Pincher"
    if pat >= 7 and o["youth_pref"] >= 6:
        return "The Patient Builder"
    if ana <= 0.35:
        return "The Traditionalist"
    return "The Steady Hand"


def _profiles(conn):
    seed = _seed(conn)
    for o in conn.execute("SELECT * FROM owners WHERE vocalness IS NULL").fetchall():
        rng = random.Random(f"{seed}-owner-profile-{o['team_id']}")
        voc = max(0.02, min(0.98, 0.1 + 0.08 * o["involvement"] + rng.gauss(0, 0.15)))
        ana = max(0.02, min(0.98, rng.betavariate(2, 2)))
        d = dict(o)
        d.update(vocalness=round(voc, 2), analytics=round(ana, 2))
        conn.execute("UPDATE owners SET name=?, vocalness=?, analytics=?, identity=?, archetype=? WHERE team_id=?",
                     (f"{rng.choice(OWNER_FIRST)} {rng.choice(OWNER_LAST)}", d["vocalness"], d["analytics"],
                      rng.choice(IDENTITIES), archetype(d), o["team_id"]))


def owner(conn, t):
    ensure_tables(conn)
    return conn.execute("SELECT * FROM owners WHERE team_id=?", (t,)).fetchone()


# ---------------------------------------------------------------- measuring

def _record(conn, t, season_id):
    """(games played, points) this regular season."""
    gp = pts = 0
    for g in conn.execute("SELECT * FROM games WHERE season_id=? AND played=1 AND game_type='RS' AND "
                          "(home_team_id=? OR away_team_id=?)", (season_id, t, t)):
        home = g["home_team_id"] == t
        gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
        gp += 1
        pts += 2 if gf > ga else 1 if (g["went_to_ot"] or gf == ga) else 0
    return gp, pts


def _losing_streak(conn, t, season_id):
    n = 0
    for g in conn.execute("SELECT * FROM games WHERE season_id=? AND played=1 AND game_type='RS' AND "
                          "(home_team_id=? OR away_team_id=?) ORDER BY game_date DESC, game_id DESC LIMIT 15",
                          (season_id, t, t)):
        home = g["home_team_id"] == t
        gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
        if gf >= ga:
            break
        n += 1
    return n


def _last10_pct(conn, t, season_id):
    gp = pts = 0
    for g in conn.execute("SELECT * FROM games WHERE season_id=? AND played=1 AND game_type='RS' AND "
                          "(home_team_id=? OR away_team_id=?) ORDER BY game_date DESC, game_id DESC LIMIT 10",
                          (season_id, t, t)):
        home = g["home_team_id"] == t
        gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
        gp += 1
        pts += 2 if gf > ga else 1 if (g["went_to_ot"] or gf == ga) else 0
    return pts / (2 * gp) if gp else 0.5


def pressure(conn, t, season_id):
    """Media pressure: the market's size, turned up by losing. A club winning 70% of its points in the last ten
    feels 60% of its market; one at 30% feels 140%; plus 0.03 a game of a losing streak beyond three. Max 0.40."""
    base = MARKETS.get(team_abbr(conn, t), 0.12)
    heat = max(0.3, min(1.6, 2 * (1 - _last10_pct(conn, t, season_id))))
    return round(min(0.40, base * heat + 0.03 * max(0, _losing_streak(conn, t, season_id) - 3)), 3)


def _conf(conn, t):
    return conn.execute("SELECT confidence FROM board WHERE team_id=?", (t,)).fetchone()[0]


def velocity(conn, t, day):
    since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=VELOCITY_DAYS)).isoformat()
    r = conn.execute("SELECT confidence FROM board_history WHERE team_id=? AND review_date<=? ORDER BY rowid DESC "
                     "LIMIT 1", (t, since)).fetchone()
    if r is None:
        r = conn.execute("SELECT confidence FROM board_history WHERE team_id=? ORDER BY rowid LIMIT 1", (t,)).fetchone()
    then = r[0] if r else _conf(conn, t)
    return max(-0.5, min(0.5, (_conf(conn, t) - then) / 100.0))


def trigger(conn, t, day, season_id=None):
    """dict(T, confidence, velocity, pressure, patience_impact)."""
    season_id = season_id or conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    o = owner(conn, t)
    pat = o["patience"] / 10
    v = velocity(conn, t, day)
    mp = pressure(conn, t, season_id)
    p_imp = (1.1 - pat) if v < 0 else pat
    c = _conf(conn, t) / 100.0
    T = c + v * p_imp - mp * (o["vocalness"] or 0.5)
    return dict(T=round(T, 3), confidence=round(c, 3), velocity=round(v, 3), pressure=round(mp, 3),
                patience_impact=round(p_imp, 3), vocalness=o["vocalness"])


# ---------------------------------------------------------------- the weekly loop

def weekly(conn, day):
    """Every NHL club: weekly drift, trigger score, rumours, coach firings, ultimatums; the user's directives."""
    if K.season_state(conn) != "regular_season":
        return []
    ensure_tables(conn)
    me = user_team(conn)
    season_id, year = conn.execute("SELECT season_id, start_year FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
    lines = []
    from . import tactics
    tactics.ensure_table(conn)
    if not conn.execute("SELECT 1 FROM team_tactics").fetchone():
        tactics.ai_choose(conn)                         # saves from before v25
    _drift(conn, day, season_id, year)
    for t in org.nhl_teams(conn):
        gp, _ = _record(conn, t, season_id)
        if gp < 5:
            continue
        if t == me and conn.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone():
            continue                                    # the user has been fired: nothing to evaluate
        lines += evaluate(conn, t, day, season_id, year)
    if me:
        lines += _directives_weekly(conn, me, day, season_id, year)
    return lines


def _drift(conn, day, season_id, year):
    from ..league import standings
    from ..league.season import db_rules
    rules = db_rules(conn)
    rec, h2h = standings.table(conn, season_id)
    if not rec:
        return
    order = standings.rank(rec, h2h, rules)
    n = len(order)
    spots = 16 if n >= 24 else max(2, n // 2)
    for t in org.nhl_teams(conn):
        if t not in rec or rec[t]["gp"] < 10:
            continue
        obj = conn.execute("SELECT * FROM objectives WHERE team_id=? AND season_start_year=? AND "
                           "category='competitive'", (t, year)).fetchone()
        if obj is None:
            continue
        place = order.index(t) + 1
        want = {"playoff_round": spots - 4 * (int(obj["target"]) - 1) if obj["code"] == "playoff_round" else None,
                "playoff_gap": spots + 4, "not_bottom": n - 3}.get(obj["code"]) or spots
        o = owner(conn, t)
        impatience = 1.2 - o["patience"] / 10
        from .tactics import system_of
        plays = system_of(conn, t)
        if o["identity"] and plays == o["identity"]:
            org._apply(conn, t, IDENTITY_BONUS, "identity", day, [f"plays {plays}, the owner's game +{IDENTITY_BONUS}"])
        elif o["identity"] and o["involvement"] >= 7:
            org._apply(conn, t, -IDENTITY_COST, "identity", day,
                       [f"plays {plays}; the owner wants {o['identity']} -{IDENTITY_COST}"])
        delta = WEEKLY_SHARE * (1.0 if place <= want else -1.5 * impatience * min(3, (place - want) / 3 + 0.5))
        org._apply(conn, t, delta, "weekly", day, [f"{place} in the league against a target of about {want}"])


def evaluate(conn, t, day, season_id=None, year=None):
    """Recalculate one club's trigger score and act on it (also called the moment a directive fails)."""
    season_id = season_id or conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    year = year or org.season_year(conn)
    me = user_team(conn)
    tr = trigger(conn, t, day, season_id)
    conn.execute("INSERT OR REPLACE INTO board_trend VALUES (?,?,?,?,?,?)",
                 (t, day, tr["confidence"], tr["velocity"], tr["pressure"], tr["T"]))
    o = owner(conn, t)
    lines = []
    if open_ultimatum(conn, t):
        return lines
    gp, _ = _record(conn, t, season_id)
    if tr["T"] <= RUMOUR:
        _leak(conn, t, day, o, "pressure", tr)
    if t != me and gp >= MIN_GP_COACH and tr["T"] <= COACH_AT and o["involvement"] >= COACH_INVOLVEMENT and _scapegoat(conn, t, day, year):
        return [f"{team_abbr(conn, t)} fire their head coach"]
    if tr["T"] > WARN or gp < MIN_GP_ULTIMATUM:
        return lines
    if t != me and o["patience"] > AI_ULTIMATUM_PATIENCE:
        return lines
    fired = _flag(conn, t, year, "coach_fired")
    if fired and (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(fired)).days < AFTER_COACH_DAYS:
        return lines
    last = conn.execute("SELECT resolved FROM ultimatums WHERE team_id=? AND status='met' ORDER BY ultimatum_id DESC "
                        "LIMIT 1", (t,)).fetchone()
    if last and (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(last[0])).days < COOLDOWN_DAYS:
        return lines
    lines.append(issue_ultimatum(conn, t, day, season_id, year, tr))
    return lines


def _flag(conn, t, year, flag, value=None):
    if value is None:
        r = conn.execute("SELECT value FROM board_flags WHERE team_id=? AND season=? AND flag=?",
                         (t, year, flag)).fetchone()
        return r[0] if r else None
    conn.execute("INSERT OR REPLACE INTO board_flags VALUES (?,?,?,?)", (t, year, flag, value))


COACH_FIRING_GAP = 6          # days between AI clubs' in-season coach firings (v39)


def _scapegoat(conn, t, day, year):
    from . import staff as S
    if _flag(conn, t, year, "coach_fired"):
        return False
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return False
    hc = S.head_coach(conn, t)
    if hc is None:
        return False
    hired = conn.execute("SELECT event_date FROM league_events WHERE event_type='STAFF_HIRED' AND staff_id=? AND "
                         "team_id=? ORDER BY event_id DESC LIMIT 1", (hc["staff_id"], t)).fetchone()
    if hired and hired[0] >= f"{year}-07-01":
        return False                                    # hired this season: not yet
    if t != user_team(conn) and K.season_state(conn) == "regular_season":
        import datetime as _dt                          # v39 (#25): in season, one firing at a time across the league
        since = (_dt.date.fromisoformat(day) - _dt.timedelta(days=COACH_FIRING_GAP)).isoformat()
        if conn.execute("SELECT 1 FROM league_events WHERE event_type='COACH_FIRED' AND event_date>? LIMIT 1",
                        (since,)).fetchone():
            return False
    o = owner(conn, t)
    _leak(conn, t, day, o, "coach", None, coach=hc["name"])
    S.dismiss(conn, t, hc["staff_id"], day, "fire head coach")
    _flag(conn, t, year, "coach_fired", day)
    org._apply(conn, t, COACH_RELIEF, "coach", day, [f"the head coach pays the price +{COACH_RELIEF:.0f}"])
    # the AI fills the job from the market straight away (an interim)
    c = conn.execute("SELECT staff_id FROM staff WHERE team_id IS NULL AND role='HC' ORDER BY coaching + "
                     "reputation / 2.0 DESC LIMIT 1").fetchone()
    if c:
        S.hire(conn, t, c[0], day)
    return True


def on_user_coach_fired(conn, t, day):
    """The user dismissed his head coach: while an ultimatum is open, the board accepts it once a season."""
    ensure_tables(conn)
    year = org.season_year(conn)
    u = open_ultimatum(conn, t)
    if u is None or _flag(conn, t, year, "coach_fired"):
        return None
    _flag(conn, t, year, "coach_fired", day)
    org._apply(conn, t, COACH_RELIEF, "coach", day, [f"the coaching change buys time +{COACH_RELIEF:.0f}"])
    conn.execute("UPDATE ultimatums SET games=games+3 WHERE ultimatum_id=?", (u["ultimatum_id"],))
    add_message(conn, day, "The owner accepts the coaching change",
                f"{owner(conn, t)['name']}: \"A new voice behind the bench. You get three more games.\"")
    return "The board accepts the coaching change: +8 confidence and three more games."


# ---------------------------------------------------------------- ultimatums

def open_ultimatum(conn, t):
    return conn.execute("SELECT * FROM ultimatums WHERE team_id=? AND status='open' ORDER BY ultimatum_id DESC LIMIT 1",
                        (t,)).fetchone()


def issue_ultimatum(conn, t, day, season_id, year, tr):
    o = owner(conn, t)
    games = 3 if o["patience"] / 10 < 0.3 else 5
    pace = PACE_TYRANT if o["archetype"] == "The Impatient Tyrant" else PACE
    need = math.ceil(2 * games * pace)
    gp, pts = _record(conn, t, season_id)
    conn.execute("INSERT INTO ultimatums (team_id, season, issued, games, points_needed, gp_at_issue, pts_at_issue, "
                 "trigger) VALUES (?,?,?,?,?,?,?,?)", (t, year, day, games, need, gp, pts, tr["T"]))
    conn.execute("UPDATE board SET warnings=1 WHERE team_id=?", (t,))
    me = user_team(conn)
    if t == me:
        add_message(conn, day, "URGENT: from the owner's office", ultimatum_text(o, games, need))
    emit(conn, "BOARD_REVIEW", day, f"{team_abbr(conn, t)} ownership issues an ultimatum: {need} points from the next "
         f"{games} games", team_id=t, importance=2 if t == me else 1, kind="ultimatum", games=games, points=need,
         trigger=tr["T"])
    _leak(conn, t, day, o, "ultimatum", tr, games=games, points=need)
    return f"{team_abbr(conn, t)}: ultimatum ({need} points in {games} games)"


def ultimatum_text(o, games, need):
    name = o["name"] or "the owner"
    arch = o["archetype"]
    style = IDENTITY_WORDS.get(o["identity"] or "", ["a different identity"])[0]
    if arch == "The Impatient Tyrant":
        return (f"--- INTERNAL EMAIL: HIGH URGENCY ---\nFrom: Office of {name}\nYour performance has brought us to a "
                f"crisis point. This is an explicit ultimatum: you have exactly {games} games to pull {need} standings "
                f"points out of this roster. If you fail to deliver, your security code to the executive suite will be "
                f"deactivated. Fix this immediately.")
    if arch == "The Moneyballer":
        return (f"--- INTERNAL MEMO: PERFORMANCE MODEL ---\nFrom: {name}\nEvery efficiency metric we track is "
                f"flashing red. The model gives this group {games} games to produce {need} points; below that, the "
                f"projection says a change in hockey operations is the highest-value move. The numbers will decide.")
    if arch == "The Penny Pincher":
        return (f"--- INTERNAL MEMO ---\nFrom: {name}\nWe are paying for a playoff team and getting something else. "
                f"{need} points from the next {games} games, or we will find someone who can do more with what we "
                f"spend.")
    if arch == "The Patient Builder":
        return (f"--- INTERNAL MEMO: PERFORMANCE REVIEW ---\nFrom: {name}\nYou know I have backed the plan. But the "
                f"plan needs to show signs of life: {need} points from the next {games} games. I do not want to make a "
                f"change, but I will.")
    if arch == "The Traditionalist":
        return (f"--- INTERNAL MEMO ---\nFrom: {name}\nThis team has lost its identity. I want to see {style} and "
                f"{need} points from the next {games} games. That is not a request.")
    return (f"--- INTERNAL MEMO: PERFORMANCE REVIEW ---\nFrom: {name}\nWe have hit a critical threshold regarding "
            f"organisational confidence. We need to see an immediate course correction over our next {games} games, "
            f"targeting a minimum of {need} points. We want to support your vision, but we require results.")


def daily(conn, day):
    """Resolve ultimatums whose window has been played; check directive deadlines. Returns lines."""
    if K.season_state(conn) != "regular_season" or not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ultimatums'").fetchone():
        return []
    season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    lines = []
    for u in conn.execute("SELECT * FROM ultimatums WHERE status='open'").fetchall():
        gp, pts = _record(conn, u["team_id"], season_id)
        played, got = gp - u["gp_at_issue"], pts - u["pts_at_issue"]
        if got >= u["points_needed"]:
            lines += _resolve(conn, u, day, True, played, got)
        elif played >= u["games"]:
            lines += _resolve(conn, u, day, False, played, got)
    me = user_team(conn)
    if me:
        lines += _directives_check(conn, me, day)
    return lines


def _resolve(conn, u, day, met, played, got):
    t = u["team_id"]
    me = user_team(conn)
    o = owner(conn, t)
    result = f"{got} points from {played} games (needed {u['points_needed']})"
    conn.execute("UPDATE ultimatums SET status=?, resolved=?, result=? WHERE ultimatum_id=?",
                 ("met" if met else "failed", day, result, u["ultimatum_id"]))
    if met:
        org._apply(conn, t, MET_BONUS, "ultimatum", day, [f"ultimatum met: {result} +{MET_BONUS:.0f}"])
        conn.execute("UPDATE board SET warnings=0 WHERE team_id=?", (t,))
        if t == me:
            add_message(conn, day, "The owner is satisfied, for now",
                        f"{o['name']}: \"{result}. That is what I needed to see. Keep it going.\"")
        return [f"{team_abbr(conn, t)} met the owner's ultimatum"]
    if t != me and _scapegoat(conn, t, day, org.season_year(conn)):
        conn.execute("UPDATE board SET warnings=0 WHERE team_id=?", (t,))     # the coach takes the fall this time
        return [f"{team_abbr(conn, t)} missed the ultimatum; the head coach is fired instead"]
    return fire_gm(conn, t, day, f"failed the owner's ultimatum ({result})")


def fire_gm(conn, t, day, why):
    """In-season firing (AI or user): the GM goes now; an interim takes over and the job is open."""
    me = user_team(conn)
    o = owner(conn, t)
    b = conn.execute("SELECT * FROM board WHERE team_id=?", (t,)).fetchone()
    voc = o["vocalness"] or 0.5
    surprise = voc < 0.3
    rng = random.Random(f"{_seed(conn)}-{day}-interim-{t}")
    from . import gm as GMx
    if t == me and not GMx.can_be_fired(conn):
        conn.execute("UPDATE board SET warnings=0, confidence=MAX(confidence, 25) WHERE team_id=?", (t,))
        conn.execute("UPDATE directives SET status='void', result='kept on' WHERE team_id=? AND status='open'", (t,))
        add_message(conn, day, "Still in the chair", f"{o['name']} wanted you gone ({why}). In this career you cannot be fired, "
                                                       "so you stay; his confidence is reset to 25.")
        return [f"The owner would have fired you ({why}); you stay on"]
    if t == me:
        conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('gm_status', 'fired')")
        add_message(conn, day, "Dismissed", f"{o['name']} has relieved you of your duties: {why}. The Job Centre lists "
                                            "the clubs looking for a GM; Continue plays on while you look.")
        try:
            from . import gm as GMx
            GMx.ensure_tables(conn)
            conn.execute("UPDATE gm_career SET end_date=?, how_ended='fired' WHERE end_date IS NULL", (day,))
        except Exception:
            pass
    who = "general manager " + (b["gm_name"] if t != me else "(you)")
    text = (f"Stunner: {team_abbr(conn, t)} fire {who}" if surprise else f"{team_abbr(conn, t)} fire {who}")
    emit(conn, "GM_FIRED", day, text, team_id=t, importance=3, why=why, surprise=surprise, in_season=True)
    interim = f"{rng.choice(org.GM_FIRST)} {rng.choice(org.GM_LAST)}"
    conn.execute("UPDATE board SET gm_name=?, gm_since=?, confidence=58, warnings=0, vacancy=1 WHERE team_id=?",
                 (f"{interim} (interim)", org.season_year(conn), t))
    emit(conn, "GM_HIRED", day, f"{team_abbr(conn, t)} name {interim} interim general manager", team_id=t, importance=2)
    conn.execute("UPDATE directives SET status='void', result='GM fired' WHERE team_id=? AND status='open'", (t,))
    if t == me:
        GMx.lose_job(conn, day, "fired")
    return [f"{team_abbr(conn, t)} fired their GM ({why})"]


# ---------------------------------------------------------------- media leaks

def _leak(conn, t, day, o, stage, tr, games=None, points=None, coach=None):
    """A rumour through the fictional insider accounts, by the owner's vocalness."""
    voc = o["vocalness"] or 0.5
    year = org.season_year(conn)
    key = f"leak_{stage}"
    if _flag(conn, t, year, key) and stage == "pressure":
        return
    _flag(conn, t, year, key, day)
    if voc < 0.3:
        return                                          # silence until the day it happens
    rng = random.Random(f"{_seed(conn)}-{day}-leak-{t}-{stage}")
    club = team_abbr(conn, t)
    style = rng.choice(IDENTITY_WORDS.get(o["identity"] or "", ["a different identity"]))
    if voc > 0.8:
        if stage == "pressure":
            text = rng.choice([
                f"Hearing from sources close to {club}'s owner that he is completely enamoured with {style}. "
                "A coaching change feels imminent.",
                f"Ownership in {club} is not happy, and is not hiding it. The word I keep hearing is 'identity': "
                f"they want {style}."])
        elif stage == "coach":
            text = f"Told {club}'s owner has lost faith in the bench. {coach} is on very thin ice."
        else:
            text = (f"Word out of {club} is that ownership's patience has evaporated. Hearing the GM has been given a "
                    f"{games}-game window, and the number is {points} points. Expect a firing if they don't get there.")
        delay = 0
    else:
        if stage != "ultimatum":
            return
        text = rng.choice([f"There is definite smoke around the {club} front office.",
                           f"Things are getting tense behind the scenes in {club}. Results matter now, not later.",
                           f"Not hearing anything concrete, but {club}'s ownership is watching every game."])
        delay = rng.randint(2, 4)
    when = (datetime.date.fromisoformat(day) + datetime.timedelta(days=delay)).isoformat()
    emit(conn, "RUMOUR", when, text, team_id=t, importance=2, kind=f"leak_{stage}", vocalness=voc,
         specific=voc > 0.8)


# ---------------------------------------------------------------- directives (the user's club)

def open_directive(conn, t):
    return conn.execute("SELECT * FROM directives WHERE team_id=? AND status='open' ORDER BY directive_id DESC LIMIT 1",
                        (t,)).fetchone()


def _directives_weekly(conn, t, day, season_id, year):
    if open_directive(conn, t) or conn.execute("SELECT 1 FROM pack_info WHERE key='gm_status'").fetchone():
        return []
    o = owner(conn, t)
    rng = random.Random(f"{_seed(conn)}-{day}-directive")
    if rng.random() >= 0.1 + o["involvement"] / 40:
        return []
    from .trades import deadline
    dl = deadline(conn).isoformat()
    end = conn.execute("SELECT MAX(game_date) FROM games WHERE season_id=? AND game_type='RS'", (season_id,)).fetchone()[0]
    options = []
    before_deadline = day < dl
    if before_deadline:
        budget = conn.execute("SELECT target FROM objectives WHERE team_id=? AND season_start_year=? AND "
                              "code='payroll'", (t, year)).fetchone()
        over = budget and K.payroll(conn, t) > budget[0]
        if o["spend"] <= 4 or over:
            vets = []
            for r in conn.execute("SELECT p.player_id, p.birth_date FROM players p WHERE p.team_id=? AND p.status IN "
                                  "('active','injured','prospect')", (t,)):
                c = K.current_contract(conn, r["player_id"])
                if c and c["cap_hit"] >= 4_000_000 and K.age_on(r["birth_date"], datetime.date.fromisoformat(day)) >= 30:
                    vets.append((c["cap_hit"], r["player_id"]))
            if vets:
                hit, pid = max(vets)
                options.append(("move_veteran", f"Move {player_name(conn, pid)}'s contract (${hit / 1e6:.2f}M) before "
                                f"the trade deadline", json.dumps(dict(player_id=pid)), dl))
        gp, pts = _record(conn, t, season_id)
        if o["ambition"] >= 7 and gp and pts / (2 * gp) < 0.55:
            mv = K.day_values(conn)
            fwd = sorted((mv.value(r["player_id"]) for r in conn.execute(
                "SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured') AND position IN "
                "('C','LW','RW')", (t,))), reverse=True)
            bar = fwd[5] if len(fwd) >= 6 else 0
            options.append(("add_forward", "Add a top-six forward before the trade deadline",
                            json.dumps(dict(bar=bar, since=day)), dl))
    from .tactics import system_of
    if o["involvement"] >= 6 and o["identity"] and system_of(conn, t) != o["identity"]:
        two_weeks = (datetime.date.fromisoformat(day) + datetime.timedelta(days=14)).isoformat()
        options.append(("play_identity", f"Change the team's system to {o['identity']}", json.dumps(dict(
            system=o["identity"])), two_weeks))
    if o["youth_pref"] >= 7 and not _flag(conn, t, year, "keep_youth_issued"):
        options.append(("keep_youth", "Do not trade any player 23 or under this season", json.dumps({}), end))
    mv = K.day_values(conn)
    core = sorted(((mv.value(r["player_id"]), r["player_id"]) for r in conn.execute(
        "SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')", (t,))), reverse=True)[:4]
    for _, pid in core:
        c = K.current_contract(conn, pid)
        if c and c["start_year"] + c["years"] - 1 == year and not K.current_contract(conn, pid, year + 1):
            options.append(("extend_core", f"Extend {player_name(conn, pid)} before the end of the regular season",
                            json.dumps(dict(player_id=pid)), end))
            break
    if not options:
        return []
    code, desc, target, deadline_day = rng.choice(options)
    if code == "keep_youth":
        _flag(conn, t, year, "keep_youth_issued", day)
    conn.execute("INSERT INTO directives (team_id, season, code, description, target, issued, deadline) VALUES "
                 "(?,?,?,?,?,?,?)", (t, year, code, desc, target, day, deadline_day))
    add_message(conn, day, "A directive from the owner", f"{o['name']}: \"{desc}.\" (deadline {deadline_day}; "
                f"missing it will cost you with the board)")
    return [f"Owner's directive: {desc} (by {deadline_day})"]


def _directive_status(conn, t, d, day):
    """'met', 'failed' or None (still open)."""
    tgt = json.loads(d["target"] or "{}")
    code = d["code"]
    if code == "move_veteran":
        if conn.execute("SELECT team_id FROM players WHERE player_id=?", (tgt["player_id"],)).fetchone()[0] != t:
            return "met"
    elif code == "add_forward":
        mv = K.day_values(conn)
        for (pid,) in conn.execute("SELECT DISTINCT player_id FROM transactions WHERE to_team_id=? AND txn_date>=? AND "
                                   "txn_type IN ('trade','sign','waiver_claim')", (t, tgt["since"])):
            p = conn.execute("SELECT position, team_id FROM players WHERE player_id=?", (pid,)).fetchone()
            if p and p["team_id"] == t and p["position"] in ("C", "LW", "RW") and mv.value(pid) >= tgt["bar"]:
                return "met"
    elif code == "keep_youth":
        for r in conn.execute("SELECT player_id, txn_date FROM transactions WHERE from_team_id=? AND txn_type='trade' "
                              "AND txn_date>=?", (t, d["issued"])):
            b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (r[0],)).fetchone()[0]
            if K.age_on(b, datetime.date.fromisoformat(r[1])) <= 23:
                return "failed"
        if day >= d["deadline"]:
            return "met"
        return None
    elif code == "play_identity":
        from .tactics import system_of
        if system_of(conn, t) == tgt["system"]:
            return "met"
    elif code == "extend_core":
        if K.current_contract(conn, tgt["player_id"], org.season_year(conn) + 1):
            return "met"
    return "failed" if day >= d["deadline"] else None


def _directives_check(conn, t, day):
    d = open_directive(conn, t)
    if d is None:
        return []
    st = _directive_status(conn, t, d, day)
    if st is None:
        return []
    o = owner(conn, t)
    conn.execute("UPDATE directives SET status=?, result=? WHERE directive_id=?", (st, day, d["directive_id"]))
    if st == "met":
        org._apply(conn, t, DIRECTIVE_GAIN, "directive", day, [f"{d['description']}: done +{DIRECTIVE_GAIN:.0f}"])
        add_message(conn, day, "Directive done", f"{o['name']}: \"Good. That is what I asked for.\"")
        return [f"Directive met: {d['description']}"]
    loss = DIRECTIVE_LOSS * (1.2 - o["patience"] / 10) * (1 + o["involvement"] / 20)
    org._apply(conn, t, -loss, "directive", day, [f"{d['description']}: not done -{loss:.1f}"])
    add_message(conn, day, "Directive missed", f"{o['name']}: \"I asked you to {d['description'][0].lower()}"
                f"{d['description'][1:]}. You did not.\" Board confidence -{loss:.1f}.")
    lines = [f"Directive missed: {d['description']} (-{loss:.1f})"]
    lines += evaluate(conn, t, day)                    # the drop feeds straight into the hot-seat score
    return lines


# ---------------------------------------------------------------- season end

def end_of_season(conn, day):
    """Open ultimatums are judged on what was played; open directives due at season end are checked."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ultimatums'").fetchone():
        return []
    season_id = conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]
    lines = []
    for u in conn.execute("SELECT * FROM ultimatums WHERE status='open'").fetchall():
        gp, pts = _record(conn, u["team_id"], season_id)
        played, got = gp - u["gp_at_issue"], pts - u["pts_at_issue"]
        need = math.ceil(u["points_needed"] * played / max(1, u["games"]))
        lines += _resolve(conn, u, day, got >= need, played, got)
    me = user_team(conn)
    if me:
        d = open_directive(conn, me)
        if d and d["deadline"] <= day:
            lines += _directives_check(conn, me, day)
    return lines
