"""Draft lab: generate draft classes, draft them through the scouting engine, play out every career, and compare
the outcomes by round with the NHL's historical rates. No database; used to calibrate hs.worldgen and
hs.game.scouting.

    python -m hs.tools.draft_lab [--classes 20] [--seed 1]

A season counts as an NHL season at overall >= REGULAR (72 games) and as a call-up at >= SPOT (10 games); a peak
at >= ELITE is a star (about the NHL's top 10%). These thresholds come from the 2025-26 rosters: NHL skater
overall mean 10.5, 25th percentile ~10.1, 90th ~11.45.
"""
from __future__ import annotations

import argparse
import random
import statistics as st

from ..game import scouting as S
from ..leaguedata.world_2025_26 import NAMES
from ..worldgen import (CLASS_GOALIES, CLASS_NATIONALITY, CLASS_SKATERS, gen_prospect, overall_of, pick_nationality,
                        yearly_change)

REGULAR, SPOT, ELITE = 10.25, 9.45, 11.45
REAL = {  # round: (1+ games, 100+, 500+, elite share) from the brief
    1: (89.3, 68.8, 41.4, None), 2: (67.4, 38.2, 16.6, 4.0), 3: (51.5, 28.1, 10.0, 1.75), 4: (40.9, 21.2, 8.1, 1.0),
    5: (33.0, 14.9, 4.8, 0.5), 6: (29.0, 10.0, 2.0, 0.5), 7: (25.0, 7.0, 0.9, 0.5)}
REAL_R1_SPLIT = {"1-14 500+": "50%+", "15-32 500+": "18-30%", "1-15 elite": "25-35%", "16-32 elite": "5-10%"}


def make_class(rng, year):
    out = []
    for i in range(CLASS_SKATERS + CLASS_GOALIES):
        goalie = i >= CLASS_SKATERS
        pos = "G" if goalie else rng.choices(["C", "LW", "RW", "D"], [4, 4, 4, 6])[0]
        nat = pick_nationality(rng, CLASS_NATIONALITY)
        pl, at, prof, info = gen_prospect(rng, NAMES, nat, pos, 17, year)
        cur = overall_of(at, pos)
        cur += yearly_change(17, cur, prof, rng)               # one more season before the draft
        out.append(dict(i=i, pos=pos, goalie=goalie, nat=nat, height=pl["height_cm"], prof=prof, info=info,
                        cur18=cur))
    return out


def clubs(rng, n=32):
    out = []
    for t in range(n):
        style = rng.choices([s for s, _ in S.STYLE_MIX], [w for _, w in S.STYLE_MIX])[0]
        q = rng.gauss(10.5, 1.2)
        out.append(dict(t=t, style=style, sd=max(0.25, min(1.0, 0.75 - 0.035 * (q - 10)))))
    return out


def draft(rng, cls, teams, rounds=7):
    common = {p["i"]: rng.gauss(0, 1) for p in cls}
    proj = {}
    for c in teams:
        for p in cls:
            khl = p["info"]["khl_years"]
            proj[c["t"], p["i"]] = S.project(p["cur18"], 18, p["goalie"], p["info"]["exposure"], common[p["i"]],
                                             rng.gauss(0, 1), c["sd"], c["style"], p["height"], khl)
    taken = {}
    picked = {c["t"]: {"F": 0, "D": 0, "G": 0} for c in teams}
    target = {"F": 4.0, "D": 2.5, "G": 0.7}
    order = list(teams)
    rng.shuffle(order)
    no = 0
    for rnd in range(1, rounds + 1):
        for c in order:
            no += 1
            best, bs = None, None
            for p in cls:
                if p["i"] in taken:
                    continue
                g = "G" if p["goalie"] else "D" if p["pos"] == "D" else "F"
                need = max(0.0, (target[g] - picked[c["t"]][g]) / target[g])
                s = S.pick_score(proj[c["t"], p["i"]], p["cur18"], rnd, need, c["style"], p["goalie"], 18)
                if bs is None or s > bs:
                    best, bs = p, s
            taken[best["i"]] = (no, rnd, c["style"])
            g = "G" if best["goalie"] else "D" if best["pos"] == "D" else "F"
            picked[c["t"]][g] += 1
    return taken


def career(rng, p):
    cur, games, peak, prof = p["cur18"], 0, p["cur18"], p["prof"]
    first = None
    for age in range(18, 39):
        if age > 18:
            cur += yearly_change(age - 1, cur, prof, rng)
        peak = max(peak, cur)
        g = 72 if cur >= REGULAR else 10 if cur >= SPOT else 0
        if g and first is None:
            first = age
        games += g
        if age >= 31 and cur < SPOT:
            break
    return games, peak, first


def run(n_classes=20, seed=1, verbose=True):
    rng = random.Random(seed)
    rows = []
    for k in range(n_classes):
        cls = make_class(rng, 2026 + k)
        teams = clubs(rng)
        taken = draft(rng, cls, teams)
        for p in cls:
            games, peak, first = career(rng, p)
            no, rnd, style = taken.get(p["i"], (None, 8, None))
            rows.append(dict(p, games=games, peak=peak, first=first, no=no, rnd=rnd, style=style, cls=k))
    if verbose:
        report(rows, n_classes)
    return rows


def pct(xs, f):
    return 100.0 * sum(1 for x in xs if f(x)) / len(xs) if xs else 0.0


