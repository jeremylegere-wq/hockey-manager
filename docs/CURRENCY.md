# Display currency (v61)

The game keeps every amount in the currency it is paid in: **US dollars** for the NHL and North America (salaries,
the cap, club finances) and **euros** for the European clubs (wages, fees, budgets). Nothing in a save is converted.

What you see is converted to your **display currency**:

* Choose it on the first step of the new-game screen, from the **Currency** menu in the menu bar (it shows the
  currency in use, e.g. `$ USD`), or in File > Settings.
* It applies to every career and is kept in the settings file next to your saves.
* When you change it, a note gives the reference rate (e.g. 1 EUR = 92.33 RUB · 1 USD = 82.98 RUB). **Currency >
  Reference rates...** shows the whole table, per euro and per US dollar.
* In a desktop window whose browser engine is older (some Linux WebKit windows), the currency's short sign is not
  available: amounts then show with the currency's code (RUB 35,086,236) and the menu with its sign.
* Inputs that the game takes in its own currency say so: ticket prices and budgets are typed in US dollars (`US$`
  while another currency is shown), and offers to European clubs in euros.
* Text the game writes (news, messages) keeps the amount in its own currency.

## Rates

Reference rates, fixed in the game (`FX` in `hs/ui/static/app.js`), per euro:

| Code | Currency | Per euro |
|---|---|---|
| USD | US dollar | 1.1127 |
| CAD | Canadian dollar | 1.5839 |
| GBP | Pound sterling | 0.8362 |
| SEK | Swedish krona | 11.051 |
| NOK | Norwegian krone | 10.6145 |
| DKK | Danish krone | 7.4755 |
| CHF | Swiss franc | 0.9234 |
| CZK | Czech koruna | 24.378 |
| PLN | Polish zloty | 4.4038 |
| RUB | Russian rouble | 92.3322 |
| AUD | Australian dollar | 1.6222 |
| JPY | Japanese yen | 177.18 |

Sources: the European Central Bank's reference rates of 11 November 2026 (as published by the Banque de France), and
for the rouble, which the ECB no longer publishes, the Bank of Russia's official rate of 13 November 2026
(EUR 92.3322, USD 82.9803). To refresh them, change the `per_eur` table and its `date`.
