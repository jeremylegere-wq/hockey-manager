# International hockey (v51)

`hs/game/international.py`; League > International (tournaments, world ranking, medal table, Triple Gold Club,
our players; click a tournament for its games, scoring leaders and rosters); console `intl`, `intl ranking`,
`intl <id>`, `intl readmit on|off`.

```
International hockey: national teams, tournaments, the world ranking, medals and the Triple Gold Club
(v51; docs/INTERNATIONAL.md).

Tournaments (each season Y, Oct Y - June Y+1)
  World Junior Championship  26 Dec - 5 Jan; 10 nations; players born in (Y+1) - 20 or later who are not on an NHL
                             roster; two groups of five, quarterfinals (1 v 4, 2 v 3 across the groups), semifinals,
                             bronze and gold
  World Championship         May (played when the NHL playoffs end); 16 nations; NHL players whose clubs missed the
                             playoffs or went out in the first round (65% of North Americans and 35% of Europeans say no), and everyone outside the
                             NHL; two groups of eight, then the same knockout
  World Cup of Hockey        February 2028, 2032, 2036...; the 8 best nations; everyone (the NHL breaks for it);
                             two groups of four, semifinals (1 v 2 across), final
  Olympic Games              February 2030, 2034...; 12 nations (the host qualifies); everyone (the NHL breaks); three
                             groups of four, the four best group records straight to the quarterfinals, 5-12 in a
                             qualification round (5 v 12, 6 v 11, 7 v 10, 8 v 9), re-seeded quarterfinals, semifinals,
                             bronze and gold
Who plays: the nations with enough players, best first by world ranking. Russia and Belarus are excluded (the IIHF
ban, extended in July 2026 for 2026-27; the setting `international_banned` readmits them). A roster is the best
available players of that nationality: 14 forwards, 8 defencemen, 3 goalies (13/7/3 at the World Cup).
The games: the leagues' results model (hs/game/leagues.py) with each nation's dressed lineup, the gaps between nations
narrowed to a fifth (they are all picked from the best) and 2.5 goals a team a game; overtime decides every game (a
shootout in the group stage, sudden death in the knockout). Over 40 runs of the 2026 world: the World Cup and the
Olympics go to Canada or the United States about four times in five; the World Championship about three in five
(Sweden, Czechia, Finland and Latvia the others); the World Juniors spread across six or seven nations.
The world ranking (IIHF style): points by final place at the World Championship and the Olympics (1st 1200, then 20
fewer a place, 40 fewer after 4th, 8th and 12th), the last four years weighted 100/75/50/25%. Before a nation has
four years of results in the save, a seed ranking from the real 2025 order fills in.
Medals are kept per player; the Triple Gold Club is the players with Olympic gold, World Championship gold and an
NHL championship (in this save). Best-on-best seasons: the NHL schedule breaks for two and a half weeks in February.
NHL players at a February tournament run a small risk of injury (1.5% each, 1-3 weeks).
```

## The real calendar (as of November 2026)

* The IIHF extended its ban on Russia and Belarus on 30 July 2026: no Russian teams in any IIHF event in 2026-27
  (World Championship, World Juniors, U18s); Belarus stays out of the World Juniors. The game keeps both out until
  you readmit them (`intl readmit on`).
* The NHL and NHLPA announced the World Cup of Hockey for February 2028 (at least eight national teams, NHL rules and
  rinks, hosts in North America and Europe still to be named) and a best-on-best event every two years after the
  2030 Olympics. NHL participation in the 2030 French Alps Games is assumed here; France, as host, qualifies.
* Formats are modelled on the recent tournaments; the World Cup's exact format is not announced, so it is a simple
  two groups of four, semifinals and final.

## Not modelled

National team staff and your role in picking a roster; the U18s, women's and lower divisions; promotion and
relegation (the field is the best-ranked nations each time); NHL clubs releasing junior-age NHL players to the World
Juniors.
