"""Built-in content: hair styles and standard garments."""

# Hair: generated from the scalp of the current body so it always fits. The hair volume is an opaque,
# darker base layer; strand cards (ribbons with an alpha strand texture) are grown over it along the
# combing direction, in overlapping layers.
#   offset: gap above the scalp; thickness: (unused by cards, kept for imported specs);
#   length: how far side/back hair falls below the hairline (metres, 0 = none);
#   extras: added shapes (ponytail, bun, braid, french_braid); crest: mohawk strip half-width
#   flow: combing direction: "crown" (out from the crown), "part" (away from a parting at x=`part`, then
#         down), "back" (pulled back to the ponytail/bun/braid, or the nape; with `part`, combed sideways
#         off a front parting first), "braid" (into a French braid along the top of the head)
#   part: x of a parting line (cut into the scalp layer); hairline: (front, side, back) heights as
#         fractions of skull base..crown (back is the nape, negative = below the skull); temple: how far the hairline recedes at the temples
#   braid_width / braid_length / braid_period: plait half-width, hanging length and weave period (m)
#   card_len / card_width: typical card size; card_lift: how far cards stack above the base;
#   card_density: layers of cover; curl: strand wave amplitude (radians); cards: False = base layer only
HAIR_STYLES = {
    "buzz": {"desc": "Very short buzz cut that follows the scalp", "offset": 0.002, "thickness": 0.002, "length": 0.0,
             "flow": "crown", "cards": False},
    "short": {"desc": "Short layered cut with some volume", "offset": 0.010, "thickness": 0.008, "length": 0.0,
              "flow": "crown", "card_len": 0.06, "card_width": 0.016, "card_lift": 0.006, "card_density": 5.0},
    "bob": {"desc": "Chin-length bob", "offset": 0.012, "thickness": 0.010, "length": 0.11,
            "flow": "part", "part": 0.02, "card_len": 0.14, "card_width": 0.018, "card_lift": 0.006,
            "card_density": 5.0},
    "long": {"desc": "Straight hair past the shoulders", "offset": 0.010, "thickness": 0.008, "length": 0.34,
             "flow": "part", "part": 0.0, "card_len": 0.24, "card_width": 0.02, "card_lift": 0.006,
             "card_density": 5.0},
    "ponytail": {"desc": "Pulled back with a ponytail", "offset": 0.006, "thickness": 0.006, "length": 0.0,
                 "extras": ["ponytail"], "flow": "back", "part": 0.0, "card_len": 0.12, "card_width": 0.016,
                 "card_lift": 0.004, "card_density": 5.0},
    "bun": {"desc": "Pulled back into a bun", "offset": 0.006, "thickness": 0.006, "length": 0.0, "extras": ["bun"],
            "flow": "back", "part": 0.0, "card_len": 0.10, "card_width": 0.016, "card_lift": 0.004, "card_density": 5.0},
    "indian_braid": {"desc": "Centre parting, pulled back into one long plait down the back", "offset": 0.006,
                     "thickness": 0.006, "length": 0.0, "extras": ["braid"], "flow": "back", "part": 0.0,
                     "hairline": (0.74, 0.55, -0.32), "braid_width": 0.015, "braid_length": 0.42,
                     "braid_period": 0.05, "card_len": 0.12, "card_width": 0.016, "card_lift": 0.004,
                     "card_density": 5.0},
    "french_braid": {"desc": "French braid woven from the forehead down the back of the head, then hanging",
                     "offset": 0.006, "thickness": 0.006, "length": 0.0, "extras": ["french_braid"],
                     "flow": "braid", "braid_width": 0.016, "braid_length": 0.22, "braid_period": 0.045,
                     "card_len": 0.09, "card_width": 0.016, "card_lift": 0.004, "card_density": 5.0},
    "indian_loose": {"desc": "Long, loose, slightly wavy hair with a centre parting, past the shoulder blades",
                     "offset": 0.01, "thickness": 0.008, "length": 0.44, "flow": "part", "part": 0.0,
                     "card_len": 0.3, "card_width": 0.022, "card_lift": 0.007, "card_density": 5.5, "curl": 0.12},
    "afro": {"desc": "Big rounded afro", "offset": 0.055, "thickness": 0.02, "length": 0.0, "round": 0.8,
             "flow": "crown", "card_len": 0.05, "card_width": 0.02, "card_lift": 0.012, "card_density": 3.5,
             "curl": 0.6, "card_jitter": 0.6},
    "mohawk": {"desc": "Shaved sides with a tall centre crest", "offset": 0.002, "thickness": 0.002, "length": 0.0,
               "crest": 0.028, "flow": "back", "card_len": 0.03, "card_width": 0.012, "card_lift": 0.002,
               "card_density": 5.0},
}

