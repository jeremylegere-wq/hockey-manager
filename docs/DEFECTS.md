# Defects and enhancements register

Logged from Jeremy's playtest notes on v28 (defects_register.odt, 1 Nov 2026). The numbering is his; where his
document numbered two items the same, they are 3a/3b and 16a/16b. **Fixed** = in v29, **Fixed v30** = in v30. **Planned** =
the release it is scheduled for, with the approach. v30 closed every item that was planned for it.

| # | Area | What was reported | Status | What changed / the plan |
|---|---|---|---|---|
| 1 | Sim centre | The score line (MTL 3 FINAL 0 DET) runs into the game headline | Fixed | The scoreboard sizes to its content; the headline sits below it |
| 2 | Contract talks | After a deal: no natural close to the conversation, no clear way out; reopening a signed player shows a bare "No talks" | Fixed | The agent sums up the deal (term, AAV, total, no-trade), the player reacts; a green "signed" note, Close and "His contract" buttons; reopening shows the finished conversation; the window's close cross is visible on every window |
| 3a | Trades | Three-team trades: AI-to-AI? The headline reads like a two-club trade | Fixed, Fixed v30 (AI) | Headlines name all three clubs. AI clubs now make three-team trades among themselves: rarely (about 4% of trades), facilitator-style, a third club with cap room takes a $1.5-5M contract for a 4th-round-or-later pick |
| 3b | Navigation | The back button seems lost | Fixed | Back and Forward buttons on the club header, besides the small ones in the menu bar; Alt+Left / Alt+Right still work |
| 4 | News | Clicking a trade headline opens the player, not the article | Fixed | Every headline opens its article: the story, each club's side of a trade, the players with last season's line and contract, the reaction, related stories |
| 5 | Contracts | Buyout rules: 2/3 (26+) or 1/3 (under 26) of what is left, over twice the years; signing bonuses excluded; window 15-30 June (or 48 h after the final) plus 48 h after arbitration; unconditional waivers; no buyout of an injured player or a contract not yet started | Fixed (rules and window), Planned v31 (bonuses) | Your buyouts follow the window (15-30 June; the arbitration-awards window) and refuse injured players and contracts that have not started; the message says he cleared unconditional waivers. The cost was already 1/3 or 2/3 over twice the term. Signing bonuses need salary-by-year contracts: with the finance work in v31 |
| 6 | Trades | Rejected offers sometimes leak as rumours; that should touch team and player morale, more so when repeated | Fixed v30 | When an offer is turned down, each of your players in it may leak as a rumour (25% the first time, +15% each repeat): a rumour story, a trust and morale hit by personality (ego, loyalty), larger each time; a proud player shopped three times asks out; three or more shopped in 30 days costs room cohesion and the coach writes to you (hs/game/rumours.py) |
| 7 | Press | Post-game rivalry question asks "sting / feel sweeter" at once | Fixed | Separate questions after a rivalry win and a rivalry loss, with answers that fit each |
| 8 | Sim centre | The bottom ticker starts empty and should show more at once; there should be a Continue button | Fixed | Tickers start full and scroll slower; when the sim stops: "Continue one day" and "Continue to next game" in the sim centre |
| 9 | Prospects | The "Now" column makes no sense | Fixed | Ability and Potential as star ratings (with the value beside ability); Development says "Value last summer" / "Value today" |
| 10 | Captaincy | A goalie can be made captain | Fixed | Goalies cannot wear the C or the A (picker, room ranking, AI choice); older saves are repaired on load |
| 11 | Free agency | Signing a KHL player is impossible; it should be possible but hard (he buys out his KHL deal, so his demands must be met; many wait until the KHL season ends). NCAA players sign when their season ends and burn an ELC year | Fixed v30 | KHL: the Prospects screen has a "KHL buyout offer" (the maximum entry-level deal); one ask a month, 30% in the KHL season, 80% from March. NCAA picks cannot sign during the season until 25 March; signing then starts the ELC that season |
| 12 | Press | Fan / media sentiment and controversy need news outcomes that follow logically, and must reach the game engine | Fixed v30 (attendance v34) | Checked every Monday: a hostile column, fans turning, the building rocking, a controversy cycle, good press, each a story with board, morale, cohesion and sentiment effects (3-week cooldown). In the engine: controversy above 60 costs up to 4% of shot attempts; a crowd above 75 adds 1.5% at home, below 30 costs 1.5% |
| 13 | Game view | The 2D replay moves everyone as a group; rebuild it with Jeremy's 2D engine | Fixed v30 | The 2D game (hs/sim/rink2d.py, docs/RINK2D.md): every skater, both goalies and the puck, steered so the engine's events happen at their time and place. See "The 2D engine" below |
| 14 | Sim | "Rest of season" never stops for a trade offer or the deadline | Fixed | Rest of season now stops for a trade offer, the owner's office, three days before the deadline and on deadline day (with an alert in the sim centre) |
| 15 | Sim centre | Ticker items need an abbreviated date | Fixed | Every news and score item starts with its date (e.g. "12 Oct") |
| 16a | Trades | Too many quality players are traded between AI clubs | Fixed v30 | Players valued in the league's top 15% move between AI clubs only from a seller, at most 4 a season, and with a 20% chance per opportunity (45% in the deadline rush) |
| 16b | Playoffs | The Stanley Cup champion screen is bland; awards night should be its own event; the Vezina (and GM of the year) is voted by the GMs | Fixed | A Champions screen (crest, the path through the four rounds, the final game by game, the Conn Smythe, playoff scoring) and a separate Awards Night screen, each award with who decides it; the Vezina is the GMs' vote; a GM of the Year award added (GMs and a media panel). League menu: Champions, Awards Night |
| 18 | Offseason | An alert when pressing Next offseason phase; break the results out into their own events | Fixed, Fixed v30 (events) | Each step asks first, saying what comes next and when; the results open as a phase report in sections (your club, trades, draft, signings, staff, retirements) instead of a long toast. Lottery night and retirements are now their own stories, each with a full message |
| 19 | Navigation | Badges on the tabs when something needs attention | Fixed | Red count badges: Inbox (unread mail plus press conferences waiting), Trade (offers waiting), Office (meeting requests and owner's messages) |
| 20 | Inbox | Messages need full text | Fixed, Fixed v30 (the rest) | The season summary is a real letter (record, finishes, goals, leading scorers, change on last season, what comes next). Board reviews (owner, reasons, verdict, risk), lottery night, retirements and the season-over letter are now written out in full |
| 21 | Inbox | The awards message needs formatting | Fixed | One line per trophy: winner, club, the case, who decided it; messages render lists and paragraphs |
| 22 | Draft | A timer for each pick; trade for a pick that is on the clock; trade your own pick; ask for trade-down offers | Fixed v30 | A pick clock in the draft room (Settings: 20 s to 10 min; at zero your top-of-board player is taken), "Trade for this pick" offers on the club on the clock, and trade-down offers when you are on it (draft-floor chart and pick swap) |
| 23 | Draft | Central scouting, media and scout rankings, or at least where each player is expected to go (consensus first overall, etc.) | Fixed v30 | Board columns: your scouts, central scouting (rank within North American / international, skaters and goalies), a media mock, the consensus, and a range ("projected 1st overall", "late first"); fixed when the draft opens |

Also fixed while working through these: the browser's own confirm and prompt boxes (the "JavaScript - http://127.0.0.1..."
dialog in the screenshots) are replaced by the game's own dialog everywhere.

