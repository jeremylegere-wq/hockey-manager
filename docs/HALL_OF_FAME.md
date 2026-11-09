# The Hall of Fame and the Career Legacy Score (v45)

`hs/game/legacy_score.py` (the score and the queue), `hs/game/legacy.py` (the ballot and the class), League > Hall of Fame
(tabs: Ballot, Members, Legacy tracker; click a CLS for the breakdown), console `hof`, `hof cls [<player>]`, `hof vote ...`.

```
The Career Legacy Score (CLS) and the Hall of Fame queue (v45; docs/HALL_OF_FAME.md).

1. Season Value (SV): each NHL regular season against the league average of that season's starters at the position
   (starters: a club's top six forwards, six defencemen and starting goalie, times the clubs that season: the top six
   rather than all twelve forwards so that the three positions share one scale - the tenth-best season of the decade
   is about 2.5 for a forward, 2.8 for a defenceman and 2.3 for a goalie). An average starter scores 1.0; an
   MVP-calibre season about 2.2-2.8, a historic one 3+.
     forwards     SV = 0.75 x points/avg points + 0.25 x goals/avg goals
     defencemen   SV = 0.50 x points/avg points + 0.30 x DPS/avg DPS + 0.20 x TOI/avg TOI
     goalies      SV = 0.30 x wins/avg wins + 0.50 x GSAA term + 0.20 x starts/avg starts
   Defensive point shares (DPS) here: minutes played x the club's defence (the league's goals against a game over
   the club's) x (1 + half his plus-minus a game, capped at +-0.5). Minutes come from TOI where the season has it,
   else 20 a game for a defenceman. GSAA is saves minus what a league-average save % would have stopped; because the
   average starter's GSAA is near zero (so a ratio would blow up), its term is 1 + (GSAA - starters' average GSAA) /
   (1% of the starters' average shots against): one point of save % over a starter's workload is worth +1.0.
2. Peak vs longevity (PVL): peak P = the sum of his best 7 SV; longevity L = the sum of the rest. PVL = 10P + 3L.
3. Hardware ledger (HL): Hart and Conn Smythe +50; Norris and Vezina +40; Selke and Art Ross +25; First All-Star Team
   +15; a championship +30 plus up to +20 for his share of the run (his playoff points against the average of the
   champion's regulars, or a goalie's share of the wins); milestones (career totals, before the save included):
     forwards     500 goals +20, 1000 points +20, 1500 points +30
     defencemen   1000 games +15, 500 points +20, 1000 points +40
     goalies      300 wins +15, 500 wins +30, 50 shutouts +20
   (Trophies count for seasons played in the save; the database's history carries no trophies.)
CLS = PVL + HL. Tiers: Inner Circle over 450; First Ballot 350-449; Hall of Fame 250-349; Hall of Very Good 180-249.

Induction (each summer, when the re-signing phase opens): a player becomes eligible three years after he retired
(the summer after his last NHL season); a CLS of 250 puts him on the ballot, for up to ten years; the best four by
CLS go in (a tie goes to the one longer on the ballot). If you sit on the selection committee (career option hof),
your up-to-four votes move a candidate ahead of any unbacked candidate within 15 points of him.
```

## Notes on the data

* Season Values cover every NHL season on file: the database's history (from v43) and every season played in the save.
  Careers before the history begins count only through the milestones (the career totals before the save are included).
* The database's champion and award sections are not decoded yet, so trophies, All-Star teams and championships count
  only for seasons played in the save. Real careers therefore start a little low on hardware; Season Values carry most
  of the weight.
* Awards night now also names the Selke Trophy and the First All-Star Team (two defencemen, a centre, two wings, a goalie).
* A sample from the 2026 world after one season: Ovechkin 367 (First Ballot), Crosby 349, Hedman 297 (Hall of Fame),
  Makar 225 and Hellebuyck 209 mid-career (Hall of Very Good so far).
