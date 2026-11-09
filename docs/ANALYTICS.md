# Analytics (hs/ui/analytics.py, v26)

The Analytics screen works from the season's recorded game events (every attempt, its shooter, its goalie and its
goal probability) and per-game player stats, so it describes the simulated league, not the real one. Charts are drawn
with Plotly (bundled in `hs/ui/static/vendor`, MIT licence; nothing is fetched from the internet). Regular season
only; overtime counts, shootouts do not.

| term | meaning |
|---|---|
| attempts (Corsi), CF% | shots on goal + missed + blocked; CF% is a club's share of all attempts in its games |
| xG, xGF%, ixG | the engine's goal probability of each shot on goal, summed (empty-net goals carry none); ixG is one player's |
| PDO | shooting % + save %, x1000. 1000 is average; far above usually means luck that fades |
| G-xG | goals above expected: finishing, or luck |
| GSAx | a goalie's xG faced minus the goals he allowed |
| expected points | GF² / (GF² + GA²) x games x 2 (Pythagorean); points above it are usually close-game luck |
| playoff odds | 2,000 simulations of the remaining schedule. Each game's home-win chance is logistic on the clubs' strength (half goal difference per game, half xG difference, shrunk towards average early in the season, plus home ice); about 23% of games reach overtime (the loser takes a point); the league's playoff format picks the qualifiers, ties broken at random |

Tabs: **League** (process map of xGF and xGA per game; PDO against points above expectation; team table),
**Team** (10-game rolling xGF%, GF% and CF%; goals against xG, cumulative; shot-quality distribution for and against;
goals and assists by player; skater table), **Players & goalies** (goals against ixG; GSAx; sortable tables),
**Contracts** (cap hit against points per 82 games; points per $1M; goalies' GSAx against cap hit) and **Playoff
odds** (by conference, with projected points and division chances). Your club is in red throughout.

Limits: shot xG is shot-on-goal xG only (the engine does not assign a probability to misses and blocks); there is no
on-ice (five-man) data yet, so no relative or on-ice player metrics.
