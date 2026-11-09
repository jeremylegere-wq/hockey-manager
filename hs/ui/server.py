"""Local web UI: a small stdlib HTTP server that serves the front end and a JSON API over the game database.

    python -m hs.ui.server [game.db] --env env.json [--saves DIR] [--template world.db] [--port 8765] [--open]

Reads use hs.ui.api; every action is a CLI command line posted to /api/command and run by the same CLI object
(hs.game.cli.CLI), so rules, validation and messages are identical to the terminal. Local use only: the server
binds to 127.0.0.1 and has no authentication.

Saves (hs.ui.saves): with --saves the title screen lists the careers in that folder and can start a new one from
--template (a built world with no game started), load, save as, rename and delete. Without a db argument the server
opens on the title screen. The sim centre (hs.ui.simjob) runs time day by day in the background so the UI can
show the league as it plays, and can be stopped.
"""
from __future__ import annotations

import argparse
import io
import json
import mimetypes
import shutil
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..game.cli import CLI
from . import api
from . import screens as SC
from . import manager_view as MG
from . import settings
from .saves import Saves
from .simjob import SimJob

STATIC = Path(__file__).parent / "static"


def _me(c):
    from hs.game.state import user_team
    t = user_team(c)
    if t is None:
        raise RuntimeError("You are out of work: the club's books are for its GM.")
    return t


