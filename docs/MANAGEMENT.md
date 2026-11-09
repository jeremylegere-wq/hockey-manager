# Management layer (GM spec v2, MVP)

Simulation first, presentation second: every system below writes facts (tables + `league_events`); the CLI only
reads them and calls the same functions a GUI will call.

| Spec item | Module | What it does |
|---|---|---|
| Event mechanism (5.3), history (3.8) | `hs/game/events.py` | `league_events`: dated, typed, with team/player/staff and a JSON payload. Signings, releases, trades, injuries, retirements, draft picks, arbitration, championships, objectives, board reviews, firings, staff moves, concerns, conversations, promises, captaincy, trade requests. `history`, `history league`, `history <player>`. |
| Ownership and objectives (3.1) | `hs/game/org.py` | Owner profile per club; season objectives (competitive / financial / development, plus a 3-season target for rebuilding clubs), required or preferred, from the owner and the roster's projected rank. |
| Board confidence and job security (3.1) | `hs/game/org.py` | Monthly drift with points pace; season review by objective (met earns less than missed costs; patience scales losses; credit fades 25% a year; a poor dressing room costs a little; a title earns a lot). Every change stored with reasons (`board`). Below the owner's threshold: AI GMs are fired; you get a warning, then are fired, and can `jobs` / `takejob`. |
| Staff and departments (3.2) | `hs/game/staff.py` | 10 staff per club (HC, 2 AC, GC, DEV, scouting director + 2 scouts, medical, analytics) with attributes and styles; a staff market. Scouting quality sets how far off your draft estimates are; development staff speed up players 24 and under; medical staff shorten injuries; the head coach shapes trust in coaching. AI clubs with an unhappy, impatient board fire the head coach in the summer. `staff`, `staffmarket`, `hire`, `dismiss`. |
| Locker room (3.3) | `hs/game/people.py` | Personality (professionalism, ambition, loyalty, leadership, resilience, patience, ego, role tolerance). Morale from five separate components (role, team, contract, trust in you, trust in the coach), updated weekly. Captain and alternates; cohesion from morale, leadership, turnover and clashing personalities - not from wins directly. `lockerroom`, `captain`. |
| Promises and trust (3.4, 17.2) | `hs/game/people.py` | Concerns become meeting requests (role, contract, call-up, trade request). `talk <player>` shows the concern and the options; `respond <player> supportive|direct|firm|diplomatic|promise`. The same words land differently by personality; repeating reassurance without action stops working; only `promise` is binding and measurable (ice-time rank over 10 games, an accepted extension by a date, NHL games after a call-up, a trade by a date). Broken promises cost trust, and if he is a leader or star, his teammates notice. `promises`. |
| GM dashboard (6.1) | `hs/game/cli.py` | `dashboard`: record, cap, board and objectives, locker room, things needing attention (meeting requests, promise deadlines, inbox), recent news, next game. |

Also: in-season contract extensions (`extend` in a player's final year; players who distrust you want 10% more,
players who asked for a trade will not talk).

## Calibration notes (three seasons, full world)
Boards ended spread across secure (7), stable (16), under pressure (4) and hot seat (5); 2 GM firings and about 8
head-coach firings a summer by year three; cohesion between ~50 and ~67. These are first settings, not tuned
against real history.

## The boardroom (v24)
Weekly hot-seat score, ultimatums, owner directives, coach scapegoats and media leaks by the owner's vocalness:
docs/BOARD.md. The monthly confidence drift is replaced by a weekly one.

## Staff contracts (v23)
Staff contracts now run out. Each offseason, AI clubs re-sign staff who are 10+ at their main job (and half of the
rest) for two years and let the others go to the market; yours renew for two years automatically, with an inbox
note so you can dismiss someone and hire from the market instead (Staff screen).

## Deliberately not yet
Morale does not change match ratings (the spec warns against morale substituting for ability, and the engine is
calibrated). Media, social feed and press conferences (spec 3.6, 17.1-17.2) will be a presentation layer over
`league_events`. Coach tactics/system effects on the engine, coaching careers beyond hire/fire, scouting
assignments by region, AI trades (so AI trade requests stay unresolved), and AI clubs acting on their players'
concerns are next candidates.
