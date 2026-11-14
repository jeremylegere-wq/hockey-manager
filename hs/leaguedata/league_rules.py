"""The rules of the leagues below and around the NHL (v44; docs/LEAGUES.md).

Clubs, divisions and conferences come from the world (the database export); these are the rules each league plays
by, from its 2025-26 rulebook and season format. Dates are month-day; a season that starts in year Y runs into Y+1.

  games        regular-season games per club (the schedule gets as close as the alignment allows)
  points       "2pt": 2 for any win, 1 for an overtime or shootout loss
               "3pt": 3 for a regulation win, 2 for an overtime or shootout win, 1 for an overtime or shootout loss
  ot           regular-season ties: "so" (3-on-3 for five minutes, then a shootout) or "tie" (3-on-3, then the game
               stands as a tie: NCAA)
  gpg          goals a team scores a game, on average (for the results model)
  start, end   first and last day of the regular season
  playoffs     format (see hs/game/leagues.py):
               europe      places 1-6 straight to the quarterfinals, 7-10 in a pre-playoff (7 v 10, 8 v 9, best-of
                           `pre`), or the Swiss play-in (`play_in="nl"`: 7 v 8 and 9 v 10 over two games each, then
                           the 7/8 loser meets the 9/10 winner); then highest seed v lowest, best-of-7
               conference  `per_conf` per conference by points, the top `byes` resting; then within the conference,
                           highest v lowest, and the conference champions meet in the final; `reseed_league` re-seeds
                           the whole league after round one (QMJHL)
               division    a quota per division (AHL: about 70% of each division, five to eight clubs; the lowest
                           seeds play a first round while the top seeds rest), division semifinals and finals,
                           conference finals and the final
               ncaa        the 16 best records overall, single games, fixed bracket (1 v 16, 8 v 9 ...)
  best         series lengths, round by round
  conferences  conference -> divisions (for leagues whose clubs are aligned by division)
  imports      most players of another nationality a club may carry (None: no limit); `no_import_goalies`
  overage      junior leagues: most 20-year-olds a club may carry
  trophy       what the champion wins
Sources: each league's 2025-26 season format (league sites and season articles, checked November 2026). Where a detail
was not published (the WHL's wildcards, the Czech pre-playoff's length) the long-standing format is used.
"""
from __future__ import annotations

