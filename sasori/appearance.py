"""Face shape sliders, face presets and randomisation, and named colours (pure Python, no Blender).

Face sliders are friendly, symmetric controls over MakeHuman's detail modifiers (`sasori morphs`).
They live in spec["face"]["shape"] as {"nose.width": 0.4, ...} and are merged into body.morphs at build
time (`effective_morphs`), so a raw body.morphs value and a slider on the same modifier add up.
"""
import random

from .errors import CliError

# slider -> (description, [(modifier, factor)], [min, max]). "{s}" expands to the r- and l- sides.
# Bipolar sliders run -1..1 (0 = the body's own shape); head-shape blends run 0..1.
FACE_SLIDERS = {
    # head
    "head.width": ("narrow .. wide head", [("head/head-scale-horiz-decr|incr", 1)], [-1, 1]),
    "head.length": ("short .. long head (vertical)", [("head/head-scale-vert-decr|incr", 1)], [-1, 1]),
    "head.depth": ("shallow .. deep head (front to back)", [("head/head-scale-depth-decr|incr", 1)], [-1, 1]),
    "head.fat": ("lean .. full face (soft tissue)", [("head/head-fat-decr|incr", 1)], [-1, 1]),
    "head.age": ("younger .. older facial structure", [("head/head-age-decr|incr", 1)], [-1, 1]),
    "head.oval": ("blend towards an oval face", [("head/head-oval", 1)], [0, 1]),
    "head.round": ("blend towards a round face", [("head/head-round", 1)], [0, 1]),
    "head.square": ("blend towards a square face", [("head/head-square", 1)], [0, 1]),
    "head.rectangular": ("blend towards a long rectangular face", [("head/head-rectangular", 1)], [0, 1]),
    "head.triangular": ("blend towards a triangular face (wide jaw, narrow top)", [("head/head-triangular", 1)], [0, 1]),
    "head.heart": ("blend towards a heart face (wide top, narrow chin)", [("head/head-invertedtriangular", 1)], [0, 1]),
    "head.diamond": ("blend towards a diamond face (wide cheekbones)", [("head/head-diamond", 1)], [0, 1]),
    # forehead
    "forehead.height": ("low .. high forehead", [("forehead/forehead-scale-vert-decr|incr", 1)], [-1, 1]),
    "forehead.slope": ("sloped back .. upright/forward forehead", [("forehead/forehead-trans-backward|forward", 1)], [-1, 1]),
    "forehead.bulge": ("flat .. rounded (nubian) forehead", [("forehead/forehead-nubian-decr|incr", 1)], [-1, 1]),
    "forehead.temples": ("hollow .. full temples", [("forehead/forehead-temple-decr|incr", 1)], [-1, 1]),
    # brow ridge (the skull under the eyebrows; eyebrow hair is `brows`)
    "brows.height": ("low .. high brow ridge and eyebrows", [("eyebrows/eyebrows-trans-down|up", 1)], [-1, 1]),
    "brows.tilt": ("outer ends down .. up", [("eyebrows/eyebrows-angle-down|up", 1)], [-1, 1]),
    "brows.ridge": ("flat .. heavy, protruding brow ridge", [("eyebrows/eyebrows-trans-backward|forward", 1)], [-1, 1]),
    # eyes (both eyes together)
    "eyes.size": ("small .. large eyes", [("eyes/{s}-eye-scale-decr|incr", 1.5)], [-1, 1]),
    "eyes.spacing": ("close-set .. wide-set", [("eyes/{s}-eye-trans-in|out", 1)], [-1, 1]),
    "eyes.height": ("lower .. higher on the face", [("eyes/{s}-eye-trans-down|up", 1)], [-1, 1]),
    "eyes.tilt": ("downturned .. upturned (cat-eye) outer corners",
                  [("eyes/{s}-eye-corner1-down|up", 2), ("eyes/{s}-eye-corner2-down|up", -0.8)], [-1, 1]),
    "eyes.openness": ("narrow .. wide-open eyelids",
                      [("eyes/{s}-eye-height1-decr|incr", 1), ("eyes/{s}-eye-height2-decr|incr", 1),
                       ("eyes/{s}-eye-height3-decr|incr", 1)], [-1, 1]),
    "eyes.lid_crease": ("low/hidden .. high upper-lid crease", [("eyes/{s}-eye-eyefold-down|up", 2)], [-1, 1]),
    "eyes.lid_fold": ("concave .. convex (hooded) upper lid", [("eyes/{s}-eye-eyefold-concave|convex", 2)], [-1, 1]),
    "eyes.monolid": ("no .. strong epicanthic fold (inner corner covered)",
                     [("eyes/{s}-eye-epicanthus-in|out", 1.5)], [-1, 1]),
    "eyes.width": ("short .. long eye opening (corner to corner)", [("eyes/{s}-eye-push1-in|out", 1.5), ("eyes/{s}-eye-push2-in|out", 1.5)], [-1, 1]),
    "eyes.bags": ("smooth .. puffy under-eye bags", [("eyes/{s}-eye-bag-decr|incr", 1.5)], [-1, 1]),
    # nose
    "nose.width": ("narrow .. wide nose", [("nose/nose-scale-horiz-decr|incr", 1)], [-1, 1]),
    "nose.length": ("short .. long nose", [("nose/nose-scale-vert-decr|incr", 1)], [-1, 1]),
    "nose.projection": ("flat .. projecting nose", [("nose/nose-scale-depth-decr|incr", 1)], [-1, 1]),
    "nose.height": ("lower .. higher on the face", [("nose/nose-trans-down|up", 1)], [-1, 1]),
    "nose.bridge": ("narrow .. wide bridge", [("nose/nose-width1-decr|incr", 1), ("nose/nose-width2-decr|incr", 0.5)], [-1, 1]),
    "nose.nostrils": ("narrow .. wide nostrils", [("nose/nose-nostrils-width-decr|incr", 1)], [-1, 1]),
    "nose.flare": ("tight .. flared nostril wings", [("nose/nose-flaring-decr|incr", 1)], [-1, 1]),
    "nose.tip_width": ("pointed .. bulbous tip", [("nose/nose-point-width-decr|incr", 1)], [-1, 1]),
    "nose.tip_up": ("drooping .. upturned tip", [("nose/nose-point-down|up", 1)], [-1, 1]),
    "nose.hump": ("straight .. humped bridge", [("nose/nose-hump-decr|incr", 1)], [-1, 1]),
    "nose.curve": ("concave (ski slope) .. convex (aquiline)", [("nose/nose-curve-concave|convex", 1)], [-1, 1]),
    "nose.volume": ("slim .. fleshy nose", [("nose/nose-volume-decr|incr", 1)], [-1, 1]),
    # mouth
    "mouth.width": ("narrow .. wide mouth", [("mouth/mouth-scale-horiz-decr|incr", 1)], [-1, 1]),
    "mouth.height": ("lower .. higher on the face", [("mouth/mouth-trans-down|up", 1)], [-1, 1]),
    "mouth.protrusion": ("recessed .. protruding mouth", [("mouth/mouth-trans-backward|forward", 1)], [-1, 1]),
    "mouth.upper_lip": ("thin .. full upper lip",
                        [("mouth/mouth-upperlip-volume-decr|incr", 1), ("mouth/mouth-upperlip-height-decr|incr", 0.5)], [-1, 1]),
    "mouth.lower_lip": ("thin .. full lower lip",
                        [("mouth/mouth-lowerlip-volume-decr|incr", 1), ("mouth/mouth-lowerlip-height-decr|incr", 0.5)], [-1, 1]),
    "mouth.corners": ("downturned .. upturned mouth corners", [("mouth/mouth-angles-down|up", 1)], [-1, 1]),
    "mouth.cupids_bow": ("flat .. pronounced cupid's bow", [("mouth/mouth-cupidsbow-decr|incr", 1)], [-1, 1]),
    "mouth.philtrum": ("flat .. deep philtrum", [("mouth/mouth-philtrum-volume-decr|incr", 1)], [-1, 1]),
    "mouth.dimples": ("none .. dimples", [("mouth/mouth-dimples-in|out", 1)], [-1, 1]),
    "mouth.laugh_lines": ("smooth .. deep laugh lines", [("mouth/mouth-laugh-lines-in|out", 1)], [-1, 1]),
    # jaw and chin
    "jaw.width": ("narrow .. wide, strong jaw", [("chin/chin-bones-decr|incr", 1)], [-1, 1]),
    "jaw.drop": ("short .. long lower jaw", [("chin/chin-jaw-drop-decr|incr", 1)], [-1, 1]),
    "jaw.underbite": ("overbite .. underbite (prognathism)", [("chin/chin-prognathism-decr|incr", 1)], [-1, 1]),
    "chin.width": ("pointed .. broad chin", [("chin/chin-width-decr|incr", 1)], [-1, 1]),
    "chin.height": ("short .. tall chin", [("chin/chin-height-decr|incr", 1)], [-1, 1]),
    "chin.projection": ("receding .. jutting chin", [("chin/chin-prominent-decr|incr", 1)], [-1, 1]),
    "chin.cleft": ("smooth .. cleft chin", [("chin/chin-cleft-decr|incr", 1)], [-1, 1]),
    # cheeks
    "cheeks.bones": ("flat .. high, wide cheekbones", [("cheek/{s}-cheek-bones-decr|incr", 1)], [-1, 1]),
    "cheeks.volume": ("hollow .. full cheeks", [("cheek/{s}-cheek-volume-decr|incr", 1)], [-1, 1]),
    "cheeks.inner": ("flat .. full under-eye cheek (apple)", [("cheek/{s}-cheek-inner-decr|incr", 1)], [-1, 1]),
    "cheeks.height": ("low .. high cheek mass", [("cheek/{s}-cheek-trans-down|up", 1)], [-1, 1]),
    # ears
    "ears.size": ("small .. large ears", [("ears/{s}-ear-scale-decr|incr", 1)], [-1, 1]),
    "ears.protrusion": ("flat against the head .. sticking out", [("ears/{s}-ear-flap-decr|incr", 1)], [-1, 1]),
    "ears.lobes": ("small .. large lobes", [("ears/{s}-ear-lobe-decr|incr", 1)], [-1, 1]),
    "ears.pointed": ("round .. pointed tips", [("ears/{s}-ear-shape-pointed|triangle", -1)], [-1, 1]),
    "ears.height": ("lower .. higher on the head", [("ears/{s}-ear-trans-down|up", 1)], [-1, 1]),
    # neck
    "neck.width": ("slim .. thick neck", [("neck/neck-scale-horiz-decr|incr", 1), ("neck/neck-scale-depth-decr|incr", 1)], [-1, 1]),
}

