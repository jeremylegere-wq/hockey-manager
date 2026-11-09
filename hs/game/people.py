"""The locker room: personality, morale, leadership, cohesion, concerns, conversations and promises.

Separate measures, not one morale number (spec 3.3). Each player has components on 0-100:
  role       ice time against what he believes his place in the lineup is (value rank vs last-10-games TOI rank);
             minor-leaguers who think they are NHL players also count here
  team       recent results against the club's expectation, weighted by his ambition
  contract   paid below his market value, or in a final year with no extension
  trust_mgmt promises kept or broken, how conversations went, leaders traded away
  trust_coach the head coach's communication/leadership and style against his personality
morale = 0.35 role + 0.20 team + 0.15 contract + 0.15 trust_mgmt + 0.15 trust_coach. Components move a quarter of
the way to their weekly target (resilient players fall more slowly), with a little noise.

Cohesion (team) is driven by average morale, leadership strength (captain and alternates), roster turnover and
clashes (high-ego, low-professionalism players who are unhappy) - not by wins directly, so a winning room can
sour and a losing one can hold together. Morale does not change match ratings (by design, for now).

Concerns become meeting requests for the user's club: role, contract (final year), call-up (a minor-leaguer who
believes he is ready) and trade requests (persistently miserable, impatient, ambitious players). The user responds
with an approach; only `promise` creates a binding, measurable commitment, and the CLI says so before it is made.
"""
from __future__ import annotations

import datetime
import json
import random

from ..schema import top_league_sql
from . import contracts as K
from .events import emit, player_name, team_abbr
from .roster import group, player_value
from .state import add_message, get_state, user_team

TRAITS = ["professionalism", "ambition", "loyalty", "leadership", "resilience", "patience", "ego", "role_tolerance"]
COMPONENTS = ["role", "team", "contract", "trust_mgmt", "trust_coach"]
WEIGHTS = {"role": 0.35, "team": 0.20, "contract": 0.15, "trust_mgmt": 0.15, "trust_coach": 0.15}
APPROACHES = ["supportive", "direct", "firm", "diplomatic", "promise"]
CONCERN_WEEKS = 6
PROMISE_TEXT = {
    "role": "a top-{n} role ({grp}) by average ice time over his next 10 games",
    "contract": "an extension offer he accepts before {deadline}",
    "callup": "an NHL call-up with at least 3 NHL games before {deadline}",
    "trade": "a trade before {deadline}",
}


def ensure_tables(conn):
    conn.execute(f"CREATE TABLE IF NOT EXISTS personality (player_id INTEGER PRIMARY KEY, "
                 f"{', '.join(t + ' INTEGER' for t in TRAITS)})")
    conn.execute("CREATE TABLE IF NOT EXISTS morale (player_id INTEGER PRIMARY KEY, morale REAL, role REAL, team REAL, "
                 "contract REAL, trust_mgmt REAL, trust_coach REAL, low_weeks INTEGER DEFAULT 0, trade_request INTEGER "
                 "DEFAULT 0, updated TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS leadership (team_id INTEGER, player_id INTEGER, role TEXT, since TEXT, "
                 "PRIMARY KEY (team_id, player_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS team_room (team_id INTEGER PRIMARY KEY, cohesion REAL, "
                 "leadership_strength REAL, atmosphere TEXT, updated TEXT, reasons TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS concerns (concern_id INTEGER PRIMARY KEY, player_id INTEGER, team_id INTEGER, "
                 "topic TEXT, raised_on TEXT, status TEXT DEFAULT 'open', detail TEXT, reassurances INTEGER DEFAULT 0, "
                 "expires_on TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS promises (promise_id INTEGER PRIMARY KEY, player_id INTEGER, team_id INTEGER, "
                 "made_on TEXT, ptype TEXT, description TEXT, params TEXT, deadline TEXT, importance INTEGER, "
                 "status TEXT DEFAULT 'active', resolved_on TEXT, note TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS conversations (conv_id INTEGER PRIMARY KEY, player_id INTEGER, "
                 "team_id INTEGER, conv_date TEXT, topic TEXT, approach TEXT, outcome TEXT, trust_change REAL, "
                 "component_change REAL, promise_id INTEGER)")


def _seed(conn):
    return get_state(conn)[1]


def nhl_teams(conn):
    return [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()} ORDER BY team_id")]


def _clip(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


# ---------------- setup

def personality_for(conn, pid, rng):
    a = conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (pid,)).fetchone()
    g = lambda m=10, s=3: max(1, min(20, round(rng.gauss(m, s))))
    take = lambda attr: (a[attr] if a is not None and a[attr] not in (None, 10) else g())
    val = player_value(conn, pid)
    ego = max(1, min(20, round(rng.gauss(9 + (val - 50) / 6, 3))))
    prof = take("professionalism")
    return dict(professionalism=prof, ambition=g(), loyalty=g(), leadership=take("leadership"),
                resilience=take("mental_toughness"), patience=g(), ego=ego,
                role_tolerance=max(1, min(20, round((20 - ego) / 2 + prof / 2 + rng.gauss(0, 2)))))


