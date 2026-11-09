"""Trade protection clauses (v39; docs/TRADES.md "Clauses").

Kinds
  NMC    no-movement: no trade, no waivers, no assignment to the minors without his consent
  NTC    full no-trade: no trade without his consent (waivers allowed)
  MNTC   modified no-trade: a list of `list_size` clubs he cannot be traded to; any other club is fine

Who has one
  Clauses go only to players who could have signed as unrestricted free agents (26+ when the deal starts) on deals of
  two years or more. The chance rises with the cap hit (15% at $2.5M up to 50% at $10M, +10% for five years or more),
  so about one NHL contract in five carries one, mostly on the best-paid veterans. Bigger deals lean to NMC and full
  NTC; mid-size deals to a modified list. Generated once per contract from a fixed seed (the export has no clause
  data), and for every new AI contract when it is signed. Your own players get one only if you agree to it in talks.

The list (MNTC)
  Each summer (and when a clause is created) a player names the clubs he will not go to: the ones he rates worst,
  by competitive state, with some noise of his own.

Waiving (NTC, NMC)
  He waives only if the move is clearly better for him:
    gain = (S_to - S_from) + (role_to - role_from) >= 0.5
  where S is the competitive state (0 hard rebuild .. 1 contender) and role is where he would slot (1.0 top line or
  pair, 0.75, 0.5, 0.25). Loyal players (15+) need 0.2 more; a veteran 33+ going to a contender needs 0.15 less; a
  player who asked for a trade needs only 0.
"""
from __future__ import annotations

import json
import random

KINDS = ("NMC", "NTC", "MNTC")
LABEL = {"NMC": "no-movement clause", "NTC": "full no-trade clause", "MNTC": "modified no-trade clause"}
SHORT = {"NMC": "NMC", "NTC": "NTC", "MNTC": "M-NTC"}
WAIVE_GAIN = 0.5


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS clauses (player_id INTEGER, contract_id INTEGER, kind TEXT, "
                 "list_size INTEGER, start_year INTEGER, end_year INTEGER, blocked TEXT, list_year INTEGER, "
                 "PRIMARY KEY (player_id, contract_id))")


def _age_at(birth, year):
    return year - int(birth[:4]) - (1 if birth[5:10] > "09-15" else 0)


def chance(cap_hit, years, age):
    """Probability that a contract carries a clause."""
    if age < 26 or years < 2 or cap_hit < 2_500_000:
        return 0.0
    p = 0.15 + 0.35 * min(1.0, (cap_hit - 2_500_000) / 7_500_000)
    return p + (0.10 if years >= 5 else 0.0)


def roll(rng, cap_hit, years, age):
    """(kind, list_size) or None."""
    if rng.random() >= chance(cap_hit, years, age):
        return None
    w = [40, 25, 35] if cap_hit >= 7_000_000 else [10, 25, 65]
    kind = rng.choices(KINDS, weights=w)[0]
    return kind, (rng.randint(8, 16) if kind == "MNTC" else 0)


def set_clause(conn, pid, contract_id, kind, list_size, start_year, end_year):
    ensure_table(conn)
    conn.execute("INSERT OR REPLACE INTO clauses VALUES (?,?,?,?,?,?,NULL,NULL)",
                 (pid, contract_id, kind, list_size, start_year, end_year))
    conn.execute("UPDATE contracts SET no_trade=1 WHERE contract_id=?", (contract_id,))


def generate_all(conn):
    """Give every current NHL contract its clause (once per save; seeded per player and contract)."""
    from . import contracts as K
    from ..schema import top_league_sql
    ensure_table(conn)
    if conn.execute("SELECT value FROM pack_info WHERE key='clauses_generated'").fetchone():
        return 0
    y = K.season_year(conn)
    n = 0
    for r in conn.execute(f"SELECT c.contract_id, c.player_id, c.start_year, c.years, c.cap_hit, c.no_trade, p.birth_date "
                          f"FROM contracts c JOIN players p USING (player_id) JOIN teams t ON t.team_id=c.team_id "
                          f"WHERE {top_league_sql('t')} AND c.start_year<=? AND c.start_year+c.years>? "
                          f"AND p.status IN ('active','injured','prospect')", (y, y)).fetchall():
        if conn.execute("SELECT 1 FROM clauses WHERE contract_id=?", (r["contract_id"],)).fetchone():
            continue
        rng = random.Random(f"clause-{r['player_id']}-{r['start_year']}")
        got = roll(rng, r["cap_hit"], r["years"], _age_at(r["birth_date"], r["start_year"]))
        if got is None and r["no_trade"]:
            got = ("NTC", 0)
        if got:
            set_clause(conn, r["player_id"], r["contract_id"], got[0], got[1], r["start_year"],
                       r["start_year"] + r["years"] - 1)
            n += 1
    conn.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('clauses_generated', ?)", (str(y),))
    return n


