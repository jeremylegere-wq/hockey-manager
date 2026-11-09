# College hockey (v46)

`hs/game/college.py`; League > College Hockey (tabs: Programs, Recruiting, Our prospects, Free agents; click a
program for its roster and commitments); console `college`, `college prospects`, `college path <player> college|junior|none`,
`college fa`, `college offer <player> [now]`, `college withdraw <player>`, `college program <name>`.

```
College hockey: programs, eligibility, recruiting, enrolment and graduation, the Hobey Baker Award and the college
free-agent market (v46; docs/COLLEGE.md).

Eligibility (NCAA Division I)
  amateurs only     no season in the NHL, AHL or ECHL and no pro contract; CHL players are eligible (since 2025-26)
  old rules         players who enrolled before 2027-28: four seasons, one fewer for each year he enrols past 21
  5-in-5            from the 2027-28 entering class (adopted June 2026): five seasons within five years; the clock
                    starts at enrolment or with the academic year after he turns 19, whichever comes first, so a player
                    who spends two years in junior after 19 enrols with three seasons left
Programs: every NCAA club has a prestige (1-100) from its talent and results (a title, the Frozen Four, the tournament),
a head coach, and a recruiting class that fills the places its seniors and early leavers open up.

Recruiting (rounds on 15 October and 1 March; a last round in the summer)
  who               players 16-20 in junior (USHL, NAHL, BCHL, the CHL, the European junior leagues) who are eligible
                    and college-bound: most USHL, NAHL and BCHL players (85%), Americans in the CHL (30%), Canadians in
                    the CHL (12%), Europeans (5%); a drafted player's NHL club can steer him (path college / junior)
  when              a commit enrols next season if he is ready (his overall within half a point of the NCAA average)
                    or will be 20, otherwise the season after
  where             the program he likes best among those that want him (his quality reaches the program's bar, it has
                    a place at his position): prestige/10 + playing time (places open at his position) + a little luck
  rate              each round 70% of next season's recruits and 35% of the year after's commit, and a program fills
                    at most 55% of its open places (a quarter for the year after); the summer round places everyone
                    left who wants to go
Summer (the start of the off-season): seniors graduate (their eligibility is used up), commits enrol (moving to their
program), and an NHL club's rights to a drafted college player run until the summer after his last college season.

The college free-agent market (when the NCAA season ends): the best undrafted players leaving college (eligibility
used up, or a strong player who turns pro early, 60%; within 0.8 of the AHL average, at most 40) can sign an entry-level deal with any club. AI clubs that need him make
offers over the next days; you can too (College Hockey > Free agents, `college offer <player> [now]`). "Now" starts the
deal this season (he can play at once; a year of it is used up), which players like. Ten days after the market opens
each player picks: playing time at his position + "now" + the club's strength + a little luck. Anyone unsigned goes
back to school (with eligibility left) or into the summer's free agency.

The Hobey Baker Award goes to the best college player when the NCAA season ends.
```

## The NCAA's rules, as of 2026

* CHL players became eligible for NCAA Division I from the 2025-26 season.
* On 23 June 2026 the Division I Cabinet adopted "5-in-5": five seasons of competition within five years, the clock
  starting at full-time enrolment or the academic year after the athlete turns 19, whichever comes first. Schools may
  apply either set of rules to athletes already in school; incoming classes from 2027-28 are under the new rules only.
  The game applies the old rules (four seasons, delayed enrolment after 21 costing a season a year) to anyone who
  enrolled before 2027-28 and 5-in-5 from then.

## Your prospects

* A drafted prospect in junior decides for himself whether to go to college (most USHL, NAHL and BCHL players do, a
  minority of CHL players, few Europeans). Set his path to *college* or *junior* to steer him; *junior* withdraws a
  commitment he has made.
* While he is in college we hold his rights until the summer after his last college season (they are extended when he
  enrols). In his last season a senior who is blocked at his position may refuse to sign and become a free agent
  (docs/CONTRACTS.md, "College picks who refuse to sign"): sign him, or move his rights, before then.
* A college pick can be signed once his college season is over (late March); a deal signed then starts this season.

## Notes

* Programs, prestige and class years are set up the first time college hockey is used in a save; the class of a player
  already in college is a guess from his age (19-20 a freshman, 21 a sophomore, 22 a junior, 23+ a senior).
* A player who leaves college (signs pro or graduates) is never placed back in a college club by the world.
* Transfers between programs, scholarships and walk-ons are not modelled.
