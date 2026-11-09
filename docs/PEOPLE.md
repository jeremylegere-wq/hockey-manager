# People (phase D, v35)

## Hidden attributes (hs/game/hidden.py)
Seven attributes nobody sees directly, 1-20, generated once per player from his id (stable across saves) around 10.5:

| Attribute | What it does | At 1 / 20 |
|---|---|---|
| Consistency | each game his offence is shifted by a random amount (mean zero) | sd 0.30 / 0.06 |
| Big games | playoff finishing | -0.10 / +0.10 sd |
| Injury proneness | injury risk, and the risk of making an injury worse | x0.62 / x1.38 |
| Temperament | his weight for taking the unit's penalty | x1.57 / x0.43 |
| Sportsmanship | with temperament and ego, who clashes in the room | |
| Coachability | young players' development | x0.955 / x1.046 |
| Greed | what he asks in contract talks | -6% / +6% |
Every effect is neutral for the average player, so the league's totals do not move (checked: docs/SIM_CALIBRATION.md, v35).

**What your scouts say.** The player screen shows phrases, never numbers, for attributes far from average: 3 or less /
18 or more for other clubs' players, 5 or less / 16 or more for yours ("a big-game player", "injury-prone", "a short
fuse", "chases the money", "steady as they come", "hard to coach"...).

## Special abilities
Badges from the ratings, the hidden attributes and the personality, shown on the player screen: big hitter, sniper,
magician (puck skills), the wall (shot blocking), faceoff ace, burner (speed), playmaker's vision, enforcer, workhorse,
iron man, glass, playoff performer, Mr. Reliable, malcontent, homebody, natural leader; for goalies cat-like reflexes and
always square. Display only: the attributes underneath already do the work.

## Game ratings
Every player, every game, 1-10 (game_ratings): offence (5.5 + 1.4 a goal + 0.8 an assist + 0.15 a shot on goal + 0.04
an attempt), defence (6 + 0.3 a block - (0.35 x goals his team allowed - 1) x his share of a full game's ice time - 0.25
a minor), overall 60/40 for forwards, 40/60 for defence; goalies 6 + 22 x (save % - .900), +1 for a shutout, -0.25 for
each goal over three. The player screen shows his last ten and his season average.

## Rust and playing hurt (hs/game/welfare.py)
* **Rust.** Back from a layoff of two weeks or more, a player starts 0.25 sd below himself (offence and defence) and it
  wears off over one game for each week he was out (up to five).
* **Playing hurt.** An injury with three weeks or less to go (not LTIR) can be played through: he is back now, 0.35 sd
  below himself until the day he would have been back; each game, 8% (x injury proneness) that it gets worse (out
  again for the time that was left plus one to three weeks). `playhurt <player>`, `rest <player>`.

## The morale log
Every change of 3 or more in a morale component (role, team, contract, trust in the coach), and every talk, promise
kept or broken and trade rumour, is logged with its reason (morale_log). Your players' Personality and morale tab shows
what moved it and why.

## Harmony (hs/game/harmony.py)
* **Cliques.** Language groups that are a minority in the room (the Swedes, the Finns, the Russians, the Czechs and
  Slovaks, the Germans, Swiss and Austrians, or the North Americans where they are the minority) and age groups (the
  veterans 31+, the kids 23 and under), four or more strong. An unhappy clique (morale under 45) costs a point of
  cohesion a week.
* **Clashes.** Two players with big egos (14+) and a short fuse or little sportsmanship (7 or less), or an unhappy
  malcontent. Each week a clash has a 12% chance of an incident (halved by a captain with leadership 15+, up 40% in a
  tense room; one a club a week): a story, cohesion -3, both players' morale -4, a message from your coach.
* Team Info (your club) lists the cliques, the clashes and the incidents.

## Mutual termination
`terminate <player>` (or the player screen) asks him to tear up his contract: no buyout, no cap charge, he becomes a
free agent and the club pays a settlement of 10-40% of what is left (more if he is greedy). He agrees when it suits him:
27 or older, unhappy with his role, asking for a trade, or a veteran past his best; loyal players hold on. One ask a
month; entry-level deals cannot be terminated.

## Not yet
Media coverage level and focus players, veteran (35+) performance bonuses, lineup priority lists, tactical roles with
on-ice effects, asymmetric chemistry, player templates by style.
