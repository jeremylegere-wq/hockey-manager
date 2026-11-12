# Roadmap: the reference manual against the game (v28, updated v31)

The reference (Hockey_Simulation_Reference.md, supplied 1 Nov 2026) is a consolidated manual for a commercial hockey
management game. It is used here as a **feature checklist only**: every system below gets our own design, our own
numbers and our own words. Nothing from the manual's text, tables or examples is copied into the game.

Legend: **have** = in the game now, **part** = some of it, **gap** = not started. Phase = the release it is planned for.

## 1. Start, setup and the shell

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Start screen: continue, new standard game, load, settings, credits | Launch screen (v28) with all five plus Exit | have | - |
| New historical / custom / exhibition game, historical challenges, quickstarts | Custom leagues via data packs; challenges (v47); quickstarts (v48). No historical starts (the database holds careers, not past rosters) | part | G |
| Achievements, rankings (career scores) | 22 achievements; GM score and GM leaders (v37, docs/CALENDAR.md) | done | F |
| Settings: window size, units, player popups, sound, logo cache, rolling saves, custom data path, facegen options | Interface size, units, popups, console, launch screen, sim pace, phase confirmations (v28). Saves are continuous (every action commits); no rolling backups | part | G (custom data path); rolling backups done (v31) |
| Set up your manager: name, nickname, nationality(s), birthplace, birthdate | Name, nationality, age, background | have | - (v32) |
| GM-only vs GM + coach; start unemployed; cannot be fired; starting reputation; start on 1 July; scout-bias randomise; no stat history; stat-adjusted talent weights | Always GM (coach runs the bench); always employed at start; jobs market exists after a firing | part | G (scout bias, stat-adjusted talent); the rest done (v32) |
| Manager ratings and templates (points to spend) | Background perk only | have | - (v32) |
| Challenge mode (no commissioner, no editor, offseason-only long sims) | v47: challenge mode (no editor, in-season sims of a week at most, can be fired) and six challenges with deadlines (docs/CHALLENGES.md) | done | G |
| Menu bar: File, World, Manager, League controls, Team controls, Play, Continue | File, Manager, Team, League, Statistics, Play, Help menus; Continue in the bottom bar; Space continues one day (v28) | have | - |
| Status box: date, record, schedule boxes (yesterday into the future) | Date and record in the header | have | - (schedule strip, v31) |
| Back / forward / home, search (players, staff) | Back, forward, home, search for players and clubs (v28) | have | - (Find Players, v32) |
| Notes screen | - | have | - (v31) |
| Play menu: auto-play until a date / an event; today's game | Day, week, next game, rest of season, next offseason phase | have | - (Play until, v31) |
| Continue button names the day's event (draft, lottery, awards, HoF) | The sim stops for press conferences and phases; the button does not rename itself | have | - (today's event beside Continue, v31) |

## 2. League controls

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Standings (conference, division, playoffs views) | Wild card, divisions, league; playoff bracket page | have | - |
| League schedule, day by day, with box scores and today's games to watch | Your schedule and calendar (v28), any game's recap and replay | have | - (v31) |
| Transactions: free agents, upcoming FAs, trade block, waivers, offer sheets, injured | Free agent centre (v28), waiver wire, offer sheets, injuries (console) | have | - (the transactions hub, v31) |
| Milestones (players near career marks) | - | have | - (v31) |
| Stats with tooltips | Stats hub: leaders, skaters, goalies, teams, splits; analytics suite | have | - (column tooltips, v31) |
| Events (draft, deadline, season dates) | Calendar shows opening night, deadline, last game, all-star weekend, exhibitions, the summer's phases and the scouting tournaments (v37) | done | F |
| Rules screen | `rules` in the console | have | - (v31) |
| League history: season pages, awards, player and staff indexes, leaderboards | Champions, awards, all-time and single-season leaders | part | G (staff index); season pages done (v31) |
| Central scouting lists (futures list, pre-season A/B/C, midterm, final) | - | have | - (v36) |
| Reports: prospect rankings, power rankings, positional rankings, injury report, game performances, morale report, draft surprises, demographics | Power rankings | part | G (draft surprises, demographics); the rest done (v31) |
| Draft logs (past drafts) | Draft room for the current draft | have | - (past drafts, v31) |
| Edit league / commissioner mode | Player and club editor and bulk import (v40); v47: trades between any clubs, take over any club, fire GMs and coaches, injuries, league rules (docs/EDITOR.md) | done | G |

