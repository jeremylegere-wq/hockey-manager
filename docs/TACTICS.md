# Tactics (hs/game/tactics.py; v25 systems, v33 phase B settings)

## Twelve settings
Three or four options each, in four groups. Each option moves some of the engine's multipliers for the club using it:
`att` / `qual` (even-strength attempts and shot quality), `allow_att` / `allow_qual` (what it allows), `pen`
(penalties taken), `pp_att` / `pp_qual` (power play), `pk_allow_att` / `pk_allow_qual` (allowed short-handed),
`sh_att` (its own attempts while short-handed). The middle option of each setting is the engine as calibrated.

| Group | Setting | Options |
|---|---|---|
| With the puck | Breakout | safe (off the glass), controlled, stretch pass |
| | Neutral zone (offence) | dump and chase, balanced, carry it in |
| | Attacking zone | cycle low, balanced, point shots, crash the net |
| Without the puck | Forecheck | passive 1-3-1, 2-1-2, aggressive 2-3 |
| | Neutral zone coverage | trap, balanced, high pressure |
| | Defensive zone | zone, hybrid, man-to-man |
| Power play | PP breakout | drop pass, single carrier, stretch |
| | PP setup | umbrella, overload, 1-3-1 |
| | PP approach | shoot first, balanced, patient |
| Penalty kill | PK forecheck | stay back, balanced, pressure |
| | PK coverage | box, diamond, aggressive |
| | Shorthanded attack | never, opportunistic, attack |

The effects of each option are in `SETTINGS` (for example an aggressive forecheck: attempts +4.5%, better chances
against +3%, penalties +4%; a trap: attempts allowed -4%, own attempts -3%).

## Fit, execution and break-even
```
execution = 1 + 0.3 x fit + 0.04 x (head coach's coaching - 10) [+ 0.15 when his style's preset uses this option]
            clamped to 0.3-1.6
fit       = the club's top 18 skaters in the option's attributes, in standard deviations from the league's average
            club, less the club's own average over every option's attribute set (a roster's shape, not its quality)
```
An option's upside is scaled by execution and its cost is not. Every option **breaks even at execution 1** (an
average roster for it and an average coach): its upside is scaled so the expected value is zero there (`BALANCE`).
So fit and coaching decide whether it pays. This was added in the v33 calibration pass: without it, 31 of 32 AI clubs
chose the same breakout. Value = a rough goal-difference index (per cent):
`(att x qual - 1) - (allow_att x allow_qual - 1) - 0.25 (pen - 1) + 0.18 (pp_att x pp_qual - 1) - 0.18 (pk_allow_att x pk_allow_qual - 1) + 0.02 (sh_att - 1)`.

## Counters
Some choices beat others, game by game (`COUNTERS`, the attacker's attempts and quality against the defender's
choice): a stretch breakout beats an aggressive forecheck (+4% attempts) and loses to a passive 1-3-1; carrying it in
loses to a trap, dumping it in beats one; cycling beats man-to-man, point shots beat a zone; an umbrella beats a box
and loses to an aggressive kill; a 1-3-1 beats a diamond; a stretch PP breakout beats a pressure kill. The Tactics
screen scouts your next opponent (or any club) and lists the switches that would counter him.

## Presets: the five systems
The v25 systems are presets of the six even-strength settings:
| System | Settings |
|---|---|
| balanced | all the middle options |
| heavy forecheck | aggressive 2-3, dump and chase, high pressure |
| puck possession | controlled, carry it in, cycle low, trap |
| defensive structure | safe, passive 1-3-1, trap, zone |
| speed and transition | stretch pass, carry it in, high pressure |
A club's "system" (for the owner's identity and the coach's style) is the preset closest to its settings.

## Preferences
| Preference | Options (default first in bold) |
|---|---|
| Pull the goalie, down one | 3:00, **2:00**, 1:30, 1:00, never |
| Pull the goalie, down two | 4:00, 3:00, 2:00, **1:00**, never |
| Pull a struggling starter | after 3, **after 4**, after 5 goals, never (through the first half of the third) |
| Line matching (home games) | **off**, checking line on their top line, top line on their top line (60% of their top line's shifts) |
| Ice time | roll four lines (31/28/24/17%), **balanced** (38/31/20/11), shorten the bench (45/33/16/6) |

## League neutrality
Every multiplier is divided by its league-wide mean (`engine_effects`), and the counters are divided by their average
over every pairing in the league (`hs.sim.loader.normalise_counters`), so whatever mix of tactics the league plays,
the league's totals stay where the engine was calibrated (docs/SIM_CALIBRATION.md, v33).

## Who picks
AI clubs take each setting's best option for their roster and coach (the middle option unless another is worth 0.2,
or 0.06 for special teams), at setup, every preseason and when they hire a head coach; their preferences stay at the
defaults. You choose on the Tactics screen (Team > Tactics) or in the CLI: `tactics` (list), `tactics <system>`,
`tactics set <setting> <option>`, `tactics pref <preference> <value>`.

