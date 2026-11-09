"""Command-line game loop.

    python -m hs.game.cli game.db --env env.json                       # interactive
    python -m hs.game.cli game.db --env env.json -c "new MTL 7" -c "sim week" -c "standings"
"""
from __future__ import annotations

import argparse
import cmd
import datetime
import json
import re
import sys

from ..league import standings as st
from ..league.season import db_rules, team_rows
from ..sim.engine import Skill
from ..sim.loader import load_teams
from . import contracts as K
from . import offseason as O
from . import roster as R
from .dayloop import remaining, sim_until
from .state import connect, get_state, new_game, season_state, user_team

SK_COLS = [("OA", "offensive_awareness"), ("PAS", "passing"), ("PCK", "puck_control"), ("SHT", "shot_accuracy"),
           ("POS", "positioning"), ("DEF", "defensive_awareness"), ("HIT", "hitting")]
G_COLS = [("POS", "goalie_positioning"), ("REF", "reflexes"), ("GLV", "glove"), ("BLK", "blocker"),
          ("LOW", "low_shot_save"), ("REB", "rebound_control")]


POSTURE_WORDS = {"contender": "contending", "middle": "in the middle of the pack", "seller": "rebuilding"}
GROUP_WORDS = {"F": "forwards", "D": "defence", "G": "goal"}


def team_abbr_of(cli, tid):
    return cli.conn.execute("SELECT abbr FROM teams WHERE team_id=?", (tid,)).fetchone()[0]


