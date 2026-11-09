"""The editor and bulk import/export (v41; docs/EDITOR.md).

Commissioner mode
  Off by default. Turning it on (Settings, or `editor on`) marks the save as edited, for good: the save's
  achievements and GM score carry an "edited" note. With it on you can edit any player or club, and import changes
  in bulk.

Player edits (`edit_player`)
  bio: first_name, last_name, birth_date, position, shoots, nationality, height_cm, weight_kg
  ratings: any of the ratings model's columns (hs/attributes.RATING_COLS: the 42 ratings, current and potential
           ability, position and role ratings); the engine attributes are re-derived from them (ratings.set_ratings)
  potential: the development ceiling on the 1-20 scale (player_dev.potential)
  personality: professionalism, ambition, loyalty, leadership, resilience, patience, ego, role_tolerance (1-20)
  contract: cap_hit, end (the last season's start year), clause (none, NTC, NMC, MNTC:<n>)
  team: a club's abbreviation (or FA for free agency); he joins its NHL roster, or its minors with status=prospect
Club edits (`edit_club`): name, nickname, abbr, conference, division.

Bulk export (`export_players`): one CSV row per player (bio, club, status, every rating, personality, potential,
contract), for your club, the NHL, or everyone.
Bulk import (`import_players`): a CSV with any subset of those columns. Rows are matched by player_id, or by first
name, last name and birth date; a row with no match and a name, birth date and position creates a new player (a free
agent unless it names a club). Headers are matched without case and with common aliases (CA, PA, DOB, surname...).
Preview first: what changes, what is new, and every problem with its row number; apply writes the rows that passed.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import random

from ..attributes import RATING_COLS
from .state import get_state, user_team

BIO = ("first_name", "last_name", "birth_date", "position", "shoots", "nationality", "height_cm", "weight_kg")
TRAITS = ("professionalism", "ambition", "loyalty", "leadership", "resilience", "patience", "ego", "role_tolerance")
CONTRACT = ("cap_hit", "contract_end", "clause")
POSITIONS = ("C", "LW", "RW", "D", "G")
ALIASES = {"id": "player_id", "pid": "player_id", "first": "first_name", "forename": "first_name", "firstname": "first_name",
           "last": "last_name", "surname": "last_name", "lastname": "last_name", "dob": "birth_date", "born": "birth_date",
           "birthdate": "birth_date", "pos": "position", "nation": "nationality", "nat": "nationality", "height": "height_cm",
           "weight": "weight_kg", "ca": "current_ability", "pa": "potential_ability", "club": "team", "team_abbr": "team",
           "salary": "cap_hit", "aav": "cap_hit", "caphit": "cap_hit", "end": "contract_end", "expires": "contract_end"}
CAREER = ("career_gp", "career_g", "career_a", "career_w", "career_so", "career_po_gp", "career_seasons")   # v41: before the save
EXPORT_COLS = ["player_id", *BIO, "team", "status", "potential", *RATING_COLS, *TRAITS, *CONTRACT, *CAREER]


# ---------------------------------------------------------------- commissioner mode
def enabled(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='commissioner'").fetchone()
    return bool(r and r[0] == "1")


def set_enabled(conn, on):
    if on:
        from . import challenge
        if challenge.mode_on(conn):
            raise ValueError("This is a challenge-mode career: commissioner mode and the editor are off for good.")
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('commissioner', ?)", ("1" if on else "0",))
    if on:
        conn.execute("INSERT OR IGNORE INTO pack_info (key, value) VALUES ('edited_since', ?)", (get_state(conn)[0],))


def edited(conn):
    r = conn.execute("SELECT value FROM pack_info WHERE key='edited_since'").fetchone()
    return r[0] if r else None


def _need(conn):
    if not enabled(conn):
        raise ValueError("The editor needs commissioner mode (Settings > Gameplay, or `editor on`).")


def _log(conn, what, detail):
    conn.execute("CREATE TABLE IF NOT EXISTS editor_log (day TEXT, what TEXT, detail TEXT)")
    conn.execute("INSERT INTO editor_log VALUES (?,?,?)", (get_state(conn)[0], what, json.dumps(detail)[:2000]))


# ---------------------------------------------------------------- values
def _int(v, lo, hi, what):
    try:
        x = int(float(str(v).strip()))
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number (got {v!r}).")
    if not lo <= x <= hi:
        raise ValueError(f"{what} must be {lo}-{hi} (got {x}).")
    return x


def _money(v):
    s = str(v).strip().lower().replace("$", "").replace(",", "")
    mult = 1_000_000 if s.endswith("m") else 1_000 if s.endswith("k") else 1
    s = s.rstrip("mk")
    x = float(s) * mult
    if x < 1000:                       # "7.5" means $7.5M
        x *= 1_000_000
    return int(round(x))


def _date(v):
    s = str(v).strip()[:10]
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"birth_date must be YYYY-MM-DD (got {v!r}).")
    return s


def _team(conn, v):
    s = str(v).strip().upper()
    if s in ("", "FA", "NONE", "FREE AGENT"):
        return None
    r = conn.execute("SELECT team_id FROM teams WHERE UPPER(abbr)=?", (s,)).fetchone()
    if r is None:
        raise ValueError(f"No club with the abbreviation {v!r}.")
    return r[0]


def clean(conn, field, value):
    """Validate and normalise one field's value."""
    if field in ("first_name", "last_name"):
        s = str(value).strip()
        if not s:
            raise ValueError(f"{field} cannot be empty.")
        return s
    if field == "birth_date":
        return _date(value)
    if field == "position":
        s = str(value).strip().upper()
        if s not in POSITIONS:
            raise ValueError(f"position must be one of {', '.join(POSITIONS)} (got {value!r}).")
        return s
    if field == "shoots":
        s = str(value).strip().upper()[:1]
        if s not in ("L", "R"):
            raise ValueError("shoots must be L or R.")
        return s
    if field == "nationality":
        return str(value).strip().upper()[:3]
    if field == "height_cm":
        return _int(value, 150, 215, "height_cm")
    if field == "weight_kg":
        return _int(value, 55, 140, "weight_kg")
    if field in ("current_ability", "potential_ability"):
        return _int(value, 1, 200, field)
    if field in RATING_COLS:
        return _int(value, 1, 20, field)
    if field in TRAITS:
        return _int(value, 1, 20, field)
    if field == "potential":
        try:
            x = float(value)
        except (TypeError, ValueError):
            raise ValueError("potential must be a number 1-20.")
        if not 1 <= x <= 20:
            raise ValueError("potential must be 1-20.")
        return round(x, 3)
    if field == "cap_hit":
        return _money(value)
    if field == "contract_end":
        return _int(value, 1990, 2100, "contract_end")
    if field == "clause":
        s = str(value).strip().upper().replace("M-NTC", "MNTC")
        if s in ("", "NONE"):
            return None
        if s in ("NTC", "NMC"):
            return (s, 0)
        if s.startswith("MNTC"):
            n = s[4:].strip(": ") or "10"
            return ("MNTC", _int(n, 1, 31, "list size"))
        raise ValueError("clause must be none, NTC, NMC or MNTC:<clubs>.")
    if field in CAREER:
        return _int(value, 0, 3000, field)
    if field == "team":
        return _team(conn, value)
    if field == "status":
        s = str(value).strip().lower()
        if s not in ("active", "prospect"):
            raise ValueError("status must be active (NHL roster) or prospect (minors).")
        return s
    raise ValueError(f"Unknown field {field}.")


