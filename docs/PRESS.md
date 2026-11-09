# The press room (hs/game/press.py)

Press conferences are decisions. Answers are preset (no free text): each one has an archetype, and the context scales its effects.

You speak for the club (you are the GM). Reporters ask; you choose an answer from a set written for the situation.
Every answer has an archetype, and the archetype has a base effect on three things, which the context then scales:

  archetype                 room morale   board   fans      also
  back the group                +5          +2      +2
  take responsibility           +8          +5      +4
  cliche                        +1          +1       0
  deflect                       -2          -3      -2
  call out a player            -15         -5      +8       the player: trust and morale down, by his ego
  blame the officials           +5         -10     +15      a league fine is possible
  credit yourself               -5          +5      +5
  question the coach           -10         -12     +10      the coach's standing with the players drops
  demand accountability         +3          -5      +8
  no comment                    -1          -2      -3
  speak from the heart          +6          +3      +8
  issue an ultimatum           -12         -15     +12      trade talk, players worry about their futures

  context: x (1 + pressure/200) where pressure is 40 + 15 for a losing streak of 3+, + 15 for a rivalry (same
  division), + the hot seat (board confidence under 45: +20); x1.2 after three or more losses in a row.
Effects land on: every player's morale (the room number x 0.3) and the room's cohesion (x 0.25); board confidence
(x 0.35, through the boardroom); and the club's media state (fan sentiment, media sentiment, controversy, 0-100).
A named player also feels it personally (call out: trust -(10 + ego/2), morale -8; praise: trust +4, morale +3).

Stories follow answers (the story queue): a player you called out may confront you the next day (inbox), the
dressing room may leak to the insider two days later (a headline and posts), a GM who blames the officials may be
fined, an ultimatum starts trade talk. Reporters remember: a later press conference can ask about something you said.

When press conferences happen: after your games when there is a story (a blowout, a losing or winning streak, a
rivalry, a big comeback or collapse) and otherwise one game in six; a weekly availability; media day before the
season; trade deadline day; the end of your season; after you make a trade; when you name a captain; when a player
asks for a trade. Captaincy, trade requests, the deadline and the end of the season are "major": a long sim stops
for them. Skipped press conferences expire (3 days; major ones 5) and count as "no comment" with the media and
the fans (no effect on the room or the board).

## Outcomes and the game engine (v30)
Every Monday `weekly_outcomes` reads your club's media state. Crossing a line makes a story with effects (each kind at
most once in three weeks):

| Outcome | When | Effects |
|---|---|---|
| A hostile column | media sentiment low | board, morale, media |
| Fans turning | fan sentiment low | board, fans |
| The building rocking | fan sentiment high | board, morale, fans |
| A controversy cycle | controversy above 60 | board, morale, cohesion -2 |
| Good press | media high, controversy low | board, cohesion, media |

`engine_form` reaches the match engine (via hs/sim/loader.py): controversy above 60 costs composure, up to 4% of shot
attempts at 100; a crowd above 75 adds 1.5% at home, one below 30 costs 1.5% at home. Clubs without a media state play
at 1.0, so league calibration is unchanged.

## In the UI
The top bar shows **Press room (n)** while reporters are waiting. The press room (`#press`) lists what is waiting (major ones
in red) and what you have said on the record. **Take the podium** opens the press conference: one question at a time, with the
reporter, the outlet and the answers labelled by archetype. After the last answer, the fallout card shows what moved (room,
board, fans, media, controversy). The sim centre stops for any press conference on a day or week sim, and for the major ones
on a season sim.

## CLI
`press` lists the waiting press conferences with their questions and numbered answers; `answer <id> <choice> <choice> ...`
answers them (1-based, one choice per question).

## Tables
press_events (one per press conference: kind, created, expires, status pending/answered/expired, context, questions,
answers, outcome), media_state (per club: fan sentiment, media sentiment, controversy), story_queue (stories coming due).


## v37-v38
* Rivalry games are now the rivalry model's (hs/game/rivalry.py, 50+ points), not every same-division game.
* The introductory press conference (v38, hs/game/welcome.py): on the first day at a club. Four questions: what
  you expect this season (a run at the Cup, the playoffs, steady progress, a rebuild), the star or the expiring
  contract, the best prospect, the coach. The first answer is weighed against the owner's competitive objective:
  in line +4 board confidence, one step off -1, further -6, written to Job Security ("introduction"). Major: a long
  sim stops for it.