def report(rows, n):
    print(f"{n} classes, {len(rows) // n} prospects each\n")
    print("round   1+ gm (real)   100+ (real)   500+ (real)   elite (real)")
    for r in range(1, 9):
        xs = [x for x in rows if x["rnd"] == r]
        real = REAL.get(r, (None,) * 4)
        lab = "undrafted" if r == 8 else f"R{r}"
        f = lambda v: f"{v:5.1f}" if v is not None else "  -  "
        print(f"{lab:<9}{pct(xs, lambda x: x['games'] > 0):5.1f} ({f(real[0])})  {pct(xs, lambda x: x['games'] >= 100):5.1f}"
              f" ({f(real[1])})  {pct(xs, lambda x: x['games'] >= 500):5.1f} ({f(real[2])})  "
              f"{pct(xs, lambda x: x['peak'] >= ELITE):5.1f} ({f(real[3])})")
    r1 = [x for x in rows if x["rnd"] == 1]
    top = [x for x in r1 if x["no"] <= 14]
    late = [x for x in r1 if x["no"] > 14]
    print(f"\npicks 1-14: 500+ {pct(top, lambda x: x['games'] >= 500):.0f}% (real 50%+), elite "
          f"{pct([x for x in r1 if x['no'] <= 15], lambda x: x['peak'] >= ELITE):.0f}% (real 25-35%)")
    print(f"picks 15-32: 500+ {pct(late, lambda x: x['games'] >= 500):.0f}% (real 18-30%), elite "
          f"{pct([x for x in r1 if x['no'] > 15], lambda x: x['peak'] >= ELITE):.0f}% (real 5-10%)")
    elite = [x for x in rows if x["peak"] >= ELITE]
    print(f"elite players per class {len(elite) / n:.1f} (real 5-8), share from round 1 "
          f"{pct(elite, lambda x: x['rnd'] == 1):.0f}% (real ~80%), from rounds 2-7 per class "
          f"{sum(1 for x in elite if 2 <= x['rnd'] <= 7) / n:.1f} (real 1-2)")
    gl = [x for x in rows if x["goalie"] and x["rnd"] <= 7]
    print(f"goalies drafted 100+ games {pct(gl, lambda x: x['games'] >= 100):.0f}% (real 21%); "
          f"goalies in round 1 per class {sum(1 for x in gl if x['rnd'] == 1) / n:.1f}")
    for r in (1, 2):
        xs = [x for x in rows if x["rnd"] == r and x["first"]]
        if xs:
            print(f"round {r}: median age at first NHL action {st.median(x['first'] for x in xs):.0f}")
    top3 = [x for x in rows if x["no"] and x["no"] <= 3]
    print(f"top-3 picks in the NHL at 18-19: {pct(top3, lambda x: x['first'] is not None and x['first'] <= 19):.0f}% "
          "(real ~100% by the year after)")
    small = [x for x in rows if not x["goalie"] and x["height"] <= 178 and x["rnd"] <= 7]
    big = [x for x in rows if not x["goalie"] and x["height"] >= 190 and x["rnd"] <= 7]
    for lab, xs in (("<=178 cm", small), (">=190 cm", big)):
        print(f"{lab}: drafted {len(xs) / n:.0f}/class, mean pick {st.mean(x['no'] for x in xs):.0f}, 100+ games "
              f"{pct(xs, lambda x: x['games'] >= 100):.0f}%")
    rus = [x for x in rows if x["info"]["khl_years"] and x["rnd"] <= 7]
    if rus:
        print(f"Russians under KHL contract: mean pick {st.mean(x['no'] for x in rus):.0f}, 100+ games "
              f"{pct(rus, lambda x: x['games'] >= 100):.0f}%")
    for style in S.STYLES:
        xs = [x for x in rows if x["style"] == style]
        if xs:
            print(f"{style:<12} picks: games per pick {st.mean(x['games'] for x in xs):.0f}, 100+ "
                  f"{pct(xs, lambda x: x['games'] >= 100):.0f}%")
    # where players were taken relative to their true talent rank in their class (positive = slid)
    by_class = {}
    for x in rows:
        by_class.setdefault(x["cls"], []).append(x)
    for xs in by_class.values():
        for k, x in enumerate(sorted(xs, key=lambda x: -x["prof"]["potential"])):
            x["true_rank"] = k + 1
    print("slide vs true talent rank (top-100 talents; positive = taken later than their talent):")
    groups = {"all": lambda x: True, "<=178 cm": lambda x: not x["goalie"] and x["height"] <= 178,
              ">=190 cm": lambda x: not x["goalie"] and x["height"] >= 190,
              "Russian, KHL contract": lambda x: x["info"]["khl_years"] > 0,
              "Swedish/Finnish": lambda x: x["info"]["exposure"] == "nordic",
              "late bloomers": lambda x: x["info"]["hidden_bloom"] > 0, "goalies": lambda x: x["goalie"]}
    for lab, f in groups.items():
        xs = [x for x in rows if x["true_rank"] <= 100 and f(x)]
        if xs:
            slide = st.mean((x["no"] or 260) - x["true_rank"] for x in xs)
            print(f"  {lab:<22} n/class {len(xs) / n:4.1f}  mean slide {slide:+5.0f} picks")
    und = [x for x in rows if x["rnd"] == 8]
    print(f"undrafted who still reach 100+ games per class {sum(1 for x in und if x['games'] >= 100) / n:.1f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    run(a.classes, a.seed)


if __name__ == "__main__":
    main()
