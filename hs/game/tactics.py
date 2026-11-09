"""Tactics (docs/TACTICS.md, v25 systems; v33 phase B: twelve settings, counters, preferences).

Twelve settings, three to four options each, in four groups: even strength with the puck (breakout, neutral zone,
attacking zone), even strength without it (forecheck, neutral-zone coverage, defensive zone), the power play
(breakout, setup, approach) and the penalty kill (forecheck, coverage, shorthanded attack). Each option changes some of
the engine's multipliers for the club using it:

  att / qual            even-strength shot attempts and shot quality
  allow_att / allow_qual  even-strength attempts and quality the club allows
  pen                   penalties taken
  pp_att / pp_qual      power-play attempts and quality
  pk_allow_att / pk_allow_qual  attempts and quality allowed short-handed
  sh_att                the club's own attempts while short-handed

The good part of an option is scaled by execution; the cost is not, so an option the roster and coach cannot run
is a bad choice. execution = 1 + 0.3 x fit + 0.04 x (coach's coaching - 10) [+ 0.15 when the coach's style suits it],
0.3-1.6; fit = the club's top 18 skaters in the option's attributes, in standard deviations from the league's average
club, less the club's own average over all option attribute sets (the shape of a roster, not its quality).

Counters: some choices beat others. A stretch breakout beats an aggressive forecheck and loses to a passive 1-3-1;
carrying the puck in loses to a trap, dumping it in beats one; cycling beats man-to-man coverage; an umbrella power
play beats a box, a 1-3-1 beats a diamond... COUNTERS lists them (the attacker's attempts and quality against the
defender's choice). They apply per game, between the two clubs' settings.

The five team systems (v25) are presets: each sets the six even-strength settings. Every multiplier is divided by its
league-wide mean (engine_effects), so the mix of choices around the league never moves total scoring; counters are
small and roughly cancel out (the v33 calibration pass, docs/SIM_CALIBRATION.md, measures them).

Preferences (per club): when to pull the goalie down one / down two, when to pull a struggling starter, line matching
at home (your checking line against their top line), how the ice time is spread over the four lines.
"""
from __future__ import annotations

import json
import statistics

from . import roster as R
from .state import get_state, user_team

KEYS = ("att", "allow_att", "qual", "allow_qual", "pen", "pp_att", "pp_qual", "pk_allow_att", "pk_allow_qual", "sh_att")
GOOD_UP = {"att", "qual", "pp_att", "pp_qual", "sh_att"}          # for these, more is better (the rest: less is better)