def setup(conn, day):
    ensure_tables(conn)
    seed = _seed(conn)
    have = {r[0] for r in conn.execute("SELECT player_id FROM personality")}
    rows = conn.execute("SELECT player_id FROM players WHERE team_id IS NOT NULL AND status<>'retired'").fetchall()
    for (pid,) in rows:
        if pid in have:
            continue
        rng = random.Random(f"{seed}-personality-{pid}")
        p = personality_for(conn, pid, rng)
        conn.execute(f"INSERT INTO personality VALUES (?, {', '.join('?' * len(TRAITS))})", [pid] + [p[t] for t in TRAITS])
        conn.execute("INSERT OR IGNORE INTO morale (player_id, morale, role, team, contract, trust_mgmt, trust_coach, "
                     "updated) VALUES (?,65,65,60,65,60,60,?)", (pid, day))
    for t in nhl_teams(conn):
        if not conn.execute("SELECT 1 FROM leadership WHERE team_id=?", (t,)).fetchone():
            choose_leaders(conn, t, day)
        conn.execute("INSERT OR IGNORE INTO team_room (team_id, cohesion, leadership_strength, atmosphere, updated) "
                     "VALUES (?, 60, 10, 'good', ?)", (t, day))


def traits(conn, pid):
    r = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone()
    if r is None:
        rng = random.Random(f"{_seed(conn)}-personality-{pid}")
        p = personality_for(conn, pid, rng)
        conn.execute(f"INSERT INTO personality VALUES (?, {', '.join('?' * len(TRAITS))})", [pid] + [p[t] for t in TRAITS])
        conn.execute("INSERT OR IGNORE INTO morale (player_id, morale, role, team, contract, trust_mgmt, trust_coach) "
                     "VALUES (?,60,60,60,60,55,55)", (pid,))
        return p
    return dict(r)


def log_event(conn, pid, day, component, delta, reason):
    """v35: the player's happiness log (what moved his morale, and why), for the Personality and morale tab."""
    conn.execute("CREATE TABLE IF NOT EXISTS morale_log (player_id INTEGER, day TEXT, component TEXT, delta REAL, reason TEXT)")
    conn.execute("INSERT INTO morale_log VALUES (?,?,?,?,?)", (pid, day, component, round(delta, 1), reason))


def morale_history(conn, pid, n=25):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale_log'").fetchone():
        return []
    return [dict(day=r[0], component=r[1], delta=r[2], reason=r[3]) for r in conn.execute(
        "SELECT day, component, delta, reason FROM morale_log WHERE player_id=? ORDER BY day DESC, rowid DESC LIMIT ?", (pid, n))]


def choose_leaders(conn, t, day):
    rows = conn.execute("SELECT p.player_id, p.birth_date, s.leadership, s.professionalism FROM players p "
                        "JOIN personality s USING (player_id) WHERE p.team_id=? AND p.status IN ('active','injured') "
                        "AND p.position<>'G'", (t,)).fetchall()                # goalies cannot wear a letter
    on = datetime.date.fromisoformat(day)
    score = lambda r: (r["leadership"] * 2 + r["professionalism"] + min(10, max(0, (on.year - int(r["birth_date"][:4])) - 22))
                       + player_value(conn, r["player_id"]) / 10)
    best = sorted(rows, key=lambda r: (-score(r), r["player_id"]))[:3]
    conn.execute("DELETE FROM leadership WHERE team_id=?", (t,))
    for i, r in enumerate(best):
        conn.execute("INSERT INTO leadership VALUES (?,?,?,?)", (t, r["player_id"], "C" if i == 0 else "A", day))


def set_captain(conn, t, pid, day):
    if conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0] == "G":
        raise ValueError("Goalies cannot be captain or alternate captain (a league rule since 1948).")
    old = conn.execute("SELECT player_id FROM leadership WHERE team_id=? AND role='C'", (t,)).fetchone()
    if old and old[0] == pid:
        raise ValueError("He is already the captain.")
    conn.execute("DELETE FROM leadership WHERE team_id=? AND player_id=?", (t, pid))
    if old:
        conn.execute("UPDATE leadership SET role='A' WHERE team_id=? AND player_id=?", (t, old[0]))
        tr = traits(conn, old[0])
        hit = 4 + max(0, tr["ego"] - 10) * 1.2
        conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-?), role=MAX(0, role-?) WHERE player_id=?",
                     (hit, hit / 2, old[0]))
        conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-3) WHERE team_id=?", (t,))
    conn.execute("INSERT INTO leadership VALUES (?,?,?,?)", (t, pid, "C", day))
    emit(conn, "CAPTAIN_CHANGED", day, f"{team_abbr(conn, t)} name {player_name(conn, pid)} captain", team_id=t,
         player_id=pid, importance=2, previous=old[0] if old else None)


