# Changelog

All notable changes to Hockey Manager. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The version is `VERSION` in `hs/ui/settings.py`; a release is the tag `v` + that version (see
[docs/RELEASING.md](docs/RELEASING.md)). Releases before 0.61 are not listed here.

## [Unreleased]

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