HEAD_SHAPES = [k for k, v in FACE_SLIDERS.items() if v[2][0] == 0]

# Face archetypes: starting points to blend from, not complete characters. Combine with body macros
# (gender, age, ethnicity) and then adjust single sliders.
FACE_PRESETS = {
    "angular": {"desc": "lean, chiselled: high cheekbones, wide jaw, defined chin",
                "shape": {"head.fat": -0.5, "cheeks.bones": 0.7, "cheeks.volume": -0.5, "jaw.width": 0.6,
                          "chin.projection": 0.4, "head.square": 0.3, "brows.ridge": 0.4, "nose.projection": 0.3}},
    "soft": {"desc": "soft and youthful: full cheeks, small nose, rounded chin",
             "shape": {"head.fat": 0.4, "cheeks.volume": 0.5, "cheeks.inner": 0.4, "jaw.width": -0.4,
                       "chin.width": -0.2, "nose.length": -0.3, "nose.tip_up": 0.3, "eyes.size": 0.3, "head.round": 0.4}},
    "round": {"desc": "round face, full cheeks, short chin",
              "shape": {"head.round": 0.8, "head.fat": 0.5, "cheeks.volume": 0.6, "chin.height": -0.4,
                        "nose.tip_width": 0.3, "head.length": -0.3}},
    "long": {"desc": "long, narrow face with a long nose and chin",
             "shape": {"head.rectangular": 0.7, "head.width": -0.4, "head.length": 0.4, "nose.length": 0.5,
                       "chin.height": 0.5, "cheeks.volume": -0.3}},
    "heart": {"desc": "wide forehead and cheekbones tapering to a narrow pointed chin",
              "shape": {"head.heart": 0.8, "chin.width": -0.6, "jaw.width": -0.5, "cheeks.bones": 0.4,
                        "forehead.height": 0.3, "mouth.width": -0.2}},
    "square": {"desc": "square face with a broad, strong jaw and chin",
               "shape": {"head.square": 0.8, "jaw.width": 0.8, "chin.width": 0.6, "brows.ridge": 0.3,
                         "neck.width": 0.3}},
    "delicate": {"desc": "fine features: narrow nose, small mouth, large eyes, small chin",
                 "shape": {"nose.width": -0.5, "nose.bridge": -0.4, "nose.tip_width": -0.4, "mouth.width": -0.3,
                           "eyes.size": 0.4, "chin.width": -0.4, "jaw.width": -0.3, "brows.ridge": -0.4}},
    "rugged": {"desc": "heavy brow, broad nose, narrow deep-set eyes, strong jaw",
               "shape": {"brows.ridge": 0.5, "eyes.openness": -0.3, "nose.width": 0.5, "nose.hump": 0.4,
                         "jaw.width": 0.7, "chin.projection": 0.3, "cheeks.volume": -0.3, "head.age": 0.3}},
    "aquiline": {"desc": "narrow face with a high-bridged, convex nose and thin lips",
                 "shape": {"nose.curve": 0.8, "nose.hump": 0.6, "nose.projection": 0.5, "nose.width": -0.3,
                           "mouth.upper_lip": -0.4, "mouth.lower_lip": -0.3, "head.width": -0.3, "cheeks.bones": 0.3}},
    "broad": {"desc": "broad face: wide nose and nostrils, full lips, wide-set eyes",
              "shape": {"head.width": 0.4, "nose.width": 0.6, "nose.nostrils": 0.6, "nose.flare": 0.4,
                        "mouth.upper_lip": 0.6, "mouth.lower_lip": 0.6, "mouth.width": 0.3, "eyes.spacing": 0.3}},
}

