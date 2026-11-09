"""Playing hurt and mutual termination (phase D, v35).

Playing hurt (injury deferral). A player out with a minor injury (three weeks or less to go, not on LTIR) can play
through it: he is back in the lineup now, 0.35 sd below himself in offence, defence and finishing until the day he
would have been back. Each game he plays hurt, 8% (more for the injury-prone, hs/game/hidden.py) that it gets worse:
he is out again for the time that was left plus a week to three. CLI: `playhurt <player>`; `rest <player>` sits him
until he is healed.

Mutual termination. You and a player agree to tear up his contract: no buyout, no cap charge, he becomes a free
agent, and the club pays him a settlement in cash (hs/game/finance.py) of 10-40% of what is left. He agrees when
leaving suits him: he is 27 or older and unhappy with his role, or barely playing, or a veteran past his best; loyal
players and players who like the city are slower to agree, greedy ones want more. CLI: `terminate <player>` asks him
(one ask a month); the answer and his price come back at once.
"""
from __future__ import annotations

import datetime
import random

from . import contracts as K
from .events import emit, player_name, team_abbr
from .state import add_message, get_state, user_team

AGGRAVATE = 0.08
MAX_DAYS = 21


def ensure(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(injuries)")}
    if "playing_hurt" not in cols:
        conn.execute("ALTER TABLE injuries ADD COLUMN playing_hurt INTEGER DEFAULT 0")


def _current_injury(conn, pid):
    return conn.execute("SELECT * FROM injuries WHERE player_id=? ORDER BY injury_id DESC LIMIT 1", (pid,)).fetchone()


def play_hurt(conn, t, pid, day):
    ensure(conn)
    p = conn.execute("SELECT team_id, status FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] != t:
        raise ValueError("He is not on your club.")
    if p["status"] == "ltir":
        raise ValueError("He is on long-term injured reserve: activate him first, when he is healthy.")
    if p["status"] != "injured":
        raise ValueError("He is not injured.")
    inj = _current_injury(conn, pid)
    left = (datetime.date.fromisoformat(inj["expected_return"]) - datetime.date.fromisoformat(day)).days
    if left > MAX_DAYS:
        raise ValueError(f"He has {left} days to go: only an injury with three weeks or less left can be played through.")
    conn.execute("UPDATE injuries SET playing_hurt=1 WHERE injury_id=?", (inj["injury_id"],))
    conn.execute("UPDATE players SET status='active' WHERE player_id=?", (pid,))
    emit(conn, "PLAYER_INJURED", day, f"{player_name(conn, pid)} will play through his injury", team_id=t, player_id=pid, importance=1, days=0)
    return left


def rest(conn, t, pid, day):
    ensure(conn)
    inj = _current_injury(conn, pid)
    if inj is None or not inj["playing_hurt"] or inj["expected_return"] <= day:
        raise ValueError("He is not playing hurt.")
    conn.execute("UPDATE injuries SET playing_hurt=0 WHERE injury_id=?", (inj["injury_id"],))
    conn.execute("UPDATE players SET status='injured' WHERE player_id=? AND team_id=?", (pid, t))


def after_games(conn, day, played):
    """After the day's games: players playing hurt who played may get worse; the healed stop playing hurt."""
    ensure(conn)
    from . import hidden as HD
    played = set(played)
    for inj in conn.execute("SELECT * FROM injuries WHERE playing_hurt=1").fetchall():
        if inj["expected_return"] <= day:
            conn.execute("UPDATE injuries SET playing_hurt=0 WHERE injury_id=?", (inj["injury_id"],))
            continue
        pid = inj["player_id"]
        if pid not in played:
            continue
        rng = random.Random(f"{get_state(conn)[1]}-{day}-hurt-{pid}")
        if rng.random() >= AGGRAVATE * HD.injury_factor(HD.of(conn, pid)["injury_proneness"]):
            continue
        left = (datetime.date.fromisoformat(inj["expected_return"]) - datetime.date.fromisoformat(day)).days
        extra = left + rng.randint(7, 21)
        ret = (datetime.date.fromisoformat(day) + datetime.timedelta(days=extra)).isoformat()
        conn.execute("UPDATE injuries SET playing_hurt=0, expected_return=?, description=? WHERE injury_id=?",
                     (ret, f"{inj['description']}, aggravated", inj["injury_id"]))
        t = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
        conn.execute("UPDATE players SET status='injured' WHERE player_id=?", (pid,))
        emit(conn, "PLAYER_INJURED", day, f"{player_name(conn, pid)} aggravates his injury playing through it, out about {extra} days",
             team_id=t, player_id=pid, importance=2, days=extra)
        if t == user_team(conn):
            add_message(conn, day, "Injury aggravated", f"{player_name(conn, pid)} made his injury worse playing through it. "
                                                       f"He is out again, about {extra} days (back {ret}).")


# ---------------------------------------------------------------- mutual termination
def _remaining(conn, pid):
    year = K.season_year(conn)
    c = K.current_contract(conn, pid, year)
    if c is None:
        return None, 0, 0
    left = c["start_year"] + c["years"] - year
    return c, left, c["cap_hit"] * left


def terms(conn, pid):
    """(willing: bool, settlement $, why) - would he agree, and for how much."""
    from .people import traits
    from . import hidden as HD
    from .roster import player_value
    c, left, owed = _remaining(conn, pid)
    if c is None:
        return False, 0, "He has no contract to end."
    if c["contract_type"] == "entry_level":
        return False, 0, "Entry-level contracts cannot be terminated."
    p = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    on = datetime.date.fromisoformat(get_state(conn)[0])
    b = datetime.date.fromisoformat(p["birth_date"])
    age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
    tr, h = traits(conn, pid), HD.of(conn, pid)
    m = conn.execute("SELECT morale, role, trade_request FROM morale WHERE player_id=?", (pid,)).fetchone()
    role = m["role"] if m else 60
    val = player_value(conn, pid)
    reasons = []
    score = 0.0
    if age >= 27:
        score += 1
    if role < 45:
        score += 1.5
        reasons.append("unhappy with his role")
    if m and m["trade_request"]:
        score += 1.5
        reasons.append("wants out")
    if age >= 33 and val < 50:
        score += 1
        reasons.append("past his best and knows it")
    score -= (tr["loyalty"] - 10) * 0.12
    if score < 1.8:
        return False, 0, "He wants to see his contract through." + (" He is loyal to the club." if tr["loyalty"] >= 14 else "")
    share = max(0.10, min(0.40, 0.25 + 0.02 * (h["greed"] - 10) - 0.04 * (score - 2)))
    return True, int(round(owed * share, -4)), ", ".join(reasons) or "ready for a fresh start"


def terminate(conn, t, pid, day):
    """Ask him; if he agrees, the contract ends now. Returns (agreed, settlement, why). One ask a month."""
    p = conn.execute("SELECT team_id FROM players WHERE player_id=?", (pid,)).fetchone()
    if p is None or p["team_id"] != t:
        raise ValueError("He is not on your club.")
    key = f"terminate_ask_{pid}_{day[:7]}"
    if conn.execute("SELECT 1 FROM pack_info WHERE key=?", (key,)).fetchone():
        raise ValueError("You already asked him this month.")
    conn.execute("INSERT INTO pack_info (key, value) VALUES (?, '1')", (key,))
    ok, pay, why = terms(conn, pid)
    if not ok:
        return False, 0, why
    c, left, owed = _remaining(conn, pid)
    year = K.season_year(conn)
    if year - c["start_year"] <= 0:
        conn.execute("DELETE FROM contracts WHERE contract_id=?", (c["contract_id"],))
    else:
        conn.execute("UPDATE contracts SET years=? WHERE contract_id=?", (year - c["start_year"], c["contract_id"]))
    conn.execute("UPDATE players SET team_id=NULL, club_id=NULL, status='active' WHERE player_id=?", (pid,))
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, from_team_id, to_team_id, detail) VALUES (?, 'release', ?, ?, NULL, ?)",
                 (day, pid, t, f"contract terminated by mutual agreement (settlement ${pay:,.0f})"))
    conn.execute("DELETE FROM leadership WHERE player_id=?", (pid,))
    try:
        from . import finance as FN
        FN.setup(conn)
        FN._post(conn, t, day, "settlement", -pay, f"{player_name(conn, pid)}: mutual termination")
    except Exception:
        pass
    emit(conn, "PLAYER_RELEASED", day, f"{team_abbr(conn, t)} and {player_name(conn, pid)} agree to terminate his contract",
         team_id=t, player_id=pid, importance=2)
    return True, pay, why
