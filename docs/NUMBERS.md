# Jersey numbers and player pictures (v49)

`hs/game/numbers.py`; the roster's # column and the player screen's "Change number"; retired numbers on the team page;
File > Player Photos...; console `number <player> <n> [swap]`, `number retire <n> <player> [ABBR]`, `number retired [ABBR]`.

```
Jersey numbers and the player picture (v49; docs/NUMBERS.md).

Numbers
  * every player at a club wears a number from 1 to 98, unique within the club he plays for (an NHL roster, an AHL
    club, a junior team); 99 is retired league-wide, and a club's own retired numbers are off limits there
  * a world built from the database starts with the database's squad numbers; anyone without one, or who clashes
    with a teammate after a trade, signing or call-up, gets one: the one he wore if it is free, else one by position
    (goalies 30, 31, 35, 1, 29...; defencemen 2-8, 44, 55, 77...; forwards 9-29, 91...), else the lowest free
  * when two teammates want the same number the one who has been at the club longer keeps it
  * you change your players' numbers on the player screen or the roster (`number <player> <n>`); if a teammate
    wears it you can swap (`number <player> <n> swap`). With commissioner mode on you can change anyone's.
  * a club retires a number for a player who gave it 300+ games or is in the Hall of Fame (`number retire <n> <player>`;
    your club only, or any club in commissioner mode); whoever wears it now keeps it until he leaves
The picture: your own photo files (faces folder next to your saves, named by player id: 12345.png / .jpg / .webp) or a
pack's headshot path; without one, the back of his jersey: club colours, his name and number.
```

The bundled 2026 world carries the database's squad numbers (20,021 of 20,807 players; the rest are given one).
The database's retired-numbers list names players and numbers but not their clubs, so it is not imported; clubs
retire numbers in the game.
