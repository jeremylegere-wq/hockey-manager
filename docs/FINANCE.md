# Club finances (hs/game/finance.py, v34, phase C)

The game's own numbers: round, plausible magnitudes for a top league, not any club's books.

## The club's profile (club_finance)
Market 1-10 (a few of the league's biggest and smallest are set; others from the club's name), arena capacity
(14,500-21,500, bigger in bigger markets), arena quality (35-92), prices for three seat types, three budgets, cash
(start: $20M + $3M x market). Made for every club when a game starts, or when an older save is opened.

| Seats | Share | Reference price (x the club's base) | Price sensitivity |
|---|---|---|---|
| Lower bowl | 44% | 1.35 | 1.10 |
| Upper bowl | 50% | 0.70 | 1.35 |
| Premium and suites | 6% | 3.60 | 0.80 |
The club's base price is $95 x (0.80 + 0.04 x market).

## Attendance (every home game)
```
demand = 0.92 + 0.003 x (fan sentiment - 55) + 0.30 x (points % - 0.5) + 0.012 x (market - 5)
         + 0.0015 x (arena quality - 60) + 0.03 on a Friday to Sunday + 0.03 against a rival + noise
seat type: sold = seats x min(1, demand x (price / reference) ^ -sensitivity)
```
Playoff games are full houses at 1.6 x the price. The fans' mood (hs/game/press.py: results, the press room, the
marketing budget) therefore reaches the gate: the attendance half of defect 12. On the 2025-26 world, clubs fill 88-100%
of their buildings at the reference prices, a club whose fans have turned on it about two thirds.

## The books (finance_ledger), month by month
| Revenue | |
|---|---|
| Gate | seats sold x price, every home game |
| Concessions and merchandise | $40 a fan, x (0.9 + 0.004 x (fan sentiment - 55)) |
| Media | national $30M a year (everyone), local $6M + $2.2M x market, x (0.9 + 0.2 x fan sentiment / 100) |
| Sponsorship | $9M + $2.4M x market, x (0.85 + 0.3 x points %) |
| Revenue sharing | +$12M a year to each club in a market of 4 or under, paid by the clubs in markets of 8 and up |

| Costs | |
|---|---|
| Players | the contracts' cash (v41, "Cap and cash" below): salaries over the seven months of the regular season, signing bonuses on 1 July |
| Staff | salaries, monthly |
| Arena | $0.7M a home game and $1.1M a month |
| Travel | $0.25M a road game |
| Administration | $1.4M a month |
| Budgets | scouting $3M, development $4M, marketing $3M a year by default |

Offseason months are posted when the phases move the date on. At the end of the playoffs the season closes
(finance_season): the owner takes 15% of a profit plus 5% for each point his spending trait is under 6 (up to 50%), or
covers part of a loss (half if he spends freely, a quarter if not). You get a letter with the season's books.
A simulated 2025-26 season on the world save (from October, so five offseason months short): clubs averaged a
profit of $9M and filled 95% of their buildings; the biggest markets made $25-65M, most small markets lost $10-30M,
and the club whose fans had turned on it filled 80% and lost $34M.

## Cap and cash (v41, hs/game/ledger.py)
Every contract has two numbers a season: its **cap hit** (the average, what the cap counts) and its **cash** (salary
plus signing bonus, what the club pays). `contract_years` holds the cash, season by season; the total over a deal is
always cap hit x years.

| Structure | Cash | Used for |
|---|---|---|
| flat | the cap hit every season | short and depth deals, entry-level deals, every contract the world came with |
| front | front-loaded: a 10% step from the first season to the last | AI deals of 4+ years at $4M+ |
| bonus | front-loaded, and 40% of each season's pay ($7M+; 25% at $4-7M) is a signing bonus paid on 1 July | AI deals of 4+ years at $7M+ |

* **Contract talks**: choose the structure beside the trade protection. A player values money early, so he asks 1.5%
  less for front-loaded and 3% less for bonus-heavy (`propose <player> <aav> <years> front|bonus`). Same cap hit,
  more cash up front.
