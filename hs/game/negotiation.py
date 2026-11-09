"""Contract talks: an agent across the table instead of a price tag (docs/NEGOTIATION.md).

A negotiation is for one of your expiring players (an extension, in season or in the offseason before free agency)
or for a free agent. It wraps the existing signing rules: the deal it closes goes through hs.game.offseason.extend
or hs.game.roster.sign_free_agent, so nothing here can sign a player below what those accept.

The agent
  Every player is represented by a (fictional) agent with a style, fixed for the player:
    shark      opens 28% above his floor, gives up 25% of the gap a round, 3 rounds of patience
    pro        opens 16% above, gives 40%, 4 rounds
    friendly   opens 8% above, gives 55%, 5 rounds
  The player's personality moves it: ego and ambition raise the opening, patience adds a round, loyalty (to your
  club, if he trusts you) is a hometown discount.
What he wants
  Term: a preferred length by age and status (young RFAs a bridge or, for the best, long; 25-30 the maximum;
    31-33 three or four; 34+ one or two). Every year away from it costs 3.5% (he wants his term, or is paid not to
    get it).
  A clause (v39): veterans 27+ want trade protection, more of it the better and prouder they are: a modified
    no-trade list (level 1), a full no-trade clause (2) or a no-movement clause (3). Each level you grant up to what
    he wants takes 2.5% off; beyond it 1% a level; each level short of it costs 2%. A 10-team list in the last two
    years only counts as half a level.
  Pitches (v39): once a talk each, you can sell him on home (his country is your club's), on friends in the room
    (players he has played with, or countrymen) and on winning (your club's place). A pitch that is true and that he
    cares about takes 1-3% off; one that is not true costs patience or mood.
  Concessions (v39): an agent never drops more than 2.5% (hard-nosed), 3.5% or 5% (easy to deal with) of his
    demand in one round, so a deal does not collapse by millions in one call.
  Winning: an ambitious player (7+) charges a bottom-eight club 5% more and gives a top-eight club 3%.
  Trust: below 35 trust in you he wants 10% more (already in the floor in season); 65+ with loyalty 7+ gives 4%.
The floor is the least he will take for that term and clause; it is never below what the signing rules accept.
A round
  Offer >= his current ask for that term: agreed (the contract is signed now).
  Offer within 3% of his ask and at or above the floor: agreed ("let's get it done").
  Otherwise he counters: an offer under 80% of his floor is an insult (-2 patience, his mood sours, he does not move);
  under 92% costs a round and he moves half as far; anything closer costs a round and he gives his style's share of
  the gap. When patience runs out talks break off for 14 days (your own player loses 5 trust in you).
"""
from __future__ import annotations

import datetime
import json
import random

from . import contracts as K
from . import roster as R
from .state import get_state, user_team

STYLES = {"shark": dict(open=0.28, give=0.25, patience=3, label="hard-nosed"),
          "pro": dict(open=0.16, give=0.40, patience=4, label="businesslike"),
          "friendly": dict(open=0.08, give=0.55, patience=5, label="easy to deal with")}
TERM_COST, NTC_GIVE, NTC_REFUSE = 0.035, 0.04, 0.02
CLAUSE_LEVEL = {"none": 0.0, "mntc_late": 0.5, "mntc": 1.0, "ntc": 2.0, "nmc": 3.0}
CLAUSE_TEXT = {"none": "no trade protection", "mntc_late": "a 10-team no-trade list in the last two years",
               "mntc": "a 10-team no-trade list", "ntc": "a full no-trade clause", "nmc": "a no-movement clause"}
CLAUSE_GIVE, CLAUSE_EXTRA, CLAUSE_REFUSE = 0.025, 0.01, 0.02
MAX_STEP = {"shark": 0.025, "pro": 0.035, "friendly": 0.05}
PITCHES = ("hometown", "friends", "winning")
COOLDOWN_DAYS = 14