# ---------------------------------------------------------------- edits
def edit_player(conn, pid, changes, log=True):
    """Apply {field: value} to one player (values already cleaned or raw). Returns the fields changed."""
    from . import ratings as RT
    _need(conn)
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None:
        raise ValueError(f"No player {pid}.")
    ch = {k: (v if k in ("team", "clause") and not isinstance(v, str) else clean(conn, k, v))
          for k, v in changes.items() if k not in ("player_id",) and v != "" and (v is not None or k in ("team", "clause"))}
    done = []
    bio = {k: v for k, v in ch.items() if k in BIO}
    if bio:
        conn.execute(f"UPDATE players SET {', '.join(f'{k}=?' for k in bio)} WHERE player_id=?", [*bio.values(), pid])
        done += list(bio)
    rat = {k: v for k, v in ch.items() if k in RATING_COLS}
    if rat:
        RT.ensure_table(conn)
        if RT.of(conn, pid) is None:
            RT.backfill(conn)
        RT.set_ratings(conn, pid, rat)
        done += list(rat)
    if "potential" in ch:
        conn.execute("UPDATE player_dev SET potential=? WHERE player_id=?", (ch["potential"], pid))
        done.append("potential")
    tr = {k: v for k, v in ch.items() if k in TRAITS}
    if tr and conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone():
        conn.execute("INSERT OR IGNORE INTO personality (player_id) VALUES (?)", (pid,))
        conn.execute(f"UPDATE personality SET {', '.join(f'{k}=?' for k in tr)} WHERE player_id=?", [*tr.values(), pid])
        done += list(tr)
    if "team" in ch or "status" in ch:
        done += _move(conn, pid, ch.get("team", p["team_id"]) if "team" in ch else p["team_id"], ch.get("status"))
    if any(k in ch for k in CONTRACT):
        done += _contract(conn, pid, ch)
    car = {k[7:]: v for k, v in ch.items() if k in CAREER}
    if car:
        from . import career as CR
        CR.set_prior(conn, pid, "editor", **car)
        done += [f"career_{k}" for k in car]
    if log and done:
        _log(conn, "player", dict(player_id=pid, fields=done))
    return done


