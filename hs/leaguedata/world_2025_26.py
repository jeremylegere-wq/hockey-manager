"""The 2025-26 hockey world around the NHL: farm, development and feeder leagues (personal packs).

Team lists come from the 2025-26 season pages on Wikipedia (AHL, ECHL, OHL, WHL, QMJHL, SHL, Liiga, KHL, NL, DEL,
Czech Extraliga) and the NCAA Division I coaches list (Oct 2026). Affiliations are the 2025-26 NHL ones.

`mean` is the average "overall" of a regular in that league (overall = mean of the key attributes used by
hs.game.roster.player_value, 1-20 scale). NHL rostered skaters average about 10.55 with a spread (sd) of only ~0.67
in the MoneyPuck-derived pack, so league gaps are small numbers: AHL 9.2 is roughly NHL replacement level minus
half a point. These are our own estimates, not measured; tune freely.
"""

# abbr: (name, kind, level, country, games, mean rating, roster size, (age_min, age_max))
LEAGUES = {
    "AHL":  ("American Hockey League", "farm", 2, "USA/CAN", 72, 9.2, 26, (18, 40)),
    "ECHL": ("ECHL", "minor", 3, "USA/CAN", 72, 8.3, 24, (19, 40)),
    "KHL":  ("Kontinental Hockey League", "europe", 2, "RUS", 68, 9.6, 28, (17, 41)),
    "SHL":  ("Swedish Hockey League", "europe", 2, "SWE", 52, 9.3, 26, (17, 40)),
    "NL":   ("National League", "europe", 2, "SUI", 52, 9.2, 26, (17, 40)),
    "LIIGA": ("Liiga", "europe", 2, "FIN", 60, 9.0, 26, (17, 40)),
    "ELH":  ("Czech Extraliga", "europe", 2, "CZE", 52, 8.9, 26, (17, 41)),
    "DEL":  ("Deutsche Eishockey Liga", "europe", 3, "GER", 52, 8.7, 26, (18, 40)),
    "NCAA": ("NCAA Division I", "college", 4, "USA", 36, 8.2, 27, (18, 25)),
    "OHL":  ("Ontario Hockey League", "junior", 4, "CAN", 68, 7.6, 25, (16, 20)),
    "WHL":  ("Western Hockey League", "junior", 4, "CAN", 68, 7.6, 25, (16, 20)),
    "QMJHL": ("Quebec Maritimes Junior Hockey League", "junior", 4, "CAN", 64, 7.5, 25, (16, 20)),
}

# AHL club: NHL parent (2025-26)
AHL = {
    "Providence Bruins": "BOS", "Wilkes-Barre/Scranton Penguins": "PIT", "Charlotte Checkers": "FLA",
    "Bridgeport Islanders": "NYI", "Hershey Bears": "WSH", "Springfield Thunderbirds": "STL",
    "Lehigh Valley Phantoms": "PHI", "Hartford Wolf Pack": "NYR", "Laval Rocket": "MTL", "Syracuse Crunch": "TBL",
    "Cleveland Monsters": "CBJ", "Toronto Marlies": "TOR", "Rochester Americans": "BUF", "Utica Comets": "NJD",
    "Belleville Senators": "OTT", "Grand Rapids Griffins": "DET", "Chicago Wolves": "CAR", "Texas Stars": "DAL",
    "Manitoba Moose": "WPG", "Milwaukee Admirals": "NSH", "Iowa Wild": "MIN", "Rockford IceHogs": "CHI",
    "Ontario Reign": "LAK", "Colorado Eagles": "COL", "Henderson Silver Knights": "VGK",
    "Coachella Valley Firebirds": "SEA", "Bakersfield Condors": "EDM", "San Jose Barracuda": "SJS",
    "San Diego Gulls": "ANA", "Tucson Roadrunners": "UTA", "Abbotsford Canucks": "VAN", "Calgary Wranglers": "CGY",
}

