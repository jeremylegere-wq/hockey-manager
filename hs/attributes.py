"""The game's player model.

Two layers (v38):

* **Ratings** (`player_ratings`): the native, editable model a player is described by, on the scale and with the
  attribute set of the classic hockey-management games: 42 attributes on 1-20 (12 mental, 10 physical, 15 technical,
  5 goalkeeping), current and potential ability on 1-200, six position ratings and two role ratings (1-20). This is
  what the player screens show, what an editor or a bulk import writes, and what develops each summer.
* **Engine attributes** (`player_attributes`, the names below in ENGINE_GROUPS): the composites the match engine,
  player valuation and the AI read. They are *derived* from the ratings by fixed recipes (COMPOSITES), then put on the
  scale the engine was calibrated on (an affine map per attribute, fitted to the top league's dressed players at
  import: `fit_scale`). They are recomputed whenever the ratings change (`derive`), so they are never edited directly.

Packs without ratings (older packs, generated worlds) get ratings back-filled from their engine attributes
(`ratings_from_engine`), so every player has both layers.

Attribute names are generic hockey terms; no other game's data is part of this module.
"""
from __future__ import annotations

RATING_MIN, RATING_MAX = 1, 20
POSITIONS = ("C", "LW", "RW", "D", "G")

# ---------------------------------------------------------------- engine attributes (derived)
SKATER_GROUPS = {
    "skating": ["speed", "acceleration", "agility", "balance", "endurance"],
    "offence": ["shot_accuracy", "shot_power", "passing", "puck_control", "offensive_awareness",
                "net_presence", "faceoffs"],
    "defence": ["checking", "stick_checking", "shot_blocking", "positioning", "defensive_awareness"],
    "physical": ["strength", "hitting", "toughness"],
    "mental": ["aggression", "bravery", "determination", "teamwork", "leadership", "composure",
               "professionalism", "mental_toughness"],
}
GOALIE_ATTRS = ["goalie_positioning", "reflexes", "glove", "blocker", "rebound_control", "recovery",
                "poke_check", "low_shot_save", "goalie_puck_handling", "goalie_passing",
                "goalie_skating", "goalie_stamina"]

SKATER_ATTRS = [a for group in SKATER_GROUPS.values() for a in group]
ALL_ATTRS = SKATER_ATTRS + GOALIE_ATTRS          # the engine attribute columns (player_attributes)
ENGINE_GROUPS = SKATER_GROUPS

# ---------------------------------------------------------------- ratings (native)
NATIVE_GROUPS = {
    "technical": ["agitation", "checking", "deflections", "deking", "faceoffs", "movement", "one_on_ones", "passing",
                  "pass_tendency", "pokecheck", "positioning", "slapshot", "stickhandling", "versatility", "wristshot"],
    "mental": ["aggression", "anticipation", "bravery", "consistency", "decisions", "dirtiness", "flair",
               "important_matches", "leadership", "teamwork", "creativity", "work_rate"],
    "physical": ["acceleration", "agility", "balance", "fighting", "hitting", "injury_proneness", "natural_fitness",
                 "pace", "stamina", "strength"],
    "goalkeeping": ["blocker", "glove", "rebounds", "recovery", "reflexes"],
}
NATIVE_ATTRS = [a for g in NATIVE_GROUPS.values() for a in g]
POSITION_RATINGS = ["pos_g", "pos_ld", "pos_rd", "pos_lw", "pos_c", "pos_rw"]
ROLE_RATINGS = ["role_off", "role_def"]
ABILITY = ["current_ability", "potential_ability"]
RATING_COLS = ABILITY + NATIVE_ATTRS + POSITION_RATINGS + ROLE_RATINGS
ABILITY_MAX = 200