RULES = {
    "AHL": dict(games=72, points="2pt", ot="so", gpg=3.05, start="10-09", end="04-18", trophy="Calder Cup",
                playoffs=dict(kind="division", best=[3, 5, 5, 7, 7]),
                conferences={"Eastern": ["Atlantic", "North"], "Western": ["Central", "Pacific"]}),
    "ECHL": dict(games=72, points="2pt", ot="so", gpg=3.15, start="10-16", end="04-18", trophy="Kelly Cup",
                 playoffs=dict(kind="division", quota=4, best=[7, 7, 7, 7]),
                 conferences={"Eastern": ["North", "South"], "Western": ["Central", "Mountain"]}),
    "KHL": dict(games=68, points="2pt", ot="so", gpg=2.65, start="09-05", end="03-01", trophy="Gagarin Cup", imports=5,
                playoffs=dict(kind="conference", per_conf=8, best=[7, 7, 7, 7]),
                conferences={"Western": ["Bobrov", "Tarasov"], "Eastern": ["Kharlamov", "Chernyshev"]}),
    "SHL": dict(games=52, points="3pt", ot="so", gpg=2.7, start="09-12", end="03-06", trophy="Le Mat Trophy",
                playoffs=dict(kind="europe", pre=3, best=[7, 7, 7])),
    "NL": dict(games=52, points="3pt", ot="so", gpg=2.95, start="09-11", end="03-05", trophy="Swiss championship", imports=6,
               playoffs=dict(kind="europe", play_in="nl", best=[7, 7, 7])),
    "LIIGA": dict(games=60, points="3pt", ot="so", gpg=2.7, start="09-10", end="03-13", trophy="Kanada-malja",
                  playoffs=dict(kind="europe", pre=3, best=[7, 7, 7])),
    "ELH": dict(games=52, points="3pt", ot="so", gpg=2.7, start="09-11", end="03-07", trophy="Czech championship",
                playoffs=dict(kind="europe", pre=5, best=[7, 7, 7])),
    "DEL": dict(games=52, points="3pt", ot="so", gpg=2.95, start="09-17", end="03-08", trophy="German championship", imports=9,
                playoffs=dict(kind="europe", pre=3, best=[7, 7, 7])),
    "NCAA": dict(games=36, points="3pt", ot="tie", gpg=2.95, start="10-02", end="03-14", trophy="NCAA championship",
                 playoffs=dict(kind="ncaa", teams=16)),
    "OHL": dict(games=68, points="2pt", ot="so", gpg=3.45, start="09-24", end="03-21", trophy="J. Ross Robertson Cup",
                imports=2, no_import_goalies=True, overage=3,
                playoffs=dict(kind="conference", per_conf=8, best=[7, 7, 7, 7]),
                conferences={"Eastern": ["Central", "East"], "Western": ["Midwest", "West"]}),
    "WHL": dict(games=68, points="2pt", ot="so", gpg=3.5, start="09-18", end="03-22", trophy="Ed Chynoweth Cup",
                imports=2, no_import_goalies=True, overage=3,
                playoffs=dict(kind="conference", per_conf=8, best=[7, 7, 7, 7]),
                conferences={"Eastern": ["Central", "East"], "Western": ["B.C.", "US"]}),
    "QMJHL": dict(games=64, points="2pt", ot="so", gpg=3.4, start="09-17", end="03-21", trophy="President's Cup",
                  imports=2, no_import_goalies=True, overage=3,
                  playoffs=dict(kind="conference", per_conf=8, reseed_league=True, best=[7, 7, 7, 7])),
    "USHL": dict(games=62, points="2pt", ot="so", gpg=3.2, start="09-25", end="04-11", trophy="Clark Cup", imports=4,
                 playoffs=dict(kind="conference", per_conf=6, byes=2, best=[3, 5, 5, 5])),
}

