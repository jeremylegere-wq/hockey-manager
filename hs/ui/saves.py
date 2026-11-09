"""Save slots for the UI: every career is one SQLite file in a saves folder.

The game writes to its save as it goes (every command and every simulated day is committed), so the open save is
always current. "Save as" copies it to a new slot (a snapshot you can go back to); "Load" switches the server to
another slot; "New game" copies the template world (a freshly built pack, no game started) and starts a career
with the club you pick. Slot files are plain .db files: copy them to back up or move a career between computers.
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import sqlite3
from pathlib import Path

SAFE = re.compile(r"[^A-Za-z0-9 _.\-]+")


def clean_name(name):
    n = SAFE.sub("", (name or "").strip())[:60].strip(" .")
    if not n:
        raise ValueError("Give the save a name (letters, numbers, spaces, - and _).")
    return n


def _summary(path):
    """What a save holds, read without the game code (fast, read-only)."""
    out = dict(file=path.name, name=path.stem, size=path.stat().st_size,
               modified=datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"))
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            st = c.execute('SELECT "current_date" FROM game_state WHERE id=1').fetchone()
            me = c.execute("SELECT team_id FROM manager LIMIT 1").fetchone()
            if me and me[0] is not None:
                t = c.execute("SELECT abbr, name, nickname FROM teams WHERE team_id=?", (me[0],)).fetchone()
                if t:
                    out.update(team=t[0], team_name=f"{t[1]} {t[2] or ''}".strip())
            else:
                me = None
                out.update(team="", team_name="Out of work")
            out["date"] = st[0] if st else None
            sid = c.execute("SELECT season_id, start_year FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()
            if sid and me:
                out["season"] = sid[1]
                w = l = o = 0
                for h, a, hg, ag, ot in c.execute("SELECT home_team_id, away_team_id, home_goals, away_goals, went_to_ot "
                                                  "FROM games WHERE played=1 AND game_type='RS' AND season_id=? AND "
                                                  "(home_team_id=? OR away_team_id=?)", (sid[0], me[0], me[0])):
                    mine, theirs = (hg, ag) if h == me[0] else (ag, hg)
                    if mine > theirs:
                        w += 1
                    elif ot:
                        o += 1
                    else:
                        l += 1
                out["record"] = f"{w}-{l}-{o}"
        finally:
            c.close()
    except sqlite3.Error:
        out["broken"] = True
    return out


def _world_info(path):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            info = dict(c.execute("SELECT key, value FROM pack_info").fetchall())
            n = c.execute("SELECT COUNT(*) FROM players WHERE status<>'retired'").fetchone()[0]
            season = info.get("quickstart_season") or info.get("season_start_year")
            return dict(players=n, season=season, source=info.get("source", ""),
                        personal=info.get("redistributable") in ("False", "false", "0"), world_name=info.get("world_name"),
                        quickstart=bool(info.get("quickstart")), edited=bool(info.get("edited_since")))
        finally:
            c.close()
    except sqlite3.Error:
        return dict(players=0, season=None, source="", personal=True)


class Saves:
    def __init__(self, folder, template=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.template = Path(template) if template else None
        self.worlds_dir = self.folder.parent / "worlds"      # v38: imported databases, one template each
        # v39: other worlds shipped with the game (save/worlds/ next to the default template)
        self.bundled_dir = self.template.parent / "worlds" if self.template else None
        if self.template and not self.template.exists() and self.bundled_dir and self.bundled_dir.exists():
            other = sorted(self.bundled_dir.glob("*.db"))      # the default world was removed: use a bundled one
            if other:
                self.template, self.bundled_dir = other[0], None

    # ---- v38: worlds (templates a career starts from)
    def worlds(self):
        out = []
        if self.template and self.template.exists():
            info = _world_info(self.template)
            out.append(dict(key="", name=info.pop("world_name", None) or "NHL (bundled)", file=self.template.name, default=True, **info))
        for d in (self.bundled_dir, self.worlds_dir):
            if d and d.exists():
                for p in sorted(d.glob("*.db")):
                    info = _world_info(p)
                    out.append(dict(key=p.stem, name=info.pop("world_name", None) or p.stem.replace("_", " "), file=p.name,
                                    default=False, **info))
        return out

    def make_quickstart(self, conn, name):
        """v48: the open save, at the start of a season, as a world new careers can start from."""
        from ..game import quickstart
        key = clean_name(name or "Quickstart").replace(" ", "_")
        self.worlds_dir.mkdir(parents=True, exist_ok=True)
        dest = self.worlds_dir / f"{key}.db"
        quickstart.make(conn, dest, clean_name(name or "Quickstart"))
        return dest

    def world_path(self, key=None):
        if not key:
            return self.template
        for d in (self.worlds_dir, self.bundled_dir):
            if not d:
                continue
            p = (d / (clean_name(key) + ".db")).resolve()
            if p.parent == d.resolve() and p.exists():
                return p
        raise ValueError(f"No world called {key}.")

    def import_world(self, src, name, db_file=None):
        """Build a world from your own database export (hs/adapters/db_export.py): the pack (editable CSVs) and its
        template database, both under worlds/ next to the saves. Personal use only."""
        from ..adapters import db_export
        from ..ingest import build_db
        src = Path(str(src).strip().strip('"')).expanduser()
        if not src.exists():
            raise ValueError(f"No folder {src}.")
        key = clean_name(name or "Imported world").replace(" ", "_")
        self.worlds_dir.mkdir(parents=True, exist_ok=True)
        pack = self.worlds_dir / f"{key}_pack"
        stats = db_export.build(src, pack)
        db = self.worlds_dir / f"{key}.db"
        build_db(pack, db, overwrite=True)
        # v42: careers and past drafts straight from the database file, when it is given or sits in the folder
        dbf = Path(str(db_file).strip().strip('"')).expanduser() if db_file else next(iter(sorted(src.rglob("database.db"))), None)
        if dbf and dbf.exists():
            import sqlite3
            from ..adapters import db_history
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                h = db_history.load(conn, dbf, src, apply=True)
                conn.commit()
                stats["history"] = h
            except (ValueError, FileNotFoundError) as e:
                stats["history_error"] = str(e)
            finally:
                conn.close()
        return key, stats

    def path(self, name):
        p = (self.folder / (clean_name(name) + ".db")).resolve()
        if p.parent != self.folder.resolve():
            raise ValueError("Bad save name.")
        return p

    def list(self, current=None):
        cur = Path(current).resolve() if current else None
        rows = [dict(_summary(p), current=cur == p.resolve()) for p in self.folder.glob("*.db")]
        rows.sort(key=lambda r: r["modified"], reverse=True)
        return rows

    def teams(self, world=None):
        """Clubs you can take over in a new game (from the template world)."""
        tpl = self.world_path(world)
        if not tpl or not tpl.exists():
            return []
        c = sqlite3.connect(f"file:{tpl}?mode=ro", uri=True)
        try:
            from ..schema import top_league_sql
            from ..game.roster import value_from_attrs
            c.row_factory = sqlite3.Row
            out = []
            for r in c.execute(f"SELECT team_id, abbr, name, nickname, conference, division FROM teams WHERE "
                               f"{top_league_sql()} ORDER BY conference, division, name"):
                players = []
                for p in c.execute("SELECT p.first_name||' '||p.last_name n, p.position, a.* FROM players p JOIN player_attributes a "
                                   "USING (player_id) WHERE p.team_id=? AND p.status IN ('active','injured')", (r["team_id"],)):
                    players.append((value_from_attrs(dict(p), p["position"]), p["n"], p["position"]))
                players.sort(reverse=True)
                strength = sum(v for v, _, _ in players[:18]) / max(1, min(18, len(players)))
                out.append(dict(abbr=r["abbr"], name=f"{r['name']} {r['nickname'] or ''}".strip(), conference=r["conference"],
                                division=r["division"], stars=[dict(name=n, pos=pos) for _, n, pos in players[:3]],
                                strength=round(strength, 1)))
            ranked = sorted(out, key=lambda x: -x["strength"])
            for i, x in enumerate(ranked):
                x["outlook"] = "contender" if i < 8 else "bubble" if i < 18 else "rebuild"
            return out
        finally:
            c.close()

    def leagues(self, world=None):
        """Leagues in the template world (only the top league can be managed for now)."""
        tpl = self.world_path(world)
        if not tpl or not tpl.exists():
            return []
        c = sqlite3.connect(f"file:{tpl}?mode=ro", uri=True)
        try:
            return [dict(league_id=r[0], name=r[1], abbr=r[2], level=r[3], clubs=r[4], playable=r[3] in (1, None))
                    for r in c.execute("SELECT l.league_id, l.name, l.abbr, l.level, COUNT(t.team_id) FROM leagues l LEFT JOIN teams t "
                                       "USING (league_id) GROUP BY l.league_id ORDER BY COALESCE(l.level, 1), l.name")]
        finally:
            c.close()

    def new_game(self, name, team, seed=1, profile=None, world=None):
        tpl = self.world_path(world)
        if not tpl or not tpl.exists():
            raise ValueError("No template world to start from (run the server with --template, or import a database).")
        dest = self.path(name)
        if dest.exists():
            raise ValueError(f"A save called {dest.stem} already exists.")
        shutil.copyfile(tpl, dest)
        try:
            from ..game.state import new_game, connect
            from ..game import quickstart
            if quickstart.is_quickstart(dest):              # v48: a world captured at the start of a season
                quickstart.start(str(dest), team.upper(), int(seed))
            else:
                new_game(str(dest), team.upper(), int(seed))
            if profile:
                c = connect(str(dest))
                try:
                    from ..game import gm
                    gm.create(c, profile.get("name"), profile.get("nationality", ""), profile.get("background", "former_player"),
                              profile.get("age", 45))
                    gm.setup_manager(c, profile.get("ratings"), profile.get("template"), profile.get("reputation", "respected"),
                                     profile.get("role", "gm"), profile.get("unfireable", False))
                    if not profile.get("unemployed"):           # v38: the owner's welcome, the briefing, the press
                        from ..game import welcome
                        from ..game.state import get_state
                        welcome.start_career(c, get_state(c)[0])
                        c.commit()
                    if profile.get("challenge_mode"):          # v47: challenge mode and a challenge
                        from ..game import challenge
                        challenge.set_mode(c, True)
                        c.commit()
                    if profile.get("challenge") and not profile.get("unemployed"):
                        from ..game import challenge
                        from ..game.state import get_state
                        challenge.start(c, profile["challenge"], get_state(c)[0])
                        c.commit()
                    if profile.get("unemployed"):
                        if profile.get("role") == "gm_coach":
                            x = gm._extra(c)
                            x["role"] = "gm_coach"
                            gm._save_extra(c, x)
                        from ..game.state import get_state
                        gm.start_unemployed(c, get_state(c)[0])
                        c.commit()
                finally:
                    c.close()
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        return dest

    def save_as(self, conn, name, overwrite=False):
        dest = self.path(name)
        if dest.exists() and not overwrite:
            raise ValueError(f"A save called {dest.stem} already exists.")
        conn.commit()
        tmp = dest.with_suffix(".tmp")
        out = sqlite3.connect(tmp)
        try:
            conn.backup(out)
        finally:
            out.close()
        os.replace(tmp, dest)
        return dest

    # ---- rolling backups (phase A): saves/backups/<career>/<career> <game date>.db, the newest `keep` kept
    def backup_dir(self, stem):
        return self.folder / "backups" / clean_name(stem)

    def backup(self, conn, stem, label, keep=3):
        if keep <= 0:
            return None
        d = self.backup_dir(stem)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{clean_name(stem)} {clean_name(label)}.db"
        conn.commit()
        tmp = dest.with_suffix(".tmp")
        out = sqlite3.connect(tmp)
        try:
            conn.backup(out)
        finally:
            out.close()
        os.replace(tmp, dest)
        old = sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]
        for p in old:
            p.unlink(missing_ok=True)
        return dest

    def backups(self, stem):
        d = self.backup_dir(stem)
        if not d.exists():
            return []
        rows = sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [dict(file=p.name, label=p.stem[len(clean_name(stem)):].strip(), modified=p.stat().st_mtime, size=p.stat().st_size)
                for p in rows]

    def restore(self, stem, file, name):
        """Copy a backup out as a new save (never over the career it came from)."""
        src = (self.backup_dir(stem) / file).resolve()
        if src.parent != self.backup_dir(stem).resolve() or not src.exists():
            raise ValueError("No such backup.")
        dest = self.path(name)
        if dest.exists():
            raise ValueError(f"A save called {dest.stem} already exists.")
        shutil.copyfile(src, dest)
        return dest

    def delete(self, name, current=None):
        p = self.path(name)
        if current and Path(current).resolve() == p:
            raise ValueError("That save is open; load another one first.")
        if not p.exists():
            raise ValueError("No such save.")
        p.unlink()

    def rename(self, old, new, current=None):
        a, b = self.path(old), self.path(new)
        if current and Path(current).resolve() == a:
            raise ValueError("That save is open; load another one first.")
        if b.exists():
            raise ValueError(f"A save called {b.stem} already exists.")
        a.rename(b)
