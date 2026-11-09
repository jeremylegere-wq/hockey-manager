# The 2D game (v30)

`hs/sim/rink2d.py` plays a finished game out on a 200 x 85 ft rink: every skater, both goalies and the puck. It is
the rebuild of Jeremy's 2D ice hockey project (defect 13) as a headless module, steered by the match engine.

## How it fits
The match engine (`hs/sim/engine.py`) decides the game: shots, saves, goals, blocks, misses and penalties, with who and
when. `hs/game/replay.py` gives each event a spot on the ice. The 2D game then plays the time in between so that each
event happens at its time, by its player, from its spot: the puck is carried up ice, passed along open lanes, worked
in the zone and delivered to the shooter. Goals go in, saves are held or kick out, blocks stop at the blocker, misses
go wide. It never changes a result.

## What is modelled
* Skating with acceleration and a top speed from the player's skating ratings; steering towards a target.
* Puck physics: friction, board bounces, possession by stick reach (3 ft).
* Passing: the best lane by a short look-ahead for interceptions.
* Coordinators that place each position in attack (points that pinch, low forwards, the slot) and defence (a box on
  the penalty kill, a pressure range on the carrier).
* Goalies on an arc in front of the net, playing the angle.
* Faceoffs between the centres on the ice; line changes by a shift schedule (forward lines 1-2-3-1-2-4, pairs
  1-2-1-3); the shooter's unit is sent out in the 25 seconds before his shot; a penalised player sits in the box.

Lines come from who played the game: ice time orders them into four forward lines, three pairs and a goalie.
Deterministic from the game id; plain Python, about a second a game (18,000 steps at 0.2 s).

## The tracking
`track(conn, game_id)` returns:
* `dt` (0.2 s) and `frames`: one list per step, `[puck x, y, home skaters 1-5 x, y, away skaters 1-5 x, y, home G x, y,
  away G x, y, carrier slot]` (27 numbers; the carrier slot 0-11 or null).
* `rosters`: `[t, [player ids in the frame order]]` each time the players on the ice change.
* `players`: `{id: [name, position]}`; `marks`: shots, goals, blocks, misses and penalties with time, team and who.
* `home` / `away`: the clubs.

API: `/api/track?id=<game_id>`.

## The viewer
The game page (`#game/<id>`) mounts `Rink` (hs/ui/static/rink.js): the rink, the players as discs in club colours (the
road team in white with its colour as the trim), names above them, a ring on the puck carrier, the score and clock,
Play / Pause, previous and next goal, next shot, speed 1x-32x, a scrubber, and who is on the ice. It interpolates the
5 frames a second to the screen's rate. If the tracking cannot be built the old event replay is shown.

## Not yet
Pass and shot lines drawn on the ice, the shot chart overlay, offside and icing (the engine does not record them),
and saving tracking with each of your games (it is built on request). Planned with phase A's game screens.