# v60: the rest of the world's leagues (second tiers, the smaller top leagues, junior and university hockey).
# v61: the European leagues are now taken from each league's 2025-26 format (sources below); only the leagues in
# APPROXIMATE are still written from general knowledge. Where the world has fewer clubs than the real league (Norway,
# Mestis, the Swiss League), the game count is the real one and the schedule fills it as evenly as it can (`fill`).
#   top        the best `teams` clubs of the overall table, highest seed v lowest, re-seeded every round
#   europe     (v61 options) `direct` clubs straight to the quarterfinals (6), the next `wild` play a first round
#              (4: 7 v 10, 8 v 9; 8: 5 v 12 ... 8 v 9) best-of-`pre`; `pre_pick` the best of them chooses his
#              opponent (ICEHL); `pick` "top3": the top three choose their quarterfinal opponents from the four below
#              the fourth (ICEHL, Alps), "low2": each round the best club left picks from the two lowest (Norway);
#              `bracket` a fixed bracket (1 v 8, 4 v 5 meet in a semifinal) instead of re-seeding; `legs` rounds played
#              over two games on aggregate goals (round index: EIHL quarterfinals); `bronze` a third-place game;
#              `phase2` a second phase before the playoffs (Alps: a Master Round and two Qualification Rounds)
#   promote    (v61) promotion and relegation with the league above, when both are in the world and in play:
#              "playout" the two last of the league above play a best-of-7 and the loser goes down for the champion
#              here (SHL); "direct" the last above goes down for the champion (DEL, if the champion has a licence);
#              "series" the last above plays the champion here, best-of-7 (Czech baraz); "playout_series" the
#              playout loser above plays the champion here (NL/SL league qualification). `apply` the chance the
#              champion applies or holds the licence to go up.
RULES.update({
    # HockeyAllsvenskan: 14 clubs, 52 games; 1-6 to the quarterfinals, 7-10 an eighth-final; the final's winner goes
    # up to the SHL; 13 v 14 play out against relegation to Hockeyettan (not in the world, so not played)
    "ALLSV": dict(games=52, points="3pt", ot="so", gpg=2.85, start="09-19", end="03-06", trophy="HockeyAllsvenskan title",
                  playoffs=dict(kind="europe", direct=6, wild=4, pre=3, best=[7, 7, 7]),
                  promote=dict(into="SHL", how="playout", apply=1.0)),
    # Maxa liga: 14 clubs, 52 games; three preliminary series (home-away-home); the champion plays the Extraliga's
    # last club, best-of-7, for its place
    "CZE2": dict(games=52, points="3pt", ot="so", gpg=2.9, start="09-10", end="02-28", trophy="Maxa liga title",
                 playoffs=dict(kind="europe", direct=5, wild=6, pre=3, best=[7, 7, 7]),
                 promote=dict(into="ELH", how="series", apply=1.0)),
    # DEL2: 14 clubs, 52 games, 1-6 direct, 7-10 pre-playoffs best-of-3; the champion goes up if licensed and the
    # DEL's last club goes down; four imports on the sheet
    "DEL2": dict(games=52, points="3pt", ot="so", gpg=3.2, start="09-12", end="03-01", trophy="DEL2 championship", imports=4,
                 playoffs=dict(kind="europe", direct=6, wild=4, pre=3, best=[7, 7, 7]),
                 promote=dict(into="DEL", how="direct", apply=0.75)),
    # ICE Hockey League: 52 games; 7-10 pre-playoffs best-of-3, the 7th choosing the 9th or 10th; the top three
    # choose their quarterfinal opponents (the 4th cannot be chosen); then the best v the lowest
    "ICEHL": dict(games=52, points="3pt", ot="so", gpg=3.0, start="09-18", end="02-28", trophy="ICE Hockey League championship",
                  playoffs=dict(kind="europe", direct=6, wild=4, pre=3, pre_pick=True, pick="top3", best=[7, 7, 7])),
    # Slovak Extraliga: 12 clubs, 54 games (44 plus a Christmas block); 7-10 a best-of-5 wild-card round
    "SVK": dict(games=54, points="3pt", ot="so", gpg=3.05, start="09-12", end="03-08", trophy="Slovak championship",
                playoffs=dict(kind="europe", direct=6, wild=4, pre=5, best=[7, 7, 7])),
    # Alps Hockey League: 13 clubs, 36 games; then the top five play a Master Round (bonus 4-3-2-1-0, each other
    # twice) and 6-13 two Qualification Rounds of four (bonus 3-2-1-0); the top three of each group meet in
    # best-of-3 pre-playoffs; the Master Round decides the quarterfinal pick
    "ALPS": dict(games=36, points="3pt", ot="so", gpg=3.3, start="09-19", end="01-30", trophy="Alps Hockey League title",
                 playoffs=dict(kind="europe", phase2="alps", pre=3, pick="top3", best=[7, 7, 7])),
    # Ligue Magnus: 12 clubs, 44 games (each other four times); the top 8, best-of-7 in every round
    "MAGNUS": dict(games=44, points="3pt", ot="so", gpg=3.2, start="09-12", end="03-06", trophy="Coupe Magnus",
                   playoffs=dict(kind="top", teams=8, best=[7, 7, 7])),
    # Elite League: 10 clubs, 54 games, two points for any win; the regular-season winner is league champion; the
    # top 8: two-game aggregate quarterfinals, then a Final Four weekend of single games with a third-place game
    "EIHL": dict(games=54, points="2pt", ot="so", gpg=3.15, start="09-13", end="04-05", trophy="Elite League playoff title", imports=14,
                 rs_title="Elite League title",
                 playoffs=dict(kind="europe", direct=8, wild=0, legs=[0], bronze=1, best=[2, 1, 1])),
    # Metal Ligaen: 9 clubs, 48 games (each other six times); the top 8, best-of-7
    "DEN": dict(games=48, points="3pt", ot="so", gpg=3.1, start="09-05", end="03-06", trophy="Danish championship",
                playoffs=dict(kind="top", teams=8, best=[7, 7, 7])),
    # EliteHockey Ligaen: 45 games (each other five times); the top 8; the best club left picks from the two lowest
    # every round; best-of-7; the champion wins the King's Cup
    "NOR": dict(games=45, points="3pt", ot="so", gpg=3.2, start="09-11", end="03-03", trophy="King's Cup", fill=True,
                playoffs=dict(kind="europe", direct=8, wild=0, pick="low2", best=[7, 7, 7])),
    # Mestis: 49 games; the top 8, re-seeded, best-of-7, a single third-place game; no promotion to the Liiga (a
    # closed league since its reform)
    "MESTIS": dict(games=49, points="3pt", ot="so", gpg=3.1, start="09-18", end="03-06", trophy="Mestis championship", fill=True,
                   playoffs=dict(kind="europe", direct=8, wild=0, bronze=1, best=[7, 7, 7])),
    # Swiss League: 50 games; 1-6 direct, 7-10 pre-playoffs; a fixed bracket (1 v 8, 4 v 5 ...), best-of-7; the
    # champion, if it applies, plays the National League's playout loser for promotion; two imports on the sheet
    "SL": dict(games=50, points="3pt", ot="so", gpg=3.25, start="09-12", end="02-28", trophy="Swiss League title", imports=2, fill=True,
               playoffs=dict(kind="europe", direct=6, wild=4, pre=3, bracket=True, best=[7, 7, 7]),
               promote=dict(into="NL", how="playout_series", apply=0.5)),
    # BCHL: 20 clubs in two conferences of two divisions (the world has no alignment: the best 16 overall), 54
    # games; the champion wins the BCHL Cup (the Fred Page Cup until 2025)
    "BCHL": dict(games=54, points="2pt", ot="so", gpg=3.4, start="09-19", end="03-29", trophy="BCHL Cup",
                 playoffs=dict(kind="top", teams=16, best=[7, 7, 7, 7])),
    "VHL": dict(games=58, points="2pt", ot="so", gpg=2.6, start="09-04", end="02-25", trophy="Petrov Cup",
                playoffs=dict(kind="top", teams=16, best=[7, 7, 7, 7])),
    "NAHL": dict(games=58, points="2pt", ot="so", gpg=3.1, start="09-12", end="04-11", trophy="Robertson Cup",
                 playoffs=dict(kind="top", teams=16, best=[3, 5, 5, 3])),
    "MHL": dict(games=58, points="2pt", ot="so", gpg=3.1, start="09-03", end="03-10", trophy="Kharlamov Cup",
                playoffs=dict(kind="top", teams=16, best=[5, 5, 7, 7])),
    "J20": dict(games=44, points="3pt", ot="so", gpg=3.5, start="09-13", end="03-08", trophy="Anton Cup",
                playoffs=dict(kind="top", teams=16, best=[3, 3, 3, 3])),
    "DNL": dict(games=36, points="3pt", ot="so", gpg=3.7, start="09-13", end="02-28", trophy="DNL championship",
                playoffs=dict(kind="top", teams=8, best=[3, 3, 3])),
    "U20CZE": dict(games=48, points="3pt", ot="so", gpg=3.5, start="09-05", end="03-01", trophy="Czech junior championship",
                   playoffs=dict(kind="top", teams=8, best=[5, 5, 5])),
    "U20FIN": dict(games=48, points="3pt", ot="so", gpg=3.4, start="09-06", end="03-08", trophy="Finnish junior championship",
                   playoffs=dict(kind="europe", pre=3, best=[5, 5, 5])),
    "U20SVK": dict(games=44, points="3pt", ot="so", gpg=3.6, start="09-06", end="03-01", trophy="Slovak junior championship",
                   playoffs=dict(kind="top", teams=8, best=[5, 5, 5])),
    "U21SUI": dict(games=44, points="3pt", ot="so", gpg=3.5, start="09-12", end="02-22", trophy="Swiss junior championship",
                   playoffs=dict(kind="top", teams=8, best=[5, 5, 5])),
    "USPORTS": dict(games=28, points="2pt", ot="so", gpg=3.3, start="10-03", end="02-07", trophy="University Cup",
                    playoffs=dict(kind="top", teams=8, best=[1, 1, 1])),
})
APPROXIMATE = frozenset(("VHL", "NAHL", "MHL", "J20", "DNL", "U20CZE", "U20FIN", "U20SVK", "U21SUI", "USPORTS"))