# How strongly `randomize` varies each slider group (1 = full range at strength 1).
_RANDOM_SPREAD = {"head": 0.55, "forehead": 0.6, "brows": 0.6, "eyes": 0.55, "nose": 0.7, "mouth": 0.6,
                  "jaw": 0.6, "chin": 0.6, "cheeks": 0.6, "ears": 0.5, "neck": 0.3}
_RANDOM_SKIP = {"head.age", "eyes.bags", "mouth.laugh_lines", "jaw.underbite", "chin.cleft", "mouth.dimples",
                "ears.pointed"}
_RANDOM_SLIDER_SPREAD = {"mouth.corners": 0.25, "eyes.monolid": 0.3, "brows.tilt": 0.35, "eyes.openness": 0.35,
                         "brows.ridge": 0.35, "ears.protrusion": 0.3, "nose.projection": 0.5, "mouth.protrusion": 0.4}


def _check_slider(name):
    if name not in FACE_SLIDERS:
        groups = sorted({k.split(".")[0] for k in FACE_SLIDERS})
        close = [k for k in FACE_SLIDERS if k.split(".")[0] == name.split(".")[0]]
        raise CliError("unknown_face_slider", f"Unknown face slider '{name}'",
                       hint=("Sliders in this group: " + ", ".join(close)) if close else
                       f"Groups: {', '.join(groups)}. List them with `sasori face list`")


