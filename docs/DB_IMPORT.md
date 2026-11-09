# Importing your own database (v38)

The game can build its world from your own plain-English export of a classic hockey-management database (the
community-maintained player database and your exporter's CSVs). **Personal use only**: the export, the pack built
from it and any game built from that pack hold that database's data. They stay on your computer (`worlds/`, `packs/`
and `save/` are git-ignored) and must not be published or shared. No such data ships with this program; only the code
that reads your copy does.

## How

In the game: **File > Import Database...** (or **Import a database...** on the World step of a new career). Give the
export folder (the exporter's top folder is fine; it is searched) and a name. The world appears on the World step of
File > New Game.

From the command line:

    python -m hs.adapters.db_export <export folder> packs/my_world      # build the pack (CSV files you can edit)
    python -m hs.ingest packs/my_world worlds/My_world.db               # build the world
    python -m hs.sim.validate <a career started in it> save/env_2025.json --seasons 3   # check the engine on it

The import reads four files (newest milestone first): `players_hockey_profiles_*.csv`, `staff_normalized.csv`,
`clubs_lookup.csv`, `player_rights_normalized.csv`. It never reads the original binary database.

## The player model (hs/attributes.py)

v38 makes the ratings the game's own player model. Two layers:

| Layer | Table | What | Edited by |
|---|---|---|---|
| Ratings (native) | `player_ratings` | 42 attributes 1-20 (15 technical, 12 mental, 10 physical, 5 goalkeeping), current and potential ability 1-200, six position ratings, offensive and defensive role | imports, editors, development |
| Engine attributes | `player_attributes` | the 40 composites the match engine, valuation and the AI read | never: derived from the ratings |

Each engine attribute is a fixed recipe of ratings (`COMPOSITES`), for example puck control = 0.6 stickhandling +
0.4 deking; offensive awareness = 0.4 movement + 0.35 anticipation + 0.25 creativity; shot blocking = 0.5 bravery +
0.3 positioning + 0.2 work rate; low-shot saves = 0.4 one-on-ones + 0.3 agility + 0.3 reflexes.

**Scale.** At import an affine map per engine attribute is fitted to the NHL's dressed players so each one has the
mean and spread the engine was calibrated on (`ENGINE_TARGET`, from the reference pack). The map is stored in the
save (`pack_info` `engine_scale`).

**Level anchored on ability.** The database's current ability is its curated judgement of how good a player is; the
ratings say what kind of player he is. The engine attributes keep the shape of his ratings and are shifted together
so his engine overall is the one his ability stands for (`derive`). Ability maps onto the engine overall's calibrated
spread: NHL skaters 10.49 +- 0.86, goalies 10.51 +- 0.66 (`fit_ability`, `OVERALL_TARGET`). Without this the
engine overall correlated only 0.65 with ability; with it, 0.99, and the league plays at the real NHL's totals.

**Development.** Each summer the development model decides how far a player's engine overall should move (age,
potential, coaching, coachability, training focus, as before). In an imported world that change is spread over the
ratings that develop (the body's ratings age first, the mind's last), current ability moves with what the ratings now
stand for, and the engine attributes are re-derived. Potential ability follows the development profile's ceiling.
Worlds built on engine attributes (the bundled NHL world, generated worlds, older saves) keep developing their engine
attributes, and their ratings are back-filled and mirrored from them, so every player has both layers.

**What is shown.** The player screen's Ratings tab shows the ratings (technical, mental, physical; goalkeeping for
goalies), ability as stars (potential only for your own players: your staff can judge their ceiling), the position
ratings and the role ratings, and on request the engine attributes.

## Field by field

| Database field | Goes to |
|---|---|
| 42 attributes, current/potential ability, position and role ratings | `player_ratings` (attributes clamped to 1-20; a negative potential is a range code: about \|value\| x 10) |
| primary position | the best of the six position ratings (defence when left or right defence is best) |
| height, weight, hand, date of birth, nationality | `players` |
| plays for / contracted to | the club he plays for (`club_id`) and the NHL organisation that holds his contract (`team_id`) |
| salary, contract expiry, first NHL contract | `contracts` (salary as the cap hit, at least the league minimum; entry-level when the first NHL contract is recent, he is 25 or younger and paid under $1.1M) |
| NHL rights to an unsigned player | `draft_rights` (draft year estimated as birth year + 18) |
| adaptability, ambition, determination, loyalty, pressure, professionalism, sportsmanship, temperament | personality (professionalism, ambition, loyalty; resilience = pressure; patience = adaptability; ego and role tolerance from ambition, sportsmanship, adaptability and loyalty; leadership = the leadership rating) and hidden attributes (consistency, big games = important matches, injury proneness, temperament, sportsmanship, coachability = determination, greed from ambition and loyalty), re-centred on the game's scale so the league's totals do not move |
| club league and division, capacity, market size, reputation, founding year, city, arena | teams and `club_profile` (the arena's capacity and the market drive the finances) |
| rivals 1-3 | rivalry seeds (30, 25, 20 points; hs/game/rivalry.py) |
| captain and alternates | the leadership group |
| NHL clubs' head coaches, coaches, scouts, physios, directors of personnel, general managers | staff names (their ratings are generated: the staff attribute block is not decoded yet) and the AI GMs' names |

Leagues imported: NHL, AHL, ECHL, KHL, SHL, NL, Liiga, Extraliga, DEL, NCAA, OHL, WHL, QMJHL and USHL (`DIVISIONS` in
the adapter; add a row to bring another league in). Players playing in other leagues are left out unless an NHL club
holds their contract or rights; the best 600 unattached players of playing age are the free-agent pool. Players born
after the season minus 15 (the database's pre-generated future players) are left out; the game makes its own draft
classes.

NHL rosters: of an organisation's players, the best 23 by ability (at least 13 forwards, 7 defencemen and 2 goalies)
are on the NHL roster and the rest play for the AHL affiliate.

## Calibration (v38)

Three seeds, three seasons each, AI tactics, line chemistry from the save; real NHL 2024-25 in brackets:
goals a team-game 2.85-2.90 (2.88), shots 27.1-27.3 (27.6), save % .894-.895 (.896), penalties 6.90-7.02 (6.90),
power-play goals 1.10-1.12 (1.10), goal-difference-per-game spread .60-.61 (.60). The import pins two constants in
its rules (`"engine": {"pp_scale": 0.90, "pen_scale": 1.03}`): its special-teams ratings ran 4% hot on the shared ones.
A full season and summer on the imported world keeps the league's ability where it was (mean 146.6 to 146.7, spread
17.5 to 17.8).

## Not yet

Statistics history (your choice: careers start in the save), staff ratings, club finances beyond capacity and market,
draft pick numbers, contract clauses and two-way terms, international play.

## Career history and past drafts (v43)
Give the database file too (the Import Database window, or leave `database.db` in the export folder) and the world gets
every player's career season by season and the past NHL drafts (hs/adapters/db_history.py, docs/HISTORY.md).