def _move(conn, pid, team, status):
    from . import roster as R
    from . import contracts as K
    if team is None:
        conn.execute("UPDATE players SET team_id=NULL, club_id=NULL, status='active' WHERE player_id=?", (pid,))
        conn.execute("UPDATE contracts SET years=MAX(1, ?-start_year) WHERE player_id=? AND start_year+years>?",
                     (K.season_year(conn), pid, K.season_year(conn)))
        return ["team"]
    st = status or "active"
    club = R.affiliate(conn, team) if st == "prospect" else team
    conn.execute("UPDATE players SET team_id=?, club_id=?, status=? WHERE player_id=?", (team, club, st, pid))
    conn.execute("UPDATE contracts SET team_id=? WHERE player_id=? AND start_year+years>?", (team, pid, K.season_year(conn)))
    return ["team"] + (["status"] if status else [])


def _contract(conn, pid, ch):
    from . import contracts as K
    from . import clauses as CL
    y = K.season_year(conn)
    c = K.current_contract(conn, pid)
    team = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    done = []
    if c is None:
        if team is None or "cap_hit" not in ch:
            if "clause" in ch or "contract_end" in ch:
                raise ValueError("He has no contract: give a club and a cap_hit to create one.")
            return done
        end = ch.get("contract_end", y)
        conn.execute("INSERT INTO contracts (player_id, team_id, start_year, years, cap_hit, contract_type, no_trade) "
                     "VALUES (?,?,?,?,?, 'standard', 0)", (pid, team, y, max(1, end - y + 1), ch["cap_hit"]))
        c = K.current_contract(conn, pid)
        done += ["cap_hit", "contract_end"]
    else:
        if "cap_hit" in ch:
            conn.execute("UPDATE contracts SET cap_hit=? WHERE contract_id=?", (ch["cap_hit"], c["contract_id"]))
            done.append("cap_hit")
        if "contract_end" in ch:
            if ch["contract_end"] < y:
                raise ValueError(f"contract_end must be {y} or later.")
            conn.execute("UPDATE contracts SET years=? WHERE contract_id=?", (ch["contract_end"] - c["start_year"] + 1,
                                                                             c["contract_id"]))
            done.append("contract_end")
    if "clause" in ch:
        CL.ensure_table(conn)
        conn.execute("DELETE FROM clauses WHERE player_id=? AND contract_id=?", (pid, c["contract_id"]))
        conn.execute("UPDATE contracts SET no_trade=0 WHERE contract_id=?", (c["contract_id"],))
        if ch["clause"]:
            c = K.current_contract(conn, pid)
            CL.set_clause(conn, pid, c["contract_id"], ch["clause"][0], ch["clause"][1], c["start_year"],
                          c["start_year"] + c["years"] - 1)
        done.append("clause")
    return done


def edit_club(conn, team, changes):
    _need(conn)
    ok = {k: str(v).strip() for k, v in changes.items() if k in ("name", "nickname", "abbr", "conference", "division")
          and str(v).strip()}
    if "abbr" in ok:
        ok["abbr"] = ok["abbr"].upper()[:4]
        if conn.execute("SELECT 1 FROM teams WHERE UPPER(abbr)=? AND team_id<>?", (ok["abbr"], team)).fetchone():
            raise ValueError(f"Another club already uses {ok['abbr']}.")
    if not ok:
        return []
    conn.execute(f"UPDATE teams SET {', '.join(f'{k}=?' for k in ok)} WHERE team_id=?", [*ok.values(), team])
    _log(conn, "club", dict(team_id=team, fields=list(ok)))
    return list(ok)