## 3. Team controls

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Roster tabs: active, contracts, protected list (rights), injured, waivers, trading block, short list, reserve | NHL roster, whole organisation, waivers, LTIR; rights on Prospects (v28); block flags on Trade | have | - (v31) |
| Right-click actions on players | Buttons per row | have | - (v31) |
| AI assistant: dress, lines, whole organisation | Automatic lines | have | - (assistant GM, v32) |
| Lines: dressed list, drag and drop, locks; PP, PK, 4-on-4 / 3-on-3 units; goalie start rules | Dropdown lines, PP and PK units, starter and backup; OT units (v33); goalie start rules (v52) | part | G (drag and drop, locks) |
| Lineups (priority lists that rebuild lines each game) | v52: priority lists per slot rebuild the lines before every game (docs/LINES.md) | done | G |
| Depth chart (organisation by position, prospects, future picks) | - | have | - (v31) |
| Team history: player index, staff index, leaderboards, alumni, jersey numbers, records | Team page with seasons and franchise leaders; jersey numbers and retired numbers (v49) | part | G |
| Trade offer: summary, assistant's opinion, five-asset limit, rights, pick protection (1/3/5/10), "make this work", needs tab, shopping tab (3 a day) | Two- and three-club trades, verdicts, "what would it take", picks, retention | part | G (needs, shopping, pick protection) |
| No-trade / no-movement clauses with acceptable destinations | No-trade flag on contracts | part | G (with the contract clauses) |
| Staff screen and staff market | Have | have | - |
| Upcoming FAs, unsigned picks with signing deadlines | Rights room, Prospects (v28) | have | - |
| Transaction log (by season) | Organisation history | have | - (v31) |
| Free agent centre and transfer summary | Free agent centre and war room | part | G (transfer summary) |
| Monthly finances: gate (seat types), broadcast, sponsorship and merchandise, owner contributions, fixed costs, scouting / morale / promotions budgets | - | have | - (v34; promotions budget: G) |
| Annual finances: ticket prices, arena improvements and quality, new arena, wage budget, development budget, marketing, owner profit-taking | Prices, budgets, renovations (v34); financial statements and budget (v54); a new arena with a loan (v57) | part | G (wage budget as a cap) |
| Year summary, salary and cap obligations | Contracts outlook (five seasons) | have | - (the season's books, v34) |
| Team info: arena, farm links, retired numbers, chemistry, job security | Affiliates on the team page, job security screen | have | - (Team Info, v31; retired numbers when packs carry them) |

## 4. Tactics

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Global / unit / player levels | Club settings, overtime units, player tendencies (v33) | part | G (unit-level settings) |
| Twelve tactical settings (breakout, neutral zone, attacking zone; forecheck, NZ coverage, D-zone coverage; PP breakout, setup, defensive approach; PK forecheck, coverage, attack) with counters between choices | Five team systems with roster fit and execution (docs/TACTICS.md) | have | - (v33) |
| Tactical tendencies per player (attacking, aggression, backchecking, pressure, hitting, tempo, passing, shooting) | - | part | G (hitting, tempo, pressure); shooting and style done (v33) |
| Global preferences: pull the goalie (down 1, down 2), goalie switch, faceoff priorities, line matching | Fixed engine behaviour | part | G (faceoff priorities); pulls, hook, line matching done (v33) |
| Player fits under each setting; coach preferences | Fit and execution per option, coach style bonus (v33) | have | - |
| Tactical roles with fit scores and on-ice effects (agitator, shadow, crease-clearer...) | Twelve roles with fit, execution and effects by strength state; AI clubs assign theirs (v55) | done | G |

## 5. People and the dressing room

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Visible attributes (offensive, defensive, mental, physical; goalie set) | 1-20 attribute model | have | - |
| Hidden attributes (aging, ambition, big games, coachability, controversy, development rate, greed, handle failure/success/critics, injury proneness, intelligence, loyalty, mood, pass/shoot, sportsmanship, temperament) | Personality: professionalism, ambition, loyalty, leadership, resilience, patience, ego, role tolerance | have | - (seven hidden attributes, v35) |
| Ability and potential stars | Value number and potential (1-20) | have | - (stars on prospects and rankings) |
| Player templates (position x style x physicality) | Generated by position | part | G |
| Special abilities (big hitter, iron man, homebody, malcontent, great deke...) | - | have | - (badges, v35) |
| Player happiness with event list and mouse-over reasons | Morale with components, concerns and promises | have | - (the morale log, v35) |
| Player roles: major (playmaker, power forward, two-way D...) and supplementary (franchise, star, leader, prospect, depth...) | Implicit (ice time) | have | - (display, v33) |
| Team harmony: incidents, conflicts, cliques | Cohesion, leadership strength, trade requests | have | - (cliques, clashes, incidents, v35) |
| Line chemistry (asymmetric, ten slots, semi-permanent and temporary) | - | part | G (asymmetric); pair chemistry done (v33) |
| Rust after layoffs | - | have | - (v35) |
| Game rating (offensive, defensive, overall per game) | Three stars, box scores | have | - (v35) |
| Injury deferral | - | have | - (playing hurt, v35) |
| Mutual contract termination | Buyouts, releases | have | - (v35) |
| Contract bonuses (ELC, 35+ one-year, injured veterans; A and B levels) | ELC performance bonuses | part | G (35+ and injured-veteran bonuses) |
| Media relations: coverage level, base attitude, focus players, GM responses | Press room with archetypes, sentiment, controversy, story chains (v27) | part | G (coverage level, focus players) |
| Staff attributes (evaluate ability/potential, tactics, motivation, negotiation, self-preservation, trainer skill...) | Coach, development, evaluation, medical, communication, leadership, style | part | G (negotiation, self-preservation, trainer skill) |

## 6. Scouting, development and the draft

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Scouting coverage by region, head and advance scouts, priorities, watch list | Director philosophy and evaluation error | have | - (v36) |
| Scouting levels A-E and success chance a-e; levels decay | Error shrinks with staff quality | have | - (v36) |
| Tournament and youth-tournament scouting assignments | - | have | - (v36) |
| Training: coaching bonus points by category, goalie training slots | Development coach rating, ice time | part | G (goalie training slots); focus by player done (v36) |
| Development tracking chart (career or last 12 months, by attribute group) | Ratings history on the profile; Development screen (v28) | have | - (v36) |
| Variable potential, wild cards | - | have | - (v36) |
| Draft: available, order, mock draft, scout / safe / risky suggestions, lottery | Draft room with lottery, board, ticker (v27) | have | - (mock and suggestions, v36) |
| Exceptional junior status | - | have | - (v36) |
| College hockey: scholarships, verbal commitments, signing day, walk-ons, academic eligibility, redshirts, polls, regionals, transfer portal | v46: programs and prestige, commitments, eligibility (old rules and 5-in-5), enrolment and graduation, college free agents, the Hobey Baker; NCAA seasons with the tournament (v44). Not modelled: scholarships, walk-ons, the transfer portal, polls | partial | G |

## 7. The season and the world

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Pre-season games | Six a club before opening night, prospects audition, chemistry, camp report (v37) | done | F |
| Prospects tournaments | One per division in mid-September; tryout invitees; your scouts watch (v37) | done | F |
| All-star game formats and skills competition | Conference, captains' draft, North America v the World; five skills events (v37) | done | F |
| Rivalries (main and potential, levels, big-game effects, fan swings) | Rivalry points per pair, five levels, main and potential rivals, big games, gate, fan swings (v37) | done | F |
| Hall of Fame (committee vote you take part in, or automatic) | 18-member committee, 75% to induct, up to four a year; your ballot (v37) | done | F |
| GM leaders and GM score | Season and career GM scores for every GM; GM leaders screen (v37) | done | F |
| International: tournaments, national teams, world rankings, Triple Gold Club | v51: World Juniors, World Championship, World Cup (2028...) and Olympics (2030...); rosters by nationality; IIHF-style ranking; medals; the Triple Gold Club; the NHL's February break (docs/INTERNATIONAL.md) | done | G |
| Expansion and expansion draft | v45 | done | G |
| Owner goals (a catalogue of acquire / get rid of / hire / prospect / attendance goals with priorities and deadlines) | Board objectives and directives; the owner's goals: twelve from a catalogue, with priorities and deadlines (v56) | done | G |
| Job security: in-jeopardy status, offseason firings, firing your coach to buy time | Hot-seat score, ultimatums, leaks, firings (docs/BOARD.md) | have | - (dismissing the coach buys time with the board) |

## 8. Modding and data

| Spec | Game now | Status | Phase |
|---|---|---|---|
| Data packs, custom leagues | Data packs and adapters (docs/DATAPACK_SPEC.md) | have | - |
| Logos (150 x 150), backgrounds, jerseys | Generated crests (v28); your own logo files replace them (v48); your own player photos, else the back of his jersey with name and number (v49) | part | G (backgrounds) |
| Export CSV | - | have | - (every table, v31) |
| Schedule export / import; preset injuries, suspensions and captains in packs | Schedule export and import (v48); captains via leadership; injuries set by the commissioner (v47); suspensions (v53) and preset injuries and suspensions in packs (v53) | done | G |
| Name generation by nation | worldgen names | part | G |

## Phases

Before phase A: the defects register (docs/DEFECTS.md). v29 fixed the first batch and v30 the rest (AI three-team
trades, rumours and morale, KHL and NCAA signings, media outcomes in the engine, the 2D game, AI star-trade limits,
draft-day trading, the pick clock and the outside rankings, fuller messages). Every register item is closed except
two parts that wait for later phases: signing bonuses in buyouts and attendance from fan mood (both phase C). Phase A
was v31 and A2 (your manager) v32; phase B (tactics and lines) v33; phase C (money) v34; phase D (people) v35; phase E (scouting and development) v36; phase F (the calendar) is next, in v37.


* **A, the depth of the screens (v31, done).** Tabbed roster with the short list and injured, depth chart, transaction
  log by season, team info, league schedule by day, the transactions hub, reports (positional, prospect, injuries,
  game performances, morale), milestones, past drafts, season pages, rules, notes, Play until a date or event, the
  schedule strip and today's event in the header, a right-click menu on players, column tooltips, staff in the
  search, CSV export of any table, rolling backups (docs/SCREENS.md).
* **A2, your manager (v32, done).** Manager ratings with points to spend and templates, reputation, GM only or GM and
  head coach, cannot be fired, start unemployed, the Job Centre (and a fired GM's club handed to the AI), the assistant
  GM, Find Players with filters (docs/SETUP.md).
* **B, tactics and lines (v33, done).** Twelve settings with fit, execution and counters (the five systems as
  presets), preferences (goalie pulls, the hook, line matching, ice time), overtime units, player tendencies, line
  chemistry, player roles with line notes, the Tactics screen with opponent scouting; a calibration pass
  (docs/TACTICS.md, docs/LINES.md, docs/SIM_CALIBRATION.md). Not done: lineup priority lists, tactical roles with
  on-ice effects (agitator, shadow) (phase D).
* **C, money (v34, done).** Club profiles (market, arena, seat types), attendance by demand (fans, form, price,
  arena), the gate, concessions, media, sponsorship and revenue sharing; costs; budgets (scouting, development,
  marketing); ticket prices; arena renovations and expansion; the owner's cut; the season's books; finance and
  attendance objectives (docs/FINANCE.md). Not done: salary by year and signing bonuses, a new arena (G).
* **D, people (v35, done).** Hidden attributes (consistency, big games, injury proneness, temperament, sportsmanship,
  coachability, greed) with scouted phrases, special abilities, game ratings, rust after layoffs, playing hurt, the
  morale event log, cliques, clashes and incidents, mutual termination (docs/PEOPLE.md). Not done: media coverage level
  and focus players, veteran bonuses, lineup priority lists, tactical roles, asymmetric chemistry, templates (G).
* **E, scouting and development (v36, done).** Regions and scouts' assignments, knowledge levels A-E with decay, the
  watch list, tournament trips, central scouting's lists by stage, the mock draft and pick suggestions, exceptional
  juniors, training focus, variable potential and wild cards, the development chart (docs/SCOUTING.md). Not done:
  scout-bias randomising and stat-adjusted talent at setup (G).
* **F, the calendar (v37, done).** Pre-season games, prospects tournaments, all-star weekend, a real rivalry model,
  Hall of Fame, GM leaders, achievements. International play moves to G.
* **v38: your database and the second register.** The ratings model (42 ratings, ability and potential, positions and
  roles) becomes the game's own; your database export imports as a world (docs/DB_IMPORT.md); the inbox, the press
  and the start of a career, screens and the 2D engine from the second register (docs/DEFECTS.md).
* **v39: the trade market and the third register.** A friction-based trade market (minor-league swaps, depth deals,
  deadline rentals, regulars only when need beats friction, draft-day pick swaps; a replacement-level value scale;
  protected picks; generated NTC / NMC / modified lists; retained salary as an asset), contract talks with trade
  protection and pitches, professional tryouts, a Quebec French interface option, and the third register
  (docs/TRADES.md, docs/DEFECTS.md).
* **v40: player development and the editor.** Young players grow through the season (monthly steps) as well as in
  the summer, driven by ice time, level of play, character, mentors, training intensity and injuries; a development
  centre and monthly reports (docs/DEVELOPMENT.md). Commissioner mode: edit any player, contract or club, and bulk
  export/import players as CSV with a preview (docs/EDITOR.md).
* **v41: cap and cash, conditional picks, history.** Contracts pay salary and signing bonuses season by season apart
  from the cap hit (flat, front-loaded, bonus-heavy; chosen in talks; bonuses survive buyouts) and finance pays the
  cash (docs/FINANCE.md). Picks that upgrade a round if a club makes the playoffs or wins a round, for you and the AI
  at the deadline (docs/TRADES.md). Careers from before the save (the M3 profiles, the editor) count in waivers,
  milestones, the Hall of Fame and new all-time leaders; past drafts import from a CSV (docs/HISTORY.md).
* **v42: the fourth register.** No source-game names in the code; shop a player; sortable tables everywhere; clubs
  labelled from day one; goalie projections; "Trade for him" preselects; past seasons import; the old world removed;
  the sim centre's bar fits (docs/DEFECTS.md).
* **v43: history from the database.** Every player's career season by season (every league, playoffs too) and the past
  NHL drafts, read from database.db (docs/HISTORY.md).
* **v44: the world's leagues.** The 13 leagues around the NHL play real seasons under their own rules (schedules,
  points, playoff formats, import and over-age limits, champions, the Memorial Cup), and 23 more leagues from the
  database join the world, simulated a season at a time with rules from the database; League > World Leagues
  (docs/LEAGUES.md). Open: the 2D game's on-ice play (waiting for the video); past champions and award winners. Next:
  expansion, then college recruiting; French at the end.
* **v45: expansion.** The league adds a club now and then, or you create one (and can become its GM); the club comes into
  being when the season ends with its arena, owner, staff and an AHL affiliate; protection lists (7-3-1 or 8-1, no-
  movement clauses, exempt young pros, exposure rules); the expansion draft with side deals; the third-worst lottery
  odds; schedules for uneven divisions; League > Expansion (docs/EXPANSION.md). The Hall of Fame votes by the Career
  Legacy Score (era- and position-adjusted Season Values, peak and longevity, trophies and milestones; a CLS tracker),
  and awards night adds the Selke and the First All-Star Team (docs/HALL_OF_FAME.md).
* **v46: college hockey.** NCAA programs with prestige and coaches; eligibility under the old rules and the 2026
  "5-in-5" model; recruiting rounds and commitments; enrolment and graduation; steering your prospects (college or
  junior); rights that run with college eligibility; the Hobey Baker Award; the college free-agent market each spring;
  League > College Hockey (docs/COLLEGE.md). Next: the long tail (commissioner and challenge modes, historical starts,
  pack logos, schedule import/export), then French; the 2D on-ice rework last. (The women's league is off the plan for now.)
* **v47: challenges and the commissioner.** Challenge mode and six challenges (turnaround, rebuild, win now, cap hell,
  dynasty, expansion) with deadlines and results (Manager > Challenges, docs/CHALLENGES.md); commissioner tools: trades
  between any clubs, takeovers, firing GMs and coaches, injuries and league rules (League > Commissioner, docs/EDITOR.md).
* **v48: quickstarts, schedules and logos.** Save a world at the start of a season and start careers from it with any
  club; export the schedule, import one in commissioner mode; your own club logos; challenge options in the new-career
  wizard (docs/QUICKSTARTS.md).
* **v49: numbers and pictures.** Jersey numbers from the database (unique per club, 99 retired, clubs retire their
  own), changed from the roster or the player screen; your own player photos, else the back of his jersey
  (docs/NUMBERS.md).
* **v50: French.** The French (Quebec) interface covers every screen's labels, tabs, headings and buttons, dates and the
  status bar (docs/FRENCH.md); the game's own text (news, messages) stays in English for now.
* **v51: international hockey.** National teams, the World Juniors, the World Championship, the World Cup and the
  Olympics, the world ranking, medals and the Triple Gold Club (docs/INTERNATIONAL.md).
* **v52: lineups.** Priority lists that rebuild your lines before every game, and goalie start rules (docs/LINES.md).
* **v53: discipline.** Suspensions from games (with repeat offenders and appeals), preset injuries and suspensions in
  packs (docs/DISCIPLINE.md).
* **v54: financial statements.** A chart of accounts over the club's books, a profit and loss report in the manner of
  an accounting package's (periods, monthly and quarterly columns, account levels, budget and last-year comparison,
  drill-down to the journal lines, CSV and print), the season's budget, depreciation, interest and a cash statement,
  and the board's quarterly finance reviews with the owner's reply (docs/FINANCE.md "Financial statements").
* **v55: tactical roles.** Twelve roles (agitator, shadow, net-front presence, trigger man, forechecker, enforcer,
  penalty killer, shutdown D, puck mover, PP quarterback, crease-clearer, rover) with fit scores, execution and effects
  on the ice by strength state; break-even at average fit, league-neutral penalties (docs/TACTICS.md).
* **v56: the owner's goals.** A catalogue of twelve goals (acquire a star or a goalie, move a contract, hire a coach,
  play a prospect, keep or add a first, beat the rival, home wins, a younger roster, a Canadian core), three a season
  with priorities and deadlines, met or missed against board confidence (docs/BOARD.md).
