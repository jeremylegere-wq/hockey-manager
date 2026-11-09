# Long-term injured reserve (v23)

`hs/game/ltir.py`. During the regular season, an injured player expected to miss at least 10 of his club's games
and 24 days can go on LTIR. His cap hit stays on the payroll, but the club can spend past the cap to replace him:

- **Accruable cap space limit**: fixed the first time the club puts someone on LTIR: the cap minus its cap space that
  day (its payroll, if under the cap). It is not recalculated for a second player, and resets once nobody is on LTIR.
- **Ceiling** while anyone is on LTIR: that limit plus the relief pool (the cap hits of everyone on LTIR). Space below
  it is not banked. Example: payroll $94M under a $95.5M cap, an $8M player goes on LTIR: the limit is $94M, the
  ceiling $102M, so the club can add $8M (it gives up its $1.5M of space).
- **Coming back**: at least 24 days after placement, once fit, and only if the club is cap compliant without his
  relief (under the cap, or under the limit plus whoever else is still on LTIR) with a roster spot. AI clubs send
  players down until compliant (up to three moves) and activate him; you get an inbox message and use `activate`.
- Players on LTIR do not count against the roster limit. LTIR ends with the regular season (players come off,
  still injured if not healed).
- AI clubs use LTIR when an eligible injury leaves them within $3M of the cap.

Source for the limit and pool: [CapFriendly's LTIR FAQ](https://www.capfriendly.com/ltir-faq) (2017). Not modelled:
performance-bonus pools, off-season and training-camp LTIR, one-day recalls to raise the limit, and the 2026-30
CBA's changes to LTIR and to the cap in the playoffs.

You: the Roster screen has an LTIR button on eligible injured players, an Activate button on LTIR players and a panel
with your ceiling; CLI `ltir <player>`, `ltir` (list and ceiling), `activate <player>`.

Same release: payroll now counts players while they are on waivers (v22 dropped their cap hit for the day).
