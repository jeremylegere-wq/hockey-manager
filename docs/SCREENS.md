# Phase A: the depth of the screens (v31)

Views over data the game already keeps (`hs/ui/screens.py`, the front end in `hs/ui/static/v31.js`). Nothing here
changes a result; actions are CLI commands like everywhere else.

## The header and the Play menu
* **Schedule strip.** Your games from yesterday into next week, under the club header: the opponent (`@` for away), the
  result once played. A played game opens its box score; any other day opens that day's league schedule. It drops
  days on narrow windows and can be turned off (Settings > Display).
* **Today's event.** Beside the Continue buttons: "Game vs TBL", "Trade deadline day", "Last day of the regular
  season", or the offseason phase ("Draft day", "Free agency").
* **Play > Play Until...** (Ctrl+U). Pick a date, or one of: your fifth game from now, the first of each coming month,
  three days before the deadline, deadline day, the last day of the regular season. It plays day by day and stops
  on that date, and like Rest of season it still stops for a trade offer, the owner's office and the deadline days.
  API: `POST /api/sim {"mode": "until", "until": "YYYY-MM-DD"}`.

## New screens
| Screen | Where | What |
|---|---|---|
| Schedule by Day (`#leagueday/<date>`) | League menu, the strip | Every top-league game on a day: score, OT/SO, star of the game, box score; the day's news; previous / next day with games |
| Transactions (`#transactions/<tab>`) | Top tab, League menu | One tabbed screen: Offseason, Free agents, Upcoming free agents (contracts ending, best first), Trade block, Waivers, Offer sheets, Injured, Short list, Transaction log |
| Roster tabs | Roster | NHL roster, Whole organisation, Depth chart, Draft rights, Contracts, Injured (yours), Short list |
| Depth Chart (`#depth[/<club>]`) | Team menu, Roster | The organisation by position (C, LW, RW, D, G): NHL, then the minors, then unsigned rights, best first; value, potential, contract; future picks |
| Transaction Log (`#txnlog`) | League menu | By season, the league or your club, by kind; minor-league and European moves on request |
| Milestones (`#milestones`) | Statistics menu | Players close to career marks (games, goals, assists, points; goalies' games, wins, shutouts), and marks reached this season |
| Reports (`#reports/<kind>`) | Statistics menu | Positional rankings (top 15 per position, where your best ranks), prospect rankings (21 and under), injury report, game performances (best skater and goalie games), morale report, power rankings |
| Past Drafts (`#draftlog/<year>`) | League menu | Every pick of a draft: club, player, where he is now, NHL games, value now |
| Season Pages (`#season/<year>`) | League menu | A finished season: champion, final standings with playoff results, awards, scoring and goaltending leaders |
| Rules (`#rules`) | League menu | Season format this year and next, roster limits, the cap and contract rules |
| Team Info (`#teaminfo/<club>`) | Team menu | League, conference, division, affiliates, payroll; owner, GM, staff, captain and alternates; room, fans, media, controversy, job security |
| Notes (`#notes`) | Manager menu | Your notebook (about a player, a club or nothing) and the short list |

## Everywhere
* **Right-click a player** anywhere: View profile, Contract, Career stats, Add to / Remove from short list, Add note,
  Trade for him. His profile has the same short-list and note buttons.
* **Column tooltips** on the usual headings (GP, SV%, GAA, CF%, Value, the rating abbreviations).
* **CSV**: every panel with a table has a CSV button. The file goes to `saves/exports/` (in a browser tab it also
  downloads). API: `POST /api/export {"name", "rows"}`.
* **Search** finds staff as well as players and clubs.

## Rolling backups
Once a game week and at every new phase, the open career is copied to `saves/backups/<career>/<career> <date>
<phase>.db`; the newest few are kept (Settings > Gameplay > Saves: none, 1, 3, 5 or 10; default 3). File > Backups
lists them, makes one now, and restores one as a new save (the career it came from is left alone). A failed backup
never stops play.

## CLI
`note [add <text> | about <player> <text> | club <abbr> <text> | edit <id> <text> | del <id>]`,
`shortlist [add <player> [reason] | del <player>]`.

## Tables
notes (note_id, created, text, player_id, team_id), shortlist (player_id, added, reason). Backups keep their state in
pack_info (backup_day, backup_phase).
