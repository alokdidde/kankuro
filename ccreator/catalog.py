"""Built-in content: hair styles and standard garments."""

# Hair: generated from the scalp of the current body so it always fits.
#   offset: gap above the scalp; thickness: shell thickness;
#   length: how far side/back hair falls below the hairline (metres, 0 = none);
#   extras: added shapes (ponytail, bun); crest: mohawk strip half-width
HAIR_STYLES = {
    "buzz": {"desc": "Very short buzz cut that follows the scalp", "offset": 0.002, "thickness": 0.002, "length": 0.0},
    "short": {"desc": "Short layered cut with some volume", "offset": 0.010, "thickness": 0.008, "length": 0.0},
    "bob": {"desc": "Chin-length bob", "offset": 0.012, "thickness": 0.010, "length": 0.11},
    "long": {"desc": "Straight hair past the shoulders", "offset": 0.010, "thickness": 0.008, "length": 0.34},
    "ponytail": {"desc": "Pulled back with a ponytail", "offset": 0.006, "thickness": 0.006, "length": 0.0,
                 "extras": ["ponytail"]},
    "bun": {"desc": "Pulled back into a bun", "offset": 0.006, "thickness": 0.006, "length": 0.0, "extras": ["bun"]},
    "afro": {"desc": "Big rounded afro", "offset": 0.055, "thickness": 0.02, "length": 0.0, "round": 0.8},
    "mohawk": {"desc": "Shaved sides with a tall centre crest", "offset": 0.002, "thickness": 0.002, "length": 0.0,
               "crest": 0.028},
}

# Garments: cut from MakeHuman's "tights" helper (or skirt helper) and conformed to the body.
#   regions: bone -> [t_min, t_max] along the bone (0 = head, 1 = tail); "*" means both sides (_l/_r)
#   neckline: round opening around the neck base (radius, drop below it at front/back), in metres
#   offset: distance from the skin; layer: stacking order (higher sits outside lower layers)
GARMENTS = {
    "tshirt": {
        "fabric": "cotton", "desc": "Short-sleeve crew-neck T-shirt", "slot": "top", "layer": 1, "offset": 0.006,
        "regions": {"torso": [0.1, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 0.45]},
        "neckline": {"radius": 0.085, "front": 0.11, "back": 0.04},
    },
    "longsleeve": {
        "fabric": "cotton", "desc": "Long-sleeve crew-neck top", "slot": "top", "layer": 1, "offset": 0.006,
        "regions": {"torso": [0.1, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 1], "lowerarm_*": [0, 0.92]},
        "neckline": {"radius": 0.085, "front": 0.11, "back": 0.04},
    },
    "tanktop": {
        "fabric": "cotton", "desc": "Sleeveless tank top", "slot": "top", "layer": 1, "offset": 0.005,
        "regions": {"torso": [0.1, 0.93]},
    },
    "jacket": {
        "fabric": "canvas", "desc": "Loose long-sleeve outer layer covering the hips", "slot": "outer", "layer": 3, "offset": 0.012,
        "weight_smooth": 16,
        "regions": {"torso": [-0.04, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 1], "lowerarm_*": [0, 0.9]},
    },
    "pants": {
        "fabric": "denim", "desc": "Full-length trousers", "slot": "bottom", "layer": 2, "offset": 0.008,
        "regions": {"torso": [0, 0.16], "thigh_*": [0, 1], "calf_*": [0, 0.9]},
    },
    "shorts": {
        "fabric": "denim", "desc": "Mid-thigh shorts", "slot": "bottom", "layer": 2, "offset": 0.008,
        "regions": {"torso": [0, 0.16], "thigh_*": [0, 0.5]},
    },
    "leggings": {
        "fabric": "spandex", "desc": "Skin-tight ankle-length leggings", "slot": "bottom", "layer": 0, "offset": 0.002,
        "regions": {"torso": [0, 0.14], "thigh_*": [0, 1], "calf_*": [0, 0.93]},
    },
    "skirt": {
        "fabric": "cotton", "desc": "Knee-length skirt (MakeHuman skirt helper)", "slot": "bottom", "layer": 2, "offset": 0.004,
        "source_group": "helper-skirt", "length": 0.55,
    },
    "long_skirt": {
        "fabric": "silk", "desc": "Ankle-length skirt (MakeHuman skirt helper)", "slot": "bottom", "layer": 2, "offset": 0.004,
        "source_group": "helper-skirt", "length": 1.0,
    },
    "shoes": {
        "fabric": "leather", "desc": "Closed shoes with a sole", "slot": "feet", "layer": 2, "offset": 0.007,
        "regions": {"foot_*": [0, 1], "ball_*": [0, 1], "calf_*": [0.9, 1]}, "sole": 0.018,
    },
    "boots": {
        "fabric": "leather", "desc": "Mid-calf boots", "slot": "feet", "layer": 3, "offset": 0.008,
        "regions": {"foot_*": [0, 1], "ball_*": [0, 1], "calf_*": [0.45, 1]}, "sole": 0.022,
    },
    "gloves": {
        "fabric": "leather", "desc": "Full-finger gloves", "slot": "hands", "layer": 2, "offset": 0.003, "source_group": "body",
        "regions": {"hand_*": [0, 1], "lowerarm_*": [0.88, 1], "thumb_*": [0, 1], "index_*": [0, 1],
                    "middle_*": [0, 1], "ring_*": [0, 1], "pinky_*": [0, 1]},
    },
    "dhoti": {
        "fabric": "canvas", "desc": "Draped dhoti: loose woven-cotton legs from the waist to mid-calf",
        "slot": "bottom", "layer": 2, "offset": 0.008, "loose": 0.06,
        "regions": {"torso": [0, 0.17], "thigh_*": [0, 1], "calf_*": [0, 0.7]},
    },
    "turban": {
        "fabric": "canvas", "desc": "Wrapped turban (pagdi) with layered folds crossing over the forehead",
        "slot": "head", "layer": 4, "offset": 0.006,
        # line: bottom edge on the head (front, side, back; 0 = skull base, 1 = crown); bulk: how far the
        # cloth swells out; crown: extra height; band/rise/depth: wrap width, climb to the front, ridge height
        "turban": {"line": [0.6, 0.5, 0.2], "bulk": 0.03, "crown": 0.045, "band": 0.03, "rise": 0.07,
                   "depth": 0.009},
    },
}
