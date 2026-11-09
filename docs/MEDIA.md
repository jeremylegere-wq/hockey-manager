# Media and the 2D replay (v18)

Roadmap item 7 (docs/ARCHITECTURE_AUDIT.md). Both are presentation over facts the game already records; neither
writes game state (`tests/test_media.py` checks the row counts do not move). Wording is picked deterministically
from the event or game id, so a save always reads the same way.

## Media (hs/game/media.py)
All outlets and accounts are fictional.

| Piece | Source | What it does |
|---|---|---|
| Game recaps (The Morning Skate) | `games`, `game_events`, `player_game_stats` | headline, lede, score by period with shots, scoring summary, penalties, shootout, three stars. Headline priority: hat trick, shootout, overtime winner, shutout, comeback from 2+ down, rout (4+), the first star, otherwise a plain result |
| Headlines (The Crease Report) | `league_events`, importance 2+ | trades (AI deals of importance 3), offer sheets matched or not, rights trades, signings $5M+ (not qualifying offers or arbitration), injuries of 3+ weeks, retirements after 400+ NHL games, coaching and GM changes, trade requests, arbitration awards $6M+, buyouts, college picks walking, top-3 picks, championships, records. Your club or the league |
| Social feed | the same events, plus your games | @InsiderOnIce (trades, requests, firings, long injuries), @CapCrunchHQ (contracts, offer sheets, buyouts), @PipelineScout (top-10 picks, rights trades, college walkaways), and @<ABBR>Faithful for your club: a post after each game whose tone follows the score and your last ten, and replies to your own moves (a signing's reply follows its contract grade A-F; otherwise the club's form) |
| Power rankings | regular-season games of the current season (last season's until this one starts) | score = 0.55 x points % + 0.25 x (0.5 + goal differential a game / 4) + 0.20 x last-ten points %; movement against the table six days earlier once every club has 5+ games; a one-line blurb per club |

Rumours are only ever about things that happened (a trade request, a firing); the feed does not invent moves.

## 2D replay (hs/game/replay.py, hs/ui/static/replay.js)
The engine is statistical: it stores each shot attempt, block, miss, goal, penalty and shootout attempt with the
shooter, goalie or blocker and the shot's goal probability, but not positions. The replay reconstructs them:

| | Rule |
|---|---|
| rink | 200 x 85 ft, centre ice at 0, 0, nets at x = +-89 |
| ends | home shoots at +x in the 1st, 3rd and overtime, at -x in the 2nd |
| shot spot | distance 8 + 52 x e^(-xg/0.06) ft, +-20% (xg 0.03 ~ 40 ft, 0.08 ~ 22 ft, 0.15 ~ 12 ft); angle up to +-70 degrees, narrower for better chances |
| misses and blocks | no probability stored: 30-55 ft attempts; a miss goes wide of the net, a block stops 30-50% of the way |
| between events | the puck is carried from the last event to the next chance through the neutral zone |
| skaters | five generic dots a side in a formation around the puck (the engine does not record who was on the ice); the shooter and blocker are named at the moment of the event; goalies sit in their creases |
| seed | random draws are keyed on the game id and seed, so the same game always replays the same way |

Player controls: play/pause, 30x-300x speed, jump to the previous or next goal, a scrubber, and a shot-chart
overlay (dot = save, cross = miss or block, ringed dot = goal). The clock holds on each event so you can see it;
at high speeds only goals and penalties linger. The scoreboard tracks the score, shots on goal and a power-play
countdown (2:00 from each minor, ended early by a power-play goal; offsetting minors show no power play).

A true positional engine (agents on the ice, 0.25 s slices) is still the "later, large" option in the audit: it
would have to be recalibrated to the same league rates before it could replace the statistical engine.

## Where to see it
- UI: **News** (Headlines, Game recaps, Social, Power rankings; your club or league) and a game page (`#game/<id>`)
  from any result on the Dashboard, Schedule, Recaps or the fan posts: replay on the left, recap, score by period,
  three stars, scoring and penalties.
- CLI: `recap [game id]` (your last game by default; `results` prints the ids), `news [league] [n]`, `feed [n]`,
  `power`.
