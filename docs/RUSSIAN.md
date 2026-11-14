# Русский интерфейс / The Russian interface (v61)

File > **Русский** switches the interface to Russian (and back); File > Français (Québec) switches to French. The
choice is kept in the browser's storage of the game window and applies at once (the page reloads).

What is translated: the menus, tabs, buttons, column headings, panel titles, dialogs, dates, the sim centre, and the
explanatory sentences and tooltips of the screens. That is every string the French interface covers (1,128) plus the
v61 screens and about 220 sentences and labels found by walking every screen in Russian. The dictionary is
`hs/ui/static/ru.js`, keyed by the English text, with patterns (`RU_RE`) for text with numbers in it.

What stays in English, as in French: text the game writes (news, inbox messages, press questions, recaps), names of
players and clubs, statistics abbreviations in table headings (GP, PTS, GAA...), and a few sentences put together
from pieces (a bold word or a link in the middle).

Terms follow Russian broadcast and KHL usage: звено (line), пара (defence pair), большинство / меньшинство (power
play / penalty kill), драфт отказов (waivers), потолок зарплат (salary cap), нагрузка на потолок (cap hit),
свободный агент (free agent), офер-лист (offer sheet), обмен (trade), аренда (loan), трансфер (transfer),
отступные (transfer fee).

To add a string: put `"English": "Русский"` in `RU` (or a pattern in `RU_RE`). Club and player names are never
translated (links to a club or player page are skipped; mark anything else with `data-noi18n`).
