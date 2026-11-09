"""Jersey numbers and the player picture (v49; docs/NUMBERS.md).

Numbers
  * every player at a club wears a number from 1 to 98, unique within the club he plays for (an NHL roster, an AHL
    club, a junior team); 99 is retired league-wide, and a club's own retired numbers are off limits there
  * a world built from the database starts with the database's squad numbers; anyone without one, or who clashes
    with a teammate after a trade, signing or call-up, gets one: the one he wore if it is free, else one by position
    (goalies 30, 31, 35, 1, 29...; defencemen 2-8, 44, 55, 77...; forwards 9-29, 91...), else the lowest free
  * when two teammates want the same number the one who has been at the club longer keeps it
  * you change your players' numbers on the player screen or the roster (`number <player> <n>`); if a teammate
    wears it you can swap (`number <player> <n> swap`). With commissioner mode on you can change anyone's.
  * a club retires a number for a player who gave it 300+ games or is in the Hall of Fame (`number retire <n> <player>`;
    your club only, or any club in commissioner mode); whoever wears it now keeps it until he leaves
The picture: your own photo files (faces folder next to your saves, named by player id: 12345.png / .jpg / .webp) or a
pack's headshot path; without one, the back of his jersey: club colours, his name and number.
"""
from __future__ import annotations

import datetime
import html

from .events import emit, player_name, team_abbr
from .state import get_state, user_team

LEAGUE_RETIRED = {99}
PREFERRED = {"G": [30, 31, 35, 1, 29, 33, 34, 40, 39, 32, 37, 41, 50, 60, 70, 80],
             "D": [2, 3, 4, 5, 6, 7, 8, 44, 55, 77, 22, 24, 27, 28, 25, 26, 47, 58, 74, 76, 86],
             "F": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 91, 88, 71, 92, 93, 81, 63, 67, 89, 97]}
RETIRE_GAMES = 300
# the crest palette (hs/ui/static/classic.js CREST_COLOURS): the same club gets the same colours on a jersey
PALETTE = [["#b3122e", "#0d2b5c"], ["#0b4ea2", "#e8b70e"], ["#00543d", "#c8c9c7"], ["#f47a38", "#1a1a1a"], ["#6f263d", "#236192"],
           ["#002654", "#c8102e"], ["#111111", "#fcb514"], ["#041e42", "#a2aaad"], ["#ce1126", "#111111"], ["#006847", "#8f8f8c"], ["#00205b", "#ff4c00"],
           ["#5f259f", "#f2a900"], ["#c8102e", "#ffffff"], ["#003e7e", "#ffb81c"], ["#00468b", "#97999b"], ["#4b2a7b", "#c4ced4"], ["#a6192e", "#eaaa00"],
           ["#001e62", "#c8102e"], ["#006d75", "#e57200"], ["#2c5234", "#a4a9ad"], ["#99d9d9", "#001628"], ["#782f40", "#63666a"], ["#0038a8", "#ffffff"],
           ["#d2001c", "#ffd100"], ["#111111", "#a2aaad"], ["#002868", "#bf0d3e"], ["#e03a3e", "#00205b"], ["#5e1a33", "#d6d2c4"], ["#007a33", "#ffffff"],
           ["#1c3f94", "#d1d3d4"], ["#8a0f2c", "#111111"], ["#00843d", "#ffcd00"]]


def _group(pos):
    return "G" if pos == "G" else "D" if pos == "D" else "F"