# Garments: cut from MakeHuman's "tights" helper (or skirt helper) and conformed to the body.
#   regions: bone -> [t_min, t_max] along the bone (0 = head, 1 = tail); "*" means both sides (_l/_r)
#   neckline: round opening around the neck base (radius, drop below it at front/back), in metres
#   offset: distance from the skin; layer: stacking order (higher sits outside lower layers)
#   flare: a skirt (MakeHuman skirt helper) sewn to the top's waist hem, down to `hem` (0 = hip joint,
#          1 = knee), with side `slits` rising that many metres from the hem
#   drape "dupatta": a scarf laid along a path over the body, not cut from a helper (`width` of the cloth,
#          `drop` = low point of the front U from mid-back (0) to the neck (1), `end` = hanging ends
#          from the hip joint (0) to the knee (1))
#   a_line: a skirt flares out by this many metres at the hem, leaving room for the legs on a stride
#   hang: a loose tunic falls straight down from the chest with this much ease (m) instead of following the waist
#   collar: band collar standing up from the neckline (height, lean in towards the neck)
#   placket: buttoned front opening drawn into the fabric relief (length, width in m, button count)
#   pleat_panel: dhoti front pleats, a strip hanging from the front of the waist between the legs (x range, fold
#          count/depth, flare at the hem, hem_up = how far its hem is above the legs' hem)
#   waist_roll / tuck: a rolled waistband (height, bulge) / the kachha gathered in at the centre back
#   gathers: bunched rings of cloth over the lower leg, from `from` (0 = knee, 1 = ankle)
#   border: width (m) of the "border"/"hem" material regions along the open edges (default 0.025)
GARMENTS = {
    "tshirt": {
        "fabric": "jersey", "desc": "Short-sleeve crew-neck T-shirt", "slot": "top", "layer": 1, "offset": 0.006,
        "regions": {"torso": [0.1, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 0.45]},
        "neckline": {"radius": 0.085, "front": 0.11, "back": 0.04},
    },
    "longsleeve": {
        "fabric": "jersey", "desc": "Long-sleeve crew-neck top", "slot": "top", "layer": 1, "offset": 0.006,
        "regions": {"torso": [0.1, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 1], "lowerarm_*": [0, 0.92]},
        "neckline": {"radius": 0.085, "front": 0.11, "back": 0.04},
    },
    "tanktop": {
        "fabric": "jersey", "desc": "Sleeveless tank top", "slot": "top", "layer": 1, "offset": 0.005,
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
        "a_line": 0.04,
    },
    "blouse": {
        "fabric": "silk", "desc": "Cropped sari blouse (choli): short sleeves, scoop neck, ends under the bust",
        "slot": "top", "layer": 1, "offset": 0.004,
        "regions": {"torso": [0.6, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 0.38]},
        "neckline": {"radius": 0.085, "front": 0.14, "back": 0.09},
    },
    "saree": {
        "border": 0.07,
        "fabric": "silk", "desc": "Saree in the Nivi drape: floor-length skirt with front pleats and the pallu over "
                                  "the left shoulder, hanging down the back (wear over a blouse)",
        "slot": "bottom", "layer": 3, "offset": 0.004, "source_group": "helper-skirt", "length": 1.0,
        # hem: height above the floor; pleats: front panel x range, fold count/depth, flare at the hem;
        # pallu: how far its end hangs below the waist at the back, gap over what it lies on
        "drape": "saree", "subdiv": 2, "hem": 0.025, "weight_smooth": 30, "a_line": 0.05,
        # the saree's skirt is a smooth tube that projects cleanly; its template layout (hem border, pallu
        # band) is what saree textures are painted against, so it keeps the plain projection
        "unsquash_uv": False,
        "pleats": {"x": [-0.075, 0.085], "folds": 7, "depth": 0.014, "flare": 0.03},
        "pallu": {"drop": 0.45, "gap": 0.007},
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
        "border": 0.045,
        "fabric": "cotton", "desc": "Draped dhoti: loose woven-cotton legs from the waist to mid-calf, a pleated "
                                    "front panel hanging between the legs, rolled waist, kachha tuck at the back",
        "slot": "bottom", "layer": 2, "offset": 0.008, "loose": 0.06,
        "pleat_panel": {"x": [-0.075, 0.075], "folds": 6, "depth": 0.009, "flare": 0.03, "hem_up": 0.04},
        "waist_roll": {"height": 0.045, "bulge": 0.007}, "tuck": {"depth": 0.025, "width": 0.06, "length": 0.3},
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
    "kurta": {
        "border": 0.015,
        "fabric": "cotton", "desc": "Loose knee-length tunic worn over a dhoti or churidar: band collar, buttoned "
                                    "front placket, 3/4 sleeves, side slits from the hip down",
        "slot": "top", "layer": 3, "offset": 0.008, "weight_smooth": 16, "hang": 0.025,
        "regions": {"torso": [0.1, 1], "clavicle_*": [0, 1], "upperarm_*": [0, 1], "lowerarm_*": [0, 0.6]},
        "neckline": {"radius": 0.075, "front": 0.075, "back": 0.035},
        "collar": {"height": 0.03, "lean": 0.12},
        "placket": {"length": 0.17, "width": 0.032, "buttons": 3},
        "flare": {"hem": 1.12, "slits": 0.36},
    },
    "churidar": {
        "fabric": "cotton", "desc": "Fitted ankle-length trousers bunched into gathers over the lower leg",
        "slot": "bottom", "layer": 0, "offset": 0.003, "subdiv": 2,
        "regions": {"torso": [0, 0.04], "thigh_*": [0, 1], "calf_*": [0, 0.97]},
        "gathers": {"from": 0.35, "amp": 0.010, "wavelength": 0.03, "extra": 0.003},
    },
    "dupatta": {
        "fabric": "silk", "desc": "Long scarf worn with a churidar: a U across the chest, over both shoulders, ends down the back",
        "slot": "shawl", "layer": 4, "offset": 0.004, "drape": "dupatta", "width": 0.22, "drop": 0.15, "end": 0.45,
    },
}


def m2m_bones():
    """The 66 Mesh2Motion bone names (with root), in file order. bpy-free."""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "m2m_rig.json")
    with open(path) as f:
        return [b["name"] for b in json.load(f)["bones"]]