VIEWS = {
    "state": lambda c, q: api.state(c),
    "dashboard": lambda c, q: api.dashboard(c),
    "roster": lambda c, q: api.roster(c, include_system=q.get("system") == "1"),
    "player": lambda c, q: api.player(c, int(q["id"])),
    "contracts": lambda c, q: api.contracts_view(c),
    "offseason": lambda c, q: api.offseason_view(c),
    "standings": lambda c, q: api.standings(c, q.get("mode", "division")),
    "schedule": lambda c, q: api.schedule(c),
    "inbox": lambda c, q: api.inbox(c, q.get("all") == "1"),
    "history": lambda c, q: api.history(c, q.get("scope", "club")),
    "teams": lambda c, q: api.teams_list(c),
    "scouting": lambda c, q: api.scouting_view(c),
    "news": lambda c, q: api.news_view(c, q.get("scope", "club")),
    "game": lambda c, q: api.game_view(c, int(q["id"])),
    "trade": lambda c, q: api.trade_view(c, q.get("team")),
    "lines": lambda c, q: api.lines_view(c),
    "staff": lambda c, q: api.staff_view(c, q.get("role")),
    "board": lambda c, q: api.board_view(c),
    "tradeeval": lambda c, q: api.trade_eval(c, q["team"], q.get("give", ""), q.get("get", "")),
    "tradeask": lambda c, q: api.trade_ask(c, q["team"], q.get("get", "")),
    "tradeeval3": lambda c, q: api.trade_eval3(c, q["a"], q["b"], q.get("legs", "")),
    "card": lambda c, q: api.player_card(c, int(q["id"])),
    "negotiation": lambda c, q: api.negotiation_view(c, int(q["id"])),
    "standings2": lambda c, q: api.standings_full(c, q.get("mode", "wildcard")),
    "inbox2": lambda c, q: api.inbox_view(c, q.get("folder", "all"), q.get("q", "")),
    "newsfeed": lambda c, q: api.news_history(c, q.get("kind", "headlines"), q.get("scope", "league"),
                                               int(q.get("season") or 0) or None, int(q.get("offset", 0)),
                                               q.get("month", "")),
    "analytics": lambda c, q: api.analytics_view(c, q.get("tab", "teams"), q.get("team")),
    "stats": lambda c, q: api.stats_hub(c, q.get("season"), q.get("league"), q.get("split", "RS")),
    "team": lambda c, q: api.team_view(c, int(q["id"]), q.get("season")),
    "leaguehistory": lambda c, q: api.league_history(c),
    "retirednumbers": lambda c, q: dict(numbers=__import__("hs.game.numbers", fromlist=["x"]).retired_list(c, int(q.get("team") or __import__("hs.game.state", fromlist=["x"]).user_team(c) or 0)),
                                        games=__import__("hs.game.numbers", fromlist=["x"]).RETIRE_GAMES),
    "discipline": lambda c, q: __import__("hs.game.discipline", fromlist=["x"]).view(c),
    "arena": lambda c, q: __import__("hs.game.arena", fromlist=["x"]).view(c, _me(c)) if not q.get("seats") else
             __import__("hs.game.arena", fromlist=["x"]).quote(c, _me(c), q.get("seats"), q.get("quality") or 90),
    "ownergoals": lambda c, q: __import__("hs.game.owner_goals", fromlist=["x"]).view(c, _me(c)),
    "troles": lambda c, q: __import__("hs.game.troles", fromlist=["x"]).view(c, _me(c)),
    "pnl": lambda c, q: __import__("hs.game.accounts", fromlist=["x"]).pnl(c, _me(c), q.get("fy"), q.get("period"), q.get("columns") or "total",
                                                                         q.get("compare") or "none", q.get("level") or 3, q.get("zero") != "1"),
    "journal": lambda c, q: __import__("hs.game.accounts", fromlist=["x"]).journal(c, _me(c), q.get("fy"), q.get("code"), q.get("period")),
    "boardpack": lambda c, q: __import__("hs.game.accounts", fromlist=["x"]).board_pack(c, _me(c)),
    "cashflow": lambda c, q: __import__("hs.game.accounts", fromlist=["x"]).cash_statement(c, _me(c), q.get("fy")),
    "lineups": lambda c, q: __import__("hs.game.lineups", fromlist=["x"]).view(c),
    "intl": lambda c, q: __import__("hs.game.international", fromlist=["x"]).view(c, q.get("tid")),
    "challenge": lambda c, q: __import__("hs.game.challenge", fromlist=["x"]).view(c),
    "commish": lambda c, q: __import__("hs.game.commissioner", fromlist=["x"]).view(c, q.get("a"), q.get("b")),
    "college": lambda c, q: __import__("hs.game.college", fromlist=["x"]).view(c, q.get("program")),
    "expansion": lambda c, q: __import__("hs.game.expansion", fromlist=["x"]).view(c),
    "worldleagues": lambda c, q: __import__("hs.game.leagues", fromlist=["x"]).world_leagues_view(c, q.get("league"), q.get("season")),
    "playerx": lambda c, q: api.player_extras(c, int(q["id"])),
    "press": lambda c, q: api.press_view(c),
    "draft": lambda c, q: api.draft_view(c),
    "playoffs": lambda c, q: api.playoffs_view(c, q.get("season")),
    "warroom": lambda c, q: api.warroom_view(c),
    "gm": lambda c, q: __import__("hs.game.gm", fromlist=["x"]).career(c),
    "rights": lambda c, q: api.rights_view(c),
    "captaincy": lambda c, q: api.captaincy_view(c, q.get("c"), q.get("a", "")),
    "calendar": lambda c, q: api.calendar_view(c, q.get("month")),
    "freeagents": lambda c, q: api.freeagents_view(c, q.get("pos", "")),
    "prospects": lambda c, q: api.prospects_view(c, q.get("team") or None, q.get("scope") or None),
    "development": lambda c, q: api.development_view(c),
    "devlog": lambda c, q: api.devlog_view(c, q["id"]),
    "search": lambda c, q: api.search_view(c, q.get("q", "")),
    "article": lambda c, q: api.article_view(c, int(q["id"])),
    "strip": lambda c, q: SC.strip(c),
    "playtargets": lambda c, q: SC.play_targets(c),
    "leagueday": lambda c, q: SC.league_day(c, q.get("day")),
    "transactions": lambda c, q: SC.transactions_hub(c, q.get("tab", "free"), q.get("team") or None),
    "depth": lambda c, q: SC.depth_chart(c, q.get("team")),
    "txnlog": lambda c, q: SC.txn_log(c, q.get("season"), q.get("team"), q.get("kind", "")),
    "milestones": lambda c, q: SC.milestones(c),
    "reports": lambda c, q: SC.reports(c, q.get("kind", "positional")),
    "draftlog": lambda c, q: SC.draft_log(c, q.get("year")),
    "season": lambda c, q: SC.season_page(c, q.get("year")),
    "rules": lambda c, q: SC.rules_view(c),
    "teaminfo": lambda c, q: SC.team_info(c, int(q["id"])),
    "notes": lambda c, q: SC.notes_view(c),
    "playermarks": lambda c, q: SC.player_marks(c, int(q["id"])),
    "finances": lambda c, q: __import__("hs.game.finance", fromlist=["x"]).view(c, __import__("hs.game.state", fromlist=["x"]).user_team(c), q.get("season")),
    "scoutnet": lambda c, q: api.scoutnet_view(c),
    "bureau": lambda c, q: api.bureau_view(c, q.get("stage")),
    "mock": lambda c, q: api.mock_view(c),
    "devchart": lambda c, q: api.devchart(c, int(q["id"])),
    "people": lambda c, q: api.people_view(c, int(q["id"])),
    "harmony": lambda c, q: api.harmony_view(c, q.get("team")),
    "tactics": lambda c, q: api.tactics_view(c, q.get("opp")),
    "jobs": lambda c, q: __import__("hs.game.gm", fromlist=["x"]).job_market(c),
    "manager": lambda c, q: MG.manager_view(c),
    "assistant": lambda c, q: __import__("hs.game.assistant", fromlist=["x"]).suggestions(c),
    "find": lambda c, q: SC.player_search(c, q),
    "track": lambda c, q: __import__("hs.sim.rink2d", fromlist=["x"]).track(c, int(q["id"])),
    # v37, phase F: the calendar
    "rivalries": lambda c, q: __import__("hs.game.rivalry", fromlist=["x"]).view(c, int(q.get("team") or __import__("hs.game.state", fromlist=["x"]).user_team(c))),
    "exhibitions": lambda c, q: __import__("hs.game.exhibitions", fromlist=["x"]).exhibitions_view(c, q.get("kind") or None, q.get("year")),
    "exbox": lambda c, q: __import__("hs.game.exhibitions", fromlist=["x"]).boxscore(c, int(q["id"])),
    "allstar": lambda c, q: __import__("hs.game.exhibitions", fromlist=["x"]).allstar_view(c, q.get("year")),
    "hof": lambda c, q: __import__("hs.game.legacy", fromlist=["x"]).hof_view(c),
    "legacy": lambda c, q: __import__("hs.game.legacy", fromlist=["x"]).legacy_view(c, q.get("player"), q.get("all") != "1"),
    "gmleaders": lambda c, q: __import__("hs.game.legacy", fromlist=["x"]).gm_leaders(c),
    "achievements": lambda c, q: __import__("hs.game.legacy", fromlist=["x"]).achievements_view(c),
    "simleaders": lambda c, q: SC.sim_leaders(c),
}
NO_GAME_OK = {"state"}
UNEMPLOYED_OK = {"intl", "discipline", "college", "worldleagues", "hof", "legacy", "expansion", "retirednumbers", "state", "jobs", "manager", "gm", "news", "newsfeed", "standings", "standings2", "stats", "player", "playerx", "card", "team",
                 "teams", "leagueday", "season", "reports", "milestones", "draftlog", "rules", "search", "article", "game", "track",
                 "inbox", "inbox2", "strip", "playoffs", "leaguehistory", "worldleagues", "expansion", "college", "challenge", "commish", "retirednumbers", "intl", "lineups", "discipline", "find", "teaminfo", "txnlog", "transactions", "playermarks", "notes", "calendar", "people", "devchart",
                 "exhibitions", "exbox", "allstar", "hof", "legacy", "gmleaders", "achievements", "simleaders"}