* **Cash payroll**: salaries and bonuses this season; retained salary counts the share kept; a buried one-way deal is
  paid in full though the cap counts only part; a two-way deal ($1.15M or less) in the minors pays a minor-league
  salary (12%, at least $80,000). On the bundled world a club's cash payroll runs about $3.5M over its cap payroll.
* **Buyouts** (defect 5): the share (1/3 under 26, 2/3 otherwise) is of the remaining *salary*; signing bonuses are
  still paid when due. Each season of the old term the cap carries his cap hit less the salary he no longer draws plus
  the buyout payment (for a flat deal, just the payment, as before); the extra seasons carry the payment alone. Bonus-
  heavy deals are buyout-proof, as in the real league. Cash goes in `buyout_cash`.
* **Screens**: the Contracts screen's "Salary by season" mode shows cash (a B marks seasons with a bonus) and the cash
  payroll; a player's Contract tab has "Pay by season" (cap hit, salary, signing bonus, cash).

## Your choices (Team > Finances, or the CLI)
* **Ticket prices** per seat type, 0.4x to 2.5x the reference (`tickets lower|upper|premium <price>`).
* **Budgets**, 0.25x to 3x the default (`budget scouting|development|marketing <$M a year>`). Every AI club spends
  the defaults, so at the default each is neutral:
  * scouting: your scouts' error x0.85 (triple) to x1.15 (a quarter)
  * development: your development rate x0.96 to x1.05
  * marketing: the fans' mood -0.5 to +0.5 a week
* **The arena**, in the offseason, from cash (down to -$50M): renovations at $5M a point of quality (up to 95),
  new seats at $9,000 each (up to 22,000) (`arena improve <points>`, `arena expand <seats>`).

## The board
Owners who spend 5 or less read the books at the season review: a loss over $15M costs 4 confidence, a profit over
$15M earns 2. New objectives: "Make a profit this season" (owners who spend 4 or less) and "Fill 90% (93%) of the
building on average" (markets of 3 and under, or of 4-5).

## The engine
Finances never change a game. Results reach the books (points % and the fans' mood drive the gate, sponsorship and
media), not the other way round, so the v33 calibration (docs/SIM_CALIBRATION.md) stands.

## Financial statements (v54, hs/game/accounts.py)
Team > Financial statements (and Team > Board pack); the CLI has `pnl` and `boardpack`. A pared-down version of an
accounting package's profit and loss report, built on the ledger above: nothing in it changes a game.

**The fiscal year** runs July to June (FY 2027-28 = 1 July 2027 to 30 June 2028), as the league's clubs keep their
books: the signing bonuses of 1 July open it, the playoffs close it.

**The chart of accounts** (three levels: section, group, account; the ledger's categories map onto the accounts):

| Section | Accounts |
|---|---|
| 4000 Revenue | 4110 regular-season gate, 4120 playoff gate, 4210 concessions and merchandise, 4310 national media, 4320 local media, 4410 sponsorship, 4510 revenue sharing received |
| 5000 Cost of hockey operations | 5110 player salaries, 5120 signing bonuses, 5210 hockey staff, 5310 team travel, 5410 scouting, 5420 player development |
| 6000 Operating expenses | 6110 game-day operations, 6120 building fixed costs, 6210 marketing, 6310 administration, 6410 revenue sharing paid, 6910 other |
| 6500 Depreciation | 6510 arena improvements |
| 7000 Non-operating | 7110 interest earned, 7120 interest paid |
| 8000 Owner | 8110 distributions to the owner, 8120 owner contributions |

Subtotals: hockey operations margin (revenue less hockey operations), EBITDA (less operating expenses), operating
profit (less depreciation), **net profit** (after interest), retained by the club (after the owner). The owner's money
is equity, below the line.

**New in the books:**
* Interest: on the 1st of each month every club earns 2% a year on a cash balance or pays 6% on an overdraft.
* Depreciation: renovations and new seats are capital. They leave the cash at once (as before) but reach the profit
  and loss as depreciation, written off over ten years from the month after they are paid.
* The season's close (end of the playoffs) books the fiscal year's net profit as the report has it (capital
  depreciated, the owner below the line). The owner's cut and the board's summer review read that figure. May and June
  are booked after it, so the annual report of 1 July has the whole year.

**The report's options:**
* Fiscal year and period: the full year, the year to date, a quarter (Q1 July-September ... Q4 April-June) or a month.
* Columns: the total, by month or by quarter.
* Compare with (total columns): the budget (variance, % of budget), last year (the same months; variance, change %),
  or both.
* Levels 1-3, zero lines shown or hidden, units ($M, $000, $).
* Click any line for its journal entries (each ledger posting: date, account, detail, amount).
* Every table exports to CSV, and Print gives a clean page.
* Signs: revenue positive, costs in brackets; a positive variance is always better than the comparison.
* For the month under way, the budget and last year's figures of the accounts booked game by game (the gate,
  concessions, travel, game-day operations) are prorated by days. Everything else is booked in full on the 1st.