* **v57: a new arena.** Proposed in the offseason, approved by the owner, built over two seasons with his contribution
  and a 25-year loan; opens with a new capacity and quality and a few seasons of novelty; depreciated over thirty years
  (docs/FINANCE.md).
* **G, the long tail.** Historical starts (needs past rosters), backgrounds; the game's
  own text in French; the 2D on-ice rework last.

Each phase ships with its docs page, unit tests and a pass through every screen in the desktop window.
* **v58: the public release.** A fictional world ships instead of a real-name one: `hs/tools/make_mock_league.py` (32 invented `docs/ALGORITHMS.md` collects the mathematics behind every AI.
  clubs, calibrated players, a cap), `build_world --fictional` (invented farm, junior, college and European clubs,
  `hs/leaguedata/fictional.py`), `hs/tools/make_mock_world.py`, and a first-run bootstrap (`--template auto --env auto`,
  `hs/bootstrap.py`, `data/env_default.json`). Help > Report a bug. README, the player's manual (`docs/MANUAL.md`), the
  build-your-own guide (`docs/BUILD_YOUR_OWN.md`), contributing, issue templates, licence and third-party notices.
* **v59: the 2D game, rebuilt.** A plan of each played game (`hs/sim/ice_plan.py`: event times the ice allows, strength,
  who was on the ice) and a new on-ice engine (`hs/sim/ice2d.py`) that plays it as hockey: breakouts, three lanes
  through the neutral zone, the cycle, a 1-3-1 power play, forecheck and zone coverage, goalies on their angle, changes
  on the fly, faceoffs, the penalty box, the sixth attacker, celebrations, the shootout. A new viewer (`ice.js`): jersey
  tokens with numbers and sticks, benches and boxes, a broadcast scoreboard, banners, two cameras, full window. The
  match engine still decides every result; nothing is written to the save, so every old game plays (docs/RINK2D.md).
