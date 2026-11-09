# Trades (hs/game/roster.py, hs/game/trades.py)

## Your trades (hs/game/gm_trades.py, v20)
Your offers are judged exactly the way AI clubs judge each other (below): the league's perceived value of each
player, contract surplus, picks by slot, and the other club's position (rebuilding clubs pay more for youth and
picks, contenders for help now; a received player at the club's weakest group counts 1.2x).

| Rule | Setting |
|---|---|
| accept | what they receive >= 105% of what they give, by their own weights, plus the friction premium |
| friction (v39) | they want 1.05 + friction/100 of what they give (see "How the market decides"); friction 90+ is untouchable; both sides valued as packages (100%, 80%, 64%) |
| asked out | a player who asked for a trade goes for 75% of his value |
| just moved | nobody traded this season, or signed in the last 30 days (a free agent: a year), can move |
| picks | the next two drafts not yet started, rounds 1-7; a pick you got from another club keeps its slot |
| your roster | if the trade leaves you short, your best prospects are recalled; it fails if there is no one to recall |
| calendar | until the trade deadline; again from the draft through the preseason |

- `trade ABBR give Suzuki, 2027 2nd get Knies, 2026 1st TOR [retain Suzuki=50]`: picks are `<year> <round>`, plus
  the original club for one you got from elsewhere (`2027 2nd TOR`).
- `tradecheck ABBR give ... get ...`: their verdict and the numbers, without making the trade.
- `ask ABBR get Knies`: what it would take. They name the cheapest one to three of your prospects, picks and depth
  players (cheapest by your own valuation) that they would accept, searched over every combination of the 30
  assets they value most.
- `picks [ABBR]`, `block <player>` / `block remove <player>`, `offers`, `accept <id>`, `decline <id>`.

**AI clubs call you.** On an in-season day there is a 3% chance (8% in the deadline rush, three times either while
you have someone on the block) that a club whose weakest group one of your players would improve builds the cheapest
package it can that you would value at 105% of him, and calls. It never asks for your core unless he is on the
block, and only makes offers you could accept without signing anyone. Offers last three days (at most three open);
`sim` stops on the day one arrives.

**The Trade screen** (UI): pick a club (its posture and weakest group are in the list), tick what you give and what
you want; their verdict updates as you tick. "What would it take?" ticks the package they would accept; "Propose"
sends it. Your players carry Block buttons; offers to you sit beside with Accept and Decline. Salary retention is in
the command box (`retain`).

## Three-team trades (hs/game/trade3.py; UI v26)
You and two AI clubs; any asset can go to either of the other two clubs. Each AI club judges its own part exactly as
in a two-club trade: what it receives, from either club, against what it gives up, to either club (105%; 130% for a
core player; a contender will not move its core). A club can be a pure facilitator (it takes a contract and passes on
a pick) as long as what it gets is worth more than what it gives. The whole deal goes through or none of it does;
roster limits and the cap are checked on the final state; no salary retention.
- UI: Trade → Three clubs. Pick clubs A and B; every row has a "Send" menu (stays / → the other clubs); both verdicts
  update as you choose. Click any name for his card without leaving the screen.
- CLI: `trade3 COL CBJ; me>COL: Gallagher, 2026 1st; COL>CBJ: Manson; CBJ>me: Sillinger` (`trade3check ...` to ask
  first).

## AI-to-AI trades
Clubs other than yours trade with each other. The same `roster.trade` applies, so every AI deal obeys the same rules
as yours. One attempt:

1. **Buyer and need.** A buyer is drawn (contenders 1.5x as likely, 3x in the deadline rush; sellers 0.3x). It
   looks for help at its weakest group (forwards, defence, goalie) measured against the league average of each
   club's top lineup (top 6 F, 4 D, 1 G).
2. **Targets.** Players on other AI clubs at that group who would make the buyer's top lineup and whose club sells:
   - sellers move players 26+ or on expiring deals; middling clubs only 30+ or expiring 27+; contenders nobody;
   - a club's core (top three skaters and its starting goalie) is off limits unless 31+, expiring, on a seller;
   - a player who asked for a trade is always available, at 75% of his value, and his club canvasses every club
     that would play him (`shop_request`);
   - nobody is traded twice in a season, and a newly signed player cannot be traded for 30 days.
