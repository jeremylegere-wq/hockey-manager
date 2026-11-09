> STATUS: implemented in hs/game (see docs/GAME_LOOP.md). The Gemini attempt was stubs with wrong column names and was not used.

# Handoff brief: build the day-by-day command-line game loop

Paste this whole file into the coding assistant, and give it the project folder (`hockeysim_v5.zip` unzipped, or the
files listed under "Read these first"). Everything it needs is below.

## 0. Ground rules (non-negotiable)
- Python 3.9+, **standard library only** (sqlite3, argparse, cmd, json, random, datetime, unittest). No pip installs.
- Do **not** change the calibrated numbers or behaviour in `hs/sim/engine.py` (the `Skill` constants and the
  game model), `hs/sim/env.py`, or anything in `hs/ratings/`. You may add optional parameters to `simulate_game`
  only if existing tests still pass and default behaviour is byte-for-byte identical.
- Every random choice must come from a `random.Random` seeded from `game_state.rng_seed` plus the date (and an index),
  so a save replays identically. No `random.random()` global calls, no `time`-based seeds.
- All state lives in the SQLite game database (schema in `hs/schema.py`). A "save" is the .db file. No other state files.
- Add tests in `tests/` (unittest). `python -m unittest discover -s tests` must pass (25 tests exist today).
- Never put third-party data (names, ratings from real games) in the repo. Tests use the fictional pack
  (`python -m hs.tools.make_example_pack`) and the synthetic `ENV` dict in `tests/test_sim.py`.
- Finish with: a list of files created/changed, how to run it, what is not done, and any decision you had to guess.
  Output complete files, not diffs.

## 1. What exists (read these first)
```
hs/attributes.py        36 attributes, 1-20 ratings; ALL_ATTRS
hs/schema.py            ddl() -> SQLite schema v2. Tables you will use: players (status: active|injured|retired|prospect,
                        team_id NULL = free agent), player_attributes, teams, games (game_type RS|PO, played, seed,
                        went_to_ot 0/1/2), game_events, player_game_stats, injuries, transactions, game_state
                        (id=1: current_date, rng_seed), pack_info (key/value; 'rules' = JSON), seasons, contracts
hs/ingest.py            build_db(pack_dir, db_path, overwrite) -> counts
hs/sim/engine.py        simulate_game(home: Team, away: Team, env: dict, skill: Skill, seed: int, events=True,
                        playoff=False) -> GameResult.  Team(team_id, name, players: list[Player]) builds lines
                        from Player.toi order.  Player.from_attrs(pid, pos, attrs_dict, name, toi, gp)
hs/sim/loader.py        load_teams(conn) -> {team_id: Team} (active, non-injured? NO: it takes status='active' only,
                        so injured players are already excluded); write_result(conn, game_id, home_id, away_id,
                        res, seed, teams); centre_on_league(teams)
hs/league/season.py     create_schedule(conn, rules, seed), play_regular_season(...), main()  <- the whole-season runner
                        you will turn into a day-by-day loop.  db_rules(conn), team_rows(conn)
hs/league/standings.py  table(conn, season_id), rank(rec, h2h, rules)
hs/league/playoffs.py   qualify_*, run_playoffs(...)
hs/league/schedule.py   build_schedule(teams, rules, seed)
docs/*.md               SIM_CALIBRATION.md, LEAGUES_AND_SCHEDULES.md, RATINGS_MODEL.md, DATAPACK_SPEC.md
tests/                  test_sim.py (ENV fixture + team() helper), test_league.py (small-league season test)
```
How to get a working database to test with:
```
python -m hs.tools.make_example_pack packs/example_fictional
python -m hs.ingest packs/example_fictional game.db --force
```
The fictional pack has 8 teams, 20 players each, a `rules.json` (56 games, top-2 per conference playoffs) and no
free agents. The engine needs an `env` dict (league rates by situation); tests build one inline. For manual runs
the user has a real `env.json` produced by `python -m hs.sim.env`; accept `--env path`.

