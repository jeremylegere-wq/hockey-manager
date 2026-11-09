# The editor and bulk import/export (v40, hs/game/editor.py)

Commissioner mode
  Off by default. Turning it on (Settings, or `editor on`) marks the save as edited, for good: the save's
  achievements and GM score carry an "edited" note. With it on you can edit any player or club, and import changes
  in bulk.

Player edits (`edit_player`)
  bio: first_name, last_name, birth_date, position, shoots, nationality, height_cm, weight_kg
  ratings: any of the ratings model's columns (hs/attributes.RATING_COLS: the 42 ratings, current and potential
           ability, position and role ratings); the engine attributes are re-derived from them (ratings.set_ratings)
  potential: the development ceiling on the 1-20 scale (player_dev.potential)
  personality: professionalism, ambition, loyalty, leadership, resilience, patience, ego, role_tolerance (1-20)
  contract: cap_hit, end (the last season's start year), clause (none, NTC, NMC, MNTC:<n>)
  team: a club's abbreviation (or FA for free agency); he joins its NHL roster, or its minors with status=prospect
  career before the save (v41): career_gp, career_g, career_a, career_w, career_so, career_po_gp, career_seasons
           (docs/HISTORY.md)
Club edits (`edit_club`): name, nickname, abbr, conference, division.

Bulk export (`export_players`): one CSV row per player (bio, club, status, every rating, personality, potential,
contract), for your club, the NHL, or everyone.
Bulk import (`import_players`): a CSV with any subset of those columns. Rows are matched by player_id, or by first
name, last name and birth date; a row with no match and a name, birth date and position creates a new player (a free
agent unless it names a club). Headers are matched without case and with common aliases (CA, PA, DOB, surname...).
Preview first: what changes, what is new, and every problem with its row number; apply writes the rows that passed.

## Where
* **File > Editor...**: Players (find one, edit bio, club, status, potential, contract, clause, personality and every
  rating; Save), Clubs (name, nickname, abbreviation, conference, division), Import / Export (export your
  organisation, the NHL or everyone as CSV; import a CSV: preview, then apply).
* A player's page has an **Edit (editor)** button while commissioner mode is on.
* Console: `editor on|off`, `edit <player>: field=value ...` (e.g. `edit Suzuki: passing=15 cap_hit=8m`).

The Import / Export tab also takes the history from before the save (v41, docs/HISTORY.md): careers from the M3 player
profile export and past drafts from a CSV. Those need no commissioner mode.

Exporting works without commissioner mode; editing and importing need it. Every edit and import is written to
`editor_log` in the save.


## Commissioner tools (v47)

`hs/game/commissioner.py`; League > Commissioner; console `commish` (trade, takeover, fire, injure, heal, rule).

```
Commissioner mode: league-level powers (v47; docs/EDITOR.md "Commissioner tools").

All of these need commissioner mode (Settings, or `editor on`), which marks the save as edited for good, and none is
open to a challenge-mode career.
  trade      any two clubs swap players (and picks), with no AI approval; the cap and roster checks still apply
             unless you force it
  takeover   you become the GM of another club at once (your old club gets a new GM)
  fire       an AI club's GM or head coach goes (a new GM is named; the best head coach on the market is hired)
  injure     a player is out for a number of days; heal brings him back now
  rules      the salary cap ceiling and floor, the league minimum, the roster limits, the trade deadline (MM-DD)
Every action is logged in the editor's log.
```

Examples: `commish trade TOR 8478483 2027-2-TOR for MTL 8480018 force`, `commish takeover SEA`, `commish fire CHI coach`,
`commish injure Matthews 21`, `commish rule cap 98.5m`, `commish rule deadline 03-06`.