AGENT_FIRST = ["Marty", "Dana", "Glen", "Ray", "Sofia", "Pat", "Lou", "Eric", "Nadia", "Brent", "Celine", "Howard",
               "Ilya", "Rory", "Tess", "Vic", "Wes", "Joanne", "Ken", "Mika"]
AGENT_LAST = ["Kowalczyk", "Brennan", "Delacroix", "Hartigan", "Lindqvist", "Moreau", "Pellerin", "Quayle",
              "Ruskin", "Strand", "Thibault", "Vance", "Whitcombe", "Yeager", "Zabek", "Ostrander", "Carrow",
              "Fairbanks", "Granger", "Halvorsen"]
AGENCIES = ["Northstar Sports Group", "Bluewater Sports Management", "Crease & Co.", "Hat Trick Athletes", "Faceoff Partners",
            "Slapshot Representation", "Coldwater Sports", "Five Hole Agency", "Top Shelf Talent", "Neutral Zone Group"]


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS negotiations (player_id INTEGER PRIMARY KEY, kind TEXT, opened TEXT, "
                 "status TEXT, patience INTEGER, max_patience INTEGER, demand REAL, pref_years INTEGER, "
                 "wants_ntc INTEGER, mood REAL, rounds INTEGER, cooldown_until TEXT, log TEXT)")


def agent_of(pid):
    rng = random.Random(f"agent-{pid}")
    style = rng.choices(list(STYLES), weights=[3, 5, 3])[0]
    return dict(name=f"{rng.choice(AGENT_FIRST)} {rng.choice(AGENT_LAST)}", agency=rng.choice(AGENCIES), style=style,
                style_label=STYLES[style]["label"])


def _player(conn, pid):
    p = conn.execute("SELECT player_id, first_name, last_name, position, birth_date, team_id, status FROM players "
                     "WHERE player_id=?", (pid,)).fetchone()
    if p is None:
        raise R.RosterError("No such player.")
    return p


def _personality(conn, pid):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone():
        return {}
    r = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone()
    return dict(r) if r else {}


def _trust(conn, pid):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
        return None
    r = conn.execute("SELECT trust_mgmt FROM morale WHERE player_id=?", (pid,)).fetchone()
    return r[0] if r else None


def kind_of(conn, pid):
    p = _player(conn, pid)
    me = user_team(conn)
    if p["team_id"] == me:
        return "extend"
    if p["team_id"] is None and p["status"] == "active":
        return "sign"
    raise R.RosterError("You can only negotiate with your own expiring players and free agents.")


def _age(conn, birth):
    from .valuation import _age as va
    return va(birth, K.signing_year(conn))


def _max_term(conn, kind):
    cr = K.crules(conn)
    return cr["max_term_resign"] if kind == "extend" else cr["max_term_new"]


def preferred_term(conn, pid, kind):
    p = _player(conn, pid)
    age = _age(conn, p["birth_date"])
    mx = _max_term(conn, kind)
    status = K.rights_status(conn, pid, K.season_year(conn)) if kind == "extend" else "UFA"
    v = K.league_values(conn).value(pid)
    if status == "RFA" and age <= 24:
        return min(mx, 6 if v >= 54 else 2)
    if age <= 30:
        return mx
    if age <= 33:
        return min(mx, 4 if age <= 31 else 3)
    return min(mx, 2 if age <= 35 else 1)


def clause_factor(clause, wants):
    """Price factor for granting `clause` to a player who wants protection level `wants` (0-3)."""
    if clause is True:
        clause = "ntc"
    if clause in (False, None):
        clause = "none"
    lv = CLAUSE_LEVEL.get(clause, 0.0)
    w = float(wants or 0)
    return 1 - CLAUSE_GIVE * min(lv, w) - CLAUSE_EXTRA * max(0.0, lv - w) + CLAUSE_REFUSE * max(0.0, w - lv)