## The 2D engine (item 13)

Jeremy's pygame project (2D_ice_hockey_sim.zip, about 1,700 lines) is a real-time simulation: skating physics with
acceleration, fatigue and sprinting; puck physics with friction and boards; possession by stick reach; passing lanes
scored by a short look-ahead (beam search); offensive and defensive coordinators that place each position (point
pinches, a PK box, pressure ranges by tactic); body and poke checks; faceoffs; offside, icing, penalties, line changes
from a bench; goalie positioning on the puck; match statistics. It is the right shape for our replay: our replay
draws dots from the game's event list and moves the skaters as a block between events, which is the "everyone moves
together" in the report.

The plan:

**Done in v30** (docs/RINK2D.md). The engine was rebuilt rather than ported line by line: the same ideas (steering
with acceleration, coordinators that place each position, a look-ahead for passes, puck physics, goalie arcs) in a
headless module, driven by the real game's events. The viewer already does most of step 3; the shot chart overlay
and pass lines are left for v31. The original plan:

1. **v30: port the engine as a headless module** (`hs/sim/rink2d/`), no pygame, no numpy (plain floats; the
   coordinators and physics are small). Player attributes come from our 1-20 ratings (speed, agility, passing,
   shooting, checking, positioning; goalie positioning and reflexes).
