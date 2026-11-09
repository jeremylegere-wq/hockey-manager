# The desktop application (hs/app.py) and the classic interface (v28)

## Its own window
`play.sh` (Linux, macOS) and `PLAY_WINDOWS.bat` run `python -m hs.app`, which starts the game server on 127.0.0.1 in a
background thread and opens the game in a window of its own:

1. **Native window** (pywebview): WebView2 on Windows 10/11, WebKit on macOS, Qt WebEngine on Linux (or GTK WebKit when
   the system has it). No tabs, no address bar, the game's own title (club, save, screen), maximised.
2. **App window** from Chrome, Chromium, Edge or Brave (`--app`, its own profile in `saves/.window/`): used when
   pywebview is missing or with `--no-window`.
3. The default browser, as a last resort (the launch screen says so).

pywebview is not in the standard library. On the first run the launcher asks once (in the terminal) to install it into
`.runtime/`, a private environment next to the game that can still see your Python's packages; nothing is installed
system-wide, and it restarts itself from there. `python -m hs.app --setup ...` installs without asking; deleting
`.runtime/` undoes it; `.runtime-declined` remembers a "no" (delete it to be asked again).

Linux notes: Qt 6.5+ needs `libxcb-cursor0` (Debian/Ubuntu) to open an X11 window; creating `.runtime/` needs
`python3-venv`. `HS_WEBVIEW_GUI=gtk` or `qt` forces a backend.

Closing the window (or File > Exit) stops the sim, commits the save and stops the server. Window storage (the sim pace,
a remembered tab) lives in `saves/.window/`.

## The classic interface
A classic desktop management look: pale blue-grey application, white and light-grey panels with thin
blue-grey borders and blue title strips, compact zebra tables with blue selection, classic tabs, rectangular gradient
buttons, Windows-style menus and scrollbars. The theme is `hs/ui/static/classic.css` (tokens at the top: colours,
borders, the font stack Tahoma / Segoe UI / DejaVu Sans) and restyles every screen, including the sim centre, the
draft room, the war room and the playoffs. The launch screen keeps its cinematic look; the management game never does.

* **Menu bar**: File (new, load, save as, settings, console, start screen, credits, exit), Manager, Team, League,
  Statistics, Play, Help; back, forward, home; search for players and clubs (Ctrl+F).
* **Club header**: crest, club name, the screen you are on, season, save; board, press room, inbox and saves buttons;
  date and record.
* **Tabs**: Office, Inbox, Roster, Lineup, Contracts, Trade, Transactions, Prospects, Scouting, Staff, Calendar,
  Standings, Statistics, News. Everything else is in the menus.
* **Bottom bar**: date, phase, record, the deadline; Day, Week, Continue to next game, Rest of season (or Next offseason
  phase). Space continues one day. The console (any CLI command) is off by default: File > Console.
* **Crests and portraits** are drawn by the game (classic.js: `crest()`, `portrait()`), seeded by the club abbreviation and
  the player id. They are not the clubs' marks or the players' likenesses.

## Launch screen, settings, credits
The launch screen is Jeremy's arena picture (`hs/ui/static/launch.jpg`, 1672 x 941) with its six blank blocks as the
buttons: Continue, New Standard Game, Load Game, Settings, Credits, Exit. The picture covers the window at any size and
the buttons stay on the blocks (positions in classic.js, `TOPS`). Settings (also File > Settings) are kept in
`saves/settings.json` (hs/ui/settings.py): interface size 80-150%, metric or imperial, highlight your club, player
cards on click, the console, the launch screen on start-up, the sim centre pace, confirmations when leaving an offseason
phase with decisions left, the draft pick clock (20 s to 10 min), rolling backups (0-10), the schedule strip. Values are clamped and unknown keys dropped, so a hand-edited file cannot break the game.

## New screens
Calendar (your season month by month, results and key dates), Free Agent Centre (everyone unsigned with the ask; sign at
the ask outside the July market), Prospects (unsigned rights and signed players below the NHL, with ELC and recall
buttons, and a KHL buyout offer for picks under KHL contracts), Development (value now against last summer's snapshot
for the whole organisation). v29 added the news article, Champions and Awards Night screens, Back / Forward on the club
header, tab badges and phase reports. v30: the 2D game on the game page (docs/RINK2D.md) and the draft room's pick clock,
rankings columns and pick deals (docs/DRAFT.md). v31 (phase A): the schedule strip, Play until, the transactions hub, roster
tabs, depth chart, transaction log, milestones, reports, past drafts, season pages, rules, team info, notes, the right-click
menu, CSV export and rolling backups (docs/SCREENS.md). v32 (phase A2): the manager step in setup, the Job Centre, the
assistant GM and Find Players (docs/SETUP.md). v33 (phase B): the Tactics screen and the Lines screen with roles, chemistry,
overtime units and tendencies (docs/TACTICS.md, docs/LINES.md). v34 (phase C): the Finances screen (docs/FINANCE.md). v35 (phase D): scouting reads, abilities, game ratings and the
morale log on the player screen; harmony on Team Info (docs/PEOPLE.md). v36 (phase E): the Scouting screen's four tabs, training focus, the development
chart (docs/SCOUTING.md). v37 (phase F): Exhibitions, All-Star Weekend, Hall of Fame, GM Leaders, Achievements and
rivalries on Team Info (docs/CALENDAR.md). v38: File > Import Database and the World step of a new career
(docs/DB_IMPORT.md), the Ratings tab, the Outlook-style inbox, the contracts grid and chart, the pick grid, sim
interruptions in Settings (docs/DEFECTS.md).

## Endpoints
`GET /api/settings`, `POST /api/settings`, `GET /api/app` (desktop or not, version), `POST /api/title` (window title),
`POST /api/quit`, and the views `calendar`, `freeagents`, `prospects`, `development`, `search`, `article`, `track` (the 2D game); v31: `strip`, `playtargets`, `leagueday`, `transactions`, `depth`, `txnlog`, `milestones`, `reports`,
`draftlog`, `season`, `rules`, `teaminfo`, `notes`, `playermarks`; `POST /api/export`; save actions `backups`, `backup`, `restore`; v32: `jobs`, `manager`, `assistant`, `find`.
