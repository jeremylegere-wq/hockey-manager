"""Seeded game engine.

A game is a sequence of 30-second segments. In each segment both teams generate shot attempts at a rate set by
(a) the real league rate for the strength state (even / power play / short-handed, from hs.sim.env) and
(b) the skill of the five skaters on the ice versus the opposing five. Every attempt can be blocked, miss, or
reach the goalie; a shot on goal scores with a probability set by the league rate, the shooter's shot-quality
and finishing, and the goalie. Saves can produce rebounds. Penalties, power plays, empty-net goals, overtime
(3v3) and the shootout are modelled. The same seed always gives the same game.

Skill enters as z-scores of the 1-20 attributes ((rating - 10.5) / 3 = standard deviations of true talent), scaled
by `Skill` constants that hs.sim.validate tunes against the real league's team-to-team spreads.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

CENTRE, SPREAD = 10.5, 3.0
STEP = 30  # seconds per segment


def zr(v):
    return ((v if v is not None else 10) - CENTRE) / SPREAD


@dataclass
class Skill:
    """Fractional change in a rate per +1 sd of the (unit-averaged) skill index.

    Tuned by hs.sim.validate so that, with real 2025-26 rosters, the sim reproduces the real league's team-to-team
    spread. att/sup are large because ratings are shrunk estimates (narrow) and a five-skater average is narrower
    still; read them as calibration constants, not as the effect of one player. See docs/SIM_CALIBRATION.md."""
    att_scale: float = 0.960  # global calibration (v33: 0.955 -> 0.960 to make up the power-play scale) of attempt volume (absorbs score-effect / skill asymmetries)
    att: float = 0.60       # own offence -> team shot attempts   (v25 ratings; 0.72 with the pre-v25 ratings model)
    sup: float = 0.60       # opposing defence -> fewer attempts against
    qual: float = 0.03      # shooter shot-quality -> goal probability
    fin: float = 0.10       # shooter finishing -> goal probability
    goalie: float = 0.33    # goalie save skill -> goal probability
    reb: float = 0.15       # goalie rebound control -> rebound probability
    dq: float = 0.03        # opposing defence -> lower goal probability (shot quality against)
    blk: float = 0.10       # shot blocking -> blocked share
    pen: float = 0.15       # composure -> penalty rate
    home: float = 0.05      # home-ice attempt boost
    score_effect: float = 0.04   # trailing teams press: +4% attempts per goal behind (max 2), leaders sit back
    offset_prob: float = 0.10   # chance a penalty is matched by an opposing one (4v4)
    en_att: float = 2.0        # attempt multiplier for a team with the goalie pulled
    en_goal_per_min: float = 0.25   # empty-net goals per minute for the leading team while the goalie is out
    ot_att: float = 1.75        # 3v3 attempt multiplier vs 5v5
    ot_sh: float = 1.15         # 3v3 shooting multiplier vs 5v5
    shootout_pct: float = 0.33
    shot_pick: float = 0.55     # how strongly shot attempts go to the unit's best puck carriers (per sd of gen)
    assist_pick: float = 0.65   # how strongly assists go to the unit's best passers (per sd of passing)
    d_finish: float = 0.46      # a defenceman's goals per attempt as a share of the league's (point shots; MoneyPuck
                                # 2023-25: 0.45 5v5, 0.47 5v4). Used when the env file has no d_goal_factor.
    d_assist: float = 0.45      # weight on a defenceman's chance of an assist against a forward's (real D share of
                                # assists ~0.32 at 5v5; without it the two D in a five-man unit took 0.46)
    pp_scale: float = 0.93      # v33 calibration: power-play attempt volume (the best players fill the first PP unit, so
                                # skill pushed PP goals ~8% over the real rate with the env's 5v4 rates alone)
    pen_scale: float = 1.015    # v33 calibration: penalty rate (composure and the clubs' tactics left it 1.5% short)
    chem: float = 0.05          # v33: even-strength attempts per unit of line chemistry above the other unit's (0-1 scale)
    hook_quality: float = 0.0   # v33: kept for packs; the hook itself is a club preference (hs/game/tactics.py)


@dataclass
class Player:
    pid: int
    pos: str
    name: str = ""
    gen: float = 0.0
    qual: float = 0.0
    fin: float = 0.0
    sup: float = 0.0
    blk: float = 0.0
    comp: float = 0.0
    pas: float = 0.0
    save: float = 0.0
    reb: float = 0.0
    toi: float = 0.0   # sort key for the depth chart (e.g. last season's ice time)
    gp: float = 0.0
    shoot_w: float = 1.0   # v33 tendencies: weight on taking the shot (shoot first > 1, pass first < 1)
    assist_w: float = 1.0  # and on making the pass
    cons_sd: float = 0.0   # v35 hidden: night-to-night swing in his offence (sd, in the engine's units)
    bg: float = 0.0        # v35 hidden: playoff finishing shift
    temper: float = 1.0    # v35 hidden: weight on taking the penalty
    rfx: dict = None       # v55 tactical role: {state: {key: multiplier}} while he is on the ice (hs/game/troles.py)
    protect: bool = False  # v55: an enforcer dressed: the other club's agitators draw half as much

    @classmethod
    def from_attrs(cls, pid, pos, a, name="", toi=0.0, gp=0.0):
        z = lambda k: zr(a.get(k))
        m = lambda *ks: sum(z(k) for k in ks) / len(ks)
        return cls(pid, pos, name,
                   gen=m("puck_control", "offensive_awareness", "passing"), qual=m("offensive_awareness", "net_presence"),
                   fin=m("shot_accuracy", "shot_power"), sup=m("positioning", "defensive_awareness", "stick_checking"),
                   blk=z("shot_blocking"), comp=z("composure"), pas=z("passing"),
                   save=m("goalie_positioning", "reflexes", "glove", "blocker", "low_shot_save"),
                   reb=z("rebound_control"), toi=toi, gp=gp)


class Team:
    def __init__(self, team_id, name, players):
        self.team_id, self.name = team_id, name
        sk = sorted([p for p in players if p.pos != "G"], key=lambda p: -p.toi)
        self.goalies = sorted([p for p in players if p.pos == "G"], key=lambda p: (-p.gp, -p.toi))
        used = set()

        def take(pred, n):
            out = [p for p in sk if p.pid not in used and pred(p)][:n]
            used.update(p.pid for p in out)
            return out
        cs = take(lambda p: p.pos == "C", 4)
        ws = take(lambda p: p.pos in ("LW", "RW"), 8)
        ds = take(lambda p: p.pos == "D", 6)
        spare = [p for p in sk if p.pid not in used]
        for lst, n in ((cs, 4), (ws, 8), (ds, 6)):
            while len(lst) < n and spare:
                lst.append(spare.pop(0))
        self.lines = [[c] + ws[2 * i:2 * i + 2] for i, c in enumerate(cs)]
        self.pairs = [ds[2 * i:2 * i + 2] for i in range(3)]
        self.pp, self.pk = [], []          # special-teams units set by a lines editor; empty = drawn from the lines
        self.tac = None                    # team-system multipliers (hs/game/tactics.py); None = balanced
        self.custom = False
        self.ot3, self.ot4 = [], []        # v33: overtime units from the lines editor (3-on-3, 4-on-4); empty = top lines
        self.chem = {}                     # v33: {frozenset({a, b}): 0-1} line chemistry, relative to the league
        self._all = {p.pid: p for p in players}
        self.skaters = [p for ln in self.lines for p in ln] + [p for pr in self.pairs for p in pr]
        self.by_id = {p.pid: p for p in self.skaters + self.goalies}

    def apply_lineup(self, lu):
        """Use a saved lineup: {"F": [[C, LW, RW] x4], "D": [[L, R] x3], "G": [starter, backup], "PP": [[5], [5]],
        "PK": [[4], [4]]} of player ids. Players no longer available are replaced from the default depth chart, so
        an injury or a trade never leaves a hole. Returns the ids that had to be replaced."""
        avail = self._all
        used, missing = set(), []

        def get(pid):
            if pid in avail and pid not in used and avail[pid].pos != "G":
                used.add(pid)
                return avail[pid]
            if pid is not None:
                missing.append(pid)
            return None
        f = [[get(x) for x in (ln + [None] * 3)[:3]] for ln in (lu.get("F") or [])[:4]]
        d = [[get(x) for x in (pr + [None] * 2)[:2]] for pr in (lu.get("D") or [])[:3]]
        while len(f) < 4:
            f.append([None, None, None])
        while len(d) < 3:
            d.append([None, None])
        # holes: the default depth chart, same position group first
        fwd = [p for ln in self.lines for p in ln] + [p for pr in self.pairs for p in pr]
        dfl = [p for pr in self.pairs for p in pr] + [p for ln in self.lines for p in ln]
        spare = [p for p in sorted(avail.values(), key=lambda p: -p.toi) if p.pos != "G"]

        def fill(slot_d):
            for src in ((dfl if slot_d else fwd), spare):
                for p in src:
                    if p.pid not in used and (p.pos == "D") == slot_d:
                        used.add(p.pid)
                        return p
            for p in spare:
                if p.pid not in used:
                    used.add(p.pid)
                    return p
            return None
        self.lines = [[x or fill(False) for x in ln] for ln in f]
        self.pairs = [[x or fill(True) for x in pr] for pr in d]
        self.lines = [[x for x in ln if x] for ln in self.lines]
        self.pairs = [[x for x in pr if x] for pr in self.pairs]
        g = [avail[x] for x in (lu.get("G") or []) if x in avail and avail[x].pos == "G"]
        if g:
            self.goalies = g + [x for x in self.goalies if x.pid not in {y.pid for y in g}]
        elif lu.get("G"):
            missing += [x for x in lu["G"] if x not in avail]
        dressed = {p.pid for ln in self.lines for p in ln} | {p.pid for pr in self.pairs for p in pr}
        self.pp = [[avail[x] for x in u if x in dressed] for u in (lu.get("PP") or [])[:2]]
        self.pk = [[avail[x] for x in u if x in dressed] for u in (lu.get("PK") or [])[:2]]
        self.pp = [u for u in self.pp if len(u) >= 4]
        self.pk = [u for u in self.pk if len(u) >= 3]
        self.ot3 = [u for u in ([[avail[x] for x in u if x in dressed] for u in (lu.get("OT3") or [])[:2]]) if len(u) == 3]
        self.ot4 = [u for u in ([[avail[x] for x in u if x in dressed] for u in (lu.get("OT4") or [])[:2]]) if len(u) == 4]
        self.custom = True
        self.force_starter = bool(lu.get("G_force"))         # v52: the goalie rule picked today's starter
        self.skaters = [p for ln in self.lines for p in ln] + [p for pr in self.pairs for p in pr]
        self.by_id = {p.pid: p for p in self.skaters + self.goalies}
        return missing


@dataclass
class GameResult:
    goals: list = field(default_factory=lambda: [0, 0])
    went_to_ot: bool = False
    shootout: bool = False
    tie: bool = False
    events: list = field(default_factory=list)       # (period, clock, type, team_idx, pid, opp_pid, xg, detail)
    stats: dict = field(default_factory=dict)        # pid -> dict(team, toi, g, a, sog, att, pim, sa, saves)
    team: list = field(default_factory=lambda: [dict(att=0, sog=0, blocked=0, missed=0, pim=0, pens=0, pp_sec=0,
                                                       pp_goals=0, sh_goals=0, ev_goals=0, en_goals=0, ot_goals=0,
                                                       att_ev=0, xg_ev=0.0)
                                                  for _ in range(2)])


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


F_WEIGHTS = {"ev": [.38, .31, .20, .11], "pp": [.55, .30, .15, 0], "sh": [.30, .35, .25, .10]}
D_WEIGHTS = {"ev": [.40, .35, .25], "pp": [.55, .35, .10], "sh": [.35, .40, .25]}
# v33: a club's ice-time preference spreads even-strength shifts differently over its lines and pairs
ICE_F = {"roll four lines": [.31, .28, .24, .17], "balanced": F_WEIGHTS["ev"], "shorten the bench": [.45, .33, .16, .06]}
ICE_D = {"roll four lines": [.36, .34, .30], "balanced": D_WEIGHTS["ev"], "shorten the bench": [.46, .36, .18]}
PULL = {"4:00": 240, "3:00": 180, "2:00": 120, "1:30": 90, "1:00": 60, "never": -1}
HOOK = {"after 3 goals": 3, "after 4 goals": 4, "after 5 goals": 5, "never": 99}


def _pref(t, k, default):
    return ((t.tac or {}).get("prefs") or {}).get(k, default)


OT_DEFAULT = {"format": "3v3", "minutes": 5, "shootout": True}
# 3v3 is what ot_att / ot_sh were fitted to; fewer skaters means more room. 4v4 sits half-way, 5v5 is regulation.
OT_SKATERS = {"3v3": 3, "4v4": 4, "5v5": 5}
OT_ROOM = {"3v3": 1.0, "4v4": 0.45, "5v5": 0.0}


def simulate_game(home: Team, away: Team, env: dict, skill: Skill, seed: int, events=True, playoff=False,
                  overtime: dict | None = None, big: bool = False) -> GameResult:
    """overtime (regular season only): {"format": "3v3"|"4v4"|"5v5"|"none", "minutes": 5, "shootout": bool}.
    "none", or no goal and no shootout, ends in a tie (res.tie). big (v37): a rivalry game, where the hidden big-games
    attribute counts as it does in the playoffs (centred on the league, so it moves no totals)."""
    ot_rules = dict(OT_DEFAULT, **(overtime or {}))
    ot_n = OT_SKATERS.get(ot_rules["format"], 3)
    room = OT_ROOM.get(ot_rules["format"], 1.0)
    ot_att = 1 + (skill.ot_att - 1) * room
    ot_shm = 1 + (skill.ot_sh - 1) * room
    ot_len = int(ot_rules.get("minutes") or 0) * 60
    tac = [home.tac, away.tac]
    form = [getattr(home, "form", 1.0) * getattr(home, "home_form", 1.0), getattr(away, "form", 1.0)]
    one = lambda i, k: (tac[i].get(k, 1.0) if tac[i] else 1.0)
    cnt = [dict(att=1.0, qual=1.0, pp_att=1.0, pp_qual=1.0), dict(att=1.0, qual=1.0, pp_att=1.0, pp_qual=1.0)]
    if tac[0] and tac[1] and tac[0].get("settings") and tac[1].get("settings"):
        from ..game.tactics import counters      # v33: some choices beat others, per game
        cnt = [counters(tac[0]["settings"], tac[1]["settings"]), counters(tac[1]["settings"], tac[0]["settings"])]
        nrm = tac[0].get("cnt_norm") or {}
        cnt = [{k: v * nrm.get(k, 1.0) for k, v in c.items()} for c in cnt]
    # multipliers by strength state: [team][state] -> (attempts, quality)
    tmul = [{"ev": (one(i, "att") * one(1 - i, "allow_att") * cnt[i]["att"], one(i, "qual") * one(1 - i, "allow_qual") * cnt[i]["qual"]),
             "pp": (one(i, "pp_att") * one(1 - i, "pk_allow_att") * cnt[i]["pp_att"], one(i, "pp_qual") * one(1 - i, "pk_allow_qual") * cnt[i]["pp_qual"]),
             "sh": (one(i, "sh_att"), 1.0)} for i in (0, 1)]
    ice_f = [ICE_F.get(_pref(t, "ice_time", "balanced"), F_WEIGHTS["ev"]) for t in (home, away)]
    ice_d = [ICE_D.get(_pref(t, "ice_time", "balanced"), D_WEIGHTS["ev"]) for t in (home, away)]
    pull1 = [PULL.get(_pref(t, "pull_down1", "2:00"), 120) for t in (home, away)]
    pull2 = [PULL.get(_pref(t, "pull_down2", "1:00"), 60) for t in (home, away)]
    hook = [HOOK.get(_pref(t, "goalie_hook", "after 4 goals"), 4) for t in (home, away)]
    match = _pref(home, "line_matching", "off")         # the home side has the last change
    rng = random.Random(seed)
    res = GameResult()
    # v35: tonight's form (hidden consistency): a shift on each skater's offence for this game, mean zero
    fr = random.Random(seed ^ 0x5EED)
    night = {p.pid: fr.gauss(0.0, p.cons_sd) for t in (home, away) for p in t.skaters if p.cons_sd}
    G = lambda p: p.gen + night.get(p.pid, 0.0)
    teams = (home, away)
    goalie = [t.goalies[0] if (len(t.goalies) < 2 or getattr(t, "force_starter", False) or rng.random() < 0.82) else t.goalies[1]
              for t in teams]
    box = [[], []]     # penalty boxes: [player, seconds_left]
    pulled = [False, False]
    ga_starter, hooked = [0, 0], [False, False]
    chem_unit = lambda ti, unit: _mean(teams[ti].chem.get(frozenset((a.pid, b.pid)), 0.0)
                                       for k, a in enumerate(unit) for b in unit[k + 1:]) if teams[ti].chem else 0.0
    seq_clock = [0]
    OPP = {"pp": "sh", "sh": "pp"}

    def rm(unit, s, key):                       # v55: tactical roles on the ice (1.0 when nobody has one)
        m = 1.0
        for p in unit:
            if p.rfx:
                d = p.rfx.get(s)
                if d:
                    m *= d.get(key, 1.0)
        return m
    protect = [any(p.protect for p in t.skaters) for t in teams]

    def st(p, ti):
        return res.stats.setdefault(p.pid, dict(team=ti, toi=0, g=0, a=0, sog=0, att=0, pim=0, sa=0, saves=0))

    def emit(period, clock, typ, ti, p=None, opp=None, xg=None, detail=None):
        if events:
            res.events.append((period, clock, typ, ti, p.pid if p else None, opp.pid if opp else None,
                               None if xg is None else round(xg, 4), detail))

    def strength(i, j):
        ni, nj = 5 - len(box[i]), 5 - len(box[j])
        ni, nj = max(3, ni), max(3, nj)
        return ni, nj

    def on_ice(ti, state, ni, force_li=None):
        t = teams[ti]
        units = t.pp if state == "pp" else t.pk if state == "sh" else None
        if units:                                   # the user's special-teams units: first unit 65% of the time
            unit = list(units[0] if len(units) == 1 or rng.random() < 0.65 else units[1])
            boxed = {b[0].pid for b in box[ti]}
            unit = [p for p in unit if p.pid not in boxed]
            while len(unit) > ni:
                unit.pop(rng.randrange(len(unit)))
            ids = {p.pid for p in unit} | boxed
            for p in t.lines[0] + t.pairs[0] + t.lines[1] + t.pairs[1]:   # top up a unit missing someone
                if len(unit) >= ni:
                    break
                if p.pid not in ids:
                    unit.append(p)
                    ids.add(p.pid)
            return unit
        li = force_li if force_li is not None else rng.choices(range(4), weights=ice_f[ti] if state == "ev" else F_WEIGHTS[state])[0]
        di = rng.choices(range(3), weights=ice_d[ti] if state == "ev" else D_WEIGHTS[state])[0]
        last_li[ti] = li
        unit = t.lines[li] + t.pairs[di]
        boxed = {b[0].pid for b in box[ti]}
        unit = [p for p in unit if p.pid not in boxed]
        while len(unit) > ni:
            unit.pop(rng.randrange(len(unit)) if len(unit) <= 3 else 2)  # drop a forward first
        return unit

    def pick_shooter(unit, d_share, state=None):
        ds = [p for p in unit if p.pos == "D"]
        fs = [p for p in unit if p.pos != "D"]
        grp = ds if (ds and (not fs or rng.random() < d_share)) else fs
        return rng.choices(grp, weights=[math.exp(skill.shot_pick * G(p)) * p.shoot_w * ((p.rfx.get(state) or {}).get("shoot", 1.0) if p.rfx else 1.0)
                                         for p in grp])[0]

    def aw(p):
        return math.exp(skill.assist_pick * p.pas) * (skill.d_assist if p.pos == "D" else 1.0) * p.assist_w

    def score(ti, shooter, unit, period, clock, xg, state, empty=False):
        oi = 1 - ti
        res.goals[ti] += 1
        res.team[ti]["en_goals" if empty else {"ev": "ev_goals", "pp": "pp_goals", "sh": "sh_goals"}[state]] += 1
        st(shooter, ti)["g"] += 1
        helpers = [p for p in unit if p.pid != shooter.pid]
        a1 = a2 = None
        if helpers and rng.random() < env["game"]["primary_assists_per_goal"]:
            a1 = rng.choices(helpers, weights=[aw(p) for p in helpers])[0]
            st(a1, ti)["a"] += 1
        rest = [p for p in helpers if a1 is None or p.pid != a1.pid]
        if rest and rng.random() < env["game"]["secondary_assists_per_goal"]:
            a2 = rng.choices(rest, weights=[aw(p) for p in rest])[0]
            st(a2, ti)["a"] += 1
        emit(period, clock, "goal", ti, shooter, goalie[oi] if not empty else None, xg,
             "A:" + ",".join(str(p.pid) for p in (a1, a2) if p) + (";EN" if empty else ""))
        if state == "pp" and not empty and box[oi]:
            box[oi].pop(0)   # a power-play goal ends the oldest minor
        if not empty and not hooked[oi] and period <= 3:      # v33: pull a struggling starter (club preference)
            ga_starter[oi] += 1
            t = teams[oi]
            if ga_starter[oi] >= hook[oi] and len(t.goalies) >= 2 and (period < 3 or clock < 900):
                hooked[oi] = True
                goalie[oi] = next(g for g in t.goalies if g.pid != goalie[oi].pid)
                emit(period, clock, "goalie", oi, goalie[oi], None, None, "goalie change")

    def attempt(ti, unit, opp_unit, state, period, clock, rebound=False, sh_mult=1.0, ot=False, top=False):
        oi = 1 - ti
        e = env[state]
        ost = OPP.get(state, "ev")
        shooter = pick_shooter(unit, e["d_attempt_share"], state)
        g = goalie[oi]
        base = e["rebound_sh_pct"] if rebound else e["sh_pct_regular"]
        # defencemen shoot from the point: a third of the attempts but about a sixth of the goals. Forwards get the
        # difference back, so the situation's goals per attempt stays where the env put it.
        ds, dgf = e["d_attempt_share"], e.get("d_goal_factor", skill.d_finish)
        pos_mult = (dgf if shooter.pos == "D" else 1.0) / (ds * dgf + 1.0 - ds)
        fin = shooter.fin + night.get(shooter.pid, 0.0) * 0.5 + (shooter.bg if (playoff or big) else 0.0)
        p_goal = base * sh_mult * pos_mult * (1 + skill.qual * shooter.qual + skill.fin * fin) * (1 - skill.goalie * g.save) * (1 - skill.dq * _mean(p.sup for p in opp_unit))
        p_goal *= rm(unit, state, "qual") * rm(opp_unit, ost, "allow_qual") * (rm(opp_unit, "ev", "allow_qual_top") if top else 1.0)
        p_goal = max(0.01, min(0.6, p_goal))
        tm = res.team[ti]
        tm["att"] += 1
        st(shooter, ti)["att"] += 1
        evs = state == "ev" and not ot
        if evs:
            tm["att_ev"] += 1
        b = e["blocked_frac"] * (1 + skill.blk * _mean(p.blk for p in opp_unit))
        if rng.random() < max(0.02, min(0.6, b)):
            tm["blocked"] += 1
            blocker = rng.choices(opp_unit, weights=[math.exp(0.5 * p.blk) for p in opp_unit])[0] if opp_unit else None
            emit(period, clock, "block", ti, shooter, blocker)
            return
        if evs:
            tm["xg_ev"] += (1 - e["missed_frac"]) * p_goal
        if rng.random() < e["missed_frac"]:
            tm["missed"] += 1
            emit(period, clock, "miss", ti, shooter)
            return
        tm["sog"] += 1
        st(shooter, ti)["sog"] += 1
        st(g, oi)["sa"] += 1
        if rng.random() < p_goal:
            score(ti, shooter, unit, period, clock, p_goal, state)
            return "goal"
        st(g, oi)["saves"] += 1
        emit(period, clock, "shot", ti, shooter, g, p_goal)
        p_reb = e["rebound_att_per_sog"] / (1 - e["sh_pct"]) * max(0.2, 1 - skill.reb * g.reb)
        p_reb *= rm(unit, state, "reb") * rm(opp_unit, ost, "allow_reb")
        if not rebound and rng.random() < p_reb:
            return attempt(ti, unit, opp_unit, state, period, clock, True, sh_mult, ot, top)

    last_li = [None, None]

    def run_step(period, clock, ot=False):
        units, state = {}, {}
        for i in (1, 0):                         # the visitors change first; the home side answers (line matching)
            j = 1 - i
            ni, nj = strength(i, j)
            state[i] = "ev" if ni == nj else ("pp" if ni > nj else "sh")
            force = None
            if i == 0 and not ot and state[0] == "ev" and match != "off" and last_li[1] == 0 and rng.random() < 0.6:
                force = 2 if match.startswith("checking") else 0
            units[i] = on_ice(i, state[i], ot_n if ot else ni, force)
        if ot and ot_n == 3:
            units = {i: (list(teams[i].ot3[0] if len(teams[i].ot3) == 1 or rng.random() < .6 else teams[i].ot3[1]) if teams[i].ot3 else
                         [teams[i].lines[0][0], teams[i].lines[0][1], teams[i].pairs[0][0]] if rng.random() < .6
                         else [teams[i].lines[1][0], teams[i].lines[1][1], teams[i].pairs[1][0]]) for i in (0, 1)}
        elif ot and ot_n == 4:
            units = {i: (list(teams[i].ot4[0] if len(teams[i].ot4) == 1 or rng.random() < .55 else teams[i].ot4[1]) if teams[i].ot4 else
                         (lambda k: [teams[i].lines[k][0], teams[i].lines[k][1]] + teams[i].pairs[k][:2])(0 if rng.random() < .55 else 1))
                     for i in (0, 1)}
        for i in (0, 1):
            for p in units[i]:
                st(p, i)["toi"] += STEP
            st(goalie[i], i)["toi"] += STEP
            if state[i] == "pp":
                res.team[i]["pp_sec"] += STEP
        scored = False
        for i in (0, 1):
            j = 1 - i
            ni, nj = strength(i, j)
            s = state[i]
            e = env[s]
            lam = e["att60"] * (1 - e["rebound_frac_of_attempts"]) * STEP / 3600.0 * skill.att_scale * (skill.pp_scale if s == "pp" else 1.0)
            gen_i, sup_j = _mean(G(p) for p in units[i]), _mean(p.sup for p in units[j])
            if ot and ot_n < 5:   # three-skater units are far more spread than five-man units the constants were fitted to:
                #      lean on the whole roster so a good top line helps, but does not decide every overtime
                gen_i = 0.5 * gen_i + 0.5 * _mean(p.gen for p in teams[i].skaters)
                sup_j = 0.5 * sup_j + 0.5 * _mean(p.sup for p in teams[j].skaters)
            mult = 1 + skill.att * gen_i - skill.sup * sup_j
            mult *= (1 + skill.home) if i == 0 else (1 - skill.home)
            if not ot:
                mult *= 1 + skill.score_effect * max(-2, min(2, res.goals[j] - res.goals[i]))
            if s == "pp" and ni - nj >= 2:
                mult *= 1.4
            if s == "sh" and nj - ni >= 2:
                mult *= 0.7
            if pulled[i]:
                mult *= skill.en_att
            if ot:
                mult *= ot_att
            else:                             # tactics (hs/game/tactics.py) by strength state, with the game's counters
                mult *= tmul[i][s][0]
                if s == "ev" and (teams[i].chem or teams[j].chem):   # line chemistry, one unit against the other
                    mult *= 1 + skill.chem * (chem_unit(i, units[i]) - chem_unit(j, units[j]))
            mult *= form[i]
            sj = state[j] if not ot else "ev"
            mult *= rm(units[i], s if not ot else "ev", "att") * rm(units[j], sj, "allow")
            top = s == "ev" and not ot and last_li[i] == 0
            if top:
                mult *= rm(units[j], "ev", "allow_top")
            if pulled[j]:
                lam = 0.0   # an empty net is handled by the empty-net goal process below
            for _ in range(_poisson(rng, max(0.0, lam * max(0.3, mult)))):
                c = min(clock + rng.randrange(STEP), 1199 if not ot else ot_len - 1)
                shm = ot_shm if ot else tmul[i][s][1]
                r = attempt(i, units[i], units[j], s, period, c, sh_mult=shm, ot=ot, top=top)
                if r == "goal":
                    scored = True
                    if ot:
                        res.team[i]["ot_goals"] += 1
                        return True
        # empty-net goals for the leading team while the other has pulled its goalie
        for i in (0, 1):
            j = 1 - i
            if pulled[j] and res.goals[i] > res.goals[j]:
                for _ in range(_poisson(rng, skill.en_goal_per_min * STEP / 60.0)):
                    shooter = pick_shooter(units[i], 0.3)
                    score(i, shooter, units[i], period, clock + rng.randrange(STEP), None, "ev", empty=True)
        for i in (0, 1):   # serve time first, so a new minor is not shortened in the step it is called
            for b in box[i]:
                b[1] -= STEP
            box[i] = [b for b in box[i] if b[1] > 0]
        # penalties
        for i in (0, 1):
            if ot or len(box[i]) >= 2:
                continue
            j = 1 - i
            rate = env["game"]["penalties_per_game_both_teams"] / 2 / 3600.0 * STEP / (1 + skill.offset_prob) * skill.pen_scale
            rate *= max(0.2, 1 - skill.pen * _mean(p.comp for p in units[i]))
            if tac[i]:
                rate *= tac[i]["pen"]
            draw = rm(units[j], state[j], "draw")                    # v55: agitators and enforcers
            if protect[i]:
                draw = 1 + (draw - 1) * 0.5
            rate *= rm(units[i], state[i], "pen") * draw * getattr(teams[i], "role_pen", 1.0)
            if rng.random() < rate:
                off = rng.choices(units[i], weights=[math.exp(-0.6 * p.comp) * p.temper for p in units[i]])[0]
                box[i].append([off, 120])
                res.team[i]["pim"] += 2
                res.team[i]["pens"] += 1
                st(off, i)["pim"] += 2
                emit(period, clock, "penalty", i, off, None, None, "minor 2:00")
                if rng.random() < skill.offset_prob and len(box[j]) < 2:
                    other = rng.choice(units[j])
                    box[j].append([other, 120])
                    res.team[j]["pim"] += 2
                    res.team[j]["pens"] += 1
                    st(other, j)["pim"] += 2
                    emit(period, clock, "penalty", j, other, None, None, "minor 2:00 (offsetting)")
        return scored

    for step in range(3600 // STEP):
        period, clock = step * STEP // 1200 + 1, step * STEP % 1200
        pulled[0] = pulled[1] = False
        if period == 3:
            left = 1200 - clock
            for i in (0, 1):                     # v33: when to pull the goalie is a club preference (2:00 and 1:00 by default)
                diff = res.goals[1 - i] - res.goals[i]
                pulled[i] = (diff == 1 and left <= pull1[i]) or (diff == 2 and left <= pull2[i])
        run_step(period, clock)
    if res.goals[0] == res.goals[1]:
        if not playoff and (ot_rules["format"] == "none" or not ot_rules.get("minutes")):
            if ot_rules.get("shootout"):
                res.went_to_ot = True        # straight to a shootout (a custom league might want this)
            else:
                res.tie = True
                return res
        res.went_to_ot = True
        pulled[0] = pulled[1] = False
        if playoff:   # full-strength 20-minute sudden-death periods until someone scores; penalties stay live
            per = 4
            while res.goals[0] == res.goals[1] and per < 12:
                for step in range(1200 // STEP):
                    run_step(per, step * STEP)
                    if res.goals[0] != res.goals[1]:
                        break
                per += 1
            if res.goals[0] == res.goals[1]:
                res.goals[rng.randrange(2)] += 1
            return res
        box[0], box[1] = [], []
        for step in range(ot_len // STEP if ot_rules["format"] != "none" else 0):
            if run_step(4, step * STEP, ot=True):
                break
        if res.goals[0] == res.goals[1] and not ot_rules.get("shootout"):
            res.tie = True
            return res
        if res.goals[0] == res.goals[1]:
            res.shootout = True
            sc = [0, 0]
            shooters = [sorted(t.skaters, key=lambda p: -(p.fin + p.qual))[:3] for t in teams]
            rnd = 0
            while True:
                for i in (0, 1):
                    sh = shooters[i][rnd % 3]
                    p = skill.shootout_pct * (1 + 0.5 * (skill.qual * sh.qual + skill.fin * sh.fin)) * (1 - skill.goalie * goalie[1 - i].save)
                    ok = rng.random() < max(0.05, min(0.8, p))
                    sc[i] += ok
                    emit(5, rnd, "so_goal" if ok else "so_miss", i, sh, goalie[1 - i])
                rnd += 1
                if (rnd >= 3 and sc[0] != sc[1]) or rnd >= 20:
                    break
            if sc[0] == sc[1]:
                sc[rng.randrange(2)] += 1
            res.goals[0 if sc[0] > sc[1] else 1] += 1
    return res


def skill_for(rules=None, **overrides):
    """The engine constants for a league: the defaults, then rules.json "engine" (a pack whose ratings came from
    another source keeps the constants it was tuned with), then explicit overrides."""
    from dataclasses import replace
    eng = dict((rules or {}).get("engine") or {})
    eng.update(overrides)
    return replace(Skill(), **{k: float(v) for k, v in eng.items() if k in Skill.__dataclass_fields__})
