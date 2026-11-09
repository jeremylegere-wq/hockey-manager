"""Player generation and the ageing curve (pure functions, no database).

Scale: "overall" = mean of the key attributes (skaters: offensive_awareness, passing, puck_control, shot_accuracy,
positioning, defensive_awareness, hitting; goalies: goalie_positioning, reflexes, glove, blocker, low_shot_save,
rebound_control), the same quantity hs.game.roster.player_value scales to 0-100. NHL regulars ~10.55, sd ~0.67.

Ageing curve (from the design brief): growth up to the draft, NHL-ready around 20-21 for those who will make it,
growth to a peak at 24-25, decline from about 30, steeper between 35 and 40. Every player gets his own profile:
  potential     ceiling of overall (hidden). Expected remaining growth by age is GROWTH_LEFT, plus individual spread.
  peak_age      ~ N(24.6, 0.8), 23-26.5          decline_age ~ N(30, 1.5), 27-34
  growth_rate   multiplier on how fast he closes the gap to potential (0.7-1.3)
  decline_rate  multiplier on how fast he declines (0.7-1.4)
Goalies peak and decline about two years later (an assumption, not from the brief; easy to change).
Physical attributes decline 1.4x faster than the average; mental/hockey-sense attributes 0.5x and keep growing a
little into the late 20s.
"""
from __future__ import annotations

import math
import random

from .attributes import ALL_ATTRS, GOALIE_ATTRS, RATING_MAX, RATING_MIN, SKATER_ATTRS

SKATER_KEYS = ("offensive_awareness", "passing", "puck_control", "shot_accuracy", "positioning",
               "defensive_awareness", "hitting")
GOALIE_KEYS = ("goalie_positioning", "reflexes", "glove", "blocker", "low_shot_save", "rebound_control")
PHYSICAL = {"speed", "acceleration", "agility", "balance", "endurance", "strength", "goalie_skating",
            "goalie_stamina", "recovery"}
MENTAL = {"offensive_awareness", "defensive_awareness", "positioning", "composure", "leadership", "teamwork",
          "determination", "professionalism", "mental_toughness", "goalie_positioning"}

# expected remaining growth in overall points at each age (age on 15 September)
GROWTH_LEFT = {15: 2.2, 16: 1.9, 17: 1.6, 18: 1.3, 19: 1.0, 20: 0.7, 21: 0.45, 22: 0.28, 23: 0.15, 24: 0.05}
LATE_BLOOM_P, LATE_BLOOM_MEAN = 0.07, 1.1      # tuned so the league keeps ~10 elite (12.3+) players; see docs/WORLD.md

ARCHETYPES = {
    "sniper": {"shot_accuracy": 1.5, "shot_power": 1.5, "offensive_awareness": 1.0, "defensive_awareness": -1.0,
               "hitting": -1.0},
    "playmaker": {"passing": 1.5, "puck_control": 1.2, "offensive_awareness": 1.0, "hitting": -1.0},
    "two_way": {"positioning": 1.0, "defensive_awareness": 1.0, "stick_checking": 0.8},
    "power": {"strength": 1.5, "hitting": 1.5, "net_presence": 1.2, "toughness": 1.0, "puck_control": -0.8},
    "offensive_d": {"passing": 1.2, "puck_control": 1.0, "offensive_awareness": 1.0, "hitting": -0.8},
    "defensive_d": {"positioning": 1.3, "defensive_awareness": 1.3, "shot_blocking": 1.5, "hitting": 1.0,
                    "offensive_awareness": -1.0},
}
POS_MIX = [("C", 4), ("LW", 4), ("RW", 4), ("D", 8), ("G", 3)]


def clip(v):
    return max(RATING_MIN, min(RATING_MAX, int(round(v))))


def stochastic_round(v, rng):
    lo = math.floor(v)
    return lo + (1 if rng.random() < v - lo else 0)


def overall_of(attrs, pos):
    keys = GOALIE_KEYS if pos == "G" else SKATER_KEYS
    vals = [float(attrs.get(k)) if attrs.get(k) not in (None, "") else 10.0 for k in keys]
    return sum(vals) / len(vals)


def growth_left(age):
    if age <= min(GROWTH_LEFT):
        return GROWTH_LEFT[min(GROWTH_LEFT)]
    return GROWTH_LEFT.get(int(age), 0.0)


