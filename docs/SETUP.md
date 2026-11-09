# Game setup and your GM (hs/game/gm.py)

New game is a four-step setup: your GM, the league, the club, the save.

Backgrounds give a small start, not a different game:
  former player   the dressing room gives you the benefit of the doubt: +5 trust in you for every player
  scout           owners who prefer youth (7+) like it: +3 board confidence
  analytics       owners with an analytics bias (0.6+) like it: +3 board confidence
  coach           the room settles faster: +3 cohesion
  business        budget-minded owners (spending 4 or less) like it: +3 board confidence

## Setup (title screen, New game)
1. **Your GM**: name, nationality, age and background (above).
2. **League**: the leagues in the world. Only NHL clubs can be managed for now; the other leagues play on around you.
3. **Club**: every NHL club by division, with its outlook (contender, bubble, rebuild), roster strength and its three best
   players.
4. **Start**: save name and world seed.

## The GM page (`#gm`)
Your profile and your record: every club you have run, season by season (record, finish, how the playoffs ended), playoff
years, championships and trades. Being fired or taking another job adds a new stint (gm_career).

## Your manager (v32, phase A2: hs/game/gm.py)
New game now has five steps: Your GM, **Manager**, League, Club, Start.

**Ratings** (1-20; 66 points to spend, each 4 to 18; templates: Balanced, Dealmaker, Talent hound, Players' GM,
Tactician, Media darling). You earn one point for every season you complete (Manager Profile, or `improve <rating>`).

| Rating | What it does |
|---|---|
| Negotiation | Contract talks settle about 0.5% of the ask lower (or higher) per point from 10 |
| Judging talent | Your scouts' draft estimates tighten about 3% a point from 10 |
| Motivation | Your players' trust in you drifts 0.12 a week per point from 10; as coach, your communication and leadership |
| Media handling | A bad answer at the podium costs 3% less (or more) per point from 10 |
| Coaching | Only as GM and head coach: your coaching rating as the head coach |
| Youth development | Only as GM and head coach: your development rating |

**Reputation** (unknown 25, respected 50, renowned 75 at the start; 1-100). It moves the owner's first view of you
(a point of confidence per 10 from 50), sets which clubs will hire you, and changes at the end of every season (playoff
rounds, a championship, your finish) and when you are fired (-8). The Manager Profile shows the last changes.

**Role.** GM only, or GM and head coach: your previous coach goes to the staff market and you take his place (a staff
row with your ratings; the engine, tactics fit and the room use it like any coach). Switch at any time on the Manager
Profile (`gmrole coach|gm`). You cannot dismiss yourself; handing over the bench leaves it empty until you hire.

**Cannot be fired** (an option). When the owner would fire you, he says so, his confidence resets to 25 and you stay.

**Start unemployed.** No club: three clubs (mostly weaker ones) are looking for a GM. You can also lose your job.
Either way:
* the club you left is run by the AI from then on (an older save that kept a fired GM's club is repaired on load);
* the league plays on (Day, Week, Rest of season, Next offseason phase); the club screens wait for a club;
* the **Job Centre** (Manager menu) lists the openings with the owner, the club's projected finish, the reputation it
  wants (20 for the weakest club to 70 for the best) and your chance; each club interviews you once a month
  (`jobs`, `apply <ABBR>`); openings stay open while you are out of work;
* with a new club you take the role you chose (GM and coach included).

## The assistant GM (v32, hs/game/assistant.py)
Manager > Assistant GM reads your organisation each time you open it: short at a position (recall the best in the
system), an oversized roster, prospects playing better than a regular, lines naming injured or departed players, the
cap, no captain, trade requests and unhappy players, empty staff roles, rights about to lapse, key players in a contract
year, offers and press conferences waiting. Each has a button. It never acts on its own; "Do the routine ones" runs only
the safe items (recalls for a short position, sending down extras, resetting broken lines).

## Find Players (v32)
Manager > Find Players: any player in the world by name, position, age range, league, status (free agent, contract
ending, on the block, unsigned rights, your organisation), nationality, value and cap hit; best 200 first.
