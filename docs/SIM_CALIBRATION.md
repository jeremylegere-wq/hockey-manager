# Game engine and calibration (hs.sim)

```bash
python -m hs.sim.env <moneypuck_dir> --season 2025 --out env.json     # real league rates by game situation
python -m hs.sim.validate game.db env.json --seasons 6                # play seasons, compare with the real league
python -m hs.sim.play game.db env.json MTL TOR --seed 5               # one game with goal log
```

## How a game works
60 minutes in 30-second segments, then 3v3 overtime and a shootout. Each segment, each team's shot-attempt rate is the
**real league rate for the strength state** (even strength, power play, short-handed) times a skill factor from the five
skaters on the ice against the opposing five. An attempt can be blocked, miss, or reach the goalie; a shot on goal scores
with the league rate adjusted for shooter quality/finishing, the goalie and the defenders. Saves can produce rebounds.
Also modelled: penalties (with occasional offsetting 4v4), power-play goals ending minors, trailing teams pressing, empty
nets, home ice. Lines come from the depth chart (last season's ice time when history exists). Same seed = same game,
and `hs.sim.loader.write_result` stores events so any game can be replayed.

## Calibration result (v25 ratings, real 2025-26 rosters, 2 seasons simulated)
| metric | sim | real |
|---|---|---|
| goals / team / game | 2.91 | 2.88 |
| shots on goal / team / game | 27.3 | 27.6 |
| shot attempts / team / game | 57.4 | 58.1 |
| save % | .893 | .896 |
| penalties / game (both teams) | 6.9 | 6.9 |
| power-play minutes / game | 8.97 | 8.98 |
| power-play goals / game | 1.20 | 1.10 |
| team spread: shot-attempt share (sd) | .035 | .032 |
| team spread: xG share (sd) | .041 | .035 |
| team spread: save % (sd) | .0096 | .0091 |
| team spread: goal difference per game (sd) | .55 | .60 |
Not derived from data (my background knowledge of the NHL, approximate): overtime games 20% (NHL roughly 22-25%),
shootout share of OT 41%, home win 53% (NHL about 54%), empty-net goals 0.18/game (about 0.2).

## v25: refitted ratings, defencemen, and per-pack engine constants
- **Skill constants.** The v25 ratings (docs/RATINGS_MODEL.md) are wider in the attributes the engine reads, so the
  same team spread needs less weight: `att` / `sup` 0.72 -> 0.60, `att_scale` 0.972 -> 0.955.
- **Defencemen shoot from the point.** They take about a third of 5v5 attempts but score about a sixth of the goals
  (MoneyPuck 2023-25: goals per attempt 0.45 of the league rate at 5v5, 0.47-0.51 on the power play). Before v25 every
  attempt scored at the same rate, so defencemen had 31% of goals and 38% of points (real: 17% and 25%), and the
  scoring list had Bouchard and Dahlin on 110-140 points. `hs.sim.env` now writes `d_goal_factor` per situation; the
  engine scales a defenceman's goal chance by it and a forward's up by the matching amount, so the situation's goals
  per attempt are unchanged (`Skill.d_finish` 0.46 stands in for older env files). Assists: a defenceman's weight is
  `Skill.d_assist` 0.45 of a forward's (real D share of assists ~0.32; the two D of a five-man unit took 0.46).
  After, on the world save: D share of goals 0.19, of assists 0.32-0.33, of points 0.27-0.28 (real 0.17 / 0.32 /
  0.25).
- **Concentration.** `shot_pick` 0.7 -> 0.55 and `assist_pick` 0.8 -> 0.65 (the wider ratings already separate the
  stars).
- **Per-pack constants.** A pack's `rules.json` may carry `"engine": {"att": ..., "sup": ..., "att_scale": ...}`;
  `hs.sim.engine.skill_for(rules)` builds the Skill from it, and the CLI, UI, season runner and validator all use it.
  The legacy 2001-02 importer (tools/) pins the pre-v25 constants (att / sup 0.72, att_scale 0.995, shot_pick 0.7, assist_pick 0.8)
  because its ratings did not change; the defenceman finishing and assist factors apply to every pack (they are real
  league rates, not rating calibration).
  `hs.sim.validate --set att=0.6 sup=0.6` overrides on the command line.

## Scoring concentration (who gets the points)
Team totals were right but the scoring leaders were too flat: with real ratings the first simulated season's top
scorer had 112 points, the 10th 83 and the 30th 69, against 138 / 96 / 78 in the real 2025-26 season. Two knobs
decide how much of a unit's offence goes to its best players: `shot_pick` (shot attempts weighted by
`exp(shot_pick * puck-carrying skill)`) and `assist_pick` (the same for passing). Raised from 0.3 / 0.4 to 0.7 / 0.8;
league goals per game are unchanged.