# setting -> (label, group, default, {option: (label, attributes, effects)})
SETTINGS = {
    "breakout": ("Breakout", "With the puck", "controlled", {
        "safe": ("Safe (off the glass)", ("positioning", "defensive_awareness"), {"allow_att": -0.02, "att": -0.02}),
        "controlled": ("Controlled", (), {}),
        "stretch": ("Stretch pass", ("passing", "speed"), {"att": 0.02, "qual": 0.02, "allow_att": 0.02}),
    }),
    "nz_offence": ("Neutral zone (offence)", "With the puck", "balanced", {
        "dump": ("Dump and chase", ("speed", "checking", "hitting"), {"att": 0.03, "qual": -0.02, "pen": 0.02}),
        "balanced": ("Balanced", (), {}),
        "carry": ("Carry it in", ("puck_control", "agility", "speed"), {"qual": 0.03, "att": -0.01, "allow_att": 0.01}),
    }),
    "zone_offence": ("Attacking zone", "With the puck", "balanced", {
        "cycle": ("Cycle low", ("puck_control", "strength", "passing"), {"qual": 0.025, "att": -0.02}),
        "balanced": ("Balanced", (), {}),
        "point": ("Point shots", ("shot_power", "shot_accuracy"), {"att": 0.04, "qual": -0.035}),
        "crash": ("Crash the net", ("net_presence", "strength", "toughness"), {"qual": 0.03, "pen": 0.02, "allow_att": 0.015}),
    }),
    "forecheck": ("Forecheck", "Without the puck", "212", {
        "passive": ("Passive 1-3-1", ("positioning", "defensive_awareness"), {"allow_att": -0.025, "att": -0.025}),
        "212": ("2-1-2", (), {}),
        "aggressive": ("Aggressive 2-3", ("speed", "checking", "endurance", "aggression"), {"att": 0.045, "allow_qual": 0.03, "pen": 0.04}),
    }),
    "nz_defence": ("Neutral zone coverage", "Without the puck", "balanced", {
        "trap": ("Trap", ("positioning", "defensive_awareness", "stick_checking"), {"allow_att": -0.04, "att": -0.03}),
        "balanced": ("Balanced", (), {}),
        "pressure": ("High pressure", ("speed", "aggression", "endurance"), {"att": 0.025, "allow_att": 0.02, "pen": 0.02}),
    }),
    "zone_defence": ("Defensive zone", "Without the puck", "hybrid", {
        "zone": ("Zone", ("positioning", "defensive_awareness"), {"allow_qual": -0.025, "allow_att": 0.01}),
        "hybrid": ("Hybrid", (), {}),
        "man": ("Man-to-man", ("checking", "strength", "speed"), {"allow_att": -0.03, "allow_qual": 0.02, "pen": 0.03}),
    }),
    "pp_breakout": ("PP breakout", "Power play", "drop", {
        "drop": ("Drop pass", (), {}),
        "carry": ("Single carrier", ("puck_control", "agility"), {"pp_att": 0.03, "pp_qual": -0.01}),
        "stretch": ("Stretch", ("passing", "speed"), {"pp_att": 0.04, "pk_allow_att": 0.0, "pp_qual": -0.02}),
    }),
    "pp_setup": ("PP setup", "Power play", "overload", {
        "umbrella": ("Umbrella", ("shot_power", "shot_accuracy"), {"pp_att": 0.05, "pp_qual": -0.04}),
        "overload": ("Overload", (), {}),
        "131": ("1-3-1", ("passing", "offensive_awareness"), {"pp_qual": 0.04, "pp_att": -0.03}),
    }),
    "pp_approach": ("PP approach", "Power play", "balanced", {
        "shoot": ("Shoot first", ("shot_power", "net_presence"), {"pp_att": 0.05, "pp_qual": -0.04}),
        "balanced": ("Balanced", (), {}),
        "patient": ("Patient", ("passing", "puck_control", "composure"), {"pp_qual": 0.04, "pp_att": -0.04}),
    }),
    "pk_forecheck": ("PK forecheck", "Penalty kill", "balanced", {
        "back": ("Stay back", ("positioning",), {"pk_allow_att": -0.03, "sh_att": -0.25}),
        "balanced": ("Balanced", (), {}),
        "pressure": ("Pressure", ("speed", "endurance"), {"sh_att": 0.2, "pk_allow_qual": 0.03, "pk_allow_att": -0.01}),
    }),
    "pk_coverage": ("PK coverage", "Penalty kill", "box", {
        "box": ("Box", (), {}),
        "diamond": ("Diamond", ("positioning", "stick_checking"), {"pk_allow_qual": -0.02, "pk_allow_att": 0.02}),
        "aggressive": ("Aggressive", ("stick_checking", "speed", "aggression"), {"pk_allow_att": -0.04, "pk_allow_qual": 0.035}),
    }),
    "pk_attack": ("Shorthanded attack", "Penalty kill", "opportunistic", {
        "never": ("Never", (), {"sh_att": -0.35, "pk_allow_qual": -0.01}),
        "opportunistic": ("Opportunistic", (), {}),
        "attack": ("Attack", ("speed", "offensive_awareness"), {"sh_att": 0.4, "pk_allow_qual": 0.025}),
    }),
}
DEFAULTS = {k: v[2] for k, v in SETTINGS.items()}

