# Architecture audit and roadmap (October 2026)

Answers the "Phase 0 / audit first" step of the GM-simulator spec (v2) and the GUI master spec, against the code
as it stands (v9), plus a review of the reference material in `02_Game Development.zip`.

## 1. What exists

| Area | Where | State |
|---|---|---|
| Data model | `hs/schema.py` (SQLite, schema v2) + game tables added by `hs/game/state.py` and `contracts.py` | players, attributes (1-20), teams, seasons, contracts, history stats, games, game_events, box scores, injuries, transactions, inbox, manager, retained, cap_charges, offseason_rights |
| Data in | `hs/datapack.py` (validator), `hs/ingest.py`, adapters (`fhm_csv`, MoneyPuck ratings; legacy importers in tools/) | one path in; third-party packs flagged non-redistributable and git-ignored |
| Ratings | `hs/ratings/moneypuck.py` | ratings from outcomes with shrinkage |
| Match engine | `hs/sim/engine.py` | statistical, 30-second segments, calibrated to 2025 league rates; events stored per game |
| League | `hs/league/` | rules.json, schedule, standings, tiebreakers, playoffs |
| Game loop | `hs/game/dayloop.py`, `injuries.py`, `roster.py` | day-by-day, injuries, AI roster moves, deterministic seeds |
| Money | `hs/game/contracts.py`, `offseason.py`, `arbitration.py` | cap, contracts, buyouts, retention, RFA/QO, free agency, arbitration, season rollover |
| UI | `hs/game/cli.py` | command line only |
| Persistence | the .db file is the save; `state.connect` adds new game tables to older saves | no migrations framework yet |
| Tests | `tests/` (unittest, 48 tests) | fictional pack + synthetic env; no third-party data |

Every random draw comes from a seeded `random.Random` keyed by seed/day/purpose, so a save replays exactly.

## 2. Spec v2 mapped to the code

| Spec area | Status | Where it would live | Notes |
|---|---|---|---|
| NHL rules engine (cap, RFA/UFA, QO, arbitration, retention, buyouts) | **Built (core)** | contracts/offseason/arbitration | offer sheets, waivers, LTIR, draft, ELC, Group 6 missing |
| Era-configurable rules (NFR-09) | **Partial** | rules.json | contract rules and schedule are data; OT format/ties still hard-coded in the engine |
| Organisational history (3.8) | **Partial** | transactions, games, injuries, inbox | add a typed `events` table (below) rather than copying data |
| Asset evaluation (3.5) | **Partial** | roster.player_value / trade_value / contract_adjustment | needs ageing curves and projection before "future value" means anything |
| Ownership and board confidence (3.1) | Missing | new `hs/org/ownership.py` + tables | needs season-end review hook (exists: finish_season) |
| Staff and delegation (3.2) | Missing | new `hs/org/staff.py` | |
| Locker room, personality, promises (3.3-3.4) | Missing | new `hs/people/` | needs personality attributes in the pack spec first |
| Media, social feed, press conferences (3.6, 17.1-17.2) | Missing | presentation layer over the event table | strictly generated from simulation facts |
| Scouting fog of war (17.3) | Missing | `scouting_knowledge(team, player, estimate, confidence)` | the 1-20 truth stays hidden; UI shows estimates |
| Coach personalities and carousel (17.4-17.5) | Missing | coach profiles feed a team "system" factor in the engine | engine change needs recalibration |
| GUI (GUI spec) | Missing | see section 4 | |

## 3. Two structural changes to make before the people systems

1. **One event table.** `league_events(event_id, date, type, team_id, player_id, staff_id, payload_json, source)`
   written by the simulation (trade, signing, injury, award, arbitration, promise made/broken, coach fired...).
   Media, social feed, history screens and AI reactions read it; nothing in the presentation layer writes game
   state. Transactions stay as they are; the event row points at them.
2. **Migrations.** A `schema_migrations` table and numbered migration functions, so new tables and columns land in
   old saves predictably (today `ensure_game_tables` only adds tables).

## 4. GUI recommendation

The GUI spec deliberately does not pick a framework. Options for this codebase (Python, stdlib-only so far):

