# Hockey Manager: an open-source hockey management simulation

**A single-player ice hockey general manager game for your desktop.** You run an NHL-style club's hockey operations (roster,
lines, contracts and the salary cap, trades, the draft, scouting, staff, the dressing room, the owner, the money and the
press) while a whole hockey world plays on around you: AHL and ECHL farm clubs, junior, college and European leagues, all
simulated game by game. Written in Python with SQLite saves. No accounts, no internet, no ads. Free, MIT licensed.

If you like text-and-stats hockey GM games, franchise modes or sports-management sims, this is a moddable, offline one you
can read, edit and extend. It ships with a fully **fictional league** (invented clubs and players), and lets you **build your
own league or roster from a spreadsheet**.

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue) ![licence MIT](https://img.shields.io/badge/licence-MIT-green) ![no dependencies](https://img.shields.io/badge/dependencies-none-lightgrey)

## Play in two minutes

You need Python 3.9 or newer. There is nothing to install: the game uses only the standard library.

```bash
git clone https://github.com/jeremylegere-wq/hockey-manager.git
cd hockey-manager
./play.sh                 # Windows: double-click PLAY_WINDOWS.bat
```

The first run builds the fictional world (a few seconds) and offers to install a small window component (pywebview) next to
the game; say no and it opens in a Chrome/Edge/Chromium app window or your browser instead. Then: **New Standard Game**, pick
a club, and press Space to play a day. Your careers are saved as plain `.db` files in `saves/`.

No window? `python3 -m hs.ui.server --saves saves --template auto --open` serves the same game to your browser.

New to it? Read **[docs/MANUAL.md](docs/MANUAL.md)**, the player's manual (a first-season checklist is at the end).

## What you can do

* **Run the club.** Roster, depth chart, lines with priority-list lineups, power-play and penalty-kill units, goalie start
  rules, twelve tactical settings with counters, twelve tactical roles with fit scores, line chemistry.
* **Manage contracts and the cap.** Cap and floor, entry-level deals, RFAs and UFAs, qualifying offers, arbitration, offer
  sheets, buyouts, salary retention, long-term injured reserve, waivers, no-trade clauses, and contract talks with agents.
* **Trade.** Two- and three-club deals, picks and conditional picks, retention, rumours, a trade deadline, and AI clubs that
  trade with each other.
* **Draft, scout and develop.** A scouting network by region, central scouting lists, a mock draft, a draft room with a pick
  clock, prospects, training focus, mentors, players who grow during the season, college recruiting.
* **Live in a whole hockey world.** 13 leagues play real seasons around you; international hockey, expansion drafts, the
  record book, awards, the Hall of Fame and a career legacy score.
* **Answer to the owner.** Board confidence, ultimatums, directives, owner goals with deadlines, quarterly finance reviews.
* **Run the money.** Gate and ticket prices, sponsors, budgets, a chart of accounts with a profit and loss report, budget
  against actual and last year, a cash statement, renovations, and a new arena paid for with the owner's money and a loan.
* **Be a person, not a menu.** Your own GM (ratings, reputation, start unemployed, a job market), staff, an assistant GM,
  morale, cliques, captaincy, press conferences, a news feed, hidden player attributes and personalities.
* **Watch it.** A 2D replay of every game (all players and the puck), box scores, recaps, analytics (expected goals,
  Corsi, shot quality), game logs and season pages.
* **Make it yours.** Build a league in a spreadsheet, edit any player or club, bulk import and export CSV, commissioner tools,
  schedule import, your own logos, quickstarts, challenge mode, a French interface.

Full feature list by version: [docs/ROADMAP.md](docs/ROADMAP.md). One page per system is in [docs/](docs/).

## The fictional world

Nothing real ships with the game. The mock world (`python -m hs.tools.make_mock_world`) is generated from a seed:

| | |
|---|---|
| Top league | the Premier Hockey League: 32 invented clubs, 2 conferences, 4 divisions, a salary cap, an 84-game season, a 7-game playoff |
| Around it | AHL- and ECHL-style farm leagues (one affiliate per club), three major junior leagues, a college league, six European leagues |
| People | about 8,000 generated players with 40-odd ratings, personalities, potential and development curves; draft classes and draft rights |
| Realism | calibrated to real scoring: about 5.7 goals, 28 shots and 6.9 penalties a game; clubs spread about 0.6 goals a game apart |

Use `--seed N` for a different league. The same seed gives the same world.

## Build your own league, roster or import one

You do not have to play the fictional world.

* **From a spreadsheet:** copy `packs/example_fictional/`, edit the CSVs, validate, build. Clubs, players, ratings, contracts,
  schedule rules.
* **Change one roster:** turn on commissioner mode and edit any player or club in the game, or export players to CSV, edit in
  Excel, and import them back (with a preview first). `docs/examples/new_players.csv` is a starting point.
* **Bring your own data:** importers read a Franchise Hockey Manager CSV export, MoneyPuck season summaries (it derives ratings
  from results), an export of a community player database, and a CSV of contracts. These are code only: the data stays yours,
  stays on your computer, and is never published.
* **Share a fictional league:** a pack of invented clubs and players can be published under any licence you like.

Step by step, with every command tested: **[docs/BUILD_YOUR_OWN.md](docs/BUILD_YOUR_OWN.md)**.

## Documentation

| | |
|---|---|
| [docs/MANUAL.md](docs/MANUAL.md) | Player's manual: start a career, a season, every area of the game, tips, FAQ |
| [docs/BUILD_YOUR_OWN.md](docs/BUILD_YOUR_OWN.md) | Make your own league or roster, import data, share packs |
| [docs/DATAPACK_SPEC.md](docs/DATAPACK_SPEC.md) | The pack file format |
| [docs/FINANCE.md](docs/FINANCE.md), [BOARD.md](docs/BOARD.md), [TACTICS.md](docs/TACTICS.md), [TRADES.md](docs/TRADES.md), [DRAFT.md](docs/DRAFT.md) | System guides |
| [docs/ALGORITHMS.md](docs/ALGORITHMS.md) | The mathematics behind every AI: match engine, valuation, trades, free agency, draft, board, finance, people |
| [docs/SIM_CALIBRATION.md](docs/SIM_CALIBRATION.md) | How the match engine is calibrated |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What exists, what is next |
| [docs/DEFECTS.md](docs/DEFECTS.md) | Bugs found and fixed |

## Report a bug

Bugs are how this gets better. Email **jeremy.legere@gmail.com** or open a GitHub issue. In the game, **Help > Report a bug**
fills in your version, system and screen and opens an email. Please include what you did, what you expected, what happened,
and, if it is about a career, the save file from `saves/` (a plain `.db` file holding only that career). A "Traceback" in the
terminal is the most useful thing there is. Details: [CONTRIBUTING.md](CONTRIBUTING.md).

## For developers

Standard library only (Python 3.9+), SQLite saves, a stdlib HTTP server and vanilla JavaScript with no build step. The same
`hs.game.cli.CLI` drives the terminal and the UI, so every action is a command line and the game has one set of rules.

```bash
python3 -m unittest discover -s tests        # about 410 tests; the whole suite takes several minutes
python3 -m hs.game.cli my.db --env data/env_default.json -c "new PHM 7" -c "sim week" -c "standings"
```

Layout: `hs/sim/` the seeded match engine and 2D rink; `hs/league/` schedules, standings, playoffs; `hs/game/` the day-by-day
game (contracts, trades, draft, finance, board, people); `hs/ui/` the server and front end; `hs/adapters/` and `hs/ratings/`
importers; `hs/tools/` world builders; `docs/` one page per system. Same seed plus same commands gives an identical database.

## Credits and licence

Design, architecture and lead development: Jeremy Legere. Built with AI coding assistants under his direction (see
Help > Credits). MIT licensed ([LICENSE](LICENSE)). Third-party notices and what the game does not ship:
[THIRD_PARTY.md](THIRD_PARTY.md). This is an independent hobby project, not affiliated with or endorsed by any league, club,
player, players' association or commercial game.

<sub>Search terms: hockey management sim, hockey manager game, ice hockey GM simulator, NHL-style franchise mode, hockey
general manager game, text-based hockey simulation, sports management game, offline single-player sports sim, open-source
hockey game, moddable hockey sim, hockey database editor, custom hockey league, Python hockey simulation, salary cap
simulator.</sub>