3. **Package.** The cheapest set of up to three assets the seller accepts, drawn from the buyer's prospects, its
   1st-4th round picks in the next two unused drafts, and depth players at the same position (only as many as it can
   spare without falling below 12 F / 6 D / 2 G).
4. **Both sides must win from their own position.** Rebuilding clubs value youth (23 and under) and picks 1.2x and
   veterans 30+ 0.85x; contenders discount prospects and picks (0.8-0.85x) and pay 1.2x for the player who fixes
   their need. The seller must get 105% of its valuation; the buyer must not pay more than the target is worth to it.
5. **Execution.** Rosters are topped up around the deal (prospect recalls, then free agents); if the cap blocks it,
   a non-contender (or any club moving a player who asked out) may retain 50%. A deal that would leave either club
   unable to dress a lineup is rolled back.

### How the league values players
GMs do not see hidden ratings. `trades.perceived_values` blends a player's rating value (40%) with his NHL record
over the last two seasons (60%): ice time per game and points per game for skaters, games and save percentage for
goalies. Each becomes a normal score from its mid-rank percentile within the position group; the two are averaged,
rescaled to unit spread, and placed on a normal curve with the group's mean and spread of rating values (v21).
Before v21 the percentile picked an entry from the sorted list of rating values; ratings are whole numbers, so that
list moves in steps and different records landed on the same value (Pastrnak, Suzuki and an NHL-less Kastelic all
at 55.6). Forwards on the 2025-26 world after two seasons: 89 distinct perceived values before, 104 after; AI trade
volume unchanged (35 in a season). Players with under 10 NHL games keep their rating value, so ties remain among
them, and the star premium is still limited by how compressed the world's ratings are at the top (the best
forwards sit 5-10 points above the league average on a 0-100 scale): a calibration question for the ratings model,
not the trade engine. Young players
also carry 40% of the gap to their potential (prospects in the minors at a 15% risk discount); goalie value
differences are stretched 2.5x because goalie ratings are compressed.

### Picks
Picks are assets: `draft_pick_owners (draft_year, round, original_team_id, owner_team_id)`, the same table the
community config uses. The draft keeps the slot and changes the owner (shown as "from XXX"). This summer's
picks are valued by the current standings (a 1st is worth 40-120, 2nd 26, 3rd 14, later 6); later years at mid-round
with a 10% discount.

### Calendar and volume (before v39; v39's router replaces the attempt rates below, see "How the market decides")
- Trade deadline: rules `contracts.trade_deadline` ("MM-DD") or the first Friday of March. No AI trades after it
  until the draft.
- In season: one attempt on 15% of days (10% before v25); two attempts a day in the 14 days before the deadline.
  Buyers try the cheapest players who would make their top lineup first (v25: with the refitted values, the star
  candidates the old order tried first were priced beyond any package).
- Clubs do not declare themselves buyers or sellers until they have played 20 games (before that, everyone is
  "middle" and only veterans and players who asked out move). Before 10 games, rank comes from paper strength.
