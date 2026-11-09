"""Your assistant GM (phase A2): reads the organisation every time you open the Assistant screen and says what needs
doing, with a button for each. It never acts on its own; "Do the routine ones" runs only the safe items (recalls to
fill a short position, sending down extras on an oversized roster, resetting lines that name players who are gone).

Each suggestion: dict(area, level 1 urgent / 2 soon / 3 worth a look, text, actions [dict(label, cmd | href, confirm)],
routine True when it is in the safe set).
"""
from __future__ import annotations

from . import contracts as K
from . import roster as R
from .events import player_name
from .state import get_state, user_team


def _has(conn, t):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone())


def suggestions(conn):
    me = user_team(conn)
    if me is None:
        return dict(items=[], routine=0)
    out = []
    add = lambda area, level, text, actions=(), routine=False: out.append(dict(area=area, level=level, text=text, actions=list(actions), routine=routine))
    phase = K.season_state(conn)
    in_season = phase in ("regular_season", "playoffs", "preseason")
    day = get_state(conn)[0]

    # ---- the roster: short at a position, too many players
    if in_season:
        for g in R.shortages(conn, me):
            own = R.prospects(conn, me, g)
            name = {"F": "forwards", "D": "defencemen", "G": "goalies"}[g]
            if own:
                v, pid, pos = own[0]
                add("Roster", 1, f"You are short of healthy {name}. {player_name(conn, pid)} ({pos}, value {v:.0f}) is the best in the system.",
                    [dict(label=f"Recall {player_name(conn, pid)}", cmd=f"recall {pid}")], routine=True)
            else:
                add("Roster", 1, f"You are short of healthy {name} and nobody in the system can come up.",
                    [dict(label="Free agents", href="#transactions/free")])
        _, mx = R.limits(conn)
        n = len(R.roster(conn, me))
        if isinstance(mx, int) and n > mx:
            low = R._lowest_healthy(conn, me)
            if low:
                add("Roster", 1, f"Your roster has {n} players, over the limit of {mx}. {player_name(conn, low[1])} is the weakest healthy player.",
                    [dict(label=f"Send down {player_name(conn, low[1])}", cmd=f"senddown {low[1]}")], routine=True)
        # promotions: a prospect clearly better than your weakest regular at his position
        for g in ("F", "D", "G"):
            own = R.prospects(conn, me, g)
            worst = R._lowest_healthy(conn, me, [g])
            if own and worst:
                v, pid, pos = own[0]
                if v >= worst[0] + R._promote_margin(conn, pid):
                    # v39 (#6): say whether he needs waivers, not "may"
                    from . import waivers as W
                    from . import clauses as CL
                    wn = player_name(conn, worst[1])
                    if CL.blocks_assignment(conn, worst[1]):
                        continue
                    if W.needs_waivers(conn, worst[1], day):
                        st = W.status(conn, worst[1])
                        why = f"{wn} is not waiver-exempt" + (f" ({st.get('why', '').replace('needs waivers: ', '')})" if st.get("why") else "") + \
                              ": he goes on waivers for a day and any club can claim him"
                    else:
                        why = f"{wn} is waiver-exempt" + (" (he cleared waivers recently)" if W.recently_cleared(conn, worst[1], day)
                                                          else "") + ": he goes straight to the minors"
                    add("Roster", 2, f"{player_name(conn, pid)} ({pos}, value {v:.0f}) is playing better than {wn} "
                                     f"(value {worst[0]:.0f}). Swap them? {why.split(':')[0]}.",
                        [dict(label="Swap", cmd=f"senddown {worst[1]}", then=f"recall {pid}", confirm=f"Send down {wn} and recall "
                              f"{player_name(conn, pid)}? {why}.")])
        # lines that name players who are gone or hurt
        try:
            from . import lineup as L
            lu = L.saved(conn, me)
            if lu:
                errs = L.validate(conn, me, lu)
                hurt = [pid for k in ("F", "D") for u in lu.get(k, []) for pid in u if pid and conn.execute(
                    "SELECT 1 FROM players WHERE player_id=? AND status='injured'", (pid,)).fetchone()]
                if errs or hurt:
                    add("Lines", 1, "Your lines name " + (f"{len(hurt)} injured player(s)" if hurt else "players who are no longer available")
                        + ". The engine fills the gaps, but your combinations are broken.",
                        [dict(label="Reset to automatic lines", cmd="lines auto"), dict(label="Edit lines", href="#lines")], routine=bool(errs))
        except Exception:
            pass

    # ---- the cap
    yr = K.signing_year(conn)
    try:
        room = K.cap_room(conn, me, yr)
        if room < 0:
            add("Cap", 1, f"You are {abs(room) / 1e6:.2f}M over the cap for {yr}-{(yr + 1) % 100:02d}. You cannot sign anyone until you clear room.",
                [dict(label="Contracts and cap", href="#contracts")])
    except Exception:
        pass

    # ---- the room
    if _has(conn, "leadership") and in_season and not conn.execute("SELECT 1 FROM leadership WHERE team_id=? AND role='C'", (me,)).fetchone():
        add("Room", 2, "The team has no captain.", [dict(label="Leadership group", href="#captaincy")])
    if _has(conn, "morale"):
        for r in conn.execute("SELECT m.player_id FROM morale m JOIN players p USING (player_id) WHERE p.team_id=? AND m.trade_request=1", (me,)):
            add("Room", 2, f"{player_name(conn, r[0])} has asked for a trade.", [dict(label="His profile", href=f"#player/{r[0]}"),
                                                                               dict(label="Talk to him", href=f"#player/{r[0]}/person")])
        low = conn.execute("SELECT m.player_id, m.morale FROM morale m JOIN players p USING (player_id) WHERE p.team_id=? AND "
                           "p.status IN ('active','injured') AND m.morale<30 ORDER BY m.morale LIMIT 3", (me,)).fetchall()
        for pid, mo in low:
            add("Room", 3, f"{player_name(conn, pid)} is unhappy (morale {mo:.0f}).", [dict(label="Morale report", href="#reports/morale")])

    # ---- staff
    if _has(conn, "staff"):
        from .staff import ROLES, ROLE_NAMES
        have = {}
        for r in conn.execute("SELECT role FROM staff WHERE team_id=?", (me,)):
            have[r[0]] = have.get(r[0], 0) + 1
        for role, n in ROLES:
            if have.get(role, 0) < n:
                add("Staff", 1 if role == "HC" else 3, f"You have {have.get(role, 0)} of {n} {ROLE_NAMES[role].lower()}{'s' if n > 1 else ''}.",
                    [dict(label="Staff market", href="#staff")])

    # ---- contracts and rights
    if _has(conn, "draft_rights"):
        for r in conn.execute("SELECT r.player_id, r.expires_year FROM draft_rights r WHERE r.team_id=? AND r.expires_year<=? AND "
                              "r.player_id NOT IN (SELECT player_id FROM contracts WHERE team_id=?)", (me, yr, me)):
            add("Prospects", 2, f"Your rights to {player_name(conn, r[0])} run out in {r[1]}: sign him or lose him.",
                [dict(label="Sign his ELC", cmd=f"elc {r[0]}", confirm=f"Sign {player_name(conn, r[0])} to his entry-level contract?"),
                 dict(label="Prospects", href="#prospects")])
    if phase == "regular_season":
        vals = {}
        for c in conn.execute("SELECT c.player_id, c.cap_hit FROM contracts c JOIN players p USING (player_id) WHERE c.team_id=? AND "
                              "c.start_year+c.years-1=? AND p.status IN ('active','injured','ltir') AND NOT EXISTS (SELECT 1 FROM "
                              "contracts x WHERE x.player_id=c.player_id AND x.start_year>c.start_year+c.years-1)",
                              (me, K.season_year(conn))):     # v39 (#27): not the ones already extended
            v = R.player_value(conn, c[0])
            if v >= 55:
                vals[c[0]] = v
        for pid, v in sorted(vals.items(), key=lambda x: -x[1])[:4]:
            add("Contracts", 3, f"{player_name(conn, pid)} (value {v:.0f}) is in the last year of his contract.",
                [dict(label="Talk extension", href=f"#player/{pid}/contract")])

    # ---- things waiting
    if _has(conn, "trade_offers"):
        n = conn.execute("SELECT COUNT(*) FROM trade_offers WHERE status='open' AND expires>=?", (day,)).fetchone()[0]
        if n:
            add("Trades", 2, f"{n} trade offer{'s' if n > 1 else ''} waiting for an answer.", [dict(label="Trade screen", href="#trade")])
    if _has(conn, "press_events"):
        n = conn.execute("SELECT COUNT(*) FROM press_events WHERE team_id=? AND status='pending' AND expires>=?", (me, day)).fetchone()[0]
        if n:
            add("Media", 2, f"{n} press conference{'s' if n > 1 else ''} waiting.", [dict(label="Press room", href="#press")])
    out.sort(key=lambda x: (x["level"], x["area"]))
    return dict(items=out, routine=sum(1 for x in out if x["routine"]))
