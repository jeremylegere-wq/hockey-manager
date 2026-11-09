"""The sim centre: time advances one day at a time in a background thread, so the UI can show what is happening
around the league (scores, your game's box score, standings, trades and injuries) and the user can stop it.

    POST /api/sim      {"mode": "day"|"week"|"next"|"season"|"until", "pace": seconds per day, "until": "YYYY-MM-DD"}
    GET  /api/simstatus?since=<n>   -> {running, mode, day, done_days, target_days, feed[n:], finished, stopped, lines}
    POST /api/simstop

Each day is simulated under the game lock with the same hs.game.dayloop.sim_until the CLI's `sim` uses (one day at
a time), so stop conditions are the CLI's: `day` 1, `week` 7, `next` through your next game, `season` to the end
(playoffs included). Like the CLI, anything but `season` stops early when you are needed (an injury to one of your
players, a shortage at a position, a trade offer). Between days the lock is free, so every other screen still reads.
"""
from __future__ import annotations

import datetime
import threading
import time

from ..game import contracts as K
from ..game import events as E
from ..game.dayloop import remaining, sim_until
from ..game.state import get_state, user_team

TARGET = {"day": 1, "week": 7}
FEED_KEEP = 400


def _ab(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT team_id, abbr FROM teams")}


def _box(conn, gid, me):
    """A compact box score of one game (your team's) for the flash card."""
    from ..game import media as M
    r = M.recap(conn, gid)
    g = conn.execute("SELECT home_team_id, away_team_id FROM games WHERE game_id=?", (gid,)).fetchone()
    top = []
    for row in conn.execute("SELECT s.player_id, s.team_id, s.goals, s.assists, s.shots, s.toi_sec, s.saves, "
                            "s.shots_against, p.first_name, p.last_name, p.position FROM player_game_stats s JOIN "
                            "players p USING (player_id) WHERE s.game_id=? ORDER BY (s.goals+s.assists) DESC, "
                            "s.goals DESC, s.shots DESC", (gid,)):
        top.append(dict(player_id=row["player_id"], team=row["team_id"], name=f"{row['first_name'][0]}. {row['last_name']}",
                        pos=row["position"], g=row["goals"], a=row["assists"], sog=row["shots"],
                        toi=row["toi_sec"], sv=row["saves"], sa=row["shots_against"]))
    goalies = [t for t in top if t["pos"] == "G" and t["sa"]]
    skaters = [t for t in top if t["pos"] != "G"]
    return dict(game_id=gid, home=r["home"], away=r["away"], home_goals=r["home_goals"], away_goals=r["away_goals"],
                ot=r["ot"], headline=r["headline"], lede=r["lede"], periods=r["periods"], line=r["line"],
                goals=r["goals"][-8:], stars=r["stars"], mine_home=g["home_team_id"] == me,
                home_id=g["home_team_id"], away_id=g["away_team_id"],
                skaters={tid: [s for s in skaters if s["team"] == tid][:5] for tid in (g["home_team_id"], g["away_team_id"])},
                goalies=goalies)


def _mini_standings(conn, me):
    from . import api
    try:
        return api.standings_full(conn, "wildcard", only_conf_of=me)
    except Exception:                                  # standings are decoration here; never stop the sim for them
        return None


def day_entry(conn, s, me):
    ab = _ab(conn)
    scores = [dict(game_id=gid, home=ab[h], away=ab[a], hg=hg, ag=ag, ot={1: "OT", 2: "SO"}.get(ot, ""),
                   mine=me in (h, a)) for gid, h, a, hg, ag, ot in s.results]
    mine = next((x for x in scores if x["mine"]), None)
    # v39 (#20, #8): one line per trade (not one per player moved as well), a waiver claim is labelled as one
    label = lambda e: "WAIVER_CLAIM" if e["event_type"] == "PLAYER_SIGNED" and '"waiver_claim"' in (e["payload"] or "") \
        else e["event_type"]
    news = [dict(type=label(e), text=e["summary"], team=ab.get(e["team_id"], ""), player_id=e["player_id"],
                 mine=e["team_id"] == me or e["other_team_id"] == me)
            for e in conn.execute("SELECT * FROM league_events WHERE event_date=? AND importance>=2 AND event_type NOT IN "
                                  "('GAME_RESULT', 'PLAYER_TRADED') ORDER BY importance DESC, event_id LIMIT 12", (s.day,))]
    alerts = []
    for pid, t, d in s.injuries:
        if t == me:
            alerts.append(f"Injury: {E.player_name(conn, pid)} out {d} day(s)")
    alerts += [f"Trade: {t}" for t in s.trades if ab.get(me, "?") in t]
    if "trade_offer" in s.user_alerts:
        alerts.append("A club has made you a trade offer (Trade screen)")
    alerts += [f"Short at {x.split(':')[1]}" for x in s.user_alerts if x.startswith("short")]
    alerts += [f"Press conference: {k.replace('_', ' ')} (Press room)" for k in getattr(s, "press", [])]
    if "board" in s.user_alerts:
        alerts.append("A message from the owner's office (Inbox)")
    deadline_days = None
    try:
        from ..game import trades as TR
        import datetime as _dt
        deadline_days = (TR.deadline(conn) - _dt.date.fromisoformat(s.day)).days
        if deadline_days == 3:
            alerts.append("The trade deadline is in 3 days: clubs are calling (Trade screen)")
        elif deadline_days == 0:
            alerts.append("Trade deadline day: last chance to deal (Trade screen)")
    except Exception:
        deadline_days = None
    return dict(day=s.day, scores=scores, mine=_box(conn, mine["game_id"], me) if mine else None, news=news,
                alerts=alerts, trades=list(s.trades), press=list(getattr(s, "press", [])), standings=_mini_standings(conn, me) if scores else None,
                finished=bool(getattr(s, "season_finished", False)), deadline_days=deadline_days)


def conn_has_room_msg(g, day):
    try:
        return bool(g.cli.conn.execute("SELECT 1 FROM inbox WHERE date=? AND subject='Trouble in the room'", (day,)).fetchone())
    except Exception:
        return False


class SimJob:
    def __init__(self, game):
        self.game = game
        self.thread = None
        self.reset()

    def reset(self):
        self.mode, self.running, self.stop_flag = None, False, False
        self.feed, self.base = [], 0
        self.done_days, self.target, self.lines, self.finished, self.stopped, self.error = 0, None, [], False, False, None
        self.pace = 0.0
        self.until = None
        self.stop_reason = None

    @property
    def busy(self):
        return self.running

    def start(self, mode, pace=0.6, until=None):
        if self.running:
            raise RuntimeError("A simulation is already running.")
        g = self.game
        with g.lock:
            conn = g.cli.conn
            me = user_team(conn)
            from ..game import gm as GMx
            if me is None and not GMx.unemployed(conn):
                raise RuntimeError("No game loaded.")
            if mode not in ("day", "week", "next", "season", "until"):
                raise ValueError("mode is day, week, next, season or until")
            if mode == "until":                     # Play > Play until a date (or an event's date): like the rest of season, to a day
                try:
                    until = datetime.date.fromisoformat(str(until)[:10]).isoformat()
                except ValueError:
                    raise ValueError("Pick a date to play until.")
                if until <= get_state(conn)[0]:
                    raise ValueError("Pick a date after today.")
            if K.season_state(conn) != "regular_season":
                raise RuntimeError("Simulation runs in the regular season; in the summer use Next offseason phase.")
            if remaining(conn) == 0:
                raise RuntimeError("The season is finished.")
            total = remaining(conn)
            # rough number of days left for the progress bar (games left / games per day so far)
            last = conn.execute("SELECT MAX(game_date) FROM games WHERE game_type='RS'").fetchone()[0]
            days_left = (datetime.date.fromisoformat(last) - datetime.date.fromisoformat(get_state(conn)[0])).days
        self.reset()
        self.mode, self.running, self.pace = mode, True, max(0.0, min(5.0, float(pace)))
        self.target = TARGET.get(mode) or (max(1, days_left) if mode == "season" else None)
        self.until = until if mode == "until" else None
        if self.until:
            self.target = max(1, (datetime.date.fromisoformat(self.until) - datetime.date.fromisoformat(get_state(g.cli.conn)[0])).days)
        self._games_left = total
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self.status(0)

    def stop(self):
        self.stop_flag = True
        return dict(ok=True)

    def _run(self):
        g = self.game
        try:
            from . import settings as ST
            stops = ST.load(g.settings_path()) if hasattr(g, "settings_path") else {}
            while not self.stop_flag:
                t0 = time.time()
                with g.lock:
                    conn = g.cli.conn
                    me = user_team(conn)
                    if not remaining(conn) or K.season_state(conn) != "regular_season":
                        break
                    out = sim_until(conn, g.cli.env, g.cli.skill, me, days=1, to_end=self.mode in ("season", "until"))
                    conn.commit()
                    g.rolling_backup()
                    if not out:
                        break
                    s = out[-1]
                    entry = day_entry(conn, s, me)
                    if s.season_finished or K.season_state(conn) == "finished":
                        entry["finished"] = True
                        champ = conn.execute("SELECT value FROM pack_info WHERE key='champion'").fetchone()
                        if champ:
                            t = conn.execute("SELECT name, nickname FROM teams WHERE team_id=?", (int(champ[0]),)).fetchone()
                            entry["champion"] = f"{t['name']} {t['nickname'] or ''}".strip()
                            self.lines.append(f"Season finished. Champion: {entry['champion']}")
                self.feed.append(entry)
                if len(self.feed) > FEED_KEEP:
                    drop = len(self.feed) - FEED_KEEP
                    self.feed, self.base = self.feed[drop:], self.base + drop
                self.done_days += 1
                self.lines += entry["alerts"]
                if entry["finished"]:
                    self.finished = True
                    break
                if self.mode in TARGET and self.done_days >= TARGET[self.mode]:
                    break
                if self.mode == "next" and entry["mine"]:
                    break
                if self.until and (datetime.date.fromisoformat(s.day) + datetime.timedelta(days=1)).isoformat() >= self.until:
                    break
                if self.mode not in ("season", "until") and (s.user_alerts or entry["alerts"] or entry["press"]):
                    self.stop_reason = (entry["alerts"] or ["Something needs you"])[0]
                    break
                # v38: what stops "rest of season" and "play until" is yours to choose (Settings)
                from ..game.press import MAJOR
                reason = None
                if stops.get("stop_press", True) and any(k in MAJOR for k in entry["press"]):
                    reason = "A major press conference is waiting (Press room)"
                elif stops.get("stop_trade_offer", True) and "trade_offer" in s.user_alerts:
                    reason = "A club has made you a trade offer (Inbox)"
                elif stops.get("stop_board", True) and "board" in s.user_alerts:
                    reason = "The owner's office has written (Inbox)"
                elif stops.get("stop_deadline", True) and entry.get("deadline_days") in (3, 0):
                    reason = "The trade deadline is close (Trade screen)"
                elif stops.get("stop_injury") and any(x.startswith("injury:") for x in s.user_alerts):
                    reason = next(a for a in entry["alerts"] if a.startswith("Injury")) if any(a.startswith("Injury") for a in entry["alerts"]) else "An injury"
                elif stops.get("stop_room") and conn_has_room_msg(g, s.day):
                    reason = "Trouble in the dressing room (Inbox)"
                if reason:
                    self.stop_reason = reason
                    break
                wait = self.pace - (time.time() - t0)
                if wait > 0:
                    time.sleep(wait)
            self.stopped = self.stop_flag
        except Exception as e:                           # report in the status; the save stays consistent per day
            self.error = str(e)
        finally:
            self.running = False

    def status(self, since=0):
        since = max(0, int(since) - self.base)
        return dict(running=self.running, mode=self.mode, done_days=self.done_days, target_days=self.target,
                    feed=self.feed[since:], next=self.base + len(self.feed), finished=self.finished,
                    stopped=self.stopped, error=self.error, lines=self.lines[-20:], pace=self.pace, until=self.until,
                    stop_reason=self.stop_reason)