def make_profile(rng, age, current, pos):
    g = growth_left(age)
    spread = 0.15 + 0.35 * g                       # younger = more uncertain ceiling (late bloomers, busts)
    extra = rng.expovariate(1 / LATE_BLOOM_MEAN) if g > 0.2 and rng.random() < LATE_BLOOM_P else 0.0
    potential = current + max(0.0, rng.gauss(g, spread)) + extra
    shift = 2.0 if pos == "G" else 0.0
    return dict(potential=round(potential, 3),
                peak_age=round(min(26.5, max(23.0, rng.gauss(24.6, 0.8))) + shift, 2),
                decline_age=round(min(34.0, max(27.0, rng.gauss(30.0, 1.5))) + shift, 2),
                growth_rate=round(min(1.3, max(0.7, rng.gauss(1.0, 0.15))), 3),
                decline_rate=round(min(1.4, max(0.7, rng.gauss(1.0, 0.18))), 3))


def yearly_change(age, current, prof, rng):
    """Change in overall for the coming year at this age (age on 15 September)."""
    if age <= prof["peak_age"]:
        rate = 0.30 if age <= 18 else 0.36 if age <= 21 else 0.42 if age <= 23 else 0.6
        gap = max(0.0, prof["potential"] - current)
        return gap * rate * prof["growth_rate"] + rng.gauss(0, 0.08)
    if age < prof["decline_age"]:
        return rng.gauss(0.0, 0.07)
    years = age - prof["decline_age"]
    base = 0.10 + 0.025 * years if age < 35 else 0.28 + 0.08 * (age - 35)
    return -base * prof["decline_rate"] + rng.gauss(0, 0.05)


def apply_change(attrs, pos, delta, rng, age, focus=()):
    """Spread an overall change over the player's attributes; returns the new attribute dict. Multipliers are
    normalised over the key attributes so the overall moves by `delta` on average. v36: `focus` attributes (his
    training focus) take 1.6x their share of a gain, and 0.6x of a loss."""
    own = GOALIE_ATTRS if pos == "G" else SKATER_ATTRS
    keys = GOALIE_KEYS if pos == "G" else SKATER_KEYS

    def mult0(a):
        if delta < 0:
            return 1.4 if a in PHYSICAL else 0.5 if a in MENTAL else 1.0
        return 1.15 if (a in MENTAL and age >= 22) else 0.9 if (a in PHYSICAL and age >= 24) else 1.0

    def mult(a):
        m = mult0(a)
        if a in focus:
            m *= 1.6 if delta >= 0 else 0.6
        return m
    norm = len(keys) / sum(mult(k) for k in keys)
    out = dict(attrs)
    for a in own:
        v = attrs.get(a)
        if v in (None, ""):
            continue
        out[a] = max(RATING_MIN, min(RATING_MAX, stochastic_round(v + delta * mult(a) * norm + rng.gauss(0, 0.12), rng)))
    return out


def gen_attributes(rng, pos, target_overall, kind=None):
    """Attributes around a target overall; physical attributes for teenagers run a little lower."""
    own = GOALIE_ATTRS if pos == "G" else SKATER_ATTRS
    if kind is None and pos != "G":
        kind = rng.choice(["offensive_d", "defensive_d", "two_way"] if pos == "D"
                          else ["sniper", "playmaker", "two_way", "power"])
    bias = ARCHETYPES.get(kind, {})
    attrs = {a: "" for a in ALL_ATTRS}
    for a in own:
        attrs[a] = clip(rng.gauss(target_overall + bias.get(a, 0.0), 1.6))
    # nudge the key attributes so the overall lands near the target
    keys = GOALIE_KEYS if pos == "G" else SKATER_KEYS
    for _ in range(3):
        diff = target_overall - overall_of(attrs, pos)
        for k in keys:
            attrs[k] = clip(attrs[k] + diff)
    return attrs


def gen_player(rng, names, nat, pos, age, season_year, mean, sd=0.6):
    """A generated player: (player fields, attribute dict, development profile)."""
    first, last = names[nat]
    born_year = season_year - age
    month, day = rng.randint(1, 12), rng.randint(1, 28)
    if (month, day) > (9, 15):          # keep the age on 15 September equal to `age`
        born_year -= 1
    current = rng.gauss(mean, sd)
    attrs = gen_attributes(rng, pos, current)
    ov = overall_of(attrs, pos)
    player = dict(first_name=rng.choice(first), last_name=rng.choice(last),
                  birth_date=f"{born_year:04d}-{month:02d}-{day:02d}", position=pos,
                  shoots=rng.choice("LLR"), height_cm=rng.randint(175, 198) if pos != "G" else rng.randint(183, 200),
                  weight_kg=rng.randint(75, 102), nationality=nat)
    return player, attrs, make_profile(rng, age, ov, pos)


def pick_position(rng):
    return rng.choices([p for p, _ in POS_MIX], [w for _, w in POS_MIX])[0]


def pick_nationality(rng, mix):
    return rng.choices(list(mix), list(mix.values()))[0]