def wanted_level(conn, pid, kind, age):
    """How much protection he asks for: 0 none, 1 a list, 2 full no-trade, 3 no-movement."""
    if age < 27:
        return 0
    v = K.league_values(conn).value(pid)
    ego = (_personality(conn, pid).get("ego") or 10)
    if v >= 58 and ego >= 12:
        return 3
    return 2 if v >= 55 else 1


def floor(conn, pid, kind, years, ntc, wants_ntc):
    """The least he will take for this term and clause (never below what the signing rules accept).
    v39: `ntc` is a clause key (none, mntc_late, mntc, ntc, nmc; True means ntc), `wants_ntc` his level 0-3."""
    from . import offseason as O
    base = O.extension_floor(conn, pid, years) if kind == "extend" else K.asking(conn, pid, "UFA")
    pers = _personality(conn, pid)
    f = 1.0
    from .trades import standings_rank
    rank = standings_rank(conn).get(user_team(conn), 16)
    if (pers.get("ambition") or 0) >= 7:
        f *= 1.05 if rank > 24 else 0.97 if rank <= 8 else 1.0
    t = _trust(conn, pid)
    if kind == "extend" and t is not None and t >= 65 and (pers.get("loyalty") or 0) >= 7:
        f *= 0.96
    f *= clause_factor(ntc, wants_ntc)
    f *= _pitch_factor(conn, pid)
    from . import gm as GMx                               # your negotiation rating (phase A2)
    f *= 1 - 0.005 * (GMx.rating(conn, "negotiation") - 10)
    from . import hidden as HD                            # v35: greed
    f *= HD.greed_factor(HD.of(conn, pid)["greed"])
    # the signing rules accept 95% of base; stay above that whatever the discounts
    return max(int(base * 0.96), int(base * f)), base


def _term_factor(years, pref):
    return 1 + TERM_COST * abs(years - pref)


def _row(conn, pid):
    ensure_tables(conn)
    return conn.execute("SELECT * FROM negotiations WHERE player_id=?", (pid,)).fetchone()


def _save(conn, pid, **kw):
    cur = _row(conn, pid)
    d = dict(cur) if cur else dict(player_id=pid)
    d.update(kw)
    if isinstance(d.get("log"), list):
        d["log"] = json.dumps(d["log"])
    cols = ["player_id", "kind", "opened", "status", "patience", "max_patience", "demand", "pref_years", "wants_ntc",
            "mood", "rounds", "cooldown_until", "log"]
    conn.execute(f"INSERT OR REPLACE INTO negotiations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 [d.get(c) for c in cols])


def _money(v):
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v:,.0f}"


def _say(rng, options, **kw):
    return rng.choice(options).format(**kw)


