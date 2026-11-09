"""League rules: season dates, schedule format, points, tiebreakers and playoff format.

Rules live in the pack as `rules.json` (all optional; see docs/LEAGUES_AND_SCHEDULES.md). `check_rules` returns a
list of human-readable problems so a custom league fails early with a clear message.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

DEFAULTS = {
    "name": "Custom league",
    "season": {"start": None, "end": None, "breaks": []},
    "schedule": {"games_per_team": 82,
                 "same_division": {"games": 4, "reduced_games": 3, "reduced_opponents_per_team": 2},
                 "same_conference": {"games": 3}, "other_conference": {"games": 2}},
    "points": {"win": 2, "ot_loss": 1, "loss": 0, "tie": 1},
    "overtime": {"format": "3v3", "minutes": 5, "shootout": True},
    "tiebreakers": ["points_pct", "regulation_wins", "regulation_overtime_wins", "wins",
                    "head_to_head_points", "goal_diff", "goals_for"],
    "playoffs": {"format": "division_wildcard", "per_division": 3, "wildcards_per_conference": 2,
                 "series_length": 7, "home_pattern": [1, 1, 0, 0, 1, 0, 1]},
}
TIEBREAKERS = {"points_pct", "points", "regulation_wins", "regulation_overtime_wins", "wins",
               "head_to_head_points", "goal_diff", "goals_for"}
PLAYOFF_FORMATS = {"division_wildcard", "conference_top_n"}
OT_FORMATS = {"none", "3v3", "4v4", "5v5"}


def merged(rules: dict | None) -> dict:
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (rules or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load_rules(pack_dir) -> dict | None:
    p = Path(pack_dir) / "rules.json"
    return merged(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def structure(teams) -> dict:
    """teams: iterable of dicts with team_id, conference, division -> {conference: {division: [team_ids]}}"""
    out = defaultdict(lambda: defaultdict(list))
    for t in teams:
        out[t["conference"]][t["division"]].append(t["team_id"])
    return {c: dict(d) for c, d in out.items()}


def opponent_counts(teams, rules) -> dict:
    """{(a, b): games} for a < b, from the structure and schedule rules. Raises ValueError for impossible rules."""
    sch = rules["schedule"]
    info = {t["team_id"]: (t["conference"], t["division"]) for t in teams}
    ids = sorted(info)
    counts = {}
    divs = defaultdict(list)
    for t in ids:
        divs[info[t]].append(t)
    reduced = set()
    k = sch["same_division"].get("reduced_opponents_per_team", 0)
    for members in divs.values():
        n = len(members)
        if k and n > 1:
            if k > n - 1:
                raise ValueError(f"division of {n} cannot give each team {k} reduced opponents")
            if k % 2 == 1 and n % 2 == 1:
                raise ValueError(f"{k} reduced opponents per team is impossible in a division of {n}")
            for step in range(1, k // 2 + 1):          # circulant graph: each team k reduced opponents
                for i in range(n):
                    reduced.add(tuple(sorted((members[i], members[(i + step) % n]))))
            if k % 2 == 1:
                for i in range(n // 2):
                    reduced.add(tuple(sorted((members[i], members[i + n // 2]))))
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if info[a] == info[b]:
                g = sch["same_division"]["reduced_games"] if (a, b) in reduced else sch["same_division"]["games"]
            elif info[a][0] == info[b][0]:
                g = sch["same_conference"]["games"]
            else:
                g = sch["other_conference"]["games"]
            counts[(a, b)] = g
    sizes = {len(m) for m in divs.values()}
    if len(sizes) > 1 or sch.get("balance"):              # v45: uneven divisions (an expansion club): even the totals out
        _balance(counts, ids, info, sch["games_per_team"])
    return counts


def _balance(counts, ids, info, want):
    """Adjust pair counts so every team plays `want` games: drop games between clubs with too many (other conference
    first), add games between clubs with too few (same division first), else move one game a-b to b-d."""
    if len(ids) * want % 2:
        return
    tot = defaultdict(int)
    for (a, b), g in counts.items():
        tot[a] += g
        tot[b] += g
    kind = lambda a, b: 2 if info[a] == info[b] else 1 if info[a][0] == info[b][0] else 0
    key = lambda a, b: (a, b) if a < b else (b, a)
    for _ in range(20 * len(ids) * len(ids)):
        over = sorted((t for t in ids if tot[t] > want), key=lambda t: want - tot[t])
        under = sorted((t for t in ids if tot[t] < want), key=lambda t: tot[t] - want)
        if not over and not under:
            return
        if len(over) >= 2:
            a = over[0]
            bs = [b for b in over[1:] if counts[key(a, b)] > 1]
            if bs:
                b = min(bs, key=lambda b: (kind(a, b), -counts[key(a, b)], b))
                counts[key(a, b)] -= 1
                tot[a] -= 1
                tot[b] -= 1
                continue
        if len(under) >= 2:
            a = under[0]
            b = min(under[1:], key=lambda b: (-kind(a, b), counts[key(a, b)], b))
            counts[key(a, b)] += 1
            tot[a] += 1
            tot[b] += 1
            continue
        if over and under:
            a, d = over[0], under[0]
            bs = [b for b in ids if b not in (a, d) and counts[key(a, b)] > 1]
            if not bs:
                return
            b = min(bs, key=lambda b: (kind(a, b), -counts[key(a, b)], counts[key(b, d)], b))
            counts[key(a, b)] -= 1
            counts[key(b, d)] += 1
            tot[a] -= 1
            tot[d] += 1
            continue
        return


def check_rules(rules: dict, teams: list) -> list:
    """Problems with these rules for this set of teams (empty list = fine)."""
    problems = []
    if not all(t.get("conference") and t.get("division") for t in teams):
        problems.append("every team needs a conference and division in teams.csv when rules.json is present")
        return problems
    try:
        counts = opponent_counts(teams, rules)
    except ValueError as e:
        return [str(e)]
    per_team = defaultdict(int)
    for (a, b), g in counts.items():
        per_team[a] += g
        per_team[b] += g
    want = rules["schedule"]["games_per_team"]
    bad = sorted({v for v in per_team.values() if v != want})
    if bad:
        problems.append(f"schedule rules give teams {bad} games, but games_per_team is {want}")
    ot = rules.get("overtime") or {}
    if ot.get("format", "3v3") not in OT_FORMATS:
        problems.append(f"unknown overtime format '{ot.get('format')}' (use {sorted(OT_FORMATS)})")
    for tb in rules["tiebreakers"]:
        if tb not in TIEBREAKERS:
            problems.append(f"unknown tiebreaker '{tb}' (use {sorted(TIEBREAKERS)})")
    po = rules["playoffs"]
    if po["format"] not in PLAYOFF_FORMATS:
        problems.append(f"unknown playoff format '{po['format']}' (use {sorted(PLAYOFF_FORMATS)})")
    if len(po["home_pattern"]) < po["series_length"]:
        problems.append("playoffs.home_pattern must have at least series_length entries")
    if po["series_length"] % 2 == 0:
        problems.append("playoffs.series_length must be odd")
    st = structure(teams)
    if po["format"] == "division_wildcard":
        if len(st) != 2 or any(len(d) != 2 for d in st.values()):
            problems.append("division_wildcard playoffs need exactly 2 conferences of 2 divisions each")
        elif po["per_division"] * 2 + po["wildcards_per_conference"] != 8:
            problems.append("division_wildcard needs per_division*2 + wildcards_per_conference == 8 per conference")
    else:
        n = po.get("teams_per_conference", 8)
        if len(st) != 2 or (n & (n - 1)) or n < 2:
            problems.append("conference_top_n needs 2 conferences and teams_per_conference a power of two")
    s = rules["season"]
    if s.get("start") and s.get("end") and s["start"] >= s["end"]:
        problems.append("season.start must be before season.end")
    for b in s.get("breaks") or []:
        if not (isinstance(b, dict) and b.get("start") and b.get("end") and b["start"] <= b["end"]):
            problems.append(f'season.breaks entries must look like {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}, got {b!r}')
    return problems
