"""Media layer: game recaps, headlines, a social feed and power rankings, written from what the game recorded.

Read-only by design (docs/ARCHITECTURE_AUDIT.md section 3): everything here is computed from `league_events`,
`games`, `game_events` and `player_game_stats`; nothing writes game state. Wording is chosen deterministically
from the event id (or game id), so the same save always reads the same way.

Outlets and accounts are fictional:
  The Crease Report (league news), The Morning Skate (game recaps)
  @InsiderOnIce (trades and front-office news), @CapCrunchHQ (contracts and the cap), @PipelineScout (draft,
  prospects), and a fan account per club (@<ABBR>Faithful) whose mood follows the club's last ten games.
"""
from __future__ import annotations

import datetime
import json
import random

from .events import player_name, team_abbr
from .state import get_state, user_team

OUTLET_NEWS, OUTLET_RECAP = "The Crease Report", "The Morning Skate"
INSIDER, CAP, PIPE = "@InsiderOnIce", "@CapCrunchHQ", "@PipelineScout"


def _rng(*key):
    return random.Random("-".join(str(k) for k in key))


def _pick(rng, options):
    return options[rng.randrange(len(options))]


def _team(conn, tid):
    r = conn.execute("SELECT * FROM teams WHERE team_id=?", (tid,)).fetchone()
    return r


def _club(conn, tid):
    r = _team(conn, tid)
    return (r["nickname"] or r["name"]) if r else "FA"


def _surname(conn, pid):
    r = conn.execute("SELECT last_name FROM players WHERE player_id=?", (pid,)).fetchone()
    return r[0] if r else f"#{pid}"


def _money(v):
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v:,.0f}"


def _payload(e):
    try:
        return json.loads(e["payload"]) if e["payload"] else {}
    except (TypeError, ValueError):
        return {}


# ---------------------------------------------------------------- game recaps

def _game_events(conn, gid):
    return conn.execute("SELECT * FROM game_events WHERE game_id=? ORDER BY period, clock_sec, seq", (gid,)).fetchall()


def _clock(sec):
    return f"{sec // 60}:{sec % 60:02d}"


def _period_name(p, playoff=False):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(p, ("OT" if p == 4 else f"{p - 3}OT") if playoff else ("OT" if p == 4 else "SO"))


