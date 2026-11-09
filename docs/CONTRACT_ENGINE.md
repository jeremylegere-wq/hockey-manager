# Contract engine (v14-v20)

Valuation and the free-agency auction (v14) are what everything else hangs off; v15 adds weak-class scarcity,
bargains, RFA bridge vs long-term deals, regret, buyouts and salary dumps; v16 offer sheets; v17 failed offer sheets, the arbitrator's box-score lens, entry-level bonuses and the slide
rule, and college picks who refuse to sign.

## 1. Valuation (hs/game/valuation.py)
"Surplus value", after the public models (projected wins above replacement priced at the market cost of a win):

| Step | Formula |
|---|---|
| current level | perceived overall: 40% ratings, 60% NHL record (ice time and points per game; goalies' games and save %) |
| ageing | the market's typical curve: +0.35 a year at 18-20, +0.17 at 22, +0.04 at 24, flat 25-28, -0.03 at 29, -0.08 at 30 ... -0.21 at 34, -0.28 at 35, then faster; goalies two years later |
| wins | WAR = scale x (overall - 9.9)^1.5; scale fitted so rostered players total 15 wins above replacement per club |
| cost of a win | (cap x clubs x 95% - minimum x rostered players) / total wins: about $5.3M at a $104M cap; grows 5% a year |
| season value | minimum salary + WAR x cost of a win (x0.65 for goalies; no goalie fair value above ~11% of the cap) |
| surplus | sum of season values over the term - cap hit x years |
| grade | A +$10M or more (elite bargain), B +$3M, C within $3M (fair), D down to -$10M (overpay), F worse (albatross) |
| risk | 200 futures with a starting error (sd 0.18) and a yearly random walk (sd 0.12): chance the deal ends positive |
| fair AAV | the AAV with zero surplus for a given term (within the league maximum) |
| star ceiling (v25) | above 9% of the cap (~$9.4M at $104M), only 25% of the extra value becomes fair AAV: the NHL's best earn 12-13% of the cap, nowhere near the 20% maximum |

Clubs never see a player's hidden development profile, so late bloomers and early decliners are where contracts go
right or wrong. Stars are worth far more than the maximum salary, so star max deals grade A; depth players on long
deals over ~$4M rarely grade well.

`value <player>` shows his current deal year by year; `value <player> 8.5m 6` prices a proposed one. The UI's player
screen has a Contract value panel, and the Contracts screen a value grade for every deal.

## 2. Free agency as a timed auction (hs/game/free_agency.py)
Opening day runs in rounds at noon, 12:30, 1, 2, 4 and 8 pm, then days 2, 3, 5 and 8. Free agents are tiered by
perceived overall: Tier 1 >= 11.3 (stars), Tier 2 >= 10.5 (middle six / top four), Tier 3 >= 9.6 (depth).

| Mechanism | Rule |
|---|---|
| what a player wants | the term for his tier and age (Tier 1 at 27-29: the maximum; 30-31: 5; 32+: 3; Tier 2: 4-5, 3 at 32-33, 2 at 34+; Tier 3: 1-2) at his fair AAV |
| his ask over time | fair x (0.5 + (peak - 0.5) x e^(-hours/10)); peak 120% Tier 1, 110% Tier 2, 100% Tier 3: half of fair after a day |
| who bids | each AI club with cap room, owner budget room and a contract slot picks the free agent who most improves its top lineup (6 F, 4 D, 1 G) and makes one offer a round, keeping room to fill 23 men at the minimum |
| what it bids | min(fair x (1 + club premium x e^(-hours/6)), ask x (1 + 15% x e^(-hours/6)), cap room); premium per club: Tier 1 10-25%, Tier 2 0-12% |
| panic buy | a club whose first Tier 1/2 target signs elsewhere in the first hour, with $5M+ room, goes after the next best at that position for 90 minutes: +1 year, +$1.5M, no-move clause |
| ceiling (v25) | no ask or bid above 125% of fair value, however scarce the class or panicked the club |
| player's choice | the best offer by utility AAV x years^s (s 0.15 under 30, 0.3 at 30-32, 0.4 at 33+) if it beats his ask; veterans 32+ discount non-contenders 10% |
| afterwards | the unsigned keep their last ask (`fa` shows it) and sign 1-2 year prove-it deals with AI clubs filling rosters, or with you |

**Failed attempts (v17).** Most real sheets are matched (Weber, Sakic, Vanek, Aho, Hjalmarsson, O'Reilly); the ones
that work sit in the low and middle tiers against a club in cap trouble (Kotkaniemi, Broberg, Holloway). The model now
gets there three ways:
- **Stars are matched.** A player 11.3+ (or in the owner's top three) is matched 95% of the time whatever the
  surplus: losing a franchise player for picks ruins clubs (`STAR_MATCH`).
- **Owners clear room.** An owner who wants to match but is up to $4M short trades its worst-value contract that
  covers the gap to a club with room, for nothing, and matches (`CLEAR_ROOM_MAX`). It only moves veteran depth
  (24+, outside the top lineup, not on an entry-level deal). This is how cap-leverage sheets
  fail.
- **GMs misjudge.** Each offering GM reads P(not matched) with an error (sd 0.2, `GM_ERROR_SD`), so some sheets that
  look like winners are matched; and 35% of the time a club that found no good sheet takes a long shot at a star at
  the top of a tier (`STAR_GAMBLE_P`). The Aho failure: a high tier at an AAV the owner can afford.

You: `offersheet <player> <aav> <years>` in the free_agency phase (prints the compensation, then the owner's
decision); if an AI club sheets one of your RFAs you get an inbox message and can `match <player>` until the
arbitration phase, after which he leaves and the picks are yours. `sheets` lists the summer's sheets and the table;
the Offseason screen shows them with a Match button.

### The war room (v27, `#warroom`)
With live mode on (the UI), entering free agency sets up the market and stops; **Open the market** plays noon. The war room shows the clock, the
round, the class's scarcity, your cap room, a ticker of the last round's signings, the market (fair value, the ask now
and its term, dots for the clubs that bid on him last round, your offer box) and the signings feed. Offers stand until
you withdraw them and are heard every round; asks fall through the day. **Next round** plays one round, **Run to the end**
plays the rest. Leaving the phase finishes the auction and then runs offer sheets, the depth market and the summer
trade window as before. Rights and re-signing have their own room (`#rights`): one card per expiring player with his
ask, qualifying offer, arbitration status and buttons for talks, qualify, decline or walk away. CLI: `faround [all]`,
`withdraw <p>`.

## 7. The arbitrator's lens (hs/game/arbitration.py, HearingLens)
Arbitrators read the box score, not shot shares. The hearing value of a player is 75% his box-score percentile
(`BOX_WEIGHT`), mapped onto the league's value scale for his position, and 25% his true value. Box score: skaters
0.7 x points a game + 0.3 x goals a game; goalies 0.6 x save % (x10) + 0.4 x wins a game; platform season 60%, the
season before 40% (`PLATFORM_WEIGHT`), at least 20 NHL games (`MIN_GAMES`), otherwise true value. Comparables,
both submissions and the award use it, so a point producer on a bad defensive team is awarded more than a quiet
play-driver of the same ability. The club's offer is still made against the normal salary market, which is where
the exploit sits: elect arbitration for the second kind of player, avoid it for the first.

## 8. Entry-level contracts (hs/game/elc.py)
| Rule | Setting |
|---|---|
| signing bonus | up to 10% of pay, inside the cap hit. P(maximum): top-10 pick with leverage 95%, top-10 50%, picks 11-32 25% with leverage / 10%, later 2%; otherwise 5% half the time for first-rounders |
| leverage | an alternative the club fears: college (he can stay in school), a European pro club, the KHL |
| performance bonuses (Schedule A) | up to $850K a season for top-10 picks, half for picks 11-32, a quarter for 2nd-3rd rounders with leverage; earned in four equal parts at season end |
| targets | forwards 20 G, 35 A, 60 P, 0.73 P/GP (42+ GP); defence 10 G, 28 A, 40 P, 20 min a game (42+ GP); goalies 25 GP, .910, 22 W, under 2.75 GA a game |
| bonus overage | earned bonuses that take a club past the cap are charged to next season's cap (`cap_charges`, "bonus overage") |
| slide rule | 18-19 on 15 September and under 10 NHL games: the first ELC year slides (at most twice), so he reaches RFA a year later |

You see the terms when you sign (`elc <player>`), list them with `elcs`, and on the player page under Contract value.

Packs without salary data (MoneyPuck worlds) get generated contracts at setup. From v25, anyone 21 or younger is on
an entry-level deal: three years from the season he turned 18 (so a 20-year-old is in his last year), at the ELC
maximum for the league's better players scaling to the minimum. Before, an 18-year-old star drew a market contract
($10M for one rookie defenceman), his qualifying offer was too dear to make, and he became a UFA at 20.

### v25 check (2025-26 world, two simulated summers)
Before the star ceiling and the bid cap, the opening day of free agency signed 3-8 players at or near the $20.8M
maximum each summer (asks and bids ran to 1.3-1.6x fair value in a scarce class). After: the top five new deals
each summer run $13.3-18.7M (the first summer's best was MacKinnon at $18.7M; the second's Makar at $16.6M), and no
one signs for the maximum.

## 9. College picks who refuse to sign
When a college pick's rights are about to lapse (four years after an 18-year-old is drafted), the club wants him
and he can walk to free agency, he refuses with
P = 1 / (1 + e^-(-2.5 + 1.5 congestion + 1.0 pipeline - 2.0 slot value - 1.0 stability + 1.0 leverage)):
congestion is how many players at his position are signed for two more seasons and better than him (0-1),
pipeline the club's young depth at his position, slot value the pick value chart (1st overall 1.0, a 7th ~0.01),
stability the board's confidence in the front office. An AI club whose pick refuses trades his rights while it can
(a 3rd for a top-64 pick, otherwise a 5th) to a club that needs him at his position (pipeline need 0.3+, half of
them willing: `RIGHTS_NEED`, `RIGHTS_DEAL_P`), where he signs; if no one
takes him, he walks into the free-agent pool (Kevin Hayes and Jimmy Vesey walked; Adam Fox's rights were traded first). You get
an inbox warning a year ahead if one of your college picks is at 25%+ risk, and can sign him early (`elc`) or move
his rights (`shoprights <player>`).

## 10. Overpaid RFAs (hs/game/rfa.py, v20)
A qualifying offer is 100% of the last cap hit above $1.75M, so an RFA paid more than he is worth could take it
every summer and stay an overpaid RFA (it happened to young stars on generated contracts, e.g. Lane Hutson at
$12.73M every year). When the QO is at or above his ask:
1. **Term for money** (QO $1.5M+): the club offers 2-6 years at the lowest AAV he prefers to a year at the QO, by
   the free-agent utility AAV x years^s (s = 0.15 under 30: five years at 79% of the QO are worth the QO for one).
   The club pays at most 110% of his fair value for that term and picks the term that saves it most.
2. **Club arbitration**: otherwise, if the QO is $1.5M+, he is arbitration-eligible, has never been taken and the QO is 5%+ over his
   ask, the club elects arbitration (the award can drop to 85% of his salary).
3. Otherwise he signs the QO, as most depth RFAs do.
Long-term deals for young RFAs never pay less than he would accept against his QO. For your own players you get an
inbox message in the rights phase with the deal he would take (`extend` accepts it below his ask, because his
alternative is the QO), the arbitration option, or declining to qualify him.