# v61: the top leagues' formats, corrected to 2025-26 (they were close but not right): the Czech Extraliga sends four
# straight to the quarterfinals and 5-12 play a best-of-5 wild-card round; the National League's play-in is two games
# on aggregate goals; and the leagues with a second tier in the world play for their places.
RULES["ELH"]["playoffs"] = dict(kind="europe", direct=4, wild=8, pre=5, best=[7, 7, 7])
RULES["NL"]["playoffs"] = dict(kind="europe", play_in="nl", best=[7, 7, 7])
RULES["SHL"]["playout"] = 7          # 13 v 14, best-of-7; the loser goes down when HockeyAllsvenskan's champion comes up
RULES["NL"]["playout"] = 7           # 13 v 14, best-of-7; the loser plays the Swiss League champion (if it applies)
# Sources (checked November 2026): Wikipedia's 2025-26 season pages for HockeyAllsvenskan, the SHL, the Czech
# Extraliga, the Slovak Extraliga, the DEL, the National League, the EIHL, Mestis and the BCHL; the 2024-25 Metal
# Ligaen page; ice.hockey (ICEHL game mode); alps.hockey (league mode); the Ligue Magnus 2025-26 press kit; the SIHF's
# Swiss League directives 2025-26; the DEL2 Spielordnung 2025-26; the Maxa liga 2025-26 presentation (bpa.cz);
# EliteHockey Ligaen (Wikipedia). The leagues in APPROXIMATE are still from general knowledge.

