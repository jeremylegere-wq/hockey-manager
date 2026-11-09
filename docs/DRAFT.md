# Draft classes, scouting and the draft floor (v13)

Code: `hs/worldgen.py` (classes), `hs/game/scouting.py` (how clubs see prospects and pick), `hs/game/draft.py`
(the draft), `hs/game/draft_floor.py` (pick trading), `hs/tools/draft_lab.py` (calibration).

## Draft classes
Every summer (preseason) a birth-year cohort of 460 17-year-olds (420 skaters, 40 goalies) joins clubs in their home
leagues: Canadians and Americans in the CHL (some Americans in college at 18+), Swedes in the SHL, Finns in Liiga,
Russians in the KHL, Czechs and Slovaks in the Extraliga, Swiss in the NL, Germans in the DEL. The world starts with
classes aged 17-21 (the best of the 19-21 cohorts are left out: in reality they are already NHLers in the pack).
Junior, college and European kids added only to fill rosters are depth players (they start 0.6 below the league
level for their age and grow about half as much), so the classes carry the talent.

Each prospect has a hidden truth and visible traits:

| Hidden | Visible |
|---|---|
| ceiling (`potential`): 7.9 + gamma(2, 0.5) for skaters, a wider and lower spread for goalies | current ability (through scouts' eyes) |
| maturity: early maturers look better now and have less growth left (sd 0.3) | height and weight (skaters ~183.5 cm, sd 5.5) |
| late bloom: some players (22% of two-way forwards, 12% of defensive D, 5% of others) add ~0.7 after 21, peaking ~1 year later | league, nationality, last season's numbers |
| | 80% of Russians are under KHL contract for 1-3 more years |

## How clubs see prospects
A club's projected ceiling = what he is now + the growth an average player has left at his age (goalies mature two
years later) + a league-wide error (everyone watched the same games) + the club's own error (its scouting staff) -
the biases of its director of amateur scouting. Errors are larger outside North America (Swedish/Finnish 1.25x,
other European 1.3x, Russian 1.35x) and for goalies (1.35x).

| Philosophy (share of directors) | size | Europe | Russia (KHL contract) | late-round upside |
|---|---|---|---|---|
| traditional (55%) | full | full | full | none |
| balanced (30%) | 55% | 55% | 60% | a little |
| analytics (15%) | 10% | 15% | 25% | more |

Full biases: 0.07 per cm under/over 183 cm (capped at 0.7; goalies around 188 cm); 0.3 for European juniors;
0.5 + 0.15 per KHL year for Russians under contract. Scouts also discount overage players (19: 0.15, 20: 0.4).
The philosophy belongs to the director: hire a different one (`staffmarket SCOUT_DIR`, `hire`) to change your lens.

## How clubs draft
Round 1: best player available with a 10% nod to need. Rounds 2-4: need weighs more (60/40), from the club's
pipeline of players 23 and under (wants 10 F, 6 D, 3 G). Rounds 5-7: boom or bust, buying the growth the club is
betting on. Goalies are pushed out of round 1 unless rated truly elite.

After the draft: top-3 picks sign at once and are promoted when close to NHL level; first-rounders sign if they are
near AHL level; others sign when ready or before their rights lapse. Players 19 and under go back to junior (and do
not count against the 50-contract limit). A Russian under KHL contract cannot sign until it ends; his rights are held
until a year after.