def clamp(name, value):
    _check_slider(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CliError("bad_value", f"face.shape.{name} must be a number")
    lo, hi = FACE_SLIDERS[name][2]
    return round(float(min(max(value, lo), hi)), 4)


def validate_shape(shape):
    if not isinstance(shape, dict):
        raise CliError("bad_spec", "face.shape must be an object of slider -> value")
    for k, v in shape.items():
        clamp(k, v)


def shape_modifiers(shape):
    """Face sliders -> {modifier: value} (both sides for paired features)."""
    out = {}
    for name, val in (shape or {}).items():
        _, mods, _ = FACE_SLIDERS[name]
        for mod, f in mods:
            for m in ([mod.replace("{s}", "r"), mod.replace("{s}", "l")] if "{s}" in mod else [mod]):
                out[m] = out.get(m, 0.0) + f * val
    return out


def effective_morphs(spec):
    """body.morphs plus the face sliders, clipped to each modifier's range."""
    from . import morph
    cat = morph.modifier_catalog()
    out = dict(spec["body"].get("morphs") or {})
    for m, v in shape_modifiers(spec.get("face", {}).get("shape")).items():
        out[m] = out.get(m, 0.0) + v
    for m, v in out.items():
        lo, hi = cat[m]["range"]
        out[m] = min(max(v, lo), hi)
    return {m: v for m, v in out.items() if abs(v) > 1e-4}


def preset_shape(name, amount=1.0):
    if name not in FACE_PRESETS:
        raise CliError("unknown_face_preset", f"Unknown face preset '{name}'", hint=f"Valid: {', '.join(FACE_PRESETS)}")
    return {k: clamp(k, v * amount) for k, v in FACE_PRESETS[name]["shape"].items()}


def random_shape(seed=None, strength=0.5, groups=None):
    """A random but plausible face: every slider drawn from a normal distribution, plus one head-shape blend.

    strength 0..1 scales the spread (0.5 is a clearly different but natural face; 1 is caricature-ish).
    groups limits it to some groups (e.g. ["nose", "eyes"]).
    """
    rng = random.Random(seed)
    shape = {}
    for name, (_, _, (lo, hi)) in FACE_SLIDERS.items():
        g = name.split(".")[0]
        if groups and g not in groups:
            continue
        if name in _RANDOM_SKIP or lo == 0:
            continue
        spread = _RANDOM_SLIDER_SPREAD.get(name, _RANDOM_SPREAD[g])
        v = rng.gauss(0.0, 0.5) * spread * strength * 1.4
        shape[name] = round(min(max(v, lo), hi), 3)
    if not groups or "head" in groups:
        shape[rng.choice(HEAD_SHAPES)] = round(rng.uniform(0.3, 0.9) * min(1.0, strength * 1.5), 3)
    return {k: v for k, v in shape.items() if abs(v) >= 0.02}


# ------------------------------------------------------------------ named colours
# Colour fields accept #RRGGBB or a name from their palette (skin colour: SKIN_TONES; hair and eyebrows:
# HAIR_COLORS; iris: EYE_COLORS).
SKIN_TONES = {
    "porcelain": "#dcb8a4", "fair": "#d4a88e", "light": "#ca9a7b", "light_olive": "#bd9068", "medium": "#b07a56",
    "olive": "#b9875f", "tan": "#a96f48", "golden_brown": "#9a6640", "brown": "#7f4f32", "dark_brown": "#5f3a26",
    "deep": "#4a2c1d", "ebony": "#3a2218",
    # stylised
    "pale_grey": "#c9c4c0", "orc_green": "#6f8a4e", "blue": "#5a7ab0",
}
HAIR_COLORS = {
    "black": "#141110", "soft_black": "#231c18", "dark_brown": "#3b2a1e", "brown": "#5a3c26",
    "chestnut": "#6e3b20", "auburn": "#7b3420", "copper": "#a4522a", "ginger": "#b8622f",
    "light_brown": "#8a6644", "dark_blonde": "#9c7c52", "blonde": "#c9a66b", "platinum": "#e3d6b8",
    "ash_blonde": "#b3a58a", "grey": "#8f8b86", "salt_pepper": "#6d6964", "white": "#e8e5e0",
    "blue_black": "#151a24", "burgundy": "#5c1a24", "pink": "#d97a9a", "blue": "#3c5fa8", "green": "#3f7a4f",
    "purple": "#6b4592",
}
EYE_COLORS = {
    "dark_brown": "#3b2416", "brown": "#5b3a22", "light_brown": "#7a5230", "amber": "#a8701e",
    "hazel": "#7a6a35", "green": "#4f7a3a", "grey_green": "#6c7d68", "grey": "#7d8790",
    "blue": "#3a6ea5", "light_blue": "#7fa7cf", "steel_blue": "#4d6a86", "violet": "#6a4d8f",
    "red": "#8f1d1d", "gold": "#c79a2a",
}
PALETTES = {"skin": SKIN_TONES, "hair": HAIR_COLORS, "eyes": EYE_COLORS}


def named_color(value, palette=None):
    """Return the hex for a colour name (or None if it isn't one)."""
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    order = [PALETTES[palette]] if palette else list(PALETTES.values())
    for pal in order:
        if key in pal:
            return pal[key]
    return None


# Eyebrow hair (built by the hair code from these spec keys under "skin")
BROW_KEYS = {
    "brow_thickness": (1.0, [0.3, 2.0], "band height: 0.5 thin, 1 natural, 1.6 bushy"),
    "brow_arch": (0.0, [-1.0, 1.0], "-1 flat/straight .. 0 natural .. 1 high arch"),
    "brow_density": (1.0, [0.2, 2.0], "hair count: 0.4 sparse, 1 natural, 1.6 dense"),
    "brow_length": (1.0, [0.5, 1.4], "how far the tail reaches toward the temple: 0.7 short, 1.2 long"),
}
BROW_PRESETS = {
    "natural": {"brow_thickness": 1.0, "brow_arch": 0.0, "brow_density": 1.0, "brow_length": 1.0},
    "thin": {"brow_thickness": 0.55, "brow_arch": 0.3, "brow_density": 0.8, "brow_length": 0.95},
    "thick": {"brow_thickness": 1.45, "brow_arch": -0.1, "brow_density": 1.4, "brow_length": 1.05},
    "bushy": {"brow_thickness": 1.7, "brow_arch": -0.2, "brow_density": 1.7, "brow_length": 1.1},
    "straight": {"brow_thickness": 1.1, "brow_arch": -0.9, "brow_density": 1.1, "brow_length": 1.05},
    "arched": {"brow_thickness": 0.85, "brow_arch": 0.8, "brow_density": 1.0, "brow_length": 1.0},
    "sparse": {"brow_thickness": 0.8, "brow_arch": 0.0, "brow_density": 0.45, "brow_length": 0.85},
    "short": {"brow_thickness": 1.0, "brow_arch": 0.1, "brow_density": 1.0, "brow_length": 0.72},
}


def check_brow(key, value):
    d, (lo, hi), _ = BROW_KEYS[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CliError("bad_value", f"skin.{key} must be a number in {lo}..{hi}")
    if not lo <= value <= hi:
        raise CliError("bad_value", f"skin.{key}={value} is out of range", hint=f"Use {lo}..{hi} ({BROW_KEYS[key][2]})")
    return float(value)