| season (world save) | top | 10th | 30th |
|---|---|---|---|
| real 2025-26 | 138 | 96 | 78 |
| sim 2025-26, before | 112 | 83 | 69 |
| sim 2025-26, after | 130-133 | 94 | 74-77 |
| sim 2025-26 / 2026-27, v25 ratings and engine (world save) | 149 / 154 | 96 / 97 | 83 / 79 |
| sim 2026-27 / 27-28 / 28-29, after (two runs) | 110-125 / 113-115 / 106 | 86-91 / 90-91 / 94 | 73-76 / 72-73 / 74 |

The top scorer still drifts down over later seasons (recent real seasons' leaders: 110-153) because today's stars
age and the generated stars who replace them are a little short of the top end; the 10th and 30th hold.

## What the skill constants mean (hs.sim.engine.Skill)
`att` and `sup` are large (0.60 per standard deviation; 0.72 before v25) because player ratings are shrunk estimates and a five-skater
average is narrower still: with real rosters, team ratings differ only a little, yet real teams differ in shot share by
about 3 points. Treat them as **calibration constants fitted to league parity**, not as the effect of one player. They
probably overstate how much a single player moves results, because team style and coaching also create real spread.
Team systems (docs/TACTICS.md, v25) now add a style factor on top; they are normalised to the league mean, so these
constants did not need retuning for them.

Ratings are read relative to the league's own average at load time (`centre_on_league`), so a custom league of mostly
15s plays like a league of average players. **League parity matters**: if a custom pack's teams differ much more in
rating than real teams do, results get lopsided. `hs.sim.validate` prints the team spreads for any pack; aim for a
shot-share sd near .03. The example pack was tuned to that.

## Known gaps
- Overtime rate runs a little low; 3v3 and shootout settings are guesses (no OT-specific data used).
- xG-share spread runs ~20% high; goal-difference spread ~5% low.
- No faceoffs, line changes on the fly, injuries in-game, goalie fatigue or pulling for delayed penalties.
- Skating, endurance and the mental attributes do nothing yet because the ratings pipeline has no data for them.
- Calibrated to the 2025-26 environment; other eras need `hs.sim.env` run for that season.


## v33: tactics, preferences and chemistry (the phase B calibration pass)
Phase B changed the engine: twelve tactical settings with counters (docs/TACTICS.md), club preferences (goalie pulls,
the hook, line matching, ice time), overtime units, player tendencies and line chemistry (docs/LINES.md). Tactics now
act by strength state (even-strength settings at even strength only, power-play and penalty-kill settings on special
teams), where the v25 systems touched every state.

Method: `python -m hs.sim.validate <save> env.json --seasons 3 --tactics ai` (every club, yours included, on its AI
settings), three seeds (7, 11, 23), on the 2025-26 world save; `--tactics none` and `--chem random` as checks.

What the pass found and changed:
1. **Everyone picked the same options.** Several options paid off even for an average roster, so 31 of 32 clubs used
   the stretch breakout and 28 the zone defence. Each option's upside is now scaled so it breaks even at execution 1
   (`tactics.BALANCE`); fit and coaching decide. Afterwards the choices spread (for example: man-to-man x18, zone x4,
   hybrid x10; stretch x14, safe x10, controlled x8).
2. **Power-play goals 8% high** (1.19 a game against 1.10): the best players fill the first PP unit, and skill pushed
   the env's 5v4 rates up. New `Skill.pp_scale` 0.93 on power-play attempt volume.
3. **Penalties 1.5% short**: new `Skill.pen_scale` 1.015.
4. **Attempts 1% short** once power-play volume came down: `Skill.att_scale` 0.955 -> 0.960.
5. **Counters do not cancel out** with a real mix of choices: they are divided by their average over every pairing
   in the league (`loader.normalise_counters`), so they only move results between clubs.
6. The goalie hook (default: after 4 goals, through the first half of the third) spreads goals against over backups:
   team save % spread .0083 with no tactics, .0095-.0105 with them (real .0091).

After (seeds 7 / 11 / 23, AI tactics, three seasons each):
| metric | sim | real |
|---|---|---|
| goals_per_team_game | 2.888 / 2.914 / 2.891 | 2.879 |
| sog_per_team_game | 27.313 / 27.220 / 27.333 | 27.561 |
| attempts_per_team_game | 57.028 / 57.079 / 57.123 | 58.103 |
| sv_pct | 0.894 / 0.893 / 0.894 | 0.895 |
| penalties_per_game_both_teams | 6.996 / 6.898 / 6.966 | 6.900 |
| pp_minutes_per_game | 9.199 / 9.100 / 9.109 | 8.984 |
| pp_goals_per_game | 1.116 / 1.108 / 1.098 | 1.098 |
| cf_pct_sd | 0.029 / 0.032 / 0.031 | 0.032 |
| xgf_pct_sd | 0.041 / 0.044 / 0.043 | 0.035 |
| sv_pct_sd | 0.011 / 0.010 / 0.009 | 0.009 |
| goal_diff_per_game_sd | 0.572 / 0.559 / 0.572 | 0.598 |

Overtime games 0.20, shootouts 0.40-0.44 of overtime, home wins 0.540-0.548, empty-net goals 0.19-0.21 a game.
Chemistry with every pair random (a stress test: `--chem random`) moves the goal-difference spread by +0.01 and
nothing else. Remaining gaps: expected-goals share spread .041-.044 against .035 (as before v33), goal-difference
spread .56-.57 against .60.

## v35: hidden attributes, rust and playing hurt
Consistency (a per-game swing in offence, mean zero), temperament (who takes the penalty), injury proneness (x1.0 on
average), coachability and big games (playoffs only) are centred, so the league's totals should not move. Checked with
the same three seeds, AI tactics, three seasons: goals 2.89 / 2.92 / 2.90 a team-game, shots 27.2-27.3, save % .893-.894,
penalties 6.89-6.93, power-play goals 1.10-1.17, shot-share spread .029-.031, goal-difference spread .57-.59 (it rose
towards the real .60: nights off and nights on spread the results a little). Nothing retuned.


## v38: an imported database

The ratings model (hs/attributes.py) derives the engine attributes from the 42 ratings, puts them on the scale the
engine was tuned on (fitted to the NHL's dressed players) and anchors each player's level on current ability
(docs/DB_IMPORT.md). On the imported 2026-27 world, three seeds x three seasons, AI tactics, chemistry from the save:
goals 2.85-2.90 (2.88), shots 27.1-27.3 (27.6), save % .894-.895 (.896), penalties 6.90-7.02 (6.90), power-play
goals 1.10-1.12 (1.10), goal-difference spread .60-.61 (.60), with `"engine": {"pp_scale": 0.90, "pen_scale": 1.03}`
pinned in the import's rules. The bundled world's engine attributes and constants are unchanged.
