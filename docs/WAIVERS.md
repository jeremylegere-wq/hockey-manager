# Waivers (v22)

`hs/game/waivers.py`. During the waiver period (the preseason phase and the regular season), sending a player who is
not exempt to the minors puts him on waivers for a day. Any club can claim him; claims go to the club with the worst
record (points percentage; on paper strength early in the season). A claiming club takes his contract onto its NHL
roster and must waive him again to send him down. If nobody claims him he clears and goes to the minors, and can be
recalled and sent down again without waivers for 30 days, as long as he plays fewer than 10 NHL games.

**Exemption** (waiver age = age on 15 September of the first season of his first NHL contract; whichever limit comes
first; table from [PuckPedia](https://www.puckpedia.com/salary-cap/waivers)):

| Waiver age | Skaters: seasons / NHL games | Goalies: seasons / NHL games |
|---|---|---|
| 18 | 5 / 160 | 6 / 80 |
| 19 | 4 / 160 | 5 / 80 |
| 20 | 3 / 160 | 4 / 80 |
| 21 | 3 / 80 | 4 / 60 |
| 22 | 3 / 70 | 4 / 60 |
| 23 | 3 / 60 | 3 / 60 |
| 24 | 2 / 60 | 2 / 60 |
| 25+ | 1 / - | 1 / - |

An 18- or 19-year-old who plays 11+ NHL games in his first season drops to 3 seasons (goalies 4). Seasons count from
the contract's first season, less slid entry-level years. From memory of the CBA, not checked: the waiver period
dates, the one-day waiver window, claim priority by points percentage, and the 30-day/10-game recall rule.

**AI clubs** decide who goes down by the league's perceived value (ratings blended with NHL production, as trades and
the salary market do), and prefer an exempt player unless he is 2.5 value points better than the non-exempt one.
They claim a player who would be better than their weakest at his position by 1.0, if they have cap room and a
contract slot, half the time (v25; it was 0.5 and 60%, which gave ~60 claims a season once ratings were refitted;
the NHL sees ~30-40). Earlier, on the 2025-26 world, preseason to New Year's: 27 players waived, 17 claimed
(mostly depth defencemen and forwards, one third goalie).

**You:** the Roster screen shows each player's status (exempt or waivers required, with the reason on hover); Send down
asks for confirmation when waivers are needed. The waiver wire sits above your roster with Claim buttons and your
priority. CLI: `senddown <player>` (says when he goes on waivers), `waivers` (the wire), `waivers <player>`
(his status), `claim <player>`, `claim remove <player>`. You get an inbox message when your player clears or is
claimed, and when your claim succeeds.

## Stats fix in the same release
A 2025-26 pack carries the real 2025-26 season's stats; when the game simulated its own 2025-26 it added a second
copy, so every career count (NHL games for waivers and rights status, arbitration platform stats, perceived value)
saw that season twice. The simulated season now replaces the pack's copy (moved to `replaced_*_season_stats`), and
older saves are repaired once when opened.