# The attacker's (att, qual) change by his choice against the defender's choice. Positive = the attacker's choice wins.
COUNTERS = {
    ("breakout", "forecheck"): {("stretch", "aggressive"): (0.04, 0.02), ("stretch", "passive"): (-0.03, -0.01),
                                ("controlled", "aggressive"): (-0.02, 0.0), ("safe", "aggressive"): (0.01, 0.0),
                                ("safe", "passive"): (-0.01, 0.0)},
    ("nz_offence", "nz_defence"): {("carry", "trap"): (-0.03, -0.03), ("dump", "trap"): (0.03, 0.0),
                                   ("carry", "pressure"): (0.02, 0.025), ("dump", "pressure"): (-0.02, 0.0)},
    ("zone_offence", "zone_defence"): {("cycle", "man"): (0.0, 0.03), ("cycle", "zone"): (0.0, -0.02),
                                       ("point", "zone"): (0.03, 0.0), ("point", "man"): (-0.02, 0.0),
                                       ("crash", "zone"): (0.0, -0.02), ("crash", "man"): (0.0, 0.02)},
    ("pp_setup", "pk_coverage"): {("umbrella", "box"): (0.04, 0.0), ("umbrella", "aggressive"): (-0.03, 0.0),
                                  ("131", "diamond"): (0.0, 0.03), ("131", "box"): (0.0, -0.02),
                                  ("overload", "aggressive"): (0.0, 0.025), ("overload", "diamond"): (0.0, -0.015)},
    ("pp_approach", "pk_coverage"): {("patient", "aggressive"): (0.0, 0.03), ("shoot", "aggressive"): (-0.02, 0.0),
                                     ("shoot", "box"): (0.02, 0.0), ("patient", "box"): (0.0, -0.015)},
    ("pp_breakout", "pk_forecheck"): {("stretch", "pressure"): (0.04, 0.0), ("drop", "pressure"): (-0.03, 0.0),
                                      ("carry", "back"): (0.02, 0.0), ("stretch", "back"): (-0.02, 0.0)},
}

# the v25 team systems as presets of the even-strength settings
PRESETS = {
    "balanced": {},
    "heavy forecheck": {"forecheck": "aggressive", "nz_offence": "dump", "nz_defence": "pressure"},
    "puck possession": {"breakout": "controlled", "nz_offence": "carry", "zone_offence": "cycle", "nz_defence": "trap"},
    "defensive structure": {"breakout": "safe", "forecheck": "passive", "nz_defence": "trap", "zone_defence": "zone"},
    "speed and transition": {"breakout": "stretch", "nz_offence": "carry", "nz_defence": "pressure"},
}
SYSTEMS = PRESETS                                      # older code and the owner's identity speak of systems
COACH_FIT = {"motivator": "heavy forecheck", "demanding": "defensive structure", "tactician": "puck possession",
             "teacher": "speed and transition", "players' coach": "speed and transition"}
FIT_WEIGHT = 0.3

PREFS = {
    "pull_down1": ("Pull the goalie, down one", ["3:00", "2:00", "1:30", "1:00", "never"], "2:00"),
    "pull_down2": ("Pull the goalie, down two", ["4:00", "3:00", "2:00", "1:00", "never"], "1:00"),
    "goalie_hook": ("Pull a struggling starter", ["after 3 goals", "after 4 goals", "after 5 goals", "never"], "after 4 goals"),
    "line_matching": ("Line matching (home games)", ["off", "checking line on their top line", "top line on their top line"], "off"),
    "ice_time": ("Ice time", ["roll four lines", "balanced", "shorten the bench"], "balanced"),
}
PREF_DEFAULTS = {k: v[2] for k, v in PREFS.items()}


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS team_tactics (team_id INTEGER PRIMARY KEY, system TEXT, set_on TEXT, "
                 "chosen_by TEXT)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(team_tactics)")}
    if "settings" not in cols:
        conn.execute("ALTER TABLE team_tactics ADD COLUMN settings TEXT")
    if "prefs" not in cols:
        conn.execute("ALTER TABLE team_tactics ADD COLUMN prefs TEXT")


def _row(conn, t):
    ensure_table(conn)
    return conn.execute("SELECT * FROM team_tactics WHERE team_id=?", (t,)).fetchone()


def settings_of(conn, t):
    r = _row(conn, t)
    out = dict(DEFAULTS)
    if r is None:
        return out
    if r["settings"]:
        try:
            out.update({k: v for k, v in json.loads(r["settings"]).items() if k in SETTINGS and v in SETTINGS[k][3]})
            return out
        except ValueError:
            pass
    out.update(PRESETS.get(r["system"] or "balanced", {}))
    return out


def prefs_of(conn, t):
    r = _row(conn, t)
    out = dict(PREF_DEFAULTS)
    if r is not None and r["prefs"]:
        try:
            out.update({k: v for k, v in json.loads(r["prefs"]).items() if k in PREFS and v in PREFS[k][1]})
        except ValueError:
            pass
    return out