## Calibration (draft lab, 30 classes)
`python -m hs.tools.draft_lab --classes 30` drafts classes through the engine and plays out every career (an NHL
season at overall 10.25+, a call-up at 9.45+, a star at 11.45+, about the NHL's top 10%).

| Round | 1+ game (real) | 100+ (real) | 500+ (real) |
|---|---|---|---|
| 1 | 81 (89) | 72 (69) | 45 (41) |
| 2 | 57 (67) | 45 (38) | 18 (17) |
| 3 | 43 (52) | 29 (28) | 11 (10) |
| 4 | 34 (41) | 22 (21) | 5 (8) |
| 5 | 20 (33) | 11 (15) | 2 (5) |
| 6 | 24 (29) | 13 (10) | 4 (2) |
| 7 | 19 (25) | 11 (7) | 3 (1) |

- Picks 1-14: 65% reach 500 games (real 50%+); picks 15-32: 30% (real 18-30%).
- Stars per class 6.7 (real 5-8), 75% from round 1, 1.5 per class from rounds 2-7 (real 1-2).
- Goalies: 1.5 in round 1 per class; 26% of drafted goalies reach 100 games (real 21%).
- Median first NHL action: 19 for first-rounders, 20 for second-rounders.
- The human element, measured against each class's true talent order (top-100 talents): small players (5'10" and
  under) go ~90 picks after their talent, big ones (6'3"+) ~26; KHL-contracted Russians slide ~20 picks more than
  average; late bloomers are missed most (~100). Small players drafted hit 100 games 39% of the time, big ones 22%.
- Analytics-minded clubs get about 18% more NHL games per pick than traditional ones.
- One-game rates run a few points under the real ones in every round; the 100- and 500-game rates match.

## Draft floor (hs/game/draft_floor.py)
Pick value chart: 1 = 1000, 32 = 300, a mid 3rd ~100, a 5th ~38, the last pick 12; future picks at mid-round less
15%. Before each AI pick another club may trade up if its top target on its own board clearly beats what it expects
to be left at its next pick, and the club on the clock loses little by moving down. The price is the chart gap
(+25% desperation premium when the buyer's need is acute) plus half the slot's live-board spike (the slot is worth up
to +50% when a player the league rated higher is still there); it pays with its next pick plus later picks (this draft,
then next year's 1st-4th) and never more than 2.5x the gap. At most 4 per round in rounds 1-2, 14 a draft. When the
draft opens, a club holding 10+ picks bundles its best three late picks into one 3rd/4th from a club with few.
Player-for-pick deals on draft day come from hs.game.trades.

You can deal too: `pickswap ABBR give 24,56 get 18` (draft day; priced on the same chart, with the live-board
multiplier on the pick on the clock).

## Commands and screens
`draftboard [n]` (CLI) and the Scouting screen (UI, any time of year) show your scouts' board: projection in words,
height, nationality, last season's line, club and flags (undersized, KHL contract to YYYY, seen less (Europe),
re-entry/overage). On draft day the Offseason screen shows it with Draft buttons.

### The draft room (v27, `#draft`)
In the UI the draft no longer runs itself when you enter the phase. The draft room shows the lottery (who moved up),
a ticker of the picks so far, who is on the clock, your picks left and your board with Draft buttons. **Run the
draft** makes the AI picks one at a time at a watchable pace (**Pause** stops it; or **Next pick** / **Jump to my pick**); it
stops when you are on the clock. Leaving the phase with picks left asks first; your scouts make the picks you leave. CLI: `draftnext [n]` makes the next n
picks and stops at yours. The live mode is a save setting (`pack_info live_draft=1`, set by the UI server); CLI-only saves
draft as before.

### Rankings, the pick clock and draft-day deals (v30)
When the draft opens (`start_draft`), `rankings()` fixes three outside views of the class and keeps them in
`pack_info draft_rankings_<year>`:
* **Central scouting**: the league bureau's rank within its list (North American or international; skaters and goalies
  separately), on potential and current ability with a little noise.
* **Media mock**: one list that leans on production (points per game, capped; goalies a flat allowance).
* **Consensus**: the average of the bureau's combined order, the mock and the clubs' own view, ranked, with a range
  in words ("projected 1st overall", "top 5", "late first", "second round", ...).
The draft board shows them beside your scouts' rank.

**The pick clock** (Settings: 20 s to 10 min, default 90 s) runs while you are on the clock in the draft room; at zero
the top of your board is taken for you.

**Deals** (`pick_deals`): when another club is on the clock, "Trade for this pick" offers the cheapest of your picks
(one, or two together) worth 110% of it on the draft-floor chart; when you are on the clock, up to four clubs picking
in the next 13 offer their pick plus their latest one that covers the chart value of yours. Both go through `pickswap`
(hs/game/draft_floor.py).

**Signing your picks** (`sign_elc`, CLI `elc <p> [khl]`): a pick under a KHL contract signs only through a KHL buyout
offer (the maximum entry-level deal; one ask a month; 30% during the KHL season, 80% from March to August). An NCAA
pick cannot sign during the season until 25 March; signing after that starts his entry-level deal that season.

## In the world (2025-26 world, five seasons, seed 5)
| | after 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| NHL players 21 and under (real ~55) | 63 | 61 | 58 | 55 | 45 |
| NHL skater overall mean | 10.70 | 10.72 | 10.74 | 10.72 | 10.71 |

Stars (12.3+) on NHL rosters stay at ~16; scoring leaders 110-135; 16-17 draft-floor trades per draft, a few
consolidations; first-rounders from the first world-made drafts reach the NHL at 12-18 of 32 within 2-3 seasons.
The NHL bar in the world sits ~0.2 above the real 2025-26 one (generated AHL/European veterans are deep), which is
why clubs also give high-ceiling 22-and-unders a development spot when they are close (docs/WORLD.md).

## Goalies (v46)

Goalie projections are noisier than skaters' and goalies have more growth left at 18, so a club's board, left alone,
put a goalie at the top of nearly every pick after the first round (in the 2027 draft of a test save, 156 of 224
picks). Now an AI club drafts at most one goalie a draft: in round one only a top-tier goalie it needs (two or fewer
young goalies in the system); from round two any goalie it needs; and a club with enough goalies may still take one it
likes from its own round (2-7, or not at all, 30%). A draft now has about 20 goalies, most in rounds 2-7.