def recap(conn, gid):
    """Box score and story of one played game."""
    g = conn.execute("SELECT * FROM games WHERE game_id=?", (gid,)).fetchone()
    if g is None or not g["played"]:
        raise ValueError("That game has not been played.")
    home, away = g["home_team_id"], g["away_team_id"]
    po = g["game_type"] == "PO"
    evs = _game_events(conn, gid)
    periods = sorted({e["period"] for e in evs if e["event_type"] in ("goal", "shot")} | {1, 2, 3})
    if g["went_to_ot"] == 2:
        periods = [p for p in periods if p < 5]
    line = {t: {p: [0, 0] for p in periods} for t in (home, away)}    # goals, shots on goal
    goals, penalties, running = [], [], {home: 0, away: 0}
    leads = []                                                       # home lead after each goal
    for e in evs:
        t = e["team_id"]
        if e["event_type"] in ("goal", "shot") and e["period"] in line[t]:
            line[t][e["period"]][1] += 1
            if e["event_type"] == "goal":
                line[t][e["period"]][0] += 1
        if e["event_type"] == "goal":
            running[t] += 1
            det = e["detail"] or ""
            ast = [int(x) for x in det.split(";")[0][2:].split(",") if x] if det.startswith("A:") else []
            goals.append(dict(period=_period_name(e["period"], po), time=_clock(e["clock_sec"]), team=team_abbr(conn, t),
                              team_id=t, scorer=player_name(conn, e["player_id"]), scorer_id=e["player_id"],
                              assists=[dict(id=a, name=player_name(conn, a)) for a in ast], en="EN" in det,
                              score=f"{running[away]}-{running[home]}"))
            leads.append(running[home] - running[away])
        elif e["event_type"] == "penalty":
            penalties.append(dict(period=_period_name(e["period"], po), time=_clock(e["clock_sec"]),
                                  team=team_abbr(conn, t), player=player_name(conn, e["player_id"]),
                                  player_id=e["player_id"], detail=e["detail"] or "minor"))
    shootout = [dict(team=team_abbr(conn, e["team_id"]), shooter=player_name(conn, e["player_id"]),
                     scored=e["event_type"] == "so_goal") for e in evs if e["event_type"] in ("so_goal", "so_miss")]
    stats = conn.execute("SELECT s.*, p.position, p.first_name||' '||p.last_name name FROM player_game_stats s "
                         "JOIN players p USING (player_id) WHERE game_id=?", (gid,)).fetchall()
    stars = _three_stars(g, stats)
    hg, ag = g["home_goals"], g["away_goals"]
    win, lose = (home, away) if hg > ag else (away, home)
    sog = {t: sum(v[1] for v in line[t].values()) for t in line}
    story = _story(conn, g, goals, leads, stats, stars, sog, win, lose)
    return dict(game_id=gid, date=g["game_date"], playoff=po, home=team_abbr(conn, home), away=team_abbr(conn, away),
                home_id=home, away_id=away, home_name=_team(conn, home)["name"], away_name=_team(conn, away)["name"],
                home_goals=hg, away_goals=ag, ot={0: "", 1: "OT", 2: "SO"}.get(g["went_to_ot"], ""),
                periods=[_period_name(p, po) for p in periods],
                line={team_abbr(conn, t): [line[t][p] for p in periods] for t in (away, home)},
                shots=dict(home=sog[home], away=sog[away]), goals=goals, penalties=penalties, shootout=shootout,
                stars=stars, headline=story["headline"], lede=story["lede"], outlet=OUTLET_RECAP)


def _three_stars(g, stats):
    scored = []
    for s in stats:
        won = g["home_goals"] != g["away_goals"] and (s["team_id"] == g["home_team_id"]) == (g["home_goals"] > g["away_goals"])
        if s["position"] == "G":
            sa = s["shots_against"] or 0
            if sa < 10:
                continue
            ga = sa - (s["saves"] or 0)
            pts = (s["saves"] or 0) * 0.12 - ga * 0.6 + (1.0 if won else 0) + (2.0 if ga == 0 else 0)
            line = f"{s['saves']} saves on {sa} shots"
        else:
            pts = (s["goals"] or 0) * 3 + (s["assists"] or 0) * 1.6 + (s["shots"] or 0) * 0.15 + (0.4 if won else 0)
            if not (s["goals"] or s["assists"]):
                continue
            line = ", ".join(x for x in (f"{s['goals']} G" if s["goals"] else "", f"{s['assists']} A" if s["assists"]
                                         else "") if x)
        scored.append((pts, s["player_id"], s["name"], s["team_id"], line))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [dict(player_id=p, name=n, team_id=t, line=ln) for _, p, n, t, ln in scored[:3]]