def nearest_preset(settings):
    def score(p):
        want = dict(DEFAULTS, **PRESETS[p])
        return sum(settings.get(k) == want[k] for k in ("breakout", "nz_offence", "zone_offence", "forecheck", "nz_defence", "zone_defence"))
    best = max(PRESETS, key=lambda p: (score(p), p == "balanced"))
    return best


def system_of(conn, t):
    r = _row(conn, t)
    return (r["system"] if r and r["system"] else "balanced") if r else "balanced"


def _save(conn, t, settings=None, prefs=None, by="user"):
    ensure_table(conn)
    cur_s, cur_p = settings_of(conn, t), prefs_of(conn, t)
    if settings is not None:
        cur_s = dict(cur_s, **settings)
    if prefs is not None:
        cur_p = dict(cur_p, **prefs)
    conn.execute("INSERT OR REPLACE INTO team_tactics (team_id, system, set_on, chosen_by, settings, prefs) VALUES (?,?,?,?,?,?)",
                 (t, nearest_preset(cur_s), get_state(conn)[0], by, json.dumps(cur_s), json.dumps(cur_p)))


def set_system(conn, t, system, by="user"):
    """Apply a preset (one of the five systems): it sets the six even-strength settings; special teams stay."""
    if system not in PRESETS:
        raise R.RosterError(f"Systems: {', '.join(PRESETS)}.")
    ensure_table(conn)
    s = settings_of(conn, t)
    for k in ("breakout", "nz_offence", "zone_offence", "forecheck", "nz_defence", "zone_defence"):
        s[k] = PRESETS[system].get(k, DEFAULTS[k])
    _save(conn, t, s, None, by)
    conn.execute("UPDATE team_tactics SET system=? WHERE team_id=?", (system, t))


def set_setting(conn, t, key, option, by="user"):
    if key not in SETTINGS:
        raise R.RosterError("Settings: " + ", ".join(SETTINGS) + ".")
    if option not in SETTINGS[key][3]:
        raise R.RosterError(f"{SETTINGS[key][0]}: " + ", ".join(SETTINGS[key][3]) + ".")
    _save(conn, t, {key: option}, None, by)


def set_pref(conn, t, key, value):
    if key not in PREFS:
        raise R.RosterError("Preferences: " + ", ".join(PREFS) + ".")
    if value not in PREFS[key][1]:
        raise R.RosterError(f"{PREFS[key][0]}: " + " | ".join(PREFS[key][1]) + ".")
    _save(conn, t, None, {key: value})


# ---------------------------------------------------------------- fit and execution
def _skater_attrs(conn, t):
    rows = conn.execute("SELECT a.* FROM players p JOIN player_attributes a USING (player_id) WHERE p.team_id=? AND "
                        "p.status IN ('active','injured') AND p.position<>'G'", (t,)).fetchall()
    return sorted(rows, key=lambda r: -R.player_value(conn, r["player_id"]))[:18]


def _attr_sets():
    out = {}
    for k, (_, _, _, opts) in SETTINGS.items():
        for o, (_, attrs, _) in opts.items():
            if attrs:
                out[(k, o)] = attrs
    return out


_FIT_CACHE = {}


def _league_fit(conn):
    """{team: {(setting, option): fit}} (cached per game day)."""
    st = get_state(conn)
    key = (id(conn), st[0] if st else None)
    if key in _FIT_CACHE:
        return _FIT_CACHE[key]
    from ..schema import top_league_sql
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    sets = _attr_sets()
    attrs = sorted({a for v in sets.values() for a in v})
    raw = {}
    for t in teams:
        rows = _skater_attrs(conn, t)
        mean = {a: statistics.fmean((r[a] or 10) for r in rows) if rows else 10.0 for a in attrs}
        raw[t] = {s: statistics.fmean(mean[a] for a in v) for s, v in sets.items()}
    z = {t: {} for t in teams}
    for s in sets:
        xs = [raw[t][s] for t in teams]
        m, sd = (statistics.fmean(xs), statistics.pstdev(xs) or 1.0) if xs else (0, 1)
        for t in teams:
            z[t][s] = (raw[t][s] - m) / sd
    out = {}
    for t in teams:
        own = statistics.fmean(z[t].values()) if z[t] else 0.0
        out[t] = {s: max(-1.5, min(1.5, v - own)) for s, v in z[t].items()}
    _FIT_CACHE.clear()
    _FIT_CACHE[key] = out
    return out


