"""Real NHL contracts from a CSV you keep locally (personal use; never commit the source data or the result).

    python -m hs.adapters.contracts_csv contracts.csv [more.csv ...] --db game.db [--dry-run]
    python -m hs.adapters.contracts_csv contracts.csv --pack packs/mp_2025          # before building the world

Where the CSV comes from is up to you: a cap site's team page copied into a spreadsheet (CapWages, PuckPedia and
Spotrac all show the same core columns), or your own notes. Only the columns below are read; headers are matched
loosely (case, spacing and punctuation ignored) and anything else is left alone.

    player   Player / Name (or First Name + Last Name)                          required
    cap hit  Cap Hit / AAV / Cap / Average Annual Value                          required
    team     Team / Club (name, nickname or abbreviation)                        recommended
    expiry   Expiry / Expires / End / Through ("2028-29", "2029", "2029 UFA")    recommended
    length   Length / Years / Term                                               optional
    start    Start / Start Season / First Season                                 optional
    type     Type / Contract Type ("ELC" -> entry-level)                         optional
    clause   Clause / Clauses / NMC / NTC (any NMC or NTC -> no-trade)           optional

Money: "$7,875,000", "7.875M", "875K" and bare millions ("7.875") all work. A bare expiry year means the summer
it ends ("2029" = last season 2028-29). With expiry and length the start follows; with expiry only, the contract is
loaded as running from the current season to its expiry (past years do not affect the cap).

--db replaces the current and future contracts of every matched player in a game database (keeping his club);
--pack rewrites the matched players' rows in the pack's contracts.csv so a world built from it starts with them.
Unmatched rows are listed; nothing is guessed.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path

import unicodedata

_ALIASES = {"soogreyhounds": "Sault Ste. Marie Greyhounds", "newjeremydevils": "New Jersey Devils"}


def fold(s):
    """A club or player name folded for matching: no league tags, accents, case or punctuation."""
    s = re.sub(r"\s*\((?:OHL|WHL|QMJHL|AHL|ECHL|NCAA)\)", "", s or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    k = re.sub(r"[^a-z]", "", s.lower())
    if k in _ALIASES:
        return re.sub(r"[^a-z]", "", _ALIASES[k].lower())
    return k

ALIASES = {
    "player": ["player", "name", "playername", "fullname"],
    "first": ["firstname", "first"],
    "last": ["lastname", "last", "surname"],
    "cap": ["caphit", "aav", "cap", "averageannualvalue", "caphitaav", "aavcaphit"],
    "team": ["team", "club", "tm", "nhlteam"],
    "expiry": ["expiry", "expires", "end", "endseason", "contractend", "through", "exp", "expirystatus",
               "expiryyear"],
    "length": ["length", "years", "term", "yrs", "contractlength"],
    "start": ["start", "startseason", "firstseason", "signedseason", "startyear"],
    "type": ["type", "contracttype", "kind"],
    "clause": ["clause", "clauses", "nmc", "ntc", "nmcntc", "tradeprotection"],
}


def _key(h):
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def columns(header):
    """{field: column name} for the fields this file has."""
    out = {}
    keys = {_key(h): h for h in header}
    for field, names in ALIASES.items():
        for n in names:
            if n in keys:
                out[field] = keys[n]
                break
    return out


def money(v):
    s = (v or "").strip().replace("$", "").replace(",", "").replace(" ", "").upper()
    if not s or s in ("-", "N/A"):
        return None
    mult = 1
    if s.endswith("M"):
        s, mult = s[:-1], 1_000_000
    elif s.endswith("K"):
        s, mult = s[:-1], 1_000
    try:
        x = float(s)
    except ValueError:
        return None
    if mult == 1 and x < 100:          # "7.875" means millions
        mult = 1_000_000
    return int(round(x * mult))


def season_of(v, bare_is_summer):
    """'2028-29' -> 2028; a bare '2029' -> 2028 if it names the summer it ends, else 2029."""
    m = re.search(r"(\d{4})\s*[-/]\s*(\d{2,4})", v or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{4})", v or "")
    if m:
        y = int(m.group(1))
        return y - 1 if bare_is_summer else y
    return None


def parse_rows(paths, season):
    """[dict(name, team, cap, start, years, type, no_trade, line)] plus a list of rows skipped."""
    out, skipped = [], []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            col = columns(rd.fieldnames or [])
            if "cap" not in col or ("player" not in col and not ("first" in col and "last" in col)):
                raise SystemExit(f"{path}: need a player column and a cap hit column; found {rd.fieldnames}")
            for i, r in enumerate(rd, start=2):
                name = r.get(col.get("player", ""), "") if "player" in col else \
                    f"{r.get(col['first'], '')} {r.get(col['last'], '')}"
                name = re.sub(r"\s+", " ", name or "").strip()
                if "," in name:                                   # "McDavid, Connor"
                    last, first = [x.strip() for x in name.split(",", 1)]
                    name = f"{first} {last}"
                cap = money(r.get(col["cap"]))
                if not name or cap is None:
                    skipped.append((path, i, "no name or cap hit"))
                    continue
                end = season_of(r.get(col.get("expiry", ""), ""), bare_is_summer=True) if "expiry" in col else None
                start = season_of(r.get(col.get("start", ""), ""), bare_is_summer=False) if "start" in col else None
                length = None
                if "length" in col:
                    m = re.search(r"\d+", r.get(col["length"]) or "")
                    length = int(m.group()) if m else None
                if start is not None and length:
                    years = length
                elif end is not None and length:
                    start, years = end - length + 1, length
                elif end is not None:
                    start, years = min(season, end), max(1, end - min(season, end) + 1)
                elif length:
                    start, years = season, length
                else:
                    skipped.append((path, i, f"{name}: no expiry or length"))
                    continue
                kind = (r.get(col.get("type", ""), "") or "").upper()
                clause = (r.get(col.get("clause", ""), "") or "").upper()
                out.append(dict(name=name, team=r.get(col.get("team", ""), "") if "team" in col else "", cap=cap,
                                start=start, years=years, type="entry_level" if "ELC" in kind or "ENTRY" in kind
                                else "standard", no_trade=int("NMC" in clause or "NTC" in clause), line=(path, i)))
    return out, skipped


def _team_index(teams):
    idx = {}
    for t in teams:
        for key in (f"{t['name']} {t.get('nickname') or ''}", t["name"], t.get("nickname") or "", t["abbr"]):
            k = fold(key)
            if k and k not in idx:
                idx[k] = t["team_id"]
    return idx


def match(rows, players, teams):
    """Attach player_id/team_id; returns (matched, unmatched). players: [dict(player_id, first, last, team_id)]."""
    tidx = _team_index(teams)
    by_name = {}
    for p in players:
        by_name.setdefault(fold(f"{p['first']}{p['last']}"), []).append(p)
    ok, miss = [], []
    for r in rows:
        hits = by_name.get(fold(r["name"]), [])
        t = tidx.get(fold(r["team"])) if r["team"] else None
        if len(hits) > 1 and t is not None:
            hits = [h for h in hits if str(h["team_id"]) == str(t)] or hits
        if len(hits) != 1:
            miss.append((r, "not found" if not hits else "ambiguous name"))
            continue
        p = hits[0]
        team = p["team_id"] or t
        if team in (None, ""):
            miss.append((r, "player has no NHL club and the team did not match"))
            continue
        ok.append(dict(r, player_id=int(p["player_id"]), team_id=int(team),
                       team_differs=t is not None and str(t) != str(p["team_id"])))
    return ok, miss


def apply_db(conn, matched, dry_run=False):
    season = conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
    for m in matched:
        if dry_run:
            continue
        conn.execute("DELETE FROM contracts WHERE player_id=? AND start_year+years>?", (m["player_id"], season))
        conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type, no_trade) "
                     "VALUES (?,?,?,?,?,?,?)", (m["player_id"], m["team_id"], m["start"], m["years"], m["cap"],
                                                m["type"], m["no_trade"]))
    if not dry_run:
        conn.commit()


def apply_pack(pack, matched, dry_run=False):
    path = Path(pack) / "contracts.csv"
    fields = ["player_id", "team_id", "start_year", "years", "cap_hit", "contract_type", "no_trade"]
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8"))) if path.exists() else []
    real = {m["player_id"] for m in matched}
    rows = [r for r in rows if int(r["player_id"]) not in real]
    rows += [dict(player_id=m["player_id"], team_id=m["team_id"], start_year=m["start"], years=m["years"],
                  cap_hit=m["cap"], contract_type=m["type"], no_trade=m["no_trade"]) for m in matched]
    if not dry_run:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--db")
    g.add_argument("--pack")
    ap.add_argument("--season", type=int, help="season start year (default: the database's or pack's)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.db:
        conn = sqlite3.connect(a.db)
        conn.row_factory = sqlite3.Row
        season = a.season or conn.execute("SELECT MAX(start_year) FROM seasons").fetchone()[0]
        players = [dict(player_id=r[0], first=r[1], last=r[2], team_id=r[3]) for r in conn.execute(
            "SELECT player_id, first_name, last_name, team_id FROM players WHERE status<>'retired'")]
        teams = [dict(r) for r in conn.execute("SELECT team_id, name, nickname, abbr FROM teams")]
    else:
        import json
        man = json.loads((Path(a.pack) / "manifest.json").read_text())
        season = a.season or int(man["season_start_year"])
        players = [dict(player_id=r["player_id"], first=r["first_name"], last=r["last_name"], team_id=r.get("team_id"))
                   for r in csv.DictReader(open(Path(a.pack) / "players.csv", encoding="utf-8"))]
        teams = list(csv.DictReader(open(Path(a.pack) / "teams.csv", encoding="utf-8")))
    rows, skipped = parse_rows(a.csv, season)
    matched, missed = match(rows, players, teams)
    if a.db:
        apply_db(conn, matched, a.dry_run)
        from ..game.contracts import crules, payroll
        cap = crules(conn).get("cap_ceiling")
        over = []
        if cap and not a.dry_run:
            for t in conn.execute("SELECT team_id, abbr FROM teams WHERE league_id=(SELECT MIN(league_id) FROM teams)"):
                pay = payroll(conn, t[0], season)
                if pay > cap:
                    over.append(f"{t[1]} ${pay:,.0f}")
        conn.close()
    else:
        n = apply_pack(a.pack, matched, a.dry_run)
        over = []
        print(f"  pack contracts.csv now has {n} rows")
    print(f"  rows read {len(rows) + len(skipped)}, matched {len(matched)}, unmatched {len(missed)}, "
          f"skipped {len(skipped)}{' (dry run: nothing written)' if a.dry_run else ''}")
    for m in [m for m in matched if m["team_differs"]][:20]:
        print(f"  note: {m['name']} is listed with {m['team']} but plays for a different club here; club kept")
    for r, why in missed[:40]:
        print(f"  unmatched ({why}): {r['name']} {r['team']}")
    for path, line, why in skipped[:20]:
        print(f"  skipped {path}:{line}: {why}")
    if over:
        print("  over the cap after import: " + ", ".join(over))
    print("  Reminder: contract data from cap sites is theirs; keep the CSV and the result out of any repository.")


if __name__ == "__main__":
    main()