# ---------------- weekly update

def _toi_ranks(conn, t, since_games=10):
    """{pid: (avg toi, games)} over the club's last N games, and the rank by group."""
    games = [r[0] for r in conn.execute("SELECT game_id FROM games WHERE played=1 AND game_type='RS' AND "
                                        "(home_team_id=? OR away_team_id=?) ORDER BY game_date DESC LIMIT ?",
                                        (t, t, since_games))]
    if not games:
        return {}, 0
    q = f"SELECT player_id, AVG(toi_sec) toi, COUNT(*) gp FROM player_game_stats WHERE team_id=? AND game_id IN " \
        f"({','.join('?' * len(games))}) GROUP BY player_id"
    return {r["player_id"]: (r["toi"] / max(1, len(games)) * r["gp"], r["gp"]) for r in conn.execute(q, (t, *games))}, \
        len(games)


def _expectation_pct(conn, t):
    r = conn.execute("SELECT description FROM objectives WHERE team_id=? AND category='competitive' ORDER BY "
                     "season_start_year DESC LIMIT 1", (t,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='objectives'").fetchone() else None
    if r is None:
        return 0.55
    d = r[0]
    return 0.64 if "conference" in d else 0.60 if "round" in d else 0.56 if "Make" in d else 0.50 if "race" in d else 0.42


def _recent_pct(conn, t, n=10):
    rows = conn.execute("SELECT home_team_id h, home_goals hg, away_goals ag, went_to_ot ot FROM games WHERE played=1 "
                        "AND game_type='RS' AND (home_team_id=? OR away_team_id=?) ORDER BY game_date DESC LIMIT ?",
                        (t, t, n)).fetchall()
    if not rows:
        return None
    pts = 0
    for r in rows:
        mine, theirs = (r["hg"], r["ag"]) if r["h"] == t else (r["ag"], r["hg"])
        pts += 2 if mine > theirs else 1 if r["ot"] else 0
    return pts / (2 * len(rows))


def weekly(conn, day):
    """Update morale, cohesion, concerns and promises for every NHL club."""
    ensure_tables(conn)
    me = user_team(conn)
    rng = random.Random(f"{_seed(conn)}-{day}-room")
    year = K.season_year(conn)
    values_all = K.league_values(conn)
    for t in nhl_teams(conn):
        roster = conn.execute("SELECT player_id, position, status FROM players WHERE team_id=? AND status IN "
                              "('active','injured','prospect')", (t,)).fetchall()
        if not roster:
            continue
        conn.execute("DELETE FROM leadership WHERE team_id=? AND player_id NOT IN (SELECT player_id FROM players "
                     "WHERE team_id=? AND status IN ('active','injured'))", (t, t))
        if not conn.execute("SELECT 1 FROM leadership WHERE team_id=? AND role='C'", (t,)).fetchone():
            choose_leaders(conn, t, day)
        toi, n_games = _toi_ranks(conn, t)
        active = [r for r in roster if r["status"] in ("active", "injured")]
        val = {r["player_id"]: player_value(conn, r["player_id"]) for r in roster}
        hc = conn.execute("SELECT * FROM staff WHERE team_id=? AND role='HC'", (t,)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone() else None
        recent = _recent_pct(conn, t)
        expect = _expectation_pct(conn, t)
        moods = []
        for g in ("F", "D", "G"):
            grp = [r for r in active if group(r["position"]) == g]
            by_value = sorted(grp, key=lambda r: -val[r["player_id"]])
            by_toi = sorted(grp, key=lambda r: -(toi.get(r["player_id"], (0, 0))[0]))
            vrank = {r["player_id"]: i + 1 for i, r in enumerate(by_value)}
            trank = {r["player_id"]: i + 1 for i, r in enumerate(by_toi)}
            worst_active = min((val[r["player_id"]] for r in grp), default=0)
            for r in roster:
                if group(r["position"]) != g:
                    continue
                pid = r["player_id"]
                tr = traits(conn, pid)
                m = conn.execute("SELECT * FROM morale WHERE player_id=?", (pid,)).fetchone()
                if m is None:
                    continue
                m = dict(m)
                sens = 1.3 - tr["role_tolerance"] / 20
                if r["status"] == "prospect":
                    ready = val[pid] - worst_active
                    target_role = 65 - max(0, ready) * 4 * (tr["ambition"] / 10) if n_games else m["role"]
                elif n_games >= 3 and r["status"] == "active":
                    gap = trank[pid] - vrank[pid]
                    scratched = toi.get(pid, (0, 0))[1] == 0
                    per = 6 if g == "D" else 4 if g == "F" else 25
                    target_role = 70 - max(0, gap) * per * sens + min(0, gap) * -1.5 - (20 * sens if scratched else 0)
                else:
                    target_role = m["role"]
                target_team = m["team"] if recent is None else 55 + (recent - expect) * 120 * (0.5 + tr["ambition"] / 20)
                c = K.current_contract(conn, pid)
                target_contract = 65.0
                if c:
                    market = K.market_aav(conn, pid, values_all)
                    under = (market - c["cap_hit"]) / 1_000_000
                    if under > 0.5:
                        target_contract -= under * 5 * (0.5 + (tr["ego"] + tr["ambition"]) / 40)
                    if c["start_year"] + c["years"] - 1 == year and day[5:7] in ("12", "01", "02", "03", "04") \
                            and not conn.execute("SELECT 1 FROM contracts WHERE player_id=? AND start_year>?",
                                                 (pid, year)).fetchone() and val[pid] >= 52:
                        target_contract -= 8 * tr["ambition"] / 10
                target_coach = m["trust_coach"]
                if hc is not None:
                    target_coach = 55 + (hc["communication"] - 10) * 1.5 + (hc["leadership"] - 10)
                    if hc["style"] == "demanding" and tr["professionalism"] < 9:
                        target_coach -= 8
                    if hc["style"] == "players' coach" and tr["ego"] >= 13:
                        target_coach += 5
                    target_coach -= max(0, 50 - m["role"]) * 0.5
                why = {"role": ("he thinks he is ready for the NHL" if r["status"] == "prospect" else
                                "scratched" if r["status"] == "active" and n_games >= 3 and toi.get(pid, (0, 0))[1] == 0 else
                                f"ice time below his place (#{vrank.get(pid)} by ability, #{trank.get(pid)} by ice time)"
                                if r["status"] == "active" and n_games >= 3 and trank.get(pid, 0) > vrank.get(pid, 0) else "a role that suits him"),
                       "team": "the team's results" + ("" if recent is None else " against what he expected" if recent < expect else ", better than expected"),
                       "contract": "his contract against what he is worth" if c and target_contract < 60 else "his contract",
                       "trust_coach": "the head coach" + (f" ({hc['style']})" if hc is not None and hc["style"] else "")}
                for comp, target in (("role", target_role), ("team", target_team), ("contract", target_contract),
                                     ("trust_coach", target_coach)):
                    target = _clip(target)
                    step = 0.25 * (target - m[comp])
                    if step < 0:
                        step *= 1.2 - tr["resilience"] / 25
                    old = m[comp]
                    m[comp] = _clip(m[comp] + step + rng.gauss(0, 1.0))
                    if abs(m[comp] - old) >= 3:
                        log_event(conn, pid, day, comp, (m[comp] - old) * WEIGHTS[comp], why[comp])
                m["morale"] = sum(WEIGHTS[k] * m[k] for k in COMPONENTS)
                m["low_weeks"] = m["low_weeks"] + 1 if m["morale"] < 32 else 0
                conn.execute("UPDATE morale SET morale=?, role=?, team=?, contract=?, trust_coach=?, low_weeks=?, "
                             "updated=? WHERE player_id=?", (m["morale"], m["role"], m["team"], m["contract"],
                                                             m["trust_coach"], m["low_weeks"], day, pid))
                if r["status"] != "prospect":
                    moods.append((pid, m, tr))
                _maybe_concern(conn, t, pid, r, m, tr, val[pid], worst_active, day, me, year)
        _update_room(conn, t, moods, day)
    if me is not None:                                     # your motivation rating (phase A2): trust in you drifts each week
        from . import gm as GMx
        drift = 0.12 * (GMx.rating(conn, "motivation") - 10)
        if drift:
            conn.execute("UPDATE morale SET trust_mgmt=MAX(0, MIN(100, trust_mgmt+?)) WHERE player_id IN "
                         "(SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured','ltir'))", (drift, me))
    _promises(conn, day)
    _expire_concerns(conn, day)


def _update_room(conn, t, moods, day):
    if not moods:
        return
    lead = conn.execute("SELECT l.role, s.leadership, m.trust_mgmt FROM leadership l JOIN personality s USING "
                        "(player_id) LEFT JOIN morale m USING (player_id) WHERE l.team_id=?", (t,)).fetchall()
    cap = [r["leadership"] for r in lead if r["role"] == "C"]
    alts = [r["leadership"] for r in lead if r["role"] == "A"]
    strength = 0.55 * (cap[0] if cap else 8) + 0.45 * (sum(alts) / len(alts) if alts else 8)
    avg = sum(m["morale"] for _, m, _ in moods) / len(moods)
    since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=30)).isoformat()
    turnover = conn.execute("SELECT COUNT(*) FROM league_events WHERE event_type='PLAYER_TRADED' AND event_date>=? AND "
                            "(team_id=? OR other_team_id=?)", (since, t, t)).fetchone()[0]
    clashes = sum(1 for _, m, tr in moods if tr["ego"] >= 15 and tr["professionalism"] <= 8 and m["morale"] < 40)
    requests = sum(1 for pid, _, _ in moods if conn.execute("SELECT trade_request FROM morale WHERE player_id=?",
                                                           (pid,)).fetchone()[0])
    target = 50 + (avg - 55) * 0.7 + (strength - 10) * 2.0 - min(10, turnover * 2) - clashes * 4 - requests * 3
    r = conn.execute("SELECT cohesion FROM team_room WHERE team_id=?", (t,)).fetchone()
    cur = r[0] if r else 55
    new = _clip(cur + 0.3 * (target - cur))
    atm = ("excellent" if new >= 70 else "good" if new >= 55 else "okay" if new >= 40 else "tense" if new >= 28
           else "toxic")
    reasons = [f"average morale {avg:.0f}", f"leadership {strength:.1f}/20"]
    if turnover:
        reasons.append(f"{turnover} trade(s) in the last 30 days")
    if clashes:
        reasons.append(f"{clashes} unhappy strong personalities")
    if requests:
        reasons.append(f"{requests} trade request(s)")
    conn.execute("INSERT OR REPLACE INTO team_room VALUES (?,?,?,?,?,?)", (t, new, strength, atm, day,
                                                                         json.dumps(reasons)))


# ---------------- concerns and trade requests

def _open_concern(conn, pid, topic):
    return conn.execute("SELECT * FROM concerns WHERE player_id=? AND topic=? AND status='open'", (pid, topic)).fetchone()


def _raise(conn, t, pid, topic, detail, day, me):
    """Meeting requests are for the user's club; AI clubs handle their players' grumbles privately (only trade
    requests become public events, raised in _maybe_concern)."""
    if t != me:
        return
    if _open_concern(conn, pid, topic) or conn.execute(
            "SELECT 1 FROM promises WHERE player_id=? AND ptype=? AND status='active'", (pid, topic)).fetchone():
        return
    expires = (datetime.date.fromisoformat(day) + datetime.timedelta(weeks=CONCERN_WEEKS)).isoformat()
    conn.execute("INSERT INTO concerns (player_id, team_id, topic, raised_on, detail, expires_on) VALUES (?,?,?,?,?,?)",
                 (pid, t, topic, day, detail, expires))
    emit(conn, "CONCERN_RAISED", day, f"{player_name(conn, pid)}: {detail}", team_id=t, player_id=pid,
         importance=2 if topic == "trade" else 1, topic=topic)
    if t == me:
        # v39 (#21): a button to the conversation, not a command with his id
        add_message(conn, day, "Meeting request", f"{player_name(conn, pid)} would like to talk: {detail}. He is "
                    "waiting for an answer; you can reassure him, be candid, hold the line or make a promise.",
                    actions=[dict(label=f"Talk to {player_name(conn, pid)}", href=f"#player/{pid}/person", primary=True)])


def _maybe_concern(conn, t, pid, r, m, tr, value, worst_active, day, me, year):
    if r["status"] == "prospect":
        if t == me and m["role"] < 45 and value >= worst_active + 2 and tr["ambition"] >= 11:
            _raise(conn, t, pid, "callup", "believes he is ready for the NHL", day, me)
        return
    if m["role"] < 38 and (tr["ego"] >= 11 or value >= 55):
        _raise(conn, t, pid, "role", "unhappy with his ice time and role", day, me)
    c = K.current_contract(conn, pid)
    extended = conn.execute("SELECT 1 FROM contracts WHERE player_id=? AND start_year>?", (pid, year)).fetchone()
    if c and c["start_year"] + c["years"] - 1 == year and not extended and m["contract"] < 52 and value >= 52 and \
            day[5:7] in ("12", "01", "02", "03"):            # v39 (#23): not once he has signed his extension
        _raise(conn, t, pid, "contract", "wants to know where his contract extension stands", day, me)
    if m["low_weeks"] >= 3 and (tr["ambition"] + 20 - tr["patience"]) / 2 >= 11:
        row = conn.execute("SELECT trade_request FROM morale WHERE player_id=?", (pid,)).fetchone()
        if row and not row[0]:
            conn.execute("UPDATE morale SET trade_request=1 WHERE player_id=?", (pid,))
            emit(conn, "TRADE_REQUEST", day, f"{player_name(conn, pid)} asks {team_abbr(conn, t)} for a trade",
                 team_id=t, player_id=pid, importance=3 if value >= 55 else 2)
            _raise(conn, t, pid, "trade", "has asked to be traded", day, me)


def _expire_concerns(conn, day):
    for r in conn.execute("SELECT * FROM concerns WHERE status='open' AND expires_on<?", (day,)).fetchall():
        conn.execute("UPDATE concerns SET status='ignored' WHERE concern_id=?", (r["concern_id"],))
        conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-4) WHERE player_id=?", (r["player_id"],))


