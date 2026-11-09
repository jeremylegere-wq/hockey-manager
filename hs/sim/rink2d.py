"""The 2D game (defect 13): Jeremy's 2D ice hockey engine, ported headless and steered by the match engine's events.

The match engine (hs/sim/engine.py) decides each game: shots, saves, goals, blocks, misses and penalties, with who and
when. It does not move anyone. This module plays the game out on a 200 x 85 ft rink so that every recorded event
happens at its time, by its player, from its spot (hs/game/replay.py places the spots): the puck is carried up ice,
passed along open lanes, worked in the zone and delivered to the shooter, who shoots; goals go in, saves are held or
kick out, blocks stop at the blocker, misses go wide. The result is tracking (positions at 5 frames a second) that the
replay viewer draws. It never changes a result.

From the original engine (2D_ice_hockey_sim, pygame + numpy) this keeps: skating with acceleration, a top speed
from the player's skating ratings and a sprint; puck friction and board bounces; possession by stick reach; passing
lanes scored by looking ahead for interceptions; offensive and defensive coordinators that place each position
(points that pinch, a box on the penalty kill, a pressure range); the goalie playing the angle on an arc in front
of his net; faceoffs; line changes; the penalised player in the box. The original's bugs (docs/DEFECTS.md, item 13)
do not carry over: the carrier and the puck are tracked by identity, not by an index into the entity list; line
changes swap whole units by a schedule, not by list position; a penalised player leaves the ice (and the line
plan) for his time; faceoffs use the centres on the ice; and since outcomes come from the match engine, nothing
here decides a goal.

Lines are the players who played the game (their ice time orders them into four forward lines, three pairs and a
goalie). A shooter is always on the ice when he shoots: his unit is sent out in the 25 seconds before.
Deterministic from the game id. Plain Python, no numpy: about a second per game.
"""
from __future__ import annotations

import math
import random

DT = 0.2                  # seconds per step (5 frames a second are kept)
SETUP, SHOT_SPRINT = 6.0, 1.6   # v39: the shooter heads for his spot 6 s out, sprints only for the last 1.6 s
NET_X, HALF_L, HALF_W = 89.0, 100.0, 42.5
BLUE = 25.0
PASS_SPEED, SHOT_SPEED = 62.0, 95.0
REACH = 3.0
F_SHIFT, D_SHIFT = 42, 50
F_ORDER = [0, 1, 2, 0, 1, 3]          # forward lines by shift (the top lines play more)
D_ORDER = [0, 1, 0, 2]


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Skater:
    __slots__ = ("side", "slot", "x", "y", "vx", "vy", "tx", "ty", "top", "pid")

    def __init__(self, side, slot, x, y):
        self.side, self.slot, self.x, self.y = side, slot, x, y
        self.vx = self.vy = 0.0
        self.tx, self.ty = x, y
        self.top = 26.0
        self.pid = None

    def steer(self, dt, sprint=False):
        dx, dy = self.tx - self.x, self.ty - self.y
        d = math.hypot(dx, dy)
        top = self.top * (1.18 if sprint else 1.0)
        want = min(top, d * 2.2)                   # slow down when arriving (v38: later, so skaters do not crawl in)
        wx, wy = (dx / d * want, dy / d * want) if d > 0.01 else (0.0, 0.0)
        ax, ay = wx - self.vx, wy - self.vy
        a = math.hypot(ax, ay)
        acc = 30.0 * dt
        if a > acc:
            ax, ay = ax / a * acc, ay / a * acc
        self.vx += ax
        self.vy += ay
        self.x = _clamp(self.x + self.vx * dt, -HALF_L + 2, HALF_L - 2)
        self.y = _clamp(self.y + self.vy * dt, -HALF_W + 2, HALF_W - 2)