def _story(conn, g, goals, leads, stats, stars, sog, win, lose):
    rng = _rng("recap", g["game_id"])
    if g["home_goals"] == g["away_goals"]:                 # a tie (eras without a shootout)
        H, A = _club(conn, g["home_team_id"]), _club(conn, g["away_team_id"])
        n = g["home_goals"]
        head = _pick(rng, [f"{A} and {H} settle for a {n}-{n} tie", f"No winner: {A}, {H} tie {n}-{n}",
                           f"Honours even as {A} and {H} draw {n}-{n}"])
        lede = (f"{_team(conn, g['away_team_id'])['name']} {n}, {_team(conn, g['home_team_id'])['name']} {n}"
                + (" after overtime" if g["went_to_ot"] else "") + f". Shots {sog[g['away_team_id']]}-"
                f"{sog[g['home_team_id']]}.")
        return dict(headline=head, lede=lede)
    W, L = _club(conn, win), _club(conn, lose)
    wg, lg = max(g["home_goals"], g["away_goals"]), min(g["home_goals"], g["away_goals"])
    score = f"{wg}-{lg}"
    hat = [s for s in stats if (s["goals"] or 0) >= 3]
    sign = 1 if win == g["home_team_id"] else -1
    deficit = -min([0] + [x * sign for x in leads])                  # biggest hole the winner climbed out of
    gw = None
    if goals:
        # the game-winner: the winning side's goal that put them one ahead of the loser's final total
        n = 0
        for gl in goals:
            if gl["team_id"] == win:
                n += 1
                if n == lg + 1:
                    gw = gl
                    break
    shutout_g = next((s for s in stats if s["position"] == "G" and s["team_id"] == win
                      and (s["shots_against"] or 0) > 0 and s["saves"] == s["shots_against"]), None)
    star = stars[0] if stars else None
    if hat:
        h = hat[0]
        head = _pick(rng, [f"{h['name'].split()[-1]} hat trick lifts {W} past {L}, {score}",
                           f"Hats fly as {h['name'].split()[-1]} scores three in {W} win",
                           f"{h['name']} nets three as {W} beat {L} {score}"])
    elif g["went_to_ot"] == 2:
        head = _pick(rng, [f"{W} edge {L} in a shootout", f"Shootout goes {W}'s way against {L}"])
    elif g["went_to_ot"] == 1 and gw:
        head = _pick(rng, [f"{gw['scorer'].split()[-1]} ends it in overtime as {W} top {L}",
                           f"{gw['scorer']} the overtime hero for {W}"])
    elif shutout_g:
        head = _pick(rng, [f"{shutout_g['name'].split()[-1]} blanks {L} in {score} {W} win",
                           f"{shutout_g['name']} perfect as {W} shut out {L}"])
    elif deficit >= 2:
        head = _pick(rng, [f"{W} rally from {deficit} down to beat {L} {score}",
                           f"Comeback: {W} erase a {deficit}-goal deficit against {L}"])
    elif wg - lg >= 4:
        head = _pick(rng, [f"{W} rout {L} {score}", f"{W} run {L} out of the building, {score}"])
    elif star and "G" in star["line"].split(", ")[0] and star["team_id"] == win:
        head = _pick(rng, [f"{star['name'].split()[-1]} leads {W} past {L} {score}",
                           f"{star['name']} ({star['line']}) powers {W}"])
    else:
        head = _pick(rng, [f"{W} beat {L} {score}", f"{W} hold off {L}, {score}", f"{W} take it from {L}, {score}"])
    lede = f"{_team(conn, win)['name']} {wg}, {_team(conn, lose)['name']} {lg}"
    lede += {1: " (OT)", 2: " (SO)"}.get(g["went_to_ot"], "") + ". "
    if gw and g["went_to_ot"] != 2:
        when = "in overtime" if gw["period"].endswith("OT") else f"of the {gw['period']}"
        lede += f"{gw['scorer']} scored the winner at {gw['time']} {when}. "
    if sog[win] >= sog[lose]:
        lede += f"The {W} outshot the {L} {sog[win]}-{sog[lose]}."
    else:
        lede += f"The {W} won despite being outshot {sog[lose]}-{sog[win]}."
    return dict(headline=head, lede=lede)


def recent_recaps(conn, team=None, n=10):
    q = "SELECT game_id FROM games WHERE played=1"
    args = []
    if team is not None:
        q += " AND (home_team_id=? OR away_team_id=?)"
        args = [team, team]
    out = []
    for (gid,) in conn.execute(q + " ORDER BY game_date DESC, game_id DESC LIMIT ?", (*args, n)):
        r = recap(conn, gid)
        out.append(dict(game_id=gid, date=r["date"], headline=r["headline"], lede=r["lede"],
                        score=f"{r['away']} {r['away_goals']} @ {r['home']} {r['home_goals']} {r['ot']}".strip()))
    return out