# ---------------- conversations

def open_concerns(conn, t):
    return conn.execute("SELECT * FROM concerns WHERE team_id=? AND status='open' ORDER BY raised_on", (t,)).fetchall()


def credibility(conn, t):
    """Share of this club's resolved promises that were kept (1.0 with no history)."""
    rows = conn.execute("SELECT status FROM promises WHERE team_id=? AND status IN ('fulfilled','broken')", (t,)).fetchall()
    return 1.0 if not rows else sum(r[0] == "fulfilled" for r in rows) / len(rows)


def promise_terms(conn, pid, topic, day):
    """The binding commitment a `promise` response to this concern would create: (ptype, description, params,
    deadline, importance)."""
    d = datetime.date.fromisoformat(day)
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = group(pos)
    if topic == "role":
        n = {"F": 6, "D": 4, "G": 1}[g]
        grp = {"F": "forwards", "D": "defencemen", "G": "starting goalie"}[g]
        return ("role", PROMISE_TEXT["role"].format(n=n, grp=grp), {"group": g, "max_rank": n, "games": 10,
                                                                   "start": day},
                (d + datetime.timedelta(days=30)).isoformat(), 2)
    if topic == "contract":
        dl = (d + datetime.timedelta(days=30)).isoformat()
        return "contract", PROMISE_TEXT["contract"].format(deadline=dl), {}, dl, 2
    if topic == "callup":
        dl = (d + datetime.timedelta(days=21)).isoformat()
        return "callup", PROMISE_TEXT["callup"].format(deadline=dl), {"games": 3, "start": day}, dl, 2
    if topic == "trade":
        dl = (d + datetime.timedelta(days=45)).isoformat()
        return "trade", PROMISE_TEXT["trade"].format(deadline=dl), {}, dl, 3
    raise ValueError(f"no promise for topic {topic}")