def open_talks(conn, pid):
    """Start (or resume) talks. Returns the view."""
    kind = kind_of(conn, pid)
    day = get_state(conn)[0]
    cur = _row(conn, pid)
    if cur and cur["status"] == "broken" and cur["cooldown_until"] and day < cur["cooldown_until"]:
        raise R.RosterError(f"His agent is not taking your calls until {cur['cooldown_until']}.")
    if cur and cur["status"] == "open" and cur["kind"] == kind:
        return view(conn, pid)
    p = _player(conn, pid)
    ag = agent_of(pid)
    st = STYLES[ag["style"]]
    pers = _personality(conn, pid)
    pref = preferred_term(conn, pid, kind)
    age = _age(conn, p["birth_date"])
    wants_ntc = wanted_level(conn, pid, kind, age)
    _save(conn, pid, log=[])                      # clear any pitches from an earlier round of talks
    fl, base = floor(conn, pid, kind, pref, "none", wants_ntc)
    opening = st["open"] + 0.02 * max(0, (pers.get("ego") or 5) - 5) + 0.01 * max(0, (pers.get("ambition") or 5) - 6)
    patience = st["patience"] + (1 if (pers.get("patience") or 5) >= 7 else 0)
    rng = random.Random(f"talks-{pid}-{day}")
    name = f"{p['first_name']} {p['last_name']}"
    demand = fl * (1 + opening)
    opener = _say(rng, [
        "{agent} here, for {name}. We think {term} years at {ask} is fair for what he brings. Your move.",
        "Thanks for reaching out. {name} wants to be paid like the player he is: {ask} a year, {term} years.",
        "Let's not waste each other's time. {term} years, {ask} per. That's where we start.",
        "{name} has options. To keep this simple: {term} years at {ask}.",
    ], agent=ag["name"], name=name, term=pref, ask=_money(demand))
    log = [dict(who="agent", text=opener, aav=round(demand), years=pref, day=day)]
    if wants_ntc:
        want_key = {1: "mntc", 2: "ntc", 3: "nmc"}[int(wants_ntc)]
        log.append(dict(who="agent", text=f"He'll want {CLAUSE_TEXT[want_key]} in there too. He's earned some say in where "
                                          "he plays, and he'll take less to get it.", day=day))
    _save(conn, pid, kind=kind, opened=day, status="open", patience=patience, max_patience=patience, demand=demand,
          pref_years=pref, wants_ntc=wants_ntc, mood=60.0, rounds=0, cooldown_until=None, log=log)
    return view(conn, pid)


def view(conn, pid):
    r = _row(conn, pid)
    p = _player(conn, pid)
    ag = agent_of(pid)
    out = dict(player_id=pid, name=f"{p['first_name']} {p['last_name']}", position=p["position"],
               age=_age(conn, p["birth_date"]), agent=ag, open=False)
    try:
        kind = kind_of(conn, pid)
    except R.RosterError as e:
        out["blocked"] = str(e)
        r0 = _row(conn, pid)
        if r0 is not None:                                   # what was said last time (a deal just done, say)
            out.update(status=r0["status"], log=json.loads(r0["log"]) if r0["log"] else [])
        return out
    out["kind"] = kind
    out["max_term"] = _max_term(conn, kind)
    try:                                   # can he sign now? (the same checks the signing rules make)
        if kind == "extend":
            from . import offseason as O
            O.extension_floor(conn, pid, 1)
        elif K.season_state(conn) == "draft":
            raise R.RosterError("Free agents sign once the draft is over.")
    except R.RosterError as e:
        out["blocked"] = str(e)
        r0 = _row(conn, pid)
        if r0 is not None and r0["status"] != "open":
            out.update(status=r0["status"], log=json.loads(r0["log"]) if r0["log"] else [])
        return out
    pers = _personality(conn, pid)
    c = K.current_contract(conn, pid)
    out["current"] = dict(cap_hit=c["cap_hit"], ends=c["start_year"] + c["years"]) if c and kind == "extend" else None
    out["value"] = round(K.league_values(conn).value(pid), 1)
    try:
        from . import valuation as V
        out["fair"] = {y: V.fair_aav(conn, pid, y) for y in (1, 2, 3, 4, 5, 6, 7)[:out["max_term"]]}
    except Exception:
        out["fair"] = None
    if r is None or r["status"] != "open":
        out["status"] = r["status"] if r else None
        out["cooldown_until"] = r["cooldown_until"] if r else None
        out["log"] = json.loads(r["log"]) if r and r["log"] else []
        return out
    out.update(open=True, status="open", patience=r["patience"], max_patience=r["max_patience"], mood=round(r["mood"]),
               pref_years=r["pref_years"], wants_ntc=bool(r["wants_ntc"]), rounds=r["rounds"],
               log=json.loads(r["log"] or "[]"))
    w = r["wants_ntc"] or 0
    pf = _pitch_factor(conn, pid)
    out["asks"] = {y: round(r["demand"] * _term_factor(y, r["pref_years"]) * clause_factor("none", w) * pf)
                   for y in range(1, out["max_term"] + 1)}
    out["clause_asks"] = {c: {y: round(r["demand"] * _term_factor(y, r["pref_years"]) * clause_factor(c, w) * pf)
                              for y in range(1, out["max_term"] + 1)} for c in CLAUSE_LEVEL}
    out["clause_text"] = CLAUSE_TEXT
    from . import ledger as LG
    out["structures"] = {k: dict(discount=v, label={"flat": "Flat (the same every season)", "front": "Front-loaded",
                                                    "bonus": "Signing-bonus heavy"}[k]) for k, v in LG.TALKS_DISCOUNT.items()}
    out["wants_level"] = w
    if w:
        out["asks_ntc"] = out["clause_asks"]["ntc"]
    used = {e.get("pitch") for e in out["log"] if e.get("pitch")}
    out["pitches"] = [dict(key=k, label={"hometown": "Sell him on home", "friends": "Friends in the room",
                                         "winning": "A chance to win"}[k], used=k in used) for k in PITCHES]
    from .trades import standings_rank
    rank = standings_rank(conn).get(user_team(conn), 16)
    wants = [dict(k="term", text=f"{r['pref_years']} years" + (" (security)" if out["age"] >= 30 else " (a bridge to a bigger deal)" if r["pref_years"] <= 2 else ""))]
    if r["wants_ntc"]:
        wants.append(dict(k="ntc", text={1: "a no-trade list", 2: "a full no-trade clause", 3: "a no-movement clause"}
                          .get(int(r["wants_ntc"]), "trade protection")))
    if (pers.get("ambition") or 0) >= 7:
        wants.append(dict(k="win", text="to win" + (": your club is contending" if rank <= 8 else ": your club is near the bottom" if rank > 24 else "")))
    t = _trust(conn, pid)
    if t is not None and kind == "extend":
        wants.append(dict(k="trust", text=f"trust in you {round(t)}/100" + (" (he likes it here)" if t >= 65 else " (he is wary)" if t < 35 else "")))
    if (pers.get("loyalty") or 0) >= 7 and kind == "extend":
        wants.append(dict(k="loyal", text="loyal to the club"))
    if (pers.get("ego") or 0) >= 7:
        wants.append(dict(k="ego", text="to be paid like a star"))
    out["wants"] = wants
    out["personality"] = {k: pers.get(k) for k in ("ambition", "loyalty", "ego", "patience") if pers.get(k) is not None}
    return out


