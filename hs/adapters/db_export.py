"""Adapter: your plain-English export of a classic hockey-management database  ->  data pack (format 0.1 + v38 extras).

    python -m hs.adapters.db_export <export folder> <out_pack_dir> [--season 2026] [--nhl-roster 23] [--free-agents 600]
    python -m hs.ingest <out_pack_dir> <game.db>

PERSONAL USE ONLY. The export is your own decoding of a community database for a commercial game; the pack this
writes holds that data, is marked redistributable=false and must never be published, shared or committed (packs/ and
save/ are git-ignored). Nothing from it ships with this program.

The export folder is searched (recursively) for these files, the newest milestone first:
  players_hockey_profiles_*.csv     ratings: 42 attributes, current/potential ability, position and role ratings,
                                     height, weight, hand (one row per player record)
  staff_normalized.csv              people: names, birth dates, nationality, the club a player plays for and the club
                                     he is contracted to, salary and contract expiry, personality, staff jobs
  clubs_lookup.csv                  clubs: league (division), conference division, arena and capacity, market size,
                                     reputation, founding year, rivals, captain and alternates
  player_rights_normalized.csv      which NHL club holds the rights to an unsigned player

What the pack holds (docs/DB_IMPORT.md has the field-by-field mapping):
  * leagues: the NHL and the 13 leagues of the game world (AHL, ECHL, KHL, SHL, NL, Liiga, Extraliga, DEL, NCAA, OHL,
    WHL, QMJHL, USHL); every club in them, AHL/ECHL clubs tied to their NHL parents
  * players: everyone playing in those leagues, everyone contracted to an NHL club (the best `--nhl-roster` per club
    on the NHL roster, the rest assigned to the AHL affiliate), NHL draft-rights holders wherever they play, and the
    best `--free-agents` unattached players; players born after season-15 (the database's future generated players)
    are left out
  * ratings.csv (native), attributes.csv (engine attributes derived with an engine scale fitted to the NHL's dressed
    players, engine_scale.json), development.csv (potential from potential ability)
  * personality.csv and hidden.csv from the personality fields, re-centred on the game's scale
  * contracts.csv (salary as the cap hit, expiry), draft_rights.csv, leadership.csv (captains), staff.csv (NHL clubs'
    coaches, scouts, physios and general managers: names only, their ratings are generated), club_profiles.csv,
    rivalries.json
  * no statistics history (careers start in the save)
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import random
import re
import statistics as st
from pathlib import Path

from ..attributes import (NATIVE_ATTRS, RATING_COLS, derive, fit_ability, fit_scale, overall_from_ability, primary_position)
from ..leaguedata import nhl_2025_26 as NHL
from ..leaguedata import world_2025_26 as W

NHL_IDS = {"ANA": 1, "BOS": 4, "BUF": 5, "CAR": 6, "CBJ": 7, "CGY": 8, "CHI": 9, "COL": 10, "DAL": 11, "DET": 12, "EDM": 13,
           "FLA": 14, "LAK": 16, "MIN": 17, "MTL": 18, "NJD": 20, "NSH": 21, "NYI": 22, "NYR": 23, "OTT": 24, "PHI": 25, "PIT": 26,
           "SEA": 28, "SJS": 29, "STL": 30, "TBL": 32, "TOR": 33, "UTA": 34, "VAN": 35, "VGK": 36, "WPG": 37, "WSH": 38}
ABBR_ALIASES = {"LA": "LAK", "NAS": "NSH", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTH": "UTA", "MON": "MTL", "WAS": "WSH"}
DIVISIONS = {   # the database's league ("Division") -> our league abbreviation
    "National Hockey League": "NHL", "American Hockey League": "AHL", "ECHL": "ECHL", "Kontinental Hockey League": "KHL",
    "Swedish Hockey League": "SHL", "Swiss National League": "NL", "Finnish Liiga": "LIIGA", "Czech Tipsport Extraliga": "ELH",
    "Deutsche Eishockey Liga": "DEL", "National Collegiate Athletic Association": "NCAA", "Ontario Hockey League": "OHL",
    "Western Hockey League": "WHL", "Québec Maritimes Junior Hockey League": "QMJHL", "United States Hockey League": "USHL",
}
EXTRA_LEAGUES = {"USHL": ("United States Hockey League", "junior", 4, "USA", 62, 7.4, 25, (16, 21))}
# v44: the next leagues down, from the database (docs/LEAGUES.md "World leagues"): the database's name -> (our
# abbreviation, kind). They are simulated a season at a time; their country, level, age limit, size, strength and
# nationality mix come from the database at import, their game count from its career history (hs/adapters/db_history.py).
DB_LEAGUES = {
    "Swedish HockeyAllsvenskan": ("ALLSV", "europe"), "Russian Vserossiyskaya Hokkeynaya Liga": ("VHL", "europe"),
    "Slovenská Tipsport Liga": ("SVK", "europe"), "win2day ICE Hockey League": ("ICEHL", "europe"),
    "Norwegian EliteHockey Ligaen": ("NOR", "europe"), "Finnish Mestis": ("MESTIS", "europe"),
    "Elite Ice Hockey League": ("EIHL", "europe"), "Deutsche Eishockey Liga 2": ("DEL2", "europe"),
    "Czech Maxa liga": ("CZE2", "europe"), "Sky Swiss League": ("SL", "europe"),
    "French Synerglace Ligue Magnus": ("MAGNUS", "europe"), "Danish Metal Ligaen": ("DEN", "europe"),
    "Alps Hockey League": ("ALPS", "europe"),
    "Swedish U20 Nationell": ("J20", "junior"), "Finnish U20 SM-sarja": ("U20FIN", "junior"),
    "Russian Molodyozhnaya Hokkeinaya Liga": ("MHL", "junior"), "Czech DHL Extraliga junioru": ("U20CZE", "junior"),
    "Swiss Junioren Elite": ("U21SUI", "junior"), "Deutsche Nachwuchs Liga": ("DNL", "junior"),
    "Slovenská Extraliga juniorov": ("U20SVK", "junior"), "British Columbia Hockey League": ("BCHL", "junior"),
    "North American Hockey League": ("NAHL", "junior"),
    "Canadian USports": ("USPORTS", "college"),
}
DB_GAMES = {"europe": 50, "junior": 60, "college": 28}            # until the history gives the real count
NATION_CODE = {"Sweden": "SWE", "Russia": "RUS", "Slovakia": "SVK", "Austria": "AUT", "Norway": "NOR", "Finland": "FIN",
               "Great Britain": "GBR", "Germany": "GER", "Czechia": "CZE", "Switzerland": "SUI", "France": "FRA",
               "Denmark": "DEN", "United States": "USA", "Canada": "CAN", "Italy": "ITA", "Slovenia": "SLO"}
PROFILE_MAP = {"position_goalie": "pos_g", "position_left_defence": "pos_ld", "position_right_defence": "pos_rd",
               "position_left_wing": "pos_lw", "position_centre": "pos_c", "position_right_wing": "pos_rw",
               "offensive_role_rating": "role_off", "defensive_role_rating": "role_def"}
STAFF_ROLES = {"Head Coach": "HC", "GM/Head Coach": "HC", "Coach": "AC", "Scout": "SCOUT", "Physio": "MED",
               "General Manager": "GM", "Director of Personnel": "SCOUT_DIR", "Assistant GM": "AGM"}
MIN_SALARY = 775_000
NEED_ACTIVE = {"G": 2, "D": 7, "F": 13}
PLAYER_FIELDS = ["player_id", "first_name", "last_name", "birth_date", "position", "shoots", "height_cm", "weight_kg",
                 "nationality", "team_id", "status", "club_id", "jersey_number"]
FILES = {"profiles": "players_hockey_profiles_*.csv", "staff": "staff_normalized.csv", "clubs": "clubs_lookup.csv",
         "rights": "player_rights_normalized.csv"}
OPTIONAL_FILES = {"comps": "club_competitions_lookup.csv"}


def find(root, pattern):
    hits = sorted(Path(root).rglob(pattern), key=lambda p: str(p))
    if not hits:
        raise FileNotFoundError(f"{pattern} not found under {root}")
    return hits[-1]


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        yield from csv.DictReader(fh)


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _int(v, default=None):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def dob(text):
    """'13.1.1997' -> '1997-01-13' (None if unreadable)."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$", text or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def group(pos):
    return "G" if pos == "G" else "D" if pos == "D" else "F"


