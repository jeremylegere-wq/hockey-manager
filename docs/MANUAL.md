# Hockey Manager: the player's manual

*[Version française (Québec)](fr/MANUAL.md)*

You are the general manager of a hockey club. You decide who plays, who is signed, traded and drafted, what the club
spends, and how you answer to an owner who can fire you. The league plays on around you whether you are watching or not.

This manual is for playing. For building your own league see [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md); every system has a
deeper page in this folder, linked below. The formulas behind the AIs are in [ALGORITHMS.md](ALGORITHMS.md).

## 1. Starting

**Run it.** `./play.sh` (macOS, Linux) or `PLAY_WINDOWS.bat` (Windows). Python 3.9 or newer is the only requirement. The
first run builds the fictional world; it also offers to install pywebview so the game gets its own window. If you decline,
the game opens in a Chrome, Edge or Chromium app window, or your browser. `./play.sh --no-window` skips the question.

**The title screen.** Continue (your latest career), New Standard Game, Load Game, Settings, Credits, Exit.

**A new career** has these steps (docs/SETUP.md):

1. **Your GM**: name, nationality, age and a background (former player, scout, analytics, coach, business). A background is
   a small start, not a different game.
2. **Manager**: 66 points across six ratings (negotiation, judging talent, motivation, media handling, coaching, youth
   development), or a template. You earn a point for each season you complete. Choose your role (GM only, or GM and head
   coach), starting reputation, whether you can be fired, or start unemployed and take a job from the Job Centre.
3. **World** (if you have more than one): the fictional world, or a league you built or imported.
4. **Club**: every club by division with its outlook (contender, bubble, rebuild), strength and best players.
5. **Start**: a name for the save and a world seed. The same seed and the same decisions give the same results.

Careers are single `.db` files in `saves/`. The game writes to them as you play, so there is no save button to forget. Copy
a file to back it up. Rolling backups are on by default (File > Backups).

## 2. The screen

* **Menu bar**: File, Manager, Team, League, Statistics, Play, Help. Back and forward buttons, and search (Ctrl+F) for any
  player, club or staff member.
* **Tabs**: Office, Inbox, Roster, Lineup, Contracts, Trade, Transactions, Prospects, Scouting, Staff, Calendar, Standings,
  Statistics, News. Everything else is in the menus.
* **Bottom bar**: the date, the phase, your record and the trade deadline. **Day**, **Week**, **Next game** and **Rest of
  season** (in the summer, **Next offseason phase**). **Space** plays one day. **Ctrl+U** is Play Until (a date, the
  deadline, the last day of the season).
* **Right-click any player** for his profile, contract, stats, short list, a note, or to trade for him.
* **Every table sorts** when you click a heading and has a CSV button.
* **The sim stops when you are needed**: an injury, a short position, a trade offer, a press conference, the owner's office.
  Settings choose what interrupts you.
* **Sim pace**: Watch, Normal, Fast or Instant, for the broadcast view of the day's scores.

## 3. A year in the life

| When | What happens | What you do |
|---|---|---|
| Late June | Re-signing phase: rights on expiring contracts; the Hall of Fame vote | Qualify, extend or let go (Rights room) |
| 1 July | Free agency, run hour by hour in the War room | Offer, withdraw, watch the market |
| Summer | Draft (lottery, then the Draft room with a pick clock), development, camps | Draft, sign picks to entry-level deals, set training |
| 15 September | Pre-season, prospects tournaments | Set lines, cut down the roster |
| October to April | The regular season: 84 games, waivers, injuries, AI trades, all-star weekend in February | Manage lines, trades, the press, the money |
| Deadline | The league's last trade day | Buy, sell, or hold |
| April to June | Playoffs, awards, the owner's season review | Learn whether you keep your job |

## 4. The roster

* **Roster**: forwards, defence, goalies with key ratings, value, scoring, ice time, morale, cap hit and expiry. NHL roster
  or the whole organisation, depth chart, draft rights, contracts, injured, short list.
* **Ratings** are 1-20, in groups (technical, mental, physical, goalkeeping). **Value** is one number for how good a player is
  now; **potential** is where he can get to. Scouting accuracy depends on your scouts.