2. **v30: drive it with the real game.** The match engine already decides the result and its events (shots, goals,
   saves, penalties, line changes) with times. The 2D engine plays the game out in between, steered so each recorded
   event happens at its time and place: a shot from the recorded spot by the recorded shooter, a goal that goes in,
   the right team on the power play. Tracking frames (10 a second) are saved per game for your games and generated on
   request for the rest.
3. **v31: the replay viewer** draws the tracking (positions, the puck, the carrier, passes and shots as lines,
   numbers on the players), with play, speed, jump to the next goal or shot, and the shot chart, in the classic look.

Bugs in the 2D project to fix on the way (none of them reach the game today):
* `ShootingPhysics.execute_shot` is called with the stats object where it expects the game state, so the AI's
  `state.stats.record_shot_attempt` fails the first time an AI player shoots.
* The attention row reads index 12 as the puck; with a player in the box there are 11 entities before the puck, so
  the index is wrong (and out of range on a 5-on-3).
* Line changes swap by list position (`bench[i]`), which goes wrong once a penalty has removed a player from the
  active list; the penalised player keeps his AI controller and can still be chosen.
* Offside fires whenever any attacker is past the blue line as the puck enters, with no tag-up and no check of who
  carried it in; icing ignores who touched it last on the way and has no hybrid race.
* Goals are counted on any puck past the goal line within the net width, regardless of the goalie or the net's
  depth; shots always aim at the centre of the net (a random spread of half a net width).
* The faceoff always uses the first player in each list as the centres, and the human-controlled draw decides every
  faceoff on the home side.


## Second register (Defects_and_Enhancement_Register.odt, 7 Nov 2026), worked in v38

Numbering is Jeremy's (00000-036, then the unnumbered requests at the end). **Fixed v38** = in v38. **Planned** = not
yet, with the reason.

