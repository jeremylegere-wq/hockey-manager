"""The 2D on-ice game, rebuilt (v59; docs/RINK2D.md): a played game shown as hockey, shift by shift.

The match engine (hs/sim/engine.py) decides every game: who shot, when, from what kind of chance, who scored, who
assisted, who blocked it, who took a penalty. It moves nobody. This module plays those results out on a 200 x 85 ft
rink. It never changes a result and it writes nothing to the save: the tracking is built from the game's stored
events when the game is opened, the same way every time (seeded by the game), so it works for every game of every
save, old or new.

How a game is played
  the plan     hs/sim/ice_plan.py lays the engine's events out in time, works out the strength (5v5, power plays,
               4v4, overtime, pulled goalies) and who was on the ice in every 30-second step.
  the script   between two events the puck has to get from where the last one left it to the next shooter's stick, at
               his spot, at his second. The director plays that as possessions: a side breaks out of its zone (up
               the wall, through the middle, D to D behind the net), crosses the neutral zone, carries the puck in or
               dumps it, cycles it (low to high, point to point, behind the net) and finds the shooter; a goal's
               last passes come from the players credited with the assists. When there is more time than one attack
               needs, the puck changes hands the way it does in a game: a dump-in, a poke check, a pass picked off,
               a penalty-killer's clear. Saves are frozen or kicked out, rebounds are fought for, blocked shots
               bounce off the blocker, misses rim around the boards.
  the shapes   players without the puck hold a system, not a spot: breakout lanes, three lanes through the neutral
               zone (nobody crosses the blue line before the puck), a low cycle with a net-front man and two
               points, a 1-3-1 on the power play; without the puck a 1-2-2 forecheck, gap control by the defence
               (skating backwards, facing the play), zone coverage with pressure on the puck, a box on the penalty
               kill. Goalies play the angle and the depth, hug the post when the puck is behind the net, drop for
               shots and cover the puck.
  the rest     faceoffs with both sides lined up, changes on the fly through the bench doors (and at whistles),
               the penalised player in the box and back out of it, the goalie to the bench for a sixth attacker,
               goal celebrations, the horn, three-on-three overtime and the shootout.

Skating is physical: every player accelerates, turns and stops within limits set by his speed, acceleration and
agility ratings, so faster players are faster on the screen. The puck is always carried, passed, shot or loose, and
is never moved by hand.

track(conn, game_id) returns the tracking the viewer (hs/ui/static/ice.js) draws; `check` in it counts anything the
director could not stage cleanly (a shooter who could not reach his spot in time), which the tests keep near zero.
"""
from __future__ import annotations

import math
import random

from . import ice_plan as IP

DT = 0.2
HL, HW, NET, BLUE, CORNER = 100.0, 42.5, 89.0, 25.0, 28.0
BENCH_Y, BOX_Y = 42.0, -42.0
BENCH_X, BOX_X = (-21.0, 21.0), (-8.0, 8.0)
REACH = 3.4
SK, GLIDE, PASS, SHOOT, CHECK, BLOCK, CELEB, GSET, GSAVE, GCOVER, DRAW, DOWN, BOXED, BENCH = range(14)


class Horn(Exception):
    pass


class GameOver(Exception):
    pass


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _inside(x, y, m=1.5):
    """The nearest point inside the boards (rounded corners), m feet off them."""
    x = _clamp(x, -HL + m, HL - m)
    y = _clamp(y, -HW + m, HW - m)
    ax, ay = abs(x), abs(y)
    cx, cy = HL - CORNER, HW - CORNER
    if ax > cx and ay > cy:
        dx, dy = ax - cx, ay - cy
        d = math.hypot(dx, dy)
        r = CORNER - m
        if d > r:
            ax, ay = cx + dx / d * r, cy + dy / d * r
            x, y = math.copysign(ax, x), math.copysign(ay, y)
    return x, y


class Pl:
    __slots__ = ("pid", "k", "side", "grp", "pos", "hand", "top", "acc", "x", "y", "vx", "vy", "face", "tx", "ty", "sprint",
                 "state", "st_until", "slot", "ovr", "key", "watch", "ph", "role", "hands")

    def __init__(self, pid, k, side, info):
        self.pid, self.k, self.side = pid, k, side
        self.grp, self.pos = info["grp"], info["pos"]
        self.hand = -1.0 if info.get("hand") == "L" else 1.0
        sp, ac = info.get("speed") or 10, info.get("acceleration") or 10
        self.top = 23.5 + 0.48 * sp if self.grp != "G" else 13.0
        self.acc = 21.0 + 0.9 * ac if self.grp != "G" else 34.0
        self.hands = info.get("puck_control") or 10
        self.x = self.y = self.vx = self.vy = self.face = 0.0
        self.tx = self.ty = 0.0
        self.sprint = 1.0
        self.state, self.st_until = SK, 0.0
        self.slot, self.ovr, self.key, self.watch = "", None, False, True
        self.ph = (pid * 0.6180339) % 6.283
        self.role = None

    def put(self, x, y, face=None):
        self.x, self.y, self.vx, self.vy = x, y, 0.0, 0.0
        self.tx, self.ty = x, y
        if face is not None:
            self.face = face


class Puck:
    __slots__ = ("x", "y", "vx", "vy", "h", "mode", "carrier", "to", "t1", "last", "tgt")

    def __init__(self):
        self.x = self.y = self.vx = self.vy = 0.0
        self.h = 0
        self.mode, self.carrier, self.to, self.t1, self.last, self.tgt = "dead", None, None, 0.0, None, None