- Summer: 10 attempts before the draft starts (pick-for-player deals use this year's picks), 8 when free agency opens.
- At most three trades per club per season.

On the 2025-26 world: about 30 in-season trades by the deadline (most in the last two weeks), plus 5-10 in the
summer; mostly veterans for prospects and picks, with buyers in playoff position.

`trades [n]` lists recent trades and the deadline; the UI has a Trades tab under History and trades appear in
league news. Each trade writes one `TRADE_COMPLETED` event (payload: players out, picks, retention, whether the
player had asked out) plus the per-player `PLAYER_TRADED` events.

### Tuning knobs (top of hs/game/trades.py)
`P_ATTEMPT`, `RUSH_ATTEMPTS`, `DEADLINE_RUSH_DAYS`, `OFFSEASON_ATTEMPTS`, `MAX_TRADES_PER_CLUB`, `TOP`,
`TV50`, `REPLACEMENT`, `TRADE_EXPONENT` (roster.py), `ATTEMPTS`, `MIX`, `USAGE_WEIGHT`, `PROJECTION_SHARE`, `PROSPECT_RISK`, `GOALIE_STRETCH`, `REQUEST_DISCOUNT`.

### Star limits and three-team deals (v30)
Players valued in the league's top 15% (`STAR_SHARE`) move between AI clubs only when the seller is selling, at most
`STAR_TRADES_MAX` (4) a season, and only on a `STAR_P` (20%) chance per opportunity, `STAR_P_RUSH` (45%) in the deadline
rush. After an AI trade, `three_team_tail` may (`P_THREE_TEAM`, 4%) bring in a facilitator: a third club with cap room
takes a $1.5-5M contract off one side for a 4th-round-or-later pick. The headline names all three clubs.

## How the market decides (v39)

Jeremy's notes (7 Nov 2026) argued that the trade engine moved NHL regulars far more than real clubs do, because
every AI trade was "a buyer finds a top-lineup player and pays for him", and proposed a friction-based model
(transaction types by tier, a friction factor, need scores, a pick curve, prospect certainty, package decay,
retained salary as an asset, clauses, and dressing-room effects). v39 adopts most of it, adjusted where the numbers
or our engine called for it. The formulas live in `hs/game/trade_model.py`; the router in `hs/game/trades.py`.

### What real clubs do (the targets)
* **2024-25 in season: 74 trades** (ProHockeyRumors' in-season list). Classified by hand: about 38% minor-league
  swaps or players for future considerations, 27% depth NHL players for picks, 35% trades involving a top-nine
  forward, top-four defenceman or starting goalie. The notes' split (45 / 30 / 15 / 10) underweights the last group:
  real seasons move 20-25 regulars, of whom 6-10 are genuine top-six / top-four players.
* **Timing:** 37 of the 74 in the deadline week, 23 on deadline day itself (NHL deadline stats pack: 16-32 deadline-day
  trades a season since 2005, 23 in 2024 and 2025).
* **2025 offseason: 55 trades**, 25 around the draft and 18 of them pick-for-pick swaps.
* **Prices:** a late 1st buys a top-six rental, a 2nd a middle-six regular, a 4th-7th or future considerations a depth
  player; two 1sts are for stars.

### The router (adopted from the notes, recalibrated)
Each day the router decides the *kind* of deal before it looks for players (`MIX`, by phase):

| Phase | Attempts a day | minor | depth | rental | roster |
|---|---|---|---|---|---|
| early (to 31 Dec) | 0.33 | 52% | 23% | - | 25% |
| mid (to two weeks before the deadline) | 0.55 | 47% | 23% | - | 30% |
| rush (last two weeks) | 5 | 20% | 15% | 35% | 30% |
| deadline day | 75 | 20% | 15% | 35% | 30% |
| draft window | 60 | 10% | 15% | swaps 25% | 50% |
| free agency window | 55 | 25% | 25% | - | 50% |

* **minor**: a minor-leaguer (22+, short of a top-prospect potential) for another, or for future considerations
  (clubs near the 50-contract limit do this most); cap hits count as buried.
* **depth**: a player outside the seller's top nine forwards / five defencemen / starting goalie, or a minor-league
  veteran 25+, to a club whose depth he improves, for a 3rd-7th or future considerations. **Waiver value collapse**
  (from the notes): a player who would need waivers to go down is worth no more than a 7th. A **cap dump** (his
  contract is worth less than nothing) goes only from a club within $2M of the cap, with a pick attached; in season
  rarely (30% of the chances).
* **rental** (new): at the deadline a club out of the race (S < 0.45) sells a veteran on an expiring deal to a club in it
  (S >= 0.55) whose top nine / five / starter he joins, for picks.
* **roster**: the pre-v39 trade (a buyer at its highest-need group, the cheapest candidates who make its top lineup),
  now gated by need and friction, or (25%) a like-for-like **hockey trade** between clubs with opposite needs.
* **swap** (draft day): moving up within a round (a worse pick plus a later one, or next year's), 60% of the clubs
  asked have a player in mind.
* Per club: at most 4 roster trades and 9 deals of any kind a season.

### The value scale (adjusted)
The notes used a 1000-point pick scale. Ours keeps the trade scale the AI already used but fixes its real flaw: it
had no replacement level, so a fringe forward was priced like a late 1st and every trade looked like "regular for
prospects". v39: `trade_value = 30 * ((value - 42) / 8) ** 3.3` (0 at replacement, 30 for an average regular, about 85
for a 75th-percentile player, 190 at the 90th, 550 at the top), fitted to the deadline prices above.

### Need, friction and the overpay (adopted)
* **Competitive state** S = 1 - (rank - 1)/(n - 1).
* **Need score** N per club and position group: the roster deficit against a playoff club's depth (65th percentile
  at each slot, weighted 1.0/0.75/0.5/0.25 by line) weighted by alpha = 0.2 + 0.8 S, plus the pipeline deficit
  (prospects' potential times readiness) weighted by beta = 1 - 0.8 S, plus urgency for top-lineup players out three
  weeks or more. 0-100.
* **Friction** F: 30 q^2 for q standard deviations above the group mean, times term (1 + 0.12 per extra year) and cap
  share; x0.7 for a rental; +40 NMC, +30 NTC, +10 modified list; +15 captain, +8 alternate; x1.25 on a contender,
  x0.7 on a seller, x0.6 in summer, x0.3 if he asked out; capped at 100. The notes' cube grew too fast on our spread,
  so it is a square with a cap.
* A club only pursues a player when N >= F, and the seller wants **1.05 + F/100** of his value. Your trades use the
  same rule (it replaces the flat 130% "core" premium); a player at F >= 90 is untouchable unless he asked out.

### Picks, prospects, packages, retention (adopted, refined)
* **Picks:** the notes' power law V = Vmax p^-gamma is unbounded at the top and too flat at the bottom; v39 uses an
  offset power law `13960 * (p + 14) ** -1.5` (1st overall 240, 16th 85, 32nd 45, mid 2nd 29, mid 3rd 15, 7th 4).
  Later drafts regress to mid-round and lose 15% a year; a weak club's future 1st carries up to 30% for the lottery.
* **Protected picks** (register #5 and #11): a 1st can be top-3, -5 or -10 protected. Value = P(out) x V(outside the
  range) + P(in) x V(next year's 1st). At the draft, a protected pick that lands in the range stays with its club and
  next year's 1st goes instead (`pick_protection`, draft.py). In the trade screen, a protection menu beside each of
  your 1sts; in commands, `2027 1st top10`.
* **Prospect certainty** (adopted): the share of the gap to potential in a young player's price is 0.65 at 18 and
  falls by C = 1 - ((age-18)/6)^1.5 x 2 x gap; centres and defencemen in the minors carry 10% / 5% more, goalies 20%
  less ("goalie voodoo").
* **Package decay** (adopted, 0.8 rather than 0.75 because packages here are 1-3 pieces): best piece 100%, then
  80%, 64%; applied to both sides, AI-to-AI and yours.
* **Retained salary** (adopted): 10 points per $1M of cap kept (this season's remaining share plus later seasons),
  times 1 + (15 - the retaining club's room in $M)/5, at most 3. Charged to the buyer in AI deals and counted on
  your trades (`retain`).

### Clauses (adopted; generated, since the export has none)
NMC, full NTC and modified lists (8-16 clubs), on about one NHL contract in five: only for players 26+ when the deal
started, two years or more, more likely and stronger with the cap hit. A modified list names the clubs he rates
worst (competitive state, with noise), refreshed each season. A full clause is waived only if (S_to - S_from) +
(role_to - role_from) >= 0.5 (loyal players need 0.2 more, a 33+ veteran going to a contender 0.15 less, a player who
asked out nothing). An NMC also keeps your player out of the minors unless he agrees. `hs/game/clauses.py`.

### Dressing room (partly adopted)
A contender that adds a regular gets +2 cohesion; a club in the race (S >= 0.45) that sells a top-lineup player for
futures loses 3. The notes' tenure-and-leadership shock and the chemistry tax were already in the game (people.py
counts leaders traded away; line chemistry is built from games together and starts at zero for a new player), so
they are not doubled.

### Not adopted
* A separate "waiver queue jump" type: it is the depth deal's waiver value cap.
* The notes' 10% share for core trades and the offseason "50% core" mix: the real numbers above are higher in season
  and lower in summer.
* Hard-coding Winnipeg and San Jose onto lists: lists follow competitive state with noise.

### Result (the bundled 2026-27 world; final settings, two seeds, a season and a summer each)
76 and 80 in-season trades (real 2024-25: 74): 23-26 minor-league deals, 26-29 depth deals, 25-27 involving NHL
regulars (about a third, as in the real season), of whom about 6 are top-30% players and 10-16 deadline rentals. 18-20
on deadline day (23), 48 in the last two weeks. 64-65 in the summer (55), with 8-9 pick swaps plus 14 draft-floor
moves. Before v39 the same world made 24 in-season trades and every one moved an NHL regular; prices now look like
the real market (a 1st and a 3rd for Taylor Hall, a 2nd and a 4th for Max Domi, a 1st for a top-four defenceman).

### Rumours (v30, hs/game/rumours.py)
When a club turns down your offer, each of your players in it may leak as "shopped": 25% the first time, 15% more each
time after. A leak is a rumour story and costs the player trust in you and morale (more with ego and loyalty, more each
time); a proud player (ego 14+) shopped three times asks for a trade. Three or more of your players in rumours within
30 days costs the room 3 cohesion and the head coach writes to you (once a month).

### Shopping a player (v42, hs/game/shop.py)
"Shop him" (his page, the trade screen, or `shop <player>`) tells the league he is available and puts him on the block.
* **Who calls**: clubs open for business whose need at his position is at least 70% of his friction and whom he would
  help (their top nine F / five D / starting goalie, or their depth). A clause can rule clubs out (one that rules out
  every club stops the shop). At most five clubs: the keenest.
* **When**: the keenest first, in 1-3 days if it badly needs him (need 70+), 3-6 otherwise; the rest a day to three
  apart. Never the same day, never all at once. The shop runs 14 days; offers stand 5 days.
* **How much**: the opening offer is worth to you 70-80% of his value when the club's need is under 40, 80-92% at
  40-70 and 92-102% at 70+ (+5% for a contender in the deadline rush). Each offer's note says which.
* **Him**: he hears about it (a trust and morale knock, as when his name leaks in a rumour).
* If nobody calls, your assistant tells you at the end. `shop` lists your open shops; `shop stop <player>` ends one.
While you shop a player, the ordinary calls about him stop: his offers all come from the shop.

### Conditional picks (v41)
A 2nd-to-7th-round pick in this season's draft can carry a condition: it **upgrades one round** if a club (by default
the one giving it) makes the playoffs, or wins a playoff round. If it comes true, the club that gave it hands over its
pick one round higher instead and takes the lower one back; the higher pick is held against it until the draft (it
cannot be traded, and the AI does not shop it). Conditions are settled when the draft order is set: met, lapsed, or
met but the higher pick is no longer the giver's (then the lower pick stands). The draft message lists each one.

Value = (1 - p) x V(the pick) + p x V(the pick one round higher, same slot), where p is the chance of the condition:
a normal spread around where the club stands (sd 1.5 + 6 x the share of the season left) against the playoff line
(the rules' qualifiers: 16 of 32 in the NHL), and for "win a round" times 0.15-0.85 by rank. A contender's
conditional pick is worth nearly the higher pick, which is why sellers like them.

* **You**: on the trade screen, a menu beside each eligible pick you give ("1 rd up if we make the playoffs" / "if we
  win a round"); console `trade TOR give 2027 2nd if playoffs get ...` or `2027 3rd if MTL round2`.
* **The AI**: at the deadline a buyer may offer an eligible 2nd-4th with a condition on itself (half the time it can):
  "win a round" if it is strong (competitive state 0.75+), "make the playoffs" otherwise. A test season on the bundled
  world made two (one met, one lapsed).
* Stored in `pick_conditions` (draft_year, round, original club, giver, kind, club, status).

### Not yet
Pick-swap rights and conditions on players (games played, re-signing), three-way deals of your own with AI clubs countering, AI clubs countering your proposals with
changes (they answer yes or no, and `ask` gives their price).