| # | Area | What was reported | Status | What changed / the plan |
|---|---|---|---|---|
| 1 | Inbox | A real welcome on day one: welcome to the team, expectations, team overview | Fixed v38 | The owner writes (who he is, the season's objectives, required or preferred, his patience, what comes next) and the assistant GM sends a club briefing: projected finish, forwards/defence/goal against the league, the core, the goalies, the captain, the cap, who is out of contract, the best prospects, the coach. Each with buttons to the screens (hs/game/welcome.py) |
| 2 | Press | A board briefing, then an introductory press conference; deviating from the board shows on job security | Fixed v38 | The introductory press conference (Press room, major): what you expect this season, the star or the expiring contract, the best prospect, the coach. Your promise is weighed against what the owner expects: in line +4 confidence, one step off -1, further -6, written to Job Security as "introduction" with the gap. The briefing is the owner's letter and the club briefing above |
| 0 | Depth chart | Order: goalie, defence, left wing, centre, right wing | Fixed v38 | |
| 3 | 2D engine | Players crawl then speed up; tracers for passes and shots | Fixed v38 | Goalies were skating the length of the ice at each period (ends switch) at goalie speed: they now start in their crease. Skaters slow down later when arriving. The viewer draws through the frames with a spline and never jumps after a slow frame. Passes leave a blue streak, shots a red one, and the puck glows |
| 4 | 2D engine | Names overlap at the draw | Fixed v38 | Home names above the players, road names below, nudged apart when they would still collide |
| 5 | 2D engine | A play-by-play beside the recap and the score by period | Fixed v38 | A Play by play panel under the score by period follows the replay (goals, saves, blocks, misses, penalties); click one to jump to it |
| 6 | Inbox | Messages that need action should link to it, and come from the right person | Fixed v38 | Messages carry a sender (the head coach, the physio, the owner, the director of scouting, another club's GM...) and action buttons: the dressing-room scuffle comes from your head coach with "Talk to <player>" buttons |
| 7 | Depth chart | Draft picks are jumbled; align them by year | Fixed v38 | A pick grid: draft by draft, round by round, own / traded away (to whom) / acquired (from whom) |
| 8 | Help | Credits and About go to the same place | Fixed v38 | About shows the version, the window, the career, the saves folder, the worlds and the keys; Credits stays the credits |
| 9 | Lines | "no defensive conscience" is cut off | Fixed v38 | The notes wrap |
| 10, 21 | Contracts | Toggles for cap commitments and salary year over year; the visuals did not populate | Fixed v38 (cap), Planned (cash) | "Contracts year by year": every contract's cap hit by season (with room under the cap), and a commitments chart by forwards, defence and goalies with retained and buyouts and the cap line. Salary by season equals the cap hit until contracts carry year-by-year salaries and bonuses (the dual-ledger finance work) |
| 11 | Trades | Picks jumbled; protected picks, conditional picks, pick swaps, tested by the AI | Partly v38 (the grid), Planned (protections, conditions, swaps) | The pick grid is on the depth chart. Protected and conditional picks and swap rights change what a pick is in the trade engine, the AI's valuation and the draft order: their own piece of work, with tests |
| 12 | Transactions | Filter by club; league views | Fixed v38 | A club picker on the upcoming free agents, the trade block, waivers, offer sheets and the injury report (the league or one club) |
| 13 | Prospects | Other clubs' prospects; a league view with central scouting | Fixed v38 | Show: your club, any club, or the league's best prospects (ability, and the potential your scouts can see: A and B knowledge shows it, C rounds it, D and E do not know); links to Central Scouting and the Mock Draft |
| 18 | Leadership | The leadership group's title only works from team screens | Needs detail | The player screen already shows "Captain" / "Alternate captain" under the name, and its "Leadership group..." button opens the dialog with him proposed as captain (checked in v38). If the problem is elsewhere (which screen, what happens), a screenshot would pin it down |
| 19 | Captaincy | "The Nth captain of the club", the longest-serving | Fixed v38 | The captaincy story numbers the captain (in this save; a pack's `captains_before` per club carries the real count) and names the longest-serving captain on record |
| 20 | League history | All-time leaders must include history the save does not have | Planned | An editable all-time leaders table in packs (the Import/Export utility), with an active/all-time toggle |
| 22 | Past drafts | Blank | Planned | Your database export does not carry draft year, round and pick yet; when it does, the importer fills the draft log from it |
| 23 | Statistics | Advanced stats only from the menu | Fixed v38 | The statistics tabs carry the advanced views: league, by club, players and goalies, playoff odds |
| 24 | Sim centre | Cycle league leaders in the side panel; say why it stopped | Fixed v38 | The side panel turns every six seconds: standings, points, goals, save %. When it stops: "Stopped: <why>" and a button straight there (inbox, press room, trade screen) |
| 25 | 2D engine | Remnants of the old engine before the new one starts | Fixed v38 | A loading panel holds the space; only the newest 2D game draws |
| 26 | Sim | A notification that interrupts a long sim; customisable | Fixed v38 | Settings > Gameplay: what stops Rest of season and Play until (trade offers, the owner, major press conferences, the deadline, injuries, trouble in the room) |
| 34 | Inbox | "accept 2 or decline 2" should be buttons | Fixed v38 | Offers carry Accept / Decline / Open the trade screen buttons; any `command` in a message is a button |
| 35 | Inbox | An Outlook-style inbox | Fixed v38 | Ribbon (mark read/unread, flag, archive, mark all read, search), favourites and folders with counts, messages grouped by day with flags, a reading pane with From / To / date and the actions |
| 36 | News | "Blue Line" is the name of the community research team | Fixed v38 | The recap outlet is The Morning Skate; the agency is Bluewater Sports Management |
| - | Database | A more detailed player database | Fixed v38 | Import your own export (File > Import Database, docs/DB_IMPORT.md): the ratings become the game's own player model |
| 14-17, 27-33 | Staff, logos, budgets, leagues | Staff bios; editable logos and photos; budgets and the P&L; multiple playable leagues; a women's league | Planned | Later phases (ROADMAP) |
| - | Editor | Commissioner-mode editor; bulk Import/Export with templates, mapping, preview, validation | Planned | Next to build on the import: the ratings layer is the editable model it needs |
| - | Finance | Dual ledger (cap and cash), signing bonuses, revenue sharing, market tiers | Planned | With year-by-year contracts |

## Third register (defect_register_v038.odt, 7 Nov 2026), worked in v39

Jeremy's numbering. Most screenshots were taken on the old generated 2025-26 world (salaries, ages), which v38 still
used by default.

| # | Area | What was reported | Status | What changed |
|---|---|---|---|---|
| 1 | 2D engine | Players sit, then speed up; goal lines run off the ice | Fixed v39 | The attacking side's zone formation cycles smoothly instead of standing on spots with a fresh random nudge each step; the shooter heads for his spot six seconds out and sprints only for the last 1.6 (the "burst"). The rink markings are clipped to the boards, so the goal lines stop in the corners |
| 2 | Inbox | The tab showed 3 with 2 unread; the achievement mail is thin | Fixed v39 | The Inbox badge counts unread mail only (press conferences wait in the Press room button) and ignores archived mail. Achievements are a note from the league office: what you did and when (the game), your record, how many of the list you have, what is still to come, a button to the list |
| 3 | Contracts | Salaries not what the database says | Fixed v39 | Those screens were the old world. The default world is now built from your export (real cap hits, e.g. Suzuki $7.875M, Hutson $8.85M from 2026-27) |
| 4 | Lines | Forwards should read left wing, centre, right wing | Fixed v39 | The Lines screen shows LW, C, RW (the line is stored the same way) |
| 5 | Trades | Picks a jumbled mess; how do I protect them? | Fixed v39 | Picks are a grid: draft year by round, with the original club and value; your 1sts have a protection menu (top 3, 5, 10) and the value updates. Players carry their clause (NTC, NMC, M-NTC n) and a "hard to get" score; the club's need scores show above their verdict |
| 6 | Assistant GM | "He may need waivers" leaves you guessing | Fixed v39 | The suggestion and its confirmation say whether he needs waivers and why ("not waiver-exempt (past 3 seasons): he goes on waivers for a day and any club can claim him") or that he is exempt; a player with an NMC is not suggested |
| 7 | Contract talks | The agent dropped a lot in one call; hometown, friends, winning, clause terms | Fixed v39 | An agent concedes at most 2.5% / 3.5% / 5% of his demand a round. Trade protection is a choice: none, a 10-team list in the last two years, a 10-team list, a full NTC, an NMC; he asks for the level his age, value and ego earn, each level granted takes 2.5% off, each short costs 2%. Pitches (once each): home, friends in the room (players he has played with, countrymen), a chance to win; true and relevant takes 1-3% off, false costs patience or mood |
| 8 | Ticker | A waiver claim showed as "player signed" | Fixed v39 | Labelled WAIVER CLAIM |
| 9 | Sim centre | Buttons not sitting properly | Fixed v39 | The header keeps one line; buttons do not wrap |
| 10 | Inbox | "Wants a word" should link to the conversation | Fixed v39 | "Talk to <player>" opens his page at the conversation; from the head coach; and it no longer arrives about a player who has since been traded or claimed |
| 11 | Inbox | "Cleared waivers" should link to the player | Fixed v39 | Cleared, lost and claimed on waivers carry a button to the player |
| 12 | Console | "help" said Done | Fixed v39 | help lists every command with a line each (help <command> for one); long output opens a console window |
| 13 | Search | Manager > Search did nothing | Fixed v39 | It opens a search window (players, clubs, staff); Ctrl+F still jumps to the box in the menu bar |
| 14 | Menus | Credits under File and Help | Fixed v39 | Help only |
| 15 | Credits | Flag the AI use responsibly | Fixed v39 | Your text: design, architecture, lead developer, QA and review; AI collaboration (Claude, Gemini, ChatGPT and what each did), with a line that the tools work under your direction, generated code is reviewed and tested, and no personal or confidential data goes to them. The data line says this personal build ships a world built from a community database export, removed before any public release |
| 16 | Language | The whole game in Quebec French | Part v39 | File > Français (Québec): menus, tabs, buttons, headings and common labels in Quebec French (alignement, trios, repêchage, ballottage, joueurs autonomes...). Text the game writes (news, messages, press questions, recaps) is still English: translating it means templating every generated sentence, a phase of its own |
| 17 | Roster | Auto-sign the best player who will take the minimum when you are short and cannot play | Fixed v39 | If your club cannot dress a lineup and has nobody to recall, it signs the best free agent asking no more than the league minimum, one year, and tells you (Emergency signing, with buttons) |
| 18 | Free agency | Sign a player to a PTO for camp and pre-season | Fixed v39 | Professional tryouts (docs/PTO.md): up to three unsigned free agents at camp from the arbitration phase, no contract, other clubs cannot sign them; on opening day the head coach reports where each would fit, with Sign / Negotiate / Let him go; unsigned after opening week they are free agents again |
| 19 | Awards | "d.awards.filter" error before any awards night | Fixed v39 | The screen says the first awards night comes after the playoffs |
| 20 | Ticker | Duplicate trades (Zuccarello) | Fixed v39 | The ticker shows one line per trade (the per-player "traded" lines are left out) |
| 21 | Inbox | A meeting request shows "talk 1483457" and does not go anywhere | Fixed v39 | A "Talk to <player>" button to his page's conversation; no id in the text |
| 22 | News | "Fans running out of patience" during an 8-game streak at the top of the division | Fixed v39 | Fan and media mood drift each week toward the last ten games' results; the negative stories need a poor run (under .550) and the "building is rocking" story a good one. Headlines use the club's name, not its abbreviation |
| 23 | Morale | A player asks about his extension after signing it | Fixed v39 | Signing resolves his open contract question, and the question is never raised once an extension is signed |
| 24 | Press | "Beating TOR" | Fixed v39 | "Beating the Maple Leafs": post-game questions use the nickname |
| 25 | Staff | Several head coaches fired the same day | Fixed v39 | AI clubs' in-season firings are at least six days apart across the league |
| 26 | Sim centre | Standings lack headings; wild-card rows misaligned | Fixed v39 | A heading row (GP, PTS, STRK) and fixed columns, so every section lines up |
| 27 | Assistant GM | Hutson listed as in his last year after his extension | Fixed v39 | Players with a signed extension are left out |
| 28 | Analytics | The glossary is messy | Fixed v39 | A definition list in a proper window |
| - | Trades | Too many NHL-calibre players traded | Fixed v39 | The friction market (docs/TRADES.md "How the market decides (v39)") |
| - | World | The default should be the imported database | Fixed v39 | The default world is now the generated fictional one (v58) |

## Fourth register (defect_register_v039.odt, 8 Nov 2026), worked in v42

| # | Area | Item | Status | What changed |
|---|---|---|---|---|
| 1 | Names | No mention of the source game in the code or on screen | Fixed v42 | The export reader is `hs/adapters/db_export.py`, the desktop theme `classic.js` / `classic.css`, the world `save/world_2026.db`, the import guide docs/DB_IMPORT.md; the credits and the import dialog name no game. The old converters were removed from the public release. A test fails if the name comes back |
| 2 | Inbox | "The screens linked below" when the buttons are above | Fixed v42 | "linked above" |
| 3 | Trades | A "shop this player" button: teams told, offers spread out, low unless a team needs him | Fixed v42 | Shop him (player page, trade screen, `shop`): up to five clubs that need him call over the next two weeks, the keenest first, a day or more apart; opening offers 70-80% of his value at low need, 80-92% at middling, 92-102% when they badly need him (docs/TRADES.md "Shopping a player") |
| 4 | Screens | Sort any table by clicking its column header; "LAKCSV GET" | Fixed v42 | Every simple table sorts by header (arrows show the order), the trade screens included; no CSV buttons on the trade screens |
| 5 | Trades | Every club "middle of the pack" at the start | Fixed v42 | Clubs are labelled from day one: on paper (expected strength) for the first ten games, then by the standings. The AI still waits 20 games before declaring itself a buyer or seller |
| 6 | History | Where are the player histories from the database? | Fixed v43 | Read straight from database.db (layout worked out with the community editor's column names): every player's career season by season in every league, and 3,492 past NHL draft picks; the bundled world ships with them (docs/HISTORY.md) |
| 7 | Trades | "Trade for him" should open the trade screen with him selected | Fixed v42 | He is ticked and scrolled into view (also from the right-click menu) |
| 8 | Scouting | Goalie projections in goalie words | Fixed v42 | Franchise starter, starter, 1A, 1B, backup, 3rd string, AHL depth |
| 9 | 2D game | On-ice play needs rework | Open | Waiting for the video |
| 10 | World | Remove the old generated world | Fixed v42 | It no longer ships; the bundled world is the only one (others can still be imported or built from packs) |
| 11 | Sim centre | The top bar pushes its buttons off screen | Fixed v42 | The bar wraps instead of overflowing, and once the sim stops it drops the pace buttons and progress bar to make room |