def _norm(name):
    return re.sub(r"[^a-z]", "", (name or "").lower().replace("é", "e").replace("è", "e"))


def standardise(rows, keys, mean=10.5, sd=3.2):
    """Rank-preserving re-centring of 1-20 values on the game's scale (personality and hidden attributes)."""
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        if len(vals) < 10:
            continue
        m, s = st.mean(vals), st.pstdev(vals) or 1.0
        for r in rows:
            if r.get(k) is not None:
                r[k] = max(1, min(20, round(mean + (r[k] - m) * sd / s)))
    return rows


def build(src, out, season=2026, nhl_roster=23, free_agents=600, seed=1):
    src, out = Path(src), Path(out)
    rng = random.Random(f"dbx-{seed}")
    out.mkdir(parents=True, exist_ok=True)
    paths = {k: find(src, v) for k, v in FILES.items()}
    stats = {"sources": {k: str(v.relative_to(src)) if str(v).startswith(str(src)) else str(v) for k, v in paths.items()}}
    on = datetime.date(season, 10, 1)

    # ---------------------------------------------------------------- leagues and clubs
    world_def = dict(W.LEAGUES)
    world_def.update(EXTRA_LEAGUES)
    leagues = [dict(league_id=1, name="National Hockey League", abbr="NHL", country="USA/CAN", level=1, games_per_team=82)]
    world, lid_of = {}, {"NHL": 1}
    for k, (abbr, (name, kind, level, country, games, mean, roster, ages)) in enumerate(world_def.items()):
        lid = 100 + k
        leagues.append(dict(league_id=lid, name=name, abbr=abbr, country=country, level=level, games_per_team=games))
        world[str(lid)] = dict(abbr=abbr, kind=kind, level=level, games=games, mean=mean, roster=roster, age_min=ages[0], age_max=ages[1])
        lid_of[abbr] = lid
    # v44: the database's next leagues (DB_LEAGUES); their numbers are filled in once the players are known
    comps = {}
    try:
        comps = {r.get("Name"): r for r in read(find(src, OPTIONAL_FILES["comps"]))}
    except FileNotFoundError:
        pass
    divisions = dict(DIVISIONS)
    db_lids = {}
    for k, (dname, (abbr, kind)) in enumerate(DB_LEAGUES.items()):
        cm = comps.get(dname, {})
        lid = 100 + len(world_def) + k
        upper = _int(cm.get("Upper Age Limit"), 0) or 0
        level = 3 if kind == "europe" else 4
        country = NATION_CODE.get(cm.get("Nation"), "")
        name = cm.get("Short Name") if cm.get("Short Name") and len(cm.get("Short Name")) > 4 else dname
        leagues.append(dict(league_id=lid, name=dname, abbr=abbr, country=country, level=level, games_per_team=DB_GAMES[kind]))
        world[str(lid)] = dict(abbr=abbr, kind=kind, level=level, games=DB_GAMES[kind], mean=8.0, roster=25,
                               age_min=15 if kind == "junior" else 17, age_max=upper or (25 if kind == "college" else 40),
                               country=country, source="database", short=name)
        lid_of[abbr] = lid
        divisions[dname] = abbr
        db_lids[lid] = abbr
    clubs = {}                                            # database club id -> our team row
    nhl_by_name = {}
    raw_clubs = list(read(paths["clubs"]))
    tid = 1000
    for c in sorted(raw_clubs, key=lambda c: (c.get("Division") or "", c.get("Long name") or "")):
        lg = divisions.get(c.get("Division"))
        if not lg:
            continue
        if lg == "NHL":
            ab = ABBR_ALIASES.get(c.get("Abbreviation"), c.get("Abbreviation"))
            if ab not in NHL_IDS:
                continue
            city, nick, conf, div = NHL.TEAMS.get(ab, (c.get("NameShort"), c.get("NickName"), "", ""))
            m = re.search(r"National Hockey League (\w+) Division", c.get("DetailedDivision") or "")
            div = m.group(1) if m else div
            conf = "Eastern" if div in ("Atlantic", "Metropolitan") else "Western" if div in ("Central", "Pacific") else conf
            row = dict(team_id=NHL_IDS[ab], league_id=1, name=city or c.get("NameShort"), nickname=nick or c.get("NickName"),
                       abbr=ab, conference=conf, division=div)
            nhl_by_name[c.get("Long name")] = row["team_id"]
        else:
            row = dict(team_id=tid, league_id=lid_of[lg], name=c.get("Long name") or c.get("lookup_name"), nickname="",
                       abbr=(c.get("Abbreviation") or "")[:5] or "CLB", parent_team_id="")
            tid += 1
        row["_db"] = c
        clubs[c["club_id"]] = row
    parents = {_norm(k): v for k, v in list(W.AHL.items()) + list(W.ECHL.items())}
    for row in clubs.values():
        if row["league_id"] in (lid_of["AHL"], lid_of["ECHL"]):
            par = parents.get(_norm(row["name"]))
            row["parent_team_id"] = NHL_IDS.get(par, "") if par else ""
    affiliate = {r["parent_team_id"]: r["team_id"] for r in clubs.values() if r["league_id"] == lid_of["AHL"] and r.get("parent_team_id")}
    nhl_ids = set(NHL_IDS.values())

    # ---------------------------------------------------------------- players
    prof = {r["player_id"]: r for r in read(paths["profiles"])}
    rights = {}
    for r in read(paths["rights"]):
        if r.get("league_name") == "National Hockey League" and r.get("club_id") in clubs:
            rights[r.get("staff_info_id")] = clubs[r["club_id"]]["team_id"]
    staff_people, players, ratings, persona = [], {}, {}, {}
    contracts_src = {}
    for s in read(paths["staff"]):
        pref = s.get("player_data_ref")
        job = s.get("job_for_club_label") or ""
        if pref in (None, "", "-1"):
            cc = clubs.get(s.get("contracted_club_ref"))
            if cc and cc["team_id"] in nhl_ids and job in STAFF_ROLES:
                staff_people.append(dict(name=s.get("staff_name"), role=STAFF_ROLES[job], team_id=cc["team_id"],
                                         age=season - _int(s.get("year_of_birth"), season - 50), nationality=s.get("primary_nationality_code")))
            continue
        p = prof.get(pref)
        if p is None:
            continue
        born = dob(p.get("date_of_birth")) or dob(s.get("staff_info_reference_date_of_birth"))
        if not born or not (1975 <= int(born[:4]) <= season - 15):
            continue
        rt = {k: _int(p.get(k)) for k in NATIVE_ATTRS}
        rt = {k: max(1, min(20, v if v is not None else 10)) for k, v in rt.items()}
        for a, b in PROFILE_MAP.items():
            rt[b] = max(1, min(20, _int(p.get(a), 1)))
        rt["current_ability"] = max(1, min(200, _int(p.get("current_ability"), 50)))
        pa = _int(p.get("potential_ability"), rt["current_ability"])
        if pa < 0:                                        # a range code: about |pa| x 10, the night decides
            r2 = random.Random(f"pa-{pref}")
            pa = max(rt["current_ability"], min(200, abs(pa) * 10 + r2.randint(-15, 15)))
        rt["potential_ability"] = max(rt["current_ability"], min(200, pa))
        pos = primary_position(rt)
        pf, cc = clubs.get(s.get("playing_for_ref")), clubs.get(s.get("contracted_club_ref"))
        org = cc["team_id"] if cc and cc["team_id"] in nhl_ids else (pf["team_id"] if pf and pf["team_id"] in nhl_ids else None)
        holder = rights.get(s.get("staff_info_id")) or rights.get(p.get("staff_info_id"))
        row = dict(player_id=_int(pref) + 1, first_name=(s.get("forename") or p.get("first_name") or "").strip(),
                   last_name=(s.get("surname") or p.get("last_name") or "").strip(), birth_date=born, position=pos,
                   shoots="R" if (p.get("handedness_label") or "").lower().startswith("r") else "L",
                   height_cm=_int(p.get("height_cm")) or "", weight_kg=_int(p.get("weight_kg")) or "",
                   nationality=s.get("primary_nationality_code") or "", team_id="", status="active", club_id="",
                   jersey_number=_int(p.get("squad_number")) if 1 <= _int(p.get("squad_number"), 0) <= 98 else "")
        if org:
            row["team_id"] = org
            row["club_id"] = pf["team_id"] if pf and pf["team_id"] not in nhl_ids else org
            if pf and pf["team_id"] not in nhl_ids:
                row["status"] = "prospect"
            contracts_src[row["player_id"]] = s
        elif pf:
            row["club_id"] = pf["team_id"]
        elif holder:
            pass
        else:
            row["_fa"] = True
        if holder and not org:
            row["_rights"] = holder
        row["_ca"] = rt["current_ability"]
        players[row["player_id"]] = row
        ratings[row["player_id"]] = rt
        persona[row["player_id"]] = s
    # free agents: the best unattached, of playing age
    fa = sorted((r for r in players.values() if r.get("_fa")), key=lambda r: -r["_ca"])
    keep_fa = {r["player_id"] for r in fa if 19 <= on.year - int(r["birth_date"][:4]) <= 37}
    keep_fa = set(sorted(keep_fa, key=lambda x: -players[x]["_ca"])[:free_agents])
    players = {k: v for k, v in players.items() if not v.get("_fa") or k in keep_fa}

    # NHL rosters: the best per club on the NHL roster (enough of each position), the rest with the AHL affiliate
    by_team = {}
    for r in players.values():
        if r["team_id"] and r["status"] == "active" and r["club_id"] == r["team_id"]:
            by_team.setdefault(r["team_id"], []).append(r)
    for t, members in by_team.items():
        ranked = sorted(members, key=lambda r: -r["_ca"])
        keep, counts = [], {"G": 0, "D": 0, "F": 0}
        for r in ranked:
            g = group(r["position"])
            if counts[g] < NEED_ACTIVE[g]:
                keep.append(r)
                counts[g] += 1
        for r in ranked:
            if len(keep) >= nhl_roster:
                break
            if r not in keep:
                keep.append(r)
        ids = {r["player_id"] for r in keep}
        for r in members:
            if r["player_id"] not in ids:
                r["status"], r["club_id"] = "prospect", affiliate.get(t, "")
    stats["players"] = len(players)

    # ---------------------------------------------------------------- the engine scale, fitted on the NHL's dressed players
    dressed = [(ratings[r["player_id"]], r["position"]) for r in players.values()
               if r["team_id"] and r["status"] == "active" and r["club_id"] == r["team_id"]]
    scale = fit_scale(dressed)
    from ..worldgen import make_profile, overall_of
    ca_scale = fit_ability({"S": [r["current_ability"] for r, p in dressed if p != "G"],
                            "G": [r["current_ability"] for r, p in dressed if p == "G"]})
    engine = {pid: derive(ratings[pid], r["position"], scale, ca_scale) for pid, r in players.items()}
    (out / "engine_scale.json").write_text(json.dumps(dict({k: list(v) for k, v in scale.items()},
                                                           _ca={k: list(v) for k, v in ca_scale.items()})), encoding="utf-8")

    # v44: the database leagues' strength, size and nationality mix, from their players. Strength is the mean overall
    # of a league's better 60% of skaters, placed on the hand-set scale of the original leagues (the offset that best
    # matches those leagues' observed means to their set ones)
    tid_lid = {r["team_id"]: r["league_id"] for r in clubs.values()}
    obs, nats, sizes = {}, {}, {}
    for pid, r in players.items():
        lid = tid_lid.get(r["club_id"]) if r.get("club_id") else None
        if lid is None or lid == 1:
            continue
        sizes.setdefault(r["club_id"], 0)
        sizes[r["club_id"]] += 1
        nats.setdefault(lid, {}).setdefault(r["nationality"] or "CAN", 0)
        nats[lid][r["nationality"] or "CAN"] += 1
        if r["position"] != "G":
            obs.setdefault(lid, []).append(overall_of(engine[pid], r["position"]))
    top60 = {lid: st.mean(sorted(v)[-max(1, int(len(v) * 0.6)):]) for lid, v in obs.items() if v}
    offs = [world[str(lid)]["mean"] - top60[lid] for lid in top60 if lid not in db_lids and str(lid) in world]
    off = st.median(offs) if offs else 0.0
    for lid, abbr in db_lids.items():
        m = world[str(lid)]
        if lid in top60:
            m["mean"] = round(top60[lid] + off, 2)
        club_sizes = [n for t, n in sizes.items() if tid_lid.get(t) == lid]
        if club_sizes:
            m["roster"] = max(22, min(30, int(st.median(club_sizes))))
        mix = nats.get(lid, {})
        tot = sum(mix.values()) or 1
        m["nat"] = {k: round(100 * v / tot) for k, v in sorted(mix.items(), key=lambda kv: -kv[1])[:8] if v / tot >= 0.02}
    stats["database_leagues"] = {abbr: dict(mean=world[str(lid)]["mean"], clubs=sum(1 for r in clubs.values() if r["league_id"] == lid),
                                            players=sum(n for t, n in sizes.items() if tid_lid.get(t) == lid))
                                 for lid, abbr in db_lids.items()}

    attr_rows, dev_rows, rating_rows = [], [], []
    for pid, r in players.items():
        pos = r["position"]
        ov = overall_of(engine[pid], pos)
        age = on.year - int(r["birth_date"][:4])
        pr = make_profile(random.Random(f"dbx-dev-{pid}"), age, ov, pos)
        pot = max(ov, overall_from_ability(ratings[pid]["potential_ability"], ca_scale, pos))
        pr["potential"] = round(min(20.0, pot), 2)
        dev_rows.append(dict(pr, player_id=pid))
        attr_rows.append(dict(engine[pid], player_id=pid, potential=max(1, min(20, round(pot)))))
        rating_rows.append(dict(ratings[pid], player_id=pid))

    # ---------------------------------------------------------------- personality and hidden attributes
    per, hid = [], []
    for pid, s in persona.items():
        if pid not in players:
            continue
        g = lambda k: _int(s.get(k), 10)
        rt = ratings[pid]
        amb, loy, adp, spt = g("ambition"), g("loyalty"), g("adaptability"), g("sportsmanship")
        per.append(dict(player_id=pid, professionalism=g("professionalism"), ambition=amb, loyalty=loy, leadership=rt["leadership"],
                        resilience=g("pressure"), patience=adp, ego=10 + 0.6 * (amb - 10) - 0.6 * (spt - 10),
                        role_tolerance=10 + 0.5 * (adp - 10) + 0.5 * (loy - 10) - 0.3 * (amb - 10)))
        hid.append(dict(player_id=pid, consistency=rt["consistency"], big_games=rt["important_matches"],
                        injury_proneness=rt["injury_proneness"], temperament=g("temperament"), sportsmanship=spt,
                        coachability=g("determination"), greed=10.5 + 0.5 * (amb - 10) - 0.5 * (loy - 10)))
    from ..game.people import TRAITS
    from ..game.hidden import HIDDEN
    standardise(per, [t for t in TRAITS if t != "leadership"], mean=10.5, sd=3.0)
    for r in per:
        r["leadership"] = max(1, min(20, round(r["leadership"])))
    standardise(hid, list(HIDDEN), mean=10.5, sd=3.2)

    # ---------------------------------------------------------------- contracts, rights, leadership
    contracts = []
    for pid, s in contracts_src.items():
        if pid not in players:
            continue
        r = players[pid]
        sal = _int(s.get("annual_salary_raw"), 0) or 0
        ey, ed = _int(s.get("club_contract_expiry_year_raw"), 0), _int(s.get("club_contract_expiry_day_raw"), 180)
        last = (ey - 1 if ed <= 200 else ey) if ey and ey >= season else season
        years = max(1, min(8, last - season + 1))
        first = _int(s.get("first_nhl_contract_year_raw"), 0) or 0
        age = on.year - int(r["birth_date"][:4])
        elc = first >= season - 2 and age <= 25 and sal <= 1_100_000
        contracts.append(dict(player_id=pid, team_id=r["team_id"], start_year=season, years=years,
                              cap_hit=max(MIN_SALARY, sal), contract_type="entry_level" if elc else "standard", no_trade=0))
    right_rows = []
    for pid, r in players.items():
        if r.get("_rights"):
            age = on.year - int(r["birth_date"][:4])
            dy = min(season, int(r["birth_date"][:4]) + 18)
            right_rows.append(dict(player_id=pid, team_id=r["_rights"], draft_year=dy, overall_pick="",
                                   expires_year=max(season + 1, dy + (4 if age <= 20 else 3))))
    lead = []
    name_dob = {(f"{r['first_name']} {r['last_name']}", r["birth_date"]): pid for pid, r in players.items()}
    for c in raw_clubs:
        row = clubs.get(c["club_id"])
        if not row or row["team_id"] not in nhl_ids:
            continue
        for key, role in (("Capt", "C"), ("Alt 1", "A"), ("Alt 2", "A")):
            pid = name_dob.get(((c.get(f"{key}: Name") or "").strip(), dob(c.get(f"{key}: DOB"))))
            if pid and players[pid]["team_id"] == row["team_id"] and players[pid]["position"] != "G":
                lead.append(dict(team_id=row["team_id"], player_id=pid, role=role))

    # ---------------------------------------------------------------- clubs' profiles and rivalries
    profiles, rivals = [], []
    for c in raw_clubs:
        row = clubs.get(c["club_id"])
        if not row or row["team_id"] not in nhl_ids:
            continue
        profiles.append(dict(team_id=row["team_id"], capacity=_int(c.get("MaxAttendance")) or "",
                             market=max(1, min(10, round((_int(c.get("MarketSize"), 10)) / 2))),
                             arena=(c.get("Arena") or "").split(":")[0].title(), reputation=_int(c.get("Reputation")) or "",
                             founded=_int(c.get("YearFounded")) or "", city=(c.get("HomeCity") or "").split(":")[0].title()))
        for i, k in enumerate(("Rivals1", "Rivals2", "Rivals3")):
            o = nhl_by_name.get(c.get(k))
            if o:
                ab = next(a for a, v in NHL_IDS.items() if v == o)
                if ab != row["abbr"]:
                    rivals.append([row["abbr"], ab, 30 - 5 * i])

    # ---------------------------------------------------------------- write the pack
    teams = [{k: v for k, v in r.items() if k != "_db"} for r in clubs.values()]
    stats["leagues"] = write(out / "leagues.csv", ["league_id", "name", "abbr", "country", "level", "games_per_team"], leagues)
    stats["teams"] = write(out / "teams.csv", ["team_id", "league_id", "name", "nickname", "abbr", "conference", "division",
                                               "primary_color", "secondary_color", "logo", "parent_team_id"], teams)
    stats["players"] = write(out / "players.csv", PLAYER_FIELDS, list(players.values()))
    from ..attributes import ALL_ATTRS
    stats["attribute_rows"] = write(out / "attributes.csv", ["player_id"] + ALL_ATTRS + ["potential"], attr_rows)
    stats["ratings"] = write(out / "ratings.csv", ["player_id"] + RATING_COLS, rating_rows)
    stats["development"] = write(out / "development.csv", ["player_id", "potential", "peak_age", "decline_age", "growth_rate",
                                                           "decline_rate"], dev_rows)
    stats["personality"] = write(out / "personality.csv", ["player_id"] + list(TRAITS), per)
    stats["hidden"] = write(out / "hidden.csv", ["player_id"] + list(HIDDEN), hid)
    stats["contracts"] = write(out / "contracts.csv", ["player_id", "team_id", "start_year", "years", "cap_hit", "contract_type",
                                                       "no_trade"], contracts)
    stats["draft_rights"] = write(out / "draft_rights.csv", ["player_id", "team_id", "draft_year", "overall_pick", "expires_year"], right_rows)
    stats["leadership"] = write(out / "leadership.csv", ["team_id", "player_id", "role"], lead)
    stats["staff"] = write(out / "staff.csv", ["name", "role", "team_id", "age", "nationality"], staff_people)
    stats["club_profiles"] = write(out / "club_profiles.csv", ["team_id", "capacity", "market", "arena", "reputation", "founded",
                                                               "city"], profiles)
    (out / "rivalries.json").write_text(json.dumps(rivals), encoding="utf-8")
    rules = json.loads(json.dumps(NHL.RULES))
    if season != 2025:                                # the season's own dates (no Olympic break outside 2025-26)
        first = datetime.date(season, 10, 5)                       # the first Tuesday from 5 October
        first += datetime.timedelta(days=(1 - first.weekday()) % 7)
        rules["season"] = {"start": first.isoformat(), "end": datetime.date(season + 1, 4, 17).isoformat(), "breaks": []}
    rules["world"] = {"leagues": world, "top_league_id": "1"}
    # v38 calibration on this import (docs/SIM_CALIBRATION.md): its special teams run a touch hot on the shared constants
    rules["engine"] = {"pp_scale": 0.90, "pen_scale": 1.03}
    rules["name"] = f"NHL {season}-{(season + 1) % 100:02d}"                       # v39: the season it really is
    (out / "rules.json").write_text(json.dumps(rules, indent=1), encoding="utf-8")
    stats["season"] = f"{season}-{(season + 1) % 100:02d}"
    man = dict(format_version="0.1", world_name=f"NHL {season}-{(season + 1) % 100:02d} (community database)", name=f"db-export-{season}", version="1", source="db_export", redistributable=False,
               contains_real_names=True, season_start_year=season,
               description="Built from your own export of a community hockey-management database. PERSONAL USE ONLY: "
                           "do not publish or share this pack or a game built from it.")
    (out / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    (out / "README.txt").write_text("PERSONAL USE ONLY: built from your own database export. Do not publish, share or commit.\n",
                                    encoding="utf-8")
    stats["engine_scale"] = {k: v for k, v in list(scale.items())[:3]}
    stats["ca_scale"] = ca_scale
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--season", type=int, default=2026, help="the season the database is set in (the 2026-27 database: 2026)")
    ap.add_argument("--nhl-roster", type=int, default=23)
    ap.add_argument("--free-agents", type=int, default=600)
    a = ap.parse_args(argv)
    s = build(a.src, a.out, a.season, a.nhl_roster, a.free_agents)
    print(json.dumps(s, indent=1, default=str))


if __name__ == "__main__":
    main()
