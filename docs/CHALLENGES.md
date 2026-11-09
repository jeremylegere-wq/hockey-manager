# Challenge mode and challenges (v47)

`hs/game/challenge.py`; Manager > Challenges; console `challenge`, `challenge mode on`, `challenge start <key>`,
`challenge abandon`. A new career can also start with them (the new-game profile's `challenge_mode` and `challenge`).

```
Challenge mode and challenges (v47; docs/CHALLENGES.md).

Challenge mode (a career setting; once on it stays on)
  * no commissioner mode and no editor
  * during the regular season and the playoffs you sim a day, a week or to the next game at most (a week at a
    time; `sim season` and long `sim to` jumps are for the off-season)
  * you can be fired (the "cannot be fired" option is switched off)
  * the career is marked: GM leaders, achievements and the Challenges screen show it
Challenges (goals with a deadline, taken on at the start of a career, before your club's first game; one at a time):
  turnaround   make the playoffs within your first two seasons            (suggested: one of the five weakest clubs)
  rebuild      win a playoff round within four seasons                    (suggested: the weakest club)
  win_now      win the championship within three seasons                  (suggested: the strongest clubs)
  cap_hell     be cap-compliant on opening night of your first season and make the playoffs within two
                                                                           (suggested: the club with the least cap room)
  dynasty      win three championships within eight seasons                (any club)
  expansion    an expansion club is announced; you run your club this season, take over the new one when it ends,
               and must make the playoffs within its first three seasons
Each season's end checks the goal; the challenge is won when it is met, lost when the deadline passes or you lose
your job (or leave the club, other than for the expansion club). The result is permanent: an inbox note, a news
story and a line on the Challenges screen.
```