# ---------------------------------------------------------------- headlines

NEWS_TYPES = ("TRADE_COMPLETED", "PLAYER_SIGNED", "PLAYER_INJURED", "PLAYER_RETIRED", "COACH_FIRED", "GM_FIRED",
              "GM_HIRED", "CHAMPIONSHIP", "RECORD_BROKEN", "TRADE_REQUEST", "ARBITRATION_AWARD", "PLAYER_RELEASED",
              "PLAYER_DRAFTED", "STAFF_HIRED", "RUMOUR", "AWARD_WON", "MEDIA_STORY", "CAPTAIN_CHANGED")


def _headline(conn, e):
    """(headline, body, tag) for one event, or None when it is not news."""
    rng = _rng("news", e["event_id"])
    t, pl = e["event_type"], _payload(e)
    who = player_name(conn, e["player_id"]) if e["player_id"] else ""
    club = _club(conn, e["team_id"]) if e["team_id"] else ""
    other = _club(conn, e["other_team_id"]) if e["other_team_id"] else ""
    s = e["summary"] or ""
    kind = pl.get("kind")
    if t == "TRADE_COMPLETED":
        if kind == "offer_sheet":
            if pl.get("matched"):
                return (_pick(rng, [f"{club} match offer sheet, keep {who}", f"{who} stays put: {club} match"]), s,
                        "offer sheet")
            return (_pick(rng, [f"{other or club} land {who} with an offer sheet", f"Offer sheet pries {who} loose"]),
                    s, "offer sheet")
        if kind == "rights_trade":
            return f"{club} move rights to unsigned pick {who}", s, "prospects"
        if pl.get("three_team"):                            # name all three clubs
            third = _club(conn, pl["third_team_id"]) if pl.get("third_team_id") else "a third club"
            return (_pick(rng, [f"Three-way deal: {club}, {other} and {third} swap pieces",
                                f"{club}, {other} and {third} pull off a three-team trade",
                                f"Three clubs, one trade: {club}, {other}, {third}"]), s, "trade")
        if e["importance"] < 3:
            return None
        return (_pick(rng, [f"Blockbuster: {s.split(' from ')[0]}" if " from " in s else s,
                            f"{club} make their move", f"{club} and {other} swing a deal"]), s, "trade")
    if t == "PLAYER_SIGNED":
        aav, yrs = pl.get("aav") or 0, pl.get("years") or 0
        if aav < 5_000_000 or "arbitration award" in s or "qualifying offer" in s:
            return None
        head = _pick(rng, [f"{who} cashes in: {yrs} year{'s' if yrs != 1 else ''}, {_money(aav)} a season",
                           f"{club} commit {_money(aav * yrs)} to {who}", f"{who} signs with {club}"])
        return head, s, "contract"
    if t == "PLAYER_INJURED":
        days = pl.get("days") or 0
        if days < 21:
            return None
        weeks = round(days / 7)
        return (_pick(rng, [f"{who} out about {weeks} weeks", f"Blow for {club}: {who} sidelined {weeks} weeks"]), s,
                "injury")
    if t == "PLAYER_RETIRED":
        gp = pl.get("nhl_games") or 0
        if gp < 400:
            return None
        return (_pick(rng, [f"{who} calls it a career after {gp} NHL games", f"End of the road for {who}"]), s,
                "retirement")
    if t == "COACH_FIRED":
        return _pick(rng, [f"{club} fire their head coach", f"Coaching change in {_team(conn, e['team_id'])['name']}"]), s, "front office"
    if t == "GM_FIRED":
        if pl.get("surprise"):
            return (_pick(rng, [f"Stunner: {club} fire their general manager", f"Out of nowhere, {club} make a change "
                                f"at the top"]), s + ". Nobody saw it coming: ownership had not said a word.", "front office")
        return f"{club} part ways with their general manager", s + (f" ({pl['why']})" if pl.get("why") else ""), \
            "front office"
    if t == "RUMOUR" and kind == "shopped":
        return (_pick(rng, [f"Trade talk: {who} on the block in {club}?", f"{club} quietly shopping {who}",
                            f"Rumour mill: {who}'s name is out there"]), s, "rumour")
    if t == "RUMOUR":
        return (_pick(rng, [f"Insider: trouble brewing in {_team(conn, e['team_id'])['name']}",
                            f"{club}: the owner's patience is wearing thin", f"Rumblings in {club}'s front office"]),
                s, "rumour")
    if t == "GM_HIRED":
        return f"{club} name a new general manager", s, "front office"
    if t == "CHAMPIONSHIP":
        return _pick(rng, [f"Champions! {s.replace(' win the championship', '')} lift the Cup",
                           f"{club or s.split(' win')[0]} are champions"]), s, "playoffs"
    if t == "RECORD_BROKEN":
        return f"Record: {s}", s, "record"
    if t == "TRADE_REQUEST":
        return _pick(rng, [f"{who} wants out of {club}", f"Trade request: {who} asks {club} to move him"]), s, "trade"
    if t == "ARBITRATION_AWARD":
        amt = pl.get("amount") or 0
        if amt < 6_000_000:
            return None
        return f"Arbitrator awards {who} {_money(amt)}", s + (f" (asked {_money(pl['ask'])}, offered {_money(pl['offer'])})"
                                                              if pl.get("ask") else ""), "contract"
    if t == "AWARD_WON":
        return s.split(" (")[0], s, "awards"
    if t == "MEDIA_STORY":
        return pl.get("headline") or s, pl.get("body") or s, pl.get("tag") or "media"
    if t == "CAPTAIN_CHANGED":
        return pl.get("headline") or s, pl.get("body") or s, "captaincy"
    if t == "PLAYER_RELEASED":
        if kind == "buyout":
            return f"{club} buy out {who}", s, "contract"
        if kind == "college_walk":
            return f"{who} spurns {club}, heads to free agency", s, "prospects"
        return None
    if t == "PLAYER_DRAFTED":
        n = pl.get("overall") or 99
        if n > 3:
            return None
        return (f"{club} take {who} {'first' if n == 1 else 'second' if n == 2 else 'third'} overall", s, "draft")
    return None