Note: `load_teams` loads only `status='active'` players. Injured players (status `injured`) are therefore left out of
the lineup automatically; healthy players beyond 18 skaters + goalies simply sit as extras.

## 2. What to build
New package `hs/game/` (create `__init__.py`), plus tests.

### 2.1 `hs/game/state.py`: manager state
- Add a table via a function `ensure_game_tables(conn)` (do not edit the pack schema file): `manager(id=1, team_id,
  name)` and `inbox(msg_id, date, subject, body, read)`. Idempotent (CREATE TABLE IF NOT EXISTS).
- `new_game(db_path, team_abbr, seed)`: opens an ingested db, sets `game_state.rng_seed`, picks the user's team,
  creates the schedule (reuse `hs.league.season.create_schedule`), sets `game_state.current_date` to the day before the
  first game date.  `current_date` is the last simulated day.

### 2.2 `hs/game/injuries.py`: injuries
- `roll_injuries(conn, day, played_players, rng)`: for every player who dressed that day (from `player_game_stats`
  for games on `day`), roll an injury with probability proportional to ice time:
  `p = base_per_60 * toi_sec/3600`, `base_per_60 = 0.006` (about 1 injury per 170 player-games at 20 min; make it a
  constant at the top of the file).  Severity (days out) drawn from a table: 1-3 days 45%, 4-10 days 30%, 11-30 days 15%,
  31-90 days 8%, 91-200 days 2%.  Insert into `injuries(player_id, start_date, expected_return, description)`, set
  `players.status='injured'`, add a `transactions` row (`txn_type='injury'`) and, if the player is on the user's
  team, an inbox message.
- `heal_injuries(conn, day)`: players whose `expected_return <= day` return to `active`; log a transaction and an
  inbox message for the user's team.
- Goalies: a team with fewer than 2 healthy goalies must sign the best free-agent goalie (see 2.4) the same day.

### 2.3 `hs/game/dayloop.py`: advancing time
- `sim_day(conn, env, skill, user_team_id)`:
  1. `day = current_date + 1`.
  2. Heal injuries for `day`.
  3. `teams = load_teams(conn)`; play every unplayed `game_type='RS'` game dated `day` exactly as
     `hs.league.season.play_regular_season` does (seed `rng_seed * 1_000_003 + game_id`; store events).
  4. Roll injuries for players who played.
  5. AI roster management for non-user teams (2.4).
  6. Update `game_state.current_date = day`; commit.
  Return a small summary object (list of results, injuries today, moves today).
- `sim_until(conn, ..., stop)`: repeat `sim_day` until a stop condition: a target date, `n` days, the user's next game
  (stop the day before it), the end of the regular season, or an event that needs the user (their player injured,
  their goalie count < 2).  Never run past the last scheduled game date.
- End of the regular season: when no unplayed RS games remain, compute standings and run the playoffs with the
  existing `run_playoffs` (see `hs/league/season.py main()` for exact calls), then mark the season finished in
  `pack_info` key `season_state` = `finished` and record the champion in `inbox`.

### 2.4 `hs/game/roster.py`: roster moves
- Definitions: a team's **roster** = all players with that `team_id` and status in (`active`,`injured`). **Max roster 26,
  min 20** (constants; read optional overrides from `rules.json` key `roster`: `{"max": 26, "min": 20}`).
  A team must always be able to dress 12 forwards (C/LW/RW), 6 D and 1 G from healthy players.
- Functions: `sign_free_agent(conn, team_id, player_id, day)`, `release(conn, team_id, player_id, day)` (player becomes a
  free agent: `team_id=NULL`), `trade(conn, team_a, give_a: list[int], team_b, give_b: list[int], day)`.  Each logs
  a `transactions` row and validates roster limits for both teams (raise `RosterError` with a clear message).