| Option | For | Against |
|---|---|---|
| Local web UI: Python serves JSON from the existing modules, browser front end (plain JS or a small framework) | no rewrite, dense tables are easy in HTML, the mock-ups' look is easy to hit, runs anywhere | needs a small local server; a desktop window wrapper (e.g. pywebview) is optional |
| PySide6 (Qt) desktop app | true desktop app, fast tables | large dependency (LGPL), Qt styling to match the mock-ups is slower |
| Tauri + web front end (Openfoot Manager's route) | small native app | adds a Rust toolchain; the simulation would sit behind a Python sidecar |

Recommended: the local web UI, with the CLI kept as the test harness. Every screen calls the same functions the
CLI calls, so the GUI never computes hockey outcomes itself (GUI spec 17-18).

## 5. The 2D match view

The current engine is statistical and calibrated; it produces events, not positions. Two ways to get a 2D view:

- **Replay view (recommended first):** draw each stored event on a rink with plausible positions (shot location from
  event type/xG, players by line). Calibration is untouched and every past game can be replayed from its seed.
- **Positional engine (later, large):** an agent-based engine like `football-simulator`'s RealTimeEngine (0.25 s
  slices, intents, tactics). It would have to be recalibrated to the same league rates before it could replace
  the statistical engine.

## 6. Reference material reviewed

| Item | Licence | Verdict |
|---|---|---|
| football-simulator (TypeScript) | MIT | Best reference for a positional/2D engine and the "simulator as a service" boundary (its integration guide matches how hs/sim is used). Ideas or code usable. |
| openfootmanager (Rust/Tauri/React) | GPLv3 | Strong reference for scope, docs (game systems, save design, modding) and the "authored data, no licensed database" stance. Copying code makes this project GPLv3. |
| hockey-engine (Angular) | GPLv3 | Early-stage; little to reuse beyond model names. |
| puck-main | MIT | This is Puck, a drag-and-drop page editor for React, not a hockey or 2D engine. Not useful for the match view. |
| FHM_Narrative_Engine | none | Template approach is fine. It imitates a real podcast and its hosts and real brands; for anything shared, use fictional outlets and personalities. |
| News Article themes.txt | yours | Good template set for the presentation layer once the event table exists. |
| GM spec v2, GUI spec | yours | Sound; this audit is their Phase 0. The "Northstar" name is ignored as requested. |
| Mock-ups | yours | Useful layout direction. Some figures are wrong: the arbitration screen's QO table (5-10% brackets) and "arbiter selects one figure"; current rules are in docs/CBA_2026.md. Real player names and faces in mock-ups are fine for private design, not for anything published. |

## 7. Licensing now that this is an open-source personal project

- Pick the licence before borrowing code: GPLv3 if any openfootmanager or hockey-engine code comes in; MIT/Apache
  otherwise (football-simulator and Puck are MIT and mix with either).
- Never commit third-party data (community databases, FHM, MoneyPuck, CapWages): adapters ship, data stays local. NHL names, logos
  and marks also stay out of the repo; the shipped world is the fictional pack plus editors.

## 8. Recommended order

1. ~~Ageing/progression and an entry draft~~ done in v10 (docs/WORLD.md), with the farm/feeder world.
2. ~~Event table~~ done in v11 (`league_events`); migrations partly (schema.migrate + ensure_* on open).
3. ~~Local web UI shell: dashboard, roster, player, standings, contracts/cap, offseason screens~~ done in v12 (docs/UI.md).
   ~~AI-to-AI trades and pick trading between AI clubs~~ done in v12 (docs/TRADES.md).
   ~~Calibrated draft classes, scouting biases and philosophies, draft-floor pick trading, real-contract import,
   perceived-value salary market, 50-contract limit~~ done in v13 (docs/DRAFT.md, docs/CONTRACTS.md).
   ~~Contract valuation (surplus value) and the free-agency auction~~ done in v14 (docs/CONTRACT_ENGINE.md).
   ~~Weak-class scarcity, bargains, RFA bridge/long-term, regret, buyouts, salary dumps~~ done in v15.
   ~~Offer sheets~~ done in v16. ~~Failed sheets, arbitration box-score lens, ELC bonuses and the slide rule,
   college walkaways~~ done in v17.
4. ~~Ownership objectives and board confidence~~ done in v11 (docs/MANAGEMENT.md).
5. ~~Personality attributes, locker room, promises~~ done in v11 (first version).
6. ~~Staff~~ done in v11 (first version); scouting fog of war partly (draft estimates by scouting quality).
7. ~~Media/social presentation over events; replay 2D view~~ done in v18 (docs/MEDIA.md). A positional engine stays
   a later option.
8. ~~Era rules for OT/ties; 2026-27 84-game structure~~ done in v19 (docs/LEAGUES_AND_SCHEDULES.md, "Rule eras").
