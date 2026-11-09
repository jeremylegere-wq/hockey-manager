# Third-party material and data

Hockey Manager is released under the MIT licence (see `LICENSE`). This file lists what is not the author's own work,
and what the game does and does not ship.

## Shipped with the game

| What | Where | Licence / terms |
|---|---|---|
| plotly.js 2.35.2 (analytics charts) | `hs/ui/static/vendor/` | MIT; the licence text is in `hs/ui/static/vendor/PLOTLY_LICENSE.txt` |
| League-wide scoring rates (goals, shots, penalties and power-play rates per game, the spread between clubs) | `data/env_default.json` | Aggregate numbers derived from MoneyPuck.com's public season summaries (2025); MoneyPuck's data is free for non-commercial use with credit to MoneyPuck.com. No player or club data is in the file. Replace it with your own with `python -m hs.sim.env` (see `data/README.md`) |
| The title-screen backdrop | `hs/ui/static/launch.jpg` | The author's own picture |

## Optional, installed on your machine only

| What | Why | Licence |
|---|---|---|
| pywebview | the game's own desktop window (the launcher offers to install it into `.runtime/`) | BSD-3-Clause |

## What the game does not ship

* **No real player, club, league or staff data.** The world that comes with the game is generated: every club, town and
  player is invented (`hs/leaguedata/fictional.py`, `hs/tools/make_mock_league.py`). Any match with a real person or club
  is chance.
* **No logos, crests, photographs or trademarks.** Crests and portraits are drawn by the game from the club abbreviation
  and the player id; they are not anyone's marks or likenesses.
* `hs/leaguedata/` holds plain facts about real league structure (club names, divisions, the shape of each league's season)
  that the importers below use when *you* build a world from your own data. The game does not use them for the bundled
  world.

## Importers for your own data (code only)

`hs/adapters/` and `hs/ratings/` can turn data you already have (a Franchise Hockey Manager CSV export, MoneyPuck season
summaries, an export of a community player database, a spreadsheet of contracts) into a world. They read **your** copy.
The worlds they build contain other people's data: they are marked `redistributable: false`, stay on your computer
(`packs/`, `save/`, `worlds/` and `saves/` are git-ignored) and must not be published or shared.

Hockey Manager is an independent hobby project. It is not affiliated with, endorsed by or connected to the NHL, the NHLPA,
any league, club, player, or any commercial game or publisher.

AI coding assistants helped write the code under the author's direction; see Help > Credits in the game.