def respond(conn, t, pid, approach, day):
    """Answer a player's open concern. Returns (text, promise description or None)."""
    if approach not in APPROACHES:
        raise ValueError(f"Approach must be one of {', '.join(APPROACHES)}.")
    c = conn.execute("SELECT * FROM concerns WHERE team_id=? AND player_id=? AND status='open' ORDER BY raised_on "
                     "LIMIT 1", (t, pid)).fetchone()
    if c is None:
        raise ValueError("He has nothing he wants to discuss right now.")
    tr = traits(conn, pid)
    m = dict(conn.execute("SELECT * FROM morale WHERE player_id=?", (pid,)).fetchone())
    rng = random.Random(f"{_seed(conn)}-{day}-talk-{pid}")
    comp = {"role": "role", "callup": "role", "contract": "contract", "trade": "trust_mgmt"}[c["topic"]]
    trust = change = 0.0
    status, promise_id, pdesc = "open", None, None
    if approach == "supportive":
        fade = 0.5 ** c["reassurances"]
        trust, change = 3 * fade, 5 * fade
        if c["reassurances"] >= 2:
            trust, change = -3, -2
            text = "He has heard the reassurance before and no longer believes it."
        else:
            text = "He appreciates the support."
        conn.execute("UPDATE concerns SET reassurances=reassurances+1 WHERE concern_id=?", (c["concern_id"],))
    elif approach == "direct":
        if tr["professionalism"] >= 12 or tr["ego"] <= 8:
            trust, change, text = 4, 2, "He respects the honesty, even if he does not like the answer."
        else:
            trust, change, text = -2, -3, "He takes the straight talk badly."
    elif approach == "firm":
        if tr["professionalism"] >= 13 and tr["ego"] < 14:
            trust, change, text = 2, 0, "He accepts the standard you have set."
        else:
            trust, change, text = -6, -4, "He feels dismissed and leaves angry."
        status = "closed"
    elif approach == "diplomatic":
        trust, change, text = 1, 1, "He leaves without a clear answer, but calm for now."
        new_exp = (datetime.date.fromisoformat(c["expires_on"]) + datetime.timedelta(weeks=3)).isoformat()
        conn.execute("UPDATE concerns SET expires_on=? WHERE concern_id=?", (new_exp, c["concern_id"]))
    else:
        ptype, pdesc, params, deadline, importance = promise_terms(conn, pid, c["topic"], day)
        cred = credibility(conn, t)
        trust, change = 6 * (0.5 + cred / 2), 10 * (0.5 + cred / 2)
        cur = conn.execute("INSERT INTO promises (player_id, team_id, made_on, ptype, description, params, deadline, "
                           "importance) VALUES (?,?,?,?,?,?,?,?)", (pid, t, day, ptype, pdesc, json.dumps(params),
                                                                    deadline, importance))
        promise_id = cur.lastrowid
        status = "promised"
        text = "He takes you at your word." if cred >= 0.7 else "He accepts, warily: your promises have been broken before."
        emit(conn, "PROMISE_MADE", day, f"{team_abbr(conn, t)} promise {player_name(conn, pid)} {pdesc}", team_id=t,
             player_id=pid, importance=importance, promise_id=promise_id)
    trust += rng.gauss(0, 0.5)
    m["trust_mgmt"] = _clip(m["trust_mgmt"] + trust)
    m[comp] = _clip(m[comp] + change)
    m["morale"] = sum(WEIGHTS[k] * m[k] for k in COMPONENTS)
    conn.execute("UPDATE morale SET trust_mgmt=?, role=?, contract=?, morale=? WHERE player_id=?",
                 (m["trust_mgmt"], m["role"], m["contract"], m["morale"], pid))
    if status != "open":
        conn.execute("UPDATE concerns SET status=? WHERE concern_id=?", (status, c["concern_id"]))
    log_event(conn, pid, day, "trust_mgmt", trust * WEIGHTS["trust_mgmt"] + change * WEIGHTS.get(comp, 0.15),
              f"a {approach} talk with you about {c['topic']}" + (" (a promise)" if promise_id else ""))
    conn.execute("INSERT INTO conversations (player_id, team_id, conv_date, topic, approach, outcome, trust_change, "
                 "component_change, promise_id) VALUES (?,?,?,?,?,?,?,?,?)",
                 (pid, t, day, c["topic"], approach, text, trust, change, promise_id))
    emit(conn, "CONVERSATION", day, f"{team_abbr(conn, t)} GM met {player_name(conn, pid)} about {c['topic']} "
         f"({approach})", team_id=t, player_id=pid, approach=approach, topic=c["topic"])
    conn.commit()
    return text, pdesc


