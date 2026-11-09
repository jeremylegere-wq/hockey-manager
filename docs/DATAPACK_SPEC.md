# Data pack format 0.1

A data pack is a folder of plain CSV files plus `manifest.json`. It is the only way data enters the
engine, so anyone can build a custom league (or write an adapter for another source) without touching code.

- Encoding UTF-8, comma separated, first row is the header, blank cell = no value.
- IDs are integers, unique within their file. Any column not listed here is ignored (with a warning).
- Ratings are integers 1-20. Dates are `YYYY-MM-DD`. Money is whole currency units per year.
- Validate before use: `python -m hs.datapack <pack_dir>`. Build a game: `python -m hs.ingest <pack_dir> game.db`.

```
my_pack/
  manifest.json
  leagues.csv        required
  teams.csv          required
  players.csv        required
  attributes.csv     required
  rules.json         optional (season dates, schedule format, tiebreakers, playoffs; see LEAGUES_AND_SCHEDULES.md)
  contracts.csv      optional
  history/skater_seasons.csv   optional
  history/goalie_seasons.csv   optional
```

## manifest.json (all keys required unless marked)

| key | type | notes |
|---|---|---|
| format_version | string | must be `"0.1"` |
| name, version, source | string | `source` e.g. `generated`, `fhm_csv`, `hand_made` |
| season_start_year | integer | the season the pack starts in (2026 = 2026-27) |
| redistributable | boolean | `false` = personal use only; the tools warn on ingest |
| contains_real_names | boolean | real people / clubs / league names |
| license, description, author | string, optional | |

## leagues.csv
`league_id`, `name`, `abbr` required; optional `country`, `level` (1 = top), `games_per_team`.

## teams.csv
`team_id`, `league_id`, `name` (city), `nickname`, `abbr` required; optional `conference`, `division`,
`primary_color`, `secondary_color` (`#rrggbb`), `logo` (relative path to a PNG in the pack).

## players.csv
`player_id`, `first_name`, `last_name`, `birth_date`, `position` (`C LW RW D G`) required.
Optional: `shoots` (L/R), `height_cm`, `weight_kg`, `nationality`, `team_id` (blank = free agent),
`status` (`active` default, `retired`, `prospect`), `headshot` (relative path).
Retired players need no attributes row; they exist so history rows can point at them.

## attributes.csv
One row per non-retired player: `player_id`, the attribute columns, and optional `potential` (1-20).
Skaters need every skater attribute; goalies need every goalie attribute (the other set may be blank).

| group | attributes |
|---|---|
| skating | speed, acceleration, agility, balance, endurance |
| offence | shot_accuracy, shot_power, passing, puck_control, offensive_awareness, net_presence, faceoffs |
| defence | checking, stick_checking, shot_blocking, positioning, defensive_awareness |
| physical | strength, hitting, toughness |
| mental | aggression, bravery, determination, teamwork, leadership, composure, professionalism, mental_toughness |
| goalie | goalie_positioning, reflexes, glove, blocker, rebound_control, recovery, poke_check, low_shot_save, goalie_puck_handling, goalie_passing, goalie_skating, goalie_stamina |

The model lives in `hs/attributes.py`, the single source of truth; the database schema is generated from it.

## contracts.csv
`player_id`, `team_id`, `start_year`, `years`, `cap_hit` required; optional `contract_type`
(`standard`, `entry_level`, `two_way`), `no_trade` (0/1).

## history/skater_seasons.csv, history/goalie_seasons.csv
`player_id`, `season` (start year, 2011 = 2011-12), `team_id`, `league_id`, `split` (`RS` regular season,
`PO` playoffs, `PS` pre-season) required. Skaters: `gp g a pim plus_minus sog toi_sec`.
Goalies: `gp gs toi_sec w l otl so ga sa`. `team_id` / `league_id` may refer to teams that no longer exist.
Rows whose player is not in `players.csv` are skipped with a warning.

## rules.json (optional)
Season dates, schedule format, points, tiebreakers and playoff format. If present, every team needs a `conference` and
`division`, and the rules are checked against the structure. Details: `docs/LEAGUES_AND_SCHEDULES.md`.

## Writing your own custom league
Copy `packs/example_fictional/`, edit the CSVs in any spreadsheet, validate, ingest.


## World additions (optional, schema v3)
- `teams.csv`: `parent_team_id` (farm/minor club -> NHL organisation).
- `players.csv`: `club_id` (club he plays for; defaults to `team_id` for active players). `status` may be
  `prospect` (signed by an NHL organisation, playing below the NHL).
- `draft_rights.csv`: `player_id, team_id[, draft_year, overall_pick, expires_year]`.
- `development.csv`: `player_id, potential, peak_age, decline_age, growth_rate, decline_rate` (hidden profiles;
  generated at game start for players without one).
- `rules.json` `"world": {"leagues": {league_id: {abbr, kind, level, games, mean, roster, age_min, age_max}}}`.
Only the top league (lowest `level`) is scheduled and needs conference/division.