class CLI(cmd.Cmd):
    prompt = "hs> "
    intro = "NHL Franchise Simulator. Type help for commands."

    def __init__(self, db, env, out=None, shared=False):
        super().__init__()
        self.db, self.env, self.skill, self.shared = db, env, Skill(), shared
        self.conn = connect(db, shared)
        from ..sim.engine import skill_for
        has_rules = self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='pack_info'").fetchone()
        self.skill = skill_for(db_rules(self.conn, base=True) if has_rules else None)   # a pack may pin its constants
        self.out = out or sys.stdout
        self.status_code = 0

    # ---- helpers
    def p(self, *a):
        print(*a, file=self.out)

    def onecmd(self, line):
        try:
            return super().onecmd(line)
        except (R.RosterError, ValueError, RuntimeError, KeyError, TypeError) as e:
            self.conn.rollback()
            self.p(f"Error: {type(e).__name__ if not isinstance(e, (R.RosterError, ValueError)) else ''}{': ' if not isinstance(e, (R.RosterError, ValueError)) else ''}{e}")
            self.status_code = 1
            return False

    def emptyline(self):
        pass

    def do_help(self, arg):
        """help [command]: the commands, or one command's description."""
        # v39 (#12): cmd.Cmd writes help to stdout, which the game window never saw ("Done.")
        if arg:
            f = getattr(self, "do_" + arg.strip().split()[0], None)
            self.p((f.__doc__ or f"No description for {arg}.").strip() if f else f"Unknown command: {arg}.")
            return
        names = sorted(n[3:] for n in dir(self) if n.startswith("do_") and n not in ("do_EOF",))
        self.p("Commands (help <command> for one):")
        for n in names:
            doc = (getattr(self, "do_" + n).__doc__ or "").strip().splitlines()
            self.p(f"  {n:<16} {doc[0][:90] if doc else ''}")

    def default(self, line):
        self.p(f"Unknown command: {line.split()[0]}. Type help for the list.")
        self.status_code = 1

    def need(self, allow_fired=False):
        if get_state(self.conn) is None:
            raise ValueError("No game started. Use: new <TEAM_ABBR> [seed]")
        fired = self.conn.execute("SELECT value FROM pack_info WHERE key='gm_status'").fetchone()
        if fired and not allow_fired:
            raise ValueError("You are out of work. `jobs` lists the clubs looking for a GM; `apply <ABBR>` to apply. "
                             "`sim` and `offseason` keep the world going.")
        if user_team(self.conn) is None and not fired:
            raise ValueError("No game started. Use: new <TEAM_ABBR> [seed]")
        return user_team(self.conn)

    def today(self):
        return get_state(self.conn)[0]

    def abbr(self):
        return {r["team_id"]: r["abbr"] for r in self.conn.execute("SELECT team_id, abbr FROM teams")}

    def team_by_abbr(self, a):
        from ..schema import top_league_sql
        r = self.conn.execute(f"SELECT team_id FROM teams WHERE UPPER(abbr)=UPPER(?) AND {top_league_sql()}",
                              (a,)).fetchone()
        if not r:
            raise ValueError(f"Unknown team {a}")
        return r["team_id"]

    def find(self, text, where="1=1", args=()):
        text = text.strip()
        if text.isdigit():
            rows = self.conn.execute(f"SELECT player_id, first_name, last_name, position, team_id FROM players "
                                     f"WHERE player_id=? AND {where}", (int(text), *args)).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT player_id, first_name, last_name, position, team_id FROM players WHERE "
                f"LOWER(first_name || ' ' || last_name) LIKE ? AND {where} ORDER BY last_name",
                (f"%{text.lower()}%", *args)).fetchall()
        if not rows:
            raise ValueError(f"No player matches '{text}'.")
        if len(rows) > 1:
            raise ValueError("Ambiguous, be more specific: " + "; ".join(
                f"{r['first_name']} {r['last_name']} ({r['position']}, #{r['player_id']})" for r in rows[:10]))
        return rows[0]

    def age(self, bd):
        t = datetime.date.fromisoformat(self.today())
        b = datetime.date.fromisoformat(bd)
        return t.year - b.year - ((t.month, t.day) < (b.month, b.day))

    def season_id(self):
        return self.conn.execute("SELECT season_id FROM seasons ORDER BY start_year DESC LIMIT 1").fetchone()[0]

    def record(self, team):
        rec, _ = st.table(self.conn, self.season_id())
        r = rec.get(team)
        pts = db_rules(self.conn)["points"]
        return r, (st.points(r, pts) if r else 0)

    # ---- commands
    def do_new(self, arg):
        "new <TEAM_ABBR> [seed]: start a new game in an ingested database"
        a = arg.split()
        if not a:
            raise ValueError("Usage: new <TEAM_ABBR> [seed]")
        self.conn.close()
        try:
            new_game(self.db, a[0], int(a[1]) if len(a) > 1 else 1)
        finally:
            self.conn = connect(self.db, self.shared)
        from . import welcome                            # v38: the owner's welcome, the briefing, the press
        welcome.start_career(self.conn, self.today())
        self.conn.commit()
        self.p(f"New game: managing {a[0].upper()}. The season starts after {self.today()}.")

    def do_status(self, arg):
        "status: date, record, next game, injuries, roster size, inbox"
        me = self.need()
        ab = self.abbr()
        r, pts = self.record(me)
        rec = f"{r['w']}-{r['l']}-{r['otl']} ({pts} pts)" if r else "no games yet"
        nxt = self.conn.execute("SELECT game_date, home_team_id, away_team_id FROM games WHERE played=0 AND game_type='RS' "
                                "AND (home_team_id=? OR away_team_id=?) ORDER BY game_date LIMIT 1", (me, me)).fetchone()
        inj = self.conn.execute("SELECT COUNT(*) FROM players WHERE team_id=? AND status='injured'", (me,)).fetchone()[0]
        unread = self.conn.execute("SELECT COUNT(*) FROM inbox WHERE read=0").fetchone()[0]
        self.p(f"Team {ab[me]}   Date {self.today()}   Season: {season_state(self.conn)}")
        self.p(f"Record {rec}")
        if nxt:
            where = f"vs {ab[nxt['away_team_id']]}" if nxt["home_team_id"] == me else f"@ {ab[nxt['home_team_id']]}"
            self.p(f"Next game: {nxt['game_date']} {where}")
        else:
            self.p("Next game: none")
        self.p(f"Injured {inj}   Roster {len(R.roster(self.conn, me))}   Unread messages {unread}")
        room = K.cap_room(self.conn, me, K.signing_year(self.conn))
        pay = K.payroll(self.conn, me, K.signing_year(self.conn))
        self.p(f"Payroll ${pay:,.0f}" + (f"   Cap room ${room:,.0f}" if room is not None else "   (no salary cap)")
               + f"   [{K.signing_year(self.conn)}-{(K.signing_year(self.conn) + 1) % 100:02d}]")

    def do_sim(self, arg):
        "sim day|week|next|season|to <YYYY-MM-DD>: advance time (stops early if you are needed)"
        me = self.need(allow_fired=True)
        a = arg.split()
        if not a:
            raise ValueError("Usage: sim day|week|next|season|to <date>")
        if remaining(self.conn) == 0 and season_state(self.conn) != "regular_season":
            self.p("The season is finished. Use `offseason` to move through the offseason.")
            return
        ab = self.abbr()

        def show(s):
            for gid, h, aw, hg, ag, ot in s.results:
                if me in (h, aw):
                    tag = " (OT)" if ot == 1 else " (SO)" if ot == 2 else ""
                    self.p(f"{s.day}  {ab[aw]} {ag} @ {ab[h]} {hg}{tag}")
            for pid, t, d in s.injuries:
                if t == me:
                    n = self.conn.execute("SELECT first_name||' '||last_name n FROM players WHERE player_id=?",
                                          (pid,)).fetchone()["n"]
                    self.p(f"{s.day}  INJURY: {n} out {d} day(s)")
            for t in s.trades:
                self.p(f"{s.day}  TRADE: {t}")
            for t in s.waivers:
                self.p(f"{s.day}  WAIVERS: {t}")
            my_ab = ab.get(me, "")
            for t in getattr(s, "board", []):
                if t.startswith(my_ab) or "fired their GM" in t or t.startswith(("Directive", "Owner's directive")):
                    self.p(f"{s.day}  BOARD: {t}")
            if "trade_offer" in s.user_alerts:
                from . import gm_trades as GT
                for r in GT.open_offers(self.conn):
                    if r["made"] == s.day:
                        self.p(f"{s.day}  TRADE OFFER: {GT.describe_offer(self.conn, r)} (`accept {r['offer_id']}` / "
                               f"`decline {r['offer_id']}`)")
            other = [x for x in s.user_alerts if x.startswith("short")]
            if other:
                self.p(f"{s.day}  ATTENTION: short of players at {', '.join(x.split(':')[1] for x in other)}")
        if a[0] == "day":
            kw = dict(days=1)
        elif a[0] == "week":
            kw = dict(days=7)
        elif a[0] == "next":
            kw = dict(through_user_game=True)
        elif a[0] == "season":
            kw = dict(to_end=True)
        elif a[0] == "to" and len(a) > 1:
            datetime.date.fromisoformat(a[1])
            kw = dict(until_date=a[1])
        else:
            raise ValueError("Usage: sim day|week|next|season|to <date>")
        from . import challenge as CH                  # v47: challenge mode keeps in-season sims short
        CH.check_sim(self.conn, a[0], (datetime.date.fromisoformat(a[1]) - datetime.date.fromisoformat(self.today())).days
                     if a[0] == "to" else None)
        res = sim_until(self.conn, self.env, self.skill, me, on_day=show, **kw)
        self.p(f"Simulated {len(res)} day(s); date is now {self.today()}.")
        if season_state(self.conn) == "finished":
            champ = self.conn.execute("SELECT value FROM pack_info WHERE key='champion'").fetchone()
            t = next(t for t in team_rows(self.conn) if str(t["team_id"]) == champ["value"])
            name = f"{t['name']} {t['nickname'] or ''}".strip()
            self.p(f"Season finished. Champion: {name}")

    def do_standings(self, arg):
        "standings [division|conference|league]"
        self.need()
        mode = (arg.split() or ["division"])[0]
        if mode not in ("division", "conference", "league"):
            raise ValueError("Usage: standings [division|conference|league]")
        rules = db_rules(self.conn)
        rec, h2h = st.table(self.conn, self.season_id())
        if not rec:
            self.p("No games played yet.")
            return
        order = st.rank(rec, h2h, rules)
        info = {t["team_id"]: t for t in team_rows(self.conn)}
        groups = {}
        for t in order:
            i = info[t]
            key = {"division": f"{i['conference']} - {i['division']}", "conference": i["conference"],
                   "league": "League"}[mode]
            groups.setdefault(key, []).append(t)
        pts = rules["points"]
        for key in sorted(groups):
            ties = any(rec[t].get("t") for t in order)
            self.p(f"\n{key}\n  {'':<5}{'GP':>3}{'W':>4}{'L':>4}{'OTL':>4}" + (f"{'T':>4}" if ties else "")
                   + f"{'PTS':>5}{'GF':>5}{'GA':>5}{'DIFF':>6}")
            for t in groups[key]:
                r = rec[t]
                self.p(f"  {info[t]['abbr']:<5}{r['gp']:>3}{r['w']:>4}{r['l']:>4}{r['otl']:>4}"
                       + (f"{r.get('t', 0):>4}" if ties else "") + f"{st.points(r, pts):>5}"
                       f"{r['gf']:>5}{r['ga']:>5}{r['gf'] - r['ga']:>+6}")

    def _games(self, where, order, n):
        me = self.need()
        ab = self.abbr()
        return me, ab, self.conn.execute(
            f"SELECT game_id, game_date, home_team_id h, away_team_id a, home_goals hg, away_goals ag, went_to_ot ot FROM games "
            f"WHERE {where} AND (home_team_id=? OR away_team_id=?) ORDER BY game_date {order} LIMIT ?",
            (me, me, n)).fetchall()

    def do_schedule(self, arg):
        "schedule [n]: next n games (default 5)"
        me, ab, rows = self._games("played=0 AND game_type='RS'", "ASC", int(arg) if arg.strip() else 5)
        for r in rows:
            self.p(f"{r['game_date']}  " + (f"vs {ab[r['a']]}" if r["h"] == me else f"@ {ab[r['h']]}"))
        if not rows:
            self.p("No games remaining.")

    def do_results(self, arg):
        "results [n]: last n results (default 5)"
        me, ab, rows = self._games("played=1", "DESC", int(arg) if arg.strip() else 5)
        for r in rows:
            tag = (" (OT)" if r["ot"] == 1 else " (SO)" if r["ot"] == 2 else "") + (" tie" if r["hg"] == r["ag"] else "")
            self.p(f"{r['game_date']}  {ab[r['a']]} {r['ag']} @ {ab[r['h']]} {r['hg']}{tag}   (recap {r['game_id']})")
        if not rows:
            self.p("No games played yet.")

    def _game_id(self, arg):
        me = self.need()
        a = arg.strip()
        if a.isdigit():
            return int(a)
        r = self.conn.execute("SELECT game_id FROM games WHERE played=1 AND (home_team_id=? OR away_team_id=?) ORDER BY "
                              "game_date DESC, game_id DESC LIMIT 1", (me, me)).fetchone()
        if r is None:
            raise ValueError("No games played yet.")
        return r[0]

    def do_recap(self, arg):
        "recap [game id]: box score and story of a game (your last game by default; ids from `results`)"
        from . import media as M
        r = M.recap(self.conn, self._game_id(arg))
        self.p(f"{r['outlet']}: {r['headline']}")
        self.p(r["lede"])
        self.p(f"  {'':<5}" + "".join(f"{p:>5}" for p in r["periods"]) + "    T  SOG")
        for ab, cells in r["line"].items():
            self.p(f"  {ab:<5}" + "".join(f"{c[0]:>5}" for c in cells)
                   + f"{sum(c[0] for c in cells):>5}{sum(c[1] for c in cells):>5}")
        for gl in r["goals"]:
            ast = ", ".join(a["name"] for a in gl["assists"]) or "unassisted"
            self.p(f"  {gl['period']:<4}{gl['time']:>6}  {gl['team']:<4}{gl['scorer']} ({ast}){' EN' if gl['en'] else ''}"
                   f"  {gl['score']}")
        if r["shootout"]:
            self.p("  Shootout: " + ", ".join(f"{x['team']} {x['shooter']} {'scores' if x['scored'] else 'misses'}"
                                             for x in r["shootout"]))
        self.p("  Stars: " + "; ".join(f"{i + 1}. {s['name']} ({s['line']})" for i, s in enumerate(r["stars"])))

    def do_news(self, arg):
        "news [league] [n]: headlines about your club (or the league)"
        me = self.need()
        from . import media as M
        toks = arg.split()
        n = int(toks.pop()) if toks and toks[-1].isdigit() else 15
        rows = M.headlines(self.conn, None if "league" in toks else me, n)
        for h in rows:
            self.p(f"{h['date']}  [{h['tag']}] {h['headline']}")
        if not rows:
            self.p("No news yet.")

    def do_feed(self, arg):
        "feed [n]: the social feed (insiders, cap and prospect accounts, your fans)"
        self.need()
        from . import media as M
        for p in M.social(self.conn, int(arg) if arg.strip().isdigit() else 15):
            self.p(f"{p['date']}  {p['account']}: {p['text']}")
            for rp in p["replies"]:
                self.p(f"{'':12}  > {rp['account']}: {rp['text']}")

    def do_power(self, arg):
        "power: power rankings (points %, goal differential, last ten; movement over the week)"
        self.need()
        from . import media as M
        for r in M.power_rankings(self.conn):
            mv = f"+{r['move']}" if r["move"] > 0 else str(r["move"]) if r["move"] else "="
            self.p(f"{r['rank']:>3} {mv:>3}  {r['team']:<4}{r['pts']:>4} pts {r['diff']:>+4}  L10 {r['last10']:<7} "
                   f"{r['blurb']}" + ("  <- you" if r["mine"] else ""))

    def do_rules(self, arg):
        "rules [preset nhl|off]: this season's and next season's rules (games, overtime, points); switch the NHL era preset"
        self.need()
        from ..league.eras import describe
        import json as _json
        toks = arg.split()
        if toks[:1] == ["preset"]:
            if len(toks) < 2 or toks[1] not in ("nhl", "off"):
                raise ValueError("Usage: rules preset nhl|off")
            row = self.conn.execute("SELECT value FROM pack_info WHERE key='rules'").fetchone()
            raw = _json.loads(row[0])
            if toks[1] == "off":
                raw.pop("era_preset", None)
            else:
                raw["era_preset"] = "nhl"
            self.conn.execute("UPDATE pack_info SET value=? WHERE key='rules'", (_json.dumps(raw),))
            self.conn.commit()
            self.p("NHL rule eras " + ("on: overtime and points follow the era from the next game, the schedule from next season."
                                       if toks[1] == "nhl" else "off: the pack's own rules apply."))
        base = db_rules(self.conn, base=True)
        year = K.season_year(self.conn)
        me = user_team(self.conn)
        n = self.conn.execute("SELECT COUNT(*) FROM games g JOIN seasons s USING (season_id) WHERE s.start_year=? AND "
                              "g.game_type='RS' AND (home_team_id=? OR away_team_id=?)", (year, me, me)).fetchone()[0]
        now = describe(base, year)
        if n:                                          # the schedule already made is what counts this season
            now = re.sub(r": \d+ games", f": {n} games", now, count=1)
        self.p("This season  " + now)
        self.p("Next season  " + describe(base, year + 1))
        self.p("Era preset: " + (base.get("era_preset") or "none") + (f"; {len(base.get('eras') or [])} custom eras"
                                                                      if base.get("eras") else ""))

    def do_roster(self, arg):
        "roster [forwards|defence|goalies] [system]: NHL roster; add 'system' to include players in the minors"
        me = self.need()
        grp = {"f": "F", "d": "D", "g": "G"}.get((arg.split() or ["all"])[0][:1].lower()) if not arg.startswith("s") else None
        rows = self.conn.execute("SELECT p.*, a.* FROM players p LEFT JOIN player_attributes a USING (player_id) "
                                 "WHERE p.team_id=? AND p.status IN ('active','injured'" + (",'prospect'" if "all" in arg
                                 or "system" in arg else "") + ") ORDER BY p.position, p.last_name", (me,)).fetchall()
        for title, cols, g in (("Forwards", SK_COLS, "F"), ("Defence", SK_COLS, "D"), ("Goalies", G_COLS, "G")):
            if grp and grp != g:
                continue
            self.p(f"\n{title}\n  {'Name':<24}{'Pos':<4}{'Age':>4}" + "".join(f"{c:>5}" for c, _ in cols)
                   + f"{'Val':>6}  Status")
            for r in rows:
                if R.group(r["position"]) != g:
                    continue
                vals = "".join(f"{(r[k] if r[k] is not None else '-')!s:>5}" for _, k in cols)
                self.p(f"  {r['first_name'] + ' ' + r['last_name']:<24}{r['position']:<4}{self.age(r['birth_date']):>4}"
                       f"{vals}{R.player_value(self.conn, r['player_id']):>6.0f}  "
                       f"{ {'injured': 'INJURED', 'prospect': 'minors'}.get(r['status'], '')}")

    def do_player(self, arg):
        "player <name or id>: attributes and season stats"
        self.need()
        r = self.find(arg)
        pl = self.conn.execute("SELECT * FROM players WHERE player_id=?", (r["player_id"],)).fetchone()
        at = self.conn.execute("SELECT * FROM player_attributes WHERE player_id=?", (r["player_id"],)).fetchone()
        ab = self.abbr()
        self.p(f"{pl['first_name']} {pl['last_name']}  #{pl['player_id']}  {pl['position']}  "
               f"age {self.age(pl['birth_date'])}  {ab.get(pl['team_id'], 'FA')}  {pl['status']}  "
               f"value {R.player_value(self.conn, pl['player_id']):.0f}")
        from . import world as Wd
        self.p(f"Playing for: {Wd.where_is(self.conn, pl['player_id'])}")
        if self._has("morale") and pl["team_id"] == user_team(self.conn):
            from . import people
            m = self.conn.execute("SELECT * FROM morale WHERE player_id=?", (pl["player_id"],)).fetchone()
            if m:
                self.p(f"Morale {m['morale']:.0f}: role {m['role']:.0f}, team {m['team']:.0f}, contract {m['contract']:.0f}, "
                       f"trust in you {m['trust_mgmt']:.0f}, trust in coach {m['trust_coach']:.0f}")
        if at:
            self.p("Attributes: " + ", ".join(f"{k}={at[k]}" for k in at.keys()
                                              if k not in ("player_id", "potential") and at[k] is not None))
            dev = self.conn.execute("SELECT potential FROM player_dev WHERE player_id=?", (pl["player_id"],)).fetchone()
            if dev and dev[0] is not None and self.age(pl["birth_date"]) <= 24:
                from . import draft as D
                est = D.perceived(self.conn, user_team(self.conn), pl["player_id"], dev[0], 0)
                self.p(f"Scouts' projection: {self._grade(est, pl['position'] == 'G')} (an estimate; true ceilings are hidden)")
        tbl, cols = (("goalie_season_stats", "gp, gs, w, l, otl, so, ga, sa") if pl["position"] == "G"
                     else ("skater_season_stats", "gp, g, a, pim, plus_minus, sog"))
        rows = self.conn.execute(f"SELECT s.season_start_year, COALESCE(l.abbr, '') lg, {', '.join('s.' + c.strip() for c in cols.split(','))} "
                                 f"FROM {tbl} s LEFT JOIN leagues l USING (league_id) WHERE s.player_id=? AND s.split='RS' "
                                 f"ORDER BY s.season_start_year", (pl["player_id"],)).fetchall()
        if rows:
            self.p("Season  " + "  ".join(rows[0].keys()[1:]))
            for x in rows:
                self.p(f"{x[0]}  " + "  ".join(str(v) for v in tuple(x)[1:]))

    def do_lines(self, arg):
        """lines | lines set F1 <C>, <LW>, <RW> [; D2 <L>, <R>; G <starter>, <backup>; PP1 <5>; PK1 <4>]
        | lines swap <p1> <p2> | lines auto: show or set the lines the engine uses (docs/LINES.md)"""
        me = self.need()
        from . import lineup as L
        a = arg.strip()
        if a.lower().startswith("set "):
            for part in filter(None, (x.strip() for x in a[4:].split(";"))):
                unit, _, who = part.partition(" ")
                pids = [] if who.strip().lower() == "none" else \
                    [self.find(x.strip(), "team_id=?", (me,))["player_id"] for x in who.split(",") if x.strip()]
                L.set_unit(self.conn, me, unit, pids)
            self.conn.commit()
        elif a.lower().startswith("swap "):
            x, y = [t.strip() for t in re.split(r"\s*,\s*|\s+(?=\S+$)", a[5:].strip(), maxsplit=1)]
            L.swap(self.conn, me, self.find(x, "team_id=?", (me,))["player_id"],
                   self.find(y, "team_id=?", (me,))["player_id"])
            self.conn.commit()
        elif a.lower() == "auto":
            L.reset(self.conn, me)
            self.conn.commit()
        elif a:
            raise ValueError("Usage: lines | lines set F1 a, b, c; D1 d, e | lines swap a, b | lines auto")
        for line in L.describe(self.conn, me):
            self.p(line)

    def do_ltir(self, arg):
        "ltir [<player>]: put an injured player on long-term injured reserve (10+ games and 24+ days), or list LTIR"
        me = self.need()
        from . import ltir as LT
        LT.ensure_tables(self.conn)
        if arg.strip():
            r = self.find(arg, "team_id=? AND status='injured'", (me,))
            self.p(LT.place(self.conn, r["player_id"], self.today()))
            self.conn.commit()
            return
        rows = LT.active(self.conn, me)
        for x in rows:
            self.p(f"  {self.conn.execute('SELECT first_name||chr(32)||last_name FROM players WHERE player_id=?', (x['player_id'],)).fetchone()[0]:<24}"
                   f"${x['cap_hit']:>11,.0f}  since {x['placed']}  earliest return {x['earliest']}")
        cap = K.crules(self.conn)["cap_ceiling"]
        self.p(("Nobody on LTIR." if not rows else "") + (f" Ceiling ${LT.ceiling(self.conn, me):,.0f} (cap ${cap:,.0f}); "
                                                         f"payroll ${K.payroll(self.conn, me):,.0f}." if cap else ""))

    def do_activate(self, arg):
        "activate <player>: bring a fit player back from LTIR (you must be cap compliant without his relief)"
        me = self.need()
        from . import ltir as LT
        r = self.find(arg, "team_id=? AND status='ltir'", (me,))
        self.p(LT.activate(self.conn, r["player_id"], self.today()))
        self.conn.commit()

    def do_tactics(self, arg):
        """tactics | tactics <system> | tactics set <setting> <option> | tactics pref <preference> <value>:
        your tactics (docs/TACTICS.md): a preset (balanced, heavy forecheck, puck possession, defensive structure,
        speed and transition), one of the twelve settings, or a preference (pull_down1, pull_down2, goalie_hook,
        line_matching, ice_time)"""
        me = self.need()
        from . import boardroom as BR
        from . import tactics as TC
        a = arg.strip()
        verb, _, rest = a.partition(" ")
        if verb.lower() == "set":
            k, _, v = rest.strip().partition(" ")
            TC.set_setting(self.conn, me, k.strip(), v.strip())
            self.conn.commit()
            self.p(f"{TC.SETTINGS[k.strip()][0]}: {TC.SETTINGS[k.strip()][3][v.strip()][0]}.")
            return
        elif verb.lower() == "pref":
            k, _, v = rest.strip().partition(" ")
            TC.set_pref(self.conn, me, k.strip(), v.strip())
            self.conn.commit()
            self.p(f"{TC.PREFS[k.strip()][0]}: {v.strip()}.")
            return
        elif a:
            TC.set_system(self.conn, me, a.lower())
            self.conn.commit()
        cur = TC.settings_of(self.conn, me)
        o = BR.owner(self.conn, me)
        self.p(f"Closest system: {TC.system_of(self.conn, me)}" + (f"  (the owner wants {o['identity']})" if o and o["identity"] else ""))
        for x in TC.setting_options(self.conn, me):
            opts = "  ".join(f"{'*' if y['option'] == cur[x['key']] else ' '}{y['option']} ({y['value']:+.1f})" for y in x["options"])
            self.p(f"  {x['key']:<14}{opts}")
        pr = TC.prefs_of(self.conn, me)
        self.p("Preferences: " + "; ".join(f"{k} = {v}" for k, v in pr.items()))

    def pname(self, pid):
        from .events import player_name
        return player_name(self.conn, pid)

    def do_goals(self, arg):
        "goals : the owner's goals for the season (priority, deadline, progress) and the catalogue they come from"
        me = self.need()
        from . import owner_goals as OG
        v = OG.view(self.conn, me)
        if not v["goals"]:
            self.p("The owner has set no goals yet (they come with the regular season).")
        for g in v["goals"][:12]:
            self.p(f"  {g['season']}  {g['description']:<52}{g['priority']:<7} by {g['deadline']}  "
                   + (g.get("progress") or "") + ("" if g["status"] == "open" else f"{g['status'].upper()} ({g['result']}) {g['delta']:+.0f}"))

    def do_troles(self, arg):
        """troles | troles suggest | troles clear | troles info | troles <player> <role|none> : tactical roles (agitator,
        shadow, net_front, trigger, forechecker, enforcer, pk_specialist, shutdown, puck_mover, pp_qb, crease_clearer, rover)"""
        me = self.need()
        from . import troles as TR
        c = self.conn
        a = arg.strip()
        low = a.lower()
        if low == "suggest":
            out = TR.suggest(c, me)
            c.commit()
            self.p("Roles: " + (", ".join(f"{self.pname(pid)} {TR.ROLES[r][0]} ({f})" for pid, (r, f) in out.items()) or "nobody clears fit "
                                + str(TR.SUGGEST_FIT)))
            return
        if low == "clear":
            c.execute("DELETE FROM tactical_roles WHERE team_id=?", (me,))
            c.commit()
            self.p("Roles cleared.")
            return
        if low == "info":
            for k in TR.ROLES:
                d = TR.describe(k)
                self.p(f"{k:<15}{d['label']:<20}{'/'.join(d['states'])}: {d['upside']} | cost {d['cost']}" + (f" | {d['extra']}" if d["extra"] else ""))
            return
        if a:
            parts = a.rsplit(" ", 1)
            if len(parts) != 2 or (parts[1].lower() not in TR.ROLES and parts[1].lower() != "none"):
                raise ValueError("Usage: troles <player> <role|none> (troles info lists the roles)")
            r = self.find(parts[0], "team_id=?", (me,))
            f = TR.set_role(c, me, r["player_id"], parts[1].lower())
            c.commit()
            self.p(f"{r['first_name']} {r['last_name']}: " + (f"{TR.ROLES[parts[1].lower()][0]}, fit {f}" if f is not None else "no role"))
            return
        v = TR.view(c, me)
        for x in v["players"]:
            if x["dressed"]:
                self.p(f"  {x['name']:<26}{x['pos']:<3}" + (f"{TR.ROLES[x['role']][0]:<20} fit {x['fit']:>3}" if x["role"] else f"{'-':<20}{'':>7}")
                       + f"   best: {TR.ROLES[x['best']][0]} {x['best_fit']}")

    def do_tend(self, arg):
        "tend <player> shoot first|pass first|attacking|defensive|normal: a player's tendency (kept with your lines)"
        me = self.need()
        from . import lineup as L
        a = arg.strip()
        for v in ("shoot first", "pass first", "attacking", "defensive", "normal"):
            if a.lower().endswith(" " + v):
                r = self.find(a[: -len(v)].strip(), "team_id=?", (me,))
                cur = L.set_tendency(self.conn, me, r["player_id"], v)
                self.conn.commit()
                self.p(f"{r['first_name']} {r['last_name']}: " + (", ".join(cur.values()) if cur else "normal"))
                return
        raise ValueError("Usage: tend <player> shoot first|pass first|attacking|defensive|normal")

    def do_finances(self, arg):
        "finances: this season's revenue, costs, attendance, prices and budgets (docs/FINANCE.md)"
        me = self.need()
        from . import finance as FN
        v = FN.view(self.conn, me)
        m = lambda x: f"${x / 1e6:,.1f}M"
        f = v["profile"]
        self.p(f"Market {f['market']}/10 · arena {f['capacity']:,} seats, quality {f['arena_quality']:.0f} · cash {m(f['cash'])}")
        self.p(f"This season: revenue {m(v['revenue'])}, costs {m(v['costs'])}, {'profit' if v['revenue'] >= v['costs'] else 'loss'} "
               f"{m(abs(v['revenue'] - v['costs']))}; attendance {v['attendance']['avg']:,} a game ({v['attendance']['fill'] * 100:.1f}% full)")
        for k, x in v["prices"].items():
            self.p(f"  {k:<8} ${x['price']:>5,.0f}  (reference ${x['ref']:,.0f}, {x['seats']:,} seats)")
        for k, x in v["budgets"].items():
            self.p(f"  {k:<12} budget {m(x['amount'])} a year (default {m(x['default'])})")
        p = v["projection"]
        self.p(f"Full season at this pace: revenue {m(p['revenue'])}, costs {m(p['costs'])}, result {m(p['profit'])}, {p['fill'] * 100:.0f}% full")

    def do_tickets(self, arg):
        "tickets <lower|upper|premium> <price>: set a ticket price"
        me = self.need()
        from . import finance as FN
        a = arg.split()
        if len(a) != 2:
            raise ValueError("Usage: tickets lower|upper|premium <price>")
        FN.set_price(self.conn, me, a[0].lower(), a[1].replace("$", "").replace(",", ""))
        self.conn.commit()
        self.p(f"{a[0].capitalize()} bowl tickets now ${float(a[1].replace('$', '').replace(',', '')):,.0f}.")

    def do_pnl(self, arg):
        """pnl [fy] [year|ytd|q1..q4|YYYY-MM] [budget|prior|both] [level 1-3] : the profit and loss report (Team > Financial
        statements). pnl journal <account> [fy] [period] : the journal lines behind an account (4110, 5100...)"""
        me = self.need()
        from . import accounts as AC
        a = arg.split()
        m = lambda v: "" if v is None else f"{v / 1e6:,.2f}"
        if a and a[0].lower() == "journal":
            if len(a) < 2:
                raise ValueError("Usage: pnl journal <account> [fy] [period]")
            j = AC.journal(self.conn, me, int(a[2]) if len(a) > 2 else AC.fy_of(self.today()), a[1], a[3] if len(a) > 3 else None)
            self.p(f"{j['code']} {j['name']}, {AC.fy_label(j['fy'])}, {j['period_label']}: {j['count']} lines, total ${m(j['total'])}M")
            for x in j["lines"][-40:]:
                self.p(f"  {x['day']}  {x['account']}  {x['detail'][:44]:<44}{x['amount']:>14,.0f}")
            return
        fy = period = None
        compare, level = "none", 3
        for x in a:
            lx = x.lower()
            if lx.isdigit() and len(lx) == 4:
                fy = int(lx)
            elif lx in ("year", "ytd", "q1", "q2", "q3", "q4") or (len(lx) == 7 and lx[4] == "-"):
                period = lx
            elif lx in ("budget", "prior", "both"):
                compare = lx
            elif lx in ("1", "2", "3"):
                level = int(lx)
        r = AC.pnl(self.conn, me, fy, period, "total", compare, level)
        self.p(f"Profit and loss, {r['fy_label']}, {r['period_label']} ($M)")
        heads = [c["label"] for c in r["columns"]]
        self.p(f"{'':<42}" + "".join(f"{h[:12]:>13}" for h in heads))
        for row in r["rows"]:
            name = ("  " * (row["level"] - 1)) + (row["code"] + " " if row["code"] and row["kind"] != "subtotal" else "") + row["name"]
            vals = "".join(f"{(m(v) if c['kind'] != 'pct' else ('' if v is None else f'{v:.1f}%')):>13}" for v, c in zip(row["vals"], r["columns"]))
            self.p((f"{name[:42]:<42}" + vals) if row["kind"] != "subtotal" else f"{'= ' + name:<42}" + vals)
        if r["budget"]:
            self.p(f"Budget ({r['budget']['status']}, {r['budget']['built']}): {r['budget']['note']}")

    def do_boardpack(self, arg):
        "boardpack : the board's finance view: the year to date against the budget, the forecast, the owner's reports"
        me = self.need()
        from . import accounts as AC
        b = AC.board_pack(self.conn, me)
        m = lambda v: f"{'-' if v < 0 else ''}${abs(v) / 1e6:,.1f}M"
        self.p(f"Board pack, {b['fy_label']} to {b['today']} · owner {b['owner']['name']} watches {b['owner']['watches']}")
        for lab, k in (("Revenue", "revenue"), ("Hockey operations", "hockey"), ("Operating expenses", "opex"), ("EBITDA", "ebitda"), ("Net profit", "net")):
            x = b["kpis"][k]
            self.p(f"  {lab:<20} actual {m(x['actual']):>9}  budget {m(x['budget']):>9}  variance {m(x['var']):>9}  forecast {m(x['forecast']):>9}  (full-year budget {m(x['full_budget'])})")
        self.p(f"  Cash {m(b['cash'])} · players {b['payroll_share']}% of forecast revenue · revenue {b['rank_revenue']} of {b['clubs']}, "
               f"net profit {b['rank_net']} of {b['clubs']}" + (f" · next review {b['next_review']}" if b["next_review"] else ""))
        for r in b["reports"][:4]:
            self.p(f"  {r['day']}  Q{r['quarter']} {r['fy_label']}: \"{r['comment']}\"" + (f" ({r['delta']:+.0f} confidence)" if r["delta"] else ""))

    def do_budget(self, arg):
        "budget <scouting|development|marketing> <$M a year>: set a budget"
        me = self.need()
        from . import finance as FN
        a = arg.split()
        if len(a) != 2:
            raise ValueError("Usage: budget scouting|development|marketing <millions a year>")
        FN.set_budget(self.conn, me, a[0].lower(), float(a[1].rstrip("mM")) * 1e6)
        self.conn.commit()
        self.p(f"The {a[0].lower()} budget is now ${float(a[1].rstrip('mM')):.2f}M a year.")

    def do_arena(self, arg):
        """arena improve <points> | arena expand <seats> | arena quote <seats> <quality> | arena new <seats> <quality> |
        arena status : renovations, new seats (offseason; from the club's cash) or a new arena (owner and loan; docs/FINANCE.md)"""
        me = self.need()
        from . import finance as FN
        a = arg.split()
        if a and a[0] in ("quote", "new", "status"):
            from . import arena as AR
            if a[0] == "status":
                v = AR.view(self.conn, me)
                p, ln = v["project"], v["loan"]
                self.p(("No new arena." if not p else f"New arena: {p['capacity']:,} seats, quality {p['quality']:.0f}, ${p['cost'] / 1e6:,.0f}M, "
                        f"{p['status']}, opens {p['opens_season']} ({p['months_paid']} of {AR.BUILD_MONTHS} months paid)")
                       + (f"; loan ${ln['balance'] / 1e6:,.1f}M at {ln['rate'] * 100:.0f}%, ${ln['payment'] / 1e6:,.2f}M a month" if ln else "")
                       + (f"; novelty +{v['novelty'] * 100:.1f}% demand" if v["novelty"] else ""))
                return
            if len(a) != 3:
                raise ValueError("Usage: arena quote|new <seats> <quality>")
            q = AR.quote(self.conn, me, a[1].replace(",", ""), a[2]) if a[0] == "quote" else AR.propose(self.conn, me, a[1].replace(",", ""), a[2], self.today())
            self.conn.commit()
            self.p(f"{'Approved' if a[0] == 'new' else 'Quote'}: {q['capacity']:,} seats, quality {q['quality']:.0f}, ${q['cost'] / 1e6:,.0f}M; "
                   f"the owner ${q['owner_share'] / 1e6:,.0f}M ({q['owner_pct']}%), a loan of ${q['loan'] / 1e6:,.0f}M (${q['yearly'] / 1e6:,.1f}M a year); "
                   f"opens {q['opens']}" + ("" if q["ok"] else f". The owner says no: {q['why']}"))
            return
        if len(a) != 2 or a[0] not in ("improve", "expand"):
            raise ValueError("Usage: arena improve <points> | arena expand <seats> | arena quote|new <seats> <quality> | arena status")
        cost = (FN.improve_arena if a[0] == "improve" else FN.expand_arena)(self.conn, me, int(a[1]), self.today())
        self.conn.commit()
        self.p(f"Done: ${cost / 1e6:.1f}M from the club's cash.")

    def do_playhurt(self, arg):
        "playhurt <player>: let an injured player (three weeks or less to go) play through it"
        me = self.need()
        from . import welfare as W
        r = self.find(arg, "team_id=?", (me,))
        left = W.play_hurt(self.conn, me, r["player_id"], self.today())
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} will play hurt ({left} days until he would have been back). "
               "He is below his best, and each game he might make it worse.")

    def do_rest(self, arg):
        "rest <player>: stop a player playing hurt; he sits until he is healed"
        me = self.need()
        from . import welfare as W
        r = self.find(arg, "team_id=?", (me,))
        W.rest(self.conn, me, r["player_id"], self.today())
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} sits until he is healed.")

    def do_terminate(self, arg):
        "terminate <player>: ask a player to tear up his contract by mutual agreement (a settlement, no cap charge)"
        me = self.need()
        from . import welfare as W
        r = self.find(arg, "team_id=?", (me,))
        ok, pay, why = W.terminate(self.conn, me, r["player_id"], self.today())
        self.conn.commit()
        if ok:
            self.p(f"Agreed: {r['first_name']} {r['last_name']} is a free agent. Settlement ${pay:,.0f} ({why}).")
        else:
            self.p(f"{r['first_name']} {r['last_name']} said no: {why}")

    def do_scout(self, arg):
        """scout | scout assign <staff id> <chl|usa|nordic|europe|russia|all> | scout trip <staff id> <event> |
        scout watch <player> | scout unwatch <player>: your scouting network (docs/SCOUTING.md)"""
        me = self.need()
        from . import scout_net as SN
        a = arg.split()
        if not a:
            v = SN.network_view(self.conn)
            for s in v["scouts"]:
                self.p(f"  #{s['staff_id']:<5}{s['name']:<24}evaluation {s['evaluation']:>2}  region {s['region']}")
            for r, c in v["coverage"].items():
                self.p(f"  {SN.REGIONS[r]:<24}" + "  ".join(f"{k}:{n}" for k, n in c.items()))
            for e in v["events"]:
                self.p(f"  {e['key']:<9}{e['name']:<30}{e['start']} to {e['end']}" + ("  (sending someone)" if e["going"] else ""))
            return
        if a[0] == "assign" and len(a) == 3:
            SN.assign(self.conn, int(a[1]), a[2].lower())
            self.p(f"Scout #{a[1]}: {SN.REGIONS.get(a[2].lower(), 'all regions')}.")
        elif a[0] == "trip" and len(a) == 3:
            name, st, en = SN.send(self.conn, int(a[1]), a[2].lower(), self.today())
            self.p(f"Scout #{a[1]} goes to the {name} ({st} to {en}).")
        elif a[0] in ("watch", "unwatch") and len(a) >= 2:
            r = self.find(" ".join(a[1:]))
            SN.watch(self.conn, r["player_id"], self.today(), a[0] == "watch")
            self.p(f"{r['first_name']} {r['last_name']} is {'on' if a[0] == 'watch' else 'off'} your watch list.")
        else:
            raise ValueError("Usage: scout | scout assign <id> <region> | scout trip <id> <event> | scout watch|unwatch <player>")
        self.conn.commit()

    def do_train(self, arg):
        "train <player> <balanced|offence|defence|skating|physical|mental|positioning|reflexes>: a player's training focus"
        me = self.need()
        from . import training as TR
        a = arg.strip().rsplit(" ", 1)
        if len(a) != 2:
            raise ValueError("Usage: train <player> <focus>")
        r = self.find(a[0], "team_id=?", (me,))
        TR.set_focus(self.conn, me, r["player_id"], a[1].lower())
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} trains: {a[1].lower()}.")

    def do_events(self, arg):
        """events | events set <preseason_games 0-10|allstar conference|draft|world|off|prospects on|off|hof committee|auto>:
        the calendar's options and dates (docs/CALENDAR.md)"""
        self.need(allow_fired=True)
        from . import exhibitions as EX
        a = arg.split()
        if a and a[0] == "set" and len(a) == 3:
            EX.set_option(self.conn, a[1], a[2].lower())
            self.conn.commit()
        elif a:
            raise ValueError("Usage: events | events set <option> <value>")
        for k, v in EX.options(self.conn).items():
            self.p(f"  {k:<16}{v}")
        today = self.today()
        for d, label in sorted(EX.league_dates(self.conn)):
            if d >= today:
                self.p(f"  {d}  {label}")

    def do_rivals(self, arg):
        "rivals [<team>]: a club's rivalries (docs/CALENDAR.md)"
        me = self.need(allow_fired=True)
        from . import rivalry as RV
        t = me
        if arg.strip():
            r = self.conn.execute("SELECT team_id FROM teams WHERE abbr=?", (arg.strip().upper(),)).fetchone()
            if not r:
                raise ValueError(f"No team {arg.strip()}.")
            t = r[0]
        if t is None:
            raise ValueError("Usage: rivals <TEAM>")
        v = RV.view(self.conn, t)
        if v["main"]:
            self.p(f"Main rival: {v['main']['abbr']} ({v['main']['level']}, {v['main']['points']:.0f})")
        for x in v["rivals"]:
            h = x["h2h"]
            self.p(f"  {x['abbr']:<5}{x['points']:>5.0f}  {x['level']:<10}{'warming ' if x['warming'] else '        '}"
                   f"{h['w']}-{h['l']}-{h['otl']}, {h['series']} playoff series")

    def do_hof(self, arg):
        "hof | hof vote <player> [, <player> ...] | hof cls [<player>]: the Hall of Fame, this year's ballot (back up to four) and Career Legacy Scores"
        self.need(allow_fired=True)
        from . import legacy as LG
        a = arg.strip()
        if a.startswith("vote"):
            names = [x.strip() for x in a[4:].split(",") if x.strip()]
            if not names:
                raise ValueError("Usage: hof vote <player>, <player> ...")
            pids = [self.find(n)["player_id"] for n in names]
            LG.vote(self.conn, pids)
            self.conn.commit()
            self.p("Your Hall of Fame vote: " + ", ".join(names) + ".")
            return
        if a.startswith("cls") or a.startswith("legacy"):
            rest = a.split(None, 1)[1] if len(a.split(None, 1)) > 1 else ""
            if rest:
                s = LG.legacy_view(self.conn, self.find(rest)["player_id"])
                self.p(f"{s['name']}: CLS {s['cls']:.1f} {s['tier'] or ''} (PVL {s['pvl']:.1f}: peak {s['peak']:.2f} x10 + longevity "
                       f"{s['longevity']:.2f} x3; hardware {s['hardware']:.1f})")
                self.p("  best seasons: " + ", ".join(f"{b['season']}: {b['sv']:.2f}" for b in s["best"]))
                for it in s["items"]:
                    self.p(f"  +{it['pts']:g}  {it['label']}")
            else:
                for r in LG.legacy_view(self.conn)["rows"][:25]:
                    self.p(f"  {r['name']:<26}{r['group']}  CLS {r['cls']:>6.1f}  {r['tier']}")
            return
        v = LG.hof_view(self.conn)
        if v["ballot"]:
            self.p(f"Ballot {v['ballot_year']} ({'open' if v['open'] else 'decided'}; the best {v['max']} by Career Legacy Score go in):")
            for b in v["ballot"]:
                mark = "*" if b["my_vote"] else " "
                res = "" if b["inducted"] is None else ("  INDUCTED" if b["inducted"] else "")
                self.p(f" {mark}{b['name']:<26}CLS {b['score']:>6.1f}  {b['tier']:<18} year {b['ballot_years'] or 1}{res}")
        self.p(f"Hall of Fame: {len(v['members'])} members.")
        for m in v["members"][:20]:
            self.p(f"  {m['year']}  {m['name']:<26}{(m['tier'] or ''):<18}{m['line']}")

    def do_allstar(self, arg):
        "allstar: all-star weekend (the date, the projected rosters or the result)"
        self.need(allow_fired=True)
        from . import exhibitions as EX
        v = EX.allstar_view(self.conn)
        if v["game"]:
            g = v["game"]
            self.p(f"{g['names'][0]} {g['score'][0]} - {g['score'][1]} {g['names'][1]}{' ' + g['ot'] if g['ot'] else ''}; MVP {v['mvp']['name']}")
            for k, x in (v["skills"] or {}).items():
                self.p(f"  {x['name']:<20}{x['results'][0]['name']} ({x['best']} {x['unit']})")
        else:
            self.p(f"All-star weekend: {v['date'] or 'none this season'} ({v['format']}).")
            for side, pl in zip((v.get("projected") or {}).get("sides", []), (v.get("projected") or {}).get("players", [])):
                self.p(f"  {side}: " + ", ".join(f"{p['name']} ({p['club']})" for p in pl))

    def do_gmleaders(self, arg):
        "gmleaders: the GM score table (every GM's seasons, record, playoffs, championships)"
        self.need(allow_fired=True)
        from . import legacy as LG
        for d in LG.gm_leaders(self.conn)["leaders"][:30]:
            self.p(f"  {d['rank']:>3} {d['name'] + (' (you)' if d['you'] else ''):<28}{d['score']:>7.1f}  {d['seasons']} seasons  "
                   f"{d['w']}-{d['l']}-{d['otl']}  {d['playoffs']} playoffs  {d['cups']} titles  {'/'.join(d['clubs'])}")

    def do_achievements(self, arg):
        "achievements: your career milestones"
        self.need(allow_fired=True)
        from . import legacy as LG
        v = LG.achievements_view(self.conn)
        self.p(f"{v['earned']} of {v['total']} achievements; GM score {v['gm']['score']}" + (f" (rank {v['gm']['rank']} of {v['gm']['of']})" if v['gm']['rank'] else ""))
        for x in v["achievements"]:
            self.p(f"  [{'x' if x['day'] else ' '}] {x['name']:<24}{x['desc']}" + (f"  ({x['day']})" if x["day"] else ""))

    def do_waivers(self, arg):
        "waivers [<player>]: the waiver wire (claim order: worst record first), or a player's waiver status"
        me = self.need()
        from . import waivers as W
        if arg.strip():
            r = self.find(arg.strip())
            self.p(f"{r['first_name']} {r['last_name']}: {W.status(self.conn, r['player_id'])['why']}"
                   + (" (in the waiver period)" if W.in_period(self.conn) else " (outside the waiver period)"))
            return
        rows = W.on_wire(self.conn)
        mine = {x[0] for x in self.conn.execute("SELECT player_id FROM waiver_claims WHERE team_id=?", (me,))}
        for w in rows:
            p = self.conn.execute("SELECT first_name||' '||last_name n, position FROM players WHERE player_id=?",
                                  (w["player_id"],)).fetchone()
            order = W.claim_order(self.conn, w["team_id"])
            c = K.current_contract(self.conn, w["player_id"])
            self.p(f"  {p['n']:<24}{p['position']:<4}{team_abbr_of(self, w['team_id']):<5}"
                   f"{('$%.2fM' % (c['cap_hit'] / 1e6)) if c else '-':>8}  clears {w['clears']}  your priority "
                   f"{order.index(me) + 1 if me in order else '-'}/{len(order)}"
                   + ("  CLAIM PUT IN" if w["player_id"] in mine else ""))
        if not rows:
            self.p("Nobody on waivers.")

    def do_claim(self, arg):
        "claim <player> | claim remove <player>: put in (or withdraw) a waiver claim"
        self.need()
        from . import waivers as W
        a = arg.strip()
        off = a.lower().startswith("remove ")
        r = self.find(a[7:] if off else a, "status='waivers'")
        W.user_claim(self.conn, r["player_id"], not off)
        self.conn.commit()
        self.p(("Claim withdrawn for " if off else "Claim in for ") + f"{r['first_name']} {r['last_name']}"
               + ("" if off else "; it is decided when he clears (worst record has priority)."))

    def do_injuries(self, arg):
        "injuries: your injured players"
        me = self.need()
        rows = self.conn.execute(
            "SELECT p.first_name||' '||p.last_name n, p.position, i.expected_return FROM players p "
            "JOIN injuries i USING (player_id) WHERE p.team_id=? AND p.status='injured' AND "
            "i.injury_id=(SELECT MAX(injury_id) FROM injuries WHERE player_id=p.player_id) "
            "ORDER BY i.expected_return", (me,)).fetchall()
        for r in rows:
            self.p(f"  {r['n']:<24}{r['position']:<4} back {r['expected_return']}")
        if not rows:
            self.p("No injuries.")

    def do_fa(self, arg):
        "fa [C|LW|RW|D|G]: best free agents by value"
        self.need()
        pos = arg.strip().upper()
        shown = 0
        for v, pid, p in R.free_agents(self.conn):
            if pos and p != pos:
                continue
            r = self.conn.execute("SELECT first_name, last_name, birth_date FROM players WHERE player_id=?",
                                  (pid,)).fetchone()
            ask = K.asking(self.conn, pid, "UFA")
            self.p(f"  #{pid:<8}{r['first_name'] + ' ' + r['last_name']:<24}{p:<4}age {self.age(r['birth_date']):<3} "
                   f"value {v:.0f}   asks ${ask:,.0f}")
            shown += 1
            if shown >= 20:
                break
        if not shown:
            self.p("No free agents.")

    @staticmethod
    def money(tok):
        t = tok.lower().replace("$", "").replace(",", "")
        mult = 1_000_000 if t.endswith("m") else 1_000 if t.endswith("k") else 1
        return int(float(t.rstrip("mk")) * mult)

    def split_terms(self, arg):
        """'<player> [aav] [years]' -> (player text, aav or None, years or None). AAV like 2.5m, 900k or 2500000."""
        toks = arg.split()
        aav = years = None
        if len(toks) >= 2 and re.fullmatch(r"\d{1,2}", toks[-1]) and re.fullmatch(r"[\d.,$]+[mMkK]?", toks[-2]):
            years, aav, toks = int(toks[-1]), self.money(toks[-2]), toks[:-2]
        elif toks and re.fullmatch(r"\$?[\d.,]+[mMkK]", toks[-1]) or (toks and re.fullmatch(r"\d{6,}", toks[-1])):
            aav, toks = self.money(toks[-1]), toks[:-1]
        return " ".join(toks), aav, years

    def do_sign(self, arg):
        "sign <player> [aav] [years]: sign a free agent (aav like 2.5m); without terms he signs at his asking price"
        me = self.need()
        who, aav, years = self.split_terms(arg)
        r = self.find(who, "team_id IS NULL")
        R.sign_free_agent(self.conn, me, r["player_id"], self.today(), aav=aav, years=years)
        self.conn.commit()
        c = K.last_contract(self.conn, r["player_id"])
        self.p(f"Signed {r['first_name']} {r['last_name']}: {c['years']} yr x ${c['cap_hit']:,.0f}.")

    def do_release(self, arg):
        "release <player>: release a player (a remaining contract is bought out: 1/3 or 2/3 over twice the term)"
        me = self.need()
        r = self.find(arg, "team_id=?", (me,))
        why = K.buyout_check(self.conn, r["player_id"], self.today())
        if why:
            raise ValueError(why)
        cost = R.release(self.conn, me, r["player_id"], self.today())
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} " + (f"cleared unconditional waivers and was bought out: ${cost:,.0f} in all, "
               "spread over twice the years left (Contracts and Cap shows the charges)." if cost else "released."))

    def do_senddown(self, arg):
        "senddown <player>: assign a player to the minors (stays in your system)"
        me = self.need()
        r = self.find(arg, "team_id=? AND status='active'", (me,))
        out = R.send_down(self.conn, me, r["player_id"], self.today())
        self.conn.commit()
        if out == "waivers":
            from . import waivers as W
            self.p(f"{r['first_name']} {r['last_name']} is not exempt ({W.status(self.conn, r['player_id'])['why']}): "
                   "placed on waivers. Unless claimed he goes to the minors tomorrow.")
        else:
            self.p(f"{r['first_name']} {r['last_name']} assigned to the minors.")

    def do_recall(self, arg):
        "recall <player>: call a player up from the minors"
        me = self.need()
        r = self.find(arg, "team_id=? AND status='prospect'", (me,))
        R.call_up(self.conn, me, r["player_id"], self.today())
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} recalled.")

    def do_cap(self, arg):
        "cap [next]: payroll, cap room and the biggest cap hits (this season, or next season with 'next')"
        me = self.need()
        year = K.season_year(self.conn) + (1 if "next" in arg else 0)
        if "next" not in arg:
            year = K.signing_year(self.conn) if season_state(self.conn) != "regular_season" else year
        total, lines = K.payroll(self.conn, me, year, detail=True)
        cr = K.crules(self.conn)
        self.p(f"{year}-{(year + 1) % 100:02d} payroll ${total:,.0f}" + (
            f" / cap ${cr['cap_ceiling']:,.0f} (room ${cr['cap_ceiling'] - total:,.0f}, floor ${cr['cap_floor']:,.0f})"
            if cr["cap_ceiling"] else " (no salary cap)"))
        for kind, pid, amt in sorted(lines, key=lambda x: -x[2])[:12]:
            n = self.conn.execute("SELECT first_name||' '||last_name n FROM players WHERE player_id=?", (pid,)).fetchone()
            self.p(f"  {n['n'] if n else pid:<26}{kind:<10}${amt:>12,.0f}")

    def do_value(self, arg):
        """value <player> [aav years]: what his contract (or a proposed one) is worth: year-by-year projection,
        market value, surplus, grade and the chance it turns out positive"""
        self.need(allow_fired=True)
        from . import valuation as V
        a = arg.split()
        if not a:
            raise ValueError("Usage: value <player> [aav years]")
        terms = None
        if len(a) >= 3:
            try:
                terms = (self._money(a[-2]), int(a[-1]))
                a = a[:-2]
            except ValueError:
                terms = None
        r = self.find(" ".join(a))
        pid = r["player_id"]
        if terms:
            ev = V.evaluate(self.conn, pid, terms[0], terms[1], K.signing_year(self.conn))
            head = f"Proposed {terms[1]} yr x ${terms[0]:,.0f}"
        else:
            ev = V.evaluate_contract(self.conn, pid)
            if ev is None:
                raise ValueError("He has no contract; try `value <player> <aav> <years>`.")
            c = ev["contract"]
            head = f"{ev['years_left']} yr left x ${c['cap_hit']:,.0f}"
        m = V.market(self.conn)
        self.p(f"{r['first_name']} {r['last_name']}: {head}   (cost of a win ${m.cost_per_win / 1e6:.2f}M)")
        self.p(f"  {'Season':<9}{'Age':>4}{'Proj':>7}{'WAR':>6}{'Worth':>12}")
        for season, age, ov, w, v in ev["rows"]:
            self.p(f"  {season}-{str(season + 1)[2:]:<4}{age:>4}{ov:>7.2f}{w:>6.2f}{v:>12,.0f}")
        self.p(f"  Worth ${ev['value']:,.0f}, costs ${ev['cost']:,.0f}: surplus ${ev['surplus']:+,.0f} -> "
               f"{ev['grade']} ({ev['words']}); {ev['p_positive']:.0%} chance it ends up positive")

    @staticmethod
    def _money(s):
        s = s.lower().replace("$", "").replace(",", "")
        mult = 1_000_000 if s.endswith("m") else 1_000 if s.endswith("k") else 1
        x = float(s.rstrip("mk"))
        return int(x * (1_000_000 if mult == 1 and x < 100 else mult))

    def do_regret(self, arg):
        """regret [mine] [n]: the league's (or your) contracts clubs would most like back: regret index
        (cap hit / this season's worth x seasons left x age friction), surplus, and whether anyone would take it"""
        me = self.need(allow_fired=True)
        from . import regret as RG
        a = arg.split()
        n = int(next((x for x in a if x.isdigit()), 15))
        rows = RG.worst(self.conn, n, me if "mine" in a else None)
        if not rows:
            self.p("No contracts to show.")
            return
        self.p(f"  {'Player':<24}{'Club':<5}{'Cap hit':>12}{'Left':>5}{'Index':>7}{'Surplus':>11}{'Regret':>11}  Status")
        for r in rows:
            nm = self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?",
                                   (r["player_id"],)).fetchone()[0]
            ab = self.conn.execute("SELECT abbr FROM teams WHERE team_id=?", (r["team_id"],)).fetchone()[0]
            reg = "-" if r["regret"] is None else f"{r['regret'] / 1e6:+.1f}M"
            flag = "untradeable without a sweetener" if r["untradeable"] else r["phase"]
            self.p(f"  {nm[:23]:<24}{ab:<5}{r['cap_hit']:>12,.0f}{r['years_left']:>5}{r['index']:>7.1f}"
                   f"{r['surplus'] / 1e6:>+10.1f}M{reg:>11}  {r['grade']} {flag}")

    def do_offersheet(self, arg):
        """offersheet <player> <aav> <years>: sign another club's restricted free agent to an offer sheet (free agency
        phase). They may match; if not, he is yours and they get the CBA compensation picks from you."""
        me = self.need()
        from . import offer_sheets as OS
        a = arg.split()
        if len(a) < 3:
            raise ValueError("Usage: offersheet <player> <aav> <years>")
        aav, years = self._money(a[-2]), int(a[-1])
        r = self.find(" ".join(a[:-2]))
        rounds = OS.compensation(self.conn, aav, years)
        self.p(f"Compensation at that AAV: {OS.describe(rounds)}.")
        self.p(OS.make(self.conn, me, r["player_id"], aav, years, self.today()))
        self.conn.commit()

    def do_match(self, arg):
        "match <player>: match an offer sheet another club gave one of your RFAs"
        me = self.need()
        from . import offer_sheets as OS
        r = self.find(arg)
        self.p(OS.match(self.conn, me, r["player_id"], self.today()))
        self.conn.commit()

    def do_sheets(self, arg):
        "sheets: this summer's offer sheets, and the compensation table"
        self.need(allow_fired=True)
        from . import offer_sheets as OS
        rows = OS.sheets(self.conn)
        for s in rows:
            ab = lambda t: self.conn.execute("SELECT abbr FROM teams WHERE team_id=?", (t,)).fetchone()[0]
            nm = self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?",
                                   (s["player_id"],)).fetchone()[0]
            self.p(f"  {ab(s['from_team'])} -> {nm} ({ab(s['owner_team'])}): {s['years']} yr x ${s['aav']:,.0f}, "
                   f"{OS.describe(__import__('json').loads(s['comp']))}: {s['status']} {s['note'] or ''}")
        if not rows:
            self.p("No offer sheets this summer.")
        self.p("Compensation (AAV = total / min(years, 5)):")
        prev = 0
        for lim, rounds in OS.comp_table(self.conn):
            self.p(f"  {'over $' + format(prev, ',') if lim is None else f'up to ${lim:,}':<22}{OS.describe(rounds)}")
            prev = lim or prev

    def do_ufas(self, arg):
        "ufas [n]: players about to become unrestricted free agents (rights phase), with what they will ask at noon"
        self.need()
        from . import free_agency as FA
        rows = FA.upcoming(self.conn)
        if not rows:
            self.p("No upcoming unrestricted free agents (this list is for the rights phase, before 1 July).")
            return
        n = int(arg) if arg.strip().isdigit() else 40
        self.p(f"  {'id':<9}{'Name':<24}{'Pos':<4}{'Age':>4} {'Tier':>4}  {'Club':<5}{'Wants':>16}{'Fair':>14}")
        for x in rows[:n]:
            nm = self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?",
                                   (x["pid"],)).fetchone()[0]
            ab = self.conn.execute("SELECT abbr FROM teams WHERE team_id=?", (x["team_id"],)).fetchone()[0]
            self.p(f"  {x['pid']:<9}{nm[:23]:<24}{x['pos']:<4}{x['age']:>4} {x['tier']:>4}  {ab:<5}"
                   f"{x['years']:>3} yr x ${x['peak_ask'] / 1e6:>5.2f}M   ${x['fair'] / 1e6:>5.2f}M")
        self.p("Register an offer with `offer <player> <aav> <years>`; offers are heard at noon on 1 July.")

    def do_offer(self, arg):
        "offer <player> <aav> <years>: an offer to an upcoming free agent, heard when the market opens"
        me = self.need()
        from . import free_agency as FA
        a = arg.split()
        if len(a) < 3:
            raise ValueError("Usage: offer <player> <aav> <years>")
        aav, years = self._money(a[-2]), int(a[-1])
        r = self.find(" ".join(a[:-2]))
        self.p(FA.register_offer(self.conn, me, r["player_id"], aav, years, self.today()))
        self.conn.commit()

    def do_withdraw(self, arg):
        "withdraw <player>: take back your free-agent offer"
        me = self.need()
        r = self.find(arg.strip())
        self.conn.execute("DELETE FROM fa_offers WHERE player_id=? AND team_id=?", (r["player_id"], me))
        self.conn.commit()
        self.p("Offer withdrawn.")

    def do_faround(self, arg):
        "faround [all]: free agency's next round (the war room), or every round left"
        self.need()
        from . import free_agency as FA
        if FA.live_state(self.conn) is None or K.season_state(self.conn) != "free_agency":
            raise ValueError("The free-agency auction is not open.")
        if arg.strip() == "all":
            for line in O.finish_live_auction(self.conn):
                self.p(line)
            self.conn.commit()
            return
        rep = FA.live_step(self.conn)
        if rep is None:
            for line in O.finish_live_auction(self.conn):
                self.p(line)
        else:
            self.p(f"{rep['clock']}: {len(rep['signed'])} signed. " + "; ".join(f"{x['team']} {x['name']} {x['years']}x${x['aav'] / 1e6:.2f}M" for x in rep["signed"][:8]))
        self.conn.commit()

    def do_contracts(self, arg):
        "contracts: every contract in your system (cap hit, years left, expiry status)"
        me = self.need()
        year = K.season_year(self.conn)
        rows = self.conn.execute("SELECT player_id, first_name||' '||last_name n, position, status FROM players "
                                 "WHERE team_id=? ORDER BY position, last_name", (me,)).fetchall()
        self.p(f"  {'Name':<24}{'Pos':<4}{'Cap hit':>12}{'Ends':>7}  Status")
        for r in rows:
            c = K.current_contract(self.conn, r["player_id"], year) or K.last_contract(self.conn, r["player_id"])
            if c is None:
                self.p(f"  {r['n']:<24}{r['position']:<4}{'none':>12}")
                continue
            end = c["start_year"] + c["years"] - 1
            tag = K.rights_status(self.conn, r["player_id"], end) if end == year else ""
            self.p(f"  {r['n']:<24}{r['position']:<4}{c['cap_hit']:>12,.0f}{end + 1:>7}  "
                   f"{'minors ' if r['status'] == 'prospect' else ''}{tag}")

    def do_offseason(self, arg):
        "offseason: move to the next offseason phase (rights > free agency > arbitration > awards > preseason > new season)"
        self.need(allow_fired=True)
        for line in O.advance(self.conn, self.env, self.skill):
            self.p(line)
        self.p(f"Phase: {season_state(self.conn)}   Date: {self.today()}")

    def do_rights(self, arg):
        "rights: your expiring contracts this offseason (RFA/UFA, qualifying offer, asking price, outcome)"
        me = self.need()
        rows = O.rights_rows(self.conn, me)
        if not rows:
            self.p("No expiring contracts listed yet (they appear in the rights phase).")
            return
        self.p(f"  {'Name':<24}{'Sts':<5}{'Prev':>12}{'QO':>12}{'Asks':>12}  Arb  Decision")
        for r in rows:
            ask = K.asking(self.conn, r["player_id"], r["status"])
            dec = r["outcome"] or ({1: "qualified", 0: "not qualified"}.get(r["qualified"], "undecided")
                                   if r["status"] == "RFA" else "undecided")
            if r["award"]:
                dec = f"award {r['award_years']} yr x ${r['award']:,.0f}" + (f" ({r['outcome']})" if r["outcome"] else "")
            elif r["arb_elected_by"] and not r["outcome"]:
                dec = f"{r['arb_elected_by']}-elected: ask ${r['player_ask']:,.0f} / offer ${r['team_offer']:,.0f}"
            n = self.conn.execute("SELECT first_name||' '||last_name n FROM players WHERE player_id=?",
                                  (r["player_id"],)).fetchone()["n"]
            self.p(f"  {n:<24}{r['status']:<5}{r['prev_aav']:>12,.0f}{(r['qo'] or 0):>12,.0f}{ask:>12,.0f}  "
                   f"{'yes' if r['arb_eligible'] else 'no ':<4} {dec}")

    def do_qualify(self, arg):
        "qualify <player>: tender a qualifying offer to your RFA (rights phase)"
        self.need()
        r = self.find(arg, "team_id=?", (user_team(self.conn),))
        qo = O.qualify(self.conn, r["player_id"], True)
        self.p(f"Qualifying offer of ${qo:,.0f} tendered to {r['first_name']} {r['last_name']}.")

    def do_extend(self, arg):
        "extend <player> <aav> [years]: re-sign an expiring player (or settle an arbitration case)"
        me = self.need()
        who, aav, years = self.split_terms(arg)
        if aav is None:
            raise ValueError("Usage: extend <player> <aav> [years], e.g. extend Smith 3.2m 4")
        r = self.find(who, "team_id=?", (me,))
        O.extend(self.conn, r["player_id"], aav, years or 1, self.today())
        self.p(f"{r['first_name']} {r['last_name']} re-signed: {years or 1} yr x ${aav:,.0f}.")

    def do_negotiate(self, arg):
        "negotiate <player>: open contract talks with an expiring player of yours or a free agent (his agent answers)"
        self.need()
        from . import negotiation as N
        r = self.find(arg.strip(), "(team_id=? OR team_id IS NULL)", (user_team(self.conn),))
        v = N.open_talks(self.conn, r["player_id"])
        self.conn.commit()
        self._talks(v)

    def _talks(self, v):
        ag = v["agent"]
        self.p(f"{v['name']} ({v['position']}, {v['age']}): agent {ag['name']}, {ag['agency']} ({ag['style_label']})")
        if v.get("open"):
            self.p(f"  patience {v['patience']}/{v['max_patience']}  mood {v['mood']}  wants: "
                   + ", ".join(w["text"] for w in v.get("wants", [])))
            self.p("  asks: " + ", ".join(f"{y}y ${a:,.0f}" for y, a in v["asks"].items()))
        for e in v.get("log", [])[-4:]:
            self.p(f"  [{e['who']}] {e['text']}")
        if v.get("open"):
            self.p(f"  `propose {v['player_id']} <aav> <years> [ntc]` to answer, `endtalks {v['player_id']}` to stop")

    def do_propose(self, arg):
        "propose <player> <aav> <years> [flat|front|bonus] [ntc|nmc|mntc|mntc_late]: your offer in contract talks"
        self.need()
        from . import negotiation as N
        st_ = re.search(r"\s(flat|front|bonus)\b", arg, re.I)
        structure = st_.group(1).lower() if st_ else "flat"
        arg = re.sub(r"\s(flat|front|bonus)\b", "", arg, flags=re.I)
        m_ = re.search(r"\s(ntc|nmc|mntc_late|mntc|none)\s*$", arg, re.I)
        ntc = m_.group(1).lower() if m_ else "none"
        arg = re.sub(r"\s(ntc|nmc|mntc_late|mntc|none)\s*$", "", arg, flags=re.I)
        who, aav, years = self.split_terms(arg)
        if aav is None or years is None:
            raise ValueError("Usage: propose <player> <aav> <years> [ntc], e.g. propose Suzuki 7.5m 6")
        r = self.find(who, "(team_id=? OR team_id IS NULL)", (user_team(self.conn),))
        outcome, v = N.offer(self.conn, r["player_id"], aav, years, ntc, structure)
        self.conn.commit()
        self.p({"agreed": "AGREED.", "counter": "Counter-offer.", "broken": "Talks broken off."}[outcome])
        self._talks(v)

    def do_career(self, arg):
        """career <player>: his NHL career before this save. career import <m3 profiles.csv> [apply]: take NHL games and
        seasons from the M3 player profile export. drafts import <file.csv> [apply]: past drafts (draft_year, round,
        overall, team, player). career seasons import <file.csv> [apply]: past seasons line by line (docs/HISTORY.md).
        Without 'apply' you see what would happen."""
        self.need(allow_fired=True)
        from . import career as CR
        a = arg.strip()
        m = re.match(r"^(career|drafts|seasons)?\s*import\s+(.+?)(\s+apply)?$", a, re.I)
        if m:
            path = m.group(2).strip().strip('"')
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                text = fh.read()
            apply = bool(m.group(3))
            if (m.group(1) or "").lower() == "seasons":
                r = CR.import_seasons(self.conn, text, apply)
                self.p(f"{r['rows']} rows: {r['seasons']} season lines for {r['players']} players, {len(r['errors'])} "
                       f"problems." + (f" {r['cleared']} games-only careers replaced." if apply else " Add 'apply' to import."))
                for e in r["errors"][:10]:
                    self.p(f"  row {e['row']}: {e['error']}")
            elif (m.group(1) or "career").lower() == "drafts":
                r = CR.import_drafts(self.conn, text, apply)
                self.p(f"{r['rows']} rows: {r['linked']} linked, {r['named']} by name, {r['skipped']} already on file, "
                       f"{len(r['errors'])} problems." + (" Imported." if apply else " Add 'apply' to import."))
                for e in r["errors"][:10]:
                    self.p(f"  row {e['row']}: {e['error']}")
            else:
                r = CR.import_m3(self.conn, text, apply)
                self.p(f"{r['rows']} profiles, {r['with_nhl']} with NHL games: {r['matched']} matched, "
                       f"{len(r['unmatched'])} not found, {r['skipped_recorded']} with seasons on file."
                       + (" Imported." if apply else " Add 'apply' to import."))
            self.conn.commit()
            return
        if not a:
            raise ValueError("Usage: career <player> | career import <file> [apply] | career drafts import <file> [apply]")
        r = self.find(a)
        p = CR.prior(self.conn, r["player_id"])
        if not p:
            self.p(f"{r['first_name']} {r['last_name']}: no NHL career on file from before this save.")
        else:
            self.p(f"{r['first_name']} {r['last_name']} before this save: {p['gp']} NHL games over {p['seasons']} seasons"
                   + (f", {p['g']} G {p['a']} A" if p["g"] or p["a"] else "") + (f", {p['w']} W {p['so']} SO" if p["w"] else "")
                   + f" (source: {p['source']}).")

    def do_drafts(self, arg):
        "drafts import <file.csv> [apply]: past drafts (see `help career`)"
        self.do_career("drafts " + arg.strip())

    def do_editor(self, arg):
        "editor [on|off]: commissioner mode (the editor and bulk import); turning it on marks the save as edited"
        self.need(allow_fired=True)
        from . import editor as ED
        a = arg.strip().lower()
        if a in ("on", "off"):
            ED.set_enabled(self.conn, a == "on")
            self.conn.commit()
        self.p(f"Commissioner mode is {'on' if ED.enabled(self.conn) else 'off'}" +
               (f" (this save has been edited since {ED.edited(self.conn)})." if ED.edited(self.conn) else "."))

    def do_edit(self, arg):
        "edit <player>: field=value ...  (commissioner mode) e.g. edit Suzuki: passing=15 cap_hit=8m team=MTL"
        self.need(allow_fired=True)
        from . import editor as ED
        if ":" not in arg:
            raise ValueError("Usage: edit <player>: field=value field=value ...")
        who, rest = arg.split(":", 1)
        r = self.find(who)
        changes = dict(x.split("=", 1) for x in rest.split() if "=" in x)
        done = ED.edit_player(self.conn, r["player_id"], changes)
        self.conn.commit()
        self.p(f"Edited {r['first_name']} {r['last_name']}: {', '.join(done) or 'nothing changed'}.")

    def do_intensity(self, arg):
        "intensity [light|normal|hard]: your club's training intensity (development against injuries)"
        me = self.need()
        from . import development as DV
        a = arg.strip().lower()
        if not a:
            self.p(f"Training intensity: {DV.intensity(self.conn, me)} (light, normal or hard).")
            return
        DV.set_intensity(self.conn, me, a)
        g, inj, dec = DV.INTENSITY[a]
        self.p(f"Training intensity set to {a}: young players grow x{g:.2f}, injuries x{inj:.2f}, veterans age x{dec:.2f}.")
        self.conn.commit()

    def do_mentor(self, arg):
        "mentor <young player> <veteran> | mentor end <young player>: pair a prospect with a veteran mentor"
        me = self.need()
        from . import development as DV
        a = arg.strip()
        if a.lower().startswith("end "):
            r = self.find(a[4:], "team_id=?", (me,))
            DV.end_mentor(self.conn, r["player_id"])
            self.p("Mentoring ended.")
        else:
            parts = [x.strip() for x in a.split(",")] if "," in a else a.split()
            if len(parts) != 2:
                raise ValueError("Usage: mentor <young player>, <veteran>  (ids work too: mentor 123 456)")
            pupil = self.find(parts[0], "team_id=?", (me,))
            mentor = self.find(parts[1], "team_id=?", (me,))
            self.p(DV.assign_mentor(self.conn, me, pupil["player_id"], mentor["player_id"], self.today()))
        self.conn.commit()

    def do_pto(self, arg):
        "pto [<player> | release <player>]: professional tryouts at training camp (up to three free agents, no contract)"
        me = self.need()
        from . import pto as PTO
        a = arg.strip()
        if not a:
            rows = PTO.current(self.conn, me)
            if not rows:
                self.p("Nobody is in camp on a tryout. `pto <player>` invites an unsigned free agent.")
            for r in rows:
                n = self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (r["player_id"],)).fetchone()[0]
                self.p(f"  {n}: {r['status']} since {r['since']}" + (f" - {r['report']}" if r["report"] else ""))
            return
        if a.lower().startswith("release "):
            r = self.find(a[8:])
            self.p(PTO.release(self.conn, r["player_id"]))
        else:
            r = self.find(a, "team_id IS NULL")
            self.p(PTO.invite(self.conn, r["player_id"], self.today()))
        self.conn.commit()

    def do_pitch(self, arg):
        "pitch <player> hometown|friends|winning: sell a player in contract talks (once each)"
        from . import negotiation as N
        a = arg.split()
        if len(a) < 2:
            raise ValueError("Usage: pitch <player> hometown|friends|winning")
        r = self.find(" ".join(a[:-1]))
        text, _ = N.pitch(self.conn, r["player_id"], a[-1].lower())
        self.p(text)

    def do_endtalks(self, arg):
        "endtalks <player>: end contract talks"
        self.need()
        from . import negotiation as N
        r = self.find(arg.strip(), "(team_id=? OR team_id IS NULL)", (user_team(self.conn),))
        N.walk(self.conn, r["player_id"])
        self.conn.commit()
        self.p("Talks ended.")

    def do_arbitrate(self, arg):
        "arbitrate <player>: elect club arbitration for your RFA (award at least 85% of his salary; once per career)"
        self.need()
        r = self.find(arg, "team_id=?", (user_team(self.conn),))
        sub = O.club_elect(self.conn, r["player_id"], self.today())
        self.p(f"Filed: he asks ${sub['ask']:,.0f}, you offer ${sub['offer']:,.0f} (comparables ${sub['comparables']:,.0f}).")

    def do_walkaway(self, arg):
        "walkaway <player>: decline a player-elected arbitration award at or above the threshold (he becomes a UFA)"
        self.need()
        r = self.find(arg, "team_id=?", (user_team(self.conn),))
        O.walk_away(self.conn, r["player_id"])
        self.p(f"You walked away from {r['first_name']} {r['last_name']}'s award.")

    def _trade_assets(self, text, team):
        """Comma-separated players (names or ids) and picks ('2027 1st', '2027 2nd TOR') owned by team."""
        from . import gm_trades as GT
        out = []
        for x in (t.strip() for t in text.split(",")):
            if not x:
                continue
            if x.startswith("player:"):
                x = x[7:]
            pk = GT.parse_pick(self.conn, x, team) if re.match(r"^(\d{4}\s|pick:)", x) else None
            out.append(pk or ("player", self.find(x, "team_id=?", (team,))["player_id"]))
        return out

    def _parse_trade(self, arg, need_give=True):
        me = self.need()
        retain_txt = ""
        if re.search(r"\sretain\s", arg, re.I):
            arg, retain_txt = re.split(r"\sretain\s", arg, maxsplit=1, flags=re.I)
        m = re.match(r"^(\S+)\s+give\s+(.*?)\s+get\s+(.*)$", arg.strip(), re.I)
        if not m:
            raise ValueError("Usage: trade <ABBR> give <p1, 2027 2nd> get <p3, 2026 1st> [retain p1=50]")
        other = self.team_by_abbr(m.group(1))
        if other == me:
            raise ValueError("Pick another team.")
        give, get = self._trade_assets(m.group(2), me), self._trade_assets(m.group(3), other)
        retain = {}
        for part in filter(None, (x.strip() for x in retain_txt.split(","))):
            who, _, pct = part.rpartition("=")
            retain[self.find(who, "team_id=?", (me,))["player_id"]] = float(pct.rstrip("%")) / 100
        return me, other, give, get, retain

    def do_trade(self, arg):
        """trade <ABBR> give <p1, 2027 2nd> get <p3, 2026 1st TOR> [retain p1=50]: propose a trade. Players by name
        or id, picks as '<year> <round>' (add the original club for a pick you got from someone else)."""
        from . import gm_trades as GT
        me, other, give, get, retain = self._parse_trade(arg)
        ok, text = GT.propose(self.conn, me, other, give, get, self.today(), retain)
        self.conn.commit()
        self.p(text)

    def _parse_trade3(self, arg):
        """'TOR BOS; me>TOR: Smith, 2027 2nd; TOR>BOS: Jones; BOS>me: Brown' -> [(from, to, asset)]"""
        me = self.need()
        parts = [x.strip() for x in arg.split(";") if x.strip()]
        if len(parts) < 2:
            raise ValueError("Usage: trade3 <A> <B>; me>A: assets; A>B: assets; B>me: assets")
        clubs = parts[0].split()
        if len(clubs) != 2:
            raise ValueError("Name the two other clubs first: trade3 TOR BOS; ...")
        ids = {"me": me}
        for ab in clubs:
            ids[ab.lower()] = self.team_by_abbr(ab)
        ab_of = {v: k for k, v in ids.items()}
        moves = []
        for part in parts[1:]:
            m = re.match(r"^(\S+)\s*>\s*(\S+?)\s*:\s*(.*)$", part)
            if not m:
                raise ValueError(f"Could not read '{part}' (expected FROM>TO: assets).")
            frm, to = (ids.get(x.lower()) if x.lower() in ids else self.team_by_abbr(x) for x in m.group(1, 2))
            if frm not in ab_of or to not in ab_of:
                raise ValueError("Only the three clubs named can be in the trade.")
            for a in self._trade_assets(m.group(3), frm):
                moves.append((frm, to, a))
        return moves

    def do_trade3(self, arg):
        """trade3 <A> <B>; me>A: p1, 2027 2nd; A>B: p2; B>me: p3: propose a three-team trade (each AI club judges
        what it gets against what it gives; all or nothing)"""
        from . import trade3 as T3
        ok, text = T3.propose(self.conn, self._parse_trade3(arg), self.today())
        self.conn.commit()
        self.p(text)
        if not ok:
            self.status_code = 1

    def do_trade3check(self, arg):
        "trade3check <A> <B>; ...: how both clubs see a three-team trade, without making it"
        from . import trade3 as T3
        ev = T3.evaluate(self.conn, self._parse_trade3(arg), self.today())
        for t, v in ev["clubs"].items():
            self.p(f"{v['abbr']}: {'yes' if v['accept'] else 'no'}. {v['why']}")

    def do_tradecheck(self, arg):
        "tradecheck <ABBR> give ... get ...: how the other club sees a trade, without making it"
        from . import gm_trades as GT
        me, other, give, get, _ = self._parse_trade(arg)
        ev = GT.evaluate(self.conn, me, other, give, get, self.today())
        self.p(("They would accept. " if ev["accept"] else "They would say no. ") + ev["why"]
               + f" ({team_abbr_of(self, other)}: {POSTURE_WORDS[ev['posture']]}; weakest group: "
                 f"{GROUP_WORDS[ev['need']]}.)")

    def do_ask(self, arg):
        "ask <ABBR> get <p3, 2026 1st>: what the other club would want from you for those assets"
        from . import gm_trades as GT
        me = self.need()
        m = re.match(r"^(\S+)\s+(?:get\s+)?(.*)$", arg.strip(), re.I)
        if not m:
            raise ValueError("Usage: ask <ABBR> get <players or picks>")
        other = self.team_by_abbr(m.group(1))
        get = self._trade_assets(m.group(2), other)
        pkg, why = GT.what_it_takes(self.conn, me, other, get, self.today())
        self.p(why)
        if pkg:
            self.p("To make it: trade " + team_abbr_of(self, other) + " give "
                   + ", ".join(GT.asset_key(a) if a[0] == "pick" else str(a[1]) for a in pkg) + " get "
                   + ", ".join(GT.asset_key(a) if a[0] == "pick" else str(a[1]) for a in get))

    def do_offers(self, arg):
        "offers: trade offers AI clubs have made you (accept <id> / decline <id>)"
        self.need()
        from . import gm_trades as GT
        rows = GT.open_offers(self.conn)
        for r in rows:
            self.p(GT.describe_offer(self.conn, r))
        if not rows:
            self.p("No open offers." + (" Put players on the block (`block <player>`) to draw calls."
                                        if not GT.on_block(self.conn) else ""))
        self.conn.commit()

    def do_accept(self, arg):
        "accept <offer id>: accept an AI club's trade offer"
        self.need()
        from . import gm_trades as GT
        self.p(GT.respond(self.conn, int(arg.strip().lstrip("#")), True, self.today()))
        self.conn.commit()

    def do_decline(self, arg):
        "decline <offer id> | decline <player>: turn down an AI club's trade offer, or do not qualify your RFA"
        me = self.need()
        from . import gm_trades as GT
        a = arg.strip().lstrip("#")
        # v53: one command for both (the RFA version was hidden by this one): an expiring player of yours wins over an
        # offer number, since player ids and offer numbers can look alike
        mine = {r["player_id"] for r in O.rights_rows(self.conn, me)} if K.season_state(self.conn) == "rights" else set()
        if a.isdigit() and int(a) not in mine and self.conn.execute("SELECT 1 FROM trade_offers WHERE offer_id=?", (int(a),)).fetchone():
            self.p(GT.respond(self.conn, int(a), False, self.today()))
            self.conn.commit()
            return
        r = self.find(a, "team_id=?", (me,))
        O.qualify(self.conn, r["player_id"], False)
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} will not be qualified.")

    def do_block(self, arg):
        "block [<player> | remove <player>]: your trading block (clubs call three times as often)"
        me = self.need()
        from . import gm_trades as GT
        a = arg.strip()
        if a:
            off = a.lower().startswith("remove ")
            r = self.find(a[7:] if off else a, "team_id=?", (me,))
            GT.block(self.conn, r["player_id"], not off)
            self.conn.commit()
        names = [self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (p,)).fetchone()[0]
                 for p in GT.on_block(self.conn)]
        self.p("On the block: " + (", ".join(names) if names else "nobody"))

    def do_shop(self, arg):
        "shop <player> | shop stop <player> | shop: tell the league a player is available (calls come over the next days)"
        me = self.need()
        from . import shop as SH
        a = arg.strip()
        if a.lower().startswith("stop "):
            r = self.find(a[5:], "team_id=?", (me,))
            SH.stop(self.conn, r["player_id"])
            self.conn.commit()
            self.p(f"Stopped shopping {r['first_name']} {r['last_name']}.")
            return
        if a:
            r = self.find(a, "team_id=?", (me,))
            self.p(SH.shop(self.conn, r["player_id"], self.today()))
            self.conn.commit()
            return
        rows = SH.shopping(self.conn)
        if not rows:
            self.p("You are not shopping anyone.")
        for pid, until, calls, planned in rows:
            name = self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?", (pid,)).fetchone()[0]
            self.p(f"{name}: shopped until {until}; {calls} offer(s) so far.")

    def do_discipline(self, arg):
        """discipline | discipline appeal <player>: suspensions around the league (League > Discipline)"""
        self.need(allow_fired=True)
        from . import discipline as D
        a = arg.strip()
        if a.lower().startswith("appeal "):
            self.p(D.appeal(self.conn, self.find(a[7:])["player_id"], self.today()))
            self.conn.commit()
            return
        v = D.view(self.conn)
        self.p(f"Suspended now: {len(v['active'])}")
        for x in v["active"]:
            self.p(f"  {x['name']:<26}{x['team']:<5}{x['left']} of {x['games']} game(s) left  ({x['reason']})")
        for x in v["log"][:15]:
            self.p(f"  {x['day']}  {x['name']:<26}{x['team']:<5}{x['games']} game(s), {x['reason']}" + (f"; appeal {x['appeal']}" if x["appeal"] else ""))

    def do_lineups(self, arg):
        """lineups | lineups on|off | lineups list <C|LW|RW|LD|RD|G|PP|PK> <player>, <player> ... | lineups goalie usual|every_game|
        back_to_back|every_fourth : priority lists that rebuild your lines before every game"""
        me = self.need()
        from . import lineups as LUP
        c = self.conn
        a = arg.strip()
        low = a.lower()
        if low in ("on", "off"):
            LUP.set_enabled(c, me, low == "on")
            c.commit()
            self.p(f"Lineups {'on: your lines are rebuilt from your lists before every game' if low == 'on' else 'off'}.")
            return
        if low.startswith("goalie "):
            LUP.set_goalie_rule(c, me, low[7:].strip())
            c.commit()
            self.p(f"Goalie rule: {low[7:].strip()}.")
            return
        if low.startswith("list "):
            key, _, names = a[5:].partition(" ")
            pids = [int(x) if x.strip().isdigit() else self.find(x, "team_id=?", (me,))["player_id"] for x in names.split(",") if x.strip()]
            LUP.set_list(c, me, key.upper(), pids)
            c.commit()
            self.p(f"{key.upper()} list saved ({len(pids)}).")
            return
        v = LUP.view(c, me)
        self.p(f"Lineups: {'on' if v['enabled'] else 'off'}; goalie rule {v['goalie_rule']}.")
        for k, xs in v["lists"].items():
            self.p(f"  {k:<3}" + ", ".join(x["name"] + ("" if x["status"] == "active" else f" ({x['status']})") for x in xs))

    def do_intl(self, arg):
        """intl | intl ranking | intl <tournament id> | intl readmit on|off: international hockey (League > International)"""
        self.need(allow_fired=True)
        from . import international as INTL
        c = self.conn
        a = arg.strip().lower()
        if a.startswith("readmit"):
            INTL.set_banned(c, a.endswith("on"))
            c.commit()
            self.p("Russia and Belarus: " + ("readmitted to international play." if a.endswith("on") else "excluded (the IIHF ban)."))
            return
        if a == "ranking":
            for r in INTL.view(c)["ranking"][:20]:
                self.p(f"  {r['rank']:>2}. {r['nation']:<16}{r['points']:>6}" + ("  (excluded)" if r["banned"] else ""))
            return
        if a.isdigit():
            d = INTL.view(c, int(a)).get("detail")
            if not d:
                self.p("No such tournament.")
                return
            self.p(f"{d['name']} ({d['status']}): " + " - ".join(d["places"][:3]))
            for g in d["games"][-6:]:
                self.p(f"  {g['stage']}: {g['home']} {g['hg']}-{g['ag']} {g['away']}{' (OT)' if g['ot'] == 1 else ' (SO)' if g['ot'] == 2 else ''}")
            for x in d["leaders"][:5]:
                self.p(f"  {x['name']:<26}{x['nation']:<16}{x['g']}-{x['a']}-{x['p']}")
            return
        v = INTL.view(c)
        for u in v["upcoming"]:
            self.p(f"Coming: {u['name']} ({u['start']} to {u['end']})")
        for t in v["tournaments"][:10]:
            self.p(f"  [{t['tid']}] {t['name']}: " + (" - ".join(t["podium"]) if t["podium"] else t["status"]))

    def do_number(self, arg):
        """number <player> <n> [swap] | number retire <n> <player> [ABBR] | number retired [ABBR]
        : jersey numbers (change your players' numbers; retire a number at your club)"""
        me = self.need(allow_fired=True)
        from . import numbers as NUM
        c = self.conn
        a = arg.strip()
        low = a.lower()
        if low.startswith("retired"):
            ab = a[7:].strip()
            t = c.execute("SELECT team_id FROM teams WHERE UPPER(abbr)=?", (ab.upper(),)).fetchone()[0] if ab else me
            rows = NUM.retired_list(c, t)
            self.p("Retired numbers: " + (", ".join(f"#{r['number']} {r['name']}" for r in rows) or "none") + " (and #99 league-wide).")
            return
        if low.startswith("retire "):
            parts = a[7:].split()
            n = parts[0]
            team = me
            if len(parts) > 2 and c.execute("SELECT 1 FROM teams WHERE UPPER(abbr)=?", (parts[-1].upper(),)).fetchone():
                team = c.execute("SELECT team_id FROM teams WHERE UPPER(abbr)=?", (parts[-1].upper(),)).fetchone()[0]
                parts = parts[:-1]
            r = self.find(" ".join(parts[1:]))
            self.p(NUM.retire(c, team, n, r["player_id"]))
            c.commit()
            return
        swap = low.endswith(" swap")
        if swap:
            a = a[:-5]
        name, _, n = a.rpartition(" ")
        if not name:
            raise ValueError("number <player> <n> [swap]")
        r = self.find(name, "team_id=?", (me,)) if not __import__("hs.game.editor", fromlist=["x"]).enabled(c) else self.find(name)
        self.p(NUM.set_number(c, r["player_id"], n, swap))
        c.commit()

    def do_challenge(self, arg):
        """challenge | challenge mode on | challenge start <turnaround|rebuild|win_now|cap_hell|dynasty|expansion> | challenge abandon
        : challenge mode and challenges (Manager > Challenges)"""
        self.need(allow_fired=True)
        from . import challenge as CH
        a = arg.strip().lower()
        c = self.conn
        if a == "mode on":
            CH.set_mode(c, True)
            c.commit()
            self.p("Challenge mode is on for the rest of this career: no editor, short sims in season, and you can be fired.")
            return
        if a.startswith("start "):
            x = CH.start(c, a[6:].strip(), self.today())
            c.commit()
            self.p(f"Challenge on: {x['name']}. {x['goal']} Deadline: {x['deadline']}-{(x['deadline'] + 1) % 100:02d}.")
            return
        if a == "abandon":
            CH.abandon(c, self.today())
            c.commit()
            self.p("Challenge abandoned.")
            return
        v = CH.view(c)
        self.p(f"Challenge mode: {'on' if v['mode'] else 'off'}" + (" (this save has used commissioner mode)" if v["edited"] else ""))
        cur = v["current"]
        if cur:
            self.p(f"Challenge: {cur['name']} ({cur['status']}): {cur['goal']} Deadline {cur['deadline']}-{(cur['deadline'] + 1) % 100:02d}."
                   + (f" {cur.get('result', '')}" if cur["status"] != "on" else ""))
            for p in cur.get("progress", []):
                self.p(f"  {p['season']}-{(p['season'] + 1) % 100:02d} {p['team']}: playoff round {p['round']}")
        if v["can_start"]:
            for ch in v["challenges"]:
                self.p(f"  {ch['key']:<11}{ch['goal']}" + (f"  (suits: {', '.join(ch['suggest'])})" if ch["suggest"] else ""))
        for h in v["history"]:
            self.p(f"  {h['name']}: {h['status']} ({h['result']})")

    def do_commish(self, arg):
        """commish | commish trade <A> <ids/picks> for <B> <ids/picks> [force] | commish takeover <ABBR> | commish fire <ABBR> gm|coach
        | commish injure <player> <days> | commish heal <player> | commish rule cap|floor|min_salary|roster_max|roster_min|deadline <value>
        : commissioner tools (needs commissioner mode). Picks are written YEAR-ROUND-ABBR, e.g. 2027-1-MTL."""
        self.need(allow_fired=True)
        from . import commissioner as CM
        c = self.conn
        a = arg.strip()
        low = a.lower()
        if low.startswith("trade "):
            force = low.endswith(" force")
            body = a[6:-6] if force else a[6:]
            left, _, right = body.partition(" for ")
            if not right:
                raise ValueError("commish trade <A> <ids/picks> for <B> <ids/picks> [force]")
            def side(txt):
                parts = txt.replace(",", " ").split()
                team = CM._team(c, parts[0])
                pids, picks = [], []
                for x in parts[1:]:
                    if x.count("-") == 2:
                        y, r, o = x.split("-")
                        picks.append((int(y), int(r), CM._team(c, o)))
                    else:
                        pids.append(int(x) if x.isdigit() else self.find(x, "team_id=?", (team,))["player_id"])
                return team, pids, picks
            ta, pa, ka = side(left)
            tb, pb, kb = side(right)
            self.p(CM.trade(c, ta, pa, tb, pb, ka, kb, force=force))
            c.commit()
            return
        if low.startswith("takeover "):
            self.p(CM.takeover(c, CM._team(c, a[9:])))
            c.commit()
            return
        if low.startswith("fire "):
            ab, who = a[5:].split()
            self.p(CM.fire(c, CM._team(c, ab), who.lower()))
            c.commit()
            return
        if low.startswith("injure "):
            name, _, days = a[7:].rpartition(" ")
            self.p(CM.injure(c, self.find(name)["player_id"], days))
            c.commit()
            return
        if low.startswith("heal "):
            self.p(CM.heal(c, self.find(a[5:])["player_id"]))
            c.commit()
            return
        if low.startswith("rule "):
            k, _, v = a[5:].partition(" ")
            self.p(CM.set_rule(c, k.lower(), v))
            c.commit()
            return
        v = CM.view(c)
        self.p(f"Commissioner mode: {'on' if v['enabled'] else 'off'}" + (" (challenge-mode career: not available)" if v["challenge_mode"] else ""))
        r = v["rules"]
        self.p(f"Cap ${r['cap'] / 1e6:.1f}M, floor ${r['floor'] / 1e6:.1f}M, minimum ${r['min_salary'] / 1e3:.0f}K, roster {r['roster_min']}-{r['roster_max']}, deadline {r['deadline']}")

    def do_college(self, arg):
        """college | college prospects | college path <player> college|junior|none | college fa | college offer <player> [now]
        | college withdraw <player> | college program <name>: college hockey (League > College Hockey)"""
        me = self.need()
        from . import college as CO
        c = self.conn
        a = arg.strip()
        low = a.lower()
        if not CO.active(c):
            self.p("This world has no college league.")
            return
        if low.startswith("path "):
            rest = a[5:].strip()
            name, _, path = rest.rpartition(" ")
            r = self.find(name, "player_id IN (SELECT player_id FROM draft_rights WHERE team_id=?)", (me,))
            self.p(CO.set_path(c, r["player_id"], path.lower()))
            c.commit()
            return
        if low.startswith("offer "):
            rest = a[6:].strip()
            now = rest.lower().endswith(" now")
            if now:
                rest = rest[:-4]
            r = self.find(rest, "player_id IN (SELECT player_id FROM college_fa WHERE status='open')")
            self.p(CO.offer(c, r["player_id"], me, now, self.today()))
            c.commit()
            return
        if low.startswith("withdraw "):
            r = self.find(a[9:], "player_id IN (SELECT player_id FROM college_fa)")
            CO.withdraw(c, r["player_id"], me)
            c.commit()
            self.p("Offer withdrawn.")
            return
        if low.startswith("program "):
            t = c.execute("SELECT team_id FROM teams WHERE league_id=? AND LOWER(name) LIKE ?", (CO.ncaa_league(c), f"%{a[8:].strip().lower()}%")).fetchone()
            if not t:
                self.p("No such program.")
                return
            v = CO.view(c, t[0])["program"]
            i = v["info"]
            self.p(f"{i['name']} ({i['conference']}): prestige {i['prestige']:.0f}, coach {i['coach']}, {i['titles']} titles in this save")
            for x in v["roster"]:
                self.p(f"  {x['name']:<26}{x['pos']:<3}{x['overall']:>6.2f}  {x['class_name']:<10}{x['rights']}")
            for x in v["commits"]:
                self.p(f"  commit {x['year']}: {x['name']} ({x['pos']})")
            return
        v = CO.view(c)
        if low.startswith("prospects"):
            for m in v["mine"]:
                col = m["college"]
                where = (f"{col['program']} ({col['class_name']}, {col['left']} more season(s))" if col else
                         f"committed to {m['commit']['program']} for {m['commit']['year']}" if m["commit"] else m["where"])
                self.p(f"  {m['name']:<26}{m['pos']:<3} rights to {m['expires']}  {where}" + (f"  [path {m['path']}]" if m["path"] else ""))
            return
        if low.startswith("fa"):
            for x in v["fa"]:
                self.p(f"  {x['name']:<26}{x['pos']:<3}{(x['overall'] or 0):>6.2f}  {x['reason']:<18}{x['status']:<9} offers {x['offers']}"
                       + (" (yours)" if x["mine"] else "") + (f" -> {x['signed']}" if x["signed"] else f" decides {x['decide_by']}"))
            if not v["fa"]:
                self.p("The college free-agent market opens when the NCAA season ends.")
            return
        self.p(f"College hockey {v['season']}-{(v['season'] + 1) % 100:02d}: {len(v['programs'])} programs. Top by prestige:")
        for p in v["programs"][:12]:
            self.p(f"  {p['name']:<44}{p['prestige']:>5.0f}  {p['players']} players, {p['nhl_picks']} NHL picks, {p['commits']} commits")
        if v["hobey"]:
            h = v["hobey"][0]
            self.p(f"Hobey Baker {h['season']}-{(h['season'] + 1) % 100:02d}: {h['name']} ({h['detail']})")

    def do_expansion(self, arg):
        """expansion | expansion create <City> | <Nickname> | <ABBR> [| Eastern|Western] [| gm] | expansion mode occasional|off
        | expansion protect auto|<scheme 7-3-1|8-1> <player>, <player>, ... | expansion pick <ABBR> <player> | expansion unpick <ABBR>
        : new clubs and the expansion draft (League > Expansion)"""
        me = self.need()
        from . import expansion as XP
        a = arg.strip()
        low = a.lower()
        c = self.conn
        if low.startswith("mode "):
            XP.set_mode(c, a[5:].strip().lower())
            c.commit()
            self.p(f"League expansion: {XP.mode(c)}.")
            return
        if low.startswith("create "):
            parts = [x.strip() for x in a[7:].split("|")]
            if len(parts) < 3:
                self.p("expansion create <City> | <Nickname> | <ABBR> [| Eastern|Western] [| gm]")
                return
            conf = next((x for x in parts[3:] if x.lower() in ("eastern", "western")), None)
            gm = any(x.lower() == "gm" for x in parts[3:])
            XP.announce(c, self.today(), parts[0], parts[1], parts[2], conf.title() if conf else None, by_user=True, user_gm=gm)
            c.commit()
            self.p(f"The {parts[0]} {parts[1]} will join next season." + (" You will be their GM." if gm else ""))
            return
        if low.startswith("protect "):
            rest = a[8:].strip()
            if rest.lower() == "auto":
                scheme, pids = XP.auto_protect(c, me)
            else:
                scheme, _, names = rest.partition(" ")
                pids = [self.find(n.strip(), "team_id=?", (me,))["player_id"] for n in names.split(",") if n.strip()]
            XP.set_protection(c, me, scheme, pids)
            c.commit()
            self.p(f"Protection list submitted ({scheme}, {len(pids)} players).")
            return
        if low.startswith("pick ") or low.startswith("unpick "):
            verb, ab, *who = a.split(None, 2)
            t = c.execute("SELECT team_id FROM teams WHERE UPPER(abbr)=? AND team_id IN (%s)" % ",".join(map(str, XP._top(c))),
                          (ab.upper(),)).fetchone()
            if not t:
                self.p(f"No club {ab}.")
                return
            if verb.lower() == "unpick":
                XP.unchoose(c, t[0])
                self.p(f"Your pick from {ab.upper()} is back with your staff.")
            else:
                r = self.find(who[0] if who else "", "team_id=?", (t[0],))
                XP.choose(c, t[0], r["player_id"])
                self.p(f"From {ab.upper()}: {r['first_name']} {r['last_name']}.")
            c.commit()
            return
        v = XP.view(c)
        self.p(f"League expansion: {v['mode']}; {v['clubs']} clubs (limit {v['max']}).")
        e = v.get("pending")
        if e:
            self.p(f"On the way: the {e['city']} {e['nickname']} ({e['abbr']}), {e['division']} Division, from {e['first_season']}; {e['status']}.")
        if v.get("protect"):
            pr = v["protect"]
            names = [x["name"] for x in pr["pool"] if x["player_id"] in pr["players"]]
            self.p(f"Your list ({pr['scheme']}): " + ", ".join(names))
            for x in pr["problems"]:
                self.p("  ! " + x)
        if v.get("draft"):
            for d in v["draft"]:
                pk = d["pick"]
                self.p(f"  {d['abbr']}: {pk['name'] + ' (' + pk['pos'] + ')' if pk else '-'}{' (yours)' if d['mine'] else ''}")
        for h in v["history"]:
            self.p(f"  {h['city']} {h['nickname']} ({h['abbr']}): from {h['first_season']}, {h['status']}")

    def do_picks(self, arg):
        "picks [ABBR]: draft picks a club owns in the tradeable drafts"
        me = self.need()
        from . import gm_trades as GT
        from . import trades as T
        team = self.team_by_abbr(arg.strip()) if arg.strip() else me
        rows = [a for a in GT.assets_of(self.conn, team) if a[0] == "pick"]
        for _, (y, rnd, orig) in rows:
            self.p("  " + T.pick_label(self.conn, y, rnd, orig, team))
        if not rows:
            self.p("No tradeable picks.")

    def do_inbox(self, arg):
        "inbox [all]: unread messages (marks them read)"
        self.need()
        rows = self.conn.execute("SELECT * FROM inbox " + ("" if arg.strip() == "all" else "WHERE read=0 ")
                                 + "ORDER BY msg_id").fetchall()
        for r in rows:
            self.p(f"[{r['date']}] {r['subject']}: {r['body']}")
        if not rows:
            self.p("No messages.")
        self.conn.execute("UPDATE inbox SET read=1")
        self.conn.commit()

    def do_draftnext(self, arg):
        "draftnext [n]: make the next n picks of the draft (default 1; stops when you are on the clock)"
        self.need()
        from . import draft as D
        if K.season_state(self.conn) != "draft":
            raise ValueError("The draft is not on.")
        n = int(arg) if arg.strip().isdigit() else 1
        for line in D.advance_picks(self.conn, self.today(), stop_for_user=True, max_picks=n):
            self.p(line)

    def do_press(self, arg):
        "press: press conferences waiting for you (answer with `answer <id> <choice> <choice> ...`)"
        self.need()
        from . import press
        for r in press.pending(self.conn):
            self.p(f"#{r['press_id']} {r['kind'].replace('_', ' ')} (expires {r['expires']})")
            for i, q in enumerate(json.loads(r["questions"])):
                self.p(f"  Q{i + 1} {q['reporter']}: {q['text']}")
                for j, a in enumerate(q["answers"]):
                    self.p(f"     {j + 1}. [{a['label']}] {a['text']}")
        if not press.pending(self.conn):
            self.p("No press conferences waiting.")

    def do_answer(self, arg):
        "answer <press id> <choice per question, 1-based>: give your answers at a press conference"
        self.need()
        from . import press
        t = arg.split()
        if len(t) < 2 or not all(x.isdigit() for x in t):
            raise ValueError("Usage: answer <press id> <choice> <choice> ...")
        out = press.answer(self.conn, int(t[0]), [int(x) - 1 for x in t[1:]])
        self.conn.commit()
        tt = out["totals"]
        self.p(f"Done. Room {tt['morale']:+.1f}, board {tt['board']:+.1f}, fans {tt['fans']:+.1f}. " + " ".join(out["lines"]))

    def do_leaders(self, arg):
        "leaders <captain> [<alternate>] [<alternate>]: name your leadership group (players by id or name, comma-separated)"
        me = self.need()
        from . import captaincy
        names = [x.strip() for x in arg.split(",") if x.strip()]
        if not names:
            raise ValueError("Usage: leaders <captain>, <alternate>, <alternate>")
        ids = [self.find(n, "team_id=? AND status IN ('active','injured')", (me,))["player_id"] for n in names]
        fx = captaincy.apply(self.conn, me, ids[0], ids[1:])
        self.conn.commit()
        self.p("Leadership group set. " + " ".join(f"{x['name']} {x['change']} ({x['mood']})." for x in fx["people"]))

    def do_read(self, arg):
        "read <message id> [unread]: mark one inbox message read (or unread)"
        self.need()
        t = arg.split()
        if not t or not t[0].isdigit():
            raise ValueError("Usage: read <message id> [unread]")
        self.conn.execute("UPDATE inbox SET read=? WHERE msg_id=?", (0 if t[1:] == ["unread"] else 1, int(t[0])))
        self.conn.commit()

    def do_mail(self, arg):
        "mail flag|unflag|archive|restore <message id>: flag a message or move it to the archive (v38)"
        self.need(allow_fired=True)
        from .state import _inbox_columns
        _inbox_columns(self.conn)
        t = arg.split()
        ops = {"flag": ("flagged", 1), "unflag": ("flagged", 0), "archive": ("archived", 1), "restore": ("archived", 0)}
        if len(t) != 2 or t[0] not in ops or not t[1].isdigit():
            raise ValueError("Usage: mail flag|unflag|archive|restore <message id>")
        col, v = ops[t[0]]
        self.conn.execute(f"UPDATE inbox SET {col}=?, read=CASE WHEN ?='archived' THEN 1 ELSE read END WHERE msg_id=?", (v, col, int(t[1])))
        self.conn.commit()

    def do_playoffs(self, arg):
        "playoffs: series results (after the regular season)"
        self.need()
        ab = self.abbr()
        rows = self.conn.execute("SELECT series_id, home_team_id h, away_team_id a, home_goals hg, away_goals ag "
                                 "FROM games WHERE game_type='PO' AND played=1 AND season_id=? ORDER BY game_date, game_id",
                                 (self.season_id(),)).fetchall()
        if not rows:
            self.p("Playoffs have not been played yet.")
            return
        series = {}
        for r in rows:
            w = r["h"] if r["hg"] > r["ag"] else r["a"]
            key = (r["series_id"], frozenset((r["h"], r["a"])))   # labels can repeat within a round
            s = series.setdefault(key, {r["h"]: 0, r["a"]: 0})
            s[w] += 1
        for (sid, _), w in series.items():
            (a, na), (b, nb) = sorted(w.items(), key=lambda x: -x[1])
            self.p(f"  {sid:<34}{ab[a]} {na}-{nb} {ab[b]}")

    def do_draftboard(self, arg):
        "draftboard [n]: available draft prospects as your scouts rate them (estimates, not true ratings)"
        me = self.need()
        from . import draft as D
        from . import scouting as S
        from . import world as Wd
        n = int(arg) if arg.strip().isdigit() else 25
        rows = D.board_rows(self.conn, me, n)
        if not rows:
            self.p("No draft prospects available (the draft runs in the 'draft' offseason phase).")
            return
        style = S.club_style(self.conn, me)
        self.p(f"Your scouts: {S.STYLE_LABEL[style]}, error about +/-{S.club_sd(self.conn, me) * S.OWN_SCALE:.2f} "
               "on top of what the whole league gets wrong.")
        self.p(f"  {'#':<4}{'id':<9}{'Name':<24}{'Pos':<4}{'Age':>3} {'Ht':>4}  {'Nat':<4}{'Projection':<22}"
               f"{'Last season':<28}Playing for / notes")
        for r in rows:
            nm = self.conn.execute("SELECT first_name||' '||last_name FROM players WHERE player_id=?",
                                   (r["pid"],)).fetchone()[0]
            ht = f"{r['height']}" if r["height"] else "-"
            self.p(f"  {r['rank']:<4}{r['pid']:<9}{nm[:23]:<24}{r['pos']:<4}{r['age']:>3} {ht:>4}  {r['nat'] or '':<4}"
                   f"{r['grade'][:21]:<22}{(r['line'] or '-')[:27]:<28}{Wd.where_is(self.conn, r['pid'])}"
                   + (f"  [{', '.join(r['flags'])}]" if r["flags"] else ""))

    @staticmethod
    def _grade(est, goalie=False):
        from .scouting import grade
        return grade(est, goalie)

    def do_pickswap(self, arg):
        """pickswap ABBR give 24[,56] get 18[,90]: trade picks in this draft with another club (draft day only).
        They price it with the pick value chart; the pick on the clock costs more if a highly rated player is
        still on the board."""
        me = self.need()
        from . import draft as D
        from . import draft_floor as F
        a = arg.replace(",", " ").split()
        if len(a) < 4 or a[1] != "give" or "get" not in a:
            raise ValueError("Usage: pickswap ABBR give 24[,56] get 18[,90]")
        other = self.conn.execute("SELECT team_id FROM teams WHERE abbr=?", (a[0].upper(),)).fetchone()
        if other is None:
            raise ValueError(f"No club {a[0]}.")
        k = a.index("get")
        give, get = [int(x) for x in a[2:k]], [int(x) for x in a[k + 1:]]
        year = D.draft_year(self.conn)
        if not self.conn.execute("SELECT 1 FROM draft_picks WHERE draft_year=? AND player_id IS NULL",
                                 (year,)).fetchone():
            raise ValueError("Picks can only be swapped while the draft is on.")
        pool = D.eligible_rows(self.conn, year)
        brd = D._Board(self.conn, year, pool)
        nxt = self.conn.execute("SELECT MIN(overall) FROM draft_picks WHERE draft_year=? AND player_id IS NULL",
                                (year,)).fetchone()[0]
        top = min(pool, key=lambda x: x["expected_slot"]) if pool else None
        slide = max(0, nxt - top["expected_slot"]) if top else 0
        del brd
        self.p(F.pickswap(self.conn, year, me, other[0], give, get, self.today(), slide))
        self.conn.commit()

    def do_pick(self, arg):
        "pick <player>: make your selection when you are on the clock at the draft"
        self.need()
        from . import draft as D
        r = self.find(arg, "team_id IS NULL AND status IN ('active','injured')")
        lines = D.user_pick(self.conn, r["player_id"], self.today())
        self.p(f"You drafted {r['first_name']} {r['last_name']}.")
        for line in lines:
            self.p(line)

    def do_prospects(self, arg):
        "prospects: players whose NHL rights you hold, and signed players in the minors or junior"
        me = self.need()
        from . import world as Wd
        rows = self.conn.execute("SELECT p.player_id, p.first_name||' '||p.last_name n, p.position, p.birth_date, "
                                 "d.draft_year, d.overall_pick, d.expires_year FROM draft_rights d JOIN players p "
                                 "USING (player_id) WHERE d.team_id=? ORDER BY d.overall_pick", (me,)).fetchall()
        self.p("Unsigned draft rights:")
        for r in rows:
            self.p(f"  {r['n']:<26}{r['position']:<4}age {self.age(r['birth_date']):<3} pick {r['overall_pick'] or '-':<4} "
                   f"({r['draft_year']}), rights to {r['expires_year']}  {Wd.where_is(self.conn, r['player_id'])}")
        if not rows:
            self.p("  none")
        rows = self.conn.execute("SELECT player_id, first_name||' '||last_name n, position, birth_date FROM players "
                                 "WHERE team_id=? AND status='prospect' ORDER BY position, last_name", (me,)).fetchall()
        self.p("Signed, playing below the NHL:")
        for r in rows:
            self.p(f"  {r['n']:<26}{r['position']:<4}age {self.age(r['birth_date']):<3} "
                   f"value {R.player_value(self.conn, r['player_id']):>3.0f}  {Wd.where_is(self.conn, r['player_id'])}")

    def do_elc(self, arg):
        "elc <player> [khl]: sign one of your draft picks to his entry-level contract (khl: the KHL buyout offer, at the maximum)"
        me = self.need()
        from . import draft as D
        a = arg.strip()
        khl = a.lower().endswith(" khl")
        if khl:
            a = a[:-4].strip()
        r = self.find(a, "player_id IN (SELECT player_id FROM draft_rights WHERE team_id=?)", (me,))
        try:
            years, aav = D.sign_elc(self.conn, r["player_id"], me, self.today(), khl_buyout=khl)
        except ValueError:
            self.conn.commit()                      # keep the record of this month's KHL answer
            raise
        self.conn.commit()
        e = self.conn.execute("SELECT * FROM elc_terms WHERE player_id=?", (r["player_id"],)).fetchone()
        self.p(f"{r['first_name']} {r['last_name']} signed his entry-level contract: {years} yr x ${aav:,.0f}"
               + (f" (signing bonus ${e['signing_bonus']:,.0f}/yr, performance bonuses up to ${e['perf_max']:,.0f}/yr"
                  + (f"; leverage: {e['leverage']}" if e["leverage"] else "") + ")" if e else "") + ".")

    def do_elcs(self, arg):
        "elcs: your entry-level contracts: bonuses, slides, bonuses earned"
        me = self.need()
        from . import elc as E
        E.ensure_tables(self.conn)
        rows = self.conn.execute(
            "SELECT p.first_name||' '||p.last_name n, c.start_year, c.years, c.cap_hit, e.* FROM contracts c "
            "JOIN elc_terms e USING (player_id) JOIN players p USING (player_id) WHERE c.team_id=? AND "
            "c.contract_type='entry_level' AND c.start_year+c.years>? ORDER BY c.cap_hit DESC",
            (me, K.season_year(self.conn))).fetchall()
        if not rows:
            self.p("No entry-level contracts with bonus terms.")
            return
        self.p(f"  {'Name':<24}{'Years':<11}{'Cap hit':>11}{'Sign bonus':>12}{'Perf max':>11}{'Earned':>11}  Slides")
        for r in rows:
            self.p(f"  {r['n']:<24}{r['start_year']}-{str(r['start_year'] + r['years'] - 1)[-2:]:<6}{r['cap_hit']:>11,.0f}"
                   f"{r['signing_bonus']:>12,.0f}{r['perf_max']:>11,.0f}{r['earned_total']:>11,.0f}  {r['slides']}")

    def do_shoprights(self, arg):
        "shoprights <player>: trade the rights to one of your unsigned draft picks for a late pick"
        me = self.need()
        from . import elc as E
        r = self.find(arg, "player_id IN (SELECT player_id FROM draft_rights WHERE team_id=?)", (me,))
        self.p(E.shop_rights(self.conn, me, r["player_id"], self.today()))
        self.conn.commit()

    def do_leagues(self, arg):
        "leagues: the leagues in this world, their level and clubs"
        self.need()
        from . import world as Wd
        meta = Wd.world_meta(self.conn)
        for r in self.conn.execute("SELECT l.league_id, l.abbr, l.name, l.level, COUNT(t.team_id) n FROM leagues l "
                                   "LEFT JOIN teams t USING (league_id) GROUP BY l.league_id ORDER BY l.level, l.abbr"):
            m = meta.get(r["league_id"], {})
            self.p(f"  {r['abbr']:<6}{r['name']:<40}level {r['level'] or 1}  {r['n']:>3} clubs  "
                   f"{m.get('kind', 'top'):<8}{'level %.1f' % m['mean'] if m else ''}")

    # ---- organisation
    def _has(self, table):
        return bool(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone())

    def do_dashboard(self, arg):
        "dashboard: your daily briefing - club, board, objectives, locker room, things needing attention, news"
        me = self.need(allow_fired=True)
        from . import events as E, org, people
        ab = self.abbr()
        r, pts = self.record(me)
        rec = f"{r['w']}-{r['l']}-{r['otl']}, {pts} pts" if r else "no games yet"
        self.p(f"=== {ab[me]}  |  {self.today()}  |  {season_state(self.conn)}  |  {rec}")
        room = K.cap_room(self.conn, me, K.signing_year(self.conn))
        self.p(f"Cap: payroll ${K.payroll(self.conn, me, K.signing_year(self.conn)):,.0f}"
               + (f", room ${room:,.0f}" if room is not None else ""))
        if self._has("board"):
            b, o = org.board_status(self.conn, me)
            self.p(f"Board: confidence {b['confidence']:.0f} ({org.label(b['confidence'])}); owner: {o['summary']}")
            for ob in self.conn.execute("SELECT * FROM objectives WHERE team_id=? AND status='active' ORDER BY "
                                        "objective_id", (me,)):
                self.p(f"  [{ob['importance']}] {ob['description']}")
        if self._has("team_room"):
            rm = people.room(self.conn, me)
            if rm:
                self.p(f"Locker room: {rm['atmosphere']} (cohesion {rm['cohesion']:.0f}, leadership "
                       f"{rm['leadership_strength']:.1f}/20)")
        self.p("Needs attention:")
        items = 0
        if self._has("concerns"):
            for c in people.open_concerns(self.conn, me):
                self.p(f"  - {E.player_name(self.conn, c['player_id'])} {c['detail']} (since {c['raised_on']}; "
                       f"`talk {c['player_id']}`)")
                items += 1
            for pr in self.conn.execute("SELECT * FROM promises WHERE team_id=? AND status='active' ORDER BY deadline",
                                        (me,)):
                self.p(f"  - promise to {E.player_name(self.conn, pr['player_id'])}: {pr['description']}")
                items += 1
        unread = self.conn.execute("SELECT COUNT(*) FROM inbox WHERE read=0").fetchone()[0]
        if unread:
            self.p(f"  - {unread} unread messages (`inbox`)")
            items += 1
        if not items:
            self.p("  nothing urgent")
        self.p("Recent news:")
        for e in E.recent(self.conn, team_id=me, limit=6):
            self.p(f"  {e['event_date']}  {e['summary']}")
        nxt = self.conn.execute("SELECT game_date, home_team_id, away_team_id FROM games WHERE played=0 AND "
                                "game_type='RS' AND (home_team_id=? OR away_team_id=?) ORDER BY game_date LIMIT 1",
                                (me, me)).fetchone()
        if nxt:
            self.p(f"Next game: {nxt['game_date']} " + (f"vs {ab[nxt['away_team_id']]}" if nxt["home_team_id"] == me
                                                       else f"@ {ab[nxt['home_team_id']]}"))

    def do_trades(self, arg):
        """trades [n]: recent trades around the league, with the trade deadline."""
        self.need(allow_fired=True)
        from . import trades as TR
        n = int(arg) if arg.strip().isdigit() else 25
        self.p(f"Trade deadline: {TR.deadline(self.conn).isoformat()}")
        rows = TR.recent(self.conn, n)
        if not rows:
            self.p("No trades yet.")
        for e in rows:
            self.p(f"{e['event_date']}  {e['summary']}")

    def do_history(self, arg):
        "history [league|<player>] [n]: organisational history (events), your club by default"
        me = self.need(allow_fired=True)
        from . import events as E
        toks = arg.split()
        n = int(toks.pop()) if toks and toks[-1].isdigit() else 25
        if toks and toks[0] == "league":
            rows = E.recent(self.conn, min_importance=2, limit=n)
        elif toks:
            rows = E.recent(self.conn, player_id=self.find(" ".join(toks))["player_id"], limit=n)
        else:
            rows = E.recent(self.conn, team_id=me, limit=n)
        for e in rows:
            self.p(f"  {e['event_date']}  {e['event_type']:<18} {e['summary']}")
        if not rows:
            self.p("No events yet.")

    def do_board(self, arg):
        "board: owner profile, objectives (this and past seasons) and recent board reviews with their reasons"
        me = self.need(allow_fired=True)
        from . import org
        from . import boardroom as BR
        BR.ensure_tables(self.conn)
        b, o = org.board_status(self.conn, me)
        self.p(f"Owner: {o['name']}, {o['archetype']}: {o['summary']}  (spend {o['spend']}, ambition {o['ambition']}, "
               f"patience {o['patience']}, youth {o['youth_pref']}, involvement {o['involvement']}, vocalness "
               f"{o['vocalness']:.2f}, analytics {o['analytics']:.2f}; wants {o['identity']})")
        if K.season_state(self.conn) == "regular_season":
            tr = BR.trigger(self.conn, me, self.today())
            self.p(f"Hot seat: trigger {tr['T']:.2f} = confidence {tr['confidence']:.2f} + velocity {tr['velocity']:+.2f}"
                   f" x {tr['patience_impact']:.2f} - pressure {tr['pressure']:.2f} x vocalness {tr['vocalness']:.2f}"
                   f"  (ultimatum at {BR.WARN})")
        u = BR.open_ultimatum(self.conn, me)
        if u:
            sid = self.season_id()
            gp, pts = BR._record(self.conn, me, sid)
            self.p(f"ULTIMATUM: {u['points_needed']} points in {u['games']} games from {u['issued']}: "
                   f"{pts - u['pts_at_issue']} points from {gp - u['gp_at_issue']} games so far")
        d = BR.open_directive(self.conn, me)
        if d:
            self.p(f"Directive: {d['description']} (by {d['deadline']})")
        self.p(f"Confidence {b['confidence']:.0f}: {org.label(b['confidence'])}" + ("  FINAL WARNING" if b["warnings"] else ""))
        self.p("Objectives:")
        for ob in self.conn.execute("SELECT * FROM objectives WHERE team_id=? ORDER BY season_start_year DESC, "
                                    "objective_id LIMIT 12", (me,)):
            self.p(f"  {ob['season_start_year']} [{ob['importance']:<9}] {ob['description']:<60} {ob['status']}"
                   + (f" - {ob['result']}" if ob["result"] else ""))
        self.p("Reviews:")
        for h in self.conn.execute("SELECT * FROM board_history WHERE team_id=? ORDER BY rowid DESC LIMIT 6", (me,)):
            self.p(f"  {h['review_date']} {h['kind']:<8} {h['delta']:+5.1f} -> {h['confidence']:.0f}: "
                   + "; ".join(json.loads(h["reasons"])))

    def do_jobs(self, arg):
        "jobs: clubs looking for a GM, what they expect and your chances"
        self.need(allow_fired=True)
        from . import gm as GMx
        m = GMx.job_market(self.conn)
        self.p(f"Your reputation: {m['reputation']:.0f} ({m['label']})")
        for j in m["jobs"]:
            self.p(f"  {j['abbr']:<5}{j['name']:<28}projected {j['projected'] or '-':>2}  wants {j['demand']:>3}  chance {j['chance'] * 100:.0f}%")
        if not m["jobs"]:
            self.p("Nobody is looking for a GM right now.")

    def do_apply(self, arg):
        "apply <ABBR>: apply for a GM vacancy (when you are out of work); one interview per club a month"
        self.need(allow_fired=True)
        from . import gm as GMx
        t = self.team_by_abbr(arg.strip())
        ok = GMx.apply_job(self.conn, t, self.today())
        self.conn.commit()
        self.p(f"You are the new GM of {arg.strip().upper()}." if ok else f"{arg.strip().upper()} turned you down. Try again next month, or another club.")

    def do_gmrole(self, arg):
        "gmrole coach|gm: also coach the team yourself, or hand the bench to a head coach (hire one on the Staff screen)"
        self.need()
        from . import gm as GMx
        a = arg.strip().lower()
        if a == "coach":
            GMx.become_coach(self.conn, self.today())
            self.p("You are now the general manager and the head coach. Your previous coach is on the staff market.")
        elif a == "gm":
            GMx.step_down_as_coach(self.conn, self.today())
            self.p("You are the general manager only. Hire a head coach on the Staff screen.")
        else:
            raise ValueError("Usage: gmrole coach|gm")
        self.conn.commit()

    def do_improve(self, arg):
        "improve <rating>: spend a season's experience point on one of your ratings"
        self.need(allow_fired=True)
        from . import gm as GMx
        v = GMx.improve(self.conn, arg.strip().lower())
        self.conn.commit()
        self.p(f"{GMx.RATINGS[arg.strip().lower()][0]} is now {v}.")

    def do_ratings(self, arg):
        "ratings: your manager ratings, reputation and role"
        self.need(allow_fired=True)
        from . import gm as GMx
        s = GMx.settings(self.conn)
        for k, (label, what) in GMx.RATINGS.items():
            self.p(f"  {label:<18}{s['ratings'][k]:>3}  {what}")
        self.p(f"Reputation {s['reputation']:.0f} ({GMx.reputation_label(s['reputation'])}); role: {GMx.ROLES_GM[s['role']]}"
               + ("; cannot be fired" if s["unfireable"] else ""))

    def do_takejob(self, arg):
        "takejob <ABBR>: the same as apply (kept for older notes)"
        return self.do_apply(arg)

    def do_staff(self, arg):
        "staff: your hockey operations staff and what their quality means"
        me = self.need()
        from . import staff as S
        for r in S.members(self.conn, me):
            self.p(f"  #{r['staff_id']:<5}{S.ROLE_NAMES[r['role']]:<30}{r['name']:<22}age {r['age']:<3} "
                   f"coach {r['coaching']:>2} dev {r['development']:>2} eval {r['evaluation']:>2} med {r['medical']:>2} "
                   f"comm {r['communication']:>2} lead {r['leadership']:>2} {r['style'] or ''}")
        self.p(f"Scouting: draft estimates off by about {S.scout_sd(self.conn, me):.2f} rating points (league "
               f"default {0.75:.2f}); development speed x{S.development_multiplier(self.conn, me):.2f}; "
               f"injury length x{S.injury_multiplier(self.conn, me):.2f}")

    def do_staffmarket(self, arg):
        "staffmarket [ROLE]: available staff (roles: HC AC GC DEV SCOUT_DIR SCOUT MED ANALYTICS)"
        self.need()
        from . import staff as S
        role = arg.strip().upper() or None
        q = "SELECT * FROM staff WHERE team_id IS NULL" + (" AND role=?" if role else "")
        rows = self.conn.execute(q, (role,) if role else ()).fetchall()
        for r in sorted(rows, key=lambda r: -(r[S.MAIN_ATTR[r["role"]]]))[:20]:
            self.p(f"  #{r['staff_id']:<5}{S.ROLE_NAMES[r['role']]:<30}{r['name']:<22}{S.MAIN_ATTR[r['role']]} "
                   f"{r[S.MAIN_ATTR[r['role']]]:>2}  comm {r['communication']:>2}  rep {r['reputation']:>2}  "
                   f"${r['salary']:,.0f}")

    def do_hire(self, arg):
        "hire <staff id>: hire someone from the staff market"
        me = self.need()
        from . import staff as S
        S.hire(self.conn, me, int(arg.strip().lstrip("#")), self.today())
        self.conn.commit()
        self.p("Hired.")

    def do_dismiss(self, arg):
        "dismiss <staff id>: let a staff member go"
        me = self.need()
        from . import staff as S
        S.dismiss(self.conn, me, int(arg.strip().lstrip("#")), self.today())
        self.conn.commit()
        self.p("Dismissed.")

    def do_lockerroom(self, arg):
        "lockerroom: cohesion, leadership group, and the unhappiest players with the reasons"
        me = self.need()
        from . import events as E, people
        rm = people.room(self.conn, me)
        if rm:
            self.p(f"Atmosphere {rm['atmosphere']}: cohesion {rm['cohesion']:.0f}, leadership {rm['leadership_strength']:.1f}/20"
                   + (f"  ({'; '.join(json.loads(rm['reasons']))})" if rm["reasons"] else ""))
        for l in self.conn.execute("SELECT * FROM leadership WHERE team_id=? ORDER BY role DESC", (me,)):
            self.p(f"  {l['role']}  {E.player_name(self.conn, l['player_id'])}")
        self.p("Lowest morale:")
        for r in people.unhappy(self.conn, me, 8):
            self.p(f"  {r['n']:<24} morale {r['morale']:>4.0f}  lowest: {people.explain(r)}"
                   + ("  TRADE REQUEST" if r["trade_request"] else ""))

    def do_captain(self, arg):
        "captain <player>: name a new captain (the old one may take it badly)"
        me = self.need()
        from . import people
        r = self.find(arg, "team_id=? AND status IN ('active','injured')", (me,))
        from . import captaincy
        cur = captaincy.current(self.conn, me)
        old_c = [p for p, role in cur.items() if role == "C"]
        alts = [p for p in old_c + [p for p, role in cur.items() if role == "A"] if p != r["player_id"]][:2]
        captaincy.apply(self.conn, me, r["player_id"], alts, self.today())
        self.conn.commit()
        self.p(f"{r['first_name']} {r['last_name']} is your new captain.")

    def do_talk(self, arg):
        "talk <player>: hear a player's concern and the ways you can respond"
        me = self.need()
        from . import people
        r = self.find(arg, "team_id=?", (me,))
        tr = people.traits(self.conn, r["player_id"])
        m = self.conn.execute("SELECT * FROM morale WHERE player_id=?", (r["player_id"],)).fetchone()
        self.p(f"{r['first_name']} {r['last_name']}: morale {m['morale']:.0f} (lowest: {people.explain(m)})")
        self.p("Personality: " + ", ".join(f"{k} {tr[k]}" for k in people.TRAITS))
        c = self.conn.execute("SELECT * FROM concerns WHERE team_id=? AND player_id=? AND status='open' ORDER BY "
                              "raised_on LIMIT 1", (me, r["player_id"])).fetchone()
        if c is None:
            self.p("He has nothing pressing to discuss.")
            return
        self.p(f"Concern: he {c['detail']} (raised {c['raised_on']}).")
        _, desc, _, deadline, _ = people.promise_terms(self.conn, r["player_id"], c["topic"], self.today())
        self.p("Respond with `respond <player> <approach>`:")
        self.p("  supportive   reassure him (works less each time you repeat it without acting)")
        self.p("  direct       be candid about where he stands (suits professionals, stings big egos)")
        self.p("  firm         restate the club's standard and close the topic")
        self.p("  diplomatic   non-committal; buys about three weeks")
        self.p(f"  promise      BINDING: promise {desc}. Breaking it costs trust, and more if he is a leader.")

    def do_respond(self, arg):
        "respond <player> <supportive|direct|firm|diplomatic|promise>"
        me = self.need()
        from . import people
        toks = arg.split()
        if len(toks) < 2:
            raise ValueError("Usage: respond <player> <approach>")
        r = self.find(" ".join(toks[:-1]), "team_id=?", (me,))
        text, promise = people.respond(self.conn, me, r["player_id"], toks[-1].lower(), self.today())
        self.p(text)
        if promise:
            self.p(f"Promise recorded: {promise}.")

    def do_note(self, arg):
        "note [add <text> | about <player id> <text> | club <team abbr> <text> | edit <id> <text> | del <id>]: your notebook"
        self.need()
        from . import notes as N
        verb, _, rest = arg.strip().partition(" ")
        if verb in ("", "list"):
            rows = N.notes(self.conn)
            for n in rows:
                self.p(f"  #{n['note_id']:<4}{n['created']}  {n['text'][:90]}")
            if not rows:
                self.p("No notes.")
            return
        if verb == "add":
            i = N.add_note(self.conn, self.today(), rest)
        elif verb == "about":
            pid, _, text = rest.partition(" ")
            r = self.find(pid)
            i = N.add_note(self.conn, self.today(), text, player_id=r["player_id"])
        elif verb == "club":
            ab, _, text = rest.partition(" ")
            t = self.conn.execute("SELECT team_id FROM teams WHERE abbr=?", (ab.upper(),)).fetchone()
            if not t:
                raise ValueError(f"No club {ab}.")
            i = N.add_note(self.conn, self.today(), text, team_id=t[0])
        elif verb == "edit":
            nid, _, text = rest.partition(" ")
            N.edit_note(self.conn, int(nid), text)
            i = int(nid)
        elif verb in ("del", "delete"):
            N.delete_note(self.conn, int(rest))
            self.conn.commit()
            self.p("Note deleted.")
            return
        else:
            raise ValueError("Usage: note add <text> | about <player id> <text> | club <abbr> <text> | edit <id> <text> | del <id>")
        self.conn.commit()
        self.p(f"Note #{i} saved.")

    def do_shortlist(self, arg):
        "shortlist [add <player> [reason] | del <player>]: the players you are watching"
        self.need()
        from . import notes as N
        verb, _, rest = arg.strip().partition(" ")
        if verb in ("", "list"):
            rows = N.shortlist(self.conn)
            for s in rows:
                from . import events as E
                self.p(f"  {s['added']}  {E.player_name(self.conn, s['player_id']):<26}{s['reason'] or ''}")
            if not rows:
                self.p("Your short list is empty.")
            return
        pid, _, reason = rest.partition(" ")
        r = self.find(pid)
        if verb == "add":
            N.shortlist_add(self.conn, self.today(), r["player_id"], reason)
            self.p(f"{r['first_name']} {r['last_name']} is on your short list.")
        elif verb in ("del", "remove"):
            N.shortlist_remove(self.conn, r["player_id"])
            self.p(f"{r['first_name']} {r['last_name']} is off your short list.")
        else:
            raise ValueError("Usage: shortlist add <player> [reason] | del <player>")
        self.conn.commit()

    def do_promises(self, arg):
        "promises [all]: your active promises (or all, with outcomes)"
        me = self.need()
        from . import events as E
        q = "SELECT * FROM promises WHERE team_id=?" + ("" if "all" in arg else " AND status='active'") +             " ORDER BY made_on DESC"
        rows = self.conn.execute(q, (me,)).fetchall()
        for p in rows:
            self.p(f"  {p['made_on']}  {E.player_name(self.conn, p['player_id']):<24}{p['status']:<10}"
                   f"{p['description']}" + (f" - {p['note']}" if p["note"] else ""))
        if not rows:
            self.p("No promises.")

    def do_quit(self, arg):
        "quit: leave (everything is already saved)"
        return True

    do_EOF = do_quit


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db")
    ap.add_argument("--env", required=True)
    ap.add_argument("-c", action="append", help="command to run (repeatable)")
    a = ap.parse_args(argv)
    cli = CLI(a.db, json.load(open(a.env)))
    if a.c:
        for c in a.c:
            if cli.onecmd(c):
                break
        return cli.status_code
    cli.cmdloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