* **Waivers and the minors**: sending a player down can expose him to waivers (docs/WAIVERS.md). Your affiliate plays in the
  farm league; recall and send down from the Roster.
* **Long-term injured reserve** gives cap relief for long injuries (docs/LTIR.md).
* **Player cards** show contract value year by year, personality, morale and what he wants.

## 5. Lines and tactics

(docs/LINES.md, docs/TACTICS.md)

* **Lines**: four forward lines, three pairs, two goalies, power-play and penalty-kill units, overtime units. One drop-down
  per slot. **Auto** lets the assistant choose.
* **Lineups** are priority lists: the game rebuilds your lines before every game from your ordered preferences, so injuries
  and rest days do not leave a hole.
* **Goalie start rules**: how often your backup plays and when the starter rests.
* **Tactics**: twelve settings (breakout, neutral zone, forecheck, coverage, power play, penalty kill) with counters between
  choices, a coach who prefers some, and a fit and execution score for each. The owner has a preferred identity.
* **Tactical roles**: twelve roles (agitator, shadow, net-front presence, trigger man, forechecker, enforcer, penalty killer,
  shutdown D, puck mover, power-play quarterback, crease-clearer, rover). Each player has a fit for each role; give a role
  to the right player and it helps, to the wrong one and it hurts. AI clubs assign theirs.
* **Chemistry** between linemates and pairs builds over time; keep good lines together.

## 6. Contracts and the cap

(docs/CONTRACTS.md, CONTRACT_ENGINE.md, NEGOTIATION.md, CBA_2026.md)

* A **salary cap and floor** apply to the payroll. Cap room is on the dashboard and the Contracts screen, with a five-year
  outlook. A roster limit of 50 contracts applies.
* **Talks**: open them from a player's page. His agent has a style, patience and mood; the player has things that matter to
  him (money, term, role, a no-trade clause). Offer an amount, a term and clauses; you see his ask at every term and your
  own estimate of his worth. A good negotiating rating settles talks lower.
* **Restricted free agents**: qualify, negotiate, or face arbitration. Other clubs can submit **offer sheets**; you can match.
* **Entry-level contracts**, buyouts, salary retention, and **regret** (the contracts you would undo).
* Contract rules follow the 2026 collective agreement as summarised from public sources (term limits, year-to-year change,
  minimums, qualifying offers). Not legal advice, and not the agreement.

## 7. Trades

(docs/TRADES.md)

Build a deal on the Trade screen: click players and picks on each side; two clubs or three. The assistant gives a verdict,
and **"what would it take"** asks the AI what it wants for a player. Picks can be conditional. Salary can be retained. AI
clubs trade with each other until the deadline and in the summer. Players have trade value that depends on age, contract
and what the AI club needs. Rejected offers become rumours that the room hears about.

## 8. Scouting, the draft and prospects

(docs/SCOUTING.md, DRAFT.md, DEVELOPMENT.md, COLLEGE.md)

* **Scouting**: assign scouts to regions, watch knowledge of players grow, read central scouting's lists and the mock draft.
  Scouts have biases; your *judging talent* rating tightens your estimates.
* **The draft**: a lottery, then the Draft room: on the clock, your board, trades of picks, a pick clock in the settings.
* **Prospects** play in juniors, college, Europe or your farm club. Sign picks to entry-level deals before their rights lapse.
  Some players develop late; scouts cannot always see it.
* **Development** happens through the season and in the summer. It depends on age, potential, ice time, the level a player
  plays at, character, mentors you assign, your training intensity and focus, and your development staff.
* **College**: programs, eligibility, recruiting, and a college free-agent market.

## 9. The people

(docs/PEOPLE.md, MANAGEMENT.md, CAPTAINCY.md, PRESS.md)

* **Staff**: head coach, assistants, scouts, physios. Hire from the market, set what they do.
* **The room**: morale with reasons, promises you have made, cliques and clashes, trade requests. Pick a captain and
  alternates; the preview shows what each choice does.
* **The press room**: press conferences wait in your inbox. Answer one question at a time; the fallout shows after.
* **Assistant GM**: reads your organisation and lists problems with a button for each; never acts on its own.
* **Hidden attributes**: ambition, loyalty, big-game temperament, injury proneness and more, revealed by scouting and time.

