"""The plan of a played game for the 2D engine (v59; docs/RINK2D.md): what the match engine decided, laid out in time.

The match engine (hs/sim/engine.py) works in 30-second steps. For each step it picks a unit for each side, then draws
shot attempts, penalties and empty-net goals, and stores them as events with a second inside the step. It does not
store who was on the ice, and two events of one step may carry the same second (a rebound) or interleave in a way
no rink allows (a shot at each end one second apart). This module turns the stored events of one game into a plan the
on-ice engine (hs/sim/ice2d.py) can play:

  events     every event with a play time. Goals keep their official second. Saves, misses and blocks are moved by a
             few seconds where needed, so that a rebound follows its shot by about two seconds, two attempts by the
             same side are at least 3.5 s apart and attempts at opposite ends at least 7.5 s. Events of one step are
             grouped by side first (their order inside a step is not visible in any box score).
  penalties  the engine decides a penalty at the end of its step, stamps it with the step's first second, and the
             club is short from the next step. The plan whistles at the step boundary (so the box score's time can
             be up to 30 seconds before the whistle you see), a few seconds earlier when a goal follows at once.
  strength   skaters a side for every step, mirroring the engine: two minutes (four steps), a power-play goal ends
             the oldest minor, at most two in the box, three skaters at least; goalies pulled in the third by the
             default rule (down one with 2:00 left, down two with 1:00), and always when an empty-net goal says so.
  units      who is on the ice in every step: the players an event names in the step (shooter, assists, blocker,
             penalised player) were on the ice together, so they are; the rest are filled from lines built from
             the game's ice time, choosing the line that fits the named players and is furthest behind its ice time.

Nothing here changes a result, and everything is derived from tables every save has (games, game_events,
player_game_stats, players, player_attributes), so games from any version of the save can be planned.
"""
from __future__ import annotations

import random

STEP = 30
GAP_REBOUND, GAP_SAME, GAP_OTHER, GAP_GOAL, GAP_PEN = 2.2, 3.5, 7.5, 6.0, 5.0
ATTEMPT = ("shot", "miss", "block", "goal")


def attack_dir(side, period):
    """+1 if this side shoots at the +x net in this period (the same rule as hs/game/replay.py)."""
    d = 1 if period in (1, 3) or period >= 4 else -1
    return d if side == 0 else -d


class Ev:
    __slots__ = ("i", "per", "clock", "type", "side", "pid", "opp", "xg", "detail", "t", "x", "y", "assists", "en",
                 "bx", "by", "mx", "my", "offset", "official", "rebound", "done", "so_round")

    def __init__(self, **k):
        self.assists, self.en, self.offset, self.rebound, self.done = [], False, False, False, False
        self.bx = self.by = self.mx = self.my = self.so_round = None
        for a, b in k.items():
            setattr(self, a, b)


def load_events(conn, gid, data):
    """The game's events as Ev objects with the spots hs/game/replay.build() gave them (data = that build)."""
    g = conn.execute("SELECT home_team_id, away_team_id FROM games WHERE game_id=?", (gid,)).fetchone()
    rows = conn.execute("SELECT * FROM game_events WHERE game_id=? ORDER BY period, clock_sec, seq", (gid,)).fetchall()
    out = []
    for i, (r, d) in enumerate(zip(rows, data["events"])):
        side = 0 if r["team_id"] == g[0] else 1
        e = Ev(i=i, per=r["period"], clock=r["clock_sec"], type=r["event_type"], side=side, pid=r["player_id"],
               opp=r["opp_player_id"], xg=r["xg"], detail=r["detail"] or "", x=d.get("x"), y=d.get("y"),
               t=None, official=None)
        if e.type in ("so_goal", "so_miss"):
            e.so_round = r["clock_sec"]
            out.append(e)
            continue
        e.official = e.t = float((e.per - 1) * 1200 + e.clock)
        if e.type == "goal":
            det = e.detail.split(";")[0]
            e.assists = [int(a) for a in det[2:].split(",") if a] if det.startswith("A:") else []
            e.en = "EN" in e.detail
        elif e.type == "block":
            e.bx, e.by = d.get("bx"), d.get("by")
        elif e.type == "miss":
            e.mx, e.my = d.get("mx"), d.get("my")
        elif e.type == "penalty":
            e.offset = "offsetting" in e.detail
            c = e.clock
            e.t = float((e.per - 1) * 1200 + (c - c % STEP + STEP))      # the whistle: the end of the engine's step
        out.append(e)
    return out


def _gap(a, b):
    if a.type == "goal":
        return GAP_GOAL
    if a.type == "penalty":
        return 0.0 if b.type == "penalty" and b.t == a.t else GAP_PEN
    if b.type == "penalty":
        return 3.0 if a.side == b.side else 1.6
    if a.side != b.side:
        return GAP_OTHER
    return GAP_REBOUND if b.rebound else GAP_SAME