def ensure(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(players)")}
    if "jersey_number" not in cols:
        conn.execute("ALTER TABLE players ADD COLUMN jersey_number INTEGER")
    conn.execute("CREATE TABLE IF NOT EXISTS retired_numbers (team_id INTEGER, number INTEGER, player_id INTEGER, name TEXT, "
                 "season INTEGER, PRIMARY KEY (team_id, number))")
    conn.execute("CREATE TABLE IF NOT EXISTS number_since (player_id INTEGER PRIMARY KEY, club_id INTEGER, since TEXT)")


def _retired(conn, club):
    out = set(LEAGUE_RETIRED)
    if club is None:
        return out
    org = conn.execute("SELECT COALESCE(parent_team_id, team_id) FROM teams WHERE team_id=?", (club,)).fetchone()
    for (n,) in conn.execute("SELECT number FROM retired_numbers WHERE team_id IN (?, ?)", (club, org[0] if org else club)):
        out.add(n)
    return out


def _club_of(conn, pid):
    r = conn.execute("SELECT COALESCE(club_id, CASE WHEN status IN ('active','injured','ltir') THEN team_id END) FROM players "
                     "WHERE player_id=?", (pid,)).fetchone()
    return r[0] if r else None


def taken(conn, club, but=None):
    return {r[0] for r in conn.execute("SELECT jersey_number FROM players WHERE COALESCE(club_id, CASE WHEN status IN "
                                       "('active','injured','ltir') THEN team_id END)=? AND status<>'retired' AND jersey_number IS NOT NULL "
                                       "AND player_id<>?", (club, but or -1))}


def pick(pos, used, retired, prefer=None):
    bad = used | retired
    if prefer and 1 <= prefer <= 98 and prefer not in bad:
        return prefer
    for n in PREFERRED[_group(pos)]:
        if n not in bad:
            return n
    return next((n for n in range(2, 99) if n not in bad), None)


def fix(conn, day=None, clubs=None):
    """Give a number to everyone at a club without one and settle clashes (the longer-serving player keeps it).
    Returns the number of players given a new number."""
    ensure(conn)
    day = day or (get_state(conn) or [datetime.date.today().isoformat()])[0]
    club_expr = "COALESCE(p.club_id, CASE WHEN p.status IN ('active','injured','ltir') THEN p.team_id END)"
    since = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT player_id, club_id, since FROM number_since")}
    # clubs with a clash, or with someone unnumbered
    where = f"{club_expr} IS NOT NULL AND p.status<>'retired'"
    if clubs:
        where += f" AND {club_expr} IN ({','.join(str(int(c)) for c in clubs)})"
    bad = {r[0] for r in conn.execute(f"SELECT {club_expr} c FROM players p WHERE {where} GROUP BY c, p.jersey_number "
                                      "HAVING COUNT(*) > 1 OR p.jersey_number IS NULL")}
    bad |= {r[0] for r in conn.execute(f"SELECT DISTINCT {club_expr} FROM players p WHERE {where} AND p.jersey_number IS NULL")}
    n = 0
    for club in bad:
        rows = conn.execute(f"SELECT p.player_id, p.position, p.jersey_number FROM players p WHERE {club_expr}=? AND p.status<>'retired'",
                            (club,)).fetchall()
        retired = _retired(conn, club)

        def tenure(r):
            s = since.get(r[0])
            return s[1] if s and s[0] == club else "9999"
        used = set()
        for pid, pos, num in sorted(rows, key=lambda r: (r[2] is None, tenure(r), r[0])):
            if num is not None and num not in used and num not in retired and 1 <= num <= 98:
                used.add(num)
                continue
            new = pick(pos, used, retired, num)
            if new is None:
                continue
            used.add(new)
            conn.execute("UPDATE players SET jersey_number=? WHERE player_id=?", (new, pid))
            n += 1
    # who is where since when (for the next clash)
    cur = {r[0]: r[1] for r in conn.execute(f"SELECT p.player_id, {club_expr} FROM players p WHERE {where}")}
    rows = [(pid, club, day) for pid, club in cur.items() if since.get(pid, (None,))[0] != club]
    if rows:
        conn.executemany("INSERT OR REPLACE INTO number_since VALUES (?,?,?)", rows)
    return n


def set_number(conn, pid, n, swap=False):
    ensure(conn)
    from . import editor
    me = user_team(conn)
    r = conn.execute("SELECT team_id, position, jersey_number FROM players WHERE player_id=?", (pid,)).fetchone()
    if r is None:
        raise ValueError("No such player.")
    if r[0] != me and not editor.enabled(conn):
        raise ValueError("You can change the numbers of your own players (or anyone's in commissioner mode).")
    try:
        n = int(str(n).strip().lstrip("#"))
    except ValueError:
        raise ValueError("A number from 1 to 98.")
    if not 1 <= n <= 98:
        raise ValueError("A number from 1 to 98 (99 is retired league-wide; 0 and 00 are not allowed).")
    club = _club_of(conn, pid)
    if club is None:
        raise ValueError("He is not with a club.")
    if n in _retired(conn, club):
        who = conn.execute("SELECT name FROM retired_numbers WHERE number=? AND team_id IN (?, (SELECT COALESCE(parent_team_id, team_id) "
                           "FROM teams WHERE team_id=?))", (n, club, club)).fetchone()
        raise ValueError(f"#{n} is retired" + (f" (for {who[0]})" if who else " league-wide") + ".")
    if n == r[2]:
        return f"{player_name(conn, pid)} already wears #{n}."
    mate = conn.execute("SELECT player_id FROM players WHERE jersey_number=? AND player_id<>? AND status<>'retired' AND "
                        "COALESCE(club_id, CASE WHEN status IN ('active','injured','ltir') THEN team_id END)=?", (n, pid, club)).fetchone()
    if mate and not swap:
        raise ValueError(f"{player_name(conn, mate[0])} wears #{n}. Swap numbers with him, or choose another.")
    if mate:
        if r[2] is None:
            raise ValueError("He has no number to swap.")
        conn.execute("UPDATE players SET jersey_number=? WHERE player_id=?", (r[2], mate[0]))
    conn.execute("UPDATE players SET jersey_number=? WHERE player_id=?", (n, pid))
    day = get_state(conn)[0]
    conn.execute("INSERT INTO transactions (txn_date, txn_type, player_id, to_team_id, detail) VALUES (?, 'number', ?, ?, ?)",
                 (day, pid, club, f"now wears #{n}" + (f" (swapped with {player_name(conn, mate[0])})" if mate else "")))
    return f"{player_name(conn, pid)} now wears #{n}" + (f"; {player_name(conn, mate[0])} takes #{r[2]}" if mate else "") + "."


def retire(conn, team, n, pid):
    """Retire a number at a club for a player who gave it 300+ games or is in the Hall of Fame."""
    ensure(conn)
    from . import editor
    me = user_team(conn)
    if team != me and not editor.enabled(conn):
        raise ValueError("You can retire numbers at your own club (or any club in commissioner mode).")
    n = int(n)
    if not 1 <= n <= 98:
        raise ValueError("A number from 1 to 98.")
    if conn.execute("SELECT 1 FROM retired_numbers WHERE team_id=? AND number=?", (team, n)).fetchone():
        raise ValueError(f"#{n} is already retired at {team_abbr(conn, team)}.")
    gp = sum((conn.execute(f"SELECT COALESCE(SUM(gp), 0) FROM {t} WHERE player_id=? AND team_id=? AND split='RS'", (pid, team)).fetchone()[0])
             for t in ("skater_season_stats", "goalie_season_stats"))
    hof = conn.execute("SELECT 1 FROM hall_of_fame WHERE player_id=?", (pid,)).fetchone() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='hall_of_fame'").fetchone() else None
    if gp < RETIRE_GAMES and not hof and not editor.enabled(conn):
        raise ValueError(f"{player_name(conn, pid)} played {gp} games for the club: a number is retired for {RETIRE_GAMES}+ games "
                         "or a Hall of Famer.")
    from .contracts import season_year
    conn.execute("INSERT INTO retired_numbers VALUES (?,?,?,?,?)", (team, n, pid, player_name(conn, pid), season_year(conn)))
    day = get_state(conn)[0]
    emit(conn, "MEDIA_STORY", day, f"{team_abbr(conn, team)} retire #{n} for {player_name(conn, pid)}", team_id=team, player_id=pid,
         importance=2, headline=f"#{n} to the rafters", body=f"{team_abbr(conn, team)} will raise {player_name(conn, pid)}'s #{n}; "
         "nobody at the club will wear it again.", tag="retired_number", kind="retired_number")
    return f"#{n} is retired at {team_abbr(conn, team)} for {player_name(conn, pid)}."


def retired_list(conn, team):
    ensure(conn)
    return [dict(number=r[0], name=r[1], player_id=r[2], season=r[3]) for r in conn.execute(
        "SELECT number, name, player_id, season FROM retired_numbers WHERE team_id=? ORDER BY number", (team,))]


# ---------------------------------------------------------------- the picture
def _fnv(s):
    h = 2166136261
    for ch in str(s):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def colours(conn, team):
    r = conn.execute("SELECT abbr, primary_color, secondary_color FROM teams WHERE team_id=?", (team,)).fetchone() if team else None
    if r and r[1]:
        return r[1], r[2] or "#ffffff"
    a, b = PALETTE[_fnv(r[0] if r else "?") % len(PALETTE)]
    return a, b


def jersey_svg(conn, pid):
    """The back of his jersey: club colours, name, number."""
    ensure(conn)
    r = conn.execute("SELECT last_name, jersey_number, COALESCE(club_id, team_id) FROM players WHERE player_id=?", (pid,)).fetchone()
    name, num, club = (r[0], r[1], r[2]) if r else ("", None, None)
    a, b = colours(conn, club)
    light = lambda h: sum(int(h[i:i + 2], 16) for i in (1, 3, 5)) > 600 if len(h) == 7 else False
    ink = "#111111" if light(a) else "#ffffff"
    trim = b if b.lower() != a.lower() else ink
    nm = html.escape((name or "").upper()[:14])
    fs = 11 if len(nm) <= 8 else 9 if len(nm) <= 11 else 7.5
    num_t = "" if num is None else str(num)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
<rect width="100" height="100" fill="#dfe5ec"/>
<path d="M30 8 L42 4 Q50 9 58 4 L70 8 L94 22 L86 42 L76 37 L76 96 L24 96 L24 37 L14 42 L6 22 Z" fill="{a}" stroke="{trim}" stroke-width="2.5" stroke-linejoin="round"/>
<path d="M6 22 L14 42 L24 37 M94 22 L86 42 L76 37" fill="none" stroke="{trim}" stroke-width="2"/>
<path d="M24 80 H76 M24 86 H76" stroke="{trim}" stroke-width="3" opacity=".9"/>
<path d="M42 4 Q50 11 58 4" fill="none" stroke="{trim}" stroke-width="3"/>
<text x="50" y="27" text-anchor="middle" font-family="Arial Narrow, Arial, sans-serif" font-weight="700" font-size="{fs}" fill="{ink}" letter-spacing=".5">{nm}</text>
<text x="50" y="66" text-anchor="middle" font-family="Arial Black, Arial, sans-serif" font-weight="900" font-size="34" fill="{ink}" stroke="{trim}" stroke-width="1.2">{num_t}</text>
</svg>"""
