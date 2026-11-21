# Changelog

All notable changes to Hockey Manager. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The version is `VERSION` in `hs/ui/settings.py`; a release is the tag `v` + that version (see
[docs/RELEASING.md](docs/RELEASING.md)). Releases before 0.61 are not listed here.

## [Unreleased]

### Added
- Approved-list no-trade clauses: a modified clause can name the 8-12 clubs a player would accept instead of the ones
  he refuses; the trade AI and your trades respect it, talks offer it, and the trade screen and contract panel name
  the clubs on either kind of list (issue #11).
- Transactions > Transfer summary: every club's arrivals and departures since the season ended, with the cap that came
  and went; linked from the Free Agent Centre (issue #9).
- League > Staff Index and Team > Alumni (also on every team page) (issue #16).
- Coaching points by category from your staff set how much a training focus helps; the goaltending coach has two to
  four one-on-one slots for young goalies (Development screen, `goalieslot`) (issue #14).
- Each club's media: a coverage level from its market, a fixed lean, and focus players the questions go to first
  (Press Room) (issue #12).

### Changed
- A press conference's starting pressure and the chance of one after a quiet game now follow the club's coverage level
  (40 and 1 in 6 at the middle level, as before).
- `docs/DEFECTS.md`: rows that still said "Planned" for work shipped in v34-v48 say what shipped; the GitHub issues
  table lists 0.61.1 and v0.62.

## [0.61.1] - 2026-11-21

### Fixed
- Draft: making your pick in the draft room made the pick, then failed with an error (a SQL function SQLite does not
  have), so it looked as if the pick had not happened (issue #32).
- Draft: the "Make the trade" and trade-down "Accept" offers on draft day were offers the AI then refused; every offer
  shown is now one it accepts, and the price of the pick on the clock includes the live-board premium (issue #32).
- Contract talks: the window no longer hangs on "Calling his agent" when talks are blocked; it says why, and a failed
  call shows the error (issue #34).
- Inbox: the arbitration button names the player instead of showing a player id (issue #33); the college free agents
  message has a button that opens College Hockey on the Free agents tab (issue #31).
- LTIR screen: the command-line listing of players on long-term injured reserve failed on the same SQL function.
- Free agency: moving on from the war room while the auction is still open always asks first, even with "confirm
  phase changes" off, and the war room shows an error instead of a blank page if it cannot open (issue #35).

## [0.61] - 2026-11-15

### Added
- Run a club in a European league (KHL, SHL, National League, Liiga, Czech Extraliga, DEL and the second tiers): the
  transfer market, loans, the board and European job openings (docs/EUROPE.md).
- Start a new career at a European club from the new-game screen (step 3, World).
- Your European club's games are played by the full game engine, with box score, recap and 2D replay.
- Display currency: 13 currencies at reference rates, chosen at launch or from the Currency menu (docs/CURRENCY.md).
- Russian interface, selectable from the File menu (docs/RUSSIAN.md).
- Help > Report a bug opens a new GitHub issue with the details filled in; Help > About shows the build.
- AI clubs loan young players a level down every Monday from August to the close of the window.
- A screenshot gallery in the README and docs/GALLERY.md, captured from the fictional world.
- CI on every push and pull request, and a tag-triggered release workflow (docs/RELEASING.md).

### Changed
- European seasons start the day before the league opens (the KHL on 5 September) instead of the NHL's opening night.
- A European club uses the same Lines, Tactics and Lineups screens as an NHL club.
- The sim centre, Standings, Playoffs, Statistics, Schedule, Calendar, News and Team Page follow your European
  league, with a League picker for any other; NHL-only menu entries are marked.
- Bug reports go to the GitHub issues page; the email contact is gone from the docs and templates.

### Fixed
- A club that fired or sacked you is no longer offered as a job.
- A perfect relief stint is no longer called a shutout in recaps.
- Currency formatting falls back to the currency code on older WebKit windows that reject short symbols.
