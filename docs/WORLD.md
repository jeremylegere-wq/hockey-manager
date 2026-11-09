# The hockey world (2025-26): leagues, development, careers and the draft

    python -m hs.tools.build_world packs/mp_2025 packs/world_2025     # NHL pack -> full world pack
    python -m hs.ingest packs/world_2025 world.db
    python -m hs.game.cli world.db --env env.json -c "new MTL 7"

## Structure
| League | Kind | Clubs | Level (mean overall) | Notes |
|---|---|---|---|---|
| NHL | top | 32 | 10.55 (real players) | game-by-game engine |
| AHL | farm | 32, each affiliated to its 2025-26 NHL club | 9.2 | NHL-contracted prospects + AHL-contract players |
| ECHL | minor | 30, NHL affiliations | 8.3 | journeymen and depth |
| KHL, SHL, NL, Liiga, Czech Extraliga | europe | 22, 14, 14, 16, 14 | 9.6 / 9.3 / 9.2 / 9.0 / 8.9 | European feeders and landing spots |
| DEL | europe | 14 | 8.7 | |
| NCAA D1 | college | 64 | 8.2 | ages 18-25 |
| OHL, WHL, QMJHL | junior | 20, 23, 18 | 7.6 / 7.6 / 7.5 | ages 16-20 |

Club lists: 2025-26 season pages (Wikipedia). League levels are our estimates (`rules.json` "world"). Everyone
outside the NHL is generated (fictional names), and so are the NHL clubs' existing draft rights.

`players.team_id` is the NHL organisation that holds his contract; `players.club_id` is the club he actually
plays for (NHL club, AHL affiliate, junior/college/European club). `draft_rights` holds unsigned picks.
Status `prospect` = signed by an NHL organisation, playing below the NHL.

## Season loop
NHL games are simulated day by day. Every other league is simulated once a season when the NHL regular season ends:
each player gets a stat line from his overall versus his league's level and his place in the depth chart.

## Ageing and development (hs/worldgen.py)
From the brief: growth up to the draft, NHL-ready for those who will make it around 20-21, peak 24-25, decline from
about 30, steeper from 35 to 40. Each player has a hidden profile (ceiling, peak age ~24.6, decline age ~30,
growth and decline speeds). Physical attributes fade fastest, hockey sense slowest. Goalies peak and decline about
two years later (our assumption). Simulated cohort of 16-year-old juniors: average overall 6.7 at 16, 8.4 at 21,
8.7 at 25-30, 8.1 at 34, 6.9 at 38; about 1% are NHL calibre at 18, 10% at 21, 17% at the peak.
Development is applied each preseason; the previous ratings are kept in `attribute_history`.

## Careers
End of each season: retirement chance rises with age (1% at 30-31 ... 55% at 39, 75% at 40). An established NHLer
(300+ NHL games) with no NHL contract who is below NHL replacement level usually retires (65% from 31). A journeyman
keeps playing: unsigned players are placed each preseason in the best league they qualify for (home leagues
preferred), drifting down through AHL, Europe and ECHL until age or ability ends the career. Juniors leave junior at
21 and collegians at 26 (or turn pro with the organisation that signed them).

## Entry draft (late June)
Eligible: age 18-20 on 15 September, never drafted, never signed. Order: non-playoff clubs worst first with two
lottery draws (odds about the NHL's; max jump 10), then playoff clubs by round reached, champion last. 7 rounds.
Clubs rank prospects through their own scouting noise; you see estimated grades (`draftboard`), not true ratings,
and pick with `pick <player>` when on the clock (`offseason` auto-picks the rest). Rights last 4 years (drafted at
18) or 3 (19+). AI clubs sign entry-level deals when a player is ready (or before his rights lapse if he is close);
you decide for your own (`prospects`, `elc <player>`) until the summer the rights expire.

## Offseason order
finished -> draft (retirements, lottery, draft) -> rights (ELCs, expiring contracts, QOs) -> free_agency ->
arbitration -> awards -> preseason (development, awards signed, AI fill, juniors age out, journeymen placed, clubs
refilled with newcomers) -> next season.

## Not yet
Offer sheets, the user trading draft picks (AI clubs trade them: docs/TRADES.md), CHL/NCAA eligibility rules by era, lower-league standings and playoffs, player
morale/role, staff/scouting quality per club (SCOUT_SD is the hook), European players choosing the NHL beyond
being unsigned.

## Six-season check (MoneyPuck 2025-26 NHL + generated world, seed 5)
| | start | after 1 | after 3 | after 6 |
|---|---|---|---|---|
| active players (all leagues) | 8,029 | 8,094 | 8,261 | 8,222 |
| NHL skater overall, mean (sd) | 10.52 (0.74) | 10.70 (0.60) | 10.72 (0.61) | 10.67 (0.63) |
| NHL average age | 27.8 | 27.5 | 27.9 | 28.0 |
| NHL players 21 and under / 35 and over | 58 / 54 | 49 / 28 | 25 / 27 | 23 / 29 |
| unsigned draft rights | 256 | 298 | 395 | 531 |
The world holds steady: retirements are replaced through the draft, development and newcomers.

**Young players (v12, widened in v13).** Clubs give a spot to a high-ceiling player 22 or younger (potential 10.6+)
when he is within 2.5 value points of the weakest player at his position, instead of requiring him to be 2 points better
(`YOUNG_PROMOTE_*` in hs/game/roster.py). NHL players 21 and under after 1 / 2 / 3 seasons: 50 / 40 / 25 before,
60 / 46 / 33 after. The remaining decline is the generated cohorts: only about 10 twenty-year-olds and 33
twenty-one-year-olds in the whole world reach the NHL's 10th-percentile skater, fewer than real draft classes
produce. The dial for that is the youth potential (GROWTH_LEFT and the late-bloom tail in hs/worldgen.py); it is
the next calibration item.

**Emergency signings.** The world places every unattached player, so the free-agent pool is often empty in season.
When a club cannot dress a lineup and has no one in its system, it signs the best uncontracted player at that
position from its affiliate, else from any lower-league club, on a one-year minimum deal (18 such signings in three
seasons, mostly goalies). Before this, two goalie injuries on one club could stop the season.

A season takes ~45 s, an offseason ~15 s.

## Lower-league scoring (v27)
Each lower league's season is drawn from a points-per-game anchor (LOWER_PPG in hs/game/world.py: AHL .45, ECHL .50,
KHL .38, SHL .37, NL .42, Liiga .40, ELH .40, DEL .40, NCAA .55, OHL / WHL / QMJHL .75) scaled by the player's standing in
his own league: rate = anchor x (0.5 for defencemen) x exp(0.36 z), with z his value's z-score in the league, clipped to
-2.5..3, and x0.6 outside a club's top twelve. Leaders now land near real ones (one world: AHL 87 points, NCAA 61, OHL
134). Saves from before v27 are rescaled once on load (history.repair_lower).
