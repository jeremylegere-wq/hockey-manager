# Local web UI (hs/ui)

v28: the game runs in its own window and uses the classic desktop look; see docs/DESKTOP.md for the window, the
menus, the theme, settings and the new screens (calendar, free agent centre, prospects, development).

    python -m hs.ui.server --saves saves --template world.db --env env.json [--port 8765] [--open]   # title screen
    python -m hs.ui.server game.db --env env.json [--port 8765] [--open]                            # one save

Then open http://127.0.0.1:8765/ (if the port is taken, for example by Hockey Night, the server uses the next free
one and says so). With `--saves` the UI opens on a title screen: continue, start a new career (pick any club from
`--template`, a built world with no game started) or load one. `play.sh` / `PLAY_WINDOWS.bat` in the play kit do
this for you.

## How it is built
- `hs/ui/server.py`: stdlib `ThreadingHTTPServer` on 127.0.0.1 (local only, no authentication). It serves the static
  front end and two kinds of API call:
  - `GET /api/<view>` returns JSON built by `hs/ui/api.py` (read only).
  - `POST /api/command {"line": "sim week"}` runs one CLI command line through the same `hs.game.cli.CLI` object the
    terminal uses and returns `{ok, output}`. Every action in the UI is one of these lines, so the rules, checks and
    messages are identical to the terminal and there is no second copy of game logic.
- One SQLite connection is shared by the request threads; a lock serialises every read and command.
- `hs/ui/static/`: `index.html`, `style.css` (light and dark), `app.js` and `replay.js` (vanilla JS, canvas, no build step, no CDN).

## Saves (hs/ui/saves.py)
Every career is one `.db` file in the saves folder, and the game writes to it as you play (each command and each
simulated day is committed), so there is no "save" button to forget. The Saves menu in the title bar: **Save as**
(a snapshot copy, optionally switching to it), load, rename and delete other careers, **New career**, and **Main
menu** (closes the career and returns to the title screen). A save is a plain file: copy it to back up a career or
move it to another computer.

