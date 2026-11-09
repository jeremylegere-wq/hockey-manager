# Leagues, rules and schedules (hs.league)

A league is described by two things in a pack: **structure** (each team's `conference` and `division` in `teams.csv`)
and **rules** (`rules.json`, optional, merged over the NHL-style defaults). `python -m hs.datapack` checks them, so a
custom league fails early with a plain message (for example "schedule rules give teams [80] games, but games_per_team is 82").

```bash
python -m hs.ratings.moneypuck <mp_dir> <pack> --season 2025 --structure nhl_2025_26   # real 2025-26 structure + rules
python -m hs.ingest <pack> game.db --force
python -m hs.league.season game.db env.json --seed 4        # schedule, 82 games, standings, playoffs, champion
python -m hs.league.season game.db env.json --schedule-only
```

## rules.json
```json
{
 "name": "NHL 2025-26",
 "season": {"start": "2025-10-07", "end": "2026-04-16",
            "breaks": [{"name": "Olympic break", "start": "2026-02-06", "end": "2026-02-24"}]},
 "schedule": {"games_per_team": 82,
              "same_division":    {"games": 4, "reduced_games": 3, "reduced_opponents_per_team": 2},
              "same_conference":  {"games": 3},
              "other_conference": {"games": 2}},
 "points": {"win": 2, "ot_loss": 1, "loss": 0, "tie": 1},
 "overtime": {"format": "3v3", "minutes": 5, "shootout": true},
 "era_preset": "nhl",
 "tiebreakers": ["points_pct", "regulation_wins", "regulation_overtime_wins", "wins",
                 "head_to_head_points", "goal_diff", "goals_for"],
 "playoffs": {"format": "division_wildcard", "per_division": 3, "wildcards_per_conference": 2,
              "series_length": 7, "home_pattern": [1, 1, 0, 0, 1, 0, 1]}
}
```
- **Schedule**: games per opponent class. The NHL gives 26 division + 24 same-conference + 32 other-conference = 82.
  `reduced_opponents_per_team` picks which division rivals get the lower count (a circulant pattern, so it is the
  same for every team). The pack fails validation if the totals do not equal `games_per_team`.
- **Tiebreakers**: any order of `points_pct, points, regulation_wins, regulation_overtime_wins, wins,
  head_to_head_points, goal_diff, goals_for`. Head-to-head uses games among the tied teams only.
- **Playoff formats**: `division_wildcard` (NHL: top 3 per division + 2 wildcards per conference, fixed bracket, no
  reseeding; the better division winner plays the lower wildcard) and `conference_top_n`
  (`teams_per_conference`, a power of two; fixed bracket 1vN, 4v5, 2v7, 3v6). `home_pattern` is 1 where the higher seed hosts.
  Playoff overtime is continuous 20-minute full-strength sudden death.

- **Overtime** (regular season): `format` is `3v3`, `4v4`, `5v5` or `none`; `minutes` of sudden death; `shootout`
  true or false. No goal and no shootout means a tie: a point each (`points.tie`), shown as T in the standings, the
  dashboard record and results. The defaults are the modern NHL's, and the engine gives the same results as before
  overtime became a rule.

## Rule eras (hs/league/eras.py, v19)
Rules can change by season. `"eras": [{"from": 2027, "until": 2030, "overtime": {...}, "schedule": {...}}, ...]`
merges each matching entry into that season's rules (seasons named by their start year; nested settings merge, so
an era can change one value). `"era_preset": "nhl"` adds the built-in NHL history, applied before any `eras`:

| Seasons | Regular season |
|---|---|
| to 1982-83 | no overtime; ties a point each |
| 1983-84 to 1998-99 | 5 min of 5v5 sudden death, then a tie; an overtime loss is a loss (no point) |
| 1999-2000 to 2003-04 | 5 min of 4v4, then a tie; the overtime loser keeps a point |
| 2005-06 to 2014-15 | 5 min of 4v4, then a shootout |
| 2015-16 on | 5 min of 3v3, then a shootout |
| 2026-27 on | 84 games: 4 against every division rival (28) + 3 against the other division of the conference (24) + 2 against the other conference (32) |

84 games from 2026-27 is in the 2026-30 CBA ([NHL.com](https://www.nhl.com/news/nhl-new-collective-bargaining-agreement-details));
the league said it "could allow for four matchups with each divisional rival", which is the only split that makes 84
with today's structure, but no schedule matrix had been published when this was written. The era dates are from
memory of the NHL's rule history. Schedules before 2026 keep the pack's own schedule rules (the preset changes
overtime and points there, not the number of games). An overtime loss in the 1983-99 era still shows in the OTL
column (worth 0 points), rather than being folded into L.

Overtime in the engine: 3v3 is what the overtime constants were fitted to; 4v4 gets 45% of the 3v3 boost to shots
and shooting and 5v5 none. Share of overtimes decided before the shootout or a tie (4,000 games each on the 2025-26
world): 3v3 58%, 4v4 45%, 5v5 33%. These look like their eras as far as I recall (about 60%, about 45%, about a
third), unchecked.

The NHL packs (`hs/leaguedata/nhl_2025_26.py`, the legacy 2001-02 importer in tools/) set `era_preset: nhl`, so a 2025-26 save
plays 84 games from 2026-27 and a 2001-02 legacy save has 4v4 overtime and ties. An older save can switch with the
`rules preset nhl` command (`rules` shows this season's and next season's rules; `rules preset off` turns it off):
overtime and points follow the era from the next game, the schedule length from the next season. When a new season's
rules differ from the last, the offseason report and an inbox message say so.

## How the schedule is built
1. Opponent counts from the structure; the odd-count pairs (3-game series) get their extra home game by an Euler-circuit
   orientation, so every team ends with exactly half its games at home (41/41 for the NHL structure).
2. Dates come from a pace-based greedy scheduler: each day it picks the games whose teams are furthest behind pace,
   penalising back-to-backs, long home/away runs and repeat opponents. It tries several random schedules and keeps one
   whose longest home/away run is at most 6.
3. Checks (tests): everyone plays 82, 41 at home, exact opponent counts, at most one game per team per day, no games in
   breaks. A 32-team schedule takes about 0.1 s.

## Known gaps
- Back-to-backs average ~8 per team; the real NHL has more (I recall about 12, unchecked). Arena conflicts, travel
  distance, time zones, rivalry nights and weekday shape are not modelled (weekday weights are a stylised guess).
- Tiebreaker head-to-head is simplified for ties of three or more teams.
- No in-season injuries, trades, cap or roster limits yet, so standings reflect fixed rosters.
- The playoffs have no series-level story: no rest days between series beyond two days per game.