def headlines(conn, team=None, n=25):
    out = []
    q = f"SELECT * FROM league_events WHERE importance>=2 AND event_type IN ({','.join('?' * len(NEWS_TYPES))})"
    args = list(NEWS_TYPES)
    if team is not None:
        q += " AND (team_id=? OR other_team_id=?)"
        args += [team, team]
    for e in conn.execute(q + " ORDER BY event_date DESC, event_id DESC LIMIT ?", (*args, n * 4)):
        h = _headline(conn, e)
        if h is None:
            continue
        out.append(dict(event_id=e["event_id"], date=e["event_date"], headline=h[0], body=h[1], tag=h[2],
                        team=team_abbr(conn, e["team_id"]) if e["team_id"] else "", player_id=e["player_id"],
                        outlet=OUTLET_NEWS))
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- social feed

def last_ten(conn, team, before=None, sid=None):
    q = ("SELECT * FROM games WHERE played=1 AND game_type='RS' AND (home_team_id=? OR away_team_id=?)"
         + (" AND game_date<?" if before else "") + (f" AND season_id={int(sid)}" if sid else "")
         + " ORDER BY game_date DESC, game_id DESC LIMIT 10")
    w = l = o = 0
    streak, kind, open_ = 0, None, True
    for g in conn.execute(q, (team, team, before) if before else (team, team)):     # newest first
        home = g["home_team_id"] == team
        gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
        r = "W" if gf > ga else ("O" if g["went_to_ot"] or gf == ga else "L")     # ties count with OT losses
        w, l, o = w + (r == "W"), l + (r == "L"), o + (r == "O")
        if kind is None:
            kind, streak = r, 1
        elif open_ and r == kind:
            streak += 1
        else:
            open_ = False
    return dict(w=w, l=l, otl=o, streak=f"{kind}{streak}" if kind else "-")


