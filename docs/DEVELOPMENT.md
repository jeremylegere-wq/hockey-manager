# Player development (v40, hs/game/development.py)

Player development v40 (docs/DEVELOPMENT.md): growth through the season, and what drives it.

Before v40 every player changed once, in the summer, by an amount set by his age, his potential, your development
staff, his coachability and (where it goes) his training focus. v40 keeps that curve as the expected year
(worldgen.yearly_change) and adds:

When
  Young players grow during the season too: IN_SEASON_SHARE (40%) of a growing player's expected year comes in six
  monthly steps (1 November to 1 April), the rest in the summer. Decline (ageing) stays a summer thing.

What drives it (multipliers on growth; the product is clamped to 0.55-1.45)
  ice      NHL players 23 and under: ice time per game played against what a regular at his position gets, and how
           many of the club's games he dressed for (scratched kids stall). Others: 1.0.
  level    Where he plays against how good he is (league mean on the engine scale): challenged (-1.5 to +1.2 of the
           league mean) 1.04; too good for the league 0.90 ("not challenged"); overmatched 0.88. The NHL counts as
           challenging for anyone who dresses.
  character  professionalism and ambition: 1 + 0.015 (prof - 10) + 0.008 (ambition - 10).
  mentor   a mentor you assign (27+, on your NHL roster, professionalism 12+, at most two pupils): 1.10, 1.14 if his
           professionalism is 16+; a pupil 23 or under on the NHL roster with no mentor gets 1.03 from an older
           teammate of good character (one is usually around). A mentor may pass on professionalism (+1, 12% a month,
           never above his own); one with an ego of 15+ may pass on a bad habit instead (-1, 6%).
  training the club's training intensity: light 0.92 (fewer injuries, x0.88), normal 1.0, hard 1.08 (more injuries,
           x1.15).
  injury   time out: 1 - (days out in the period / days in it) x 0.8; a long injury (40+ days) at 27+ can cost a
           point of speed or acceleration.
  staff, coachability: as before (staff.development_multiplier, hidden.coach_factor).
Decline: professionalism slows it (x(1 - 0.02 (prof - 10)), 0.8-1.2); hard training x1.05.

Reports
  Every month your development coach writes: who moved most, and the calls to make: a kid who is not playing, a
  prospect too good for his league, one in over his head, an injury costing him development. dev_log keeps every
  step with its factors (the player's Development tab and the Development screen read it).

## Where you see it
* **Team > Development** (the development centre): training intensity; every player 26 and under with his overall,
  last month's step, this season's change, his pace (all factors multiplied) and what drives it (chips: green
  helps, red hurts), a mentor menu and his training focus; established players below with their change since the
  summer.
* **The player's Ratings tab:** the development chart and a development log (each monthly step and summer with its
  factors).
* **The inbox:** the development coach's report on the 1st of each month from November to April: most improved, going
  the wrong way, and the calls to make.
* **Console:** `intensity [light|normal|hard]`, `mentor <young player>, <veteran>`, `mentor end <young player>`,
  `train <player> <focus>`.

## Calibration
The expected year is unchanged (the same age curve and potential); the factors average about 1.0 across the league
(the "challenged" level factor is 1.04 so that coasting and overmatched players balance it). Over two simulated
season on the 2026-27 world (a season and a summer, same seed) the average change by age against v39:

| Age | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 30 | 34 | 36 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v39 | +1.04 | +1.17 | +0.61 | +0.53 | +0.78 | +0.98 | +0.86 | +0.28 | -0.08 | -0.20 | -0.33 |
| v40 | +1.08 | +1.10 | +0.58 | +0.50 | +0.73 | +0.93 | +0.93 | +0.28 | -0.07 | -0.19 | -0.30 |

(GROWTH_NORM = 1.08 brings the year back to v39's after the in-season share shrinks the summer's gap.) The NHL's
average current ability holds: 146.8 to 146.4, spread 17.7 to 18.3. What changes is who grows: a kid who plays,
in the right league, with a good mentor and good habits, grows faster; one sitting in the press box or coasting in
the AHL grows slower.
