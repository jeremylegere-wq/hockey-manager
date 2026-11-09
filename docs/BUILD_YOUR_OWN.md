# Build your own league, roster or world

Everything the game plays comes from a **world**: a SQLite file built from a **data pack**, a folder of CSV files you can edit
in a spreadsheet. The game ships a fictional world; this page shows how to make another, change a roster, or bring in data
you already have. Every command here was run against this version.

All commands run from the game folder.

## 1. The quick ways

| You want | Do |
|---|---|
| A different fictional league | `python3 -m hs.tools.make_mock_world --out worlds/Another.db --seed 7` |
| To change a few players or clubs | turn on commissioner mode and use File > Editor (section 4) |
| To edit lots of players in Excel | export CSV, edit, import (section 4) |
| Your own clubs and players from scratch | copy a pack and edit the CSVs (section 2) |
| Real names from your own data | an importer (section 5) |

Any `.db` in a `worlds/` folder next to `saves/` shows on the **World** step of a new career.

## 2. Make a league from a spreadsheet

Start from a working pack. `packs/example_fictional/` is 8 clubs; `python3 -m hs.tools.make_mock_league packs/my_league` makes
32 clubs with contracts and a cap.

```bash
cp -r packs/example_fictional packs/my_league      # or make_mock_league (above)
# edit packs/my_league/*.csv in a spreadsheet: save as CSV, UTF-8
python3 -m hs.datapack packs/my_league             # validate: it lists every problem with the file and row
python3 -m hs.tools.build_world packs/my_league packs/my_world --fictional
python3 -m hs.ingest packs/my_world worlds/My_League.db
```

`build_world` adds the leagues around yours (farm, junior, college, Europe) with invented clubs and players. Leave that step
out and ingest the pack directly (`python3 -m hs.ingest packs/my_league worlds/My_League.db`) for a one-league world. Then
**New Standard Game**, choose the world on the World step, pick a club.

### The files

| File | Holds | Required |
|---|---|---|
| `manifest.json` | name, version, `season_start_year`, `redistributable`, `contains_real_names`, licence | yes |
| `leagues.csv` | `league_id, name, abbr, level, games_per_team` | yes |
| `teams.csv` | `team_id, league_id, name (city), nickname, abbr, conference, division, primary_color, secondary_color, logo` | yes |
| `players.csv` | `player_id, first_name, last_name, birth_date, position (C LW RW D G), shoots, height_cm, weight_kg, nationality, team_id (blank = free agent), status` | yes |
| `attributes.csv` | one row per player: 1-20 ratings (skaters and goalies have different sets) and `potential` | yes |
| `contracts.csv` | `player_id, team_id, start_year, years, cap_hit, contract_type, no_trade` | no |
| `rules.json` | season dates, schedule format, points, tiebreakers, playoff format | no |
| `history/*.csv` | past seasons' statistics | no |

The full column list and the rating groups are in [DATAPACK_SPEC.md](DATAPACK_SPEC.md); the schedule and playoff options in
[LEAGUES_AND_SCHEDULES.md](LEAGUES_AND_SCHEDULES.md). Colours are `#rrggbb`; a `logo` is a PNG path inside the pack.

### Tips

* **Ratings 1-20.** The league the engine is tuned for has dressed players averaging about 10.5 with a spread of about 0.7 on
  the player's overall (the mean of his key ratings). If your players are much stronger or more spread out than that, scoring
  and the gap between clubs will be off. Check a season: `python3 -m hs.sim.validate <a career in your world> data/env_default.json --seasons 3`.
* **A goalie needs the goalie ratings, a skater the skater ratings.** The validator tells you what is missing.
* **Every club needs 12 forwards, 6 defence and 2 goalies** to play; 23 or more is comfortable.
* **Cap hits** should sum to a little under the cap. The cap and floor are in `rules.json` and can be changed in the commissioner
  tools.
* **Number of games and the schedule** must agree: the validator checks that the schedule format gives every club the number of
  games `leagues.csv` says.
* **IDs** are integers, unique inside their file. A free agent has no `team_id`.

## 3. A different fictional world, same shape

`python3 -m hs.tools.make_mock_world --out worlds/Name.db --seed N` builds the bundled kind of world from a seed. The names
come from `hs/leaguedata/fictional.py` (clubs, towns) and `hs/worldgen.py` (player names by nationality); edit those pools for
a different flavour. `hs/tools/make_mock_league.py` shows how players, ratings and contracts are generated.