def youth_age(rng, kind):
    """Age profile of a club's newcomers by league kind."""
    if kind == "junior":
        return rng.choices([16, 17, 18, 19], [55, 25, 12, 8])[0]
    if kind == "college":
        return rng.choices([18, 19, 20, 21], [25, 45, 20, 10])[0]
    if kind == "europe":
        return rng.choices([18, 19, 20, 22, 25, 28, 31], [12, 14, 12, 14, 18, 18, 12])[0]
    return rng.choices([20, 21, 22, 24, 26, 29, 32], [12, 14, 16, 18, 16, 14, 10])[0]


def roster_age(rng, kind, lo, hi):
    """Ages for an initial (full) club roster."""
    if kind == "junior":
        return rng.choices([16, 17, 18, 19, 20], [14, 26, 26, 22, 12])[0]
    if kind == "college":
        return rng.choices([18, 19, 20, 21, 22, 23, 24], [6, 18, 22, 22, 18, 10, 4])[0]
    return max(lo, min(hi, int(rng.triangular(19, 37, 26))))


def age_mean_offset(age, kind):
    """Younger players in a league sit below its mean; prime-age players at or above it."""
    if kind == "junior":
        return {16: -0.9, 17: -0.45, 18: 0.0, 19: 0.35, 20: 0.6}.get(age, 0.0)
    if kind == "college":
        return {18: -0.5, 19: -0.25, 20: 0.0, 21: 0.15, 22: 0.3, 23: 0.35}.get(age, 0.3)
    if age <= 20:
        return -0.6
    if age <= 23:
        return -0.25
    if age >= 33:
        return -0.1
    return 0.05


# ---------------------------------------------------------------- draft classes (v13)
#
# Each summer a birth-year cohort of 17-year-olds is created. Every prospect has a hidden true ceiling and a few
# things scouts can see (current ability through a noisy lens, height, league, nationality). Calibrated with
# hs.tools.draft_lab so that, drafted through the scouting engine, the classes reproduce the NHL's historical
# outcome rates by round (see docs/DRAFT.md).

CLASS_SKATERS, CLASS_GOALIES = 420, 40
CEILING_BASE, CEILING_SHAPE, CEILING_SCALE = 7.9, 2.0, 0.5       # visible ceiling = base + gamma(shape, scale)
G_CEILING_BASE, G_CEILING_SCALE = 7.0, 0.75
HIDDEN_BLOOM_P = {"two_way": 0.22, "defensive_d": 0.12}             # late developers scouts cannot see coming
HIDDEN_BLOOM_P_OTHER, HIDDEN_BLOOM_MEAN = 0.05, 0.7
MATURITY_SD = 0.3                                                   # early vs late physical maturers
CLASS_NATIONALITY = {"CAN": 38, "USA": 24, "SWE": 10, "FIN": 7, "RUS": 8, "CZE": 5, "SVK": 3, "SUI": 2, "GER": 3}
HOME_LEAGUE = {"CAN": "CHL", "USA": "CHL", "SWE": "SHL", "FIN": "LIIGA", "RUS": "KHL", "CZE": "ELH", "SVK": "ELH",
               "SUI": "NL", "GER": "DEL"}
EXPOSURE = {"CAN": "chl", "USA": "chl", "SWE": "nordic", "FIN": "nordic", "RUS": "russia"}
KHL_LOCK_P = 0.8                                                    # Russians tied to KHL contracts as teenagers


def g_growth_left(age, goalie=False):
    """Expected growth still to come at this age; goalies mature about two years later."""
    return growth_left(age - 2 if goalie else age)