# Accessories: rigid pieces on one bone (blender/accessories.py). Built-ins are made on the reference body
# so agents can try the command without a mesh; your own are modelled on `sasori reference-body`.
#   fit: none (rigid; slides along the bone until clear of the body) | wrap (radial scale to hug a limb) |
#        chest / neck (the lower part settles onto the chest) | pierce (rigid and left exactly where it is,
#        through the body: earrings, nose rings); hang: extra bones for a dangling part
ACCESSORIES = {
    "circlet": {"desc": "Plain gold band around the head at the forehead, with a small front ornament",
                "bone": "head", "fit": "none", "material": "gold"},
    "ring_earring_l": {"desc": "Small hoop earring through the left earlobe", "bone": "head", "fit": "pierce",
                       "hang": 1, "material": "gold"},
    "ring_earring_r": {"desc": "Small hoop earring through the right earlobe", "bone": "head", "fit": "pierce",
                       "hang": 1, "material": "gold"},
    "bangle_l": {"desc": "Bangle on the left wrist", "bone": "lowerarm_l", "fit": "wrap", "material": "gold"},
    "bangle_r": {"desc": "Bangle on the right wrist", "bone": "lowerarm_r", "fit": "wrap", "material": "gold"},
}
ACCESSORY_FITS = ("none", "wrap", "chest", "neck", "pierce")