# what develops each summer (skills), and which of those age like the body or like the mind
DEVELOPS = {
    "S": ["acceleration", "agility", "balance", "pace", "stamina", "strength", "hitting", "checking", "deflections", "deking",
          "faceoffs", "movement", "passing", "pokecheck", "positioning", "slapshot", "stickhandling", "wristshot",
          "anticipation", "decisions", "creativity", "teamwork"],
    "G": ["blocker", "glove", "rebounds", "recovery", "reflexes", "positioning", "one_on_ones", "pokecheck", "agility",
          "acceleration", "stamina", "anticipation", "decisions"],
}
BODY = {"acceleration", "agility", "balance", "pace", "stamina", "strength"}
MIND = {"anticipation", "decisions", "creativity", "teamwork", "positioning"}

# engine attribute <- weighted ratings
COMPOSITES = {
    "speed": {"pace": 1}, "acceleration": {"acceleration": 1}, "agility": {"agility": 1}, "balance": {"balance": 1},
    "endurance": {"stamina": .7, "natural_fitness": .3},
    "shot_accuracy": {"wristshot": .75, "decisions": .15, "flair": .10},
    "shot_power": {"slapshot": .75, "strength": .25},
    "passing": {"passing": .75, "creativity": .25},
    "puck_control": {"stickhandling": .6, "deking": .4},
    "offensive_awareness": {"movement": .4, "anticipation": .35, "creativity": .25},
    "net_presence": {"deflections": .5, "strength": .25, "bravery": .25},
    "faceoffs": {"faceoffs": 1},
    "checking": {"checking": 1}, "stick_checking": {"pokecheck": 1},
    "shot_blocking": {"bravery": .5, "positioning": .3, "work_rate": .2},
    "positioning": {"positioning": 1},
    "defensive_awareness": {"positioning": .4, "anticipation": .3, "decisions": .3},
    "strength": {"strength": 1}, "hitting": {"hitting": 1},
    "toughness": {"fighting": .5, "bravery": .25, "strength": .25},
    "aggression": {"aggression": 1}, "bravery": {"bravery": 1}, "determination": {"work_rate": 1},
    "teamwork": {"teamwork": 1}, "leadership": {"leadership": 1},
    "composure": {"decisions": .6, "consistency": .4},
    "professionalism": {"work_rate": .5, "consistency": .5},
    "mental_toughness": {"important_matches": .5, "work_rate": .5},
    "goalie_positioning": {"positioning": 1}, "reflexes": {"reflexes": 1}, "glove": {"glove": 1}, "blocker": {"blocker": 1},
    "rebound_control": {"rebounds": 1}, "recovery": {"recovery": 1}, "poke_check": {"pokecheck": 1},
    "low_shot_save": {"one_on_ones": .4, "agility": .3, "reflexes": .3},
    "goalie_puck_handling": {"stickhandling": 1}, "goalie_passing": {"passing": 1},
    "goalie_skating": {"agility": .5, "acceleration": .5}, "goalie_stamina": {"stamina": 1},
}
assert set(COMPOSITES) == set(ALL_ATTRS)

# the engine's calibrated scale: mean and sd of each engine attribute over the top league's dressed players in the
# reference pack the engine was tuned on (v25/v33). Unmeasured attributes get a neutral (10.5, 2.2).
ENGINE_TARGET = {
    "shot_accuracy": (10.48, 1.18), "shot_power": (10.48, 1.18), "passing": (10.37, 1.91), "puck_control": (10.34, 2.15),
    "offensive_awareness": (10.45, 1.73), "net_presence": (10.56, 1.93), "faceoffs": (10.12, 1.72), "checking": (10.61, 1.32),
    "stick_checking": (10.45, 1.45), "shot_blocking": (10.62, 2.63), "positioning": (10.49, 1.81),
    "defensive_awareness": (10.48, 1.23), "strength": (10.74, 2.56), "hitting": (10.83, 3.05), "toughness": (10.67, 2.13),
    "aggression": (10.79, 2.43), "bravery": (10.75, 2.37), "composure": (10.35, 2.25),
    "goalie_positioning": (10.54, 0.96), "reflexes": (10.55, 1.14), "glove": (10.51, 0.98), "blocker": (10.46, 1.02),
    "rebound_control": (10.48, 1.99), "recovery": (10.49, 2.16), "low_shot_save": (10.52, 1.07),
}
NEUTRAL_TARGET = (10.5, 2.2)


