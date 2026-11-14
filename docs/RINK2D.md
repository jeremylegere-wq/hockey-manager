# The 2D game (rebuilt in v59)

Open any played game (`#game/<id>`): the whole game plays out on a 200 x 85 ft rink, every skater, both goalies and the
puck, with benches and penalty boxes. It is built from the game's stored events when you open it, so it works for
every game of every save, old or new, and it writes nothing to the save.

## Who decides what

* **The match engine** (`hs/sim/engine.py`) decides the game: every shot, save, miss, block, goal, assist and penalty, by
  whom and when. It is calibrated to real scoring (docs/SIM_CALIBRATION.md) and it does not move anyone.
* **The plan** (`hs/sim/ice_plan.py`) lays those events out in time, works out the strength and who was on the ice.
* **The on-ice engine** (`hs/sim/ice2d.py`) plays the time in between as hockey, so that each event happens at its time,
  by its player, from its spot. It never changes a result. (v30's `hs/sim/rink2d.py` is kept as a fallback.)

The ideas for how the play is organised (breakout support, controlled entries and dump-ins, the cycle, defensive lanes,
faceoff set-ups, team-relative coordinates that mirror cleanly) come from the Retro Hockey Simulator V3 work. That engine
decides its own results and is not calibrated, so here its ideas steer the movement and the match engine keeps the score.

## The plan

The engine works in 30-second steps and stamps events with a second inside the step. Two things follow:

* **Times.** Goals keep their official second. Saves, misses and blocks move by a few seconds where the ice needs it: a
  rebound follows its shot by about 2 s, two attempts by one side are 3.5 s apart or more, attempts at opposite ends 7.5 s
  or more, and the attempts of one step are grouped by side. About 70% of attempts do not move; nine in ten move less
  than 8 s. Two goals a second apart (it happens) are staged six seconds apart.
* **Penalties.** The engine decides a penalty at the end of its step and the club is short from the next one, but stamps
  the step's first second. The whistle you see is at the step boundary: up to 30 s after the time in the box score.
* **Strength** mirrors the engine: two minutes, a power-play goal ends the oldest minor, offsetting minors make it four
  a side, three-on-three overtime, goalies pulled late in the third when trailing.
* **Who is on the ice.** The engine does not store it. The players an event names in a step (shooter, assists, blocker,
  penalised player) were on the ice together, so they are; the rest come from lines built from the game's ice time,
  choosing the line that fits and is furthest behind its ice time.

## The play

Between two events the puck has to get from where the last one left it to the next shooter's stick. The director plays
that as possessions:

* **Breakouts**: up the wall, through the middle, D to D behind the net, or carried out.
* **The neutral zone**: three lanes, the defence trailing; nobody crosses the blue line ahead of the puck.
* **In the zone**: a low cycle with a net-front man and two points; low to high, point to point, down the wall, behind
  the net. On the power play a 1-3-1.
* **The shot**: the puck reaches the shooter at his spot at his second; a goal's last passes come from the players
  credited with the assists. Saves are frozen or kicked out, rebounds are fought for (a rebound chance goes straight
  to the next shooter), blocks come off the blocker, misses rim around the boards.
* **Changes of possession** when there is more time than one attack needs: a dump-in, a poke check, a pass picked off,
  a penalty-killer's clear down the ice.
* **Without the puck**: a 1-2-2 forecheck, the defence backing up facing the play, zone coverage with one man on the
  puck, a box on the penalty kill, a triangle three against five.
* **Goalies** play the angle and the depth, go to the post when the puck is behind the net, drop for shots, cover.
* **Whistles**: faceoffs with both sides lined up at the right dot, changes on the fly through the bench doors (never
  the puck carrier or a player the next play needs) and at whistles, the walk to the penalty box and back out of it,
  the goalie to the bench for a sixth attacker, goal celebrations, the horn, the shootout.

Skating is physical: each player accelerates, turns and stops within limits from his speed and acceleration ratings.
The puck is always carried, passed, shot or loose; it is never moved by hand.

## The viewer (`hs/ui/static/ice.js`)

* The rink with markings, creases, nets, benches and boxes; the home club in its colour, the road club in white.
* Players are jersey tokens with their number; a notch shows which way they face; the puck carrier is ringed and
  carries a stick, as does anyone passing, shooting or checking. With the close camera everyone has one.
* A broadcast scoreboard: score, period, clock, shots on goal, strength (power play, four on four, empty net).
* Banners for goals (scorer and assists) and penalties; SAVE / BLOCKED / WIDE calls; a goal lamp.
* Play / Pause, previous and next goal, next shot, speed 0.5x to 16x, a scrubber, **Goals only**.
* Cameras: the whole rink, or following the play. **Full window** fills the window (Esc leaves; Space plays; the
  arrow keys move five seconds).
* Who is on the ice for each club, and a running play by play.

## Watching your game

On a game day the bar at the bottom has **Watch in 2D**. The day is played, then your game opens in a window of its own
from the opening draw: the score builds as it happens, and there is no scrubber, no "next goal" and no box score to give
the result away. Close it (Esc, or Close) at any time, or wait for the final; the day's results are then on the usual
screens. If the day stops before your game for something that needs you (a press conference, an offer), you are told
and nothing is shown.

## Offside (v0.61, issue #24)

The engine does not record offsides, so the replay must never draw one. A goal it shows comes from a legal entry.
The blue line works as it does under the rulebook (NHL Rule 83): it is a foot wide and belongs to the zone the puck is in.
The puck is in the zone only once it has completely crossed the line, and out only once it has completely crossed back.
A player is offside when both skates are over the line before the puck. In the 2D game, his centre is more than
`ONSIDE` (1 ft) past it.

- **Puck in the zone.** The man with it, or the man the pass is going to, keeps it inside the line. The point man does
  not let it slide out and play it straight back in to team-mates who are still deep.
- **Puck outside.** No team-mate goes in ahead of it. Each one stops at the line, allowing for the room he needs to
  stop. A bump from another skater never pushes him over. Anyone still deep only skates out (tags up). The carrier
  holds at the line until they are out.
- **Passes.** No pass into the zone goes to a man who is already inside, and none in the zone goes to a man outside
  the line. The passer waits up to 2.6 s for the receiver to get onside. A pass meant for someone who has gone off in
  a change goes to the nearest man still on the ice. Before this, the man changing could take the puck to the bench.
- **The last play before a shot.** If the puck is still outside the zone when the shooter's play starts, the carrier
  brings it in himself, at speed, and the shooter follows it. Nobody stands still in his own end with the shooter
  waiting deep for a long pass. That was the play in issue #24.

`check["offside"]` counts any entry still drawn offside: carried, passed or dumped in. It is zero across 180+ games
from five saves, about 75 of them in overtime. `tests/test_v61.py` also reads it back from the frames alone. The cost:
shooters miss their spot a little more often (about 2.5 a game, was 2.3), because they now follow the puck in rather
than wait at the spot.

## For developers

`ice2d.track(conn, game_id)` returns `dt` (0.2 s), `frames`, `players`, `marks`, `periods`, `check`; the docstring has the
frame layout. API: `/api/track2?id=<game_id>`. A game takes about a second to build; nothing is cached or stored.

`check` counts what the director could not stage cleanly: `offspot` (a shooter more than 9 ft from his spot when he
shot: two to three a game), `offside` (an entry drawn offside: zero), `rushed` (a shooter brought off the bench for his shot), `missing`, `late`, `snap`; the tests
(`tests/test_v59.py`) hold the last three at zero and check that every stored event is played, that nobody moves
faster than a skater can, that the puck stays on the ice, that the same game always plays the same way, and that a
save without the newer columns still plays.

## Not yet

Hits and board battles as their own events, referees, offside and icing whistles (the engine does not record
them, so the 2D game plays every entry onside instead of calling one), and goalies playing the puck.
