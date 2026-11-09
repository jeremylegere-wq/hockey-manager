# Lines editor (v22)

`hs/game/lineup.py`, engine support in `hs/sim/engine.py` (`Team.apply_lineup`, special-teams units in `on_ice`).

The engine dresses 4 forward lines, 3 defence pairs and two goalies. Without a saved lineup it builds them from last
season's ice time (then ratings), as before. Once you save lines, the engine uses them in every game:

| Unit | Players | Ice time |
|---|---|---|
| F1-F4 | C, LW, RW | 38 / 31 / 20 / 11% of even-strength shifts |
| D1-D3 | LD, RD | 40 / 35 / 25% |
| G | starter, backup | the starter about 82% of games |
| PP1, PP2 | 5 each (optional) | PP1 65% of power-play time; empty = drawn from the top lines, weighted to the first |
| PK1, PK2 | 4 each (optional) | PK1 65% of short-handed time; empty = drawn from the lines |

Positions within a line are labels (the engine uses forward or defenceman, not wing side); a defenceman at
forward plays as a defenceman would (shoots like one). Special-teams players must be dressed. Anyone unavailable on
the day (injured, traded, sent down, on waivers) is replaced from the default depth chart for that game, and the
Lines screen and `lines` say who was replaced. With no saved special-teams units the results are exactly as before
(same random draws).

- UI: **Lines** screen: a dropdown per slot, duplicates highlighted, Save lines, Automatic.
- CLI: `lines`; `lines set F1 Suzuki, Slafkovsk, Demidov; D1 Hutson, Carrier; G Dobes, Fowler; PP1 a, b, c, d, e`;
  `lines set PP2 none`; `lines swap Suzuki, Kapanen`; `lines auto`.

AI clubs keep the automatic depth chart.

## v33: overtime units, tendencies, chemistry and roles
* **Overtime units.** Two 3-on-3 units (F, F, D) and two 4-on-4 units (F, F, D, D); the first plays about 60% of
  overtime. Empty: the top lines go out. CLI: `lines set OT31 a, b, c; OT41 a, b, c, d`.
* **Tendencies** (per player, kept with your lines): shoot first (1.6 x his weight for his unit's shots, 0.75 for
  assists) or pass first (0.6 / 1.35); attacking (+0.12 sd offence, -0.12 defence) or defensive (the reverse).
  CLI: `tend <player> shoot first|pass first|attacking|defensive|normal`.
* **Chemistry** (hs/game/chemistry.py). Each game adds a game together to every pair in a forward line and a
  defence pair; a pair's chemistry is min(1, games / 30), halved once they have been apart for a month. At even
  strength the engine moves attempts by 5% per unit of chemistry above the opposing unit's (both relative to the
  league's average pair), so a settled line is worth a little and constant shuffling costs a little. The Lines screen
  shows each unit's chemistry.
* **Roles** (hs/game/roles.py, display only). Major roles from the ratings: sniper, playmaker, power forward, two-way
  forward, grinder, enforcer; offensive, defensive, two-way and physical D; positional and athletic goalies. Tags:
  franchise, star, core, depth, prospect, veteran. Beside each line, what it lacks: no finisher (nobody shoots 12+), no
  playmaker (nobody passes 12+), no defensive conscience (nobody reads the game 11+); for a pair, no stay-at-home side
  or nobody to move the puck.


## Lineups (v52)

`hs/game/lineups.py`; the Lineups panel at the top of Team > Lineup; console `lineups`, `lineups on|off`,
`lineups list <C|LW|RW|LD|RD|G|PP|PK> <player>, ...`, `lineups goalie <rule>`.

```
Lineups: priority lists that rebuild your lines before every game, and the goalie start rule (v52; docs/LINES.md
"Lineups").

You rank players for each slot: centres, left wings, right wings, left and right defence, goalies, the power play and
the penalty kill (a player may be on several lists). Before each of your games, with lineups on, the lines are built
from the lists: the first healthy player on the roster not already used fills each slot in order (C1, C2... then the
wings line by line, then the pairs), the power play takes the first ten dressed players on its list (two units of
five), the penalty kill the first eight (two of four); a list that runs out is filled from the best remaining players
at the position. Overtime units are kept as saved. Your saved lines are replaced each game day, so lines you set by
hand stay only until the next game; turn lineups off to set lines by hand again.

The goalie rule (with lineups on): "usual" (the first goalie on the list starts about 82% of games, as before),
"every game" (he starts them all), "rest on back-to-backs" (the second goalie starts the second of two games on
consecutive days), "every fourth game" (the second goalie starts every fourth game).
```
