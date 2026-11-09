# The boardroom (v24)

`hs/game/boardroom.py`, on top of `hs/game/org.py` (owners, season objectives, the summer review). Every number below
is a constant at the top of the module.

## The owner
Each club's owner keeps the existing traits (spending, ambition, patience, risk, youth, development, involvement,
1-10) and gains a **name** (fictional), **vocalness** VOC (0-1, how much he talks to the media; correlated with
involvement), **analytics bias** ANA (0-1), a preferred **identity** (heavy forecheck, puck possession, defensive
structure, speed and transition) and an **archetype**:

| Archetype | Rule |
|---|---|
| The Impatient Tyrant | patience 3 or less, and involvement 6+ or vocalness 0.7+ |
| The Moneyballer | analytics 0.7+ |
| The Penny Pincher | spending 3 or less |
| The Patient Builder | patience 7+ and youth 6+ |
| The Traditionalist | analytics 0.35 or less |
| The Steady Hand | everyone else |

The archetype chooses the voice of the ultimatum memo; vocalness decides what reaches the media.

## Every week (Mondays, regular season, clubs with 5+ games)
- **Drift**: confidence moves with the points pace against the competitive objective (half the old monthly step,
  each week).
- **Trend line velocity** v: the four-week change in confidence /100, clamped to +-0.5.
- **Media pressure** mp: market size (Toronto and Montreal 0.40 ... small markets 0.12) x heat, where heat is
  2 x (1 - points % over the last ten), between 0.3 and 1.6; plus 0.03 a game of a losing streak beyond three; at
  most 0.40.
- **Trigger score** T = confidence/100 + v x P - mp x VOC, where P = 1.1 - patience when v < 0 and patience when
  v >= 0 (patience as 0-1): impatient owners punish a slide hardest.

| T | What happens |
|---|---|
| <= 0.40 | a vocal owner (VOC > 0.8) leaks it: "Hearing from sources close to MTL's owner that he is completely enamoured with a heavy-forecheck engine. A coaching change feels imminent." |
| <= 0.33 | an AI club whose owner is involved (4+) fires its head coach, once a season, after 15 games, if he was not hired this season: +8 confidence |
| <= 0.25 | after 20 games the owner issues an **ultimatum**: 3 games (patience under 0.3) or 5, and the points to take from them: 2 x games x 0.55, rounded up (0.60 for the Impatient Tyrant). AI owners only do this mid-season if their patience is 4 or less; the rest wait for the summer review |

**Ultimatum resolution** (checked daily): met, +6 confidence, the warning lifts, and no new ultimatum for 14 days;
missed: the GM is fired on the spot (an AI club sacrifices its coach instead if it has not already this season).
An ultimatum still open at season end is judged on the games played. A new coach gets 30 days before anyone issues
one. You can fire your own head coach while an ultimatum is open: once a season the board accepts it as a reset
(+8 and three more games).

**When you are fired** mid-season, the job opens (an interim takes over), and so do jobs at other clubs that fired
their GM; `jobs` and `takejob`.

## Directives (your club)
At most one open at a time; each Monday a new one comes with probability 0.1 + involvement/40, from what fits:

| Directive | Issued when | Deadline | Met |
|---|---|---|---|
| Move <player>'s contract | budget owner (spending 4 or less) or over the payroll objective, a veteran 30+ at $4M+ | trade deadline | he is no longer on your club |
| Add a top-six forward | ambition 7+, points % under 0.55 | trade deadline | a forward who would be in your top six arrives by trade, signing or claim |
| Trade nobody 23 or under | youth 7+ (once a season) | end of regular season | fails the day you do |
| Extend <core player> | one of your top four in his final year | end of regular season | he has a contract for next season |
| Play our identity | involvement 6+, your system is not his preferred identity | 14 days | your team system is his identity (docs/TACTICS.md) |

Every week: +0.25 confidence while your club plays the owner's identity; -0.15 while it does not, if his involvement
is 7+.