def _coach(conn, t):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='staff'").fetchone():
        return None
    from .staff import head_coach
    return head_coach(conn, t)


def _execution(fit, coaching, style_bonus):
    return max(0.3, min(1.6, 1 + FIT_WEIGHT * fit + 0.04 * (coaching - 10) + style_bonus))


def option_execution(conn, t, key, option, fits=None, hc=None):
    if not SETTINGS[key][3][option][1]:
        return 1.0
    fits = fits if fits is not None else _league_fit(conn)
    hc = hc if hc is not None else _coach(conn, t)
    coaching = ((hc["coaching"] if hc else 10) or 10)
    style = COACH_FIT.get(((hc["style"] if hc else "") or ""))
    bonus = 0.15 if style and PRESETS.get(style, {}).get(key) == option else 0.0
    return _execution(fits.get(t, {}).get((key, option), 0.0), coaching, bonus)


def _raw_multipliers(key, option, ex, f=1.0):
    m = {k: 1.0 for k in KEYS}
    for k, v in SETTINGS[key][3][option][2].items():
        good = (v > 0) == (k in GOOD_UP)
        m[k] *= 1 + (v * ex * f if good else v)
    return m


def _balance():
    """Every option breaks even at execution 1 (an average roster for it and an average coach): its upside is scaled
    so the expected value is zero there. Fit and coaching then make it pay, or not. (Without this, the v33 calibration
    pass found 31 of 32 AI clubs on the same breakout.)"""
    out = {}
    for key, (_, _, _, opts) in SETTINGS.items():
        for o, (_, _, fx) in opts.items():
            if not fx:
                continue
            lo, hi = 0.0, 3.0
            if expected_value(_raw_multipliers(key, o, 1.0, hi)) < 0:
                out[(key, o)] = hi
                continue
            for _ in range(40):
                mid = (lo + hi) / 2
                if expected_value(_raw_multipliers(key, o, 1.0, mid)) > 0:
                    hi = mid
                else:
                    lo = mid
            out[(key, o)] = hi
    return out


def option_multipliers(key, option, ex):
    return _raw_multipliers(key, option, ex, BALANCE.get((key, option), 1.0))


def expected_value(m):
    """A rough goal-differential index (per cent of a game's goal difference) of a set of multipliers."""
    ev = (m["att"] * m["qual"] - 1) - (m["allow_att"] * m["allow_qual"] - 1) - 0.25 * (m["pen"] - 1)
    st = 0.18 * (m["pp_att"] * m["pp_qual"] - 1) - 0.18 * (m["pk_allow_att"] * m["pk_allow_qual"] - 1) + 0.02 * (m["sh_att"] - 1)
    return ev + st


BALANCE = {}
BALANCE.update(_balance())


def multipliers_for(conn, t, settings=None):
    settings = settings or settings_of(conn, t)
    fits, hc = _league_fit(conn), _coach(conn, t)
    m = {k: 1.0 for k in KEYS}
    for key, opt in settings.items():
        om = option_multipliers(key, opt, option_execution(conn, t, key, opt, fits, hc))
        for k in KEYS:
            m[k] *= om[k]
    return m


def setting_options(conn, t):
    """For the Tactics screen: every setting, its options with fit, execution and value; the current choice."""
    fits, hc = _league_fit(conn), _coach(conn, t)
    cur = settings_of(conn, t)
    out = []
    for key, (label, group, default, opts) in SETTINGS.items():
        rows = []
        for o, (ol, attrs, fx) in opts.items():
            ex = option_execution(conn, t, key, o, fits, hc)
            rows.append(dict(option=o, label=ol, attrs=list(attrs), fit=round(fits.get(t, {}).get((key, o), 0.0), 2), execution=round(ex, 2),
                             value=round(expected_value(option_multipliers(key, o, ex)) * 100, 2), effects=fx))
        out.append(dict(key=key, label=label, group=group, default=default, current=cur[key], options=rows))
    return out


# ---------------------------------------------------------------- the v25 view: systems (presets)
def execution(conn, t, system, fits=None):
    """A preset's execution: the mean of its options' execution (1 for balanced)."""
    p = PRESETS.get(system, {})
    if not p:
        return 1.0
    return statistics.fmean(option_execution(conn, t, k, o) for k, o in p.items())