# Props: held in the hand through a socket bone (prop_l / prop_r under hand_l / hand_r). Built-in test props
# are cylinders laid across the palm: radius/length in metres, `along` = how far the prop runs past the
# grip towards the index finger (the rest runs towards the little finger), `tilt` = degrees the index end
# leans towards the fingertips (negative: towards the wrist, so a long staff points down a hanging arm),
# `reach` = where the second hand holds a two-hand prop, metres from the grip towards the index finger
# (negative: towards the little finger; default -0.3);
# `hold` = where the anchor hand's wrist brings a two-hand prop, metres from `hold_bone`'s head (x is
# mirrored for a left anchor). Default: in front of the chest, from spine_03.
PROPS = {
    "handle": {"desc": "Plain cylinder handle, 3 cm across (a tool grip, a bucket handle)", "radius": 0.015,
               "length": 0.14, "along": 0.5, "tilt": 15, "grip": "power", "hand": "r", "material": "iron_dark"},
    "staff": {"desc": "Walking staff (lathi), 4 cm across and 1.3 m long", "radius": 0.02, "length": 1.3, "along": 0.37, "tilt": -40,
              "grip": "staff", "hand": "r", "color": "#6b4a2b"},
    "flute": {"desc": "Bansuri flute, 2.5 cm across and 0.55 m long, held in both hands", "radius": 0.0125,
              "length": 0.55, "along": 0.35, "tilt": 0, "grip": "flute", "hand": "both", "anchor": "r", "reach": -0.12,
              "hold_bone": "head", "hold": [-0.22, -0.2, -0.12],
              "color": "#b98c4f"},
}

# Grips: finger poses for holding props. "contact" curls each finger joint until it touches the prop
# (limited to `max` degrees per joint: knuckle, middle, tip); a list of degrees is a fixed pose.
GRIPS = {
    "power": {"desc": "Full wrap round a handle, thumb over the fingers", "fingers": "contact", "thumb": "contact",
              "max": [90, 100, 80]},
    "staff": {"desc": "Like power, for a long pole", "fingers": "contact", "thumb": "contact", "max": [90, 100, 80]},
    "hook": {"desc": "Fingers hooked round a handle, thumb free (carrying a bucket or a bag)",
             "fingers": "contact", "thumb": [10, 5, 0], "max": [25, 100, 80]},
    "pinch": {"desc": "Thumb and index pinch, other fingers loosely curled", "fingers": "contact",
              "thumb": "contact", "max": [70, 80, 60], "only": ["index"], "rest": [30, 45, 30]},
    "flute": {"desc": "Fingers laid over a flute's holes, thumb under it", "fingers": "contact", "thumb": "contact",
              "max": [30, 35, 25]},
    "open": {"desc": "Flat, relaxed open hand", "fingers": [5, 5, 5], "thumb": [0, 0, 0]},
    "fist": {"desc": "Closed fist", "fingers": [80, 95, 70], "thumb": [30, 40, 40]},
    "point": {"desc": "Index finger pointing, the rest in a fist", "fingers": [80, 95, 70], "thumb": [30, 40, 40],
              "index": [0, 0, 0]},
}
FINGERS = ("index", "middle", "ring", "pinky")
