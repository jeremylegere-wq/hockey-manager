# The algorithms: the mathematics behind the AIs

This page collects the formulas and constants behind everything the computer decides in Hockey Manager: how a game is
played, how players grow and get hurt, what a player is worth, how AI clubs trade, bid, draft, scout, set lines and fire
their GM, how the money works, and how the other leagues are simulated. Everything here is taken from the code; the module
that holds each piece is named at the top of its section, and its docstring is the final authority. Constants are tuned in
the code and may move between versions (this page is for v0.58).

**Notation.** Ratings $r$ are on a 1-20 scale; a z-score is $z=(r-\mu)/\sigma$. $N(\mu,\sigma)$ is a normal draw,
$\text{Poisson}(\lambda)$ a Poisson draw, $\operatorname{clip}(x,a,b)=\min(b,\max(a,x))$. Every random draw comes from a
seeded generator, so the same seed and the same decisions give the same result. Math is written in LaTeX (GitHub renders
`$...$` and `$$...$$`).

## Contents

1. [The match engine (`hs/sim/engine.py`)](#1-the-match-engine-hssimenginepy)
2. [Players: ratings, generation, development, injuries](#2-players-ratings-generation-development-injuries)
3. [What a player is worth (`hs/game/valuation.py`, `hs/game/roster.py`)](#3-what-a-player-is-worth-hsgamevaluationpy-hsgamerosterpy)
4. [The trade AI (`hs/game/trade_model.py`, `hs/game/trades.py`, `hs/game/gm_trades.py`)](#4-the-trade-ai-hsgametrade_modelpy-hsgametradespy-hsgamegm_tradespy)
5. [Contracts: free agency, talks, restricted free agents, arbitration, offer sheets](#5-contracts-free-agency-talks-restricted-free-agents-arbitration-offer-sheets)
6. [Roster, lines, tactics and roles](#6-roster-lines-tactics-and-roles)
7. [Draft, scouting and prospects](#7-draft-scouting-and-prospects)
8. [The owner, the board and jobs](#8-the-owner-the-board-and-jobs)
9. [Finance](#9-finance)
10. [People: morale, harmony, leadership, press, discipline](#10-people-morale-harmony-leadership-press-discipline)
11. [The wider world](#11-the-wider-world)

## 1. The match engine (`hs/sim/engine.py`)

Every game is played by the same seeded engine, for the AI clubs and for you. Same seed, same lines, same result.

### 1.1 Notation

A rating *r* is on a 1-20 scale. Every skill enters the engine as a z-score of true talent:

$$ z(r) = \frac{r - 10.5}{3} $$

so 3 rating points are one standard deviation. A **unit** is the skaters on the ice (five at even strength, fewer when
penalised). Bars denote the mean over a unit. *i* is the team with the puck, *j* the other.

The skill indices a player carries (means of z-scores):

| Index | Built from | Used for |
|---|---|---|
| gen | puck control, offensive awareness, passing | shot-attempt volume, who shoots |
| qual | offensive awareness, net presence | chance quality |
| fin | shot accuracy, shot power | finishing |
| sup | positioning, defensive awareness, stick checking | suppressing attempts and chance quality |
| blk | shot blocking | blocked share |
| comp | composure | penalty rate |
| pas | passing | who gets assists |
| save | goalie positioning, reflexes, glove, blocker, low-shot save | goal probability against |
| reb | rebound control | rebound probability |

### 1.2 Time

A game is 120 segments of 30 seconds. In each, both teams generate shot attempts, penalties are served and called, and
the clock moves. Segments are independent given the state (strength, score, who is on the ice).

### 1.3 Shot attempts

For team *i* in strength state *s* (even, power play, short-handed) the expected attempts in a segment are

$$ \lambda_i = a_{60}^{(s)} \,(1-\rho^{(s)})\,\frac{30}{3600}\; k_{att}\,k_{pp}^{[s=pp]} \cdot M_i $$

where a₆₀ is the real league's attempts per 60 minutes in that state (from `data/env_default.json`), ρ the share of attempts
that are rebounds (those are generated separately), k_att = 0.96 and k_pp = 0.93 are calibration constants, and the
multiplier is

$$ M_i = \bigl(1 + 0.60\,\bar{gen}_i - 0.60\,\bar{sup}_j\bigr)\cdot h_i \cdot \bigl(1 + 0.04\,\mathrm{clip}(g_j - g_i,\,-2,\,2)\bigr)\cdot c_i \cdot \tau_i \cdot \phi_i \cdot \rho_i $$

* h = 1.05 at home, 0.95 away.
* The score effect: +4% of attempts per goal behind (at most two), so leaders sit back and trailers press.
* c = 1 + 0.05 (χᵢ − χⱼ): line chemistry (0-1) of one unit against the other (even strength only).
* A two-man advantage multiplies by 1.4; being two men down by 0.7.
* A pulled goalie multiplies by 2.0. Overtime multiplies by 1.75 for 3-on-3 (the engine blends a unit's skill half-and-half
  with the whole roster's there, because three-skater units are far more spread out than the five-man units the constants were fitted to).
* τ: tactics and counters (section 7); φ: tonight's form; ρ: tactical roles (section 7.3).

The number of attempts in the segment is Poisson(λ · max(0.3, M)). The 0.60 constants are not "the effect of one player":
ratings are shrunk estimates and a five-skater average is narrow, so they are calibrated until the engine reproduces the real league's
team-to-team spread (`python -m hs.sim.validate`; `docs/SIM_CALIBRATION.md`).

### 1.4 Who shoots

A defenceman takes the shot with the league's defence share d (a third of attempts, about a sixth of goals). Within the group the
shooter is drawn with weight

$$ w_p = e^{0.55\,G_p} \cdot \text{shoot}_p \cdot \text{role}_p, \qquad G_p = gen_p + \text{night}_p $$

### 1.5 What an attempt becomes

1. **Blocked** with probability b = clip(b₀ (1 + 0.10 · mean blk of the defenders), 0.02, 0.60).
2. **Missed** with the league's missed share.
3. Otherwise a **shot on goal**, which scores with

$$ p_{goal} = \bar p_s \cdot \pi_{pos} \cdot (1 + 0.03\,qual + 0.10\,fin)\,(1 - 0.33\,save_G)\,(1 - 0.03\,\overline{sup}_{opp}), \quad p \in [0.01,\,0.60] $$

   where p̄ₛ is the league's shooting percentage in that state (a separate, higher one for rebounds), and the position factor keeps the
   state's total goals where the league put them while a defenceman scores at 0.46 of a forward's rate per attempt:

$$ \pi_{pos} = \frac{f_D^{[D]} \cdot 1^{[F]}}{d f_D + 1 - d} $$

4. A save can leave a **rebound** with probability

$$ p_{reb} = \frac{r}{1 - \bar p_s}\cdot\max(0.2,\; 1 - 0.15\,reb_G) $$

   which starts one more attempt (at the rebound shooting percentage), once.

Assists: the primary assist is awarded with the league's primary-assist rate, the secondary with its secondary rate, each to a
teammate drawn with weight e^{0.65 pas} (0.45 for a defenceman).

### 1.6 Penalties

Per segment, for a team not already two men down, the chance of a minor is

$$ \pi_{pen} = \frac{P_{game}}{2}\cdot\frac{30}{3600}\cdot\frac{k_{pen}}{1 + 0.10}\cdot \max\bigl(0.2,\;1 - 0.15\,\overline{comp}\bigr)\cdot \text{tactics}\cdot\text{roles}$$

P_game = 6.9 minors a game for both teams and k_pen = 1.015. The offender is drawn with weight $e^{-0.6\,comp}\cdot temper$ (the hot-headed
are more likely). A minor is 120 seconds, ended early by a power-play goal. With probability 0.10 an opposing minor offsets it (4-on-4).

### 1.7 Late-game behaviour

In the third period a team trailing by one pulls its goalie at its preference (default 2:00 left; 1:00 when trailing by two). The
leader then scores an empty-net goal at a Poisson rate of 0.25 a minute. A starter is relieved after a club-set number of goals
(default four).

### 1.8 Goalies, ice time, form

* The starter plays with probability 0.82 when the club has no rule; the backup 0.18 (your goalie rules replace this).
* Even-strength ice time by line (F): 0.38 / 0.31 / 0.20 / 0.11; by pair: 0.40 / 0.35 / 0.25. Power play: 0.55 / 0.30 / 0.15 for
  forwards. Short-handed: 0.30 / 0.35 / 0.25 / 0.10. A club's "ice time" preference swaps the vectors (roll four lines: 0.31 / 0.28 /
  0.24 / 0.17).
* **Tonight's form:** each skater's offence gets an independent N(0, σ) shift (σ from his hidden consistency).
* **Playoffs:** the hidden big-games rating shifts finishing (centred on the league, so it moves no totals).

### 1.9 Overtime and the shootout

Regular season: 5 minutes of 3-on-3 (attempt multiplier 1.75, shooting multiplier 1.15), then a shootout. Each club's three best
shooters (by fin + qual) go, then sudden death:

$$ p_{shoot} = 0.33\,\bigl(1 + 0.5\,(0.03\,qual + 0.10\,fin)\bigr)\,(1 - 0.33\,save_G),\quad p \in [0.05,\,0.8] $$

Playoffs: full-strength 20-minute sudden-death periods until someone scores.

### 1.10 Why these numbers

The engine is checked against the league environment (`docs/SIM_CALIBRATION.md`): 2.88 goals a team-game, 27.6 shots, a 0.896 save
percentage, 6.9 penalties a game, a goal-differential spread between clubs of about 0.6 a game. A season in the bundled world gives
5.70 goals a game, 19.6% of games past regulation and a 0.65 spread.

## 2. Players: ratings, generation, development, injuries

### 2.1 Two layers of ratings (`hs/attributes.py`, `hs/game/ratings.py`)

A player has **ratings** (42 attributes 1-20, current and potential ability 1-200, six position ratings, two role ratings),
which you see and edit, and **engine attributes** (40 composites), which the engine reads. Each engine attribute is a fixed
weighted mean of ratings, for example

$$ \text{puck control} = 0.6\,\text{stickhandling} + 0.4\,\text{deking},\qquad \text{offensive awareness} = 0.4\,\text{movement} + 0.35\,\text{anticipation} + 0.25\,\text{creativity} $$

**Putting the composites on the engine's scale.** At import an affine map $x' = a + b\,x$ is fitted per attribute so that the dressed
top-league players have the mean and spread the engine was calibrated on. **Level anchored on ability:** the composites keep the
shape of a player's ratings and are shifted together so his overall matches what his current ability stands for. Ability maps onto the
calibrated spread (skaters 10.49 ± 0.86, goalies 10.51 ± 0.66). Without this step the overall correlated 0.65 with ability; with it, 0.99.

**Overall.** A player's *overall* is the mean of seven skater composites (offensive awareness, passing, puck control, shot accuracy,
positioning, defensive awareness, hitting) or six goalie composites (positioning, reflexes, glove, blocker, low-shot save, rebound
control). *Value* (0-100) is

$$ V = \frac{\bar{o} - 1}{19}\cdot 100 \cdot f_{age},\qquad f_{age} = \begin{cases} 1 - 0.01\,(21 - a) & a < 21\\ 1 & 21 \le a \le 33\\ 1 - 0.02\,(a - 33) & a > 33 \end{cases} $$

### 2.2 Generating a player (`hs/worldgen.py`)

A generated player draws `current ~ N(league mean + offsets, 0.6)` for his overall; attributes are spread around it with
archetype offsets (sniper, playmaker, two-way, power forward, offensive and defensive defence), physical ratings a little lower
for teenagers. His **development profile**:

* Growth left by age: $g(a)$ = 2.2, 1.9, 1.6, 1.3, 1.0, 0.7, 0.45, 0.28, 0.15, 0.05 for ages 15-24, then 0.
* Potential: $P = c + \max\bigl(0,\; N(g,\; 0.15 + 0.35\,g)\bigr) + B$, where with probability 0.07 (when $g > 0.2$) a **late bloomer**
  bonus $B \sim \text{Exp}(\text{mean } 1.1)$ is added. Younger players have more uncertain ceilings.
* Peak age $\sim N(24.6, 0.8)$ clipped to [23, 26.5]; decline age $\sim N(30, 1.5)$ clipped to [27, 34]; goalies two years later.
* Growth rate $\sim N(1, 0.15)$ in [0.7, 1.3]; decline rate $\sim N(1, 0.18)$ in [0.7, 1.4].

### 2.3 The yearly change in overall

For age $a$ (on 15 September), current $c$, profile $(P, a_{peak}, a_{dec}, k_g, k_d)$:

$$ \Delta = \begin{cases}
(P - c)\cdot r(a)\cdot k_g + N(0,\,0.08) & a \le a_{peak},\quad r = 0.30\,(\le 18),\,0.36\,(\le 21),\,0.42\,(\le 23),\,0.6\\[2pt]
N(0,\,0.07) & a_{peak} < a < a_{dec}\\[2pt]
-\,k_d\,\bigl(0.10 + 0.025\,(a - a_{dec})\bigr) + N(0,\,0.05) & a_{dec} \le a < 35\\[2pt]
-\,k_d\,\bigl(0.28 + 0.08\,(a - 35)\bigr) + N(0,\,0.05) & a \ge 35
\end{cases} $$

The change is spread across attributes with weights normalised so the overall moves by Δ on average: when growing, mental ratings
×1.15 (age ≥ 22) and physical ×0.9 (age ≥ 24); when declining, physical ×1.4, mental ×0.5. A **training focus** gives the focus
attributes 1.6× their share of a gain and 0.6× of a loss. Rounding is stochastic ($\lfloor v\rfloor + [U < v - \lfloor v\rfloor]$).

### 2.4 Development through the season (`hs/game/development.py`)

40% of a growing player's expected year arrives in six monthly steps (1 November to 1 April); the rest in the summer. Decline stays
in the summer. The growth is multiplied by the product of factors, clamped to [0.55, 1.45], times a calibration constant 1.08:

| Factor | Value |
|---|---|
| ice time (NHL, 23 and under) | his ice time a game against what a regular at his position gets, and how many games he dressed for; scratched kids stall |
| level of play | challenged (−1.5 to +1.2 of the league mean) 1.04; too good for the league 0.90; overmatched 0.88 |
| character | $1 + 0.015\,(\text{professionalism} - 10) + 0.008\,(\text{ambition} - 10)$ |
| mentor (27+, professionalism 12+, at most two pupils) | 1.10, or 1.14 if his professionalism is 16+; unassigned pupil 1.03 from a good older teammate |
| training intensity | light 0.92, normal 1.0, hard 1.08 |
| time injured | $1 - 0.8\cdot(\text{days out} / \text{days in period})$ |
| staff, coachability | development coach multiplier; hidden coachability $0.95 + 0.01\,r$ |

Decline is slowed by professionalism ($\times(1 - 0.02\,(p - 10))$, 0.8-1.2) and made worse by hard training (×1.05). A mentor can
pass on professionalism (+1, 12% a month, never above his own); a mentor with ego 15+ may pass on a bad habit (−1, 6%).

### 2.5 Hidden attributes (`hs/game/hidden.py`)

Seven attributes nobody sees, generated once per player, centred on 10.5 so they never move league totals:

| Attribute | Effect |
|---|---|
| consistency | night-to-night swing of his offence: sd 0.30 (least consistent) to 0.06 |
| big games | playoff finishing ±0.10 sd |
| injury proneness | injury risk × $1 + 0.04\,(r - 10.5)$ (×0.62 at 1, ×1.38 at 20) |
| temperament | share of penalties taken: weight × $1 + 0.06\,(10.5 - r)$ |
| sportsmanship | with temperament and ego, who clashes in the room |
| coachability | development × $0.95 + 0.01\,r$ |
| greed | contract asks × $1 + 0.006\,(r - 10)$ (±6%) |

### 2.6 Injuries (`hs/game/injuries.py`)

After each game day, each player who played $t$ seconds is injured with probability

$$ p = 0.006\cdot\frac{t}{3600}\cdot f_{prone}\cdot f_{training} $$

(about one injury per 170 player-games at 20 minutes). Severity draws from the cumulative table 45% 1-3 days, 30% 4-10, 15% 11-30, 8%
31-90, 2% 91-200 days (uniform within a band), scaled by the club's medical staff multiplier.

## 3. What a player is worth (`hs/game/valuation.py`, `hs/game/roster.py`)

Contract talks, free agency, trades, regret and the AI's ideas of a "bargain" all rest on one valuation. It follows the public
*surplus value* method: project a player's wins above replacement, price a win at what the league pays, and compare with the cap hit.

### 3.1 Perceived level

Clubs do not see a player's true rating. The **perceived value** blends his ratings with his NHL record in the last two seasons (10+
games):

$$ \tilde V = (1 - 0.6)\,V_{ratings} + 0.6\,\bigl(\mu_g + \sigma_g\, z_{usage}\bigr),\quad z_{usage} = \frac{\tfrac12\,[z(\text{ice time}) + z(\text{points per game})]}{\sigma_z} $$

(goalies: games and save percentage). The percentile scores are taken within the position group (F, D, G). So a player used a lot and
producing looks better than his ratings say, and a hidden development profile is invisible to every club.

### 3.2 Wins above replacement

$$ \text{WAR}(o) = k\,\max(0,\; o - 9.9)^{1.5} $$

where *o* is the overall, 9.9 is replacement level (the best player a club can call up or sign for the minimum), and the scale *k* is
refitted every day so the league's rostered players sum to **15 WAR per club**.

### 3.3 The cost of a win

$$ c_w = \frac{0.95\,\cdot\,\text{cap}\cdot n_{clubs} - \text{min salary}\cdot N_{rostered}}{15\, n_{clubs}} $$

about $5.3M at a $104M cap, growing 5% a year. The market value of one season is

$$ \text{MV} = \text{min salary} + \text{WAR}\cdot c_w\cdot\begin{cases}1 & \text{skater}\\0.65 & \text{goalie}\end{cases} $$

### 3.4 Ageing

The market expects a typical player to change each year by

| age | 18-19 | 20 | 21 | 22 | 23 | 24 | 25-28 | 29 | 30 | 31 | 32 | 33 | 34 | 35 | 36 | 37 | 38 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Δ overall | +0.35 | +0.33 | +0.25 | +0.17 | +0.10 | +0.04 | 0 | −0.03 | −0.08 | −0.12 | −0.15 | −0.18 | −0.21 | −0.28 | −0.36 | −0.44 | −0.52 |

(goalies use age − 2). Beyond 38 it falls a further 0.08 a year.

### 3.5 Fair AAV, surplus, grade

For a deal of *T* seasons the **fair AAV** is the average market value of the projected seasons, then bent by the **star ceiling**:

$$ \text{fair} = \begin{cases}\text{AAV} & \text{AAV} \le s\\ s + 0.25\,(\text{AAV} - s) & \text{AAV} > s\end{cases},\quad s = 9\%\ \text{of the cap}$$

capped at the league maximum (and goalies at 11% of the cap), floored at the minimum salary. This reproduces the NHL's shape: the best
players earn 12-13% of the cap, nowhere near their full value. Surplus is the sum over the term of (market value − cap hit), graded

| A | B | C | D | F |
|---|---|---|---|---|
| ≥ +$10M | ≥ +$3M | within $3M | down to −$10M | worse (albatross) |

**Risk.** 200 simulated futures draw a starting error $N(0, 0.18)$ and a yearly random walk $N(0, 0.12)$ around the age curve and report
the share of futures in which the deal ends up positive.

### 3.6 The player value and the salary market (`hs/game/roster.py`, `hs/game/contracts.py`)

Before the surplus model, a player's asking AAV was his percentile $q$ among rostered players by value:

$$ \text{AAV} = m + (0.13\,\text{cap} - m)\,q^{3.5} $$

(average near 3.5% of the cap, top near 13%).

### 3.7 Trade value

The currency the trade AI compares. For a player of value *V* (0-100, 50 = league average), with replacement level 42:

$$ T(V) = 30\,\Bigl(\frac{\max(V - 42,\,0)}{50 - 42}\Bigr)^{3.3} $$

on the same scale as draft picks (a mid first-round pick 85, a mid second 29). An average player is worth 30 (a 2nd), the 75th percentile
about 85, the 90th about 190, the best about 550; a fringe NHLer about 5. Goalie values are stretched about the mean by 1.0 (off in v39).
Young players count part of the gap to their potential *P* (as a value):

$$ V' = V + (P' - V)\cdot 0.65\cdot C(a),\qquad C = \max\Bigl(0.2,\;1 - \bigl(\tfrac{a-18}{6}\bigr)^{1.5}\cdot 2\cdot\tfrac{P'-V}{P'}\Bigr)$$

for age ≤ 23 (skaters): the share fades as the development window burns without progress. Players still in the minors are discounted a
further 0.85, with a position premium for young prospects (C 1.10, D 1.05, W 1.00, G 0.80). A contract adds

$$ \Delta_{contract} = 3\cdot\frac{\text{market AAV} - \text{cap cost after retention}}{\$1M}\cdot\min(3,\ \text{years left}) $$

trade-value points (positive when he is paid below market).

## 4. The trade AI (`hs/game/trade_model.py`, `hs/game/trades.py`, `hs/game/gm_trades.py`)

Both AI-to-AI trades and the offers an AI makes to you use one model, so your side and theirs obey the same laws.

### 4.1 Competitive state

$$ S = 1 - \frac{\text{rank} - 1}{n - 1} $$

rank by points percentage once a club has played 10 games (paper strength before). S = 0 is a hard rebuild, S = 1 all-in. For
posture, clubs ranked in the top 31% are *contenders*, the bottom 37.5% *sellers* (neither before 20 games), the rest in the middle.

### 4.2 Need

For each club and position group (F, D, G), with depth slots F 12, D 6, G 2:

$$ D_r = \frac{\sum_i w_i \max(0,\ t_i - c_i)}{\sum_i w_i\,\sigma},\qquad D_p = \max\Bigl(0,\ 1 - \frac{\sum_j \rho_j \max(0,(P_j - 10)/5)}{\text{target}}\Bigr) $$

* $t_i$ is the 65th percentile of every club's *i*-th best player at the group (a playoff club's depth), $c_i$ the club's own, $\sigma$ the group's
  spread. Slot weights are 1.0 / 0.75 / 0.5 / 0.25 by forward line (D 1.0 / 0.7 / 0.4, G 1.0 / 0.3). Players out 3+ weeks do not count.
* $\rho_j$ is a prospect's readiness (0.9 at 22+, 0.7 at 21, 0.5 at 20, 0.3 younger); targets F 2.5, D 1.5, G 0.8.
* Urgency $U$: 0.25 for each top-lineup player out three weeks or more (0.4 in the deadline rush).

$$ N = 100\cdot\mathrm{clamp}\bigl(\alpha D_r + 0.3\,\beta D_p + U,\ 0,\ 1\bigr),\quad \alpha = 0.2 + 0.8S,\ \ \beta = 1 - 0.8S $$

Contenders chase today's gaps; rebuilders care about the pipeline.

### 4.3 Friction: how hard a player is to move

With $q = (V - \bar V_g)/\sigma_g$ among NHL regulars of his group:

$$ F = \min\Bigl(100,\ 30\,q^2 \cdot \bigl(1 + 0.12\,(\text{years left} - 1)\bigr)\cdot\bigl(0.8 + 2\cdot\text{cap share}\bigr)\cdot \text{modifiers}\Bigr) + \text{clause} + \text{role}$$

modifiers: ×0.7 on an expiring deal in season (a rental); ×1.25 if the holder is a contender, ×0.7 a seller; ×0.6 in the offseason;
×0.3 if he asked out. Additions: +40 no-movement, +30 no-trade, +10 modified; +15 captain, +8 alternate. A club **pursues** a player
only if its need at the position is at least his friction, $N \ge F$, and the seller demands $1.05 + F/100$ of his value back.

### 4.4 Draft pick value

$$ V(p) = 13960\,(p + 14)^{-1.5},\qquad p = 32\,(\text{round} - 1) + \text{slot} $$

1st overall 240, 16th 85, 32nd 45, mid second 29, mid third 15, mid fourth 10, seventh 4. The offset power law fixes the plain
$p^{-\gamma}$ curve, which is too flat at the bottom and unbounded at the top. This year's slot follows the standings; later drafts regress
to mid-round (half after one year, three quarters after two), are discounted 15% a year, and a weak club's future first carries up to a
30% lottery premium. Sellers weight picks ×1.2, middle ×1.0, contenders ×0.85 (×0.95 more for later drafts).

### 4.5 Packages and retention

Pieces a club receives are summed best first at 100%, 80%, 64%, …(each 0.8 of the last), so four nickels do not buy a quarter.
Retained salary is an asset the retaining club *gives*: 10 points per $1M of cap it keeps paying times $1 + (15 - \text{room in } \$M)/5$, bounded
1-3 — clubs with room broker cap cheaply, clubs near the ceiling barely at all.

### 4.6 Acceptance

An AI club accepts when what it receives, in its own weights, is at least **105%** of what it gives (130% when giving a core player: a top
three skater or its starting goalie, which a contender will not sell at all). Weights: a seller values players ≤ 23 at ×1.2 and 30+ at
×0.85; a contender values prospects ≤ 22 at ×0.8; a player that fills a need counts ×1.2. A player who asked out goes for 75% of his value.
A newly signed player cannot be traded for 30 days (a free agent: a year).

### 4.7 How often AI clubs trade, and with whom

The league as a whole makes trade *attempts* at an expected rate per day of 0.33 early in the season, 0.55 mid-season, 5 a day in the
deadline rush (the last 14 days) and 75 on deadline day (stochastic rounding: $\lfloor\lambda\rfloor$ plus one with probability the fractional part). The
summer runs 60 attempts on draft day and 55 as free agency opens. Each attempt is one of four kinds, in these shares:

| Phase | minor (farm) | depth | roster | rental | pick swap |
|---|---|---|---|---|---|
| early | 0.52 | 0.23 | 0.25 | | |
| mid | 0.47 | 0.23 | 0.30 | | |
| rush, deadline day | 0.20 | 0.15 | 0.30 | 0.35 | |
| draft day | 0.10 | 0.15 | 0.50 | | 0.25 |
| free agency | 0.25 | 0.25 | 0.50 | | |

A club makes at most 4 in-season roster trades and 9 deals in a season. A roster attempt tries a like-for-like swap first (25%), may become a
three-team deal (4%), and a club within $2M of the cap will pay a sweetener to dump a contract (30% in season). A *star* (the league's top 15% by value) moves only if he asked out or his club is a seller, with probability 0.2 per try (0.45 in the rush), at most four a season league-wide.

**Offers to you.** On an in-season day an AI club looks at your roster with probability 3% (8% in the rush, three times as often while you
have players on the block): a club whose weakest group one of your players would improve builds the cheapest package it can, with the
same search, and calls. **Counter-offers** ("what would it take") name the cheapest set of up to three of your assets by your own valuation.
**Shopping** a player: a club calls only if his friction × 0.7 is at most its need; its opening offer is 70-80% of his value at need under 40,
80-92% at 40-70, 92-102% at 70+; calls arrive over 1-10 days, at most five.

## 5. Contracts: free agency, talks, restricted free agents, arbitration, offer sheets

### 5.1 Free agency is a timed auction (`hs/game/free_agency.py`)

The market opens at noon on 1 July and runs in rounds at hours 0, 0.5, 1, 2, 4, 8, 24, 48, 96, 168. Players are sorted into **tiers** by perceived
overall: Tier 1 ≥ 11.3 (stars), Tier 2 ≥ 10.5 (middle six, top four), Tier 3 ≥ 9.6 (depth). Everything is anchored on the fair AAV of section 3
for the term he wants.

**What a player asks, at hour *t*:**

$$ \text{ask}(t) = \text{fair}\cdot\Bigl(0.5 + (\text{peak}_{tier} - 0.5)\,e^{-t/10}\Bigr),\qquad \text{peak} = 1.20,\ 1.10,\ 1.00 $$

so a Tier 1 player asks 120% of fair at noon and everybody left is near half a day later. Asks and bids never exceed 125% of fair.

**What a club bids.** Each round, every AI club with cap room, owner budget and a contract slot picks the free agent who most improves its top
lineup (6 F, 4 D, 1 G), measured as the gain over the weakest of the slots:

$$ \text{gain} = o_{player} - o_{\text{weakest top-lineup player at the group}},$$

and offers

$$ \text{offer}(t) = \min\Bigl(\text{fair}\,\bigl(1 + \pi\,e^{-t/6}\bigr),\ \ \text{ask}(t)\,\bigl(1 + 0.15\,e^{-t/6}\bigr)\Bigr),\quad \pi \in \begin{cases}[0.10, 0.25] & \text{Tier 1}\\ [0, 0.12] & \text{Tier 2}\end{cases} $$

with π drawn per club and tier, and never above the club's cap room less the money it keeps back for its own qualified RFAs and for filling the
roster. A player takes the best offer when it beats his current ask, otherwise he waits.

**Scarcity.** The market's heat is the ratio of money to talent,

$$ s = \frac{\sum_{clubs}\text{spendable room}}{\sum_{\text{Tier 1-2}}\text{fair}\times\text{years}},\qquad k = \mathrm{clamp}\Bigl(\frac{s/0.27 - 1}{0.15},\ 0,\ 1\Bigr) $$

A hot market (k near 1) adds up to two years to a term, multiplies the peak ask by $(1 + 0.25\,k)$, and adds $0.20\,k$ to every club's premium, but nothing goes above 125% of fair. Clubs keep room to fill a 23-man roster at the minimum.

**Panic.** A club whose Tier 1-2 target signs elsewhere in the first hour, with $5M+ of room, goes for the next best at the position for 90 minutes:
+1 year, +$1.5M and a no-move clause.

**Terms.** Tier 1 aged ≤ 29 wants the maximum, 30-31 five years, 32+ three. Tier 2 five years to 28, four to 31, three, two at 34+. Tier 3 two years
(one after 30). Players weigh security more with age: the utility of a deal is

$$ u = \text{AAV}\times \text{years}^{\,s},\qquad s = 0.15\ (<30),\ 0.30\ (30\text{-}32),\ 0.40\ (33+) $$

Veterans 32+ take 10% less utility from a non-contender. Players unsigned after the auction keep their last ask and sign later as one to two year
"prove-it" deals.

### 5.2 Contract talks with an agent (`hs/game/negotiation.py`)

Every player has an agent with a style:

| Style | Opens above his floor | Gives up of the gap each round | Patience (rounds) |
|---|---|---|---|
| shark | 28% | 25% | 3 |
| pro | 16% | 40% | 4 |
| friendly | 8% | 55% | 5 |

Ego and ambition raise the opening; patience adds a round; loyalty (with trust in you) is a hometown discount. The **floor** is the least he will
take for a term and clause, never below what the signing rules accept, and it is built from several terms:

* **Term.** Each year away from his preferred length costs 3.5%.
* **Clause.** Veterans 27+ want trade protection (level 1 modified list, 2 no-trade, 3 no-movement). Each level granted up to what he wants takes 2.5% off,
  1% a level beyond, and each level short costs 2%. A 10-team list in the last two years counts half a level.
* **Pitches** (once each): home (his country), friends in the room, winning. A true pitch he cares about takes 1-3% off; a false one costs patience.
* **Winning.** An ambitious player (7+) charges a bottom-eight club 5% more and gives a top-eight club 3%.
* **Trust.** Below 35 trust he asks 10% more; 65+ with loyalty 7+ gives 4%.

**A round.**

| Your offer | Result |
|---|---|
| at least his ask for the term | signed now |
| within 3% of his ask and at or above the floor | signed ("let's get it done") |
| under 80% of his floor | an insult: −2 patience, his mood sours, he does not move |
| under 92% of the floor | costs a round; he moves half as far |
| otherwise | costs a round; he gives his style's share of the gap, but never more than 2.5% / 3.5% / 5% of his demand in one round |

When patience runs out, talks break off for 14 days (your own player loses 5 trust in you).

### 5.3 Restricted free agents (`hs/game/rfa.py`)

* **No arbitration rights.** A two-year bridge at $\max(\text{QO},\ 0.8\times\text{fair}_{2y})$.
* **Arbitration rights, ≤ 25, perceived 10.5+, club can afford it.** Buy his UFA years now, up to the re-signing maximum:

$$ \text{AAV} = \frac{(\text{RFA years})\cdot 0.85\,\text{fair} + (\text{UFA years})\cdot 1.10\,\text{fair}}{\text{total years}} $$

* **Overpaid RFAs** (qualifying offer ≥ his ask). A club offers 2-6 years and he accepts when the utility beats a year at the QO,
  $\text{AAV}\times\text{years}^{0.15}$ (so a five-year deal at about 79% of the QO is worth as much to him as the QO for one year); the club pays at most 110%
  of fair and picks the term that saves it most. Otherwise, if the QO is $1.5M+, he is eligible, and the QO is 5%+ over his ask, the club elects arbitration
  (the award can be as low as 85% of his salary); otherwise he signs the QO.

### 5.4 Arbitration (`hs/game/arbitration.py`)

The arbitrator sees mostly the box score:

$$ V_{hear} = 0.75\,\bigl[\,0.6\,B_{platform} + 0.4\,B_{prior}\,\bigr] + 0.25\,V_{ratings} $$

with the box score *B* mapped to the value scale by percentile in his position group (skaters: 0.7 points per game + 0.3 goals per game; goalies: 0.6 save
percentage + 0.4 wins per game). Comparable players are rostered players with hearing value within a band (market value if too few). Then

$$ \text{ask} = 1.12\,\max(M, C),\qquad \text{offer} = 0.88\,\min(M, C)\ \ (\ge \text{QO}),\qquad \text{award} = 0.5\,C + 0.25\,\text{ask} + 0.25\,\text{offer} \pm 4\% $$

where *M* is market value and *C* the median cap hit of the comparables. The award is kept between offer and ask. Term: one or two years, chosen by the
side that did not elect. A club may walk away from a player-elected award above the walk-away threshold; he then becomes a UFA. This is why
point-producers win big awards and quiet play-drivers do not.

### 5.5 Offer sheets (`hs/game/offer_sheets.py`)

Compensation by AAV (total ÷ min(years, 5), thresholds scaled by cap / $95.5M): ≤ $1.56M none; $2.36M a 3rd; $4.73M a 2nd; $7.09M a 1st and a 3rd; $9.46M a
1st, 2nd and 3rd; $11.82M two 1sts, a 2nd and a 3rd; above that four 1sts.

The AI's model of whether the player's club will match: affordability (cannot fit the AAV after its other pending RFAs → almost cannot match), compensation delta
(matching is worth less than the picks → lets him go), overpay premium, a 20% owner-spite matching rate for homegrown top-lineup players, **stars (perceived
11.3+) matched 95% of the time if affordable**, and an owner up to $4M short who clears room. The sheeting GM's estimate of the owner has error σ = 0.2. It tries a
*cap-leverage* sheet and a *tier-jump* sheet and makes the better by expected value

$$ E = P(\text{not matched})\cdot\bigl(\text{surplus} + 0.15\cdot\text{years}\ \text{[a top-lineup hole filled]} - \text{picks' expected surplus}\bigr) $$

with a first worth $6M, a second $2M, a third $0.8M, if $E > 0$ and $P \ge 0.4$. About one in eight clubs looks each summer, and at most two sheets are made.

### 5.6 Regret, buyouts, dumps (`hs/game/regret.py`)

Every signed contract is valued at signing; later the same model is run on the seasons left. 

$$ \text{regret} = \text{expected worth of remaining seasons at signing} - \text{worth now},\qquad \text{regret index} = \frac{\text{cap hit}}{\text{this season's worth}}\times\text{seasons left}\times 1.15^{\,\text{years past 30}} $$

A contract a year or more in, worth under 75% of what was expected and graded D or F, is *untradeable* without a sweetener. AI clubs, in the June buyout window,
**buy out** a contract worth under half its cap hit on a player outside the top lineup, signed before 35, when it saves cap this season and the club has under $5M of
room (or the deal is $6M+ under water), one a summer. **Salary dumps** (surplus below −$8M on a club with under $10M of room) go to a club with lots of room and no
playoff ambitions with a sweetener: a 2nd for up to $6M of negative value, a 1st up to $18M, a 1st and a 2nd up to $30M.

### 5.7 Clauses and entry-level contracts

**Trade protection** (`hs/game/clauses.py`) goes only to players who could have been UFAs (26+) on deals of 2+ years. The chance rises with the cap hit from 15% at
$2.5M to 50% at $10M, +10% for five years or more. A player with an NTC or NMC waives only if

$$ \text{gain} = (S_{to} - S_{from}) + (\text{role}_{to} - \text{role}_{from}) \ge 0.5 $$

where role is 1.0 / 0.75 / 0.5 / 0.25 by line or pair; loyal players (15+) need 0.2 more, veterans 33+ going to a contender 0.15 less, a player who asked out needs none.

**Entry-level contracts** (`hs/game/elc.py`). The chance of the maximum signing bonus is 0.95 / 0.5 for a top-10 pick with / without leverage, 0.25 / 0.1 for picks 11-32,
0.02 later. A college senior refuses to sign with probability

$$ P = \frac{1}{1 + e^{-(b_0 + b_1\,\text{congestion} + b_2\,\text{pipeline} - b_3\,\text{slot value} - b_4\,\text{stability} + b_5\,\text{leverage})}} $$

(congestion: better NHLers at his position under contract two more seasons; pipeline: the club's prospects 23 and under at his position against what it wants; stability: the
board's confidence). A 18-19 year old who plays under 10 NHL games does not use up the ELC year: it slides, at most twice.

## 6. Roster, lines, tactics and roles

Source: `hs/game/roster.py`, `lineup.py`, `lineups.py`, `waivers.py`, `ltir.py`, `tactics.py`, `troles.py`, `chemistry.py`.

### 6.1 Promotion and demotion (AI clubs)

Let $v_i$ be a player's value (section 3). For each position group $g \in \{F, D, G\}$ the club looks at its best
prospect $c$ in the system and its weakest healthy NHL player $w$ in the group. It swaps them (up to three swaps per
group) when

$$v_c \ge v_w + m_c, \qquad m_c = \begin{cases} -2.5 & \text{age} \le 22 \text{ and potential} \ge 10.6 \\ +2.0 & \text{otherwise} \end{cases}$$

so a clearly better prospect gets the job (margin 2.0 value points), and a young high-ceiling one gets it even when he is
a little worse (clubs make room for players they expect to grow).

Daily upkeep (`ai_manage`): fill positional needs, send down extras while over the roster limit (from the group with a
surplus first), and with probability $p = $ `UPGRADE_PROB` a day sign the best free agent if he beats the weakest healthy
player in his group by `UPGRADE_MARGIN` and the club has cap room and a contract slot.

### 6.2 Waivers and long-term injured reserve

Exemption is a table lookup on age on 15 September of the first contract year (skaters 5 seasons or 160 games at 18, down
to 1 season at 25+; goalies 6 or 80 at 18, down to 1 at 25+). A claim is made by an AI club when the player would improve
its weakest position group's depth, it has cap room and a contract slot, with probability $\tfrac12$. Claim order is by
points percentage, lowest first.

LTIR: a player is eligible if he will miss at least 10 games and 24 days. With $C$ the cap, $S_0$ the club's cap space on
the day the first player goes on LTIR, and $R = \sum$ cap hits on LTIR:

$$\text{limit} = C - S_0 \;(\text{or payroll if under the cap}), \qquad \text{ceiling} = \text{limit} + R$$

A club can spend up to the ceiling. To activate a player the club must be compliant without his relief; an AI club sends
players down (at most three moves) until it is.

### 6.3 Lines and ice time

The depth chart is by ice time last season, then ratings. Ice time shares at even strength:

| Unit | Share |
|---|---|
| Forward lines F1 / F2 / F3 / F4 | 38% / 31% / 20% / 11% |
| Defence pairs D1 / D2 / D3 | 40% / 35% / 25% |
| First power-play and penalty-kill unit | 65% of special-teams time |
| Starting goalie | 82% of starts (rule-driven with lineups on) |

A priority-list lineup fills each slot with the first healthy unused player on the list (C1, C2, ... then wings by line,
then pairs); the power play takes the first ten dressed players on its list (two units of five), the penalty kill the
first eight (two of four). A list that runs out is filled with the best remaining player at the position.

### 6.4 Tactics

Twelve settings, each with 3-4 options. An option has effects on multipliers $\mu_k$ for attempts, quality, penalties and
the like (`att, qual, allow_att, allow_qual, pen, pp_att, pp_qual, pk_allow_att, pk_allow_qual, sh_att`). The good part of an
option is scaled by *execution*, the cost is not:

$$\text{execution} = \operatorname{clip}\big(1 + 0.3\,f + 0.04\,(\text{coaching} - 10) + 0.15\,[\text{style suits}],\; 0.3,\, 1.6\big)$$

$$f = \frac{1}{\sigma}\Big(\overline{a}_{\text{top 18 skaters}} - \mu_{\text{league}}\Big) - \overline{f}_{\text{club, all option sets}}$$

where the last term removes the club's own average over all attribute sets, so fit measures the *shape* of a roster, not its
quality. Each multiplier is divided by its league-wide mean ($\mu_k \leftarrow \mu_k / \bar\mu_k$), so the mix of choices
never moves total scoring. Counters (stretch breakout beats an aggressive forecheck, umbrella beats a box, and so on) are
small per-game adjustments of the attacker's attempts and quality against the defender's choice, and roughly cancel.

Five team systems are presets of the six even-strength settings.

### 6.5 Tactical roles

For a role $r$ and player $i$ at his position, with $\bar a_{i,r}$ the average of his ratings in the role's attributes, and
$\mu, \sigma$ the mean and standard deviation of NHL players at the position:

$$\text{fit}_{i,r} = \operatorname{clip}\!\Big(50 + 15\,\frac{\bar a_{i,r} - \mu}{\sigma},\, 0, 100\Big), \qquad
\text{execution} = \operatorname{clip}\!\Big(0.2 + \frac{\text{fit}}{62.5},\, 0.2, 1.8\Big)$$

Fit 50 gives execution 1.0 (the role breaks even), fit 75 gives 1.4. Each role has an upside scaled by execution and a cost
that is not:

| Role | Upside (x execution) | Cost |
|---|---|---|
| Agitator | opponents' penalty rate +16% | his unit's penalties +16% |
| Shadow | their top line: attempts -8%, quality -4% | his unit's attempts -4% |
| Net-front presence | quality +4%, rebounds +15% | attempts -3%, penalties +5% |
| Trigger man | PP quality +6%, shot share x1.8 | PP attempts -5% |
| Forechecker | attempts +5% | penalties +12%, attempts allowed +2% |
| Enforcer | opponents' penalty rate +8%, their quality -2% | attempts -3%, more penalties |
| Penalty killer | SH attempts allowed -6%, quality -2% | even-strength attempts -2% |
| Shutdown D | attempts allowed -5% | attempts -5% |
| Puck mover | attempts +5% | attempts allowed +5% |
| PP quarterback | PP attempts +7% | PP quality -6% |
| Crease-clearer | quality allowed -4%, rebounds allowed -20% | penalties +12%, attempts allowed +3% |
| Rover | quality +5% | quality allowed +5% |

"Suggest" and the AI assign each role to the best-fitting dressed player who clears fit 60. As with tactics, effects are
divided by their league mean so roles move results between clubs, not the league's scoring.

### 6.6 Line chemistry

For each pair of linemates (the three pairs in a forward trio, each defence pair), with $G$ games together and `FULL` the
games for full chemistry:

$$\text{chem} = \min(1, G/\text{FULL}), \qquad \text{halved after a month apart}$$

The engine compares the two units on the ice (each unit's average pair chemistry, relative to the league average pair) and
moves even-strength attempts by `Skill.chem` $= 0.05$ per unit of difference. Only the difference between units counts.

## 7. Draft, scouting and prospects

Source: `hs/game/draft.py`, `draft_floor.py`, `scouting.py`, `scout_net.py`, `staff.py`.

### 7.1 Eligibility, order, rights

Eligible: age 18-20 on 15 September of the draft year, undrafted, not under an NHL contract. Non-playoff clubs pick
worst-first through a two-draw lottery (a winner may rise at most 10 places); playoff clubs by round reached, champion
last. Draft rights last until 1 June of draft year $+4$ (drafted at 18) or $+3$ (19+). Entry-level terms: 3 years if
signed at 18-21, 2 at 22-23, 1 at 24+.

### 7.2 How a club sees a prospect

Each prospect has a hidden truth (ceiling, early or late maturity, late bloom). A club's projection of his ceiling is

$$\hat{c}_{ij} = \underbrace{n_i}_{\text{now, as seen}} + \underbrace{g(\text{age})}_{\text{average growth left}}
+ \underbrace{\varepsilon^{L}_i}_{\text{league-wide}} + \underbrace{\varepsilon^{j}_i}_{\text{club's own}} - \underbrace{B_j(i)}_{\text{biases}}$$

with $\varepsilon^L \sim N(0, \sigma_L)$ shared by every club (bigger outside North America) and
$\varepsilon^j \sim N(0, \sigma_j)$ the club's own error. Goalies are 1.35 times harder to project. Biases depend on the
director of amateur scouting's philosophy (traditional: full, balanced: about half, analytics: little):

| Bias | Formula |
|---|---|
| Size | $B_{\text{size}} = \operatorname{clip}\big(0.07\,(183 - h_{\text{cm}}),\, -0.7,\, 0.7\big)$ (small marked down, big up) |
| Europe | European junior seen less and discounted |
| Russia | Russian under KHL contract discounted, more per year left on the contract |

Nobody sees late blooming, so safe early maturers are overrated and late developers underrated.

### 7.3 Staff effect on scouting error

Scouting quality $Q = 0.5\,e_{\text{director}} + 0.25\,e_{s_1} + 0.25\,e_{s_2}$ (evaluation ratings). The club's noise sd:

$$\sigma_j = \operatorname{clip}\big(0.75 - 0.035\,(Q - 10),\; 0.25,\; 1.0\big)$$

### 7.4 Picking

| Round | Rule |
|---|---|
| 1 | best player available on the club's own board, with a 10% nod to need |
| 2-4 | 60% best available, 40% positional need |
| 5-7 | chase upside ("boom or bust") |
| Goalies | pushed out of round 1 unless top tier |

### 7.5 The user's scouting network

Knowledge of each prospect is a number of points $K \in [0, 100]$, graded A (80+), B (60+), C (40+), D (20+), E (below 20).
Everyone starts at 45. Each week, for a prospect in region $r$:

$$K_{t+1} = 0.94\,K_t + \underbrace{\tfrac{e_s}{20}\cdot 8\cdot w}_{\text{assigned scout}} + \tfrac13\cdot\underbrace{\tfrac{e_d}{20}\cdot 8}_{\text{director}}$$

with $w = 2$ for a prospect on the watch list (otherwise 1). The steady state is $K^* = G / 0.06 \approx 16.7\,G$ for
weekly gain $G$, so the default spread (two average scouts over five regions, an average director) settles near 50, a C,
the level of the AI clubs; two scouts on one region take it to A there and leave the rest at D.

Your error on a prospect is the staff's error times a grade factor:

| Grade | A | B | C | D | E |
|---|---|---|---|---|---|
| Factor | 0.5 | 0.75 | 1.0 | 1.25 | 1.5 |

A tournament trip (World Juniors, Top Prospects Game, Frozen Four, U18 Worlds, Memorial Cup, combine, Hlinka Gretzky
Cup) adds 12 points (more for a better scout) to every prospect the scout saw. Central scouting publishes lists on 15
October, 15 January and 15 April, with error sd 1.0, 0.7 and 0.45 rating points around the league's consensus; grades A
(first round), B (second or third), C (fourth to sixth).

### 7.6 Picks as currency

Pick value chart: pick 1 = 1000, pick 32 = 300, a mid third-rounder about 100, a fifth about 38, the last pick 12,
log-linear between anchors. Future picks are valued at the middle of their round and discounted 15%.

When a prospect the league rated well above the current slot is still on the board, the slot is worth more:

$$M_{\text{live}} = 1 + 0.5\,\min\!\big(1,\; \text{slide}/10\big)$$

Module A (moving up): a club whose top target is clearly better than anyone it expects at its own pick offers its next
pick plus later picks to cover the chart gap, plus half the live-board spike $V\,(M_{\text{live}} - 1)/2$; if desperate the
seller adds a 25% premium on the gap, and sells only if its own top choice is not much better than what it expects lower.
Module B (consolidation): a club with more than 9 picks bundles three picks from rounds 5-7 into one higher pick, if its
contract count leaves room under the 50-contract limit.

## 8. The owner, the board and jobs

Source: `hs/game/org.py`, `boardroom.py`, `owner_goals.py`, `gm.py`, `staff.py`.

### 8.1 Weekly hot-seat score

For every NHL club with at least 5 games played, each week. Let $c$ be board confidence (0-100), $v$ the four-week
change in confidence divided by 100 and clamped to $[-0.5, 0.5]$, $\pi \in [0,1]$ the owner's patience, VOC his
vocalness (0-1), and

$$m_p = \min\big(0.40,\; m_{\text{market}} + 0.03\,\max(0, L - 3)\big), \qquad m_{\text{market}} \in [0.10, 0.40]$$

with $L$ the current losing streak. Then

$$P = \begin{cases} 1.1 - \pi & v < 0 \\ \pi & v \ge 0 \end{cases}, \qquad T = \frac{c}{100} + v\,P - m_p\,\text{VOC}$$

Confidence itself drifts with the points pace against the competitive objective (a quarter of the old monthly drift each
week).

| Threshold | Consequence |
|---|---|
| $T \le 0.40$ | media leaks, by VOC: above 0.8 specific, the same day; 0.3-0.8 vague, 2-4 days later and only for ultimatums; below 0.3 silence |
| $T \le 0.33$ | an AI club whose owner is involved (4+) fires its head coach first, once a season (+8 confidence) |
| $T \le 0.25$ | ultimatum |

### 8.2 Ultimatum

Games $n = 3$ if patience is under 0.3, otherwise 5. Points required: $\lceil 2 n \cdot r \rceil$ with $r = 0.55$ (0.60 for
impatient owners). Met: +6 confidence, the warning lifts and no new ultimatum for 14 days. Missed: the GM is fired. The
user may dismiss the head coach while an ultimatum is open: +8 confidence and three more games.

### 8.3 Directives (user's club)

At most one open, issued weekly with probability $0.1 + \text{involvement}/40$:

| Directive | Condition | Deadline |
|---|---|---|
| move_veteran | a named veteran (30+, $4M+ cap hit); budget owners or club over its payroll objective | trade deadline |
| add_forward | a top-six forward; ambitious owner, club below target | trade deadline |
| keep_youth | trade nobody 23 or under | fails the day it is broken |
| extend_core | extend a named core player in his last year | end of regular season |

Met: +3. Missed: $-8\,(1.2 - \pi/10)\,(1 + \text{involvement}/20)$, and $T$ is recomputed at once.

### 8.4 Owner goals

At the start of each season the owner picks up to three goals from a catalogue, those that fit the club's situation and
leave a month, weighted by his traits (ambition, patience, spending, youth, involvement, market).

| Priority | Met | Failed |
|---|---|---|
| Low | +2 | -2 |
| Medium | +4 | -4 |
| High | +6 | -7 |

Catalogue (trigger, then task): acquire a top-30 skater (ambition 6+, deadline); acquire a top-16 goalie; shed a
veteran's contract ($3M+, 29+, outside the top six, value lags pay most, spending 5 or less); hire a coach rated 14+
within 75 days (current head coach rated 10 or less, involvement 5+); hire a development coach rated 14+ (current 9 or
less, development 6+); give the best prospect (21 or under, under 20 NHL games) 20 NHL games (youth 5+); keep next
summer's first-round pick until the draft; add a first-round pick (rebuilding club, ambition 5 or less); take the
season series from the fiercest rival; win 24 home games (market 7+); bring average age under 28 (current 28.5+, youth
7+); dress 12 or more Canadians at the deadline (Canadian club, involvement 6+).

### 8.5 GM background

A small start, not a different game: former player +5 trust from every player; scout +3 confidence with owners who
prefer youth (7+); analytics +3 with owners with analytics bias 0.6+; coach +3 cohesion; business +3 with budget owners
(spending 4 or less).

### 8.6 Staff effects

Relative to a neutral rating of 10:

| Effect | Formula |
|---|---|
| Scouting noise | $\sigma = \operatorname{clip}(0.75 - 0.035\,(Q-10), 0.25, 1.0)$ |
| Development speed (age $\le$ 24) | $\times\,(1 + 0.02\,(Q_{\text{dev}} - 10))$ |
| Injury length | $\times\,\max\big(0.6,\; 1 - 0.025\,(m_{\text{MED}} - 10)\big)$ |

with $Q_{\text{dev}} = 0.5\,\text{DEV} + 0.3\,\text{HC} + 0.2\,\overline{\text{AC}}$ (goalies use the goalie coach instead of
the assistants). The head coach has no direct effect on the match engine except through tactics execution (section 6.4);
his communication and leadership feed trust and cohesion.

## 9. Finance

Source: `hs/game/finance.py`, `accounts.py`, `arena.py`. The numbers are the game's own, not any club's books.

### 9.1 Attendance and the gate

Seats are split into lower bowl (44%), upper bowl (50%) and premium (6%). For each seat type, per home game:

$$D = \big[\,0.92 + 0.003\,(s - 55) + 0.30\,(\text{pts\%} - 0.5) + 0.012\,(M - 5) + 0.0015\,(q - 60) + w + r + \varepsilon\,\big]\;
\Big(\frac{p}{p_{\text{ref}}}\Big)^{-\eta}$$

| Symbol | Meaning |
|---|---|
| $s$ | fan sentiment (0-100) |
| pts% | points percentage |
| $M$ | market size (1-10) |
| $q$ | arena quality |
| $w$ | weekend bonus 0.03 |
| $r$ | rival bonus 0.03 (rivalry 50+: +3% demand, heated or bitter +5%) |
| $\varepsilon$ | noise |
| $p, p_{\text{ref}}$ | ticket price and the club's reference price |
| $\eta$ | price elasticity: lower 1.1, upper 1.35, premium 0.8 |

$$\text{sold} = \text{capacity}_{\text{type}} \cdot \min(1, D)$$

Playoffs: a full house at 1.6 times the price. Gate revenue is $\sum_{\text{types}} \text{sold}\cdot p$.

### 9.2 Other revenue and costs

| Item | Amount |
|---|---|
| Concessions and merchandise | $40 per fan (more when fans are happy) |
| National media | $30M a year, the same for all |
| Local media | $6M + $2.2M x market |
| Sponsorship | $9M + $2.4M x market (more when winning) |
| Revenue sharing | clubs in markets 4 or under receive $12M a year, paid by markets 8 and up |
| Arena operations | $0.7M a home game + $1.1M a month |
| Travel | $0.25M a road game |
| Administration | $1.4M a month |
| Player payroll | contract cash: salaries over the seven months of the regular season, signing bonuses on 1 July |

At the close of the season the owner takes a share of a profit (more if he spends little) or covers part of a loss (more
if he spends freely).

### 9.3 Budgets

The league default for each of the three budgets (scouting, development, marketing) is what every AI club spends, so they
are league-neutral. Moving yours changes: scouting error by up to 15% either way; development rate by up to +5% / -4%;
fans' mood by up to 0.5 a week either way.

### 9.4 Statements, budget and the board's review

The fiscal year runs July to June. The chart of accounts has sections 4000 Revenue, 5000 Cost of hockey operations, 6000
Operating expenses, 6500 Depreciation, 7000 Non-operating (2% a year earned on a cash balance, 6% paid on an overdraft,
monthly) and 8000 Owner. Subtotals:

$$\begin{aligned}
\text{Hockey ops margin} &= \text{Revenue} - \text{Cost of hockey ops} \\
\text{EBITDA} &= \text{margin} - \text{Operating expenses} \\
\text{Operating profit} &= \text{EBITDA} - \text{Depreciation} \\
\text{Net profit} &= \text{Operating profit} \pm \text{interest} \\
\text{Retained} &= \text{Net profit} - \text{owner distributions} + \text{contributions}
\end{aligned}$$

Capital items (renovations, new seats) are depreciated straight-line over 10 years from the month after payment.
The budget is set on opening night: July to September at actuals, October to June planned from the schedule, today's
prices, fan mood, last season's form, contracts, staff and budgets, with no playoff revenue.

The board's quarterly review compares net result with budget. With gap $g$ = actual minus budget and owner spending trait $S$:

$$\Delta c = \begin{cases}
S \le 4: & -4\ (g \le -\$10M),\ -2\ (g \le -\$5M),\ +2\ (g \ge \$5M),\ 0 \\
5 \le S \le 6: & -2\ (g \le -\$10M),\ +1\ (g \ge \$10M),\ 0 \\
S \ge 7: & -1\ (g \le -\$20M),\ 0
\end{cases}$$

### 9.5 A new arena

$$\text{cost} = \text{capacity}\times \$22{,}000 \times \Big(0.6 + 0.4\,\frac{q}{90}\Big)$$

so 18,000 seats at quality 90 cost $396M. Capacity 15,000-21,000, quality 70-95. The owner pays $0.20 + 0.06\,S$ of the cost
as contributions (spending 5: 50%); the club borrows the rest. He refuses a second project, an arena already rated 80+,
board confidence under 45, or a share over $\$40M \times S$.

Construction takes 24 months; the cost leaves as capital spending in 24 equal monthly drawdowns. The loan is 5% a year
and repaid monthly over 25 years from opening. The building depreciates over 30 years. At opening, demand gets a novelty
boost fading to zero over five seasons:

$$\text{novelty}_k = 0.08\,\Big(1 - \frac{k}{5}\Big),\qquad k = 0,1,\dots,4 \text{ seasons since opening}$$

This is the demand boost: 8% in the first season, fading linearly to nothing over five (`NOVELTY`, `NOVELTY_YEARS` in `arena.py`).

## 10. People: morale, harmony, leadership, press, discipline

Source: `hs/game/people.py`, `harmony.py`, `captaincy.py`, `welfare.py`, `press.py`, `rivalry.py`, `discipline.py`.

### 10.1 Morale

Five components, each 0-100: role (ice time against his belief about his place: value rank against last-10-games TOI
rank), team (results against expectation, weighted by ambition), contract (paid below market value, or final year with no
extension), trust in management (promises kept, conversations, leaders traded) and trust in the coach (communication and
leadership, style against personality).

$$\text{morale} = 0.35\,R + 0.20\,T + 0.15\,C + 0.15\,M + 0.15\,H$$

Each component moves a quarter of the way to its weekly target (resilient players fall more slowly), with a little noise:
$x_{t+1} = x_t + \tfrac14\,(x^* - x_t) + \varepsilon$. Morale does not change match ratings. Cohesion is driven by average
morale, leadership strength, roster turnover and clashes, not directly by wins.

### 10.2 Harmony

Cliques: players grouped by language and age (veterans 31+, kids 23 and under); four or more make a clique. A clique whose
average morale is under 45 costs one cohesion point a week. Two players clash when both have ego 14+ and either temperament
$\le 7$ or sportsmanship $\le 7$, or one is a malcontent (ego 16+, professionalism $\le 7$) with morale under 45. Weekly
chance of an incident: 12%, halved by a captain with leadership 15+, higher in a tense room. An incident: cohesion -3, both
players' morale -4.

### 10.3 Captaincy

Each player ranks leaders by $2\,\text{leadership} + \text{professionalism} + \text{experience} + \text{standing}$. Naming
the room's top three costs nothing; each outside pick costs cohesion 3 (captain) or 1.5 (alternate), and the veteran passed
over loses 3 trust. A new captain: +6 morale, +5 trust. Losing the C:

$$\Delta\text{trust} = -(6 + 1.2\,\max(0, \text{ego} - 10)),\quad \Delta\text{role} = -4,\quad \Delta\text{morale} = -5$$

An ego-driven player (15+) with loyalty $\le 8$ asks for a trade with probability $0.15 + 0.04\,(\text{ego} - 15)$; losing an A
is half of all this. Mid-season changes cost 2 more cohesion. Owner effects: +1.5 confidence for a captain 24 or younger
(youth 7+), -1.5 for stripping a franchise veteran (value 60+, 28+, involvement 6+), +0.5 for the room's own choice.

### 10.4 Press conferences

Each answer archetype has base effects on room morale, board confidence and fans:

| Archetype | Room | Board | Fans |
|---|---|---|---|
| Back the group | +5 | +2 | +2 |
| Take responsibility | +8 | +5 | +4 |
| Cliche | +1 | +1 | 0 |
| Deflect | -2 | -3 | -2 |
| Call out a player | -15 | -5 | +8 |
| Blame the officials | +5 | -10 | +15 |
| Credit yourself | -5 | +5 | +5 |
| Question the coach | -10 | -12 | +10 |
| Demand accountability | +3 | -5 | +8 |
| No comment | -1 | -2 | -3 |
| Speak from the heart | +6 | +3 | +8 |
| Issue an ultimatum | -12 | -15 | +12 |

The context scales every effect by $(1 + \text{pressure}/200)$, where pressure is 40, +15 for a losing streak of three or
more, +15 for a rivalry, +20 on the hot seat (confidence under 45), and by a further 1.2 after three or more straight
losses. Effects land on each player's morale (room number x 0.3), cohesion (x 0.25), board confidence (x 0.35) and the
club's media state. A named player also feels it: calling out costs trust $-(10 + \text{ego}/2)$ and morale -8; praise
gives trust +4 and morale +3.

### 10.5 Rivalries

Points per pair of clubs, 0-100: base 22 same division, 10 same conference, +30 for a traditional rivalry. Regular-season
meetings add +0.4 a game, +0.4 more if decided by one goal or in overtime, +0.3 if chippy (ten or more penalties). Playoff
meetings add +2 a game, +8 for the series, +4 for a seventh game, +6 for a final. Each summer:
$h \leftarrow h + \tfrac14\,(\text{base} - h)$. Levels: under 30 none; 30-49 simmering; 50-69 rivalry; 70-84 heated; 85+ bitter.

### 10.6 Playing hurt, termination, suspensions

Playing hurt: a player with at most three weeks to go plays at $-0.35\,\sigma$ in offence, defence and finishing; each game
there is an 8% (higher for the injury-prone) chance it worsens, costing the remaining time plus one to three weeks.
Mutual termination: settlement 10-40% of the remaining money; a player agrees when he is 27+ and unhappy with his role, or
barely plays, or is a veteran past his best.

Suspensions: about 3.5% of NHL games produce one. The player is drawn from the two lineups, weighted by aggression and
hitting. Length distribution:

| Games | 1 | 2 | 3 | 4-5 | 6-10 | 11-20 |
|---|---|---|---|---|---|---|
| Probability | 35% | 25% | 15% | 12% | 10% | 3% |

A repeat offender (within 18 months) gets half as many games again. Pay forfeited is cap hit / 82 per game. A suspension of
six or more games can be appealed once; the commissioner cuts it by a third with probability 0.25.

## 11. The wider world

Source: `hs/game/leagues.py`, `international.py`, `college.py`, `expansion.py`, `legacy_score.py`.

### 11.1 Other leagues (results model)

Leagues other than the top league are not run through the match engine (it would be about six times slower). Each club's
best twelve forwards and six defencemen give an attack rating $A$, and the starter (in about seven games of ten) a goalie
rating $G$. Goals are Poisson around the league scoring rate $\lambda_0$, tilted by the attack gap and the opposing goalie:

$$\lambda_h = \lambda_0\,\exp\big(K_A\,(A_h - A_a) - K_G\,(G_a - \bar G)\big)\,(1 + \eta_h),\qquad X_h \sim \text{Poisson}(\lambda_h)$$

with $K_A = 0.55$ (a club 0.5 better scores about 30% more), $K_G = 0.22$ (a point of goalie overall above the league's takes about 20% off), and a home edge $\eta_h = 0.04$ (zero for the away club). A 3-on-3 overtime produces a goal with probability 0.55. Ties go to overtime and a shootout (or stand, in NCAA).
Each goal gets a scorer and up to two assists among the dressed players, weighted by overall, line and position. Shots and
penalty minutes are spread the same way.

### 11.2 International hockey

Games use the same results model with the gaps between nations narrowed to a fifth (all rosters are picked from the best)
and 2.5 goals a team a game. A roster is 14 forwards, 8 defence and 3 goalies (13/7/3 at the World Cup). Overtime decides
every game. The ranking gives points by final place at the World Championship and the Olympics (1st 1200, then lower).
Eligibility: 65% of North Americans and 35% of Europeans in NHL clubs that missed the playoffs say no to the World
Championship.

### 11.3 College

Recruiting rounds (15 October, 1 March, a summer round): of eligible commits, a program is chosen by

$$\text{score} = \frac{\text{prestige}}{10} + \text{playing time (open places at his position)} + \text{luck}$$

among programs that want him (his quality reaches the program's bar and it has a place). Each round, 70% of next season's
recruits and 35% of the year after's commit, and a program fills at most 55% of open places (a quarter for the year after).
Commit rates: USHL, NAHL and BCHL 85%; Americans in the CHL 30%; Canadians in the CHL 12%; Europeans 5%. A commit enrols
next season if his overall is within half a point of the NCAA average or he will be 20. Eligibility: old rules four seasons
(one fewer for each year enrolled past 21); from 2027-28 five seasons in five years.

### 11.4 Expansion

Each 1 February from the second season, 25% chance of an announcement, up to 36 clubs. Expansion draft: protect 7F + 3D + 1G
or any 8 skaters + 1G; each club loses exactly one player; the new club must finish with 14+ forwards, 9+ defence, 3+
goalies, 20+ contracts, and a payroll of 60-100% of the cap. Side deals: a 1st when the trade-value gap is 80 or more
(three at most), a 2nd when 25 or more, up to six a draft. The new club gets the third-worst club's lottery odds.

### 11.5 Career Legacy Score

Season value (SV) is relative to the league average starter at the position (average = 1.0):

| Position | SV |
|---|---|
| Forward | $0.75\,\dfrac{\text{pts}}{\overline{\text{pts}}} + 0.25\,\dfrac{\text{goals}}{\overline{\text{goals}}}$ |
| Defence | $0.50\,\dfrac{\text{pts}}{\overline{\text{pts}}} + 0.30\,\dfrac{\text{DPS}}{\overline{\text{DPS}}} + 0.20\,\dfrac{\text{TOI}}{\overline{\text{TOI}}}$ |
| Goalie | $0.30\,\dfrac{\text{wins}}{\overline{\text{wins}}} + 0.50\,\Big(1 + \dfrac{\text{GSAA} - \overline{\text{GSAA}}}{1\%\,\overline{\text{SA}}}\Big) + 0.20\,\dfrac{\text{starts}}{\overline{\text{starts}}}$ |

Peak and longevity: $P = $ sum of the best seven SV, $L = $ sum of the rest, $\text{PVL} = 10P + 3L$. Then
$\text{CLS} = \text{PVL} + \text{HL}$ where the hardware ledger adds Hart and Conn Smythe +50, Norris and Vezina +40, Selke
and Art Ross +25, First All-Star +15, a championship +30 (up to +20 more for his share), and milestones (forwards: 500
goals +20, 1000 points +20, 1500 points +30; defence: 1000 games +15, 500 points +20, 1000 points +40; goalies: 300 wins
+15, 500 wins +30, 50 shutouts +20). Tiers: Inner Circle over 450; First Ballot 350-449; Hall of Fame 250-349; Hall of Very
Good 180-249.
