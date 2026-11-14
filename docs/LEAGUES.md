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

## Every league has a season (v60)

The 23 leagues that used to be simulated only a season at a time now have rules and can play game by game:
HockeyAllsvenskan, the Czech and German second leagues, the ICE Hockey League, Slovakia, the Alps league, the VHL, France,
the Elite League, Denmark, Norway, Mestis, the Swiss League, the BCHL, the NAHL, the MHL, Sweden's J20, the DNL, the Czech,
Finnish, Slovak and Swiss junior leagues, and Canadian university hockey.

**Their formats are approximate.** Game counts, the points system and the size and length of the playoffs are written
from general knowledge of each league, not taken from its rulebook, and the world has no conferences or divisions for
them, so they qualify by the overall table. The thirteen original leagues are the ones checked against their 2025-26
formats. The Leagues in play screen marks each league "from the rulebook" or "approximate". To correct one, edit its
entry in `hs/leaguedata/league_rules.py`.

A new playoff format serves most of them: **top** (`kind="top"`, `teams=8` or `16`): the best N of the table, highest
seed against lowest, re-seeded each round, with a series length for every round (`best=[7, 7, 7]`).

## Leagues in play (v60)

League > World Leagues > **Leagues in play** chooses, league by league, between:

* **Game by game**: a schedule, standings, playoffs, box-score statistics day by day. Costs a little time every day.
* **A season at a time**: statistics for every player and a champion when the year ends (the model every league used
  before v44). Costs nothing during the season.

Changing a league takes effect at once. Switching one **on** schedules it and catches it up to today. Switching one
**off** takes back what it has played this season (its games, series and the statistics that came from them), so the
year is not counted twice when the season-at-a-time model writes it. A finished season is never taken back. Your own
league is always played in full.

Console: `leagues play` (the list), `leagues play ALLSV off`, `leagues play all`, `leagues play core` (every league whose format is taken from the league itself: 26 from v61),
`leagues play none`. Stored in the save (`lg_select`); a save from before v60 has every league on, and its new leagues
catch up to today the first day you play.

## Schedules (v60)

* **Home and away are shared out.** Each pair of clubs splits its meetings evenly, and an odd meeting goes to the club
  with fewer home games so far. Before v60 every game's host was a coin toss, so a club could be given 17 home games of
  52. This applies to schedules made from v60 on (a new season, or a league switched on); a season already scheduled
  keeps its dates.
* **Exact game counts for the new leagues.** They play whole rounds and then part of one more (every club the same
  number of extra games, against different opponents), so a 36-club league can play 58. The thirteen original leagues
  keep their v44 schedules, which round to whole rounds or follow their divisions.


## Real formats (v61)

The European leagues now play their real 2025-26 formats. The v60 versions were approximations; these are taken from
each league's season page, rulebook or press kit (sources at the foot of `hs/leaguedata/league_rules.py`). Only
VHL, NAHL, MHL, J20, DNL and the Czech, Finnish, Slovak and Swiss junior leagues are still approximate.

| League | Regular season | Playoffs |
|---|---|---|
| SHL | 52 | 1-6 direct, 7-10 eighth-finals (best-of-3); 13 v 14 play out (best-of-7) |
| HockeyAllsvenskan | 52 | 1-6 direct, 7-10 eighth-finals; the champion goes up to the SHL |
| Czech Extraliga | 52 | 1-4 direct, **5-12 a best-of-5 wild-card round** (5 v 12 ... 8 v 9) |
| Maxa liga | 52 | 1-5 direct, 6-11 in three home-away-home series; the champion plays the Extraliga's last club (best-of-7) |
| National League | 52 | the play-in is **two games on aggregate goals** (7 v 8, 9 v 10, then the 7/8 loser v the 9/10 winner); 13 v 14 play out |
| Swiss League | 50 | 1-6 direct, 7-10 pre-playoffs, a **fixed bracket**; the champion, if it applies, plays the NL's play-out loser |
| DEL / DEL2 | 52 / 52 | 1-6 direct, 7-10 best-of-3; the DEL2 champion goes up if licensed and the DEL's last goes down |
| ICE Hockey League | 52 | 7-10 pre-playoffs (the 7th **picks** the 9th or 10th); the top three **pick** their quarterfinal opponents |
| Alps Hockey League | 36 | a **Master Round** (top five, bonus 4-3-2-1-0) and two **Qualification Rounds**, then pre-playoffs and picks |
| Slovak Extraliga | 54 | 7-10 a best-of-5 wild-card round |
| Elite League (UK) | 54 | the regular-season winner takes the league title; **two-game aggregate** quarterfinals, a **Final Four** of single games and a third-place game |
| Norway | 45 | the top 8; each round the best club left **picks** from the two lowest |
| Mestis | 49 | the top 8, re-seeded, and a single third-place game |
| Denmark, France | 48, 44 | the top 8, best-of-7 |
| BCHL | 54 | the best 16 (the world has no divisions for it); the BCHL Cup |

**Picks.** A club choosing its opponent usually takes the one with the fewest points, and now and then the other.

**Promotion and relegation.** It is played between leagues when both are in the world and both are in play: SHL and
HockeyAllsvenskan, National League and Swiss League, DEL and DEL2, the Czech Extraliga and the Maxa liga. The
play-outs and qualification series show under **Playoffs** for both leagues, with the moves underneath. A club that
goes up or down changes league when the new season is scheduled, and takes its players with it. Last season's
tables keep the clubs that played in them. Relegation to a league that is not in the world (Hockeyettan, the
Oberliga, Division 1 in France, Suomi-sarja) is not played. Mestis has no promotion: the Liiga is closed since its
reform.

Saves from before v61 keep any series already under way. The new formats start with each league's next playoff
round, and promotion and relegation start with the season in progress.