def offer(conn, pid, aav, years, ntc=False, structure="flat"):
    """One round. Returns (outcome, view): outcome 'agreed', 'counter' or 'broken'."""
    r = _row(conn, pid)
    if r is None or r["status"] != "open":
        open_talks(conn, pid)
        r = _row(conn, pid)
    kind = r["kind"]
    day = get_state(conn)[0]
    mx = _max_term(conn, kind)
    if not 1 <= years <= mx:
        raise R.RosterError(f"Term must be 1-{mx} years.")
    cr = K.crules(conn)
    if aav < cr["min_salary"]:
        raise R.RosterError(f"At least the league minimum ({_money(cr['min_salary'])}).")
    if cr["cap_ceiling"] and aav > cr["max_salary_pct"] * cr["cap_ceiling"]:
        raise R.RosterError(f"Above the maximum salary ({_money(cr['max_salary_pct'] * cr['cap_ceiling'])}).")
    p = _player(conn, pid)
    name = p["first_name"]
    ag = agent_of(pid)
    st = STYLES[ag["style"]]
    pref = r["pref_years"]
    wants_ntc = r["wants_ntc"] or 0
    clause = "ntc" if ntc is True else ("none" if not ntc else ntc)
    if clause not in CLAUSE_LEVEL:
        raise R.RosterError(f"Clause must be one of {', '.join(CLAUSE_LEVEL)}.")
    if clause != "none" and _age(conn, _player(conn, pid)["birth_date"]) < 26:
        raise R.RosterError("Trade protection is for players old enough to have signed as unrestricted free agents.")
    from . import ledger as LG
    if structure not in LG.STRUCTURES:
        raise R.RosterError(f"Structure must be one of {', '.join(LG.STRUCTURES)}.")
    fl, base = floor(conn, pid, kind, years, clause, wants_ntc)
    sdisc = 1 - LG.TALKS_DISCOUNT[structure]                   # v41: money early is worth something to him
    fl = max(int(base * 0.96), int(fl * sdisc))
    ntc_adj = clause_factor(clause, wants_ntc) * _pitch_factor(conn, pid) * sdisc
    ask = r["demand"] * _term_factor(years, pref) * ntc_adj
    ask = max(ask, fl)
    log = json.loads(r["log"] or "[]")
    log.append(dict(who="you", text=f"{years} yr x {_money(aav)}" + (f" with {CLAUSE_TEXT[clause]}" if clause != "none" else "")
                    + {"flat": "", "front": ", front-loaded", "bonus": ", mostly signing bonus"}[structure],
                    aav=aav, years=years, ntc=clause, structure=structure, day=day))
    ntc = clause
    rng = random.Random(f"talks-{pid}-{day}-{r['rounds']}")
    patience, mood, demand = r["patience"], r["mood"], r["demand"]

    def close(text):
        log.append(dict(who="agent", text=text, day=day))
        final = int(round(aav / 5000) * 5000)
        log.append(dict(who="agent", day=day, text=f"So that's {years} year{'s' if years != 1 else ''} at {_money(final)} a season, "
                        f"{_money(final * years)} in all{', with ' + CLAUSE_TEXT[ntc] if ntc != 'none' else ''}. I'll have the paperwork with the league office today."))
        log.append(dict(who="player", day=day, text=rng.choice(
            ["I wanted to stay. Thanks for getting it done.", "This is home. Now let's go win something.",
             "Happy it's sorted. I can just play hockey now."] if kind == "extend" else
            ["Can't wait to get started. I picked this team for a reason.", "Thanks for believing in me. I'll be ready.",
             "Let's get to work."])))
        _sign(conn, pid, kind, int(round(aav / 5000) * 5000), years, ntc, day, structure)
        _save(conn, pid, status="agreed", log=log, rounds=r["rounds"] + 1)
        return "agreed", view(conn, pid)

    if aav >= ask:
        return close(_say(rng, ["Done. {name} is thrilled. Send the paperwork over.",
                                "We have a deal. Pleasure doing business.",
                                "That works. {name} will sign today."], name=name))
    if aav >= fl and aav >= 0.97 * ask:
        return close(_say(rng, ["Close enough. Let's get it done.",
                                "You're splitting hairs and so am I. Deal.",
                                "Fine. He wants this finished as much as you do."]))
    ratio = aav / fl
    if ratio < 0.80:
        patience -= 2
        mood -= 12
        text = _say(rng, ["With respect, that's not a serious offer. {name} is insulted.",
                          "I'm going to pretend I didn't hear that number.",
                          "If that's where you are, we're a long way apart. Call me when you mean it."], name=name)
    else:
        patience -= 1
        give = st["give"] * (0.5 if ratio < 0.92 else 1.0)
        target = fl * _term_factor(pref, pref)
        step = min((demand - target) * give, MAX_STEP[ag["style"]] * demand)    # v39 (#7): no collapse in one call
        demand = max(target, demand - step)
        mood -= 3 if ratio < 0.92 else 0
        new_ask = max(fl, demand * _term_factor(years, pref) * ntc_adj)
        if years != pref:
            term_note = f" At {years} years it's {_money(new_ask)}; at {pref} it's {_money(demand)}."
        else:
            term_note = ""
        text = _say(rng, ["We can come down a little: {ask}.{note}",
                          "{name} wants to stay, but not at any price. {ask}.{note}",
                          "Meet me partway. {ask} and we're done.{note}",
                          "I've talked to {name}. The best we can do is {ask}.{note}"],
                    name=name, ask=_money(new_ask), note=term_note)
        if wants_ntc and CLAUSE_LEVEL[ntc] < wants_ntc and rng.random() < 0.5:
            text += " And he still wants his trade protection."
    if patience <= 0:
        until = (datetime.date.fromisoformat(day) + datetime.timedelta(days=COOLDOWN_DAYS)).isoformat()
        log.append(dict(who="agent", text=_say(rng, ["We're done for now. Don't call me for a couple of weeks.",
                                                     "{name} is frustrated. We'll talk again when you're serious.",
                                                     "I'm going to take some other calls. We'll revisit."],
                                               name=name), day=day))
        if kind == "extend" and conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone():
            conn.execute("UPDATE morale SET trust_mgmt=MAX(0, trust_mgmt-5) WHERE player_id=?", (pid,))
        _save(conn, pid, status="broken", patience=0, mood=mood, demand=demand, rounds=r["rounds"] + 1,
              cooldown_until=until, log=log)
        if kind == "extend" and K.league_values(conn).value(pid) >= 55:
            from . import press
            press.schedule(conn, "contract", day, dict(player=pid))
        return "broken", view(conn, pid)
    log.append(dict(who="agent", text=text, aav=round(max(fl, demand * _term_factor(years, pref) * ntc_adj)),
                    years=years, day=day))
    if mood < 45 and rng.random() < 0.6:
        log.append(dict(who="player", text=rng.choice([f"{name}: I just want to know you actually want me here.",
                                                       f"{name}: Honestly, this is starting to feel personal.",
                                                       f"{name}: I've given this club everything. Show me something."]),
                        day=day))
    _save(conn, pid, patience=patience, mood=mood, demand=demand, rounds=r["rounds"] + 1, log=log)
    return "counter", view(conn, pid)