class Game:
    """The open save (or none: the title screen), its CLI, the lock that serialises it, and the sim job."""

    def __init__(self, db, env, saves=None, template=None):
        self.env = env
        self.lock = threading.Lock()
        self.cli = None
        self.db = None
        self.saves = Saves(saves, template) if saves else None
        self.sim = SimJob(self)
        self.desktop = None                       # hs.app sets this to the native window when there is one
        self.httpd = None
        if db:
            self.open(db)

    def settings_path(self):
        if self.saves:
            return self.saves.folder / "settings.json"
        return Path(self.db).with_name("hockeysim_settings.json") if self.db else Path("hockeysim_settings.json")

    def quit(self):
        """Exit from the game's menu: stop the sim, close the save, close the window (or stop the server)."""
        if self.sim.running:
            self.sim.stop()
        with self.lock:
            if self.cli is not None:
                self.cli.conn.commit()
        if self.desktop is not None:
            self.desktop.close()
        elif self.httpd is not None:
            self.httpd.shutdown()

    def open(self, db):
        if self.cli is not None:
            self.cli.conn.close()
        self.cli = CLI(str(db), self.env, out=io.StringIO(), shared=True)
        self.db = str(db)
        c = self.cli.conn
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='pack_info'").fetchone():
            c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('live_draft', '1')")   # the draft room runs it
            c.commit()
        try:                                                   # repairs for saves made by earlier versions
            from ..game import people
            from ..game.state import get_state
            if people.fix_goalie_letters(c, get_state(c)[0]):
                c.commit()
            # v32: a GM fired in an older version kept his club id, so the club got no AI management: hand it back
            if c.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone() and \
                    c.execute("SELECT team_id FROM manager WHERE id=1").fetchone()[0] is not None:
                from ..game import gm as GMx
                GMx.lose_job(c, get_state(c)[0], "fired_old")
                c.commit()
        except Exception:
            pass

    def rolling_backup(self, force=False):
        """A rolling backup of the open career once a game week and at each new phase (Settings: backups, 0-10).
        Call with the lock held. Never fails the caller."""
        if not self.saves or self.cli is None:
            return None
        try:
            from ..game.state import get_state
            from ..game import contracts as K
            c = self.cli.conn
            keep = settings.load(self.settings_path()).get("backups", 3)
            if keep <= 0:
                return None
            day, phase = get_state(c)[0], K.season_state(c)
            last = dict(c.execute("SELECT key, value FROM pack_info WHERE key IN ('backup_day', 'backup_phase')").fetchall())
            import datetime as _dt
            due = force or last.get("backup_phase") != phase or not last.get("backup_day") or \
                (_dt.date.fromisoformat(day) - _dt.date.fromisoformat(last["backup_day"])).days >= 7
            if not due:
                return None
            c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('backup_day', ?)", (day,))
            c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('backup_phase', ?)", (phase,))
            return self.saves.backup(c, Path(self.db).stem, f"{day} {phase.replace('_', ' ')}", keep)
        except Exception as e:                                 # a backup must never break play
            print("backup failed:", e)
            return None

    def export_csv(self, name, rows):
        import re as _re
        import datetime as _dt
        base = Path(self.saves.folder) if self.saves else Path(self.db or ".").parent
        d = base / "exports"
        d.mkdir(parents=True, exist_ok=True)
        stem = _re.sub(r"[^A-Za-z0-9 _-]", "", str(name))[:60].strip() or "table"
        p = d / f"{stem} {_dt.datetime.now().strftime('%Y-%m-%d %H%M%S')}.csv"
        p.write_text(SC.to_csv(rows), encoding="utf-8")
        return dict(ok=True, path=str(p), rows=max(0, len(rows) - 1))

    def view(self, name, q):
        with self.lock:
            if self.cli is None:
                if name == "state":
                    return dict(started=False, loaded=False, saves=bool(self.saves))
                raise RuntimeError("No game is loaded.")
            if name not in UNEMPLOYED_OK and self.cli.conn.execute("SELECT team_id FROM manager WHERE id=1").fetchone()[0] is None:
                raise RuntimeError("You are out of work: that screen needs a club. The Job Centre lists the clubs looking for a GM.")
            out = VIEWS[name](self.cli.conn, q)
            if name == "state":
                out["loaded"] = True
                out["save"] = Path(self.db).stem
                out["saves"] = bool(self.saves)
                out["sim_running"] = self.sim.running
            return out

    def command(self, line):
        if self.sim.running:
            return dict(ok=False, output="The simulation is running; stop it first.")
        with self.lock:
            if self.cli is None:
                return dict(ok=False, output="No game is loaded.")
            buf = io.StringIO()
            self.cli.out = buf
            self.cli.status_code = 0
            self.cli.onecmd(line)
            self.rolling_backup()
            return dict(ok=self.cli.status_code == 0, output=buf.getvalue())

    def editor(self, body):
        """v41: the editor and bulk import/export (hs/game/editor.py)."""
        from ..game import editor as ED
        if self.sim.running:
            return dict(ok=False, output="The simulation is running; stop it first.")
        with self.lock:
            if self.cli is None:
                return dict(ok=False, output="No game is loaded.")
            c = self.cli.conn
            act = body.get("action")
            try:
                if act == "state":
                    out = dict(ok=True, enabled=ED.enabled(c), edited=ED.edited(c))
                elif act == "enable":
                    ED.set_enabled(c, bool(body.get("on")))
                    out = dict(ok=True, enabled=ED.enabled(c), edited=ED.edited(c))
                elif act == "form":
                    out = dict(ok=True, form=ED.player_form(c, int(body["player_id"])))
                elif act == "save":
                    done = ED.edit_player(c, int(body["player_id"]), body.get("changes") or {})
                    out = dict(ok=True, output=f"Saved: {', '.join(done) or 'no changes'}.", form=ED.player_form(c, int(body["player_id"])))
                elif act == "club":
                    done = ED.edit_club(c, int(body["team_id"]), body.get("changes") or {})
                    out = dict(ok=True, output=f"Saved: {', '.join(done) or 'no changes'}.")
                elif act == "clubs":
                    from ..schema import top_league_sql
                    out = dict(ok=True, clubs=[dict(r) for r in c.execute(
                        f"SELECT team_id, abbr, name, nickname, conference, division FROM teams WHERE {top_league_sql()} ORDER BY name")])
                elif act == "export":
                    out = dict(ok=True, csv=ED.export_players(c, body.get("scope", "mine")))
                elif act == "import":
                    out = dict(ok=True, result=ED.import_players(c, body.get("text", ""), bool(body.get("apply"))))
                elif act == "career_import":                  # v41: careers before the save (the M3 profiles)
                    from ..game import career as CR
                    out = dict(ok=True, result=CR.import_m3(c, body.get("text", ""), bool(body.get("apply"))))
                elif act == "history_db":                     # v42: careers and drafts from the database file
                    from ..adapters import db_history
                    out = dict(ok=True, result=db_history.load(c, body.get("db_file", "").strip().strip('"'),
                                                               body.get("export_folder", "").strip().strip('"'), bool(body.get("apply"))))
                elif act == "seasons_import":                 # v42: past seasons, line by line
                    from ..game import career as CR
                    out = dict(ok=True, result=CR.import_seasons(c, body.get("text", ""), bool(body.get("apply"))))
                elif act == "schedule_export":                # v48: this season's schedule
                    from ..game import schedule_io as SI
                    out = dict(ok=True, csv=SI.export_csv(c))
                elif act == "schedule_import":                # v48: replace the unplayed games (commissioner)
                    from ..game import schedule_io as SI
                    out = dict(ok=True, result=SI.import_csv(c, body.get("text", ""), bool(body.get("apply"))))
                elif act == "drafts_import":                  # v41: past drafts from a CSV
                    from ..game import career as CR
                    out = dict(ok=True, result=CR.import_drafts(c, body.get("text", ""), bool(body.get("apply"))))
                else:
                    return dict(ok=False, output="Unknown editor action.")
            except (ValueError, FileNotFoundError) as e:
                c.rollback()
                return dict(ok=False, output=str(e))
            c.commit()
            return out

    # ---- v48: logos (image files named by club abbreviation: MTL.png, TOR.svg ...)
    LOGO_EXT = (".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif")
    LOGO_MAX = 2_000_000

    def logo_dirs(self):
        out = []
        if self.saves:
            out.append(self.saves.folder.parent / "logos")
            if self.saves.template:
                out.append(self.saves.template.parent / "logos")
        if self.db:
            out.append(Path(self.db).parent.parent / "logos")
        seen, res = set(), []
        for d in out:
            r = d.resolve()
            if r not in seen:
                seen.add(r)
                res.append(d)
        return res

    def logos(self):
        out = set()
        for d in self.logo_dirs():
            if d.exists():
                for f in d.iterdir():
                    if f.suffix.lower() in self.LOGO_EXT and f.is_file() and f.stat().st_size <= self.LOGO_MAX:
                        out.add(f.stem.upper())
        return out

    def logo_file(self, abbr):
        abbr = "".join(ch for ch in abbr.upper() if ch.isalnum())[:8]
        if not abbr:
            return None
        for d in self.logo_dirs():
            if not d.exists():
                continue
            for f in d.iterdir():
                if f.stem.upper() == abbr and f.suffix.lower() in self.LOGO_EXT and f.is_file() and f.stat().st_size <= self.LOGO_MAX \
                        and f.resolve().parent == d.resolve():
                    return f
        return None

    PHOTO_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")

    def face_dirs(self):
        return [d.parent / "faces" for d in self.logo_dirs()]

    def face(self, pid):
        """(bytes, mime): his photo (faces/<player id>.png ..., or a pack's headshot path), else his jersey's back."""
        for d in self.face_dirs():
            for ext in self.PHOTO_EXT:
                f = d / f"{pid}{ext}"
                if f.is_file() and f.stat().st_size <= self.LOGO_MAX:
                    return f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if self.cli is None:
            raise ValueError("no game")
        from ..game import numbers
        with self.lock:
            c = self.cli.conn
            r = c.execute("SELECT headshot_path FROM players WHERE player_id=?", (pid,)).fetchone()
            if r and r[0]:
                hp = Path(r[0])
                if not hp.is_absolute() and self.db:
                    hp = Path(self.db).parent.parent / "worlds" / hp
                if hp.is_file() and hp.suffix.lower() in self.PHOTO_EXT and hp.stat().st_size <= self.LOGO_MAX:
                    return hp.read_bytes(), mimetypes.guess_type(hp.name)[0] or "application/octet-stream"
            return numbers.jersey_svg(c, pid).encode(), "image/svg+xml"

    def import_faces(self, folder):
        """Copy photo files named by player id from a folder into the faces folder."""
        src = Path(str(folder).strip().strip('"')).expanduser()
        if not src.is_dir():
            raise ValueError(f"No folder {src}.")
        if not self.saves:
            raise ValueError("This server was started without a saves folder.")
        dest = self.saves.folder.parent / "faces"
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in sorted(src.iterdir()):
            if f.is_file() and f.suffix.lower() in self.PHOTO_EXT and f.stem.isdigit() and f.stat().st_size <= self.LOGO_MAX:
                for old in dest.glob(f.stem + ".*"):
                    old.unlink()
                shutil.copyfile(f, dest / (f.stem + f.suffix.lower()))
                n += 1
        return n, dest

    def import_logos(self, folder):
        """Copy image files named by club abbreviation from a folder into the logos folder."""
        src = Path(str(folder).strip().strip('"')).expanduser()
        if not src.is_dir():
            raise ValueError(f"No folder {src}.")
        if not self.saves:
            raise ValueError("This server was started without a saves folder.")
        dest = self.saves.folder.parent / "logos"
        dest.mkdir(parents=True, exist_ok=True)
        n, skipped = 0, []
        for f in sorted(src.iterdir()):
            if not f.is_file() or f.suffix.lower() not in self.LOGO_EXT:
                continue
            if f.stat().st_size > self.LOGO_MAX:
                skipped.append(f"{f.name} (over 2 MB)")
                continue
            stem = "".join(ch for ch in f.stem.upper() if ch.isalnum())[:8]
            if not stem:
                continue
            for old in dest.glob(stem + ".*"):
                old.unlink()
            shutil.copyfile(f, dest / (stem + f.suffix.lower()))
            n += 1
        return n, skipped, dest

    # ---- saves
    def saves_list(self, world=None):
        if not self.saves:
            return dict(enabled=False, current=Path(self.db).stem if self.db else None)
        try:
            self.saves.world_path(world)
        except ValueError:
            world = None
        return dict(enabled=True, saves=self.saves.list(self.db), teams=self.saves.teams(world), leagues=self.saves.leagues(world),
                    worlds=self.saves.worlds(), world=world or "",
                    backgrounds={k: dict(label=v[0], text=v[1]) for k, v in __import__("hs.game.gm", fromlist=["x"]).BACKGROUNDS.items()},
                    manager=MG.setup_options(),
                    current=Path(self.db).stem if self.db else None, folder=str(self.saves.folder))

    def save_action(self, body):
        if not self.saves:
            raise ValueError("This server was started without a saves folder (--saves).")
        if self.sim.running:
            raise ValueError("Stop the simulation first.")
        act = body.get("action")
        with self.lock:
            if act == "new":
                dest = self.saves.new_game(body.get("name") or f"{body.get('team', 'New')} career", body["team"],
                                           body.get("seed", 1), body.get("profile"), body.get("world") or None)
                self.open(dest)
                return dict(ok=True, output=f"New career: {dest.stem}.")
            if act == "import_world":                # v38: build a world from your own database export
                key, stats = self.saves.import_world(body.get("path", ""), body.get("name"), body.get("db_file"))
                h = stats.get("history")
                return dict(ok=True, world=key, output=f"Imported {stats.get('players', 0)} players, {stats.get('teams', 0)} clubs "
                                                       f"and {stats.get('contracts', 0)} contracts into the world '{key}'"
                                                       + (f", with {h['skater_lines'] + h['goalie_lines']:,} career lines and "
                                                          f"{h['draft_picks_added']:,} past draft picks" if h else "")
                                                       + (f" (history skipped: {stats['history_error']})" if stats.get("history_error") else "") + ".")
            if act == "faces":                       # v49: import a folder of player photos (named by player id)
                n, dest = self.import_faces(body.get("path", ""))
                return dict(ok=True, output=f"Imported {n} photo(s) into {dest}.")
            if act == "logos":                       # v48: import a folder of club logos
                n, skipped, dest = self.import_logos(body.get("path", ""))
                return dict(ok=True, output=f"Imported {n} logo(s) into {dest}" + (f"; skipped {', '.join(skipped)}" if skipped else "") + ".")
            if act == "quickstart":                  # v48: save the world at the start of a season for new careers
                if self.cli is None:
                    raise ValueError("No game is loaded.")
                dest = self.saves.make_quickstart(self.cli.conn, body.get("name") or "Quickstart")
                return dict(ok=True, world=dest.stem, output=f"Saved the quickstart {dest.stem}: it is listed with the worlds when you start a new career.")
            if act == "load":
                p = self.saves.path(body["name"])
                if not p.exists():
                    raise ValueError("No such save.")
                self.open(p)
                return dict(ok=True, output=f"Loaded {p.stem}.")
            if act == "saveas":
                if self.cli is None:
                    raise ValueError("No game is loaded.")
                dest = self.saves.save_as(self.cli.conn, body["name"], body.get("overwrite", False))
                if body.get("switch"):
                    self.open(dest)
                return dict(ok=True, output=f"Saved a copy as {dest.stem}" + (" and switched to it." if body.get("switch") else "."))
            if act == "delete":
                self.saves.delete(body["name"], self.db)
                return dict(ok=True, output="Deleted.")
            if act == "rename":
                self.saves.rename(body["name"], body["to"], self.db)
                return dict(ok=True, output="Renamed.")
            if act == "backups":
                stem = body.get("name") or (Path(self.db).stem if self.db else None)
                return dict(ok=True, career=stem, backups=self.saves.backups(stem) if stem else [])
            if act == "restore":
                dest = self.saves.restore(body["career"], body["file"], body["name"])
                if body.get("switch", True):
                    self.open(dest)
                return dict(ok=True, output=f"Restored the backup as {dest.stem}.")
            if act == "backup":
                if self.cli is None:
                    raise ValueError("No game is loaded.")
                p = self.rolling_backup(force=True)
                return dict(ok=bool(p), output=f"Backup made: {p.name}" if p else "Backups are off (Settings).")
            if act == "close":
                if self.cli is not None:
                    self.cli.conn.commit()
                    self.cli.conn.close()
                self.cli, self.db = None, None
                return dict(ok=True, output="Closed. Your progress is saved.")
        raise ValueError("Unknown save action.")


