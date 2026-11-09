# Ratings from outcomes (hs.ratings.moneypuck)

Builds a data pack whose 1-20 ratings come from observed results, so no one else's ratings are needed.
`python -m hs.ratings.moneypuck <moneypuck_dir> <out_pack> --season 2025 [--backtest]`

## Method
1. Rates per player-season: 5-on-5 per-60 and per-shot process rates (goalies: per shot, all situations).
   On-ice metrics are measured relative to the player's team, and every metric relative to that season's
   league rate, so era drift and team strength do not leak into ratings.
2. Repeatability r = year-to-year correlation among qualified players (400+ 5v5 minutes; goalies 500+ shots).
   True-talent spread `sd_true = sd_obs * sqrt(r)`; shrinkage constant `k = n0 * (1 - r) / r`.
3. Pool 3 seasons (weights 1, .6, .36); shrink toward league mean by `n / (n + k)`.
4. `rating = 10.5 + 3 * z`, z in true-talent standard deviations. 3 points = 1 sd of real skill, so low-signal
   skills (finishing, goalie saves) produce narrow rating ranges: that is the correct, honest result.
5. Attributes are weighted blends of metric z-scores (`ATTRIBUTE_MODEL` in the module).

## What is measured, proxied, or unmeasured
- Measured directly: hitting, toughness, shot_blocking, faceoffs, rebound_control, recovery.
- Blends/proxies (best available signal; labelled approximate): shot_accuracy, shot_power, passing,
  puck_control, offensive_awareness, net_presence, checking, stick_checking, positioning,
  defensive_awareness, strength (half body weight), aggression, bravery, composure, goalie_positioning,
  reflexes, glove, blocker, low_shot_save.
- Unmeasured (set to a neutral 10): speed, acceleration, agility, balance, endurance, leadership,
  determination, teamwork, professionalism, mental_toughness, poke_check, goalie_puck_handling,
  goalie_passing, goalie_skating, goalie_stamina. These need another source (tracking data, scouting layer).

## Back-test (`--backtest`)
For each season T (2013-2024), calibrate on data up to T only, then predict season T+1. The pooled, shrunk
estimate has lower error than last season's raw number for almost every metric.

## The v25 recalibration: does the value number rank players?
Every AI decision (trades, salaries, waivers, depth, morale's role expectations) reads one number per player,
`hs.game.roster.value_from_attrs`. Until v25 it was the flat average of the skater attributes. Checked against what
players went on to do, it ranked forwards no better than chance. `python -m hs.tools.ratings_check <pack> <mp_dir>
--season S [--value flat|weighted]` measures that: Spearman rank correlation of pack value with the season's ice time,
points and MoneyPuck game score per game (20+ games), forwards and defencemen separately.

Changes:
1. A points-per-60 metric (`pts60`, all individual points at 5v5) feeds the offensive attributes: passing
   (assists 0.4, pts60 0.3, on-ice xGF 0.3), puck control (attempts 0.5, xGF 0.3, pts60 0.2) and offensive awareness
   (xG 0.35, pts60 0.3, shot quality 0.2, high-danger share 0.15). Composure is now penalties taken only (fewer is better).
   The 10.5 centre and 3-point spread are unchanged (restandardising would break the engine's calibration and other
   packs).
2. The value number is a weighted mean of attributes (`VALUE_WEIGHTS`, by forward and defence), fitted by
   non-negative least squares on ratings built from data to 2023 against 2024 outcomes, then blended 50/50 with a
   prior. Forwards lean on passing (0.37), puck control, stick checking and offensive awareness; defencemen spread
   more evenly over offence, positioning and defensive awareness. Goalies keep the flat goalie mean.
3. The weighted composite is wider than the flat mean (forwards sd 5.8 against 3.5 value points). The salary market,
   trade values, waiver margins and depth decisions were all tuned on the flat scale, and a trial on the wider scale
   broke them (a dozen maximum contracts, AI trades down to 4-20 a season, claims tripled). So `VALUE_SCALE` maps the
   composite back onto the flat formula's mean and sd for NHL skaters: the order changes, the scale does not.

Out-of-sample test (ratings from data to 2024, outcomes 2025):

| rank correlation with | forwards, flat | forwards, v25 | defence, flat | defence, v25 |
|---|---|---|---|---|
| ice time / game | 0.24 | 0.61 | 0.30 | 0.43 |
| points / game | 0.28 | 0.67 | 0.38 | 0.55 |
| game score / game | 0.37 | 0.69 | 0.45 | 0.63 |

(The flat formula on the pre-v25 ratings scored -0.02 to 0.08 for forwards.) The top of the v25 forward list is the
league's real top end (McDavid, MacKinnon, Kucherov, Pastrnak).

Existing packs and saves keep their old attributes: rebuild a MoneyPuck pack with `hs.ratings.moneypuck` and the world
with `hs.tools.build_world` to get the new ratings. The value weights apply to every pack at once.

## Lesson learned
Year-to-year correlations pooled across seasons are inflated by era drift (league averages change). Always
centre each season on the league rate first. Doing so cut the apparent goalie rebound repeatability from 0.76
to 0.28 and high-danger save skill from 0.49 to 0.07.

## Data terms
MoneyPuck data: free for non-commercial use, credit MoneyPuck.com; ask them for anything else. Packs from
this tool are `redistributable: false`. Do not commit them or the source files.