## The owner
An owner may want an identity (one of the five systems). A club whose settings are closest to it earns +0.25 board
confidence a week; an owner with involvement 7+ whose club plays something else takes 0.15 a week off, and may issue a
directive (docs/BOARD.md).

## Tables
`team_tactics (team_id, system, set_on, chosen_by, settings JSON, prefs JSON)`; older saves read their system as a preset.

## Tactical roles (v55, hs/game/troles.py)
A job you give a player, with a fit score and an effect while he is on the ice. On the Lines screen ("Tactical roles")
or in the CLI: `troles`, `troles suggest`, `troles clear`, `troles info`, `troles <player> <role|none>`.

```
fit       = 50 + 15 x (his average in the role's attributes against the league's NHL players at his position, in sd)
            0-100: 65 is about the best sixth, 80 the best 2-3%
execution = 0.2 + fit / 62.5, 0.2-1.8 (fit 50 -> 1.0, 75 -> 1.4)
```
Each role has an upside, scaled by execution, and a cost, fixed. Both apply while he is on the ice, in the strength
states listed. As with the tactics, a role roughly **breaks even at execution 1**, so it pays only when the player
suits it, and costs when he does not.

| Role | For | When | Upside (x execution) | Cost | Fit from |
|---|---|---|---|---|---|
| Agitator | F | even | opponents' penalties +12% | his unit's penalties +8%, attempts allowed +1%; he is the one who goes | aggression, determination, agility, toughness |
| Shadow | F | even | against the opponents' **top line**: their attempts -8%, quality -4% | his unit's attempts -4% (every shift) | defensive awareness, positioning, stick checking, speed |
| Net-front presence | F | even, PP | shot quality +4%, rebounds +15% | attempts -4% | net presence, strength, toughness, bravery |
| Trigger man | F | PP | shot quality +6%; he takes the shot (x1.8) | PP attempts -5% | shot power, accuracy, composure, offensive awareness |
| Forechecker | F | even | attempts +5% | penalties +4%, attempts allowed +4% | speed, checking, hitting, endurance |
| Enforcer | F | even | opponents' penalties +4%, their quality -2%; the other club's agitators draw half as much (dressed) | attempts -3% | toughness, strength, aggression, hitting |
| Penalty killer | F, D | short-handed | attempts allowed -6%, quality allowed -2% | even-strength attempts -2% | defensive awareness, positioning, shot blocking, speed |
| Shutdown D | D | even | attempts allowed -5% | attempts -5% | positioning, defensive awareness, stick checking, shot blocking |
| Puck mover | D | even | attempts +5% | attempts allowed +5% | passing, puck control, speed, offensive awareness |
| PP quarterback | D | PP | PP attempts +7% | PP shot quality -6% (point shots) | passing, puck control, offensive awareness, composure |
| Crease-clearer | D | even, SH | quality allowed -4%, rebounds allowed -20% | penalties +4%, attempts allowed +5% | strength, hitting, positioning, bravery |
| Rover | D | even | shot quality +5% | quality allowed +5% (odd-man rushes) | speed, offensive awareness, puck control, shot accuracy |

**Rules.** A player has one role or none, and a role takes at most two players. A traded player leaves his role
behind. "Suggest" gives each role to the best-fitting dressed player who clears fit 60 (two penalty killers). AI clubs
do the same at setup (or the first game day of a save from before v55), on the first game day of each month, and in
the preseason.

**League neutrality.** Roles move results between clubs, not the league's totals. The league's average effect on the
penalty rate (each role player's own penalties and the ones he draws, weighted by the share of the even-strength game
his effect reaches: forwards 0.22, defencemen 0.26, measured) is divided out of every club's rate.

Measured on the 2027-28 world with every club's suggested roles, against the same rosters with none (3,000 games each,
the same seeds):

| | Goals a game | PP goals | Penalties |
|---|---|---|---|
| no roles | 5.914 | 1.075 | 6.855 |
| roles | 5.874 (-0.7%) | 1.048 (-2.5%) | 6.872 (+0.2%) |

The change in each club's goal difference was the same size as the seed noise (two runs with no roles and different
seeds: up to +-0.45 a game over about 190 games).
