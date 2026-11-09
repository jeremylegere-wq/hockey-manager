# Scouting and development (phase E, v36)

## Your scouting network (hs/game/scout_net.py)
**Knowledge levels.** Your club knows each draft-eligible prospect to a level from 0-100 points: A 80+, B 60+, C 40+,
D 20+, E under 20. Everyone starts at 45 (C), which is what the AI clubs see (they keep the v13 scouting model).
Your own error on a prospect's ceiling is your staff's error x A 0.5, B 0.75, C 1.0, D 1.25, E 1.5 (the Lens in
hs/game/scouting.py), so better-known prospects are projected more accurately. The league-wide shared error and your
director's biases stay.

**Each week** (Mondays) every amateur scout adds (evaluation / 20) x 8 points to the prospects of his region
(unassigned: spread over all five), double for a prospect on your watch list; the director of amateur scouting adds a
third of a scout's pace everywhere; and every prospect loses 6% of his points (knowledge fades unless kept up). Points
settle at 16.7 x the weekly gain: the default spread (two average scouts over all regions, an average director)
settles near 50 (C); two scouts on one region take it to A there and leave the rest at D.

Regions: the CHL (OHL, WHL, QMJHL), US college and junior, Sweden and Finland, the rest of Europe, Russia.

**Tournaments.** Send any scout (or the director) to the next World Junior Championship (26 December, ages 18-19, the
league's top 80), CHL/NHL Top Prospects Game (late January, CHL), NCAA Frozen Four (April, US college), U18 World
Championship (late April, ages 17-18), Memorial Cup (late May, CHL), the scouting combine (early June, the top 100) or
the Hlinka Gretzky Cup (August, age 17). When it ends, everyone he saw gains 12 points (x 0.6 + evaluation / 25), and he
writes to you.

**The watch list.** Prospects you watch are learned twice as fast.

## Central scouting's lists
Three lists a season, published on 15 October (preliminary), 15 January (midterm) and 15 April (final), each closer to
the truth (an error of 1.0, 0.7 and 0.45 of a rating point around the league's consensus). Ranked within North American
skaters and goalies and international skaters and goalies (60 skaters and 15 goalies each), with grades A (first
round), B (second or third), C (fourth to sixth); a news story names the top North American skater. (The draft board's
outside rankings, docs/DRAFT.md, are fixed when the draft opens.)

## Mock draft and suggestions
The first round as it stands (the draft order if set, otherwise the standings from the bottom), each club taking the
player its own scouts rate best for the pick. For your first pick, your scouts suggest the best available (likely
there at your slot), a safe pick (closest to the NHL already, well known to your scouts) and a risky one (the most
growth left).

## The board
Ranked the way your club would pick in the first round (projection, overage discounts, goalies only near the top when
top tier), with each prospect's knowledge level, his region and a Watch button.

## Exceptional juniors
From September each year, a 16- or 17-year-old with a ceiling of 13.6 or more is granted exceptional status: a news
story, every club's knowledge of him set to A, and a tag on the board until his draft.

## Training (hs/game/training.py)
Every player in your organisation can have a focus: balanced, offence, defence, skating, physical, mental (goalies:
positioning, reflexes, mental). Development each summer still moves his overall by the same amount (age, potential,
coaches, coachability); a focus decides where: focus attributes take 1.6x their share of a gain (0.6x of a loss in
decline) and the rest give it back. Set it on the Development screen, the player's Ratings tab, or `train <player>
<focus>`.

## Variable potential
Each summer every player 24 or younger has his ceiling moved by a little (sd 0.2); one prospect in 25 is a wild card
(sd 0.7). The average does not move. A big move in your organisation (a point or more) gets a note from your
development staff; the Ratings tab marks wild cards.

## The development chart
The player's Ratings tab charts his attribute groups (offence, defence, skating and physical, mental; goaltending for
goalies) season by season from the ratings history, to now.

## CLI
`scout` (the network), `scout assign <staff id> <region|all>`, `scout trip <staff id> <event>`, `scout watch|unwatch
<player>`, `train <player> <focus>`.

## The engine and the league
Nothing here changes a game. The AI clubs' scouting is the v13 model (level C for everyone), training focus moves the
shape of development not its size, and potential drift has a zero mean, so league-wide talent and the v33 calibration
are unchanged. Not done: scout-bias randomising and stat-adjusted talent at setup (G).