def walk(conn, pid):
    r = _row(conn, pid)
    if r is None or r["status"] != "open":
        raise R.RosterError("There are no open talks with him.")
    log = json.loads(r["log"] or "[]")
    day = get_state(conn)[0]
    log.append(dict(who="you", text="You ended the talks.", day=day))
    _save(conn, pid, status="ended", log=log)


def _sign(conn, pid, kind, aav, years, ntc, day, structure="flat"):
    from . import offseason as O
    from . import ledger as LG
    if kind == "extend":
        O.extend(conn, pid, aav, years, day)
    else:
        R.sign_free_agent(conn, user_team(conn), pid, day, aav=aav, years=years)
    LG.write(conn, K.last_contract(conn, pid)["contract_id"], structure)
    clause = "ntc" if ntc is True else (ntc or "none")
    if clause != "none":                               # v39: the clause is a real one (hs/game/clauses.py)
        from . import clauses as CL
        c = K.last_contract(conn, pid)
        end = c["start_year"] + c["years"] - 1
        kind_, size, start = {"mntc": ("MNTC", 10, c["start_year"]), "mntc_late": ("MNTC", 10, max(c["start_year"], end - 1)),
                              "ntc": ("NTC", 0, c["start_year"]), "nmc": ("NMC", 0, c["start_year"])}[clause]
        CL.set_clause(conn, pid, c["contract_id"], kind_, size, start, end)
    conn.commit()