# ---------------- promises

def _promises(conn, day):
    for p in conn.execute("SELECT * FROM promises WHERE status='active'").fetchall():
        params = json.loads(p["params"] or "{}")
        team_now = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (p["player_id"],)).fetchone()
        if p["ptype"] != "trade" and (team_now is None or team_now["team_id"] != p["team_id"]
                                      or team_now["status"] == "retired"):
            _resolve(conn, p, "withdrawn", day, "no longer applicable (he left the club)")
            continue
        verdict = None
        if p["ptype"] == "role":
            rows = conn.execute("SELECT g.game_id FROM games g WHERE g.played=1 AND g.game_type='RS' AND "
                                "(g.home_team_id=? OR g.away_team_id=?) AND g.game_date>? ORDER BY g.game_date LIMIT ?",
                                (p["team_id"], p["team_id"], params["start"], params["games"])).fetchall()
            if len(rows) >= params["games"]:
                ids = [r[0] for r in rows]
                q = f"SELECT s.player_id, SUM(s.toi_sec) toi FROM player_game_stats s JOIN players pl USING (player_id) " \
                    f"WHERE s.team_id=? AND s.game_id IN ({','.join('?' * len(ids))}) GROUP BY s.player_id"
                tot = {r[0]: r[1] for r in conn.execute(q, (p["team_id"], *ids))}
                pos = {r[0]: group(r[1]) for r in conn.execute(
                    f"SELECT player_id, position FROM players WHERE player_id IN ({','.join('?' * len(tot))})", list(tot))}
                peers = sorted((pid for pid in tot if pos.get(pid) == params["group"]), key=lambda x: -tot[x])
                rank = peers.index(p["player_id"]) + 1 if p["player_id"] in peers else 99
                verdict = ("fulfilled", f"ranked {rank} in ice time") if rank <= params["max_rank"] else \
                    ("broken", f"ranked {rank} in ice time")
            elif day > p["deadline"] and not rows:
                verdict = ("withdrawn", "no games played in the window")
        elif p["ptype"] == "contract":
            year = K.season_year(conn)
            if conn.execute("SELECT 1 FROM contracts WHERE player_id=? AND team_id=? AND start_year>?",
                            (p["player_id"], p["team_id"], year)).fetchone():
                verdict = ("fulfilled", "extension signed")
            elif day > p["deadline"]:
                verdict = ("broken", "no extension")
        elif p["ptype"] == "callup":
            gp = conn.execute("SELECT COUNT(*) FROM player_game_stats s JOIN games g USING (game_id) WHERE "
                              "s.player_id=? AND s.team_id=? AND g.game_date>?", (p["player_id"], p["team_id"],
                                                                                   params["start"])).fetchone()[0]
            if gp >= params["games"]:
                verdict = ("fulfilled", f"played {gp} NHL games")
            elif day > p["deadline"]:
                verdict = ("broken", f"played {gp} NHL games")
        elif p["ptype"] == "trade":
            if team_now is not None and team_now["team_id"] != p["team_id"]:
                verdict = ("fulfilled", "traded")
            elif day > p["deadline"]:
                verdict = ("broken", "not traded")
        if verdict:
            _resolve(conn, p, verdict[0], day, verdict[1])


