# Stats hub and the record book (hs/game/history.py, hs/ui/stats.py)

Seasons are labelled the way the league labels them (2025-26). The record book is written when each season ends; the live season is computed from box scores.

At the end of every simulated NHL season (hs.game.dayloop.finish_season calls season_end):
  * goalie decisions: the goalie with the most ice time for a club in a game gets the win, loss or overtime loss,
    and a shutout when he allowed nothing; folded into goalie_season_stats (W, L, OTL, SO, GS)
  * playoff stats: every playoff box score folded into skater/goalie_season_stats with split 'PO'
  * team_seasons: each club's final record, its place in division, conference and league, and how its playoffs
    ended (missed, first round ... lost the final, champion)
  * awards (AWARDS below): voted on numbers the game records. Names are the NHL's (kept for personal use; see
    docs/DATAPACK_SPEC.md on publishing)
Idempotent per season. The live season's equivalents are worked out on the fly by hs.ui.stats.

## Screens
* **Stats** (`#stats`): league leaders (points, goals, assists, points a game, shots, points by defencemen, rookie
  points; goalie wins, save %, GAA, shutouts; leaders need a quarter of the games played), full skater and goalie tables
  (with shooting % and ice time a game), team stats; filters for season, league (every league with recorded seasons, NHL by
  default) and regular season / playoffs. Shot-based advanced stats live in Analytics (docs/ANALYTICS.md).
* **League history** (`#leaguehistory`): champions by season, award winners, all-time and single-season leaders.
* **Team pages** (`#team/<id>/<season>`, in the style of hockeydb.com): the season's record and finish, roster with every
  player's line (players link to their profiles), and the club's season-by-season history. Every club in a player's
  career table links here.
* **Player profile** (`#player/<id>/<tab>`): overview, career stats (by season and league, regular season and playoffs,
  totals), game log, ratings (with their history and league percentile), contract, personality and history (awards,
  transactions, events).
* **Playoffs** (`#playoffs`): the bracket and the season's awards.

## Lower leagues
Lower-league seasons are simulated statistically (hs/game/world.py, see docs/WORLD.md). Points per game are anchored per
league (LOWER_PPG) and spread by the player's standing within his league; history.repair_lower rescales older saves once.