def retime(events, period_len):
    """Give every in-play event a play time (see the module docstring). Works period by period."""
    live = [e for e in events if e.t is not None and e.type != "goalie"]
    pers = sorted({e.per for e in live})
    for per in pers:
        evs = sorted((e for e in live if e.per == per), key=lambda e: (e.t, e.i))    # a penalty sorts at its whistle
        base = (per - 1) * 1200
        # 1. inside a step, between the fixed events, group the movable attempts by side
        out, i = [], 0
        while i < len(evs):
            e = evs[i]
            if e.type in ("goal", "penalty"):
                out.append(e)
                i += 1
                continue
            j = i
            step = int(e.official - base) // STEP
            run = []
            while j < len(evs) and evs[j].type not in ("goal", "penalty") and int(evs[j].official - base) // STEP == step:
                run.append(evs[j])
                j += 1
            first = run[0].side
            # a goal by one side right after the run: that side's attempts come last (they lead to the goal)
            if j < len(evs) and evs[j].type == "goal" and int(evs[j].official - base) // STEP == step:
                first = 1 - evs[j].side
            elif out and out[-1].type in ATTEMPT and out[-1].side != first and any(r.side == out[-1].side for r in run):
                first = out[-1].side
            times, grouped = sorted(r.t for r in run), []
            for s in (first, 1 - first):
                same = [r for r in run if r.side == s]
                for k, r in enumerate(same):
                    r.rebound = k > 0 and r.official == same[k - 1].official and same[k - 1].type == "shot"
                grouped.extend(same)
            for r, v in zip(grouped, times):          # the regrouped attempts take the step's own seconds, in order
                r.t = v
            out.extend(grouped)
            i = j
        # a goal at the same second as the save before it by the same side is a rebound goal
        for k in range(1, len(out)):
            a, b = out[k - 1], out[k]
            if b.type == "goal" and a.type == "shot" and a.side == b.side and a.official == b.official:
                b.rebound = True
        evs = out
        lo, hi = base + 2.5, base + period_len - 0.4
        n = len(evs)
        for e in evs:
            if e.type == "penalty":                    # a penalty in the period's last step: the whistle beats the horn
                e.t = min(e.t, base + period_len - 2.0)
        t = [e.t for e in evs]
        fixed = [e.type in ("goal", "penalty") for e in evs]
        for k in range(n):
            if not fixed[k]:
                t[k] = min(hi, max(lo, t[k]))
        # 2. backward: pull the movable attempts earlier to make room before what follows them. A whistle for a penalty may
        #    come a few seconds early; a goal is only moved when two goals are closer than the ice allows (a second
        #    apart: the first comes earlier).
        for k in range(n - 2, -1, -1):
            cap = t[k + 1] - _gap(evs[k], evs[k + 1])
            if t[k] > cap and (not fixed[k] or evs[k].type == "penalty" or (evs[k].type == "goal" and evs[k + 1].type == "goal")):
                t[k] = cap
        # 3. forward: whatever is still too close (the period's first seconds) moves later, goals last of all
        if n and t[0] < lo:
            t[0] = lo
        for k in range(1, n):
            need = t[k - 1] + _gap(evs[k - 1], evs[k])
            if t[k] < need:
                t[k] = need
        for e, v in zip(evs, t):
            e.t = round(v, 2)
        order = {id(e): k for k, e in enumerate(evs)}
        evs.sort(key=lambda e: (e.t, order[id(e)]))
    events.sort(key=lambda e: (e.per, e.t if e.t is not None else 1e9, e.i))
    return events


