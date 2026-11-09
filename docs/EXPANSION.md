# Expansion (v45)

`hs/game/expansion.py`; the screen is League > Expansion; the console command is `expansion`.

```
Expansion: new NHL clubs and the expansion draft (v45; docs/EXPANSION.md).

How it happens
  * The league expands on its own (League > Expansion, setting "League expansion": occasional by default): from the
    second season of a career, on 1 February each season it may announce a new club (a 25% chance, up to 36 clubs,
    one at a time) in one of the candidate markets, to join the next season.
  * Or you create one (League > Expansion > Create a club, or `expansion create`): city, nickname, abbreviation,
    colours, conference and division, before the trade deadline. You can choose to become its GM.
  * The new club comes into being when the season ends (its arena, owner, board, staff and an AHL affiliate), the
    clubs submit their protection lists, and the expansion draft is held the day the entry draft phase opens. If you
    are its GM you take it over when the season ends (your old club passes to a new GM) and make its picks.

The rules (the NHL's for Vegas, 2017, and Seattle, 2021)
  protect   7 forwards, 3 defencemen and 1 goalie, or any 8 skaters and 1 goalie
  exempt    first- and second-year pros (two or fewer North American pro seasons of 10+ games) and unsigned draft picks: they cannot be taken
  must      players with a no-movement clause must be protected (they count against the limits)
  expose    at least 2 forwards and 1 defenceman under contract next season who played 40+ games this season or 70+
            over the last two, and 1 goalie under contract next season (or a pending RFA)
  eligible  players under contract next season, or pending RFAs (their rights move)
  the draft exactly one player from each club; the new club must end with 14+ forwards, 9+ defencemen, 3+ goalies,
            20+ under contract, and a payroll between 60% and 100% of the cap
  side deals a club that would lose a valuable player may give the new club a pick to take someone else (AI clubs; up
            to six a draft: a 1st when the gap in trade value is 80+ (three at most), a 2nd when it is 25+)
  the entry draft: the new club gets the lottery odds of the third-worst club
```

## The season, step by step

| When | What happens |
| --- | --- |
| Regular season, up to the trade deadline | A club is announced: by the league (from the first sim day on or after 1 February, a 25% chance a season from the second season on, while the setting is "occasional") or by you (League > Expansion > Create a club). |
| The season ends | The club is created: a team in the conference's smallest division, its arena and market, an owner and board, finances, staff, and a new AHL affiliate. If you chose to run it, you become its GM and your old club gets a new GM. Every club's protection list is drawn up; yours is your assistant's until you change it. |
| The entry draft phase opens | The expansion draft runs first (before draft-day trades): one player from every club, side deals, then the club's leadership group is chosen. |
| The entry draft | The new club picks with the third-worst club's lottery odds. |
| The next season | The schedule is built for the uneven divisions: every club still plays the full schedule (games against the extra club are taken from other-conference meetings first). |

## Your protection list

The screen lists your players with their games played, trade value and tags: *exempt* (two or fewer pro seasons:
cannot be taken), *NMC* (must be protected), *not eligible* (no contract next season and not a pending RFA) and
*meets exposure* (counts towards the exposure rules). Tick players to protect, choose the scheme, and submit; the
problems with the list are shown above it. "Assistant's list" restores the list your assistant would submit.

## Running the expansion club

The draft room lists every club with your staff's choice and a menu of its exposed players. Choose a player to fix the
pick, or leave it to your staff: their choices are made after yours and keep the roster legal (14 forwards, 9
defencemen, 3 goalies, 20 under contract, a payroll between 60% and 100% of the cap). The screen warns when your own
picks would leave the roster short. No side deals are made when you run the club.

## Console

```
expansion                                     the status, your list or your draft board
expansion create Houston | Wildcatters | HOU | Western | gm
expansion mode occasional|off
expansion protect auto | expansion protect 7-3-1 <id>, <id>, ...
expansion pick SEA <player> | expansion unpick SEA
```