def multipliers(system, ex):
    m = {k: 1.0 for k in KEYS}
    for k, o in PRESETS.get(system, {}).items():
        om = option_multipliers(k, o, ex)
        for x in KEYS:
            m[x] *= om[x]
    return m


def options(conn, t):
    out = []
    for s in PRESETS:
        settings = dict(DEFAULTS, **PRESETS[s])
        m = multipliers_for(conn, t, settings)
        out.append(dict(system=s, fit=round(statistics.fmean([_league_fit(conn).get(t, {}).get((k, o), 0.0) for k, o in PRESETS[s].items()] or [0.0]), 2),
                        execution=round(execution(conn, t, s), 2), value=round(expected_value(m) * 100, 1),
                        multipliers={k: round(v, 3) for k, v in m.items()}))
    return out


def best_settings(conn, t):
    """Each setting's best option for this roster and coach (AI clubs). The default unless something is worth 0.2."""
    fits, hc = _league_fit(conn), _coach(conn, t)
    out = {}
    for key, (_, _, default, opts) in SETTINGS.items():
        vals = {o: expected_value(option_multipliers(key, o, option_execution(conn, t, key, o, fits, hc))) * 100 for o in opts}
        top = max(vals, key=lambda o: (vals[o], o == default))
        margin = 0.2 if SETTINGS[key][1].startswith("With") else 0.06    # special-teams options are worth less a game
        out[key] = top if vals[top] > vals[default] + margin else default
    return out


def best(conn, t):
    return nearest_preset(best_settings(conn, t))


def ai_choose(conn, teams=None):
    """AI clubs pick their settings (preseason, and when the head coach changes); preferences stay at the defaults."""
    ensure_table(conn)
    me = user_team(conn)
    from ..schema import top_league_sql
    teams = teams or [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    for t in teams:
        if t != me:
            _save(conn, t, best_settings(conn, t), None, "ai")


# ---------------------------------------------------------------- counters
def counters(mine, theirs):
    """The attacker's multipliers from his settings against the defender's: dict(att, qual, pp_att, pp_qual)."""
    m = dict(att=1.0, qual=1.0, pp_att=1.0, pp_qual=1.0)
    for (a, d), table in COUNTERS.items():
        x = table.get((mine.get(a), theirs.get(d)))
        if x:
            pp = a.startswith("pp_")
            m["pp_att" if pp else "att"] *= 1 + x[0]
            m["pp_qual" if pp else "qual"] *= 1 + x[1]
    return m


def scout_opponent(conn, t, opp):
    """For the Tactics screen: the opponent's settings, how yours match up, and what would counter him."""
    mine, theirs = settings_of(conn, t), settings_of(conn, opp)
    you, him = counters(mine, theirs), counters(theirs, mine)
    tips = []
    for (a, d), table in COUNTERS.items():
        best_o = max(SETTINGS[a][3], key=lambda o: sum(table.get((o, theirs[d]), (0, 0))))
        gain = sum(table.get((best_o, theirs[d]), (0, 0)))
        if gain > 0 and best_o != mine[a]:
            tips.append(dict(setting=a, label=SETTINGS[a][0], option=best_o, option_label=SETTINGS[a][3][best_o][0],
                             against=SETTINGS[d][3][theirs[d]][0], gain=round(gain * 100, 1)))
    return dict(theirs=theirs, you=you, them=him, tips=tips)


# ---------------------------------------------------------------- the engine
def engine_effects(conn):
    """{team: dict(multipliers..., settings, prefs)} for the engine. Each multiplier is divided by its league-wide mean,
    so the mix of choices around the league never moves the league's totals; only the differences between clubs
    remain. Counters are worked out per game (hs.sim.engine) from the settings carried here."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='team_tactics'").fetchone():
        return {}
    ensure_table(conn)
    from ..schema import top_league_sql
    teams = [r[0] for r in conn.execute(f"SELECT team_id FROM teams WHERE {top_league_sql()}")]
    if not teams:
        return {}
    raw = {t: multipliers_for(conn, t) for t in teams}
    mean = {k: statistics.fmean(m[k] for m in raw.values()) for k in KEYS}
    out = {}
    for t, m in raw.items():
        d = {k: m[k] / mean[k] for k in KEYS}
        d["settings"] = settings_of(conn, t)
        d["prefs"] = prefs_of(conn, t)
        out[t] = d
    return out