## 10. The owner and the board

(docs/BOARD.md)

Every owner has a personality (spending, patience, a preference for youth or analytics). **Confidence** moves each week and at
reviews. When it gets low the owner issues an **ultimatum**, which gives a number of games and a points target. **Directives** are
standing orders ("do not trade anyone 23 or under"). **Owner goals**: three a season (acquire a top-30 skater, move a
contract, hire a better coach, give your best prospect 20 NHL games, win the season series against a rival...), each with a
priority and a deadline; meeting one gives +2 to +6 confidence, missing one costs 2 to 7. The Board screen shows all of it.

## 11. The money

(docs/FINANCE.md)

* **Prices and budgets**: ticket prices by seat type, scouting, development, promotions. Demand depends on winning, prices,
  the market, the arena and novelty.
* **Financial statements**: a chart of accounts (revenue, player costs, operating costs, depreciation, interest) and a
  **profit and loss report** by month, quarter or year, against budget or last year, with drill-down to every entry. A **cash
  statement** and a **board pack**.
* **The board's quarterly review** reads your numbers against budget and moves confidence.
* **Arena**: renovations raise quality. A **new arena** (offseason only, once) costs capacity x $22,000 x a quality factor; the
  owner pays 20% plus 6% per point of his spending trait, the club borrows the rest over 25 years at 5%; it takes two
  seasons and gives a novelty boost at the gate that fades over five.

## 12. The wider world

* **Other leagues** (AHL-style farm league, an ECHL-style league, three junior leagues, college, six European leagues) play
  real seasons with standings and playoffs. Their players are your future.
* **International hockey**, **expansion** (a new club, an expansion draft), **discipline** (suspensions and fines), the
  **Hall of Fame** and your **GM score** and achievements.
* **History**: league champions, awards, records, past drafts, season pages, club pages, every player's career.
* **News**: headlines, recaps, a social feed, power rankings, and an archive.
* **The 2D game**: open any played game to watch it on the rink: every player, the puck, line changes, power plays,
  goals with their passes. Speed, cameras, goals only, full window (docs/RINK2D.md).

## 13. Making it yours

* **Settings**: interface size, units, sim pace, interruptions, pick clock, backups, console.
* **Editor and commissioner mode** (File > Editor): edit any player or club, import and export CSV, trade any clubs, take over
  any club, set league rules. Turning it on marks the save as edited for good.
* **Challenge mode** and six **challenges** (turnaround, rebuild, win now, cap hell, dynasty, expansion) with deadlines; no
  editor, short sims in-season, and you can be fired.
* **Quickstarts**: save a world at the start of a season and start new careers from it.
* **Your own logos**, **schedule export and import**, a **French (Quebec) interface**.
* **Console** (File > Console): any command, e.g. `sim week`, `standings`, `trade ABC give ... get ...`. `help` lists them.

## 14. Your first season: a checklist

1. Open **Office** and read the owner's welcome and objectives.
2. **Roster**: check cap room, injuries, expiring contracts. Look at the depth at each position.
3. **Lineup**: press Auto, then change what you disagree with. Check the PP and PK units.
4. **Tactics**: leave the defaults until you see what the coach likes.
5. **Staff**: any empty role? Hire. Any unhappy player? Open his card.
6. Press **Space** a few times. Read the Inbox when the game stops.
7. By December look at **Standings** and **Board**. Is the owner's confidence moving?
8. Before the deadline decide whether you are buying or selling.
9. In the summer: **Rights** (expiring deals), the **draft**, then **free agency**. Set training for your prospects.

## 15. Questions

**The game does not open a window.** Run `./play.sh --no-window`, or `python3 -m hs.ui.server --saves saves --template auto
--open`. On Linux the window needs `libxcb-cursor0`.

**"No template world".** Run `python3 -m hs.tools.make_mock_world` and start again.

**Can I use real players and clubs?** Only with data you own and only for yourself: see BUILD_YOUR_OWN.md. Nothing real ships.

**Can I undo?** Rolling backups (File > Backups) restore a copy as a new save. Careers are plain files; copy one before a risky
decision.

**A result looks wrong.** It might be a bug. Help > Report a bug, or email jeremy.legere@gmail.com with the save file.