ECHL = {
    "Wheeling Nailers": "PIT", "Maine Mariners": "BOS", "Adirondack Thunder": "NJD", "Reading Royals": "PHI",
    "Trois-Rivieres Lions": "MTL", "Worcester Railers": "NYI", "Norfolk Admirals": "WPG",
    "Greensboro Gargoyles": "CAR", "Florida Everblades": "STL", "South Carolina Stingrays": "WSH",
    "Atlanta Gladiators": "NSH", "Savannah Ghost Pirates": "FLA", "Jacksonville Icemen": "BUF",
    "Greenville Swamp Rabbits": "LAK", "Orlando Solar Bears": "TBL", "Fort Wayne Komets": "EDM",
    "Toledo Walleye": "DET", "Bloomington Bison": "NYR", "Indy Fuel": "CHI", "Kalamazoo Wings": "VAN",
    "Cincinnati Cyclones": "TOR", "Iowa Heartlanders": "MIN", "Kansas City Mavericks": "SEA",
    "Allen Americans": "OTT", "Idaho Steelheads": "DAL", "Tahoe Knight Monsters": "VGK", "Utah Grizzlies": "COL",
    "Rapid City Rush": "CGY", "Tulsa Oilers": "ANA", "Wichita Thunder": "SJS",
}

FEEDERS = {
    "OHL": ["Brantford Bulldogs", "Ottawa 67's", "Peterborough Petes", "Kingston Frontenacs", "Oshawa Generals",
            "Barrie Colts", "North Bay Battalion", "Niagara IceDogs", "Sudbury Wolves", "Brampton Steelheads",
            "Kitchener Rangers", "London Knights", "Owen Sound Attack", "Guelph Storm", "Erie Otters",
            "Windsor Spitfires", "Flint Firebirds", "Sault Ste. Marie Greyhounds", "Saginaw Spirit", "Sarnia Sting"],
    "WHL": ["Everett Silvertips", "Penticton Vees", "Prince George Cougars", "Kelowna Rockets", "Kamloops Blazers",
            "Spokane Chiefs", "Seattle Thunderbirds", "Portland Winterhawks", "Victoria Royals", "Tri-City Americans",
            "Wenatchee Wild", "Vancouver Giants", "Prince Albert Raiders", "Medicine Hat Tigers",
            "Edmonton Oil Kings", "Calgary Hitmen", "Brandon Wheat Kings", "Saskatoon Blades", "Regina Pats",
            "Red Deer Rebels", "Moose Jaw Warriors", "Swift Current Broncos", "Lethbridge Hurricanes"],
    "QMJHL": ["Moncton Wildcats", "Chicoutimi Sagueneens", "Newfoundland Regiment", "Charlottetown Islanders",
              "Quebec Remparts", "Cape Breton Eagles", "Halifax Mooseheads", "Saint John Sea Dogs",
              "Rimouski Oceanic", "Baie-Comeau Drakkar", "Rouyn-Noranda Huskies", "Blainville-Boisbriand Armada",
              "Drummondville Voltigeurs", "Shawinigan Cataractes", "Sherbrooke Phoenix", "Val-d'Or Foreurs",
              "Victoriaville Tigres", "Gatineau Olympiques"],
    "NCAA": ["Air Force", "American International", "Army", "Bentley", "Canisius", "Holy Cross", "Mercyhurst",
             "Niagara", "RIT", "Robert Morris", "Sacred Heart",                                    # Atlantic Hockey America
             "Michigan", "Michigan State", "Minnesota", "Notre Dame", "Ohio State", "Penn State", "Wisconsin",  # Big Ten
             "Augustana", "Bemidji State", "Bowling Green", "Ferris State", "Lake Superior State", "Michigan Tech",
             "Minnesota State", "Northern Michigan",                                                # CCHA
             "Brown", "Clarkson", "Colgate", "Cornell", "Dartmouth", "Harvard", "Princeton", "Quinnipiac", "RPI",
             "St. Lawrence", "Union", "Yale",                                                       # ECAC
             "Boston College", "Boston University", "Maine", "Merrimack", "New Hampshire", "Northeastern",
             "Providence", "UConn", "UMass", "UMass Lowell", "Vermont",                             # Hockey East
             "Arizona State", "Colorado College", "Denver", "Miami", "Minnesota Duluth", "North Dakota", "Omaha",
             "St. Cloud State", "St. Thomas", "Western Michigan",                                   # NCHC
             "Alaska", "Alaska Anchorage", "Lindenwood", "LIU", "Stonehill"],                       # independents
    "SHL": ["Brynas IF", "Djurgardens IF", "Farjestad BK", "Frolunda HC", "HV71", "Leksands IF", "Linkoping HC",
            "Lulea HF", "Malmo Redhawks", "Orebro HK", "Rogle BK", "Skelleftea AIK", "Timra IK", "Vaxjo Lakers"],
    "LIIGA": ["HIFK", "HPK", "Ilves", "Jukurit", "JYP", "KalPa", "Kiekko-Espoo", "KooKoo", "Karpat", "Lukko",
              "Pelicans", "SaiPa", "Sport", "Tappara", "TPS", "Assat"],
    "KHL": ["Lada Togliatti", "SKA Saint Petersburg", "HC Sochi", "Spartak Moscow", "Torpedo Nizhny Novgorod",
            "CSKA Moscow", "Dinamo Minsk", "Dynamo Moscow", "Lokomotiv Yaroslavl", "Severstal Cherepovets",
            "Shanghai Dragons", "Ak Bars Kazan", "Avtomobilist Yekaterinburg", "Metallurg Magnitogorsk",
            "Neftekhimik Nizhnekamsk", "Traktor Chelyabinsk", "Admiral Vladivostok", "Amur Khabarovsk",
            "Avangard Omsk", "Barys Astana", "Salavat Yulaev Ufa", "Sibir Novosibirsk"],
    "NL": ["HC Ajoie", "HC Ambri-Piotta", "SC Bern", "EHC Biel", "HC Davos", "HC Fribourg-Gotteron",
           "Geneve-Servette HC", "EHC Kloten", "Lausanne HC", "HC Lugano", "SCL Tigers", "SC Rapperswil-Jona Lakers",
           "ZSC Lions", "EV Zug"],
    "DEL": ["Augsburger Panther", "Eisbaren Berlin", "Fischtown Pinguins", "Dresdner Eislowen", "Lowen Frankfurt",
            "ERC Ingolstadt", "Iserlohn Roosters", "Kolner Haie", "Adler Mannheim", "EHC Red Bull Munchen",
            "Nurnberg Ice Tigers", "Schwenninger Wild Wings", "Straubing Tigers", "Grizzlys Wolfsburg"],
    "ELH": ["Pardubice", "Plzen", "Liberec", "Mountfield HK", "Trinec", "Karlovy Vary", "Sparta Praha",
            "Kometa Brno", "Ceske Budejovice", "Kladno", "Vitkovice", "Olomouc", "Mlada Boleslav", "Litvinov"],
}

