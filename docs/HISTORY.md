# History before the save (v41; hs/game/career.py)

A world built from a database export starts with no seasons on file: every veteran looks like a rookie to the waiver
rules, the milestone watch, the Hall of Fame and the all-time leaders, and the Past Drafts screen is empty until the
game holds its first draft. v41 brings the past in.

## From the database file (v43, hs/adapters/db_history.py): the best source
Your `database.db` holds every player's career, season by season and league by league, and every NHL Entry Draft pick
since 1990. With the export folder you built the world from (for the ids), it comes straight in:

* **Every season line**: club, league, regular season and playoffs; GP, G, A, PIM, +/- for skaters; GP, W, L, T/OT,
  shutouts, goals against, saves and minutes for goalies. 9,736 of the bundled world's 9,742 players have one: 178,000
  skater and 18,000 goalie lines, 1,696 players with NHL seasons. Clubs and leagues outside the world (U18 teams, the
  MHL, the Allsvenskan...) keep their names on the player page.
* **Past drafts**: 3,492 NHL Entry Draft picks (1990-2026) of players still in the database, linked to players in the
  world, by name otherwise; Arizona's and Atlanta's picks count for Utah and Winnipeg. Draft rights the world holds get
  their pick number.
* Seasons go on file like seasons the game played (marked `source='history'`): Career stats, the all-time leaders and
  best single seasons, waivers, milestones, the Hall of Fame, arbitration and UFA status (pro and NHL seasons), the draft
  board's "last season". One exception: the league's view of a player's value (the trade market's production blend)
  uses only seasons the game plays, as before, so the v39 trade calibration stands (a test season: 80 in-season trades
  either way).
* Where: File > Import Database (give the database file, or leave it in the export folder), File > Editor > Import /
  Export > "From the database file", or `python -m hs.adapters.db_history <database.db> <export folder> <world.db>
  --apply`. Only seasons before the save's first season; importing again replaces the earlier import. A player given
  NHL seasons this way drops his games-only total below.
* The bundled world ships with it imported. Checked against real careers: Suzuki 2024-25 82 GP 30 G 59 A,
  Hellebuyck 2024-25 47-12-3 with 8 shutouts, Crosby 1,420 GP 654 G 1,107 A, McDavid 2022-23 153 points.

How the file was read (two fixed-width sections; the layouts are in the adapter's docstring) came from a community
editor's column names, checked against those careers. Champions and award winners sit in variable-length sections
not yet decoded.

## Careers (`career_prior`)
One row per player: NHL games, goals, assists, wins, shutouts, playoff games and seasons from **before the first
season on file**. Everything that adds up a career adds it in:

| Where | What it adds |
|---|---|
| Waivers (`waivers.nhl_games`) and the world's games count (`world.nhl_games`: exemptions, retirements) | games |
| Milestones (Leagues > Milestones) | games, goals, assists, points; wins and shutouts for goalies |
| Hall of Fame score (`legacy.career`) | games, goals, assists; wins and shutouts |
| All-time leaders (Stats > League history) | points (with seasons, games, goals, assists), and a new "Most NHL games" |
| Past Drafts | a drafted player's NHL games |
| The player page | Career stats: "NHL career before this save" |

Sources
* **The M3 player profile export** (`player_profiles_plain_english_m311.csv`): its `career_nhl_games_raw` and
  `career_nhl_seasons_raw`, matched by name (accents and punctuation ignored) and birth date. It covers 96 players
  with NHL games (95 match the bundled world; it has no goals or assists, and some stars are missing from it). The
  bundled world ships with them already imported. File > Editor > Import / Export > "History before this save",
  or `career import <file> [apply]`.
* **The editor**: the career columns in the player CSV (`career_gp, career_g, career_a, career_w, career_so,
  career_po_gp, career_seasons`) and the "NHL career before this save" box in the player editor.

A world that already has past seasons on file (the data-pack worlds) would count those games twice, so the M3 import
leaves alone any player with recorded NHL seasons.

## Past drafts (`draft_picks`, `past_draft_names`)
The export has no drafts, so they come from a CSV: `draft_year, round, overall, team, player`, with `player_id` or
`birth_date` optional (headers like year, pick, club, name, dob work too; round is worked out from the pick if left
out). A player in this world is linked: the draft log shows where he is now, his NHL games and value. A player who is
not keeps his name on the log. Drafts the game held itself, and this year's draft, are never touched; rows that are
already on file are skipped. File > Editor > Import / Export, or `drafts import <file> [apply]`.

## Past seasons, line by line (v42)
A CSV with one row per player, season, league and club: `player_id` (or `player` with `birth_date`), `season`
(2019 or 2019-20), `league` (abbreviation or name), `team` (optional), `split` (RS or PO, default RS), then `gp, g, a,
pim, plus_minus, sog` for skaters or `gp, w, l, otl, so, ga, sa` for goalies. The lines go on file like seasons the game
played: the player's Career stats, the leaders, waivers, milestones and the Hall of Fame. Only seasons before this one;
importing the same lines again replaces them. A player given NHL seasons this way drops his games-only total from the
M3 profiles, so nothing counts twice. File > Editor > Import / Export, or `career seasons import <file> [apply]`.

The database export does not yet carry decoded season-by-season history (its history table is still raw fields); this
importer is ready for when it does.

`career <player>` shows what is on file for him.

## Not yet
Past champions and award winners from the database (variable-length sections, not yet decoded), past award winners and champions, draft rights from
imported drafts (a player's rights still come from the world's `draft_rights`).