def on_signed(conn, pid, team_id, contract_id, start_year, years, aav, user_club=False):
    """A new contract: AI clubs' veterans get a clause by the same rule; the user's only through talks."""
    ensure_table(conn)
    if user_club:
        return None
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    if not b:
        return None
    rng = random.Random(f"clause-{pid}-{start_year}")
    got = roll(rng, aav, years, _age_at(b[0], start_year))
    if got:
        set_clause(conn, pid, contract_id, got[0], got[1], start_year, start_year + years - 1)
    return got


def of(conn, pid, year=None):
    """The clause in force for this player this season: dict(kind, list_size, blocked [team_ids], label) or None."""
    ensure_table(conn)
    from . import contracts as K
    if year is None:
        year = K.season_year(conn)
    c = K.current_contract(conn, pid, year)
    if c is None:
        return None
    r = conn.execute("SELECT * FROM clauses WHERE player_id=? AND contract_id=?", (pid, c["contract_id"])).fetchone()
    if not r or not (r["start_year"] <= year <= r["end_year"]):
        return None
    d = dict(kind=r["kind"], list_size=r["list_size"], blocked=json.loads(r["blocked"]) if r["blocked"] else None,
             list_year=r["list_year"])
    d["label"] = LABEL[d["kind"]] + (f" ({d['list_size']}-team list)" if d["kind"] == "MNTC" else "")
    d["short"] = SHORT[d["kind"]] + (f" {d['list_size']}" if d["kind"] == "MNTC" else "")
    return d


def refresh_lists(conn, state, year=None):
    """Each player with a modified clause names the clubs he will not go to: the worst by competitive state (noise
    of his own), once a season. `state` is {team_id: S}."""
    from . import contracts as K
    ensure_table(conn)
    year = K.season_year(conn) if year is None else year
    for r in conn.execute("SELECT c.player_id, c.list_size, p.team_id FROM clauses c JOIN players p USING (player_id) "
                          "WHERE c.kind='MNTC' AND (c.list_year IS NULL OR c.list_year<>?)", (year,)).fetchall():
        rng = random.Random(f"ntclist-{r['player_id']}-{year}")
        others = [t for t in state if t != r["team_id"]]
        others.sort(key=lambda t: state[t] + rng.uniform(-0.15, 0.15))
        conn.execute("UPDATE clauses SET blocked=?, list_year=? WHERE player_id=? AND kind='MNTC'",
                     (json.dumps(others[:r["list_size"]]), year, r["player_id"]))


def waive_threshold(conn, pid, s_to, requested=False):
    if requested:
        return 0.0
    t = WAIVE_GAIN
    p = conn.execute("SELECT loyalty FROM personality WHERE player_id=?", (pid,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='personality'").fetchone() else None
    if p and (p[0] or 0) >= 15:
        t += 0.2
    b = conn.execute("SELECT birth_date FROM players WHERE player_id=?", (pid,)).fetchone()
    from . import contracts as K
    if b and K.season_year(conn) - int(b[0][:4]) >= 33 and s_to >= 0.7:
        t -= 0.15
    return t


def check(conn, pid, to_team, s_from, s_to, role_from, role_to, requested=False):
    """None if the clause (if any) lets this trade happen, else the reason it does not."""
    from .events import player_name, team_abbr
    c = of(conn, pid)
    if c is None:
        return None
    if c["kind"] == "MNTC":
        if c["blocked"] and to_team in c["blocked"]:
            return f"{player_name(conn, pid)} has {team_abbr(conn, to_team)} on his no-trade list"
        return None
    gain = (s_to - s_from) + (role_to - role_from)
    if gain >= waive_threshold(conn, pid, s_to, requested):
        return None
    return (f"{player_name(conn, pid)} will not waive his {LABEL[c['kind']]} to go to {team_abbr(conn, to_team)}")


def blocks_assignment(conn, pid):
    """An NMC keeps a player out of the minors and off waivers without his consent."""
    c = of(conn, pid)
    return bool(c and c["kind"] == "NMC")


def consent(conn, pid, frm, to, requested=None):
    """Standalone check for a single trade (roster.trade): None if allowed, else the reason. Competitive state from
    the standings, roles from rating values."""
    if of(conn, pid) is None:
        return None
    from . import roster as R
    from .trades import standings_rank
    from ..schema import top_league_sql
    rank = standings_rank(conn)
    n = max(2, len(rank))
    S = lambda t: 1.0 - (rank.get(t, (n + 1) / 2) - 1) / (n - 1)
    pos = conn.execute("SELECT position FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    g = R.group(pos)
    v = R.player_value(conn, pid)

    def role(t):
        mine = sorted((R.player_value(conn, r["player_id"]) for r in R.roster(conn, t)
                       if R.group(r["position"]) == g and r["player_id"] != pid), reverse=True)
        better = sum(1 for x in mine if x > v)
        return max(0.25, 1.0 - 0.25 * (better // {"F": 3, "D": 2, "G": 1}[g]))
    if requested is None:
        r = conn.execute("SELECT trade_request FROM morale WHERE player_id=?", (pid,)).fetchone() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='morale'").fetchone() else None
        requested = bool(r and r[0])
    return check(conn, pid, to, S(frm), S(to), role(frm), role(to), requested)