def _fan(conn, team):
    return f"@{team_abbr(conn, team)}Faithful"


def social(conn, n=30):
    """Posts from the fictional accounts above, newest first."""
    me = user_team(conn)
    day = get_state(conn)[0]
    posts = []
    for e in conn.execute("SELECT * FROM league_events WHERE importance>=2 ORDER BY event_date DESC, event_id DESC "
                          "LIMIT 200"):
        p = _post(conn, e, me)
        if p:
            posts.append(p)
    # the user's fans on recent form, one post per game played (the last five)
    for g in conn.execute("SELECT * FROM games WHERE played=1 AND (home_team_id=? OR away_team_id=?) ORDER BY game_date "
                          "DESC, game_id DESC LIMIT 5", (me, me)):
        posts.append(_fan_game_post(conn, g, me))
    posts.sort(key=lambda p: (p["date"], p["order"]), reverse=True)
    del day
    return [dict(p, order=None) for p in posts[:n]]


def _post(conn, e, me):
    rng = _rng("post", e["event_id"])
    t, pl = e["event_type"], _payload(e)
    who = player_name(conn, e["player_id"]) if e["player_id"] else ""
    ab = team_abbr(conn, e["team_id"]) if e["team_id"] else ""
    s = e["summary"] or ""
    mine = me in (e["team_id"], e["other_team_id"])
    acct = text = None
    if pl.get("social"):                     # events that carry their own posts (captaincy, press conferences, leaks)
        first, *rest = pl["social"]
        return dict(date=e["event_date"], order=e["event_id"], account=first["account"], text=first["text"], team=ab,
                    mine=mine, player_id=e["player_id"], replies=[dict(account=r["account"], text=r["text"]) for r in rest])
    if t == "TRADE_COMPLETED":
        if pl.get("kind") == "offer_sheet":
            acct, text = CAP, f"Offer sheet alert: {s.split(':')[0]}. " + ("Matched." if pl.get("matched") else
                                                                          "Not matched; picks change hands.")
        elif pl.get("kind") == "rights_trade":
            acct, text = PIPE, s + ". He was not going to sign there."
        else:
            acct = INSIDER
            text = _pick(rng, ["Done deal: ", "Trade: ", "Confirmed: "]) + s + "."
    elif t == "TRADE_REQUEST":
        acct, text = INSIDER, _pick(rng, [f"Hearing {who} has asked {ab} for a trade. Worth watching.",
                                          f"Sources: {who} wants a fresh start away from {ab}."])
    elif t == "PLAYER_SIGNED" and (pl.get("aav") or 0) >= 4_000_000:
        acct, text = CAP, f"{ab}: {who}, {pl.get('years')}x{_money(pl.get('aav'))}" + (
            " (arbitration)" if "arbitration" in s else "") + "."
    elif t == "PLAYER_RELEASED" and pl.get("kind") == "buyout":
        acct, text = CAP, s + "."
    elif t == "PLAYER_RELEASED" and pl.get("kind") == "college_walk":
        acct, text = PIPE, f"{who} will not sign with {ab} and heads to free agency."
    elif t == "PLAYER_DRAFTED" and (pl.get("overall") or 99) <= 10:
        acct, text = PIPE, f"#{pl['overall']}: {s.split(' select ')[0]} take {who}." if " select " in s else s
    elif t in ("COACH_FIRED", "GM_FIRED"):
        acct, text = INSIDER, s + ("." if not pl.get("surprise") else ". Did not see that one coming. Not a peep from "
                                                                      "ownership beforehand.")
    elif t == "RUMOUR":
        acct, text = INSIDER, s
    elif t == "PLAYER_INJURED" and (pl.get("days") or 0) >= 28:
        acct, text = INSIDER, f"{who} ({ab}) out about {round(pl['days'] / 7)} weeks."
    if acct is None:
        return None
    post = dict(date=e["event_date"], order=e["event_id"], account=acct, text=text, team=ab, mine=mine,
                player_id=e["player_id"], replies=[])
    if mine and t in ("TRADE_COMPLETED", "PLAYER_SIGNED", "PLAYER_RELEASED"):
        post["replies"].append(dict(account=_fan(conn, me), text=_fan_take(conn, e, rng, me)))
    return post


