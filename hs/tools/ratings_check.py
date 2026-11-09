"""How well do a pack's ratings rank players? (the v25 recalibration's yardstick; docs/RATINGS_MODEL.md)

    python -m hs.tools.ratings_check <pack_dir> <moneypuck_dir> --season 2025 [--value flat|weighted] [--top 20]

For every skater in the pack with 20+ games in the given MoneyPuck season (all situations), compares the pack's
single value number with what he did that season: ice time a game (how much his coach trusted him), points a game,
and MoneyPuck's game score a game. Spearman rank correlations, forwards and defencemen separately, plus the spread
of each attribute (sd in rating points; the model's target is 3) and the top forwards by value. Use a pack built from
seasons before the one checked (e.g. ratings from 2024, outcomes 2025) for an out-of-sample test.
"""
from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = _rank(a), _rank(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 0.0


def outcomes(mp: Path, season: int):
    out = {}
    with open(mp / f"skaters_{season}.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["situation"] != "all":
                continue
            gp = float(r["games_played"] or 0)
            if gp < 20:
                continue
            out[int(r["playerId"])] = dict(name=r["name"], toi=float(r["icetime"]) / gp / 60,
                                           pts=float(r["I_F_points"]) / gp, gs=float(r["gameScore"]) / gp)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack")
    ap.add_argument("mp")
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--value", choices=["flat", "weighted"], default="weighted")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args(argv)
    from ..game.roster import SKATER_KEYS, value_from_attrs
    pack = Path(a.pack)
    pos = {}
    with open(pack / "players.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            pos[int(r["player_id"])] = r["position"]
    attrs = {}
    with open(pack / "attributes.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            attrs[int(r["player_id"])] = {k: (float(v) if v not in ("", None) else None) for k, v in r.items()
                                         if k != "player_id"}
    out = outcomes(Path(a.mp), a.season)

    def value(pid):
        at = attrs[pid]
        if a.value == "flat":
            return (statistics.fmean(at.get(k) or 10 for k in SKATER_KEYS) - 1) / 19 * 100
        return value_from_attrs(at, pos[pid])

    print(f"value: {a.value}; outcomes: {a.season}")
    for grp, posset in (("F", {"C", "LW", "RW"}), ("D", {"D"})):
        ids = [p for p in out if p in attrs and pos.get(p) in posset]
        v = [value(p) for p in ids]
        print(f"{grp}: n={len(ids)}  rank corr with  ice time {spearman(v, [out[p]['toi'] for p in ids]):.3f}  "
              f"points {spearman(v, [out[p]['pts'] for p in ids]):.3f}  game score "
              f"{spearman(v, [out[p]['gs'] for p in ids]):.3f}")
    keys = sorted({k for at in attrs.values() for k in at})
    sk = [p for p in attrs if pos.get(p) != "G"]
    print("attribute sd (skaters): " + ", ".join(
        f"{k} {statistics.pstdev([attrs[p][k] for p in sk if attrs[p].get(k) is not None]):.2f}"
        for k in ("offensive_awareness", "passing", "puck_control", "shot_accuracy", "positioning",
                  "defensive_awareness", "stick_checking", "hitting") if k in keys))
    fwd = sorted((p for p in attrs if pos.get(p) in ("C", "LW", "RW")), key=lambda p: -value(p))[:a.top]
    print(f"top {a.top} forwards by value:")
    for p in fwd:
        o = out.get(p)
        print(f"  {value(p):6.1f}  {(o['name'] if o else p)!s:<24}" + (f" {o['pts']:.2f} pts/gp, {o['toi']:.1f} toi"
                                                                      if o else ""))


if __name__ == "__main__":
    main()