# ---------------------------------------------------------------- strength and pulled goalies, step by step
def strength(events, periods, pull=(120, 60), ot_n=3, playoff=False):
    """{(period, step): dict(n=[home skaters, away skaters], box=[[pid...], [pid...]], pulled=[bool, bool])}.
    periods = [(period, length in seconds)]. Mirrors the engine's loop (hs/sim/engine.py)."""
    by = {}
    for e in events:
        if e.official is None:
            continue
        by.setdefault((e.per, int(e.official - (e.per - 1) * 1200) // STEP), []).append(e)
    for v in by.values():
        v.sort(key=lambda e: e.i)
    box = [[], []]                        # [pid, seconds left]
    score = [0, 0]
    out = {}
    for per, length in periods:
        ot = per >= 4 and not playoff
        if ot:
            box = [[], []]
        for step in range(length // STEP):
            n = [max(3, 5 - len(box[0])), max(3, 5 - len(box[1]))]
            if ot:
                n = [ot_n, ot_n]
            pulled = [False, False]
            if per == 3:
                left = 1200 - step * STEP
                for i in (0, 1):
                    diff = score[1 - i] - score[i]
                    pulled[i] = (diff == 1 and left <= pull[0]) or (diff == 2 and left <= pull[1])
            evs = by.get((per, step), [])
            for e in evs:
                if e.type == "goal" and e.en:
                    pulled[1 - e.side] = True
            out[(per, step)] = dict(n=n, box=[[b[0] for b in box[0]], [b[0] for b in box[1]]], pulled=pulled)
            for e in evs:
                if e.type == "goal":
                    score[e.side] += 1
                    i, j = e.side, 1 - e.side
                    if not e.en and n[i] > n[j] and box[j]:
                        box[j].pop(0)
            for i in (0, 1):
                for b in box[i]:
                    b[1] -= STEP
                box[i] = [b for b in box[i] if b[1] > 0]
            if not ot:
                for e in evs:
                    if e.type == "penalty":
                        box[e.side].append([e.pid, 120])
    return out


# ---------------------------------------------------------------- who is on the ice
ATTRS = ("speed", "acceleration", "agility", "passing", "puck_control", "checking", "hitting", "faceoffs", "shot_power")


def roster(conn, gid, team_id):
    """The players who dressed, most ice time first: [dict(pid, pos, grp, toi, name, num, hand, attrs...)]. Reads only
    the columns the save has (older saves have no jersey numbers and fewer attributes)."""
    pc = {r[1] for r in conn.execute("PRAGMA table_info(players)")}
    ac = {r[1] for r in conn.execute("PRAGMA table_info(player_attributes)")}
    cols = ["s.player_id pid", "p.position pos", "s.toi_sec toi", "p.first_name fn", "p.last_name ln",
            ("p.shoots" if "shoots" in pc else "NULL") + " hand", ("p.jersey_number" if "jersey_number" in pc else "NULL") + " num"]
    cols += [(f"a.{a}" if a in ac else "NULL") + f" {a}" for a in ATTRS]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM player_game_stats s JOIN players p USING (player_id) "
                        "LEFT JOIN player_attributes a USING (player_id) WHERE s.game_id=? AND s.team_id=? "
                        "ORDER BY s.toi_sec DESC, s.player_id", (gid, team_id)).fetchall()
    out = []
    for r in rows:
        d = dict(zip(["pid", "pos", "toi", "fn", "ln", "hand", "num"] + list(ATTRS), r))
        d["grp"] = "G" if d["pos"] == "G" else "D" if d["pos"] == "D" else "F"
        d["name"] = f"{(d.pop('fn') or '?')[:1]}. {d.pop('ln')}"
        out.append(d)
    return out


def _lines(ros):
    f = [p for p in ros if p["grp"] == "F"]
    d = [p for p in ros if p["grp"] == "D"]
    g = [p for p in ros if p["grp"] == "G"]
    lines = [f[i:i + 3] for i in range(0, len(f), 3)]
    pairs = [d[i:i + 2] for i in range(0, len(d), 2)]
    return f, d, g, [x for x in lines if x], [x for x in pairs if x]


def _slots(unit, info):
    """Order a unit for the formations: centre, left wing, right wing, left defence, right defence, extras."""
    fs = [p for p in unit if info[p]["grp"] == "F"]
    ds = [p for p in unit if info[p]["grp"] == "D"]
    c = next((p for p in fs if info[p]["pos"] == "C"), fs[0] if fs else None)
    rest = [p for p in fs if p != c]
    lw = next((p for p in rest if info[p]["pos"] == "LW"), None) or next((p for p in rest if info[p]["pos"] != "RW"), None) \
        or (rest[0] if rest else None)
    rest = [p for p in rest if p != lw]
    rw = rest[0] if rest else None
    extra = rest[1:]
    ld = next((p for p in ds if info[p]["hand"] == "L"), ds[0] if ds else None)
    dr = [p for p in ds if p != ld]
    rd = dr[0] if dr else None
    extra += dr[1:]
    names = ["C", "LW", "RW", "LD", "RD"]
    out = [(n, p) for n, p in zip(names, (c, lw, rw, ld, rd)) if p is not None]
    out += [(f"X{k}", p) for k, p in enumerate(extra)]
    return out


def units(events, st, periods, rosters, seed):
    """{(period, step): [home, away]} with each side dict(sk=[(slot, pid)...], g=pid or None, x=extra attacker pid or
    None). rosters = [home roster, away roster] from roster()."""
    rng = random.Random(f"units-{seed}")
    plen = dict(periods)
    named, prev = {}, None
    for e in events:
        if e.official is None or e.type == "goalie":
            continue
        tt = e.t - (e.per - 1) * 1200 - (1.0 if e.type == "penalty" else 0.6)      # the step the play happens in
        k = (e.per, min(max(0, int(tt // STEP)), plen.get(e.per, 1200) // STEP - 1))
        if e.rebound and prev is not None and prev[0].per == e.per and prev[0].side == e.side:
            k = prev[1]                                    # a rebound is the same shift as the shot before it
        prev = (e, k)
        a = named.setdefault(k, [set(), set()])
        if e.pid:
            a[e.side].add(e.pid)
        for x in e.assists:
            a[e.side].add(x)
        if e.type == "block" and e.opp:
            a[1 - e.side].add(e.opp)
    changes = {}                                              # goalie changes: {side: [(t, pid)]}
    for e in events:
        if e.type == "goalie":
            changes.setdefault(e.side, []).append((e.official, e.pid))
    out = {}
    state = []
    for side in (0, 1):
        ros = rosters[side]
        info = {p["pid"]: p for p in ros}
        f, d, g, lines, pairs = _lines(ros)
        fp, dp = [p["pid"] for p in f], [p["pid"] for p in d]
        backup = {pid for _, pid in changes.get(side, [])}
        starter = next((p["pid"] for p in g if p["pid"] not in backup), g[0]["pid"] if g else None)
        state.append(dict(info=info, fp=fp, dp=dp, lines=[[p["pid"] for p in x] for x in lines],
                          pairs=[[p["pid"] for p in x] for x in pairs], left={p["pid"]: p["toi"] or 0 for p in ros},
                          goalie=starter, last=(None, None), chg=sorted(changes.get(side, []))))
    for per, length in periods:
        for step in range(length // STEP):
            k = (per, step)
            s = st[k]
            row = []
            for side in (0, 1):
                S = state[side]
                info, left = S["info"], S["left"]
                n = s["n"][side]
                boxed = set(s["box"][side])
                req = {p for p in named.get(k, [set(), set()])[side] if p in info and info[p]["grp"] != "G" and p not in boxed}
                t0 = (per - 1) * 1200 + step * STEP
                while S["chg"] and S["chg"][0][0] < t0:
                    S["goalie"] = S["chg"].pop(0)[1]
                opp_n = s["n"][1 - side]
                fpool = [p for p in S["fp"] if p not in boxed]
                dpool = [p for p in S["dp"] if p not in boxed]

                def best(groups, last):
                    def sc(u):
                        return 3.0 * len(req & set(u)) + sum(left[p] for p in u) / (60.0 * max(1, len(u))) \
                            - (1.5 if tuple(u) == last and not (req & set(u)) else 0.0) + rng.random() * 0.3
                    groups = [[p for p in u if p not in boxed] for u in groups]
                    groups = [u for u in groups if u]
                    return list(max(groups, key=sc)) if groups else []
                if per >= 4 and n < 5 and opp_n == n:              # overtime: three or four a side
                    nf = 2
                    fw = best([fpool[i:i + nf] for i in range(0, min(len(fpool), 6), nf)], None)
                    de = best([dpool[i:i + n - nf] for i in range(0, min(len(dpool), 2 * (n - nf)), n - nf)], None)
                elif n > opp_n:                                    # power play: four forwards and a defenceman
                    fw = best([fpool[0:4], fpool[4:8]], None)
                    de = best([dpool[0:1], dpool[1:2]], None)
                elif n < opp_n:                                    # short-handed: two forwards (one at three), two defence
                    nf = max(1, n - 2)
                    fw = best([fpool[i:i + nf] for i in (4, 6, 0)], None)
                    de = best([dpool[0:2], dpool[2:4]], None)
                else:
                    nf = 3 if n >= 5 else 2
                    fw = best([ln[:nf] for ln in S["lines"]], S["last"][0])
                    de = best([pr[:n - nf] for pr in S["pairs"]], S["last"][1])
                    S["last"] = (tuple(fw), tuple(de))
                unit = fw + de
                for p in sorted(req - set(unit), key=lambda q: -left[q]):       # the named players are on the ice
                    grp = info[p]["grp"]
                    cand = [q for q in unit if q not in req and info[q]["grp"] == grp] or [q for q in unit if q not in req]
                    if cand:
                        unit[unit.index(min(cand, key=lambda q: left[q]))] = p
                    elif len(unit) < n:
                        unit.append(p)
                pool = [p for p in fpool + dpool if p not in unit]
                while len(unit) < n and pool:
                    unit.append(pool.pop(0))
                unit = unit[:max(n, len(req & set(unit)))]
                extra = None
                if s["pulled"][side]:
                    rest = [p for p in fpool if p not in unit]
                    extra = rest[0] if rest else None
                for p in unit:
                    left[p] -= STEP
                row.append(dict(sk=_slots(unit, info), g=None if s["pulled"][side] else S["goalie"], x=extra))
            out[k] = row
    return out