- `player_value(conn, player_id) -> float`: a single number used for AI decisions.  Use the ratings:
  skaters = mean of (`offensive_awareness`, `passing`, `puck_control`, `shot_accuracy`, `positioning`,
  `defensive_awareness`, `hitting`) ; goalies = mean of (`goalie_positioning`, `reflexes`, `glove`, `blocker`,
  `low_shot_save`, `rebound_control`) ; then scale to roughly 0-100 by `(mean-1)/19*100` and apply an age factor
  from `birth_date` (peak 24-29; -2%/year under 22; -4%/year over 31). Document the formula in the module docstring.
- `ai_manage(conn, team_id, day, rng)`: (a) if the team cannot dress 12F/6D/1G (or has < 2 healthy goalies), sign the best
  available free agent at the needed position; (b) if roster > max, release the lowest-value non-injured player;
  (c) with probability 0.02 per team per day, sign a free agent whose value exceeds the team's worst skater by 5+ and
  release that skater.
- `evaluate_trade(conn, a, give_a, b, give_b) -> (accept: bool, reason: str)`: AI team accepts when the value it
  receives is at least 105% of the value it gives (sum of `player_value`, with a 15% premium for goalies on the
  receiving side if the team has < 3 goalies). The user team is always team_a in the CLI.

### 2.5 `hs/game/cli.py`: the command line
`python -m hs.game.cli <game.db> --env env.json` starts an interactive prompt (use `cmd.Cmd`).  Also support
non-interactive use: `python -m hs.game.cli game.db --env env.json -c "sim week" -c "standings"`.
Commands (short, forgiving, with `help`):
```
new <TEAM_ABBR> [seed]        start a new game in an ingested db (once)
status                        date, record, next game, injuries, roster size, inbox count
sim day | sim week | sim to <YYYY-MM-DD> | sim next | sim season      (stops early on events needing the user)
standings [division|conference|league]
schedule [n]                  next n games for the user's team (default 5)
results [n]                   last n results
roster [forwards|defence|goalies]   name, pos, age, key ratings, value, status; injured players marked
player <name or id>           full attributes + season stats from skater_season_stats
lines                         the lines the engine will use for the user's team (call hs.sim.engine.Team)
injuries                      user's team injuries with return dates
fa [pos]                      best free agents by value
sign <player> / release <player> / trade <ABBR> give <p1,p2> get <p3>
inbox [all]                   unread messages (mark read)
playoffs                      bracket / results once played
quit
```
Player lookup by case-insensitive substring of "first last" or by id; if ambiguous, list matches.  Output is plain
text tables (fixed-width), no colour, no third-party libs.  The CLI must never leave the db half-written: wrap each
command that changes data in one transaction.

### 2.6 Tests (must add)
- Same seed + same commands => identical db contents (compare `games` rows and `transactions`).
- `sim_day` plays only games on that date; second call plays the next day.
- Injured player is excluded from the next game's lineup and returns on `expected_return`.
- A team with < 2 healthy goalies signs a goalie; roster limits enforced on sign/trade (raises `RosterError`).
- `evaluate_trade` rejects a lopsided trade and accepts a fair one.
- `sim season` on the fictional pack reaches the end, runs the playoffs once, and is idempotent if called again.
- CLI scripted run (`-c` commands) exits 0 and prints the standings.

## 3. Performance and robustness
- Fictional pack season (224 games) must run in under ~15 s; the real 32-team season in under ~60 s with events stored.
  Load teams once per day, not once per game.
- Handle: no free agents available, user quitting mid-season (everything already committed), db without `rules`
  (print the message used in `hs/league/season.py`), repeated `new`.

## 4. Out of scope (do NOT do yet)
Player ageing/progression between seasons, drafts, contracts and salary cap, GUI, AI-vs-AI trades, line editing,
in-game injuries, multi-season rollover.  Leave clearly marked TODO comments only where an obvious hook exists.

## 5. Report back with
1. Files created/changed.  2. Exact commands to try it (fictional pack).  3. Test output (`Ran N tests ... OK`).
4. Anything ambiguous you decided, and any place you deviated from this brief.
