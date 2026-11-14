# Running a European club (v61)

You can take a job with a club in any European league that plays game by game: the KHL, SHL, National League, Liiga,
Czech Extraliga, DEL, the second tiers and the smaller top leagues. League > **European club** lists them; so does the
Job Centre. Console: `club start` lists them, `club start <club>` takes the job.

You can also **start a career in Europe**. In the new-game screen, choose a European league at step 3 (World). Step 4
then lists its clubs, strongest first, with each club's outlook and best players. The game opens on the Club screen.

Taking a European job empties your NHL seat. The NHL plays on under its AI, as when you are out of work, and NHL
jobs stay open to you. A good European record is a way back into the NHL: when an NHL club hires you, the European
club's AI takes over.

## How European hockey is run

There is **no draft and there are no trades**. Clubs grow players in their academies and recruit the rest.

* **Contracts** run one to four seasons at a yearly wage. A player whose contract has ended is a **free agent** and
  moves for nothing.
* **Transfers.** For a player under contract, his club must first agree a **fee**, which buys out his deal. He then
  agrees his own terms.
  * The fee asked is about 0.8 x his wage x the seasons he has left (plus half a season before the new year).
  * It rises for the young (x1.6 at 21 and under, x1.3 to 24), falls for veterans (x0.7 over 30), and rises again for
    a key player (x1.5 for a top-six forward, top-four defenceman or starting goalie).
  * A club sometimes refuses to sell one of its two best players at any price. It never lets its squad fall below
    12 forwards, 6 defencemen and 2 goalies.
* **His terms.** He wants at least his current wage, and at least the going rate for a player of his ability in your
  league. He takes 10% less to step up to a stronger league and wants 25% more to step down.
* **Loans** are limited transfers. A player joins until a date (30 April at the latest) and then goes home. You pay a
  share of his wage: at least half for a player 23 or under, three quarters for older players.
  * Clubs lend players outside their top lineup (9 forwards, 5 defencemen, 1 goalie).
  * Veterans will not drop more than one level for a loan.
  * You can lend your own players to clubs in your league or below (they take him if he would play), and recall
    them.
* **The window.** International transfers run from **1 July to 15 February** (the IIHF regulations); outside it
  nobody moves.
* **Imports.** Your league's import limits apply to every signing.
* **Offers for your players.** While the window is open, a club from a league as strong as yours or stronger comes in
  for one of your best players about every three weeks. An offer stands for a week. The fee goes to your transfer
  budget.
* **The summer (1 July).**
  * Loans end and players go home.
  * Your players whose contracts ran out leave, unless you extended them in time.
  * AI clubs keep about four in five of theirs (fewer of the old and the weak). The rest become free agents.
* **The academy (mid-September).** Four youngsters of 16-17 come up from the club's junior teams on three-year academy
  deals.
* **Releasing** a player pays out half of what is left on his deal, from your transfer budget.

## Money

Money is kept in euros and is approximate. It is shown in your display currency (the Currency menu; docs/CURRENCY.md);
offers you type are in euros. A league's typical wage comes from its strength, at about €25,000 x e^(1.15 x
(league mean - 7.6)): roughly €175,000 in the SHL, €60,000 in HockeyAllsvenskan, and 2.5 times that in the KHL. A
player's wage rises with his ability above his league's mean.

Your club's **transfer budget** (about two league wages, more at the league's bigger clubs) and **wage budget** (your
wage bill with a margin) are set when you take over and again each summer. Fees you receive go into the transfer
budget.

## Lineup and tactics

A European club is picked on the same screens as an NHL club (Team > Lines, Tactics; the Lineups lists):

* **Lines**: four lines, three pairs, the starter and backup, power-play, penalty-kill and overtime units, tendencies.
  Automatic lines come from last season's ice time until you save your own.
* **Lineups**: the priority lists that rebuild your lines before each game, and the goalie rule.
* **Tactics**: the twelve settings, the presets and the preferences. Your players' fit is measured against the clubs
  of your own league.

**Your club's games are played by the full game engine**, as an NHL club's (hs/game/eu_match.py): your lines,
power-play, penalty-kill and overtime units, goalies, tendencies and tactics count exactly as they do in the NHL, and
the opponent dresses its own best lineup. Every game has a box score, a recap and the 2D replay: the sim centre's game
card has *Full recap & replay*, and your games in its scores link to their pages. The result goes into your league's
table and its season statistics like any other.

Ratings are measured against your own league (its average dressed player), as an NHL game's are against the NHL's, so
a game plays at the engine's usual pace and only the difference between the two clubs counts. The rest of your
league, and every other league, is played by the quicker results model; so is the second game of a two-game series
on aggregate goals (a few play-ins).

## The board

* **The target.** Each September, and when you arrive, the board sets a target from the squad's rank on paper in
  the league, plus one place of slack: "a top-N finish". The strongest squad is also told to win the title.
* **Monthly.** Confidence starts at 60. On the first of each month in the season it moves 3 for each place you stand
  above or below the target (at most 8 either way). It falls 5 more if the wage bill is over budget.
* **The review.** When your league's season is over:
  * Title: +25 confidence, +6 reputation.
  * Target met: +15, +3.
  * Missed by up to three places: -10.
  * Missed by more: -25, -3 reputation.
  * Missing a title the board expected costs 5 more.