def _resolve(conn, p, status, day, note):
    conn.execute("UPDATE promises SET status=?, resolved_on=?, note=? WHERE promise_id=?",
                 (status, day, note, p["promise_id"]))
    pid, t = p["player_id"], p["team_id"]
    me = user_team(conn)
    name = player_name(conn, pid)
    if status == "fulfilled":
        conn.execute("UPDATE morale SET trust_mgmt=MIN(100, trust_mgmt+8), role=MIN(100, role+6) WHERE player_id=?",
                     (pid,))
        if p["ptype"] == "trade":
            conn.execute("UPDATE morale SET trade_request=0, trust_mgmt=60, role=60, morale=62 WHERE player_id=?", (pid,))
        log_event(conn, pid, day, "trust_mgmt", 8 * 0.15 + 6 * 0.35, f"you kept your promise: {p['description']}")
        emit(conn, "PROMISE_FULFILLED", day, f"Promise to {name} kept: {p['description']} ({note})", team_id=t,
             player_id=pid, importance=p["importance"], promise_id=p["promise_id"])
    elif status == "broken":
        hit = 12 * p["importance"] / 2
        conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-?), role=MAX(0, role-6) WHERE player_id=?",
                     (hit, pid))
        log_event(conn, pid, day, "trust_mgmt", -(hit * 0.15 + 6 * 0.35), f"you broke your promise: {p['description']}")
        leader = conn.execute("SELECT 1 FROM leadership WHERE team_id=? AND player_id=?", (t, pid)).fetchone()
        tr = traits(conn, pid)
        influential = bool(leader) or tr["leadership"] >= 14 or player_value(conn, pid) >= 58
        if influential:          # teammates notice when a leader or star is let down
            conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-3) WHERE player_id IN (SELECT player_id FROM "
                         "players WHERE team_id=? AND player_id<>?)", (t, pid))
            conn.execute("UPDATE team_room SET cohesion=MAX(0, cohesion-3) WHERE team_id=?", (t,))
        emit(conn, "PROMISE_BROKEN", day, f"Promise to {name} broken: {p['description']} ({note})", team_id=t,
             player_id=pid, importance=p["importance"] + (1 if influential else 0), promise_id=p["promise_id"],
             influential=influential)
    else:
        emit(conn, "PROMISE_WITHDRAWN", day, f"Promise to {name} no longer applies ({note})", team_id=t, player_id=pid,
             promise_id=p["promise_id"])
    if t == me:
        add_message(conn, day, f"Promise {status}", f"{name}: {p['description']} - {note}.")


