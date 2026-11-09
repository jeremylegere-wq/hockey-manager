# data/

`env_default.json` is the league environment the match engine is calibrated against: league-wide rates by game situation
(shot attempts, shot quality, save percentage, penalties, power-play and short-handed rates, goals per game) and how far
apart the clubs are. The game loads it with `--env auto` when you have not made your own (`save/env_2025.json`).

It holds numbers only, no players or clubs. It was derived from MoneyPuck.com's public 2025 season summaries (free for
non-commercial use with credit to MoneyPuck.com).

## Make your own

If you have the season-summary CSVs (`skaters_<season>.csv`, `goalies_<season>.csv`):

    python -m hs.sim.env <folder with the csv files> --season 2025 --out save/env_2025.json

The game prefers `save/env_2025.json` when it exists. The engine and the numbers it is checked against are described in
`docs/SIM_CALIBRATION.md`.

The bundled mock world is generated to play at these rates: about 5.7 goals a game, 28 shots a side, 6.9 penalties a game,
a goal-differential spread of about 0.6 a game between clubs. If you change the environment, check a season with
`python -m hs.sim.validate <a career started in the world> save/env_2025.json --seasons 3`.