def gen_prospect(rng, names, nat, pos, age, season_year, quality=None):
    """A draft-class prospect: (player fields, attributes, development profile, prospect info).

    quality: optional fixed visible ceiling (tests); otherwise drawn from the class distribution."""
    goalie = pos == "G"
    if quality is None:
        if goalie:
            quality = G_CEILING_BASE + rng.gammavariate(CEILING_SHAPE, G_CEILING_SCALE)
        else:
            quality = CEILING_BASE + rng.gammavariate(CEILING_SHAPE, CEILING_SCALE)
    if goalie:
        kind = None
    else:
        kind = rng.choice(["offensive_d", "defensive_d", "two_way"] if pos == "D"
                          else ["sniper", "playmaker", "two_way", "two_way", "power"])
    p_bloom = HIDDEN_BLOOM_P.get(kind, HIDDEN_BLOOM_P_OTHER)
    hidden = rng.expovariate(1 / HIDDEN_BLOOM_MEAN) if rng.random() < p_bloom else 0.0
    maturity = min(1.7, max(0.4, rng.gauss(1.0, MATURITY_SD)))
    current = quality - g_growth_left(age, goalie) * maturity + rng.gauss(0, 0.12)
    attrs = gen_attributes(rng, pos, current, kind)
    born_year = season_year - age
    month, day = rng.randint(1, 12), rng.randint(1, 28)
    if (month, day) > (9, 15):
        born_year -= 1
    height = int(round(min(203, max(165, rng.gauss(189, 4) if goalie else rng.gauss(183.5, 5.5)))))
    weight = int(round(min(110, max(65, 82 + 0.9 * (height - 183) + rng.gauss(0, 5)))))
    first, last = names[nat]
    player = dict(first_name=rng.choice(first), last_name=rng.choice(last),
                  birth_date=f"{born_year:04d}-{month:02d}-{day:02d}", position=pos, shoots=rng.choice("LLR"),
                  height_cm=height, weight_kg=weight, nationality=nat)
    shift = 2.0 if goalie else 0.0
    prof = dict(potential=round(quality + hidden, 3),
                peak_age=round(min(26.5, max(23.0, rng.gauss(24.6, 0.8))) + shift + (1.2 if hidden else 0.0), 2),
                decline_age=round(min(34.0, max(27.0, rng.gauss(30.0, 1.5))) + shift, 2),
                growth_rate=round(min(1.3, max(0.7, rng.gauss(1.0, 0.15))) * (0.85 if hidden else 1.0), 3),
                decline_rate=round(min(1.4, max(0.7, rng.gauss(1.0, 0.18))), 3))
    info = dict(hidden_bloom=round(hidden, 3), maturity=round(maturity, 3), archetype=kind or "goalie",
                exposure=EXPOSURE.get(nat, "europe"), khl_years=0)
    if nat == "RUS" and rng.random() < KHL_LOCK_P:
        info["khl_years"] = rng.choice([1, 2, 2, 3])
    return player, attrs, prof, info


FILLER_OFFSET = -0.6    # depth juniors/collegians/European kids start below the draft classes' body


def filler_profile(rng, age, current, pos):
    """Depth juniors and collegians outside the draft classes: modest growth, rarely an NHL ceiling."""
    g = g_growth_left(age, pos == "G") * 0.55
    prof = make_profile(rng, age, current, pos)
    prof["potential"] = round(current + max(0.0, rng.gauss(g, 0.25)), 3)
    return prof


JUNIOR_HOME = {"SWE": "J20", "FIN": "U20FIN", "RUS": "MHL", "CZE": "U20CZE", "SVK": "U20SVK", "SUI": "U21SUI",
               "GER": "DNL"}                                         # v44: the database's junior leagues, when the world has them


def class_leagues(nat, age, rng):
    """Where a prospect of this nationality and age plays, best guess first (league abbreviations; leagues the world
    does not have are skipped by the caller)."""
    home = HOME_LEAGUE.get(nat, "CHL")
    chl = ["OHL", "WHL", "QMJHL"]
    rng.shuffle(chl)
    if home == "CHL":
        if age >= 21:
            return ["NCAA", "AHL", "ECHL"]
        if age >= 19 and nat == "USA" and rng.random() < 0.5:
            return ["NCAA"] + chl
        if age >= 18 and nat == "USA" and rng.random() < 0.3:
            return ["NCAA"] + chl
        if nat == "USA" and rng.random() < 0.35:              # the US junior route: USHL, then the NAHL
            return ["USHL"] + chl + ["NAHL", "NCAA"]
        return chl + (["BCHL"] if nat == "CAN" else ["USHL"]) + ["NCAA"]
    junior = JUNIOR_HOME.get(nat)
    # a European 17- or 18-year-old mostly plays junior at home; the best (or older) ones in the men's league
    first = [junior, home] if junior and (age <= 18 and rng.random() < 0.75) else [home, junior] if junior else [home]
    return [x for x in first if x] + ["SHL", "LIIGA"] + chl


def make_draft_class(rng, names, season_year, age=17, drop_top=0):
    """A whole birth-year cohort: [(player, attrs, profile, info)], strongest `drop_top` removed (used when building
    a world whose older cohorts' best players are already real NHLers)."""
    out = []
    for i in range(CLASS_SKATERS + CLASS_GOALIES):
        pos = "G" if i >= CLASS_SKATERS else rng.choices(["C", "LW", "RW", "D"], [4, 4, 4, 6])[0]
        nat = pick_nationality(rng, CLASS_NATIONALITY)
        pl, at, prof, info = gen_prospect(rng, names, nat, pos, age, season_year)
        if age > 17:                                   # play the seasons since 17 (growth shows in current ability)
            cur = overall_of(at, pos)
            for a in range(17, age):
                cur += yearly_change(a, cur, prof, rng)
            at = gen_attributes(rng, pos, cur, info["archetype"] if pos != "G" else None)
        info["class_year"] = season_year - age + 18    # the draft he is first eligible for
        out.append((pl, at, prof, info))
    if drop_top:
        out.sort(key=lambda x: -x[2]["potential"])
        out = out[drop_top:]
    return out
