# The calendar (phase F, v37)

Everything around the regular season: rivalries, the exhibitions (pre-season, prospects tournaments, all-star
weekend), the Hall of Fame, GM scores and leaders, and your achievements. None of the exhibitions counts in the
standings or the season's statistics.

Screens: League > Exhibitions (with the calendar options), League > All-Star Weekend, League > Hall of Fame,
League > GM Leaders, Manager > Achievements, and the Rivalries panel on Team Info. The Calendar shows the new dates.

CLI: `events` (options and coming dates), `events set <option> <value>`, `rivals [TEAM]`, `allstar`, `hof`,
`hof vote <player>, <player>`, `gmleaders`, `achievements`.

When things happen:

| When | What |
|---|---|
| Every game day | rivalry heat from each meeting; rivalry games are big games |
| Mondays | achievements are checked |
| First Saturday of February | all-star weekend (skills competition and the game), except in an Olympic year |
| End of the playoffs | playoff series add rivalry heat, then the summer cools it; GM season scores; the Hall of Fame ballot |
| Re-signing phase opens (29 June) | the Hall of Fame vote |
| Pre-season phase opens (15 September) | the prospects tournaments |
| The regular season is scheduled | the pre-season games, dated in the two weeks before opening night |

Calibration: the big-games attribute is centred on the league's average, so counting it in rivalry games moves no
league totals; the exhibitions have their own tables. The engine is otherwise unchanged from v36, so the v33
calibration stands.

## Rivalries (hs/game/rivalry.py)

Rivalries (phase F, v37): a real rivalry model in place of "same division = rivalry".

Every pair of top-league clubs has rivalry points, 0-100:
  * a base: 22 for the same division, 10 for the same conference, 0 otherwise; +30 for a traditional rivalry
    (finance.RIVALS, or a pack's own list in pack_info 'rivalries': [["TOR", "MTL", 30], ...])
  * regular-season meetings add heat: +0.4 a game, +0.4 more when it is decided by one goal or in overtime, +0.3
    for a chippy one (ten or more penalties between them)
  * playoff meetings add the most: +2 a game, +8 for the series, +4 more for a seventh game, +6 more for a final
  * each summer the heat cools: points move a quarter of the way back to the base
Levels: under 30 none; 30-49 simmering (a potential rivalry); 50-69 rivalry; 70-84 heated; 85+ bitter.
A club's main rival is its highest pair at 50 or more; its potential rivals are pairs 35-49 that warmed this season.

What a rivalry (50+) does:
  * big games: the hidden "big games" attribute (hs/game/hidden.py), which used to count only in the playoffs,
    counts in rivalry games too. It is centred on the league's average, so league scoring does not move
  * the press room treats the game as a rivalry game (pressure, the questions; hs/game/press.py)
  * the gate: +3% demand (+5% heated or bitter) for the home club (hs/game/finance.py)
  * fan swings: your fans swing harder after a rivalry game, win or lose (+-1.5 to 3 on their mood)

## Exhibitions (hs/game/exhibitions.py)

The calendar's exhibitions (phase F, v37): pre-season games, the prospects tournaments, all-star weekend.

All three are played by the real game engine, but none of them touches the standings, the season's statistics or the
box-score tables (games, player_game_stats): they live in their own tables, `exhibitions` (one row a game, or a
skills competition) and `exhibition_stats` (each player's line and his 1-10 game rating).

Pre-season (each club plays `preseason_games`, default 6, in the two weeks before opening night; played when the
regular season is scheduled, `advance` from the pre-season phase). Clubs play nearby clubs (same conference first).
Your camp's prospects (status 'prospect', the best three forwards, two defencemen and a goalie) take the fourth line,
the third pair and every second start in goal for the first half of the games, so the games are an audition. What
pre-season does: line chemistry (hs/game/chemistry.py: lines that play together get better together, relative to the
league, so league totals do not move), injuries at half the regular-season rate, and the camp report in your inbox
(record, who stood out, how the prospects did).

Prospects tournaments (in mid-September, when the pre-season phase opens): one per division, each club's prospects
(22 or younger: signed prospects and unsigned draft picks; tryout invitees from the unattached fill the gaps) play three
group games, then the top two meet in the final. Your scouts watch your tournament: every player in it is better known
(+10 knowledge points, hs/game/scout_net.py).

All-star weekend (the first Saturday of February; none in a season with an Olympic break). Formats (the career option
`allstar`): conference (East against West), draft (the two leading vote-getters pick their teams, alternating), world
(North America against the World). Twenty per side: twelve forwards, six defencemen and two goalies, chosen on this
season's scoring and ability, with every club represented (except in the world format). Defence is optional: every
skater's defensive play and every goalie's saving are lowered
for the game (about a dozen goals, as in the real one). The skills competition the same day: fastest skater, hardest shot,
accuracy shooting, stickhandling and the goalies' save streak, from the players' attributes plus the night.

Career options (pack_info 'calendar_options', CLI `events set <key> <value>`): preseason_games 0-10, allstar
conference|draft|world|off, prospects on|off, hof committee|auto (hs/game/legacy.py).

## Hall of Fame, GM score, achievements (hs/game/legacy.py)

What a career leaves behind (phase F, v37): the Hall of Fame, GM leaders and the GM score, your achievements.

Hall of Fame. A retired player is eligible once three full seasons have passed since his last NHL season. His case
(the Hall of Fame score) comes from his NHL career in the save, regular season and playoffs:
  skaters: 0.06 a point + 0.02 a goal + 0.01 a game, x1.25 for a defenceman
  goalies: 0.1 a game + 1500 x (save % - .905) for a goalie with 300+ games (pro rata below)
  plus trophies: Hart 10, Vezina and Norris 8, Art Ross and Conn Smythe 6, Richard 4, Calder 2; 3 a championship
(The pack's history starts in 2008, so a player whose career began well before it is undercounted.)
Each summer (when the re-signing phase opens) the selection committee (18 members) votes on a ballot of the ten best
eligible cases: each member backs up to four, more likely the stronger the case (a case of 82 is a coin flip). 75% of
the committee inducts, at most four a year. Career option hof (hs/game/exhibitions.py): committee, where you are
one of the eighteen and get the ballot in your inbox (CLI `hof vote <player> [<player> ...]`, up to four), or auto,
where the committee votes without you.

GM score and GM leaders. Every season each club's GM (you, or the AI GM on the board's books, hs/game/boardroom.py)
earns a season score: (points % - .500) x 100, +5 for each playoff round reached, +10 more for the championship,
+8 for the GM of the year award. A GM's career score is the sum; GM leaders ranks them, with seasons, clubs, record,
playoffs and championships. The save keeps it from its first finished season.

Achievements: milestones of your career as a GM (the list in ACHIEVEMENTS), checked weekly and at season end; each one
once, dated, with an inbox note and a news line.
