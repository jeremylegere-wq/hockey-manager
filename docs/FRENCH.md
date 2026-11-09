# The French (Quebec) interface (v39, completed v50)

File > Français (Québec) switches the interface; the choice is kept per browser (localStorage) and the page reloads.

* v39 translated the interface chrome: menus, the bar, tabs, common buttons and headings (about 200 strings).
* v50 covers every screen's labels, column headings, tabs, panels and buttons, including the screens added since v39
  (World Leagues, Expansion, Hall of Fame, College Hockey, Challenges, Commissioner, numbers, logos and photos), the
  board's objectives, the challenges, dates (lun. 5 oct. 2026, the schedule strip) and the status bar. About 992 strings
  in all (`hs/ui/static/v39.js` FR, `hs/ui/static/v50.js`), in Quebec hockey usage: alignement, trios, ballottage,
  repêchage, joueurs autonomes, Association de l'Est, Temple de la renommée.
* How it works: text the screens draw is matched against the dictionary (exact strings, and patterns for text with
  numbers and dates) and replaced as it appears. Names of players, clubs and leagues are not translated.
* Still in English: the text the game writes (news stories, inbox messages, press questions, recaps, the assistant's
  advice) and long help paragraphs on a few screens. Translating those needs the Python side to write in two
  languages; it is the next step for French.
