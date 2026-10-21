"""Body morphing on the MakeHuman base mesh (pure numpy, no Blender needed).

Macro sliders follow MakeHuman's own blending rules (apps/human.py) so values
behave like MakeHuman / Character Creator sliders.
"""
import json
import os
from functools import lru_cache

import numpy as np

from .errors import CliError

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Friendly macro sliders: name -> (default, description). All range 0..1.
MACROS = {
    "gender": (0.5, "0 = female, 1 = male"),
    "age": (0.5, "0 = 1 year, 0.1875 = 10y, 0.5 = 25y, 1 = 90y"),
    "muscle": (0.5, "0 = minimal muscle tone, 1 = very muscular"),
    "weight": (0.5, "0 = thin, 1 = heavy"),
    "height": (0.5, "0 = short, 1 = tall (relative to gender/age)"),
    "proportions": (0.5, "0 = uncommon, 0.5 = regular, 1 = idealised proportions"),
    "african": (1 / 3, "ethnic blend; the three ethnic values are normalised to sum to 1"),
    "asian": (1 / 3, "ethnic blend"),
    "caucasian": (1 / 3, "ethnic blend"),
    "breast_size": (0.5, "0 = small, 1 = large (female shapes)"),
    "breast_firmness": (0.5, "0 = soft, 1 = firm"),
}


@lru_cache(maxsize=1)
def base():
    return np.load(os.path.join(DATA, "base_mesh.npz"))


@lru_cache(maxsize=1)
def targets():
    return np.load(os.path.join(DATA, "targets.npz"))


@lru_cache(maxsize=1)
def target_names():
    return sorted({k[:-2] for k in targets().files})


# MakeHuman's eye targets move only a millimetre or two at full strength, so they may be pushed past 1.
OVERDRIVE = {"eyes": 2.0}


@lru_cache(maxsize=1)
def modifier_catalog():
    """Detailed (non-macro) modifiers: name -> {targets: {side: target}, range: [min, max], group}."""
    names = set(target_names())
    cat = {}
    for grp in json.load(open(os.path.join(DATA, "modeling_modifiers.json"))):
        g = grp["group"]
        for m in grp["modifiers"]:
            if "target" not in m:
                continue
            t = m["target"]
            if m.get("min") and m.get("max"):
                lo, hi = f"{g}/{t}-{m['min']}", f"{g}/{t}-{m['max']}"
                if lo in names and hi in names:
                    r = OVERDRIVE.get(g, 1.0)
                    cat[f"{g}/{t}-{m['min']}|{m['max']}"] = {"group": g, "decr": lo, "incr": hi, "range": [-r, r]}
            else:
                full = f"{g}/{t}"
                if full in names:
                    cat[full] = {"group": g, "incr": full, "range": [0.0, 1.0]}
    return cat


def _macro_vars(m):
    g = m["gender"]
    v = {"female": 1 - g, "male": g, "universal": 1.0}
    a = m["age"]
    if a < 0.5:
        v["old"] = 0.0
        v["baby"] = max(0.0, 1 - a * 5.333)
        v["young"] = max(0.0, (a - 0.1875) * 3.2)
        v["child"] = max(0.0, min(1.0, 5.333 * a) - v["young"])
    else:
        v["child"] = v["baby"] = 0.0
        v["old"] = max(0.0, a * 2 - 1)
        v["young"] = 1 - v["old"]
    for key, lo, mid, hi in (("muscle", "minmuscle", "averagemuscle", "maxmuscle"),
                             ("weight", "minweight", "averageweight", "maxweight")):
        x = m[key]
        v[hi] = max(0.0, x * 2 - 1)
        v[lo] = max(0.0, 1 - x * 2)
        v[mid] = 1 - (v[hi] + v[lo])
    for key, lo, mid, hi in (("height", "minheight", "averageheight", "maxheight"),
                             ("proportions", "uncommonproportions", "regularproportions", "idealproportions"),
                             ("breast_size", "mincup", "averagecup", "maxcup"),
                             ("breast_firmness", "minfirmness", "averagefirmness", "maxfirmness")):
        x = m[key]
        v[hi] = max(0.0, x * 2 - 1)
        v[lo] = max(0.0, 1 - x * 2)
        v[mid] = 1 - max(v[hi], v[lo])
    eth = np.array([m["african"], m["asian"], m["caucasian"]], dtype=float)
    eth = np.clip(eth, 0, None)
    eth = eth / eth.sum() if eth.sum() > 0 else np.full(3, 1 / 3)
    v["african"], v["asian"], v["caucasian"] = eth
    return v


def _macro_weights(m):
    v = _macro_vars(m)
    out = {}
    for name in target_names():
        grp, _, leaf = name.rpartition("/")
        if not (grp.startswith("macrodetails") or grp == "breast"):
            continue
        parts = leaf.split("-")
        if not all(p in v for p in parts):
            continue
        w = 1.0
        for p in parts:
            w *= v[p]
        if w > 1e-6:
            out[name] = w
    return out


def resolve_macros(values):
    m = {k: d for k, (d, _) in MACROS.items()}
    for k, x in (values or {}).items():
        if k not in MACROS:
            raise CliError("unknown_macro", f"Unknown body slider '{k}'", hint=f"Valid: {', '.join(MACROS)}")
        m[k] = float(min(max(x, 0.0), 1.0))
    return m


def target_weights(macros=None, modifiers=None):
    w = _macro_weights(resolve_macros(macros))
    cat = modifier_catalog()
    for name, val in (modifiers or {}).items():
        if name not in cat:
            raise CliError("unknown_modifier", f"Unknown morph modifier '{name}'",
                           hint="Run `kankuro morphs list` to see valid modifier names")
        c = cat[name]
        lo, hi = c["range"]
        val = float(min(max(val, lo), hi))
        if val > 0:
            w[c["incr"]] = w.get(c["incr"], 0) + val
        elif val < 0:
            w[c["decr"]] = w.get(c["decr"], 0) - val
    return w


def morphed_coords(macros=None, modifiers=None):
    """Return (19158, 3) float64 coordinates (Blender space, metres) with feet on z=0."""
    co = base()["coords"].astype(np.float64).copy()
    t = targets()
    for name, w in target_weights(macros, modifiers).items():
        co[t[name + "|i"]] += w * t[name + "|d"]
    return co


def faces_of_group(group):
    b = base()
    names = list(b["group_names"])
    gid = names.index(group)
    sizes = b["face_sizes"]
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    sel = np.nonzero(b["face_group"] == gid)[0]
    fv = b["face_verts"]
    fu = b["face_uvs"]
    faces = [fv[starts[i]:starts[i] + sizes[i]].tolist() for i in sel]
    fuvs = [fu[starts[i]:starts[i] + sizes[i]].tolist() for i in sel]
    return faces, fuvs