## The sim centre (hs/ui/simjob.py)
Day, Week, Next game and Rest of season run in a background thread one day at a time (the same `sim_until` as the CLI,
so the stop rules are the CLI's: anything but Rest of season stops early when you are needed). A full-screen broadcast
view shows the day's final scores, your game's box score as it comes in (score, story, scoring, three stars, top
skaters), your conference's wild-card table, your club's alerts, and news and score tickers. **Stop** finishes the day
in progress and stops; **Watch / Normal / Fast / Instant** set the pace (1.6, 0.6, 0.15 or 0 seconds a day; remembered
in your browser). While it runs, commands are refused; screens still read.

## Screens
| Screen | Shows | Actions |
|---|---|---|
| Dashboard | record, payroll and cap room, board confidence and owner, objectives, players needing attention, locker room and leaders, club news, next games, recent results, division table, league news | sim controls |
| Roster | waiver wire; forwards / defence / goalies with key ratings, value, scoring, ice time, morale, cap hit, expiry, waiver status; NHL roster or whole organisation (docs/WAIVERS.md) | send down (confirms when waivers are needed), recall, claim |
| Player card (pop-up) | from the trade screens, sim centre, analytics and news archive: ratings, season line, contract, fair value | full profile, contract talks |
| Contract talks (pop-up) | his agent (name, agency, style), patience and mood, what matters to him, the conversation, his ask at every term, our fair value (docs/NEGOTIATION.md) | offer (AAV slider, term, no-trade clause), offer his ask, walk away |
| Player | profile, scouts' projection, contract value (year-by-year worth, surplus, grade, chance positive), attributes by group, career stats, contract history, event history; for your players morale components, personality, his concern | respond to a concern (four tones or a binding promise), send down / recall, captain, release, extension offer |
| Contracts | payroll against cap and floor, contracts against the 50 limit, multi-year outlook, retained salary and buyouts, every contract with expiry status, asking price and value grade | via player screen |
| Offseason | phase stepper; draft board when you are on the clock; your picks; upcoming free agents (rights phase, with what they will ask at noon); expiring contracts with QO, ask, arbitration status and decisions; free agents; unsigned draft picks | next phase, draft, qualify, decline, club arbitration, walk away, re-sign at ask, sign, sign ELC |
| Scouting | next draft as your scouts see it, any time of year: projection, height, nationality, last season, club, flags (undersized, KHL contract, seen less, overage); your director's philosophy | |
| Standings | broadcast style (after Hockey Night): wild card (division leaders + wild cards with the cut line), divisions, league; GP W L OT PTS P% RW ROW GF GA DIFF L10 streak home away; clinch marks x y z p e (conservative: worked out from points and games left) | playoff odds |
| Analytics | League (xGF/xGA map, PDO and points against expectation, team table), Team (rolling xGF% / GF% / CF%, goals against xG, shot quality for and against, who drives the offence, skater table), Players & goalies (goals against ixG, GSAx), Contracts (cap hit against production, points per $1M), Playoff odds (2,000 simulations); docs/ANALYTICS.md | |
| Lines | forward lines, pairs, goalies, power-play and penalty-kill units, one dropdown per slot (docs/LINES.md); the Team system panel: fit, execution and value of each system, and the owner's preferred identity (docs/TACTICS.md) | save, automatic, Play this |
| Staff | your staff with ratings, salary and contract; what they do for you (scouting error, development, injury length); the staff market by role | hire, dismiss |
| Board | ultimatum (games and points left), confidence with its weekly trend, the hot-seat trigger score and its formula, owner's directives, objectives this and past seasons, every review with its reasons, the owner (name, archetype, vocalness, analytics, traits), GM vacancies (docs/BOARD.md) | |
| Trade | The proposal panel shows who is in the deal, as player cards with value and cap, for each side (and each club in a three-way); clicking a row adds or removes him. Two clubs: pick a club; your players and picks against theirs with values, core / block / just-moved flags; their verdict updates live; offers to you. Three clubs: pick two clubs, send each asset to either of the others, both verdicts update live (docs/TRADES.md). Names open the player card. | propose, what would it take, block, accept / decline offers |
| Schedule | upcoming games and results | open a game: recap and 2D replay |
| News | headlines, game recaps, social feed, power rankings (docs/MEDIA.md); Archive: any season's news by month and type (headlines, trades, signings, injuries, front office, draft, retirements), your club or the league, loading as you scroll | your club / league |
| Game (`#game/<id>`) | 2D replay (play, speed, previous/next goal, scrubber, shot chart), recap, score by period, three stars, scoring, penalties | |
| History | your club's events, league news, league trades | vacancies |
| Inbox | a mail client in the style of the SPB wiki tool: folders (all, unread, owner & board, players & agents, trades, staff reports, league office), message list with sender and preview, reading pane with links to the screen the message is about, search | mark read / unread, mark all read |
| Title screen and setup | continue, load, new game: a four-step setup (your GM, league, club, save; docs/SETUP.md) | start career |
| GM (`#gm`) | your profile and record: every club you have run, season by season (docs/SETUP.md) | |
| Stats (`#stats`) | league leaders, skater, goalie and team tables, by season, league and RS / playoffs (docs/STATS.md) | |
| League history (`#leaguehistory`) | champions, award winners, all-time and single-season leaders | |
| Team page (`#team/<id>/<season>`) | hockeydb-style season page: record, finish, roster with every player's line, the club's history; linked from standings and every player's career table | |
| Player profile (v27) | hero card (club, age, contract, captaincy, injury), tabs: overview, career stats (hockeydb-style, by league, RS and playoffs), game log, ratings and their history, contract, personality, history | contract talks, leadership group, send down, release |
| Leadership group (pop-up) | current C and As, the room's ranking, a live preview of every consequence, who is replaced (docs/CAPTAINCY.md) | name the group |
| Press room (`#press`) | press conferences waiting and on the record, fan / media sentiment and controversy; the podium pop-up asks one question at a time, then shows the fallout (docs/PRESS.md) | answer |
| Draft room (`#draft`) | lottery, pick ticker, on the clock, your board (docs/DRAFT.md) | run / pause, next pick, jump to my pick, draft |
| Rights (`#rights`) | one card per expiring contract: ask, QO, arbitration, his mood | talks, qualify, decline, walk away |
| War room (`#warroom`) | free agency hour by hour: clock, round, signings, the market with asks and interest, your offers (docs/CONTRACT_ENGINE.md) | offer, withdraw, next round, run to the end |
| Playoffs (`#playoffs`) | bracket by round and the season's awards | |

The title bar has back and forward buttons (and Alt+Left / Alt+Right), the save's name and the Saves menu.
The status bar always carries the date, phase, record, the trade deadline while it is open, a command box (any CLI
command, e.g. `pickswap TOR give 24 get 18` or `trade ...`) and the sim controls (day, week, next game, rest of
season; in the summer, next offseason phase). The Contracts screen shows contracts against the 50 limit. Tables sort by clicking a heading.
Every command's output appears in a toast; errors stay longer and are red.

## Tests
`tests/test_ui.py` starts the server on a free port, checks every view answers from the handler threads, and checks
that actions and unknown commands go through the CLI.

Offseason phases are rooms: each phase shows a banner pointing at its room (draft room, rights, war room), and leaving a
phase with decisions left asks first. In the UI the draft and free agency run only as you step through them.

## Not yet
Team logos and colours (the broadcast views use neutral colours: no third-party marks are shipped), keyboard shortcuts
beyond back/forward and Esc, a player comparison view in analytics.
