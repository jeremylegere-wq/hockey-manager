"""The NHL's 2025-26 structure and rules, as plain data.

Real club names are trademarks; this file is only used to build *personal* packs (contains_real_names = true).
Sources: NHL 2025-26 season dates and Olympic break (FloHockey, Fox Sports), points/tiebreakers/playoff format
(Sofascore, Elite Prospects). The 26/24/32 division/conference/other-conference game split and 20-minute
sudden-death playoff overtime are from general knowledge; the split is checked arithmetically (26+24+32 = 82).
"""
TEAMS = {   # MoneyPuck abbreviation: (city, nickname, conference, division)
    "BOS": ("Boston", "Bruins", "Eastern", "Atlantic"), "BUF": ("Buffalo", "Sabres", "Eastern", "Atlantic"),
    "DET": ("Detroit", "Red Wings", "Eastern", "Atlantic"), "FLA": ("Florida", "Panthers", "Eastern", "Atlantic"),
    "MTL": ("Montréal", "Canadiens", "Eastern", "Atlantic"), "OTT": ("Ottawa", "Senators", "Eastern", "Atlantic"),
    "TBL": ("Tampa Bay", "Lightning", "Eastern", "Atlantic"), "TOR": ("Toronto", "Maple Leafs", "Eastern", "Atlantic"),
    "CAR": ("Carolina", "Hurricanes", "Eastern", "Metropolitan"), "CBJ": ("Columbus", "Blue Jackets", "Eastern", "Metropolitan"),
    "NJD": ("New Jersey", "Devils", "Eastern", "Metropolitan"), "NYI": ("New York", "Islanders", "Eastern", "Metropolitan"),
    "NYR": ("New York", "Rangers", "Eastern", "Metropolitan"), "PHI": ("Philadelphia", "Flyers", "Eastern", "Metropolitan"),
    "PIT": ("Pittsburgh", "Penguins", "Eastern", "Metropolitan"), "WSH": ("Washington", "Capitals", "Eastern", "Metropolitan"),
    "CHI": ("Chicago", "Blackhawks", "Western", "Central"), "COL": ("Colorado", "Avalanche", "Western", "Central"),
    "DAL": ("Dallas", "Stars", "Western", "Central"), "MIN": ("Minnesota", "Wild", "Western", "Central"),
    "NSH": ("Nashville", "Predators", "Western", "Central"), "STL": ("St. Louis", "Blues", "Western", "Central"),
    "UTA": ("Utah", "Mammoth", "Western", "Central"), "WPG": ("Winnipeg", "Jets", "Western", "Central"),
    "ANA": ("Anaheim", "Ducks", "Western", "Pacific"), "CGY": ("Calgary", "Flames", "Western", "Pacific"),
    "EDM": ("Edmonton", "Oilers", "Western", "Pacific"), "LAK": ("Los Angeles", "Kings", "Western", "Pacific"),
    "SEA": ("Seattle", "Kraken", "Western", "Pacific"), "SJS": ("San Jose", "Sharks", "Western", "Pacific"),
    "VAN": ("Vancouver", "Canucks", "Western", "Pacific"), "VGK": ("Vegas", "Golden Knights", "Western", "Pacific"),
}

RULES = {
    "era_preset": "nhl",                 # overtime/ties/points by era, 84 games from 2026-27 (hs/league/eras.py)
    "name": "NHL 2025-26",
    "season": {"start": "2025-10-07", "end": "2026-04-16",
               "breaks": [{"name": "Olympic break", "start": "2026-02-06", "end": "2026-02-24"}]},
    "schedule": {"games_per_team": 82,
                 "same_division": {"games": 4, "reduced_games": 3, "reduced_opponents_per_team": 2},
                 "same_conference": {"games": 3}, "other_conference": {"games": 2}},
    "points": {"win": 2, "ot_loss": 1, "loss": 0},
    "tiebreakers": ["points_pct", "regulation_wins", "regulation_overtime_wins", "wins",
                    "head_to_head_points", "goal_diff", "goals_for"],
    "playoffs": {"format": "division_wildcard", "per_division": 3, "wildcards_per_conference": 2,
                 "series_length": 7, "home_pattern": [1, 1, 0, 0, 1, 0, 1]},
}
