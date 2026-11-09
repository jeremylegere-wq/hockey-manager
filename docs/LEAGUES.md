# The leagues around the NHL (v44; hs/game/leagues.py, hs/leaguedata/league_rules.py)

You manage an NHL club; the world around it now plays real seasons. League > World Leagues shows every league: its
standings, playoffs, scoring leaders, champions and rules. Each league's clubs have team pages, and every player page
shows his line in whichever league he plays.

## Leagues that play their games (13, plus the Memorial Cup)
The AHL, ECHL, KHL, SHL, National League, Liiga, Czech Extraliga, DEL, NCAA, OHL, WHL, QMJHL and USHL play a real
schedule, day by day alongside the NHL, under their 2025-26 rules (`league_rules.py`):

| | |
|---|---|
| Schedule | each club's game count (AHL 72, KHL 68, SHL 52, NCAA 36...), more games inside a division or conference, spread over the league's real season dates |
| Points | 2-point leagues (North America, the KHL) or 3-point (Europe: 3 a regulation win, 2 an overtime or shootout win, 1 an overtime or shootout loss); NCAA ties stand after overtime |
| Playoffs | each league's format: Europe's top six plus a pre-playoff (the Swiss two-game play-in), the CHL, KHL and USHL by conference, the AHL and ECHL by division, the NCAA's 16-team single-game bracket |
| Limits | import limits (CHL 2 and no import goalies, KHL 5, NL 6, DEL 9, USHL 4) and the CHL's three 20-year-olds, applied when clubs sign players and when draft classes are placed |
| The Memorial Cup | the OHL, WHL and QMJHL champions and a host club (the leagues take turns): a round robin, a semifinal and the final |

**The results model.** This is not the NHL match engine, which would make a season six times slower. Each club's
lineup (its best 12 forwards and 6 defencemen, the starter in about 7 games of 10) gives an attack and a goalie. Goals
are Poisson around the league's scoring rate, tilted by the attack gap and the goalie. Ties go to overtime and a
shootout. Every goal gets a scorer and up to two assists among the dressed players (weighted by overall, line and
position), and goalies get their saves. The lines go into the season tables (`source='league'`), so player pages, the
draft board and development all see them.

## World leagues (23, simulated a season at a time)
From your database: the Allsvenskan, VHL, Slovak Tipsport Liga, ICE Hockey League, Norway, Mestis, the Elite League,
DEL2, Czech Maxa liga, Swiss League, Ligue Magnus, Denmark and the Alps League; the J20 Nationell, Finland's U20
SM-sarja, the MHL, the Czech, Slovak and Swiss U20/U21 leagues, the DNL, the BCHL and the NAHL; and USports.
(`hs/adapters/db_export.py` DB_LEAGUES, chosen by strength and size: the strongest is the Allsvenskan, at about ECHL
level; below Denmark and the Alps League the database's leagues thin out.)

* Their rules come from the database: country, level, age limit and club count; their strength, roster size and
  nationality mix from their players; their game count from the career history's last season (Allsvenskan 52,
  ICE Hockey League 48, Norway 45, Elite League 54, BCHL 53, USports 28...).
* Each player gets his season's line as before (scoring relative to the league). Each spring a champion and a
  runner-up are drawn by club strength (P ~ exp(2.2 x strength); a club 0.3 better wins about twice as often).
* Players move through them like the rest of the world: unsigned players find the level they can play at, and
  draft-class 17-year-olds start in their home junior league (Swedes in the J20, Finns in the U20 SM-sarja, Russians
  in the MHL...) or the CHL and USHL.

## The world
The bundled world is rebuilt with them: 20,807 players (from 9,742) in 724 clubs and 37 leagues, every player's
career history and the past NHL drafts included (docs/HISTORY.md). A season and a summer take about three minutes
(two before). Most of the extra time is the leagues' games; the NHL lineup loader was made faster along the way
(it had been scanning every season line in the world each game day).

## Not yet
Fully manageable lower-league clubs (a career running an AHL or SHL club), the AHL's NHL call-up limits in the
results model, international tournaments.