# ---------------------------------------------------------------- v39 (#7): pitches
def _pitch_factor(conn, pid):
    r = _row(conn, pid)
    if not r or not r["log"]:
        return 1.0
    f = 1.0
    for e in json.loads(r["log"]):
        if e.get("pitch") and e.get("effect"):
            f *= 1 - e["effect"]
    return f


def _club_country(conn, t):
    r = conn.execute("SELECT value FROM pack_info WHERE key='club_country_' || ?", (t,)).fetchone()
    if r:
        return r[0]
    canada = {"MTL", "TOR", "OTT", "WPG", "CGY", "EDM", "VAN"}
    a = conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()
    return "CAN" if a and a[0] in canada else "USA"


def _friends(conn, pid, t):
    """Players on your club he has played with (same club and season) and countrymen."""
    mates = {r[0] for r in conn.execute(
        "SELECT DISTINCT b.player_id FROM skater_season_stats a JOIN skater_season_stats b ON a.team_id=b.team_id AND "
        "a.season_start_year=b.season_start_year AND a.league_id=b.league_id WHERE a.player_id=? AND b.player_id<>?",
        (pid, pid))} if conn.execute("SELECT 1 FROM sqlite_master WHERE name='skater_season_stats'").fetchone() else set()
    roster = [r[0] for r in conn.execute("SELECT player_id FROM players WHERE team_id=? AND status IN ('active','injured')", (t,))]
    nat = conn.execute("SELECT nationality FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    country = [x for x in roster if conn.execute("SELECT nationality FROM players WHERE player_id=?", (x,)).fetchone()[0] == nat
               and x != pid]
    return [x for x in roster if x in mates], country


