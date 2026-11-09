# Supplementary discipline (v53)

`hs/game/discipline.py`; League > Discipline; the player page shows "Suspended: N games"; console `discipline`,
`discipline appeal <player>`.

```
Supplementary discipline: suspensions (v53; docs/DISCIPLINE.md).

Incidents: about 3.5% of NHL games produce a play the league's player-safety office suspends for (the NHL hands out
roughly 40-50 a season). The player is drawn from the two lineups, weighted by aggression and hitting (the
toughest, angriest players most often). Length: 1 game 35%, 2 25%, 3 15%, 4-5 12%, 6-10 10%, 11-20 3%; a repeat
offender (suspended in the last 18 months) gets half as many games again. The kinds: an illegal check to the head,
boarding, charging, cross-checking, slashing, high-sticking, elbowing, kneeing, interference, leaving the bench.
Serving it: the suspension starts with his club's next game; he cannot dress until it is served (games left carry
over into the playoffs and the next season). He forfeits his pay for those days (his cap hit / 82 a game); it does
not count against the cap.
Appeals: a suspension of six or more games can be appealed once (your club: `discipline appeal <player>`); the
commissioner cuts it by a third 25% of the time, otherwise upholds it.
Data packs can preset suspensions (suspensions.csv: player_id, games[, reason]) and injuries (injuries.csv:
player_id, days or return_date[, description]).
```

Not modelled: in-person hearings, fines (other than the forfeited pay) and suspensions for off-ice conduct.