# ---------------------------------------------------------------- one player, for the form
def player_form(conn, pid):
    from . import ratings as RT
    from . import contracts as K
    from . import clauses as CL
    from ..attributes import NATIVE_GROUPS, POSITION_RATINGS, ROLE_RATINGS
    from . import career as CR
    p = conn.execute("SELECT p.*, t.abbr FROM players p LEFT JOIN teams t ON t.team_id=p.team_id WHERE p.player_id=?",
                     (pid,)).fetchone()
    if p is None:
        raise ValueError(f"No player {pid}.")
    RT.ensure_table(conn)
    rat = RT.of(conn, pid) or {}
    tr = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone():
        r = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone()
        tr = {k: r[k] for k in TRAITS} if r else {}
    pot = conn.execute("SELECT potential FROM player_dev WHERE player_id=?", (pid,)).fetchone()
    c = K.current_contract(conn, pid)
    cl = CL.of(conn, pid)
    groups = {g: list(cols) for g, cols in NATIVE_GROUPS.items()}
    groups["ability"] = ["current_ability", "potential_ability"]
    groups["positions"] = POSITION_RATINGS + ROLE_RATINGS
    return dict(player_id=pid, bio={k: p[k] for k in BIO}, team=p["abbr"] or "FA", status=p["status"], ratings=rat,
                groups=groups, personality=tr, potential=pot[0] if pot else None,
                contract=dict(cap_hit=c["cap_hit"], contract_end=c["start_year"] + c["years"] - 1) if c else None,
                clause=(cl["kind"] + (f":{cl['list_size']}" if cl["kind"] == "MNTC" else "")) if cl else "none",
                career=(lambda pr: {f"career_{k}": pr[k] for k in CR.FIELDS} if pr else {f: 0 for f in CAREER})(CR.prior(conn, pid)),
                commissioner=enabled(conn))


# ---------------------------------------------------------------- export
def export_players(conn, scope="mine"):
    """CSV text of players: scope mine | nhl | all."""
    from . import ratings as RT
    from . import contracts as K
    from . import clauses as CL
    from ..schema import top_league_sql
    from . import career as CR
    RT.ensure_table(conn)
    if scope == "mine":
        where, args = "p.team_id=?", (user_team(conn),)
    elif scope == "nhl":
        where, args = f"p.team_id IN (SELECT team_id FROM teams WHERE {top_league_sql()})", ()
    else:
        where, args = "p.status<>'retired'", ()
    has_pers = conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone()
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=EXPORT_COLS)
    w.writeheader()
    for p in conn.execute(f"SELECT p.*, t.abbr FROM players p LEFT JOIN teams t ON t.team_id=p.team_id WHERE {where} "
                          "ORDER BY p.team_id, p.last_name", args).fetchall():
        pid = p["player_id"]
        row = {k: p[k] for k in BIO}
        row.update(player_id=pid, team=p["abbr"] or "FA", status=p["status"])
        pot = conn.execute("SELECT potential FROM player_dev WHERE player_id=?", (pid,)).fetchone()
        row["potential"] = pot[0] if pot else ""
        row.update(RT.of(conn, pid) or {})
        if has_pers:
            r = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone()
            if r:
                row.update({k: r[k] for k in TRAITS})
        c = K.current_contract(conn, pid)
        if c:
            row.update(cap_hit=c["cap_hit"], contract_end=c["start_year"] + c["years"] - 1)
            cl = CL.of(conn, pid)
            row["clause"] = (cl["kind"] + (f":{cl['list_size']}" if cl["kind"] == "MNTC" else "")) if cl else "none"
        pr = CR.prior(conn, pid)
        if pr:
            row.update({f"career_{k}": pr[k] for k in CR.FIELDS})
        w.writerow({k: row.get(k, "") for k in EXPORT_COLS})
    return out.getvalue()


# ---------------------------------------------------------------- import
def _header(h):
    k = (h or "").strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(k.replace("_", ""), ALIASES.get(k, k))


