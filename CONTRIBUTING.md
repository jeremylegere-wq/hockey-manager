# Contributing and reporting bugs

## Report a bug

Email **jeremy.legere@gmail.com**, or open an issue on GitHub (the templates ask for the right things). In the game,
**Help > Report a bug** fills in the details and opens an email.

A report that can be fixed has:

1. **The version** (Help > About, or `hs/ui/settings.py`) and your system (Windows, macOS, Linux; window or browser).
2. **What you did, what you expected, what happened instead.**
3. **The exact error**, word for word, or a screenshot. If the terminal the game started from shows a `Traceback`, paste all of it.
4. **The save file**, if it is about a career: the `.db` file in `saves/`. It holds only that career, and with it a bug can
   usually be replayed exactly (the game is seeded: same save plus same commands gives the same result).

Please do not send real-name databases or anything you do not have the right to share.

Wrong-feeling results (a trade the AI accepted that looks absurd, a rating that looks off, a league that scores too much)
are bugs too: say what you expected and why.

## Suggest a feature

Open an issue. `docs/ROADMAP.md` shows what is planned and what is already in; the long tail is there on purpose.

## Share a league

A pack of invented clubs and players is welcome. Open an issue using "Share a league" and link it, or send it by email. Do
not publish packs built from other people's data (see `THIRD_PARTY.md`).

## Code

```bash
python3 -m unittest discover -s tests
```

* Standard library only. No new dependencies without a very good reason.
* Every module has a docstring that says what it does and what the numbers are; docs in `docs/` repeat it for players.
* A new rule gets a test and a doc line. A change that moves match results needs the calibration check
  (`docs/SIM_CALIBRATION.md`): league goals, penalties and the spread between clubs must stay where they are.
* Every UI action is one CLI command line (`hs/game/cli.py`); the UI never has rules of its own.
* Keep real names, logos and third-party data out of the repository.