def _fan_take(conn, e, rng, me):
    """A fan's reaction to one of the user's moves, from the contract grade where there is one."""
    pid = e["player_id"]
    grade = None
    if pid and e["event_type"] == "PLAYER_SIGNED":
        try:
            from .valuation import evaluate_contract
            ev = evaluate_contract(conn, pid)
            grade = ev and ev["grade"]
        except Exception:
            grade = None
    if grade in ("A", "B"):
        return _pick(rng, ["Love this. Great value.", "Steal of a deal. Well done.", "GM earning his money today."])
    if grade in ("D", "F"):
        return _pick(rng, ["We are going to regret this one.", "That term... yikes.", "Who signed off on this?"])
    form = last_ten(conn, me)
    if form["w"] >= 6:
        return _pick(rng, ["Keep it rolling.", "In on this. We're for real."])
    if form["w"] <= 3:
        return _pick(rng, ["Rearranging deck chairs.", "Fine, but we need more than this."])
    return _pick(rng, ["We'll see.", "Interesting move.", "Not sure about this one."])


def _fan_game_post(conn, g, me):
    rng = _rng("fan", g["game_id"])
    home = g["home_team_id"] == me
    gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
    opp = team_abbr(conn, g["away_team_id"] if home else g["home_team_id"])
    form = last_ten(conn, me)
    if gf == ga:
        text = _pick(rng, [f"{gf}-{ga} tie with {opp}. A point's a point.", f"Kissed our sister: {gf}-{ga} vs {opp}."])
    elif gf > ga:
        text = _pick(rng, [f"W! {gf}-{ga} over {opp}.", f"Two points. {gf}-{ga} {opp}. Next.",
                           f"That's how you do it. {gf}-{ga}."])
    elif g["went_to_ot"]:
        text = _pick(rng, [f"Point's a point. {gf}-{ga} {opp} in {'OT' if g['went_to_ot'] == 1 else 'the shootout'}.",
                           "So close."])
    else:
        text = _pick(rng, [f"{gf}-{ga} loss to {opp}. Not good enough.", f"Ugh. {opp} {ga}, us {gf}.",
                           f"Embarrassing. {gf}-{ga}."] if ga - gf >= 3 else
                     [f"Tough one. {gf}-{ga} to {opp}.", f"Lost {gf}-{ga}. Regroup."])
    if form["l"] + form["otl"] >= 7:
        text += " " + _pick(rng, ["Something has to change.", "Time for a shake-up?", "This is a slump."])
    elif form["w"] >= 7:
        text += " " + _pick(rng, ["Best team in the league?", "This team is rolling."])
    return dict(date=g["game_date"], order=10 ** 9 + g["game_id"], account=_fan(conn, me), text=text,
                team=team_abbr(conn, me), mine=True, player_id=None, replies=[], game_id=g["game_id"])


# ---------------------------------------------------------------- power rankings

def _season_with_games(conn):
    """The current season, or the last one if this one has not started."""
    r = conn.execute("SELECT s.season_id FROM seasons s WHERE EXISTS (SELECT 1 FROM games g WHERE g.season_id="
                     "s.season_id AND g.played=1 AND g.game_type='RS') ORDER BY s.start_year DESC LIMIT 1").fetchone()
    return r[0] if r else conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]