def _match(conn, row):
    if row.get("player_id"):
        try:
            pid = int(float(row["player_id"]))
        except ValueError:
            raise ValueError(f"player_id {row['player_id']!r} is not a number.")
        if conn.execute("SELECT 1 FROM players WHERE player_id=?", (pid,)).fetchone():
            return pid
        raise ValueError(f"No player {pid}.")
    if row.get("first_name") and row.get("last_name") and row.get("birth_date"):
        r = conn.execute("SELECT player_id FROM players WHERE LOWER(first_name)=? AND LOWER(last_name)=? AND birth_date=?",
                         (row["first_name"].strip().lower(), row["last_name"].strip().lower(), row["birth_date"].strip()[:10])).fetchall()
        if len(r) == 1:
            return r[0][0]
        if len(r) > 1:
            raise ValueError("More than one player matches that name and birth date; give the player_id.")
    return None


def import_players(conn, text, apply=False):
    """Preview (apply=False) or apply a CSV of player rows. Returns dict(rows, matched, created, changes, errors,
    unknown_columns, applied)."""
    _need(conn)
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not rd.fieldnames:
        raise ValueError("The file has no header row.")
    cols = {h: _header(h) for h in rd.fieldnames}
    known = set(EXPORT_COLS)
    unknown = [h for h, k in cols.items() if k not in known]
    res = dict(rows=0, matched=0, created=0, changes=[], errors=[], unknown_columns=unknown, applied=False)
    conn.execute("SAVEPOINT editor_import")
    try:
        for i, raw in enumerate(rd, start=2):
            res["rows"] += 1
            row = {cols[h]: (v or "").strip() for h, v in raw.items() if h in cols and cols[h] in known}
            try:
                pid = _match(conn, row)
                fields = {k: v for k, v in row.items() if v != "" and k not in ("player_id", "status") or (k == "status" and v)}
                if pid is None:
                    need = [k for k in ("first_name", "last_name", "birth_date", "position") if not row.get(k)]
                    if need:
                        raise ValueError(f"no match, and to create a player it needs {', '.join(need)}.")
                    for k, v in fields.items():
                        clean(conn, k, v) if k not in ("status",) else None
                    pid = create_player(conn, fields)
                    res["created"] += 1
                    res["changes"].append(dict(row=i, player_id=pid, name=f"{row['first_name']} {row['last_name']}",
                                               fields=["new player"]))
                    continue
                cur = _current(conn, pid)
                diff = {}
                if fields.get("status") and not fields.get("team"):
                    fields["team"] = cur.get("team") or "FA"
                for k, v in fields.items():
                    nv = clean(conn, k, v)
                    if k == "team":
                        if nv != cur.get("team_id"):
                            diff[k] = nv
                    elif k == "clause":
                        if (nv[0] + (f":{nv[1]}" if nv and nv[0] == "MNTC" else "") if nv else "none") != cur.get("clause"):
                            diff[k] = nv
                    elif k == "status":
                        if nv != conn.execute("SELECT status FROM players WHERE player_id=?", (pid,)).fetchone()[0]:
                            diff[k] = nv
                            diff.setdefault("team", cur.get("team_id"))
                    elif k == "potential":
                        if cur.get(k) is None or abs(float(nv) - float(cur[k])) > 0.0015:
                            diff[k] = nv
                    elif str(nv) != str(cur.get(k)):
                        diff[k] = nv
                res["matched"] += 1
                if diff:
                    name = conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
                    res["changes"].append(dict(row=i, player_id=pid, name=name,
                                               fields=[f"{k}: {cur.get(k)} -> {v if not isinstance(v, tuple) else v[0]}" for k, v in diff.items()]))
                    edit_player(conn, pid, diff, log=False)
            except ValueError as e:
                res["errors"].append(dict(row=i, error=str(e)))
        if apply:
            conn.execute("RELEASE editor_import")
            _log(conn, "import", dict(rows=res["rows"], changed=len(res["changes"]), errors=len(res["errors"])))
            res["applied"] = True
        else:
            conn.execute("ROLLBACK TO editor_import")
            conn.execute("RELEASE editor_import")
    except Exception:
        conn.execute("ROLLBACK TO editor_import")
        conn.execute("RELEASE editor_import")
        raise
    res["changes"] = res["changes"][:500]
    return res


