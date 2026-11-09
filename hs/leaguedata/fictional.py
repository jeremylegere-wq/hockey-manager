"""Invented clubs for the bundled mock world (hs/tools/make_mock_league.py, build_world --fictional).

Every place, nickname and club here is made up. Any match with a real club, town or school is chance; the names are
built from small pools so that the world has no real trademarks in it.

  NHL_CLUBS         the 32 top-league clubs: (city, nickname, abbr, conference, division)
  club_names(kind, n, rng)   n distinct names for a lower league: AHL, ECHL, OHL, WHL, QMJHL, NCAA, SHL, LIIGA, KHL,
                    NL, DEL, ELH
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

CONFERENCES = {"Eastern": ["Lakes", "Coast"], "Western": ["Plains", "Mountain"]}

NHL_CLUBS = [
    ("Port Halvard", "Mariners", "PHM", "Eastern", "Lakes"), ("Brackenridge", "Foxes", "BRF", "Eastern", "Lakes"),
    ("Stonehaven", "Wardens", "SHW", "Eastern", "Lakes"), ("Lake Corran", "Pike", "LCP", "Eastern", "Lakes"),
    ("Ashford", "Thunder", "ATH", "Eastern", "Lakes"), ("Northgate", "Ravens", "NGR", "Eastern", "Lakes"),
    ("Millbrook", "Bears", "MLB", "Eastern", "Lakes"), ("Cedar Hollow", "Herons", "CHH", "Eastern", "Lakes"),
    ("Seabrook", "Admirals", "SBA", "Eastern", "Coast"), ("Marlow Bay", "Gulls", "MBG", "Eastern", "Coast"),
    ("Westerly", "Breakers", "WBR", "Eastern", "Coast"), ("Fenwick Harbour", "Kings", "FHK", "Eastern", "Coast"),
    ("Tidewater", "Ospreys", "TWO", "Eastern", "Coast"), ("Carrow Point", "Anchors", "CPA", "Eastern", "Coast"),
    ("Saltmarsh", "Rays", "SMR", "Eastern", "Coast"), ("Dunmore", "Sails", "DMS", "Eastern", "Coast"),
    ("Redfield", "Stampede", "RFS", "Western", "Plains"), ("Kestrel Prairie", "Hawks", "KPH", "Western", "Plains"),
    ("Wheatland", "Wolves", "WLW", "Western", "Plains"), ("Harlan", "Bison", "HLB", "Western", "Plains"),
    ("Crowsnest", "Coyotes", "CRC", "Western", "Plains"), ("Oakhurst", "Rangers", "OKR", "Western", "Plains"),
    ("Fort Merrin", "Voyageurs", "FMV", "Western", "Plains"), ("Silver Creek", "Miners", "SCM", "Western", "Plains"),
    ("Highpeak", "Condors", "HPC", "Western", "Mountain"), ("Glacier Bay", "Orcas", "GBO", "Western", "Mountain"),
    ("Timberline", "Lynx", "TLL", "Western", "Mountain"), ("Copper Ridge", "Smelters", "CRS", "Western", "Mountain"),
    ("Eagle Pass", "Falcons", "EPF", "Western", "Mountain"), ("Snowmere", "Yetis", "SMY", "Western", "Mountain"),
    ("Ironwood", "Hammers", "IWH", "Western", "Mountain"), ("Cascade Ridge", "Pumas", "CRP", "Western", "Mountain"),
]

# league -> (place pool, nickname pool or format)
_NA_PLACES = ["Alder", "Ashbury", "Bayfield", "Birchmont", "Blackwater", "Bramley", "Briarcliff", "Calder", "Cardiff Glen",
              "Cinder", "Clearwater", "Copperfield", "Crestview", "Dalton", "Deerfield", "Eastmoor", "Elmhurst", "Falkirk",
              "Fernhill", "Flintridge", "Garnet", "Glenmore", "Gray Harbour", "Greywood", "Hadley", "Halcyon", "Hawthorn",
              "Hollis", "Ivy Bridge", "Juniper", "Kingsford", "Lakemont", "Larchwood", "Linden", "Maplecrest", "Marsden",
              "Mistral", "Northfield", "Oakridge", "Otter Lake", "Pinehurst", "Quarry Bay", "Ravenna", "Redcliff",
              "Rockport", "Rosedale", "Rushmore", "Sandford", "Shalebank", "Southfork", "Springdale", "Stillwater",
              "Sundown", "Thornbury", "Tillman", "Underhill", "Valemont", "Wexford", "Whitcomb", "Winterbourne",
              "Wolf Hollow", "Yarrow", "Zephyr Falls", "Aspen Cove", "Baxter", "Cobalt", "Dunwich", "Evergreen",
              "Fairmont", "Gannet", "Harrow", "Iron Bay", "Jasper Ford", "Kelso", "Lowell Park", "Moorhead", "Norwick",
              "Orchard", "Penrose", "Quillan", "Ridgeway", "Sable Island", "Tamarack", "Upland", "Verdant", "Windham"]
_NICK = ["Bulldogs", "Wolves", "Hawks", "Owls", "Rapids", "Blazers", "Pioneers", "Ironmen", "Raiders", "Storm", "Jets",
         "Thunder", "Lancers", "Barons", "Stags", "Badgers", "Otters", "Cardinals", "Mustangs", "Sharks", "Comets",
         "Foxes", "Rebels", "Royals", "Spartans", "Titans", "Knights", "Tigers", "Griffins", "Falcons", "Pirates",
         "Rockets", "Bruisers", "Trappers", "Loggers", "Drillers", "Steelheads", "Rovers", "Phantoms", "Outlaws",
         "Mariners", "Gladiators", "Hornets", "Marauders", "Admirals", "Eagles", "Cougars", "Wildcats", "Generals",
         "Silvertips", "Colts", "Chargers", "Sabres", "Patriots", "Voyageurs", "Wranglers", "Monarchs", "Ospreys"]
_SE = ["Alvik", "Bergsjo", "Dalby", "Ekeby", "Falun Ost", "Gavle Norr", "Hallby", "Ingelsta", "Jarna", "Kolsva", "Lidhem",
       "Mora Syd", "Norrby", "Orsjo", "Piteby", "Ramsjo", "Skarby", "Tyrsta", "Ulvik", "Vasterfall", "Alsta", "Brunnby"]
_FI = ["Haukila", "Ilmari", "Joensuu Nord", "Kaarela", "Lahtinen", "Mäntylä", "Nokela", "Oulunki", "Pohja", "Raahela",
       "Saarela", "Tuuli", "Uusikoski", "Vaasala", "Ylitalo", "Kemijoki", "Lappeen", "Koivula", "Pirkka", "Sisu"]
_RU = ["Belgorod Ost", "Chelny", "Dmitrovsk", "Ekaterinsk", "Gorodets", "Ilmen", "Kamensk", "Lipetsk Nord", "Murmansk Syd",
       "Nevsk", "Orenburg Ost", "Perm Volga", "Ryazansk", "Sarapul", "Tobolsk", "Ulyansk", "Volzhsk", "Yaroslav Nord",
       "Zarechny", "Angarsk", "Bratsk Ost", "Kirovsk"]
_CH = ["Aarbach", "Biel See", "Chur Alp", "Davoser Tal", "Emmen", "Freiburg Nord", "Gstaad", "Herisau", "Interlaken Ost",
       "Jona", "Kloster", "Lenzburg", "Martigny", "Nyon", "Olten", "Pratteln", "Rheintal", "Sion Alp"]
_DE = ["Altenburg", "Bremer Nord", "Cuxhaven", "Dortmunder Ost", "Erfurter", "Flensburger", "Gießener", "Hildesheimer",
       "Ingolstädter", "Jenaer", "Kasseler", "Landshuter", "Memminger", "Neuwieder", "Oldenburger", "Passauer", "Regensburger",
       "Stuttgarter Nord"]
_CZ = ["Beroun", "Chrudim", "Dobruska", "Frydek", "Havlickuv", "Jihlava Nord", "Kolin", "Louny", "Mlada Ostrava", "Nachod",
       "Opava Syd", "Prerov", "Rokycany", "Sumperk", "Tabor", "Usti Labe", "Vsetin", "Znojmo Ost"]
_COLLEGE = ["Alder", "Ashbury", "Bayfield", "Calder", "Crestview", "Dalton", "Eastmoor", "Fairmont", "Glenmore", "Hadley",
            "Kingsford", "Lakemont", "Marsden", "Northfield", "Oakridge", "Pinehurst", "Redcliff", "Rosedale", "Stillwater",
            "Thornbury", "Upland", "Valemont", "Wexford", "Whitcomb", "Yarrow", "Aspen", "Baxter", "Cobalt", "Dunwich",
            "Evergreen", "Gannet", "Harrow", "Kelso", "Moorhead", "Norwick", "Penrose", "Ridgeway", "Tamarack", "Windham"]
_COLLEGE_FORMS = ["{} University", "{} State", "{} College", "{} Tech", "{} Polytechnic"]


def _pick_unique(pool, n, rng, used=None):
    """n items from the pool, none twice until the pool runs out (then it starts over); `used` is shared between calls so
    that two leagues do not take the same town while there are unused ones left."""
    used = used if used is not None else set()
    fresh = [x for x in pool if x not in used]
    rng.shuffle(fresh)
    out = fresh[:n]
    used.update(out)
    while len(out) < n:
        again = list(pool)
        rng.shuffle(again)
        out += again[: n - len(out)]
    return out


def club_names(kind, n, rng, used=None):
    """n distinct invented names for a lower league (kind = the league's abbreviation). Pass the same `used` set for
    every league of one world."""
    if kind in ("AHL", "ECHL", "OHL", "WHL", "QMJHL"):
        places = _pick_unique(_NA_PLACES, n, rng, used)
        nicks = _pick_unique(_NICK, n, rng, set())
        return [f"{p} {k}" for p, k in zip(places, nicks)]
    if kind == "NCAA":
        places = _pick_unique(_COLLEGE, min(n, len(_COLLEGE)), rng, set())
        first = {p: rng.randrange(len(_COLLEGE_FORMS)) for p in places}
        out = [_COLLEGE_FORMS[first[p]].format(p) for p in places]
        k = 1
        while len(out) < n:                              # a second school in some towns, in another form
            out += [_COLLEGE_FORMS[(first[p] + k) % len(_COLLEGE_FORMS)].format(p) for p in places][: n - len(out)]
            k += 1
        return out
    pools = {"SHL": (_SE, "{} IF"), "LIIGA": (_FI, "{} HT"), "KHL": (_RU, "HK {}"), "NL": (_CH, "EHC {}"),
             "DEL": (_DE, "{} Eishockey"), "ELH": (_CZ, "HC {}")}
    pool, fmt = pools[kind]
    return [fmt.format(p) for p in _pick_unique(pool, n, rng, set())]


def load_clubs(path):
    """Read your own 32 clubs from a CSV with the columns city, nickname, abbr, conference, division (abbr may be
    blank: it is made from the city and nickname). Returns the list make_mock_league uses in place of NHL_CLUBS.
    Raises ValueError listing every problem: the league needs 32 distinct clubs in 2 conferences of 2 divisions,
    8 clubs in each division (the schedule and playoff format are built for that shape)."""
    rows, problems = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        cols = [(c or "").strip().lower() for c in (rd.fieldnames or [])]
        for need in ("city", "nickname", "conference", "division"):
            if need not in cols:
                raise ValueError(f"{path}: missing column '{need}' (columns are city, nickname, abbr, conference, division)")
        for n, r in enumerate(rd, start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            if not any(r.values()):
                continue
            for need in ("city", "nickname", "conference", "division"):
                if not r.get(need):
                    problems.append(f"row {n}: '{need}' is empty")
            rows.append(r)
    used, out = set(), []
    for n, r in enumerate(rows, start=2):
        abbr = r.get("abbr", "").upper()
        if not abbr:
            letters = "".join(w[0] for w in (r["city"] + " " + r["nickname"]).split())
            abbr = (r["city"].replace(" ", "")[:2] + r["nickname"][:1] + letters).upper()[:3]
        base, k = abbr, 2
        while abbr in used:
            abbr, k = base[:2] + str(k), k + 1
        used.add(abbr)
        out.append((r["city"], r["nickname"], abbr, r["conference"], r["division"]))
    if len(out) != 32:
        problems.append(f"the league needs exactly 32 clubs, the file has {len(out)}")
    names = Counter(f"{c} {n}".lower() for c, n, *_ in out)
    problems += [f"'{k}' appears {v} times" for k, v in names.items() if v > 1]
    divs = Counter((c, d) for *_, c, d in out)
    confs = {c for c, _ in divs}
    if len(confs) != 2 or len(divs) != 4 or any(v != 8 for v in divs.values()):
        problems.append("use 2 conferences, each with 2 divisions of 8 clubs (found "
                        + ", ".join(f"{c}/{d}: {v}" for (c, d), v in sorted(divs.items())) + ")")
    if problems:
        raise ValueError("clubs file problems:\n  " + "\n  ".join(problems))
    return out