def clip(v, lo=RATING_MIN, hi=RATING_MAX):
    return max(lo, min(hi, int(round(v))))


def raw_composite(ratings, key):
    tot = w = 0.0
    for k, wt in COMPOSITES[key].items():
        v = ratings.get(k)
        if v is None or v == "":
            continue
        tot += wt * float(v)
        w += wt
    return tot / w if w else None


def own_engine(pos):
    return GOALIE_ATTRS if pos == "G" else SKATER_ATTRS


def derive(ratings, pos, scale=None, ca_scale=None):
    """Engine attributes for one player from his ratings. scale: {attr: (a, b)} (identity when absent). With an
    ability scale (an imported world), the level is anchored on current ability: every engine attribute is shifted
    by the same amount so the engine overall is the one his current ability stands for, and the attributes keep the
    shape (strengths and weaknesses) of his ratings."""
    out = {a: "" for a in ALL_ATTRS}
    vals = {}
    for a in own_engine(pos):
        r = raw_composite(ratings, a)
        if r is None:
            continue
        ab = (scale or {}).get(a)
        vals[a] = ab[0] * r + ab[1] if ab else r
    shift = 0.0
    ca = ratings.get("current_ability")
    if ca_scale and ca not in (None, "") and vals:
        shift = overall_from_ability(float(ca), ca_scale, pos) - unanchored_overall(vals, pos)
    for a, v in vals.items():
        out[a] = clip(v + shift)
    return out


def unanchored_overall(vals, pos):
    from .worldgen import GOALIE_KEYS, SKATER_KEYS
    keys = GOALIE_KEYS if pos == "G" else SKATER_KEYS
    xs = [vals[k] for k in keys if k in vals]
    return sum(xs) / len(xs) if xs else 10.0


def raw_overall(ratings, pos, scale=None):
    """The engine overall his ratings alone stand for (before anchoring on ability)."""
    vals = {}
    for a in own_engine(pos):
        r = raw_composite(ratings, a)
        if r is not None:
            ab = (scale or {}).get(a)
            vals[a] = ab[0] * r + ab[1] if ab else r
    return unanchored_overall(vals, pos)


def fit_scale(players):
    """players: [(ratings dict, pos)] of the top league's dressed players. Returns {attr: (a, b)} putting each engine
    attribute on the engine's calibrated scale, plus "_ca": (a, b) mapping an engine overall to current ability."""
    import statistics as st
    scale = {}
    for a in ALL_ATTRS:
        goalie = a in GOALIE_ATTRS
        vals = [raw_composite(r, a) for r, p in players if (p == "G") == goalie]
        vals = [v for v in vals if v is not None]
        if len(vals) < 10:
            continue
        m, sd = st.mean(vals), st.pstdev(vals) or 1.0
        tm, tsd = ENGINE_TARGET.get(a, NEUTRAL_TARGET)
        k = tsd / sd
        scale[a] = (round(k, 4), round(tm - k * m, 4))
    return scale


# the engine overall's spread over the reference pack's dressed players: (mean, sd) for skaters and goalies
OVERALL_TARGET = {"S": (10.49, 0.86), "G": (10.51, 0.66)}
DEFAULT_CA = {"S": (20.0, -95.0), "G": (25.0, -150.0)}