def room(conn, t):
    return conn.execute("SELECT * FROM team_room WHERE team_id=?", (t,)).fetchone()


def unhappy(conn, t, limit=6):
    return conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, m.* FROM morale m JOIN players p USING "
                        "(player_id) WHERE p.team_id=? AND p.status<>'retired' ORDER BY m.morale LIMIT ?",
                        (t, limit)).fetchall()


def explain(m):
    """The weakest components of a morale row, as words."""
    labels = {"role": "role/ice time", "team": "team results", "contract": "contract", "trust_mgmt": "trust in you",
              "trust_coach": "trust in the coach"}
    low = sorted(COMPONENTS, key=lambda k: m[k])[:2]
    return ", ".join(f"{labels[k]} {m[k]:.0f}" for k in low)


def fix_goalie_letters(conn, day):
    """Saves from before v29 could have a goalie wearing a letter. Take it off and let the room choose again."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='leadership'").fetchone():
        return []
    rows = conn.execute("SELECT l.team_id, l.player_id, l.role FROM leadership l JOIN players p USING (player_id) "
                        "WHERE p.position='G'").fetchall()
    teams = sorted({r[0] for r in rows})
    for t in teams:
        keep = [r[0] for r in conn.execute("SELECT l.player_id FROM leadership l JOIN players p USING (player_id) WHERE "
                                           "l.team_id=? AND p.position<>'G' ORDER BY l.role='C' DESC", (t,))]
        conn.execute("DELETE FROM leadership WHERE team_id=? AND player_id IN (SELECT player_id FROM players WHERE position='G')", (t,))
        if not conn.execute("SELECT 1 FROM leadership WHERE team_id=? AND role='C'", (t,)).fetchone():
            choose_leaders(conn, t, day)
        elif len(keep) < 3:                                  # fill the empty A from the room's choice
            on = datetime.date.fromisoformat(day)
            have = {r[0] for r in conn.execute("SELECT player_id FROM leadership WHERE team_id=?", (t,))}
            cands = conn.execute("SELECT p.player_id, p.birth_date, s.leadership, s.professionalism FROM players p JOIN personality s "
                                 "USING (player_id) WHERE p.team_id=? AND p.status IN ('active','injured') AND p.position<>'G'", (t,)).fetchall()
            cands = sorted([c for c in cands if c["player_id"] not in have],
                           key=lambda c: -(c["leadership"] * 2 + c["professionalism"] + min(10, max(0, on.year - int(c["birth_date"][:4]) - 22))))
            for c in cands[:3 - len(have)]:
                conn.execute("INSERT INTO leadership VALUES (?,?,?,?)", (t, c["player_id"], "A", day))
    return teams