Met: +3. Missed: -8 x (1.2 - patience/10) x (1 + involvement/20), so an impatient, hands-on owner takes up to 14.4,
and the trigger score is recalculated at once: a missed directive can bring the ultimatum the same day, and it is
the next message in your inbox.

## The media (fictional accounts; hs/game/media.py)
| Vocalness | Leaks |
|---|---|
| over 0.8 | specific, the same day: the owner's preferred identity at T <= 0.40, the coach on thin ice, the ultimatum's window and points |
| 0.3-0.8 | vague, two to four days later, ultimatums only ("There is definite smoke around the NYI front office.") |
| under 0.3 | nothing; the firing is reported as a stunner ("Stunner: NSH fire their general manager") |

Leaks appear as headlines (tag: rumour) and as @InsiderOnIce posts. The game does not imitate real journalists.

## On the 2025-26 world (two seasons, two seeds)
| | Season 1 | Season 2 |
|---|---|---|
| ultimatums (met/failed) | 0-3 / 1-3 | 6-7 / 2-7 |
| GMs fired mid-season | 1-3 | 1-4 |
| head coaches fired mid-season | 3-7 | 10-11 |
The real league fires about five to eight coaches and one or two GMs in a season (from memory). Season 2 runs hotter
because summer reviews leave lower confidence; `AI_ULTIMATUM_PATIENCE`, `COACH_AT` and `WEEKLY_SHARE` are the dials.

## Where you see it
Board screen: the ultimatum (games and points left), confidence with its weekly trend and the trigger score, the
formula with today's numbers, directives, past objectives and reviews, and the owner (name, archetype, vocalness,
analytics and the 1-10 traits). The title bar shows the ultimatum on every screen. CLI: `board`.

## The finance reviews (v54)
Each quarter (1 October, 1 January, 1 April, 1 July) the finance office reports your club's year to date against the
budget, and the owner replies. Cost-minded owners move confidence on it; see docs/FINANCE.md "Financial statements".

## Owner goals (v56, hs/game/owner_goals.py)
On the first day of the regular season (or the first day of a save from before v56), your owner picks up to three
goals from a catalogue. He only picks goals that fit the club's situation and leave a month at least to do them, and
weights them by his traits. Each goal has a priority and a deadline, and shows on the Board screen with its progress
(`goals` in the CLI).

| Goal | When he asks | Deadline |
|---|---|---|
| Acquire one of the league's top 30 skaters (by value) | the club has none; ambition 6+ | trade deadline |
| Acquire one of the league's top 16 goalies | the club has none | trade deadline |
| Move a veteran's contract | 29+, $3M+, outside the club's top six, the worst value for his pay; the owner spends 5 or less | trade deadline |
| Hire a head coach rated 14+ in coaching | the coach is rated 10 or less; involvement 5+ | 75 days |
| Hire a development coach rated 14+ in development | the development coach is rated 9 or less; development 6+ | 75 days |
| Give the best prospect (21 or under, under 20 NHL games) 20 NHL games | youth 5+ | end of the regular season |
| Keep next summer's first-round pick | patience or youth 6+ | end of the regular season (fails at once if traded) |
| Add a first-round pick for next summer's draft | projected in the bottom third; ambition 5 or less | trade deadline |
| Take the season series against the fiercest rival | a rivalry of 30+ points | end of the regular season |
| Win 24 home games | a market of 7+ | end of the regular season |
| Bring the NHL roster's average age under 28 | average 28.5+; youth 7+ | judged at the deadline |
| Keep 12 or more Canadians on the NHL roster | a Canadian club; involvement 6+ | judged at the deadline |

Priority comes from the trait behind the goal: 8+ high, 6-7 medium, otherwise low. Board confidence:

| Priority | Met | Missed |
|---|---|---|
| low | +2 | -2 |
| medium | +4 | -4 |
| high | +6 | -7 |

A goal is met the moment its condition holds, and missed at its deadline. The acquisition goals are checked on Mondays
and on deadline day, because valuing the league's players is costly. You get a message when the goals are set and
when each is resolved. AI clubs' owners do not set goals (their boards work as before).