## 4. Edit what you have

**In the game**: File > Editor. Turn on commissioner mode (Settings, or the console command `editor on`). It marks the save as
edited, for good, so achievements and GM score say so. Then:

* **Players**: bio, club, status, potential, contract (cap hit, end, clause), personality, every rating.
* **Clubs**: name, nickname, abbreviation, conference, division.
* **Console**: `edit Suzuki: passing=15 cap_hit=8m team=MTL`.
* **League tools** (League > Commissioner): trade any clubs, take over any club, fire a GM or coach, injure or heal, change
  the cap, the roster limits, the deadline, import a schedule.

**Bulk, in a spreadsheet**: File > Editor > Import / Export. Export your club, the league or everyone as CSV; edit; import. The
importer shows a **preview** (what changes, what is new, every problem with its row) and writes only when you apply. Columns
are matched loosely (`DOB`, `Surname`, `Club` work). A row with no match and a name, birth date and position creates a
player; `docs/examples/new_players.csv` is a working example (three new players). The columns and aliases are in
[EDITOR.md](EDITOR.md).

**Start a career from your edited world**: File > Save as quickstart (at the start of a season, before a game is played).
New careers can start from it. See [QUICKSTARTS.md](QUICKSTARTS.md).

## 5. Bring in data you already have

These read **your copy** of data. The game ships none of it. A pack built from them holds other people's data: it is marked
`redistributable: false`, stays on your computer and is never to be published (the folders `packs/`, `worlds/`, `saves/` and
`save/` are git-ignored for this reason).

| Source | Command | Notes |
|---|---|---|
| A Franchise Hockey Manager CSV export | `python3 -m hs.adapters.fhm_csv <export folder> packs/fhm` | converts ratings to the game's model; potential stars map to 1-20 |
| MoneyPuck season summaries (`skaters_<year>.csv`, `goalies_<year>.csv`, free for non-commercial use) | `python3 -m hs.ratings.moneypuck <folder> packs/mp --season 2025` | derives ratings from results; add `--structure nhl_2025_26` for the real league's clubs and rules |
| An export of a community player database | `python3 -m hs.adapters.db_export <export folder> packs/db` | or File > Import Database; [DB_IMPORT.md](DB_IMPORT.md) lists the files and the mapping |
| A CSV of contracts (copied from a cap site into a spreadsheet) | `python3 -m hs.adapters.contracts_csv contracts.csv --pack packs/mp` | loose headers: Player, Cap Hit, Team, Expiry |
| Careers and past drafts | File > Editor > Import / Export, `career import` | [HISTORY.md](HISTORY.md) |

After any of these: `python3 -m hs.datapack packs/x`, then `python3 -m hs.tools.build_world packs/x packs/x_world`, then
`python3 -m hs.ingest packs/x_world worlds/X.db`. MoneyPuck data also needs a league environment of its own:
`python3 -m hs.sim.env <folder> --season 2025 --out save/env_2025.json` (see `data/README.md`).

**Write your own adapter.** An adapter is any script that writes the CSV files of section 2. `hs/adapters/fhm_csv.py` is a
short, readable model: read the source, map its ratings to the engine's attributes (`hs/attributes.py` is the one list of
them), write a pack.

## 6. Share a league

A pack of **invented** clubs and players can be shared freely: set `redistributable: true`, `contains_real_names: false` and a
licence in `manifest.json`, and zip the folder. Others unzip it into `packs/`, run `hs.ingest`, and play. To have yours listed,
open a "Share a league" issue or email jeremy.legere@gmail.com.

Do not share packs with real players, clubs, logos or anyone else's data. Real names and marks generally need a licence from
the leagues and players' associations; see `THIRD_PARTY.md`.

## 7. If something goes wrong

* `hs.datapack` prints every problem with its file and row. Fix them all, then run it again.
* "No template world to start from": build one (`python3 -m hs.tools.make_mock_world`) or put a world in `worlds/`.
* Scoring too high or too low in your world: see the tips in section 2 and [SIM_CALIBRATION.md](SIM_CALIBRATION.md); the formulas are in [ALGORITHMS.md](ALGORITHMS.md).
* Anything else: [CONTRIBUTING.md](../CONTRIBUTING.md) says what to send. jeremy.legere@gmail.com.