def make_handler(game):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", cache=False):
            data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/saves":
                return self._send(200, game.saves_list((parse_qs(u.query).get("world") or [None])[0] or None))
            if u.path == "/api/settings":
                return self._send(200, settings.load(game.settings_path()))
            if u.path == "/api/app":
                return self._send(200, dict(desktop=game.desktop is not None, version=settings.VERSION))
            if u.path == "/api/simstatus":
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self._send(200, game.sim.status(int(q.get("since", 0))))
            if u.path == "/api/logos":                     # v48: your own club logos
                return self._send(200, dict(logos=sorted(game.logos()), folders=[str(d) for d in game.logo_dirs()]))
            if u.path.startswith("/face/"):               # v49: a player's photo, or the back of his jersey
                try:
                    data, mime = game.face(int(u.path[6:].split("?")[0]))
                except (ValueError, TypeError):
                    return self._send(404, b"no face", "text/plain")
                return self._send(200, data, mime)
            if u.path.startswith("/logo/"):
                f = game.logo_file(u.path[6:])
                if not f:
                    return self._send(404, b"no logo", "text/plain")
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            if u.path.startswith("/api/"):
                name = u.path[5:]
                if name not in VIEWS:
                    return self._send(404, dict(error="unknown view"))
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    return self._send(200, game.view(name, q))
                except Exception as e:                     # report, keep serving
                    traceback.print_exc()
                    return self._send(500, dict(error=str(e), trace=traceback.format_exc(limit=3)))
            path = STATIC / ("index.html" if u.path in ("/", "") else u.path.lstrip("/"))
            if not path.resolve().is_relative_to(STATIC.resolve()) or not path.exists():
                return self._send(404, b"not found", "text/plain")
            return self._send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                              cache=u.path.startswith("/vendor/"))

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/command":
                    return self._send(200, game.command(body.get("line", "")))
                if path == "/api/save":
                    return self._send(200, game.save_action(body))
                if path == "/api/editor":                   # v41: the editor
                    return self._send(200, game.editor(body))
                if path == "/api/settings":
                    return self._send(200, settings.save(game.settings_path(), body))
                if path == "/api/export":                   # File > Export: a table as CSV, written next to the saves
                    return self._send(200, game.export_csv(body.get("name", "table"), body.get("rows") or []))
                if path == "/api/quit":                     # Exit: the desktop window closes; a plain server stops
                    self._send(200, dict(ok=True))
                    threading.Thread(target=game.quit, daemon=True).start()
                    return None
                if path == "/api/title":                    # the desktop window's title follows the career
                    if game.desktop is not None:
                        game.desktop.set_title(str(body.get("title", ""))[:120])
                    return self._send(200, dict(ok=True))
                if path == "/api/sim":
                    return self._send(200, game.sim.start(body.get("mode", "day"), body.get("pace", 0.6), body.get("until")))
                if path == "/api/simstop":
                    return self._send(200, game.sim.stop())
                if path == "/api/simpace":
                    game.sim.pace = max(0.0, min(5.0, float(body.get("pace", 0.6))))
                    return self._send(200, dict(ok=True, pace=game.sim.pace))
                return self._send(404, dict(error="unknown"))
            except Exception as e:
                return self._send(400 if isinstance(e, (ValueError, RuntimeError, KeyError)) else 500,
                                  dict(ok=False, output=str(e), error=str(e)))
    return Handler