def pitch(conn, pid, what):
    """Make one pitch (hometown, friends, winning) in open talks. Returns (text, view)."""
    from .events import player_name
    from .trades import standings_rank
    if what not in PITCHES:
        raise R.RosterError(f"Pitch one of: {', '.join(PITCHES)}.")
    r = _row(conn, pid)
    if r is None or r["status"] != "open":
        raise R.RosterError("There are no open talks with him.")
    log = json.loads(r["log"] or "[]")
    if any(e.get("pitch") == what for e in log):
        raise R.RosterError("You have made that pitch already.")
    me = user_team(conn)
    day = get_state(conn)[0]
    pers = _personality(conn, pid)
    p = _player(conn, pid)
    name = p["first_name"]
    rng = random.Random(f"pitch-{pid}-{day}-{what}")
    effect, patience, mood = 0.0, r["patience"], r["mood"]
    if what == "hometown":
        you = "You talk up the city, the rink, the life here."
        if (p["nationality"] or "") == _club_country(conn, me):
            effect = 0.025 if (pers.get("loyalty") or 0) >= 10 or _age(conn, p["birth_date"]) >= 30 else 0.012
            reply = rng.choice([f"{name} grew up dreaming about playing at home. That matters. I can move a little.",
                                f"Playing in front of family and friends: you've found the right button. We'll come down some."])
        else:
            patience -= 1
            reply = rng.choice([f"He's from {p['nationality'] or 'elsewhere'}. Home is not here. Let's talk numbers.",
                                "Nice city. That isn't going to pay his mortgage."])
    elif what == "friends":
        mates, country = _friends(conn, pid, me)
        you = "You remind him who is in the room."
        if mates or len(country) >= 3:
            effect = 0.03 if len(mates) >= 2 else 0.015
            who = ", ".join(player_name(conn, x) for x in (mates or country)[:2])
            reply = f"He's talked to {who}. They like it here. That helps."
        else:
            mood -= 3
            reply = "He doesn't really know anybody there."
    else:
        rank = standings_rank(conn)
        n = max(2, len(rank))
        S = 1 - (rank.get(me, n / 2) - 1) / (n - 1)
        you = "You tell him this club is built to win, now."
        if S >= 0.65:
            effect = 0.03 if (pers.get("ambition") or 0) >= 12 else 0.015
            reply = "He's watched you this year. He wants a ring. We can work with that."
        elif S >= 0.45:
            effect = 0.008
            reply = "You're in the mix. He's not sold, but he's listening."
        else:
            mood -= 6
            patience -= 1
            reply = "Have you looked at the standings? Don't insult him."
    log.append(dict(who="you", text=you, pitch=what, effect=effect, day=day))
    log.append(dict(who="agent", text=reply, day=day))
    _save(conn, pid, log=log, patience=max(1, patience), mood=mood)
    conn.commit()
    return reply, view(conn, pid)