def fit_ability(cas):
    """cas: {"S": [current ability of the top league's dressed skaters], "G": [... goalies]}. Returns
    {"S": (a, b), "G": (a, b)} with CA = a * overall + b, so the league's spread of ability maps onto the engine's
    calibrated spread of overall."""
    import statistics as st
    out = {}
    for g, xs in cas.items():
        if len(xs) < 10:
            out[g] = DEFAULT_CA[g]
            continue
        tm, tsd = OVERALL_TARGET[g]
        a = (st.pstdev(xs) or 1.0) / tsd
        out[g] = (round(a, 4), round(st.mean(xs) - a * tm, 4))
    return out


def _ca(ca_scale, pos):
    g = "G" if pos == "G" else "S"
    if isinstance(ca_scale, dict):
        return tuple(ca_scale.get(g) or DEFAULT_CA[g])
    return tuple(ca_scale) if ca_scale else DEFAULT_CA[g]


def ability_of(overall, ca_scale=None, pos=None):
    a, b = _ca(ca_scale, pos)
    return max(1, min(ABILITY_MAX, int(round(a * overall + b))))


def overall_from_ability(ca, ca_scale=None, pos=None):
    a, b = _ca(ca_scale, pos)
    return (ca - b) / a


def ratings_from_engine(engine, pos, scale=None, ca_scale=None, overall=None, potential=None):
    """Back-fill ratings from engine attributes (packs without ratings, generated players): every rating takes the
    (unscaled) engine attributes it feeds, weighted; ratings no engine attribute uses sit at 10 (or the player's
    level for the skill-like ones)."""
    acc = {}
    for comp, recipe in COMPOSITES.items():
        if comp not in own_engine(pos):
            continue
        v = engine.get(comp)
        if v in (None, ""):
            continue
        ab = (scale or {}).get(comp)
        raw = (float(v) - ab[1]) / ab[0] if ab and ab[0] else float(v)
        for k, w in recipe.items():
            s = acc.setdefault(k, [0.0, 0.0])
            s[0] += w * raw
            s[1] += w
    level = sum(t / w for t, w in acc.values()) / len(acc) if acc else 10.0
    out = {}
    for k in NATIVE_ATTRS:
        if k in acc:
            out[k] = clip(acc[k][0] / acc[k][1])
        elif k in NATIVE_GROUPS["goalkeeping"]:
            out[k] = 1
        elif k in ("versatility", "flair", "creativity", "anticipation", "movement", "deking", "deflections", "one_on_ones"):
            out[k] = clip(level) if not (pos == "G" and k in ("deking", "deflections")) else 1
        else:
            out[k] = 10
    if pos != "G":
        for k in NATIVE_GROUPS["goalkeeping"]:
            out[k] = 1
    out.update(position_ratings(pos))
    out["role_off"], out["role_def"] = 10, 10
    if overall is not None:
        out["current_ability"] = ability_of(overall, ca_scale, pos)
    if potential is not None:
        out["potential_ability"] = max(out.get("current_ability", 1), ability_of(potential, ca_scale, pos))
    return out


def position_ratings(pos):
    base = {"pos_g": 1, "pos_ld": 1, "pos_rd": 1, "pos_lw": 1, "pos_c": 1, "pos_rw": 1}
    if pos == "G":
        base["pos_g"] = 20
    elif pos == "D":
        base.update(pos_ld=20, pos_rd=15)
    elif pos == "C":
        base.update(pos_c=20, pos_lw=10, pos_rw=10)
    elif pos == "LW":
        base.update(pos_lw=20, pos_c=8, pos_rw=12)
    elif pos == "RW":
        base.update(pos_rw=20, pos_c=8, pos_lw=12)
    return base


def primary_position(r):
    """C/LW/RW/D/G from the six position ratings (ties: centre, then the wings, then defence)."""
    best = {"G": r.get("pos_g") or 0, "D": max(r.get("pos_ld") or 0, r.get("pos_rd") or 0), "C": r.get("pos_c") or 0,
            "LW": r.get("pos_lw") or 0, "RW": r.get("pos_rw") or 0}
    order = ["G", "C", "LW", "RW", "D"]
    return max(order, key=lambda p: (best[p], -order.index(p)))