def _current(conn, pid):
    from . import ratings as RT
    from . import contracts as K
    from . import clauses as CL
    p = conn.execute("SELECT * FROM players WHERE player_id=?", (pid,)).fetchone()
    cur = {k: p[k] for k in BIO}
    cur["team_id"] = p["team_id"]
    cur["team"] = (conn.execute("SELECT abbr FROM teams WHERE team_id=?", (p["team_id"],)).fetchone() or [None])[0]
    cur.update(RT.of(conn, pid) or {})
    pot = conn.execute("SELECT potential FROM player_dev WHERE player_id=?", (pid,)).fetchone()
    cur["potential"] = pot[0] if pot else None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone():
        r = conn.execute("SELECT * FROM personality WHERE player_id=?", (pid,)).fetchone()
        if r:
            cur.update({k: r[k] for k in TRAITS})
    c = K.current_contract(conn, pid)
    if c:
        cur.update(cap_hit=c["cap_hit"], contract_end=c["start_year"] + c["years"] - 1)
        cl = CL.of(conn, pid)
        cur["clause"] = (cl["kind"] + (f":{cl['list_size']}" if cl["kind"] == "MNTC" else "")) if cl else "none"
    from . import career as CR
    pr = CR.prior(conn, pid)
    if pr:
        cur.update({f"career_{k}": pr[k] for k in CR.FIELDS})
    return cur


def create_player(conn, fields):
    """A new player from a row: bio, then his ratings (unspecified ones at 10, or around his ability), potential,
    personality; a free agent unless the row names a club."""
    from . import ratings as RT
    from ..attributes import ALL_ATTRS, NATIVE_ATTRS
    f = {k: clean(conn, k, v) for k, v in fields.items() if k != "status"}
    pid = conn.execute("SELECT COALESCE(MAX(player_id), 0) + 1 FROM players").fetchone()[0]
    conn.execute("INSERT INTO players (player_id, first_name, last_name, birth_date, position, shoots, height_cm, weight_kg, "
                 "nationality, status) VALUES (?,?,?,?,?,?,?,?,?, 'active')",
                 (pid, f["first_name"], f["last_name"], f["birth_date"], f["position"], f.get("shoots", "L"),
                  f.get("height_cm", 185), f.get("weight_kg", 88), f.get("nationality", "CAN")))
    conn.execute("INSERT INTO player_attributes (player_id) VALUES (?)", (pid,))
    RT.ensure_table(conn)
    rng = random.Random(f"new-{pid}")
    base = {a: max(1, min(20, int(round(rng.gauss(10, 1.5))))) for a in NATIVE_ATTRS}
    pos = f["position"]
    if pos != "G":
        for gk in ("blocker", "glove", "rebounds", "recovery", "reflexes"):
            if gk in base:
                base[gk] = 1
    base.update({k: v for k, v in f.items() if k in RATING_COLS})
    pr = {"pos_g": 20 if pos == "G" else 1, "pos_ld": 20 if pos == "D" else 1, "pos_rd": 15 if pos == "D" else 1,
          "pos_lw": 20 if pos == "LW" else 8, "pos_c": 20 if pos == "C" else 8, "pos_rw": 20 if pos == "RW" else 8}
    for k, v in pr.items():
        base.setdefault(k, v)
    base.setdefault("role_off", 10)
    base.setdefault("role_def", 10)
    RT.write(conn, pid, base, pos)
    pot = f.get("potential")
    conn.execute("INSERT OR REPLACE INTO player_dev (player_id, potential, peak_age, decline_age, growth_rate, decline_rate) "
                 "VALUES (?,?,?,?,?,?)", (pid, pot if pot is not None else 10.0, 27, 31, 1.0, 1.0))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone():
        conn.execute("INSERT OR IGNORE INTO personality (player_id) VALUES (?)", (pid,))
        tr = {k: f.get(k, 10) for k in TRAITS}
        conn.execute(f"UPDATE personality SET {', '.join(f'{k}=?' for k in tr)} WHERE player_id=?", [*tr.values(), pid])
    if f.get("team") is not None:
        st = str(fields.get("status") or "active").lower()
        _move(conn, pid, f["team"], "prospect" if st == "prospect" else "active")
        if f.get("cap_hit"):
            _contract(conn, pid, {k: f[k] for k in ("cap_hit", "contract_end", "clause") if k in f})
    _log(conn, "create", dict(player_id=pid))
    return pid