**The budget** is drawn up when the season opens (opening night) for the whole fiscal year:
* July to September at what actually happened.
* October to June planned from the schedule (home and road games by month), today's ticket prices and fans' mood (about
  45% of home games on a Friday to Sunday), last season's form, the contracts' cash, staff salaries and the club's
  budgets.
* No playoff revenue: budgets do not assume the playoffs.
* Before opening night a provisional budget is drawn with a standard schedule, and redrawn at the opening. A save from
  before v54 draws its budget the first time it is needed.

**The board pack:**
* The year to date against the budget for revenue, hockey operations, operating expenses, EBITDA and net profit.
* The forecast: the actual so far plus the budget for the rest of the year.
* Cash, players' pay as a share of revenue, attendance and revenue per fan.
* Net profit by month against the budget (bars; cumulative lines).
* The owner (who he is and what he watches), the league's clubs year to date, the cash statement (opening cash, net
  profit, depreciation, cash from operations, arena projects, the owner, closing cash), and the reports to the board.

**The board's reviews** (your club): on 1 October, 1 January, 1 April and 1 July, the finance office reports the
quarter just ended to the board. The report comes to your inbox with the owner's reply, and how much he cares depends
on his spending trait:

| Owner spends | Net profit against the budget, year to date | Confidence |
|---|---|---|
| 4 or less | $10M under / $5M under / $5M over | -4 / -2 / +2 |
| 5-6 | $10M under / $10M over | -2 / +1 |
| 7 or more | $20M under | -1 |

The 1 July report is the annual report: no confidence change, because the summer review (docs/BOARD.md) already reads
the season's books. A forecast loss of more than $20M draws a warning from any owner who is not a free spender.

## A new arena (v57, hs/game/arena.py)
On the Finances screen ("A new arena"), or `arena quote <seats> <quality>`, `arena new <seats> <quality>`,
`arena status`.

| | |
|---|---|
| Cost | capacity x $22,000 x (0.6 + 0.4 x quality / 90): 18,000 seats at quality 90 cost $396M |
| Range | 15,000-21,000 seats; quality 70-95 |
| The owner | pays 20% + 6% x his spending trait (spending 5: 50%) as contributions; the club borrows the rest |
| Approval | offseason only. He refuses a second project, a club whose arena is already rated 80+ (renovate instead), board confidence under 45, or a share of more than $40M x his spending trait |
| Building | 24 months from the month after approval: each month a 24th of the cost leaves as capital spending, a 24th of his share arrives as his contribution, a 24th of the loan is drawn |
| Opening | at the preseason two seasons after approval: the new capacity (the seat types keep their shares) and quality; demand +8% in the first season, fading to nothing over five |
| The loan | 5% a year, repaid monthly over 25 years from the month after the opening |

In the accounts:
* The building is depreciated over 30 years (6520 new arena).
* The loan's interest is a cost (7130 arena loan interest).
* The drawdowns and repayments are financing: on the cash statement (and not revenue on the Finances screen).
* The owner's contributions are equity, below the line (8120).
* The budget plans the loan's interest.

AI clubs do not build arenas.

## Not yet
Performance bonuses, escrow, the owner's profit-taking as a
running decision, concession and parking prices, attendance on the engine's home-ice edge.
