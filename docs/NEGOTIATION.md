# Contract talks (hs/game/negotiation.py, v26)

Instead of typing a number and getting yes or no, you negotiate with the player's agent, round by round. Talks open
from the player page (an expiring player of yours, or a free agent), the Contracts screen (Talk), the Offseason
screen (Negotiate, for expiring contracts and free agents) and any player card. The deal that closes is signed
through the normal rules (`extend` for your players, `sign` for free agents), so talks can never get a player below
what the rules accept, and everything else (cap, roster, contract limit) is checked as usual.

## The agent
Every player has a fictional agent with a style, the same every time you deal with him:

| style | opens above his floor | gives up of the gap each round | patience (rounds) |
|---|---|---|---|
| hard-nosed (shark) | 28% | 25% | 3 |
| businesslike (pro) | 16% | 40% | 4 |
| easy to deal with (friendly) | 8% | 55% | 5 |

The player's personality moves it: ego (+2% per point over 5) and ambition raise the opening, patience 7+ adds a
round.

## What he wants
- **Term**: a preferred length by age and status: young RFAs a two-year bridge, or six years for the best of them;
  25-30 the maximum; 31-33 three or four; 34+ one or two. Every year away from it costs 3.5% (shorter or longer).
- **A no-trade clause**: veterans 27+ on an extension want one. Granting it takes 4% off; refusing costs 2%.
- **Winning**: an ambitious player (7+) charges a bottom-eight club 5% more and gives a top-eight club 3% off.
- **Trust**: under 35 trust in you, 10% more (the signing rules already add this in season); 65+ trust and loyalty
  7+: a 4% hometown discount.
His **floor** for a term is the least he will take; it never goes below what the signing rules accept.

## A round
- An offer at or above his current ask for that term: agreed, and the contract is signed now.
- Within 3% of his ask and at or above his floor: agreed ("let's get it done").
- Under 80% of his floor: an insult. Two rounds of patience gone, his mood sours, and his ask does not move.
- Under 92%: a round gone and he moves half his usual amount.
- Closer: a round gone and he gives his style's share of the gap.
- Patience at zero: talks break off for 14 days, and your own player loses 5 trust in you.
When his mood drops below 45 the player sometimes speaks up himself.

## The screen
Left: the agent, the player and his current deal, patience pips and mood, and what matters to him. Right: the
conversation, his ask at every term (his preferred term outlined), an AAV slider, a no-trade box when he wants one,
our analysts' fair value for the term (hs.game.valuation), Make offer, Offer his ask, and Walk away.

CLI: `negotiate <player>`, `propose <player> <aav> <years> [ntc]`, `endtalks <player>`.


## v39: trade protection, pitches, gentler concessions (register #7)

* **Concessions.** An agent never drops more than 2.5% (hard-nosed), 3.5% (businesslike) or 5% (easy to deal with) of
  his demand in one round, so a deal no longer falls by $1.7M in one call.
* **Trade protection** is a choice in the talks window (and `propose <player> <aav> <years> [mntc_late|mntc|ntc|nmc]`):
  none; a 10-team no-trade list in the last two years (half a level); a 10-team list (1); a full no-trade clause (2);
  a no-movement clause (3). A player 27+ asks for a level: 1, or 2 when he is valued 55+, or 3 when 58+ with an ego
  of 12+. Each level you grant up to his ask takes 2.5% off; each beyond it 1% more; each level short of it costs 2%.
  The clause you sign is a real one (docs/TRADES.md "Clauses"): it can stop you trading him later.
* **Pitches**, once per talks: *Sell him on home* (his country is your club's; worth 2.5% to a loyal or 30+ player,
  1.2% otherwise; otherwise -1 patience), *Friends in the room* (players he has played with, or three countrymen;
  1.5-3%; otherwise his mood dips), *A chance to win* (your competitive state: a contender 3% to an ambitious player,
  1.5% to others; the middle 0.8%; a bottom club costs mood and patience).

## v41: contract structure
Beside trade protection, choose how the deal pays (docs/FINANCE.md "Cap and cash"): **flat**, **front-loaded** (a 10%
step down each season) or **signing-bonus heavy** (front-loaded, with 40% of each season's pay as a 1 July bonus at
$7M+, 25% at $4-7M). The cap hit is the same; a player values money early, so the asks drop 1.5% for front-loaded and
3% for bonus-heavy (the screen shows the lowered asks). Console: `propose <player> <aav> <years> front|bonus [ntc]`.
