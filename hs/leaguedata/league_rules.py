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

# the Memorial Cup: the OHL, WHL and QMJHL champions and a host club (the leagues take turns: the best club in the
# host league that did not win it), a round robin of single games, a semifinal (2 v 3) and the final
MEMORIAL = dict(leagues=("OHL", "WHL", "QMJHL"), name="Memorial Cup")

# the database's competition names, and how a club's division is written there
DIVISION_PREFIX = {
    "AHL": "American Hockey League", "ECHL": "ECHL", "KHL": "Kontinental Hockey League", "OHL": "Ontario Hockey League",
    "WHL": "Western Hockey League", "QMJHL": "Québec Maritimes Junior Hockey League", "USHL": "United States Hockey League",
    "NCAA": "NCAA",
}
COUNTRY = {"KHL": "RUS", "SHL": "SWE", "NL": "SUI", "LIIGA": "FIN", "ELH": "CZE", "DEL": "GER", "OHL": "CAN", "WHL": "CAN",
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