class Game2D:
    def __init__(self, data, units, ratings, seed):
        """data: hs.game.replay.build(); units[side] = dict(F=[[pid]*3]*4, D=[[pid]*2]*3, G=pid); ratings[pid] = top speed."""
        self.d, self.units, self.top = data, units, ratings
        self.rng = random.Random(seed)
        self.sk = {s: [Skater(s, i, 0.0, 0.0) for i in range(5)] for s in ("home", "away")}
        self.g = {s: Skater(s, 5, 0.0, 0.0) for s in ("home", "away")}
        for s in ("home", "away"):
            self.g[s].pid = units[s]["G"]
            self.g[s].top = 14.0
        self.px = self.py = 0.0
        self.pvx = self.pvy = 0.0
        self.carrier = None                # a Skater
        self.flight = None                 # (target skater or None, kind) while a pass or shot travels
        self.hold = 0.0                    # puck frozen (faceoff, covered) for this long
        self.box = {"home": [], "away": []}  # (until, pid)
        self.overrides = {"home": [], "away": []}   # (start, end, f_line, d_pair) to put a shooter on the ice
        self._pending, self._resolve_after = None, 0.0
        self._plan()

    # ---------------------------------------------------------------- who is on the ice
    def _unit_of(self, side, pid):
        u = self.units[side]
        for i, ln in enumerate(u["F"]):
            if pid in ln:
                return ("F", i)
        for i, pr in enumerate(u["D"]):
            if pid in pr:
                return ("D", i)
        return None

    def _plan(self):
        for e in self.d["events"]:
            if e.get("t") is None or not e.get("shooter_id"):
                continue
            side = e["team"]
            u = self._unit_of(side, e["shooter_id"])
            if u:
                self.overrides[side].append((e["t"] - 25, e["t"] + 4, u))

    def on_ice(self, side, t):
        u = self.units[side]
        f = F_ORDER[int(t // F_SHIFT) % len(F_ORDER)] % max(1, len(u["F"]))
        dp = D_ORDER[int(t // D_SHIFT) % len(D_ORDER)] % max(1, len(u["D"]))
        for a, b, (kind, i) in self.overrides[side]:
            if a <= t <= b:
                if kind == "F":
                    f = i
                else:
                    dp = i
        fw = list(u["F"][f]) if u["F"] else []
        dd = list(u["D"][dp]) if u["D"] else []
        out = (fw + [None] * 3)[:3] + (dd + [None] * 2)[:2]
        boxed = {pid for until, pid in self.box[side] if until > t}
        if boxed:                                   # short-handed: the boxed man (or the third forward) sits
            for k, pid in enumerate(out):
                if pid in boxed:
                    out[k] = None
            if all(p is not None for p in out):
                out[2] = None
        return out

    # ---------------------------------------------------------------- the plan of play
    def _dir(self, side, period):
        d = 1 if period in (1, 3) or period >= 4 else -1
        return d if side == "home" else -d

    def _attack_targets(self, side, d, phase, shooter=None, spot=None):
        """The attacking side's formation: breakout and neutral zone, then the zone, then the shot."""
        sk = self.sk[side]
        c = self.carrier
        px = self.px
        if phase == "zone":
            # v39 (#1): the zone formation cycles smoothly (low men circle, the points walk the line) instead of
            # standing on spots with a fresh random nudge every step, which looked like players doing nothing
            tt = getattr(self, "now", 0.0)
            base = [(d * 70, 0), (d * 72, 24), (d * 72, -24), (d * 58, 18), (d * 58, -18)]
            amp = [(7, 7), (8, 6), (8, 6), (3, 9), (3, 9)]
            base = [(x + d * ax * math.sin(0.55 * tt + 1.3 * i), y + ay * math.cos(0.42 * tt + 1.7 * i))
                    for i, ((x, y), (ax, ay)) in enumerate(zip(base, amp))]
        else:
            lead = _clamp(px + d * 18, -70, 70)
            base = [(lead, 0), (lead + d * 4, 22), (lead + d * 4, -22), (lead - d * 22, 14), (lead - d * 22, -14)]
        for i, s in enumerate(sk):
            if s.pid is None:
                continue
            s.tx, s.ty = base[i]
            if shooter is not None and s.pid == shooter and spot:
                s.tx, s.ty = spot                         # (v39: from up to SETUP seconds out, at his normal pace)
            elif c is s and phase != "shot":
                s.tx, s.ty = (s.x + d * 12, _clamp(s.y + self.rng.uniform(-8, 8), -36, 36)) if phase == "carry" else (s.tx, s.ty)

    def _defend_targets(self, side, d):
        """The defending side (attacking direction d is the OTHER side's): pressure on the puck, a shell in front."""
        sk = [s for s in self.sk[side] if s.pid is not None]
        own = -d * NET_X * -1  # the net they defend is the one the attackers shoot at: x = d * NET_X
        own = d * NET_X
        near = min(sk, key=lambda s: math.hypot(s.x - self.px, s.y - self.py)) if sk else None
        deep = abs(self.px - own) < 64
        for i, s in enumerate(self.sk[side]):
            if s.pid is None:
                continue
            if s is near:
                s.tx, s.ty = self.px - d * 2.5, self.py * 0.95
                continue
            if deep:
                spots = [(own - d * 18, 0), (own - d * 28, 18), (own - d * 28, -18), (own - d * 10, 9), (own - d * 10, -9)]
            else:
                mid = (self.px + own) / 2
                spots = [(mid, 0), (mid - d * 4, 16), (mid - d * 4, -16), (own - d * 22, 12), (own - d * 22, -12)]
            s.tx, s.ty = spots[i]

    def _goalies(self, period):
        for side in ("home", "away"):
            g = self.g[side]
            net = -self._dir(side, period) * NET_X       # a goalie guards the net the other side shoots at
            ax, ay = self.px - net, self.py
            dd = math.hypot(ax, ay) or 1
            depth = 4.0 * max(0.0, 1 - dd / 90)
            g.tx, g.ty = net + ax / dd * depth + (-math.copysign(1, net) * 1.5), ay / dd * depth
            if math.hypot(g.tx - g.x, g.ty - g.y) > 25:     # v38: a new period (ends switch) or the opening draw: he is
                g.x, g.y, g.vx, g.vy = g.tx, g.ty, 0.0, 0.0   # in his crease, not skating the length of the ice
            g.steer(DT)

    def _best_pass(self, side, d):
        """A look-ahead pass: the teammate furthest up ice whose lane no opponent reaches in time."""
        c = self.carrier
        opp = [s for s in self.sk["away" if side == "home" else "home"] if s.pid is not None]
        best, score = None, -1e9
        for s in self.sk[side]:
            if s is c or s.pid is None:
                continue
            dist = math.hypot(s.x - c.x, s.y - c.y)
            if dist < 8 or dist > 85:
                continue
            risk = 0
            for k in range(1, 6):
                f = k / 6
                lx, ly = c.x + (s.x - c.x) * f, c.y + (s.y - c.y) * f
                tt = dist * f / PASS_SPEED
                if any(math.hypot(o.x + o.vx * tt - lx, o.y + o.vy * tt - ly) < 4.5 for o in opp):
                    risk += 1
            sc = (s.x - c.x) * d / 40 - risk * 1.5
            if sc > score:
                best, score = s, sc
        return best if score > -0.5 else None

    # ---------------------------------------------------------------- the puck
    def _give(self, s):
        self.carrier, self.flight = s, None
        self.pvx = self.pvy = 0.0

    def _send(self, tx, ty, speed, target=None, kind="pass"):
        dx, dy = tx - self.px, ty - self.py
        dd = math.hypot(dx, dy) or 1
        self.pvx, self.pvy = dx / dd * speed, dy / dd * speed
        self.carrier, self.flight = None, (target, kind, tx, ty)

    def _puck_step(self):
        c = self.carrier
        if self.hold > 0:
            self.hold -= DT
            return
        if c is not None:
            sp = math.hypot(c.vx, c.vy) or 1
            self.px, self.py = c.x + c.vx / sp * 1.8, c.y + c.vy / sp * 1.8
            return
        self.px += self.pvx * DT
        self.py += self.pvy * DT
        f = 0.97 if self.flight else 0.9
        self.pvx *= f
        self.pvy *= f
        if abs(self.px) > HALF_L - 1:
            self.px = math.copysign(HALF_L - 1, self.px)
            self.pvx *= -0.6
        if abs(self.py) > HALF_W - 1:
            self.py = math.copysign(HALF_W - 1, self.py)
            self.pvy *= -0.6
        if self.flight:
            tgt, kind, tx, ty = self.flight
            if tgt is not None and math.hypot(tgt.x - self.px, tgt.y - self.py) < REACH:
                self._give(tgt)
            elif tgt is None and kind != "shot" and math.hypot(self.pvx, self.pvy) < 4:
                self.flight = None

    def _loose_pickup(self, side):
        if self.carrier is not None or self.flight or self.hold > 0:
            return
        near = min((s for s in self.sk[side] if s.pid is not None), key=lambda s: math.hypot(s.x - self.px, s.y - self.py), default=None)
        if near is None:
            return
        near.tx, near.ty = self.px, self.py
        if math.hypot(near.x - self.px, near.y - self.py) < REACH:
            self._give(near)

    def _faceoff(self, x, y, period, att_side):
        self.carrier, self.flight = None, None
        self.px, self.py, self.pvx, self.pvy = x, y, 0.0, 0.0
        self.hold = 1.2
        for side in ("home", "away"):
            d = self._dir(side, period)
            for i, s in enumerate(self.sk[side]):
                off = [(-2.5, 0), (-6, 18), (-6, -18), (-24, 12), (-24, -12)][i]
                s.x, s.y = x + d * off[0], _clamp(y + off[1], -40, 40)
                s.vx = s.vy = 0.0
                s.tx, s.ty = s.x, s.y
        win = [s for s in self.sk[att_side] if s.pid is not None]
        if win:
            self._win = win[0]

    # ---------------------------------------------------------------- the game
    def run(self):
        evs = [e for e in self.d["events"] if e.get("t") is not None]
        evs.sort(key=lambda e: e["t"])
        length = self.d["length"]
        frames, rosters, marks = [], [], []
        last_roster = None
        k, t, period = 0, 0.0, 1
        self._win = None
        self._faceoff(0, 0, 1, evs[0]["team"] if evs else "home")
        att = evs[0]["team"] if evs else "home"
        next_pass = 0.0
        step = 0
        while t < length:
            new_period = int(t // 1200) + 1 if t < 3600 else 4
            if new_period != period:
                period = new_period
                self._faceoff(0, 0, period, att)
            # whose puck it is: the side of the next shot-type event; long gaps start with the other side
            nxt = evs[k] if k < len(evs) else None
            while nxt and nxt["type"] == "penalty" and nxt["t"] <= t:
                pen = nxt
                side = pen["team"]
                mins = 5 if "major" in (pen.get("detail") or "") else 2
                if pen.get("shooter_id"):
                    self.box[side].append((pen["t"] + 60 * mins, pen["shooter_id"]))
                marks.append(dict(t=pen["t"], type="penalty", team=side, who=pen.get("shooter")))
                k += 1
                nxt = evs[k] if k < len(evs) else None
                self._faceoff(-self._dir(side, period) * 69, 22, period, "home" if side == "away" else "away")
            if nxt is not None:
                gap_start = evs[k - 1]["t"] if k else 0
                gap = nxt["t"] - gap_start
                flip = gap > 30 and t < gap_start + gap * 0.4
                want = ("away" if nxt["team"] == "home" else "home") if flip else nxt["team"]
                tau = nxt["t"] - t
            else:
                want, tau = att, 99
            if want != att and self.hold <= 0:
                att = want
                if self.carrier is not None and self.carrier.side != att:   # a turnover: poke it loose
                    self._send(self.px + self.rng.uniform(-8, 8), self.py + self.rng.uniform(-8, 8), 14, None, "loose")
            dfd = "away" if att == "home" else "home"
            pf = getattr(self, "_pending_faceoff", None)
            if pf:
                left, fx, fy = pf
                left -= DT
                if left <= 0:
                    self._pending_faceoff = None
                    self._faceoff(fx, fy, period, att)
                else:
                    self._pending_faceoff = (left, fx, fy)
            # rosters on the ice
            for side in ("home", "away"):
                ids = self.on_ice(side, t)
                for s, pid in zip(self.sk[side], ids):
                    if s.pid != pid:
                        if s is self.carrier and pid is None:
                            self._send(self.px, self.py, 0, None, "loose")
                        s.pid = pid
                        if pid is None:
                            s.x, s.y = 0.0, HALF_W - 1
                        s.top = self.top.get(pid, 26.0)
            roster = [s.pid for side in ("home", "away") for s in self.sk[side]] + [self.g["home"].pid, self.g["away"].pid]
            if roster != last_roster:
                rosters.append([round(t, 1), roster])
                last_roster = roster
            d = self._dir(att, period)
            # the phase of play
            if self.hold > 0 and self._win is not None and self.hold <= DT * 1.5:
                self._give(self._win)
                self._win = None
            ev = nxt if nxt and nxt["type"] in ("shot", "goal", "miss", "block") and nxt["team"] == att else None
            phase = "carry"
            if ev and tau <= SHOT_SPRINT:
                phase = "shot"
            elif self.px * d > BLUE - 4:
                phase = "zone"
            shooter = ev["shooter_id"] if ev else None
            spot = (ev["x"], ev["y"]) if ev else None
            self.now = t
            # v39 (#1): the shooter drifts to his spot from SETUP seconds out instead of sprinting the whole way in
            # the last 2.6 seconds (the burst after the lull)
            self._attack_targets(att, d, phase, shooter, spot if (ev and tau <= SETUP) else None)
            self._defend_targets(dfd, d)
            if ev and ev["type"] == "block" and tau <= 2.0:   # the blocker gets in the lane
                bl = min((s for s in self.sk[dfd] if s.pid is not None), key=lambda s: math.hypot(s.x - ev["bx"], s.y - ev["by"]), default=None)
                if bl:
                    bl.tx, bl.ty = ev["bx"], ev["by"]
            # the carrier moves the puck: passes on a rhythm, and to the shooter for the shot
            c = self.carrier
            if c is not None and c.side == att and self.hold <= 0:
                if phase == "shot" and shooter and c.pid != shooter:
                    tgt = next((s for s in self.sk[att] if s.pid == shooter), None)
                    if tgt:
                        self._send(tgt.x, tgt.y, PASS_SPEED, tgt)
                elif t >= next_pass and phase != "shot":
                    tgt = self._best_pass(att, d)
                    if tgt:
                        self._send(tgt.x + tgt.vx * 0.3, tgt.y + tgt.vy * 0.3, PASS_SPEED, tgt)
                    next_pass = t + self.rng.uniform(1.8, 3.6)
                elif phase == "carry":
                    c.tx, c.ty = _clamp(c.x + d * 14, -80, 80), _clamp(c.y + self.rng.uniform(-6, 6), -34, 34)
            elif c is not None and c.side != att and self.hold <= 0:
                self._send(c.x, c.y + self.rng.uniform(-6, 6), 10, None, "loose")
            self._loose_pickup(att)
            # the event itself
            if ev and tau <= DT / 2 + 1e-9:
                self._shoot(ev, d, period)
                marks.append(dict(t=ev["t"], type=ev["type"], team=att, who=ev.get("shooter"), x=ev["x"], y=ev["y"]))
                k += 1
            elif nxt and nxt["type"] in ("shot", "goal", "miss", "block") and tau <= DT / 2 + 1e-9:
                k += 1                                    # an event for the side without the puck (rare): skip it
            # move everyone
            for side in ("home", "away"):
                for s in self.sk[side]:
                    if s.pid is not None:
                        s.steer(DT, sprint=(s is self.carrier or phase == "shot"))
            self._goalies(period)
            self._puck_step()
            self._after(period)
            if step % 1 == 0:
                fr = [round(self.px), round(self.py)]
                for side in ("home", "away"):
                    for s in self.sk[side]:
                        fr += [round(s.x), round(s.y)] if s.pid is not None else [None, None]
                for side in ("home", "away"):
                    fr += [round(self.g[side].x), round(self.g[side].y)]
                fr.append(self._carrier_slot())
                frames.append(fr)
            t += DT
            step += 1
        return dict(dt=DT, frames=frames, rosters=rosters, marks=marks)

    def _carrier_slot(self):
        c = self.carrier
        if c is None:
            return -1
        return (0 if c.side == "home" else 5) + c.slot

    def _shoot(self, ev, d, period):
        net = ev["net"]
        shooter = next((s for s in self.sk[ev["team"]] if s.pid == ev.get("shooter_id")), None)
        if shooter is not None:                           # the shooter is on his spot with the puck
            shooter.x, shooter.y = ev["x"], ev["y"]
            self.px, self.py = ev["x"], ev["y"]
        self.carrier = None
        typ = ev["type"]
        if typ == "goal":
            self._send(net + math.copysign(2.5, net), self.rng.uniform(-2.5, 2.5), SHOT_SPEED, None, "shot")
            self.hold_after = ("faceoff", 0, 0)
            self.hold = 0
            self._pending = ("goal", net)
        elif typ == "shot":
            self._send(net - math.copysign(3, net), self.rng.uniform(-2, 2), SHOT_SPEED, None, "shot")
            self._pending = ("save", net)
        elif typ == "miss":
            self._send(ev.get("mx", net), ev.get("my", 10), SHOT_SPEED, None, "shot")
            self._pending = ("miss", net)
        elif typ == "block":
            self._send(ev["bx"], ev["by"], SHOT_SPEED * 0.8, None, "shot")
            self._pending = ("block", net)
        self._resolve_after = 0.6

    def _after(self, period):
        """What happens once the shot arrives: in the net, held or kicked out by the goalie, loose after a block or miss."""
        if not self._pending:
            return
        self._resolve_after -= DT
        if self._resolve_after > 0:
            return
        kind, net = self._pending
        self._pending = None
        sgn = math.copysign(1, net)
        if kind == "goal":
            self.px, self.py, self.pvx, self.pvy = net + sgn * 2.5, self.rng.uniform(-2, 2), 0.0, 0.0
            self.flight, self.hold = None, 0.0
            self._pending_faceoff = (2.6, 0, 0)
        elif kind == "save":
            if self.rng.random() < 0.5:                       # held: a whistle and a faceoff in that end
                self.px, self.py, self.pvx, self.pvy = net - sgn * 2, 0.0, 0.0, 0.0
                self.flight = None
                self._pending_faceoff = (1.4, net - sgn * 20, self.rng.choice((-22, 22)))
            else:                                             # a rebound
                a = self.rng.uniform(-1.1, 1.1)
                self._send(net - sgn * 12 * math.cos(a), 12 * math.sin(a) * 2, 24, None, "loose")
        else:
            self.flight = None

    def resolve(self):
        pass


def _units(conn, gid, team, side):
    rows = conn.execute("SELECT s.player_id, p.position, s.toi_sec FROM player_game_stats s JOIN players p USING (player_id) "
                        "WHERE s.game_id=? AND s.team_id=? ORDER BY s.toi_sec DESC", (gid, team)).fetchall()
    f = [r[0] for r in rows if r[1] in ("C", "LW", "RW")][:12]
    dmen = [r[0] for r in rows if r[1] == "D"][:6]
    g = next((r[0] for r in rows if r[1] == "G"), None)
    return dict(F=[f[i:i + 3] for i in range(0, len(f), 3)] or [[]], D=[dmen[i:i + 2] for i in range(0, len(dmen), 2)] or [[]], G=g)


def track(conn, gid):
    """Tracking for one played game: {dt, frames: [[puck x, y, 10 skaters x, y (home 5, away 5), 2 goalies x, y,
    carrier slot]], rosters: [[t, [player ids in the same order]]], players: {id: [name, pos]}, marks}."""
    from ..game import replay as RP
    data = RP.build(conn, gid)
    g = conn.execute("SELECT home_team_id, away_team_id, seed FROM games WHERE game_id=?", (gid,)).fetchone()
    units = {"home": _units(conn, gid, g[0], "home"), "away": _units(conn, gid, g[1], "away")}
    ids = [p for u in units.values() for ln in u["F"] + u["D"] for p in ln] + [u["G"] for u in units.values() if u["G"]]
    top, players = {}, {}
    for pid in ids:
        r = conn.execute("SELECT p.first_name, p.last_name, p.position, a.speed FROM players p LEFT JOIN player_attributes a USING (player_id) "
                         "WHERE p.player_id=?", (pid,)).fetchone()
        if r:
            top[pid] = 22.0 + 0.45 * (r[3] or 10)
            players[pid] = [f"{r[0][:1]}. {r[1]}", r[2]]
    out = Game2D(data, units, top, f"rink-{gid}-{g[2]}").run()
    out.update(players=players, home=data["home"], away=data["away"], final=data["final"], events=data["events"], length=data["length"])
    return out
