# Speed (v60)

On the full world (20,000 players, 37 leagues), over the same 30 days of the same save (20 October to 19 November, one
monthly development step included), on one core, in two runs:

| | Seconds a day |
|---|---|
| v59, thirteen leagues game by game | 0.90 - 0.97 |
| v60, the same thirteen leagues | 0.62 - 0.69 (about 30% less) |
| v60, all 36 leagues game by game | 0.76 - 0.80 |

The third row includes the one-off catch-up of the 23 new leagues' first five weeks. Rest of a season with all 36
leagues (November to the end of the playoffs): 143 s; the offseason: 63 s.

**Nothing a save contains changes.** With the same leagues in play, v59 and v60 produce a byte-identical save over
those 30 days: every row of every table the two versions share (112 of them). The changes below only remove repeated work.

## What changed

| Change | Where | Why it is safe |
|---|---|---|
| Indexes on `players(team_id)` and `players(club_id)` | `hs/schema.py` `migrate` (added when a save is opened) | An index changes how rows are found, not which rows or their content. "Who is on this club" was reading all 20,000 players, thousands of times a day |
| A read cache that lives until the next write | `hs/perf.py`; used by `roster.player_value` and `roster.roster` | sqlite counts every row a connection changes; the cache is dropped the moment the count moves, so an answer from it is always the answer the query would give. It is only on while a connection is simulating a day; the interface's own connections never use it |
| Clubs of the other leagues read only the ratings their overall is made of | `hs/game/leagues.py` `_load_clubs` | Same rows in the same order, the same arithmetic, fewer columns |
| A player's last season is found from the player, by index | `hs/sim/loader.py` `load_teams` | The result is a maximum and sums of whole numbers: the order rows arrive in does not matter |
| The rating scale is read once for the monthly development pass, not once a player | `hs/game/ratings.py` `batch` | The scale does not change during the pass |

## Leagues in play

League > World Leagues > **Leagues in play** (or `leagues play <league> on|off`, `leagues play all|core|none`). A league
played game by game costs a little every day; one simulated a season at a time costs nothing until the year ends
(docs/LEAGUES.md). "The main thirteen only" is the v59 set.

## Checking a change

The rule for speed work here: the save must come out the same. To check, sim the same days from the same save with the
old and the new code and compare a hash of every table (the method used for the numbers above). `tests/test_v60.py`
checks that cached and uncached answers agree and that a write is seen at once.

## Where the time goes now

Roughly, per day, with every league in play: the monthly development step (averaged over the month) a fifth, loading the
NHL clubs (tactics fit, roles, chemistry, form) a fifth, the other leagues' games a sixth, the NHL match engine an
eighth, and the rest spread over AI roster moves, trades, scouting, contracts and jersey numbers. The match engine
itself is not the bottleneck.