# nationality mix of generated players per league (weights)
NATIONALITY_MIX = {
    "AHL": {"CAN": 45, "USA": 30, "SWE": 6, "FIN": 5, "CZE": 4, "RUS": 4, "SVK": 2, "GER": 2, "SUI": 2},
    "ECHL": {"CAN": 45, "USA": 45, "SWE": 2, "FIN": 2, "CZE": 2, "RUS": 2, "GER": 2},
    "OHL": {"CAN": 80, "USA": 12, "CZE": 2, "SVK": 2, "RUS": 2, "SWE": 1, "FIN": 1},
    "WHL": {"CAN": 78, "USA": 14, "CZE": 2, "SVK": 2, "RUS": 2, "SWE": 1, "FIN": 1},
    "QMJHL": {"CAN": 82, "USA": 6, "CZE": 3, "SVK": 3, "RUS": 2, "SUI": 2, "FIN": 1, "SWE": 1},
    "NCAA": {"USA": 70, "CAN": 25, "SWE": 2, "FIN": 1, "GER": 1, "SUI": 1},
    "SHL": {"SWE": 75, "FIN": 8, "CAN": 7, "USA": 5, "CZE": 3, "SVK": 2},
    "LIIGA": {"FIN": 80, "SWE": 5, "CAN": 6, "USA": 4, "CZE": 3, "SVK": 2},
    "KHL": {"RUS": 82, "CAN": 5, "USA": 3, "FIN": 3, "SWE": 2, "CZE": 2, "SVK": 2, "GER": 1},
    "NL": {"SUI": 70, "CAN": 10, "SWE": 6, "FIN": 6, "USA": 4, "CZE": 2, "GER": 2},
    "DEL": {"GER": 60, "CAN": 18, "USA": 12, "SWE": 3, "FIN": 3, "CZE": 2, "SUI": 2},
    "ELH": {"CZE": 85, "SVK": 7, "CAN": 3, "USA": 2, "FIN": 2, "SWE": 1},
}

