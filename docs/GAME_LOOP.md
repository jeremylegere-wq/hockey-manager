# Game loop (hs/game)

Day-by-day play on top of an ingested pack. A save is the .db file.

    python -m hs.tools.make_example_pack packs/example_fictional
    python -c "from hs.ingest import build_db; build_db('packs/example_fictional','my.db',overwrite=True)"
    python -m hs.sim.env <moneypuck_dir> --season 2025 --out env.json      # league rates (or any env.json)
    python -m hs.game.cli my.db --env env.json -c "new NLT 7" -c "sim week" -c "standings"

Commands: new, status, sim day|week|next|season|to DATE, standings [division|conference|league], schedule, results,
roster [system], player, lines [set F1 a, b, c; D1 d, e; G g1, g2; PP1 ...; PK1 ... | swap a, b | auto]
(docs/LINES.md), tactics [<system>] (docs/TACTICS.md), waivers [<p>], claim [remove] <p> (docs/WAIVERS.md), ltir [<p>], activate <p> (docs/LTIR.md), injuries, fa, sign <p> [aav] [years], release, senddown, recall,
trade ABBR give a, 2027 2nd get c [retain a=50], tradecheck, trade3 A B; me>A: ...; A>B: ...; B>me: ..., trade3check, ask ABBR get c, picks [ABBR], block <p>, offers,
accept <id>, decline <id> (docs/TRADES.md), trades [n], cap [next], contracts, inbox, read <id> [unread], playoffs, quit.
Contract talks: negotiate <p>, propose <p> <aav> <years> [ntc], endtalks <p> (docs/NEGOTIATION.md).
Web UI over the same commands: `python -m hs.ui.server my.db --env env.json --open` (docs/UI.md).
Offseason: offseason (next phase), rights, qualify, decline, extend <p> <aav> [years], arbitrate, walkaway,
ufas, offer <p> <aav> <years>, offersheet <p> <aav> <years>, match <p>, sheets. Contracts: value <p> [aav years], regret [mine] [n]. See docs/CONTRACT_ENGINE.md.
Draft and prospects: draftboard [n], pick <p>, pickswap ABBR give 24 get 18, prospects, elc <p>, elcs, shoprights <p>, leagues.
See docs/DRAFT.md and docs/WORLD.md.
Rules: rules [preset nhl|off] (overtime, ties, points and schedule length by era).
Media: recap [game id], news [league] [n], feed [n], power. The UI's News screen and game pages add the 2D replay (docs/MEDIA.md).
Management: dashboard, history [league|<p>], board, jobs, takejob, staff, staffmarket [ROLE], hire, dismiss,
lockerroom, captain <p>, leaders <c>, <a>, <a> (docs/CAPTAINCY.md), talk <p>, respond <p> <approach>, promises [all]. See docs/MANAGEMENT.md.
Press: press, answer <id> <choice> ... (docs/PRESS.md). Live offseason (UI saves): draftnext [n] (docs/DRAFT.md), faround [all], withdraw <p>
(docs/CONTRACT_ENGINE.md).
See docs/CONTRACTS.md for the money rules and the offseason phases.
`sim` stops early when one of your players is injured or you become short at a position; `sim next` runs through
your next game. `sim season` runs to the end and plays the playoffs once.

Behaviour: injuries 0.006 per 60 min on ice, severity 1-200 days (hs/game/injuries.py). Teams need 12F/6D/2G healthy;
any team (including yours, on game days) recalls from its own system, then signs the best affordable free agent,
then (no free agents left) an uncontracted lower-league player on an emergency deal. AI teams also trim
oversize rosters and 2%/day swap in a clearly better free agent (hs/game/roster.py). Trades: AI accepts at >=105% value;
AI clubs also trade with each other up to the deadline and in the summer (docs/TRADES.md).
RNG: game seeds `rng_seed*1_000_003+game_id`; injuries, AI moves and AI trades use `Random(f"{seed}-{day}-injury|ai|trades")`, so the same
seed and commands give identical databases.

Not yet: in-game injuries.
Known weaknesses: unrated players are invisible (no ratings, no
play); goalies do not rest (no backup starts).
Gotcha: `current_date` is an SQL keyword. `SELECT current_date FROM game_state` returns the real date; use
`"current_date"` (see hs/game/state.py).