def make_server(db, env, port=8765, saves=None, template=None):
    """The server, bound to 127.0.0.1 on the first free port from `port`; returns (httpd, url, game)."""
    game = Game(db, env, saves, template)
    for p in range(port, port + 20):              # the port is taken (an earlier server still running): try the next
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(game))
            break
        except OSError:
            if p == port + 19:
                raise
    if p != port:
        print(f"Port {port} is in use; using {p}.")
    game.httpd = httpd
    return httpd, f"http://127.0.0.1:{p}/", game


def serve(db, env, port=8765, open_browser=False, saves=None, template=None):
    httpd, url, game = make_server(db, env, port, saves, template)
    print(f"Serving {db or 'the title screen'} at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?", help="save to open (omit to start on the title screen; needs --saves)")
    ap.add_argument("--env", default="auto", help="league environment json (auto: save/env_2025.json or data/env_default.json)")
    ap.add_argument("--saves", help="folder of save slots (enables the title screen: new game, load, save as)")
    ap.add_argument("--template", help="a built world with no game started, copied for each new game")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    from ..bootstrap import resolve
    a.template, a.env = resolve(a.template, a.env)
    if not a.db and not a.saves:
        ap.error("give a save to open, or --saves for the title screen")
    serve(a.db, json.load(open(a.env)), a.port, a.open, a.saves, a.template)


if __name__ == "__main__":
    main()