# Small invented name pools for generated players (combinations are random; any match to a real person is chance)
NAMES = {
    "CAN": (["Liam", "Noah", "Owen", "Logan", "Carter", "Ethan", "Jack", "Ryan", "Tyler", "Cole", "Brayden", "Dylan",
             "Mason", "Nathan", "Luke", "Evan", "Connor", "Adam", "Mathieu", "Samuel", "Gabriel", "Felix", "Olivier",
             "Xavier", "Jordan", "Cameron", "Brody", "Hunter", "Parker", "Riley"],
            ["MacLeod", "Fraser", "Tremblay", "Gagnon", "Bouchard", "Cote", "Pelletier", "Bergeron", "Leblanc",
             "Campbell", "Murray", "Robertson", "Gillis", "MacDonald", "Chisholm", "Stewart", "Hudson", "Kerr",
             "Lavoie", "Fortin", "Gauthier", "Morin", "Ouellet", "Paquette", "Benoit", "Harrison", "Sinclair",
             "Doucette", "Arsenault", "Comeau", "Landry", "Thibodeau", "Boudreau", "McNeil", "Rankin", "Wilson"]),
    "USA": (["Jake", "Matt", "Mike", "Chris", "Nick", "Zach", "Josh", "Kyle", "Brett", "Ben", "Will", "Sam", "Max",
             "Drew", "Grant", "Trevor", "Jason", "Aaron", "Austin", "Colin", "Danny", "Joey", "Tommy", "Quinn"],
            ["Johnson", "Miller", "Anderson", "Peterson", "Olson", "Larson", "Hanson", "Murphy", "Sullivan", "Walsh",
             "Brennan", "Carlson", "Lindgren", "Novak", "Kowalski", "Schultz", "Becker", "Reed", "Parker", "Hayes",
             "Foley", "Donovan", "Callahan", "Gallagher", "Kelleher", "Thorson", "Engstrom", "Dahl"]),
    "SWE": (["Erik", "Oskar", "Lucas", "Viktor", "Gustav", "Axel", "Elias", "Hugo", "Isak", "Filip", "Anton",
             "Emil", "Jonas", "Linus", "Albin", "Melker"],
            ["Johansson", "Karlsson", "Nilsson", "Eriksson", "Larsson", "Andersson", "Lindqvist", "Berg", "Holm",
             "Sandberg", "Wikstrom", "Lundgren", "Hedman", "Ekholm", "Forsberg", "Bergqvist", "Sjoberg", "Nyberg"]),
    "FIN": (["Mikko", "Juho", "Aleksi", "Eetu", "Joonas", "Kasper", "Otto", "Valtteri", "Lauri", "Niko", "Jesse",
             "Rasmus", "Aatu", "Eemeli"],
            ["Virtanen", "Korhonen", "Nieminen", "Makinen", "Laine", "Heikkinen", "Koskinen", "Jarvinen", "Lehtonen",
             "Saarinen", "Salminen", "Kallio", "Rantanen", "Hakala", "Lindholm", "Mattila"]),
    "RUS": (["Alexei", "Dmitri", "Ivan", "Nikita", "Sergei", "Andrei", "Pavel", "Kirill", "Maxim", "Artyom",
             "Yegor", "Danil", "Ilya", "Matvei"],
            ["Ivanov", "Smirnov", "Kuznetsov", "Popov", "Sokolov", "Lebedev", "Kozlov", "Novikov", "Morozov",
             "Volkov", "Fedorov", "Mikhailov", "Orlov", "Zaitsev", "Belov", "Gusev"]),
    "CZE": (["Jakub", "Tomas", "Martin", "Ondrej", "David", "Lukas", "Matej", "Filip", "Adam", "Vojtech", "Radek"],
            ["Novak", "Svoboda", "Dvorak", "Cerny", "Prochazka", "Kucera", "Vesely", "Hajek", "Kral", "Benes",
             "Pokorny", "Marek", "Sedlacek", "Zeman"]),
    "SVK": (["Marek", "Michal", "Juraj", "Peter", "Samuel", "Dominik", "Patrik", "Simon"],
            ["Horvath", "Kovac", "Varga", "Toth", "Nagy", "Balaz", "Molnar", "Hudak", "Polak", "Benko"]),
    "SUI": (["Luca", "Nico", "Fabio", "Janis", "Reto", "Damien", "Yannick", "Sven", "Timo", "Andrea"],
            ["Meier", "Muller", "Keller", "Brunner", "Frei", "Huber", "Steiner", "Fischer", "Graf", "Moser",
             "Baumann", "Zurcher"]),
    "GER": (["Leon", "Moritz", "Tobias", "Jonas", "Lukas", "Maximilian", "Dominik", "Marcel", "Kai", "Florian"],
            ["Schmidt", "Schneider", "Fischer", "Weber", "Wagner", "Becker", "Hoffmann", "Krause", "Wolf", "Braun",
             "Zimmermann", "Hartmann"]),
}