# the Memorial Cup: the OHL, WHL and QMJHL champions and a host club (the leagues take turns: the best club in the
# host league that did not win it), a round robin of single games, a semifinal (2 v 3) and the final
MEMORIAL = dict(leagues=("OHL", "WHL", "QMJHL"), name="Memorial Cup")

# the database's competition names, and how a club's division is written there
DIVISION_PREFIX = {
    "AHL": "American Hockey League", "ECHL": "ECHL", "KHL": "Kontinental Hockey League", "OHL": "Ontario Hockey League",
    "WHL": "Western Hockey League", "QMJHL": "Québec Maritimes Junior Hockey League", "USHL": "United States Hockey League",
    "NCAA": "NCAA",
}
COUNTRY = {"ALLSV": "SWE", "J20": "SWE", "CZE2": "CZE", "U20CZE": "CZE", "DEL2": "GER", "DNL": "GER", "ICEHL": "AUT", "ALPS": "AUT",
           "SVK": "SVK", "U20SVK": "SVK", "VHL": "RUS", "MHL": "RUS", "MAGNUS": "FRA", "EIHL": "GBR", "DEN": "DEN", "NOR": "NOR",
           "MESTIS": "FIN", "U20FIN": "FIN", "SL": "SUI", "U21SUI": "SUI", "BCHL": "CAN", "USPORTS": "CAN", "NAHL": "USA",
           "KHL": "RUS", "SHL": "SWE", "NL": "SUI", "LIIGA": "FIN", "ELH": "CZE", "DEL": "GER", "OHL": "CAN", "WHL": "CAN",
           "QMJHL": "CAN", "USHL": "USA", "NCAA": "USA", "AHL": "USA", "ECHL": "USA"}


def split_division(detailed):
    """'American Hockey League Atlantic Division' -> ('', 'Atlantic'); 'Québec Maritimes Junior Hockey League Eastern
    Conference' -> ('Eastern', 'Eastern'); 'NCAA Hockey East Division' -> ('', 'Hockey East'); no division -> ('', '')."""
    d = (detailed or "").strip()
    for prefix in sorted(DIVISION_PREFIX.values(), key=len, reverse=True):
        if d.startswith(prefix + " "):
            rest = d[len(prefix) + 1:].strip()
            if rest.endswith(" Conference"):
                name = rest[:-len(" Conference")].strip()
                return (name, name) if prefix != "NCAA" else ("", name)
            if rest.endswith(" Division"):
                return "", rest[:-len(" Division")].strip()
            return "", rest
    return "", ""
