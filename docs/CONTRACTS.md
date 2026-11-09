# Contracts, cap, rights and arbitration (hs/game/contracts.py, offseason.py, arbitration.py)

Rules live in `rules.json` under `"contracts"`; anything missing falls back to `CONTRACT_DEFAULTS` (2026 CBA where
confirmed, prior CBA otherwise; see docs/CBA_2026.md). `"cap_ceiling": null` switches the cap off (the legacy 2001-02
pack does this). Every number is a setting, so eras and custom leagues can change them.

## Money model
- A contract covers `start_year .. start_year+years-1`; cap hit = AAV. No signing bonuses, performance bonuses,
  two-way deals or salary-vs-cap-hit difference yet.
- Payroll = NHL roster cap hits (less shares other clubs retain) + players in the minors above the burial allowance
  (minimum + $375K) + shares this club retains on traded contracts + buyout charges.
- Market value (v13): percentile of a player's *perceived* value among rostered players ->
  `min + (13% of cap - min) * pct^3.5`, minus 10% a year past 33. Perceived value is what clubs can see: 40% ratings,
  60% NHL record over two seasons (ice time and points per game; goalies' games and save %), the same lens the AI
  trade engine uses (`MarketValues`, `hs.game.trades.Perception`). Before v13 the market priced raw ratings, so depth
  players with flattering ratings were paid like top-liners. RFAs ask 85% of market. Packs without salaries
  (MoneyPuck) get generated contracts at new-game time, scaled so no payroll exceeds 98% of the cap.
- Contract limit: 50 per organisation (`max_contracts`), counting every contract running that season except players
  19 and under who are back in junior. Signings, ELCs and AI upgrades respect it; AI clubs that must fill a roster
  spot at the limit use a one-year emergency deal.

## Valuation and the free-agency auction
See docs/CONTRACT_ENGINE.md: surplus value per contract (`value`), and opening day of free agency as a timed auction
(`ufas`, `offer` before 1 July).

## Real contracts (hs/adapters/contracts_csv.py)
Generated contracts are placeholders. To play with real ones, put them in a CSV you keep locally (copied from a cap
site's team pages, for example) and load them:

    python -m hs.adapters.contracts_csv my_contracts.csv --pack ../work_packs/mp_2025     # then rebuild the world
    python -m hs.adapters.contracts_csv my_contracts.csv --db game.db [--dry-run]          # or an existing save

Columns are matched loosely: Player (or First/Last Name), Cap Hit (or AAV), Team, Expiry ("2028-29", "2029",
"2029 UFA"), Length, Start, Type ("ELC"), Clause (any NMC/NTC sets the no-trade flag). Money can be "$7,875,000",
"7.875M" or "7.875". Players are matched by name (accents ignored), using the team to separate namesakes; ambiguous
or unknown names are listed, never guessed. `--db` replaces each matched player's current and future contracts;
`--pack` rewrites his rows in the pack's contracts.csv. Clubs that end up over the cap are listed. The source data
belongs to whoever compiled it: never commit the CSV or a pack built from it (packs/ is git-ignored).

## Roster moves now
`sign <player> [aav] [years]` (he accepts at >= 95% of his ask), `release` (buyout: 1/3 under 26, 2/3 otherwise, over
twice the remaining term; windows not enforced), `senddown` / `recall` (players stay in the organisation as status
`prospect`), `trade ... retain <player>=50` (max 50%, max 3 retained contracts, no-trade clauses block, cap checked for
both clubs). AI clubs recall from their own system before signing, sign only what fits their cap (emergency minimum
deals otherwise) and send players down instead of releasing them.

Trade value = convex rating value + 15 points per $1M a year of contract surplus (up to 3 years), so cheap
contracts and retained salary make a player worth more; overpaid ones less. Zero when the cap is off.

## Offseason (`offseason` command advances a phase)
| Phase | Date | What happens |
|---|---|---|
| rights | 25 Jun | Expiring deals classified RFA/UFA (UFA at 27 or 7 NHL seasons). AI qualifies RFAs worth it and re-signs some UFAs. You: `rights`, `qualify`, `decline`, `extend <p> <aav> [years]`. |
| free_agency | 1 Jul | Unqualified RFAs and unsigned UFAs hit the market: the opening-day auction (docs/CONTRACT_ENGINE.md), then AI clubs fill rosters from the leftovers at their dropped asks; you `fa` / `sign`. |
| arbitration | 5 Jul | Qualified RFAs accept the QO, file (if eligible) or settle on a 2-year deal. You may settle (`extend`) or `arbitrate` (club election, once per career, award >= 85% of salary). |
| awards | 1 Aug | Awards: 0.5 x comparables + 0.25 x ask + 0.25 x offer (+-4%), between offer and ask; term picked by the side that did not elect (1 year if one year from UFA). Walk-away on player-elected awards >= threshold (`walkaway`). |
| preseason | 15 Sep | Awards signed, walk-aways freed, AI fills rosters. |
| next season | | New season row, schedule with dates moved forward a year, season stats folded into history. |

Arbitration eligibility uses pro seasons (any league, games played) against age at first pro season (18-20: 4,
21: 3, 22-23: 2, 24+: 1). As far as we know NHL arbitrators may award any figure (MLB uses pick-one-side), so the
model does not force one side's number; the "Salary arbitration.txt" notes and the arbitration mock-up say otherwise.

Waivers: docs/WAIVERS.md. LTIR: docs/LTIR.md.

## Not yet
Group 6 UFAs, bonuses on standard contracts (entry-level bonuses: CONTRACT_ENGINE.md section 8),
cap floor enforcement, bidding between clubs for one free agent, morale effects of arbitration (hook: the
`arbitration` rows in `transactions`).