* **The sack.** At 20 or below you are sacked (-5 reputation) and the club looks for a new coach.

## European jobs

* Your first European job can be any club. After that you **apply for openings**: Job Centre > Manage in Europe, or
  the Board tab.
* Each summer, clubs that finished three or more places below their strength rank part with their coach four times
  in ten.
* A club wants a reputation from 20 (the weakest club of the weakest league) to 75 (the best club of the strongest).
  Your chance is 50% at that reputation, 3% per point either way, between 3% and 97%.
* Each club interviews you once a month. When an NHL club hires you, you leave Europe.

## The rest of Europe

* **Window business.** Every Monday in the window AI clubs do business: five moves a week in July and August, two
  after that. A club buys a regular for a position from a league no stronger than its own, pays his fee and gives
  him the going wage. Notable moves make the news.
* **Loans.** Every Monday from August until the window closes, three AI loans a week: a club lends a player of 22 or
  under from outside its top lineup to a club a level or two down where he will play, usually in the same country
  (SHL to HockeyAllsvenskan, National League to Swiss League, Liiga to Mestis, KHL to VHL). Now and then one goes
  to a neighbour (a Swede to Norway or Denmark, a Czech to Slovakia). Russian clubs deal only with Russian clubs.
  The borrower pays half his wage, and he goes home when the season ends.
* **NHL signings.** On 1 July each of your players 27 or under who is as good as an NHL regular (the 25th percentile
  of NHL roster players) may sign in the NHL: four in ten each summer, and fewer from the KHL. He goes to the club
  holding his draft rights, else a club with room. Your club gets the transfer-agreement compensation, €220,000
  (about the Swedish agreement's US$240,000). The KHL has no agreement, so a KHL club gets nothing.

## While you sim

* **The sim centre follows your league.** It shows that league's scores, your club's game, its table, and news about
  its clubs.
* **It stops for your club's business.** A bid for one of your players, a word from the board, or the academy's new
  faces stops a day, week or next-game sim. A season sim plays on.
* **Out of work, the NHL is the default.** With no club at all, the sim centre shows the NHL as before.
* **Your season starts with your league's.** A new game at a European club starts the day before its league opens
  (the KHL on 5 September, the SHL on 12 September), not on the NHL's opening night. In later seasons training camp
  opens a week before your league and the new season the day before it, so you play every game of it. The NHL keeps
  its own calendar: its games start in October as usual.

When your league's season is over, the sporting director lists the contracts that end on 1 July and what each player
wants to stay. On the Squad tab those contracts read *ends this summer*.

A club that fired or sacked you, in the NHL or in Europe, is not an opening for you for a year. It is left off your
list, and an application to it is turned down.

## The league screens

While you run a European club, the league screens are about **your league** first:

* **Standings** and **Playoffs** (League menu, Standings tab) show your league's table, groups, play-in and playoff
  series, with your club highlighted.
* **Statistics** (leaders, skaters, goalies, teams) opens on your league; your players are marked.
* **Schedule and Results** and the **Calendar** are your club's games, with *Recap & replay* for each game played,
  and the transfer window's dates.
* **News**: headlines about your club or your league (transfers, loans, releases and its stories), the recaps of your
  games, and power rankings from your league's table and last ten games.
* **Team > Team Page** is your club's page.

A **League** picker above Standings, Playoffs and Statistics shows any league played game by game, the NHL included;
the choice lasts for the session, and *Back to your league* returns. Screens about the NHL only (the draft, free
agency, analytics, playoff odds, league trades, awards night...) are marked **NHL** in the menus.

## Your club's screens

A European club uses the game's own tabs, with what each means in Europe:

| Tab | For a European club |
|---|---|
| Office | the board: target, confidence, last verdict; bids for your players; European openings |
| Roster | the squad, and players out on loan (Recall) |
| Lineup | the Lines screen (above), with Tactics and the Lineups lists |
| Contracts | wages, contract ends, what each player wants to stay; Extend, Lend to, Release |
| Transfers (the Trade tab) | the transfer market: Transfer or Loan, filters by position, age and fee; *Offer* asks for the fee and his wage |
| Transactions | every bid and its answer |
| Standings, Statistics, News | as in the NHL; your league's table is on League > World Leagues |

Prospects, Scouting, Staff and Calendar are NHL screens and stay greyed while you run a European club.

## Not yet

* Staff (coaches and scouts) at a European club.
* Club finances beyond the two budgets: gates, sponsors, a bank balance.

Console: `club`, `club market [F|D|G|C|LW|RW] [age<=N] [fee<=N] [free]`, `club buy <player> <fee> <wage> <years>`,
`club loan <player> [share%] [until YYYY-MM-DD]`, `club lend <player> <club>`, `club recall|release <player>`,
`club renew <player> <wage> <years>`, `club offer <id> accept|reject`, `club lineup [auto | <player> F1-F4|D1-D3|G1|G2|X|auto]`,
`club tactic attack|balanced|defend [60-90%]`, `club board`, `club jobs`, `club apply <club>`.

Code: `hs/game/europe.py` (the market), `eu_lineup.py`, `eu_board.py` (the board and jobs), `eu_world.py` (window
business and NHL signings). Nothing in it runs unless a European career has started, so NHL careers play exactly as
before.
