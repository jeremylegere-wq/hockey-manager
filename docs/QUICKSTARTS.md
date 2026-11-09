# Quickstarts, schedules and logos (v48)

## Quickstarts

`hs/game/quickstart.py`; File > Save as Quickstart...

```
Quickstarts: a world captured at the start of a season, for new careers to begin from (v48; docs/QUICKSTARTS.md).

Make one (File > Save as quickstart, or `quickstart save <name>`) from any career when a regular season has been
scheduled and no game of it has been played (after the pre-season phase ends). The quickstart keeps the whole world -
rosters, contracts, prospects, history, the leagues around the NHL, expansion clubs, records, the Hall of Fame - and
drops what belongs to your career: your inbox, achievements, challenge, scouting assignments and knowledge, short list
and notes, open trade offers and shops, prospect paths, and your place at your club (it gets a GM of its own). It is
listed with the worlds when you start a new career; pick any club. A quickstart made from an edited save stays marked
as edited.
```

A quickstart lives with the worlds (the `worlds` folder next to your saves) and is listed in the new-career wizard as
"<name> (quickstart <season>)". Delete the file to remove it.

## Historical starts

Not yet: a start in a past season needs every club's roster, contracts and prospects as they were that season, and
the database file holds careers, not past rosters. A quickstart is the way to keep a world at a moment of your own.

## Schedules

`hs/game/schedule_io.py`; League > Commissioner > Schedule.

```
Schedule export and import (v48; docs/QUICKSTARTS.md "Schedules").

Export (anyone): this season's regular-season schedule as CSV: date, home, away (club abbreviations), and for games
already played the score (home_goals, away_goals, ot).
Import (commissioner mode): a CSV with date, home and away columns (others are ignored) replaces this season's
unplayed regular-season games. Checks, row by row: a real date inside the season (after today, before the regular
season's end plus 30 days), two different NHL clubs, no club twice on one day. Then for the whole schedule: every club's
total (games played plus imported) is reported, and unequal totals are a warning (standings use points percentage only
if you set it so; points tables still work). Preview first; apply writes it.
```

## Logos

File > Logos... Image files named by a club's abbreviation (`MTL.png`, `TOR.svg`, `HOU.webp`; png, svg, jpg, webp or
gif, up to 2 MB each) in a `logos` folder next to your saves (or next to the bundled world) replace the generated
crests everywhere; a club without a file keeps its crest. "Import" copies a folder of them in (a file with the same
abbreviation is replaced). Abbreviations are shared across leagues, so a file named for an NHL club also shows for a
minor-league club with the same letters.