def _ranking(conn, on, sid):
    teams = [r[0] for r in conn.execute("SELECT DISTINCT home_team_id FROM games WHERE season_id=?", (sid,))]
    rows = []
    for t in teams:
        gs = conn.execute("SELECT * FROM games WHERE season_id=? AND played=1 AND game_type='RS' AND game_date<? AND "
                          "(home_team_id=? OR away_team_id=?)", (sid, on, t, t)).fetchall()
        gp = len(gs)
        if gp == 0:
            rows.append((0.0, t, dict(gp=0, pts=0, diff=0)))
            continue
        pts = diff = 0
        for g in gs:
            home = g["home_team_id"] == t
            gf, ga = (g["home_goals"], g["away_goals"]) if home else (g["away_goals"], g["home_goals"])
            pts += 2 if gf > ga else 1 if g["went_to_ot"] or gf == ga else 0
            diff += gf - ga
        f = last_ten(conn, t, on, sid)
        score = 0.55 * pts / (2 * gp) + 0.25 * (0.5 + diff / gp / 4) + 0.20 * (f["w"] + 0.5 * f["otl"]) / max(
            1, f["w"] + f["l"] + f["otl"])
        rows.append((score, t, dict(gp=gp, pts=pts, diff=diff, form=f)))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return rows


def power_rankings(conn):
    """Ranked by points %, goal differential a game and the last ten; movement against a week before."""
    sid = _season_with_games(conn)
    day = get_state(conn)[0]
    last = conn.execute("SELECT MAX(game_date) FROM games WHERE season_id=? AND played=1 AND game_type='RS'",
                        (sid,)).fetchone()[0] or day
    day = min(day, last)
    now = _ranking(conn, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat(), sid)
    prev = _ranking(conn, (datetime.date.fromisoformat(day) - datetime.timedelta(days=6)).isoformat(), sid)
    # movement only once a week-old table means something (everyone 5+ games in)
    before = {t: i + 1 for i, (_, t, d) in enumerate(prev)} if prev and min(d["gp"] for _, _, d in prev) >= 5 else {}
    me = user_team(conn)
    out = []
    for i, (score, t, d) in enumerate(now):
        rank = i + 1
        rng = _rng("power", day, t)
        f = d.get("form") or dict(w=0, l=0, otl=0)
        move = before.get(t, rank) - rank
        if d["gp"] == 0:
            blurb = "No games yet."
        elif rank <= 3:
            blurb = _pick(rng, ["The team to beat.", "Everything is clicking.", "Contender, no question."])
        elif f["w"] >= 7:
            blurb = _pick(rng, [f"{f['w']} wins in ten. Hot.", "Surging."])
        elif f["l"] + f["otl"] >= 7:
            blurb = _pick(rng, ["In free fall.", "Searching for answers.", "Cold stretch."])
        elif move >= 4:
            blurb = "Climbing fast."
        elif move <= -4:
            blurb = "Sliding."
        elif d["diff"] > 15 and rank > 10:
            blurb = "Goal differential says they are better than the record."
        elif d["diff"] > 15:
            blurb = _pick(rng, ["Solid at both ends.", "Outscoring people night after night."])
        elif d["diff"] < -15:
            blurb = "Getting outscored badly."
        else:
            blurb = _pick(rng, ["In the mix.", "Treading water.", "Hard to read.", "Steady."])
        out.append(dict(rank=rank, move=move, team=team_abbr(conn, t), name=_team(conn, t)["name"], gp=d["gp"],
                        pts=d["pts"], diff=d["diff"], last10=f"{f['w']}-{f['l']}-{f['otl']}", blurb=blurb,
                        mine=t == me, score=round(score, 3)))
    return out