class Game:
    def __init__(self, events, st, un, periods, rosters, seed, shootout=()):
        self.ev, self.st, self.un, self.periods = events, st, un, periods
        self.rng = random.Random(f"ice-{seed}")
        self.pl, self.players = {}, []
        for side in (0, 1):
            for info in rosters[side]:
                p = Pl(info["pid"], len(self.players), side, info)
                self.pl[p.pid] = p
                self.players.append(dict(id=p.pid, side=side, name=info["name"], pos=info["pos"], num=info.get("num"),
                                         hand=info.get("hand") or "R"))
        self.sk = [[], []]                  # skaters on the ice (not on their way off)
        self.gk = [None, None]
        self.off = []                       # skaters on their way to the bench: (player, give up at)
        self.box = [set(), set()]
        self.goalie_now = [None, None]      # set when the engine changes a goalie mid-step
        self.pk = Puck()
        self.t = self.pt = 0.0              # game clock (seconds from the opening draw); presentation time
        self.per, self.t_end = 1, 1200.0
        self.run, self.mode = False, "dead"
        self.poss, self.loose_for = 0, None
        self.cut = True
        self.frames, self.marks = [], []
        self.score = [0, 0]
        self.sog = [0, 0]
        self.sgn_mem = [1, 1]
        self.presser = [None, None]
        self.roles_at = [-9.0, -9.0]
        self.delay = [False, False]
        self.shootout = list(shootout)
        self.check = dict(offspot=0, snap=0, missing=0, late=0, rushed=0)
        self.ei = 0
        self.late = []
        self.held = [None, None]

    # ------------------------------------------------------------------ small helpers
    def dir(self, side):
        return IP.attack_dir(side, self.per)

    def rel(self, side, x, y):
        d = self.dir(side)
        return x * d, y * d

    def world(self, side, u, v):
        d = self.dir(side)
        return u * d, v * d

    def sgn(self, side, pv):
        if abs(pv) > 4:
            self.sgn_mem[side] = 1 if pv > 0 else -1
        return self.sgn_mem[side]

    def setst(self, p, state, dur):
        p.state, p.st_until = state, self.pt + dur

    def peek(self):
        while self.ei < len(self.ev) and (self.ev[self.ei].done or self.ev[self.ei].t is None):
            self.ei += 1
        if self.ei < len(self.ev) and self.ev[self.ei].per == self.per:
            return self.ev[self.ei]
        return None

    def after(self, e):
        """The next event still to be played after e, in this period."""
        for x in self.ev[self.ei:]:
            if x is not e and not x.done and x.t is not None and x.per == self.per:
                return x
        return None

    def mark(self, typ, side=None, **k):
        self.marks.append(dict(f=len(self.frames), t=round(self.t, 1), per=self.per, type=typ, side=side, **k))

    def stick(self, p):
        """Where the blade of his stick is: ahead of him, on his forehand."""
        c, s = math.cos(p.face), math.sin(p.face)
        return p.x + c * 2.7 - s * 1.1 * p.hand, p.y + s * 2.7 + c * 1.1 * p.hand

    def dist(self, a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    def dpk(self, p):
        return math.hypot(p.x - self.pk.x, p.y - self.pk.y)

    def key_step(self, t=None):
        t = self.t if t is None else t
        base = (self.per - 1) * 1200
        n = int(self.t_end - base) // IP.STEP
        return self.per, int(_clamp((t - base) // IP.STEP, 0, n - 1))

    # ------------------------------------------------------------------ who is on the ice
    def want(self, t=None):
        k = self.key_step(t)
        row = self.un.get(k)
        st = self.st.get(k)
        return row, st

    def door(self, side, i=0):
        return BENCH_X[side] + (i % 5 - 2) * 4.0, HW - 2.0

    def apply_units(self, instant, t=None):
        """Bring the skaters on the ice in line with the plan. instant: at a whistle (swap in place); otherwise on the
        fly, one for one through the bench door, never the puck carrier or a player the next play needs."""
        row, st = self.want(t)
        if row is None:
            return
        now_row, now_st = (row, st) if instant else self.want(self.t)      # strength, box and goalie change on time,
        for side in (0, 1):                                                 # not ahead of it
            was = set(self.box[side])
            self.box[side] = set(st["box"][side]) if instant else (was & set(now_st["box"][side]))
            des = [(slot, self.pl[pid]) for slot, pid in row[side]["sk"] if pid in self.pl and pid not in self.box[side]]
            if now_row[side]["x"] in self.pl and all(p.pid != now_row[side]["x"] for _, p in des):
                des.append(("X9", self.pl[now_row[side]["x"]]))
            if not instant:
                n_now = now_st["n"][side] + (1 if now_row[side]["x"] else 0)
                if len(des) < n_now - len(was - self.box[side]) and len(des) < len(self.sk[side]):
                    continue                                  # fewer skaters are coming: that waits for the whistle
                busy = self.busy()
                while len(des) > n_now:
                    spare = [q for q in des if q[1].pid not in busy] or des
                    des.remove(spare[-1])
                # nobody changes while his side is hemmed in its own end, unless the next play needs a man on the
                # bench, or the shift has run long
                pu = self.pk.x * self.dir(side)
                coming = {p.pid for _, p in des} - {p.pid for p in self.sk[side]}
                if pu < -BLUE and not (coming & self.busy(13.0)) and len(des) == len(self.sk[side]):
                    if self.held[side] is None:
                        self.held[side] = self.pt
                    if self.pt - self.held[side] < 14.0:
                        continue
                self.held[side] = None
            desset = {p.pid for _, p in des}
            cur = self.sk[side]
            leave = [p for p in cur if p.pid not in desset]
            enter = [p for _, p in des if p not in cur]
            if not instant:
                busy = self.busy()
                leave = [p for p in leave if p is not self.pk.carrier and p is not self.pk.to and p.pid not in busy and not p.key]
            for i, p in enumerate(leave):
                cur.remove(p)
                p.ovr, p.key = None, False
                if not instant and p.pid not in self.box[side]:
                    self.off.append((p, self.pt + 5.0))
            room = len(des) - len(cur)
            for i, p in enumerate(enter[:max(0, room)]):
                if not instant:
                    if any(q is p for q, _ in self.off):
                        self.off = [(q, u) for q, u in self.off if q is not p]
                    else:
                        bx, by = (BOX_X[side], -HW + 2.0) if (p.state == BOXED or p.pid in was) else self.door(side, i)
                        p.put(bx, by, -math.pi / 2 if by > 0 else math.pi / 2)
                p.state, p.ovr, p.key, p.role = SK, None, False, None
                cur.append(p)
            for slot, p in des:
                if p in cur:
                    p.slot = slot
            self.roles_at[side] = -9.0
            g = now_row[side]["g"]
            if g is not None and self.goalie_now[side] is not None:
                g = self.goalie_now[side]
            gp = self.pl.get(g) if g is not None else None
            if gp is not self.gk[side]:
                old = self.gk[side]
                if old is not None and not instant and gp is None:
                    self.off.append((old, self.pt + 7.0))
                self.gk[side] = gp
                if gp is not None:
                    nx = -self.dir(side) * (NET - 3.0)
                    if instant or old is not None:
                        gp.put(nx, 0.0, 0.0 if nx < 0 else math.pi)
                    else:
                        bx, by = self.door(side, 2)
                        gp.put(bx, by, -math.pi / 2)
                    gp.state = GSET

    def force_on(self, S, e):
        """The play needs S and he is still on the bench: he comes on now for someone the play does not name."""
        side = S.side
        if S.pid in self.box[side] or S.grp == "G":
            return False
        named = {e.pid, e.opp, *e.assists}
        row, _ = self.want(self.plan_time())
        keep = {pid for _, pid in row[side]["sk"]} if row else set()
        out = [p for p in self.sk[side] if p.pid not in named and p is not self.pk.carrier and p is not self.pk.to]
        if not out:
            return False
        out.sort(key=lambda p: (p.pid in keep, p.grp != S.grp))
        q = out[0]
        self.sk[side].remove(q)
        q.ovr, q.key = None, False
        self.off = [(a, u) for a, u in self.off if a is not S]
        self.off.append((q, self.pt + 5.0))
        S.put(*self.door(side, 1), -math.pi / 2)
        S.state, S.slot, S.role = SK, q.slot, None
        self.sk[side].append(S)
        self.roles_at[side] = -9.0
        return True

    def busy(self, window=7.0):
        """Players the plays of the next few seconds name: they stay on."""
        out = set()
        for e in self.ev[self.ei:self.ei + 6]:
            if e.done or e.t is None or e.per != self.per or e.t - self.t > window:
                continue
            out.add(e.pid)
            out.update(e.assists)
            if e.type == "block" and e.opp:
                out.add(e.opp)
        return out

    def plan_time(self):
        """The moment of the plan the benches work towards: three seconds ahead, or the next play if it is close (its
        shooter, passers and blocker have to be out there before it starts)."""
        t = self.t + 3.0
        e = self.peek()
        if e is not None and e.t - self.t < 11.0:
            t = max(t, e.t - (1.0 if e.type == "penalty" else 0.6))
        return min(t, self.t_end - 0.5)

    def needs_change(self):
        row, _ = self.want(self.plan_time())
        now, _ = self.want(self.t)
        if row is None or now is None:
            return False
        for side in (0, 1):
            des = {pid for _, pid in row[side]["sk"]} | ({now[side]["x"]} if now[side]["x"] else set())
            if des != {p.pid for p in self.sk[side]} or (now[side]["g"] is None) != (self.gk[side] is None):
                return True
        return False

    # ------------------------------------------------------------------ shapes: where everyone wants to be
    def shapes(self):
        pk = self.pk
        for side in (0, 1):
            sk = self.sk[side]
            if not sk:
                continue
            if self.mode != "play":                              # a whistle: only what the script asks for
                for p in sk:
                    if p.ovr is not None:
                        p.tx, p.ty, p.sprint = p.ovr
                continue
            has = self.poss == side if pk.mode != "loose" else self.loose_for == side
            tg = self.off_shape(side) if has else self.def_shape(side)
            a = 0.45 if has else 0.38
            for p in sk:
                if p.ovr is not None:
                    p.tx, p.ty, p.sprint = p.ovr
                    continue
                q = tg.get(p)
                if q is None:
                    continue
                x, y = self.world(side, q[0], q[1])
                x += 1.6 * math.sin(0.53 * self.pt + p.ph)
                y += 1.6 * math.cos(0.41 * self.pt + p.ph * 1.7)
                x, y = _inside(x, y, 2.5)
                p.tx += (x - p.tx) * a
                p.ty += (y - p.ty) * a
                p.sprint = q[2] if len(q) > 2 else 1.0
        for p, _ in self.off:
            bx, by = self.door(p.side, p.k)
            p.tx, p.ty, p.sprint = bx, by, 1.0

    def off_shape(self, side):
        pk, sk = self.pk, self.sk[side]
        pu, pv = self.rel(side, pk.x, pk.y)
        s = self.sgn(side, pv)
        c = pk.carrier if pk.carrier in sk else (pk.to if pk.to in sk else None)
        F = [p for p in sk if p.grp == "F"]
        D = [p for p in sk if p.grp == "D"]
        n, on = len(sk), len(self.sk[1 - side])
        out = {}
        lat = {"C": 0, "LW": 1, "RW": -1, "LD": 1, "RD": -1}
        if pu < -BLUE:                                            # the breakout
            for p in F:
                if p is c:
                    continue
                la = lat.get(p.slot, 1 if p.k % 2 else -1)
                if la == 0:
                    out[p] = (min(pu + 17, -27), s * 7)
                elif la == s:
                    out[p] = (max(min(pu + 22, -30), -62), s * 36.5)
                else:
                    out[p] = (min(pu + 40, -14), -s * 21)
            cd = c is not None and c.grp == "D"
            for i, p in enumerate(D):
                if p is c:
                    continue
                if cd:
                    out[p] = (max(min(pu - 1, -70), -85), -s * 11)
                else:
                    la = lat.get(p.slot, 1 - 2 * i)
                    out[p] = (max(pu - 9, -84), la * 13) if la == s else (-79, la * 9)
        elif pu < BLUE:                                           # through the neutral zone, three lanes
            cf = c is not None and c.grp == "F"
            for p in F:
                if p is c:
                    continue
                la = lat.get(p.slot, 1 if p.k % 2 else -1)
                ahead = 10 if cf else 24
                if la == 0:
                    out[p] = (min(pu + ahead - 3, BLUE - 2.5), s * 3 if cf else 0)
                else:
                    out[p] = (min(pu + ahead, BLUE - 2.0), la * 28)
            for i, p in enumerate(D):
                if p is c:
                    continue
                la = lat.get(p.slot, 1 - 2 * i)
                out[p] = (pu - (6 if (c is not None and c.grp == "D") else 21), la * 14)
        else:                                                     # in the zone
            if self.pt - self.roles_at[side] > 2.6 or any(p.role is None for p in sk):
                self.assign_oz(side, s, F, D, n, on)
            for p in sk:
                if p is not c and p.role is not None:
                    u, v = p.role
                    out[p] = (u, v * s)
        return out

    def assign_oz(self, side, s, F, D, n, on):
        self.roles_at[side] = self.pt
        if n >= 5 and n > on:                                     # the power play: a 1-3-1
            dspots = [(34.0, 0.0)]
            fspots = [(61.0, 31.0), (61.0, -31.0), (65.0, -3.0), (81.0, 8.0), (36.0, -24.0)]
            if len(D) > 1:
                dspots.append(fspots.pop(1 if s > 0 else 0))
        elif n >= 5:
            dspots = [(31.5, 21.0), (31.5, -15.0)]
            fspots = [(74.0, 30.0), (81.0, -8.0), (60.0, -9.0), (56.0, 18.0)]
        elif n == 4:
            dspots = [(32.0, 17.0), (32.0, -17.0)] if len(D) > 1 else [(33.0, 0.0)]
            fspots = [(73.0, 28.0), (81.0, -6.0), (56.0, -12.0)]
        else:
            dspots = [(37.0, 0.0)]
            fspots = [(66.0, 24.0), (74.0, -12.0), (50.0, -4.0)]
        for group, spots in ((D, dspots), (F, fspots)):
            spots = list(spots)
            if len(group) > len(spots):
                spots += fspots[len(group):] or [(50.0, 0.0)] * (len(group) - len(spots))
            free = list(spots[:max(len(group), 1)]) if len(spots) >= len(group) else spots
            for p in group:
                pu, pv = self.rel(side, p.x, p.y)
                if not free:
                    p.role = (50.0, 0.0)
                    continue
                b = min(free, key=lambda q: (q[0] - pu) ** 2 + (q[1] * s - pv) ** 2)
                free.remove(b)
                p.role = b

    def def_shape(self, side):
        pk, sk = self.pk, self.sk[side]
        pu, pv = self.rel(side, pk.x, pk.y)
        s = self.sgn(side, pv)
        F = [p for p in sk if p.grp == "F"]
        D = [p for p in sk if p.grp == "D"]
        n, on = len(sk), len(self.sk[1 - side])
        short = n < on
        out = {}
        # one man on the puck: the nearest forward up ice, the strong-side defenceman down low
        low = pu < -58
        pool = (D if low and D else F) or sk
        pr = self.presser[side]
        if pr not in pool or pr is None or self.rng.random() < 0.02:
            pr = min(pool, key=self.dpk)
        else:
            near = min(pool, key=self.dpk)
            if self.dpk(near) + 9 < self.dpk(pr):
                pr = near
        self.presser[side] = pr
        gap = 5.0 if not short else 9.0
        tu, tv = -89.0 - pu, -pv
        td = math.hypot(tu, tv) or 1.0
        on_puck = (pu + tu / td * gap, pv + tv / td * gap, 1.12)
        lat = {"LW": 1, "RW": -1, "LD": 1, "RD": -1}
        if pu < -BLUE:                                            # in our zone
            if n >= 5:
                ds = sorted(D, key=lambda p: -s * self.rel(side, p.x, p.y)[1])
                for i, p in enumerate(ds):
                    out[p] = (-77.0, s * 9.0) if i == 0 else (-80.0, -s * 7.0)
                fs = sorted(F, key=lambda p: (p.slot != "C", -s * lat.get(p.slot, 0)))
                spots = [(-71.0, s * 11.0) if low else (-66.0, s * 2.0), (-46.0, s * 25.0), (-55.0, -s * 6.0), (-60.0, s * 4.0)]
                for p, q in zip(fs, spots):
                    out[p] = q
                if pu > -50 and abs(pv) > 8 and len(fs) > 1:
                    out[fs[1]] = on_puck
                    pr = None
            elif n == 4:
                box = [(-75.0, s * 12.0), (-77.0, -s * 9.0), (-56.0, s * 14.0), (-58.0, -s * 8.0)]
                order = D + F if len(D) >= 2 else sk
                for p, q in zip(order, box):
                    out[p] = q
                hi = order[2] if len(order) > 2 else None
                if hi is not None and pu > -52:
                    out[hi] = (pu - 7.0, pv * 0.8)
                pr = None
            else:
                tri = [(-79.0, s * 7.0), (-78.0, -s * 7.0), (-61.0, s * 2.0)]
                for p, q in zip(D + F, tri):
                    out[p] = q
                pr = None if short else pr
        elif pu < BLUE:                                           # the neutral zone: gap up, forwards come back
            du = max(-64.0, pu - (30.0 if not short else 36.0))
            for i, p in enumerate(D):
                la = lat.get(p.slot, 1 - 2 * i)
                out[p] = (du, la * 12.0 + s * 4.0)
            others = [p for p in F if p is not pr]
            for p, q in zip(others, [(pu - 15.0, s * 21.0), (pu - 13.0, -s * 11.0), (pu - 20.0, 0.0)]):
                out[p] = q
        else:                                                     # they are in their zone: the forecheck
            for i, p in enumerate(D):
                la = lat.get(p.slot, 1 - 2 * i)
                out[p] = (max(-18.0, min(6.0, pu - 64.0)), la * 14.0)
            others = [p for p in F if p is not pr]
            if short:
                for p, q in zip(others, [(4.0, -s * 9.0), (-6.0, s * 9.0)]):
                    out[p] = q
                on_puck = (max(28.0, pu - 26.0), pv * 0.5, 1.0)
            else:
                for p, q in zip(others, [(max(30.0, pu - 19.0), s * 27.0), (max(26.0, pu - 34.0), -s * 5.0), (20.0, 0.0)]):
                    out[p] = q
        if pr is not None:
            out[pr] = on_puck
        return out

    def goalies(self):
        pk = self.pk
        for side in (0, 1):
            g = self.gk[side]
            if g is None:
                continue
            if g.ovr is not None:
                g.tx, g.ty, g.sprint = g.ovr
                continue
            d = self.dir(side)
            nx = -d * NET
            dx, dy = pk.x - nx, pk.y
            dist = math.hypot(dx, dy) or 1.0
            out = d * dx                                            # how far out from the goal line the puck is
            if out < 0.5:                                           # behind the net: on the post
                g.tx, g.ty = nx + d * 1.0, _clamp(pk.y, -1, 1) * 2.6 if abs(pk.y) > 0.5 else 0.0
            else:
                depth = 2.2 + 3.4 * _clamp((dist - 12.0) / 45.0, 0.0, 1.0)
                g.tx, g.ty = nx + dx / dist * depth, _clamp(dy / dist * depth, -3.6, 3.6)
            g.sprint = 1.0

    # ------------------------------------------------------------------ one step of the clock
    def move(self, p):
        dx, dy = p.tx - p.x, p.ty - p.y
        d = math.hypot(dx, dy)
        top = p.top * p.sprint
        want = min(top, d * 2.3) if d > 0.35 else 0.0
        if d > 0.01:
            ax, ay = dx / d * want - p.vx, dy / d * want - p.vy
        else:
            ax, ay = -p.vx, -p.vy
        a = math.hypot(ax, ay)
        lim = p.acc * DT * (1.5 if want < math.hypot(p.vx, p.vy) else 1.0)
        if a > lim:
            ax, ay = ax / a * lim, ay / a * lim
        p.vx += ax
        p.vy += ay
        p.x, p.y = _inside(p.x + p.vx * DT, p.y + p.vy * DT, 1.6 if p.state != BOXED else 0.0)
        sp = math.hypot(p.vx, p.vy)
        if p.grp == "G" or (p.watch and p is not self.pk.carrier and (sp < 11.0 or self.poss != p.side)):
            want_f = math.atan2(self.pk.y - p.y, self.pk.x - p.x)
        elif sp > 2.0:
            want_f = math.atan2(p.vy, p.vx)
        else:
            want_f = p.face
        df = (want_f - p.face + math.pi) % (2 * math.pi) - math.pi
        p.face += _clamp(df, -1.9, 1.9)
        if p.st_until and self.pt >= p.st_until and p.state not in (BOXED,):
            p.state, p.st_until = (GSET if p.grp == "G" else SK), 0.0

    def separate(self):
        """Bodies do not overlap: skaters keep about four and a half feet apart, and out of the goalies' creases."""
        ps = self.sk[0] + self.sk[1]
        R = 4.5
        for i in range(len(ps)):
            a = ps[i]
            for j in range(i + 1, len(ps)):
                b = ps[j]
                dx, dy = b.x - a.x, b.y - a.y
                if abs(dx) < R and abs(dy) < R:
                    d = math.hypot(dx, dy)
                    if d < R:
                        if d < 0.05:
                            dx, dy, d = 0.5, 0.3, 0.6
                        k = min(1.0, (R - d) * 0.35) / d
                        a.x -= dx * k
                        a.y -= dy * k
                        b.x += dx * k
                        b.y += dy * k
        for g in self.gk:
            if g is None:
                continue
            for p in ps:
                dx, dy = p.x - g.x, p.y - g.y
                if abs(dx) < 5.6 and abs(dy) < 5.6:
                    d = math.hypot(dx, dy) or 0.1
                    if d < 5.6:
                        p.x += dx / d * min(1.2, (5.6 - d) * 0.4)
                        p.y += dy / d * min(1.2, (5.6 - d) * 0.4)
        for p in ps:
            if abs(p.x) > NET - 1.0 and abs(p.x) < NET + 4.5 and abs(p.y) < 4.2:      # nobody stands in the net
                p.y += 1.2 if p.y >= 0 else -1.2

    def move_puck(self):
        pk = self.pk
        if pk.mode == "carry" and pk.carrier is not None:
            x, y = self.stick(pk.carrier)
            pk.x, pk.y = _inside(x, y, 0.6)
            pk.vx, pk.vy = pk.carrier.vx, pk.carrier.vy
            pk.h = 0
        elif pk.mode in ("pass", "shot"):
            left = pk.t1 - self.pt
            if pk.to is not None or pk.tgt is not None:               # it arrives where it is going, not a step past it
                if pk.to is None:
                    tx, ty = pk.tgt
                else:
                    tx, ty = self.stick(pk.to) if pk.mode == "pass" else (pk.to.x, pk.to.y)
                pk.vx, pk.vy = (tx - pk.x) / max(left, DT), (ty - pk.y) / max(left, DT)
                if pk.mode == "pass":
                    sp = math.hypot(pk.vx, pk.vy)
                    if sp > 98.0:                              # no pass is a slapshot: it arrives a moment later
                        pk.vx, pk.vy = pk.vx / sp * 98.0, pk.vy / sp * 98.0
                        pk.t1 += DT
            pk.x += pk.vx * DT
            pk.y += pk.vy * DT
        elif pk.mode == "loose":
            for _ in range(4):
                h = DT / 4
                pk.x += pk.vx * h
                pk.y += pk.vy * h
                sp = math.hypot(pk.vx, pk.vy)
                if sp > 0.01:
                    dec = min(sp, (7.0 + 0.10 * sp) * h)
                    pk.vx -= pk.vx / sp * dec
                    pk.vy -= pk.vy / sp * dec
                ix, iy = _inside(pk.x, pk.y, 0.5)
                if ix != pk.x or iy != pk.y:
                    nx, ny = pk.x - ix, pk.y - iy
                    nd = math.hypot(nx, ny) or 1.0
                    nx, ny = nx / nd, ny / nd
                    vn = pk.vx * nx + pk.vy * ny
                    if vn > 0:
                        pk.vx -= 1.55 * vn * nx
                        pk.vy -= 1.55 * vn * ny
                        pk.vx *= 0.93
                        pk.vy *= 0.93
                    pk.x, pk.y = ix, iy
                # the back of the net stops a puck coming from behind or the side
                for sx in (-1, 1):
                    if 0 < (pk.x * sx - NET) < 3.4 and abs(pk.y) < 3.1:
                        if abs(pk.y) > 2.4:
                            pk.vy = abs(pk.vy) * 0.4 * (1 if pk.y > 0 else -1)
                            pk.y = 3.15 if pk.y > 0 else -3.15
                        else:
                            pk.vx = abs(pk.vx) * 0.3 * sx
                            pk.x = sx * (NET + 3.45)
            pk.h = 0

    def tick(self):
        self.shapes()
        self.goalies()
        for side in (0, 1):
            for p in self.sk[side]:
                self.move(p)
            if self.gk[side] is not None:
                self.move(self.gk[side])
        keep = []
        for p, until in self.off:
            self.move(p)
            if self.pt < until and math.hypot(p.x - p.tx, p.y - p.ty) > 4.0:
                keep.append((p, until))
        self.off = keep
        if self.mode == "play":
            self.separate()
        self.move_puck()
        self.pt += DT
        if self.run:
            self.t += DT
        if self.mode == "play" and int(round(self.pt / DT)) % 3 == 0 and self.needs_change():
            self.apply_units(False, self.plan_time())
        self.record()

    def record(self):
        pk = self.pk
        flags = (1 if self.run else 0) | (2 if self.cut else 0) | (4 if self.delay[0] else 0) | (8 if self.delay[1] else 0)
        self.cut = False
        ents = []
        for side in (0, 1):
            for p in self.sk[side]:
                ents += [p.k, round(p.x * 10), round(p.y * 10), int(p.face * 11.459) % 72, p.state]
            g = self.gk[side]
            if g is not None:
                ents += [g.k, round(g.x * 10), round(g.y * 10), int(g.face * 11.459) % 72, g.state]
            for pid in self.box[side]:
                b = self.pl.get(pid)
                if b is not None and b not in self.sk[side]:
                    ents += [b.k, round((BOX_X[side] + (b.k % 3 - 1) * 2.2) * 10), round((-HW - 3.2) * 10), 18, BOXED]
        for p, _ in self.off:
            ents += [p.k, round(p.x * 10), round(p.y * 10), int(p.face * 11.459) % 72, p.state]
        c = pk.carrier.k if (pk.mode == "carry" and pk.carrier is not None) else -1
        m = {"carry": 0, "pass": 1, "shot": 2, "loose": 3, "dead": 4}[pk.mode]
        self.frames.append([round(self.t * 10), flags, round(pk.x * 10), round(pk.y * 10), m * 10 + pk.h, c] + ents)

    # ------------------------------------------------------------------ script primitives (each `yield` is one tick)
    def give(self, p):
        pk = self.pk
        pk.mode, pk.carrier, pk.to, pk.last = "carry", p, None, p
        self.poss, self.loose_for = p.side, None

    def wait(self, sec):
        end = self.pt + sec
        while self.pt < end - 1e-9:
            yield

    def until(self, t):
        while self.t < t - 1e-9:
            yield

    def pass_to(self, a, b, flight=None, speed=60.0):
        pk = self.pk
        d = self.dist(a, b)
        fl = _clamp(d / speed, 0.3, 2.4) if flight is None else max(0.2, flight)
        self.setst(a, PASS, 0.4)
        x, y = self.stick(a)
        pk.x, pk.y = x, y
        pk.mode, pk.carrier, pk.to, pk.t1, pk.last = "pass", None, b, self.pt + fl, a
        self.poss = a.side
        if b.ovr is None:
            mx, my = _inside(b.x + b.vx * fl * 0.6, b.y + b.vy * fl * 0.6, 2.5)
            b.ovr = (mx, my, 1.0)
            tmp = True
        else:
            tmp = False
        while self.pt < pk.t1 - 1e-9:
            yield
        if tmp:
            b.ovr = None
        self.give(b)

    def loose(self, x, y, speed, side=None):
        """Send the puck sliding towards (x, y); it slows on the ice and comes off the boards."""
        pk = self.pk
        dx, dy = x - pk.x, y - pk.y
        d = math.hypot(dx, dy) or 1.0
        pk.vx, pk.vy = dx / d * speed, dy / d * speed
        pk.mode, pk.carrier, pk.to = "loose", None, None
        self.loose_for = side

    def recover(self, side, who=None, limit=6.0):
        """A loose puck: the nearest man of `side` goes and gets it, with an opponent on his heels."""
        pk = self.pk
        self.loose_for = side
        cand = self.sk[side]
        if not cand:
            cand = [self.gk[side]] if self.gk[side] else self.sk[1 - side]
        ahead = lambda p: math.hypot(p.x - (pk.x + pk.vx * 0.7), p.y - (pk.y + pk.vy * 0.7))
        r = who if who is not None and who in cand else min(cand, key=ahead)
        r.key = True
        opp = min(self.sk[1 - side], key=ahead) if self.sk[1 - side] else None
        start = self.pt
        while True:
            lead = _clamp(self.dpk(r) / 30.0, 0.0, 0.9)
            r.ovr = (*_inside(pk.x + pk.vx * lead, pk.y + pk.vy * lead, 1.8), 1.15)
            if opp is not None and opp.ovr is None:
                pass
            if self.dpk(r) < REACH + 0.6 and math.hypot(pk.vx, pk.vy) < 60:
                break
            if self.pt - start > limit * 0.6:
                pk.vx *= 0.7
                pk.vy *= 0.7
            if self.pt - start > limit:
                self.check["snap"] += 1
                break
            yield
        r.ovr, r.key = None, False
        self.give(r)

    def lane(self, a, b, side, clear=3.6):
        """Is the pass from a to b clear of the other side's sticks?"""
        ax, ay, bx, by = a.x, a.y, b.x, b.y
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1:
            return True
        for o in self.sk[1 - side]:
            t = _clamp(((o.x - ax) * dx + (o.y - ay) * dy) / L2, 0.05, 0.95)
            if math.hypot(o.x - (ax + dx * t), o.y - (ay + dy * t)) < clear:
                return False
        return True

    def carry(self, c, u, v, dur, sprint=1.0, stop=None):
        """The carrier skates the puck towards (u, v) in his side's frame for up to `dur` seconds."""
        x, y = _inside(*self.world(c.side, u, v), 3.0)
        c.ovr = (x, y, sprint)
        end = self.pt + dur
        yield                                                    # always at least one step: no action is free
        while self.pt < end - 1e-9 and math.hypot(c.x - x, c.y - y) > 3.0:
            if stop is not None and stop():
                break
            yield
        c.ovr = None

    # ------------------------------------------------------------------ a side moves the puck
    def mates(self, c):
        return [p for p in self.sk[c.side] if p is not c]

    def move_up(self, side, hurry, room):
        """One action towards the other end: a breakout pass, a carry, a pass in the neutral zone."""
        pk, rng = self.pk, self.rng
        c = pk.carrier
        pu, pv = self.rel(side, c.x, c.y)
        s = self.sgn(side, pv)
        ms = self.mates(c)
        fw = [p for p in ms if p.grp == "F"]
        ahead = [p for p in fw if self.rel(side, p.x, p.y)[0] > pu + 8 and self.lane(c, p, side)]
        if pu < -BLUE:
            if not hurry and room > 5 and c.grp == "D" and rng.random() < 0.55:      # set up behind the net first
                yield from self.carry(c, _clamp(pu - 3, -93, -78), pv * 0.55, rng.uniform(0.6, 1.4), 0.75)
                partner = next((p for p in ms if p.grp == "D"), None)
                if partner is not None and rng.random() < 0.4 and self.lane(c, partner, side, 3.0):
                    yield from self.pass_to(c, partner, speed=48)
                    return
            if ahead and (hurry or rng.random() < 0.8):
                far = max(ahead, key=lambda p: self.rel(side, p.x, p.y)[0])
                tgt = far if hurry else rng.choice(ahead)
                yield from self.pass_to(c, tgt, speed=66 if hurry else 58)
            else:
                yield from self.carry(c, min(pu + 30, -10), _clamp(pv * 0.7 + s * 4, -30, 30), 2.2, 1.12 if hurry else 1.0,
                                      stop=lambda: self.rel(side, c.x, c.y)[0] > -BLUE + 4)
        else:
            lane_v = _clamp(pv + s * rng.uniform(4, 12), -33, 33) if abs(pv) < 18 else pv * 0.95
            wide = [p for p in ahead if abs(self.rel(side, p.x, p.y)[1]) > 12]
            if wide and pu < BLUE - 12 and rng.random() < (0.75 if hurry else 0.45):
                yield from self.pass_to(c, max(wide, key=lambda p: self.rel(side, p.x, p.y)[0]), speed=62)
            else:
                yield from self.carry(c, BLUE + 16, lane_v, 2.6, 1.14 if hurry else 1.04,
                                      stop=lambda: self.rel(side, c.x, c.y)[0] > BLUE + 5)

    def cycle(self, side, room):
        """One action in the zone: low to high, point to point, down the wall, behind the net, or hold it."""
        pk, rng = self.pk, self.rng
        c = pk.carrier
        pu, pv = self.rel(side, c.x, c.y)
        s = 1 if pv >= 0 else -1
        ms = self.mates(c)
        if room < 1.0:
            yield from self.carry(c, pu + rng.uniform(-3, 3), pv + rng.uniform(-3, 3), max(DT, room), 0.5)
            return
        opts = []
        for p in ms:
            qu, qv = self.rel(side, p.x, p.y)
            d = self.dist(c, p)
            if d < 12 or d > 78 or qu < BLUE + 2 or not self.lane(c, p, side):
                continue
            if 52 < qu < 86 and abs(qv) < 13:                 # the slot is for the pass that leads to the shot
                continue
            w = 1.0
            if pu > 58 and qu < 42:
                w = 2.4                                        # low to high
            elif pu < 45 and qu < 42:
                w = 2.0                                        # point to point
            elif pu < 45 and qu > 58:
                w = 1.8                                        # back down the wall
            elif d > 55:
                w = 0.3
            opts.append((w, p))
        r = rng.random()
        if opts and r < 0.62:
            tot = sum(w for w, _ in opts)
            x = rng.random() * tot
            for w, p in opts:
                x -= w
                if x <= 0:
                    break
            yield from self.carry(c, pu + rng.uniform(-4, 4), pv + rng.uniform(-4, 4), min(room - 0.9, rng.uniform(0.3, 1.0)), 0.6)
            yield from self.pass_to(c, p, speed=56)
        elif pu > 62 and r < 0.85 and room > 3.2:              # take it behind the net
            yield from self.carry(c, 95.0, s * 9.0, 1.6, 0.95)
            if self.pk.carrier is c:
                yield from self.carry(c, 84.0, -s * 22.0, 1.6, 0.95)
        elif pu < 42:                                          # walk the line
            yield from self.carry(c, _clamp(pu, 29, 36), _clamp(pv - s * rng.uniform(8, 16), -30, 30), min(room, 1.8), 0.8)
        else:
            yield from self.carry(c, _clamp(pu + rng.uniform(-9, 5), 30, 90), _clamp(pv + rng.uniform(-8, 8), -37, 37),
                                  min(room, 1.5), 0.8)

    def pass_time(self, a, b):
        """Seconds for a crisp pass from a to b, with a moment to handle it."""
        return _clamp(self.dist(a, b) / 64.0, 0.3, 2.2) + 0.3

    def chain(self, e, S, c):
        """Who touches the puck on the way to the shot, in order, after the carrier: the players credited with a
        goal's assists (second assist first), then the shooter. Shortened from the front when time is short."""
        side = e.side
        seq = []
        if e.type == "goal":
            seq = [self.pl[a] for a in reversed(e.assists) if a in self.pl and self.pl[a] in self.sk[side] and self.pl[a] is not S]
        seq.append(S)
        if c in seq:
            seq = seq[seq.index(c) + 1:]
        while len(seq) > 1:
            tot = sum(self.pass_time(a, b) for a, b in zip([c] + seq, seq))
            if tot <= e.t - self.t - 0.3:
                break
            seq.pop(0)
        return seq

    def need(self, side, e, pickup=0.0):
        """Seconds this side needs from here to get event e away (a shot from its spot; a foul needs the puck only)."""
        pk = self.pk
        if e.type == "penalty":
            return 1.0 + pickup
        pu, _ = self.rel(side, pk.x, pk.y)
        su, _ = self.rel(side, e.x, e.y)
        travel = max(0.0, su - 14.0 - pu) / 44.0
        sh = self.pl.get(e.pid)
        eta = 0.0
        if sh is not None:
            eta = math.hypot(sh.x - e.x, sh.y - e.y) / (sh.top * 0.9) + 0.9
        c = pk.carrier
        if c is not None and c.side == side and sh is not None and sh in self.sk[side] and pu > BLUE - 30:
            seq = [self.pl[a] for a in reversed(e.assists) if a in self.pl and self.pl[a] in self.sk[side] and self.pl[a] is not sh] \
                if e.type == "goal" else []
            seq.append(sh)
            if c in seq:
                seq = seq[seq.index(c) + 1:]
            fin = sum(self.pass_time(a, b) for a, b in zip([c] + seq, seq)) + 0.45
            return max(fin, eta) + pickup
        chain = len([a for a in e.assists if a in self.pl]) if e.type == "goal" else 1
        return max(travel + 1.0 + 0.75 * chain, eta) + pickup

    def possess(self, side, until, lose, e=None):
        """`side` keeps the puck until the clock reads `until` (re-read from e if given), then loses it if `lose`."""
        pk = self.pk
        while True:
            c = pk.carrier
            if c is None or c.side != side:
                return
            if e is not None and lose:
                until = e.t - self.need(1 - side, e, 1.7)
            left = until - self.t
            if lose and left < 1.3:
                yield from self.turnover(side)
                return
            if not lose and left < 0.25:
                return
            pu, pv = self.rel(side, c.x, c.y)
            if pu < BLUE - 1:
                if lose and left < 3.5 and pu > -BLUE:
                    yield from self.turnover(side, "dump")
                    return
                if lose and pu > -8 and self.rng.random() < 0.3:
                    yield from self.turnover(side, "dump")
                    return
                if left < 2.0:
                    yield from self.carry(c, pu + 2, pv, max(DT, left - 1.0 if lose else left), 0.7)
                else:
                    yield from self.move_up(side, False, left)
            else:
                yield from self.cycle(side, max(0.0, left - (1.3 if lose else 0.2)))

    def turnover(self, side, kind=None):
        """`side` loses the puck: dumped in, poked away, picked off, or (short-handed) cleared down the ice."""
        pk, rng = self.pk, self.rng
        c = pk.carrier
        other = 1 - side
        pu, pv = self.rel(side, c.x, c.y)
        s = 1 if pv >= 0 else -1
        opp = self.sk[other]
        short = len(self.sk[side]) < len(opp)
        if kind is None:
            r = rng.random()
            if pu < -BLUE:
                kind = "clear" if short else ("pick" if r < 0.5 else "poke")
            elif pu < BLUE:
                kind = "dump" if r < 0.6 else ("poke" if r < 0.85 else "pick")
            else:
                kind = "poke" if r < 0.55 else "pick"
        if not opp:
            kind = "dump"
        if kind in ("dump", "clear"):
            self.setst(c, PASS, 0.4)
            tu, tv = (90.0, -s * rng.uniform(22, 34)) if kind == "dump" else (93.0, s * rng.uniform(8, 30))
            x, y = self.world(side, tu, tv)
            d = math.hypot(x - pk.x, y - pk.y)
            self.loose(x, y, min(92.0, 16.0 + 0.62 * d), other)
            yield from self.wait(0.4)
            deep = [p for p in opp if p.grp == "D"] or opp
            who = min(deep, key=lambda p: math.hypot(p.x - x, p.y - y))
            yield from self.recover(other, who, 7.0)
            return
        if kind == "pick":
            best = None
            for m in self.mates(c):
                if self.dist(c, m) < 16:
                    continue
                dx, dy = m.x - c.x, m.y - c.y
                L2 = dx * dx + dy * dy
                for o in opp:
                    t = _clamp(((o.x - c.x) * dx + (o.y - c.y) * dy) / L2, 0.3, 0.9)
                    qx, qy = c.x + dx * t, c.y + dy * t
                    fl = math.sqrt(L2) * t / 54.0
                    gap = math.hypot(o.x - qx, o.y - qy)
                    if gap < o.top * 1.1 * fl + 3.0 and (best is None or gap < best[0]):
                        best = (gap, o, qx, qy, fl)
            if best is None:
                kind = "poke"
            else:
                _, o, qx, qy, fl = best
                fl = max(fl, 0.35)
                o.ovr, o.key = (qx, qy, 1.2), True
                self.setst(c, PASS, 0.4)
                pk.x, pk.y = self.stick(c)
                pk.mode, pk.carrier, pk.to, pk.t1 = "pass", None, o, self.pt + fl
                while self.pt < pk.t1 - 1e-9:
                    yield
                o.ovr, o.key = None, False
                self.give(o)
                return
        o = min(opp, key=lambda p: self.dist(p, c))
        o.key = True
        start = self.pt
        while self.dist(o, c) > 3.3 and self.pt - start < 2.4:
            o.ovr = (c.x, c.y, 1.25)
            if c.ovr is None:
                c.ovr = (*_inside(c.x + c.vx * 0.5, c.y + c.vy * 0.5, 3.0), 0.55)
            yield
        self.setst(o, CHECK, 0.5)
        self.setst(c, DOWN, 0.6)
        c.ovr = None
        pk.x, pk.y = self.stick(c)
        pk.mode, pk.carrier, pk.to, pk.t1 = "pass", None, o, self.pt + 0.4
        while self.pt < pk.t1 - 1e-9:
            yield
        o.ovr, o.key = None, False
        self.give(o)

    # ------------------------------------------------------------------ the attack that ends in the engine's event
    def attack(self, e):
        side = e.side
        pk = self.pk
        S = self.pl.get(e.pid)
        while True:
            c = pk.carrier
            room = e.t - self.t - self.need(side, e)
            if room <= 0.35:
                break
            if S is not None and S in self.sk[side] and S is not c and S.ovr is None:
                if e.t - self.t < math.hypot(S.x - e.x, S.y - e.y) / (S.top * 0.8) + 2.6:
                    S.ovr, S.key = (e.x, e.y, 1.1), True
            pu, _ = self.rel(side, c.x, c.y)
            if pu < BLUE - 1:
                yield from self.move_up(side, room < 2.5, room)
            else:
                yield from self.cycle(side, min(room, 3.0))
        yield from self.finish(e)

    def finish(self, e):
        """The last passes and the shot: the puck reaches the shooter at his spot and leaves his stick at e.t."""
        pk = self.pk
        side = e.side
        S = self.pl.get(e.pid)
        if S is not None and S not in self.sk[side] and self.force_on(S, e):
            self.check["rushed"] += 1
        if S is None or S not in self.sk[side]:
            self.check["missing"] += 1
            S = pk.carrier if pk.carrier in self.sk[side] else (self.sk[side][0] if self.sk[side] else None)
            if S is None:
                e.done = True
                return
        c = pk.carrier
        S.key = True
        S.ovr = (e.x, e.y, 1.3)
        blocker = None
        if e.type == "block" and e.opp in self.pl and self.pl[e.opp] in self.sk[1 - side]:
            blocker = self.pl[e.opp]
            blocker.key = True
        seq = self.chain(e, S, c)
        T = e.t
        k = len(seq)
        for i, r in enumerate(seq):
            rest = sum(self.pass_time(a, b) for a, b in zip(seq[i:], seq[i + 1:]))    # the passes still to come after this one
            arrive = T - 0.35 - rest
            fl = self.pass_time(c, r) - 0.3
            if c.ovr is None:
                c.ovr = (*_inside(c.x + c.vx * 0.4, c.y + c.vy * 0.4, 3.0), 0.6)
            while self.t < arrive - fl - 1e-9:
                yield
            if c is not S:
                c.ovr = None
            if blocker is not None and i == k - 1 and e.bx is not None:
                blocker.ovr = (e.bx, e.by, 1.25)
            yield from self.pass_to(c, r, flight=max(self.dist(c, r) / 96.0, arrive - self.t, 0.25))
            c = r
        if blocker is not None and blocker.ovr is None and e.bx is not None:
            blocker.ovr = (e.bx, e.by, 1.25)
        while self.t < T - 1e-9:
            yield
        off = math.hypot(S.x - e.x, S.y - e.y)
        if off > 9.0:
            self.check["offspot"] += 1
        S.ovr, S.key = None, False
        yield from self.shoot(S, e, blocker)

    def shoot(self, S, e, blocker=None):
        pk, rng = self.pk, self.rng
        side, other = e.side, 1 - e.side
        d = self.dir(side)
        nx = d * NET
        g = self.gk[other]
        self.setst(S, SHOOT, 0.6)
        pk.x, pk.y = self.stick(S)
        pk.carrier, pk.last = None, S
        self.poss = side
        if e.type == "goal":
            gy = g.y if g is not None else 0.0
            ty = (-1 if gy > 0 else 1) * rng.uniform(0.8, 2.5) if g is not None else rng.uniform(-2, 2)
            tgt = (nx + d * 2.0, ty)
        elif e.type == "shot" and g is not None:
            tgt = (g.x, g.y)
        elif e.type == "miss":
            tgt = (e.mx if e.mx is not None else nx + d * 4, e.my if e.my is not None else 8.0)
        elif e.type == "block" and blocker is not None:
            tgt = (blocker.x, blocker.y)
        else:
            tgt = (nx - d * 1.0, rng.uniform(-2, 2))
        dist = math.hypot(tgt[0] - pk.x, tgt[1] - pk.y)
        fl = _clamp(dist / 105.0, 0.2, 0.8)
        pk.mode, pk.to, pk.t1, pk.tgt = "shot", None, self.pt + fl, tgt
        pk.vx, pk.vy = (tgt[0] - pk.x) / fl, (tgt[1] - pk.y) / fl
        sv = (pk.vx, pk.vy)
        pk.h = 2 if dist > 22 and e.type != "block" else 1
        if e.type == "block" and blocker is not None:
            pk.to = blocker
            self.setst(blocker, BLOCK, 0.9)
        if g is not None and e.type in ("goal", "shot"):
            self.setst(g, GSAVE, 1.0)
            if e.type == "shot":
                pk.to = g
        self.mark("release", side, pid=S.pid, kind=e.type, x=round(S.x, 1), y=round(S.y, 1))
        while self.pt < pk.t1 - 1e-9:
            yield
        pk.to, pk.h, pk.tgt = None, 0, None
        pk.vx, pk.vy = sv
        e.done = True
        if e.type in ("goal", "shot"):
            self.sog[side] += 1
        if blocker is not None:
            blocker.ovr, blocker.key = None, False
        nxt = self.after(e)
        gap = nxt.t - self.t if nxt is not None else 99.0
        same = nxt is not None and nxt.side == side and nxt.type in IP.ATTEMPT
        if e.type == "goal":
            yield from self.goal(e, S)
            return
        if e.type == "shot":
            self.mark("save", other, pid=g.pid if g else None, by=S.pid, xg=e.xg)
            if same and gap <= 3.4:                                   # the rebound goes straight to the next shooter
                yield from self.rebound(nxt)
                return
            if same and gap <= 15:
                self.loose(nx - d * rng.uniform(4, 12), rng.choice((-1, 1)) * rng.uniform(22, 36), rng.uniform(24, 36), side)
                yield from self.recover(side, None, 4.0)
                return
            if g is not None and (nxt is None or gap > 9) and rng.random() < 0.34:
                yield from self.freeze(other, g)
                return
            self.loose(nx - d * rng.uniform(2, 9), rng.choice((-1, 1)) * rng.uniform(20, 36), rng.uniform(20, 32), other)
            deep = [p for p in self.sk[other] if p.grp == "D"]
            yield from self.recover(other, min(deep, key=self.dpk) if deep else None, 4.5)
            return
        if e.type == "miss":
            self.mark("miss", side, pid=S.pid)
            pk.mode = "loose"
            pk.vx *= 0.55
            pk.vy *= 0.55
        else:
            self.mark("block", other, pid=blocker.pid if blocker else None, by=S.pid)
            ang = rng.uniform(0, 6.283)
            pk.mode = "loose"
            pk.vx, pk.vy = math.cos(ang) * 22 - d * 8, math.sin(ang) * 22
        if same and gap <= 3.4:
            yield from self.rebound(nxt)
            return
        if same and gap <= 15:
            who = side
        elif nxt is not None and nxt.type in IP.ATTEMPT and nxt.side != side and gap <= 13:
            who = other
        elif nxt is not None and nxt.type == "penalty" and gap <= 12:
            who = 1 - nxt.side
        else:
            who = other if rng.random() < 0.6 else side
        self.loose_for = who
        yield from self.wait(0.4)
        yield from self.recover(who, None, 5.0)

    def rebound(self, e):
        """A second chance: the puck comes out to the next shooter, who puts it back at the net at once."""
        pk = self.pk
        side = e.side
        S = self.pl.get(e.pid)
        if S is not None and S not in self.sk[side] and self.force_on(S, e):
            self.check["rushed"] += 1
        if S is None or S not in self.sk[side]:
            self.check["missing"] += 1
            S = min(self.sk[side], key=self.dpk)
        S.key = True
        S.ovr = (e.x, e.y, 1.3)
        fl = max(0.3, e.t - 0.3 - self.t)
        pk.mode, pk.carrier, pk.to, pk.t1 = "pass", None, S, self.pt + fl
        self.loose_for = side
        blocker = None
        if e.type == "block" and e.opp in self.pl and self.pl[e.opp] in self.sk[1 - side]:
            blocker = self.pl[e.opp]
            blocker.key = True
            if e.bx is not None:
                blocker.ovr = (e.bx, e.by, 1.25)
        while self.pt < pk.t1 - 1e-9:
            yield
        self.give(S)
        while self.t < e.t - 1e-9:
            yield
        if math.hypot(S.x - e.x, S.y - e.y) > 9.0:
            self.check["offspot"] += 1
        S.ovr, S.key = None, False
        yield from self.shoot(S, e, blocker)

    # ------------------------------------------------------------------ whistles
    def clear_script(self):
        for p in self.pl.values():
            p.ovr, p.key = None, False
        self.presser = [None, None]
        self.delay = [False, False]

    def goal(self, e, S):
        pk = self.pk
        side = e.side
        self.run = False
        self.score[side] += 1
        pk.mode, pk.vx, pk.vy = "dead", 0.0, 0.0
        self.mark("goal", side, pid=S.pid, assists=list(e.assists), score=list(self.score), en=e.en, clock=e.clock, xg=e.xg,
                  official=e.official)
        self.mode = "dead"
        d = self.dir(side)
        cx, cy = _inside(S.x - d * 14, S.y + (10 if S.y < 0 else -10), 6.0)
        for p in self.sk[side]:
            self.setst(p, CELEB, 3.4)
            p.ovr = (cx + (p.k % 3 - 1) * 3.0, cy + (p.k % 2) * 3.0 - 1.5, 0.8)
        for p in self.sk[1 - side]:
            p.ovr = (*_inside(p.x - d * 6, p.y * 0.8, 4.0), 0.35)
        yield from self.wait(3.4)
        for x in self.ev[self.ei:self.ei + 4]:                       # the engine changed the beaten goalie
            if x.type == "goalie" and not x.done and x.official == e.official:
                x.done = True
                self.goalie_now[x.side] = x.pid
                self.mark("goalie", x.side, pid=x.pid)
        if self.per >= 4:
            raise GameOver()
        yield from self.faceoff(0.0, 0.0)

    def freeze(self, side, g):
        pk = self.pk
        pk.mode, pk.vx, pk.vy = "dead", 0.0, 0.0
        pk.x, pk.y = g.x + self.dir(side) * 1.2, g.y
        self.setst(g, GCOVER, 1.6)
        yield from self.wait(0.8)
        self.run = False
        self.mode = "dead"
        self.mark("whistle", side, why="frozen")
        yield from self.wait(0.9)
        d = self.dir(side)
        yield from self.faceoff(-d * 69.0, 22.0 if pk.y >= 0 else -22.0)

    def penalty(self, pens):
        """The foul, the whistle, the walk to the box, and the draw in the offender's end."""
        pk = self.pk
        e = pens[0]
        c = pk.carrier
        both = len({x.side for x in pens}) > 1
        offenders = [self.pl[x.pid] for x in pens if x.pid in self.pl]
        O = self.pl.get(e.pid)
        if O is not None and O in self.sk[e.side] and c is not None and c.side != e.side:
            O.key = True
            self.delay[e.side] = True
            while self.t < e.t - 0.5 and self.dist(O, c) > 3.4:
                O.ovr = (c.x, c.y, 1.3)
                yield
            self.setst(O, CHECK, 0.7)
            self.setst(c, DOWN, 0.9)
        while self.t < e.t - 1e-9:
            yield
        self.run = False
        self.mode = "dead"
        for x in pens:
            x.done = True
            self.mark("penalty", x.side, pid=x.pid, detail=x.detail, clock=x.clock, official=x.official)
        pk.mode, pk.carrier, pk.vx, pk.vy = "dead", None, 0.0, 0.0
        self.clear_script()
        for p in offenders:
            if any(q is p for q, _ in self.off):               # he was on his way off: he goes to the box instead
                self.off = [(q, u) for q, u in self.off if q is not p]
                self.sk[p.side].append(p)
            p.ovr = (BOX_X[p.side], -HW + 2.0, 1.0)
        start = self.pt
        while self.pt - start < 7.0 and any(math.hypot(p.x - BOX_X[p.side], p.y + HW - 2.0) > 5.0 for p in offenders if p in self.sk[p.side]):
            yield
        yield from self.wait(0.4)
        for p in offenders:
            p.ovr = None
            p.state, p.st_until = BOXED, 0.0
            if p in self.sk[p.side]:
                self.sk[p.side].remove(p)
            self.box[p.side].add(p.pid)
        if both:
            fx = -20.0 if pk.x < 0 else 20.0
        else:
            fx = -self.dir(e.side) * 69.0
        yield from self.faceoff(fx, 22.0 if pk.y >= 0 else -22.0, t=e.t + 0.5)

    def horn(self):
        self.run = False
        self.mode = "dead"
        self.pk.mode, self.pk.carrier, self.pk.to = "dead", None, None
        self.pk.vx = self.pk.vy = 0.0
        self.clear_script()
        self.mark("horn", None)
        for side in (0, 1):
            for i, p in enumerate(self.sk[side]):
                p.ovr = (*self.door(side, i), 0.6)
        yield from self.wait(2.4)
        self.clear_script()

    def faceoff(self, fx, fy, t=None):
        """Line both sides up at a dot and drop the puck."""
        pk, rng = self.pk, self.rng
        self.mode = "dead"
        self.run = False
        self.clear_script()
        self.off = []
        self.apply_units(True, (self.t if t is None else t) + 0.3)
        self.cut = True
        pk.mode, pk.carrier, pk.to, pk.x, pk.y, pk.vx, pk.vy = "dead", None, None, fx, fy, 0.0, 0.0
        cen = [None, None]
        for side in (0, 1):
            d = self.dir(side)
            sk = self.sk[side]
            F = [p for p in sk if p.grp == "F"]
            D = [p for p in sk if p.grp == "D"]
            c = next((p for p in F if p.slot == "C"), F[0] if F else (sk[0] if sk else None))
            cen[side] = c
            wings = [p for p in F if p is not c]
            fu = fx * d
            inner = -1 if fy > 0 else 1                               # towards the middle of the ice
            for p in sk:
                if p is c:
                    p.put(fx - d * 2.3, fy, 0.0 if d > 0 else math.pi)
                    p.state, p.st_until = DRAW, 0.0
            if abs(fy) > 1:
                wspots = [(fx - d * 2.5, fy + inner * 15.5), (fx - d * 2.5, fy - inner * 13.0)]
            else:
                wspots = [(fx - d * 2.5, 15.5), (fx - d * 2.5, -15.5)]
            for p, q in zip(wings, wspots):
                x, y = _inside(q[0], q[1], 3.0)
                p.put(x, y, 0.0 if d > 0 else math.pi)
            for p in wings[2:]:
                p.put(*_inside(fx - d * 9.0, fy + inner * 6.0, 3.0), 0.0 if d > 0 else math.pi)
            if fu > 40:                                               # attacking-zone draw: the defence on the points
                dsp = [(d * 31.0, fy * 0.95), (d * 31.0, fy * 0.95 + inner * 26.0)]
            elif fu < -40:                                            # own-zone draw: one behind the centre, one at the net
                dsp = [(fx - d * 9.0, fy - inner * 1.0), (fx - d * 12.0, fy + inner * 14.0)]
            else:
                dsp = [(fx - d * 17.0, fy + 8.0 if abs(fy) < 1 else fy + inner * 3.0), (fx - d * 17.0, fy - 8.0 if abs(fy) < 1 else fy + inner * 18.0)]
            for p, q in zip(D, dsp):
                x, y = _inside(q[0], q[1], 3.0)
                p.put(x, y, 0.0 if d > 0 else math.pi)
            g = self.gk[side]
            if g is not None:
                g.put(-d * (NET - 3.0), 0.0, 0.0 if d > 0 else math.pi)
                g.state = GSET
        self.mark("faceoff", None, x=fx, y=fy)
        yield from self.wait(1.4)
        nxt = self.peek()
        if nxt is not None and nxt.t - self.t < 14 and nxt.type in IP.ATTEMPT:
            win = nxt.side
        elif nxt is not None and nxt.type == "penalty" and nxt.t - self.t < 14:
            win = 1 - nxt.side
        else:
            win = 0 if rng.random() < 0.5 else 1
        c = cen[win]
        self.mode = "play"
        self.run = True
        for side in (0, 1):
            if cen[side] is not None:
                cen[side].state = SK
        if c is None:
            return
        back = [p for p in self.sk[win] if p is not c and p.grp == "D"] or [p for p in self.sk[win] if p is not c]
        if back:
            r = min(back, key=lambda p: self.dist(p, c))
            pk.mode, pk.carrier, pk.to, pk.t1, pk.last = "pass", None, r, self.pt + 0.6, c
            self.poss = win
            self.setst(c, PASS, 0.4)
            while self.pt < pk.t1 - 1e-9:
                yield
            self.give(r)
        else:
            self.give(c)

    # ------------------------------------------------------------------ the game
    def play(self):
        pk, rng = self.pk, self.rng
        while True:
            e = self.peek()
            if pk.mode == "loose" or pk.carrier is None:
                side = self.loose_for if self.loose_for is not None else (0 if rng.random() < 0.5 else 1)
                yield from self.recover(side)
            c = pk.carrier
            x = c.side
            if e is None:
                yield from self.possess(x, self.t + rng.uniform(7, 18), True)
                continue
            if e.type == "goalie":
                e.done = True
                self.goalie_now[e.side] = e.pid
                continue
            if e.type == "penalty":
                pens = [q for q in self.ev[self.ei:self.ei + 3] if q.type == "penalty" and not q.done and q.t == e.t]
                a = x if len({q.side for q in pens}) > 1 else 1 - e.side
                if x != a:
                    yield from self.possess(x, 0.0, True, e)
                    continue
                yield from self.possess(x, e.t - 1.5, False)
                if pk.carrier is None or pk.carrier.side != a:
                    continue
                yield from self.penalty(pens)
                continue
            a = e.side
            if x != a:
                yield from self.possess(x, 0.0, True, e)
                continue
            slack = e.t - self.t - self.need(a, e)
            if slack > 13 and rng.random() < min(0.72, (slack - 9) / 26):
                yield from self.possess(x, self.t + rng.uniform(4, max(5, slack - 10)), True)
            else:
                yield from self.attack(e)

    def script(self):
        for per, length in self.periods:
            self.per = per
            self.t = (per - 1) * 1200.0
            self.t_end = self.t + length
            self.goalie_now = self.goalie_now if per > 1 else [None, None]
            self.mark("period", None, n=per)
            try:
                yield from self.faceoff(0.0, 0.0)
                yield from self.play()
            except Horn:
                for e in self.ev:
                    if e.per == per and e.t is not None and not e.done:
                        e.done = True
                        if e.type in IP.ATTEMPT or e.type == "penalty":
                            self.check["late"] += 1
                            self.late.append((e.type, e.t, self.t))
                yield from self.horn()
            except GameOver:
                self.clear_script()
                yield from self.wait(1.0)
                return
        if self.shootout:
            yield from self.play_shootout()

    def play_shootout(self):
        pk, rng = self.pk, self.rng
        self.per = 5
        self.mode, self.run = "shootout", False
        self.mark("period", None, n=5)
        sc = [0, 0]
        for e in self.shootout:
            side, other = e.side, 1 - e.side
            S, g = self.pl.get(e.pid), self.pl.get(e.opp)
            if S is None:
                continue
            self.clear_script()
            self.off = []
            self.sk = [[], []]
            self.sk[side] = [S]
            self.gk = [None, None]
            d = 1                                                    # every attempt at the +x net
            self.cut = True
            S.put(-6.0, 0.0, 0.0)
            S.slot = "C"
            if g is not None:
                self.gk[other] = g
                g.put(NET - 3.0, 0.0, math.pi)
                g.state = GSET
            pk.x, pk.y, pk.vx, pk.vy = 0.0, 0.0, 0.0, 0.0
            pk.mode, pk.carrier = "dead", None
            self.poss = side
            self.mark("so_start", side, pid=S.pid, round=(e.so_round or 0) + 1)
            yield from self.wait(1.0)
            S.ovr = (0.0, 0.0, 0.7)
            yield from self.wait(0.8)
            self.give(S)
            sx, sy = (e.x if e.x is not None else 76.0), (e.y if e.y is not None else 0.0)
            swing = rng.choice((-1, 1)) * rng.uniform(6, 13)
            S.ovr = (40.0, swing, 0.82)
            while S.x < 36.0:
                if g is not None:
                    g.ovr = (NET - 2.5 - 4.5 * _clamp((70 - S.x) / 60, 0, 1), _clamp(S.y * 0.08, -2, 2), 1.0)
                yield
            S.ovr = (sx, sy, 0.8)
            while math.hypot(S.x - sx, S.y - sy) > 3.5:
                if g is not None:
                    g.ovr = (NET - 2.5 - 3.0 * _clamp((80 - S.x) / 40, 0, 1), _clamp(S.y * 0.25, -3, 3), 1.0)
                yield
            S.ovr = None
            self.setst(S, SHOOT, 0.6)
            pk.x, pk.y = self.stick(S)
            pk.carrier = None
            ok = e.type == "so_goal"
            if ok:
                ty = (-1 if (g.y if g else 0) > 0 else 1) * rng.uniform(1.0, 2.5)
                tgt = (NET + 2.0, ty)
            else:
                tgt = (g.x, g.y) if (g is not None and rng.random() < 0.75) else (NET + 3.0, rng.choice((-1, 1)) * rng.uniform(4.5, 8))
            fl = 0.3
            pk.mode, pk.to, pk.t1, pk.h, pk.tgt = "shot", None, self.pt + fl, 1, tgt
            pk.vx, pk.vy = (tgt[0] - pk.x) / fl, (tgt[1] - pk.y) / fl
            if g is not None:
                self.setst(g, GSAVE, 1.2)
                g.ovr = None
            yield from self.wait(fl)
            pk.mode, pk.vx, pk.vy, pk.h, pk.tgt = "dead", 0.0, 0.0, 0, None
            sc[side] += ok
            self.mark("so_goal" if ok else "so_miss", side, pid=S.pid, tally=list(sc), round=(e.so_round or 0) + 1)
            if ok:
                self.setst(S, CELEB, 1.6)
            S.ovr = (S.x - 10, S.y + 14, 0.5)
            yield from self.wait(1.8)
        self.clear_script()

    def run_game(self):
        gen = self.script()
        while True:
            try:
                if self.run and self.mode == "play" and self.t >= self.t_end - 1e-9 and self.pk.mode != "shot":
                    gen.throw(Horn())
                else:
                    next(gen)
            except StopIteration:
                break
            self.tick()
            if len(self.frames) > 60000:
                break
        return self


def _periods(conn, g, events):
    from ..league.season import db_rules
    try:
        ot = dict(dict(format="3v3", minutes=5, shootout=True), **((db_rules(conn) or {}).get("overtime") or {}))
    except Exception:
        ot = dict(format="3v3", minutes=5, shootout=True)
    last = max([e.per for e in events if e.t is not None] + [3])
    playoff = (g["game_type"] or "RS") not in ("RS", "PRE", "EX") and last >= 4
    periods = [(1, 1200), (2, 1200), (3, 1200)]
    went = g["went_to_ot"] or 0
    if playoff or (last >= 4 and ot.get("format") == "5v5" and not ot.get("shootout") and last > 4):
        for p in range(4, last + 1):
            periods.append((p, 1200))
        return periods, 5, True
    if went or last >= 4:
        n = {"3v3": 3, "4v4": 4, "5v5": 5}.get(ot.get("format"), 3)
        mins = int(ot.get("minutes") or 0)
        if mins and ot.get("format") != "none":
            periods.append((4, mins * 60))
        return periods, n, False
    return periods, 3, False


def build(conn, gid):
    """Plan and play one game; returns the Game (frames, marks, players, check)."""
    from ..game import replay as RP
    data = RP.build(conn, gid)
    g = conn.execute("SELECT * FROM games WHERE game_id=?", (gid,)).fetchone()
    events = IP.load_events(conn, gid, data)
    periods, ot_n, playoff = _periods(conn, g, events)
    plen = dict(periods)
    for per in sorted({e.per for e in events if e.t is not None and e.per >= 4}):
        # sudden death: nothing follows the goal. The engine draws one side's attempts of a step before the other's,
        # so an attempt can carry a later second than the winning goal; it happened before it.
        goal = next((e for e in events if e.per == per and e.type == "goal"), None)
        if goal is not None:
            for e in events:
                if e.per == per and e.t is not None and e is not goal and e.t >= goal.t:
                    e.t = max((per - 1) * 1200 + 2.5, goal.t - 7.0)
    for per in sorted({e.per for e in events if e.t is not None}):
        IP.retime([e for e in events if e.per == per and e.t is not None], plen.get(per, 1200))
    events.sort(key=lambda e: (e.per, e.t if e.t is not None else 1e9, e.i))
    st = IP.strength(events, periods, ot_n=ot_n, playoff=playoff)
    rosters = [IP.roster(conn, gid, g["home_team_id"]), IP.roster(conn, gid, g["away_team_id"])]
    un = IP.units(events, st, periods, rosters, f"{gid}-{g['seed']}")
    so = [e for e in events if e.type in ("so_goal", "so_miss")]
    live = [e for e in events if e.t is not None]
    game = Game(live, st, un, periods, rosters, f"{gid}-{g['seed']}", so).run_game()
    return game, data


def track(conn, gid):
    """The tracking of one played game for the viewer.

    dt        seconds between frames
    frames    [clock in tenths, flags (1 clock running, 2 cut: do not glide from the frame before, 4 / 8 delayed
              penalty on the home / away side), puck x, puck y (tenths of a foot; centre ice is 0, 0; the home side
              shoots at +x in the 1st and 3rd), puck mode x 10 + height (0 carried, 1 pass, 2 shot, 3 loose, 4 dead),
              carrier (index into players, or -1), then five numbers for everyone on the ice: player index, x, y,
              facing (0-71, five degrees a step), state]
    players   [dict(id, side (0 home, 1 away), name, pos, num, hand)]
    marks     what happened, each with its frame f: period, faceoff, release, save, miss, block, goal, penalty,
              whistle, horn, goalie, so_start, so_goal, so_miss
    """
    game, data = build(conn, gid)
    return dict(v=2, dt=DT, frames=game.frames, players=game.players, marks=game.marks, check=game.check,
                home=data["home"], away=data["away"], final=data["final"], length=data["length"], date=data.get("date"),
                periods=[list(p) for p in game.periods], states=["skate", "glide", "pass", "shoot", "check", "block", "celebrate",
                                                                "set", "save", "cover", "draw", "down", "box", "bench"])
