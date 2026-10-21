"""Facial blendshapes: the 52 ARKit expressions as per-vertex deltas on the MakeHuman base mesh.

Built from MakeHuman's CC0 face data (compiled by tools/build_data.py into data/face_units.npz):
  * pose units: 59 face "muscle" rotations on MakeHuman's face skeleton, skinned with its weights,
    so they adapt to any face shape (jaw, lids, eye look, lips, cheeks, tongue);
  * sculpted units: 34 hand-sculpted expression targets per ethnicity (smile, pucker, frown, blink, brows,
    nose), blended by the character's ethnicity sliders and scaled to its face size.
Deltas are in Blender space for the pre-T-pose body; body.build turns them into shape keys.
"""
import json
import os
from functools import lru_cache

import numpy as np

from . import morph

DATA = os.path.join(os.path.dirname(__file__), "data")
ETHNICITIES = ("african", "asian", "caucasian")
SIDE_BLEND = 0.006  # metres either side of the midline over which a left/right split fades

# ARKit name -> list of (source, unit, amount, side). source: "pose" or "sculpt"; side: "L"/"R"/None.
# Left/right are the character's own (ARKit convention), i.e. +X in Blender for left.
ARKIT = {
    "eyeBlinkLeft": [("sculpt", "eye-left-closure", 1.0, None)],
    "eyeLookDownLeft": [("pose", "LeftEyeDown", 1.0, None)],
    "eyeLookInLeft": [("pose", "LeftEyeturnRight", 1.0, None)],
    "eyeLookOutLeft": [("pose", "LeftEyeturnLeft", 1.0, None)],
    "eyeLookUpLeft": [("pose", "LeftEyeUp", 1.0, None)],
    "eyeSquintLeft": [("sculpt", "eye-left-slit", 1.0, None)],
    "eyeWideLeft": [("sculpt", "eye-left-opened-up", 1.0, None)],
    "eyeBlinkRight": [("sculpt", "eye-right-closure", 1.0, None)],
    "eyeLookDownRight": [("pose", "RightEyeDown", 1.0, None)],
    "eyeLookInRight": [("pose", "RightEyeturnLeft", 1.0, None)],
    "eyeLookOutRight": [("pose", "RightEyeturnRight", 1.0, None)],
    "eyeLookUpRight": [("pose", "RightEyeUp", 1.0, None)],
    "eyeSquintRight": [("sculpt", "eye-right-slit", 1.0, None)],
    "eyeWideRight": [("sculpt", "eye-right-opened-up", 1.0, None)],
    "jawForward": [("pose", "ChinForward", 1.0, None)],
    "jawLeft": [("pose", "ChinLeft", 1.0, None)],
    "jawRight": [("pose", "ChinRight", 1.0, None)],
    "jawOpen": [("pose", "JawDrop", 1.0, None)],
    "mouthClose": [("pose", "JawDrop", -1.0, "lips")],
    "mouthFunnel": [("sculpt", "mouth-protusion", 1.0, None), ("pose", "JawDrop", 0.2, None)],
    "mouthPucker": [("sculpt", "mouth-pursing", 1.0, None)],
    "mouthLeft": [("pose", "MouthMoveLeft", 1.0, None)],
    "mouthRight": [("pose", "MouthMoveRight", 1.0, None)],
    "mouthSmileLeft": [("sculpt", "mouth-corner-puller", 1.0, "L")],
    "mouthSmileRight": [("sculpt", "mouth-corner-puller", 1.0, "R")],
    "mouthFrownLeft": [("sculpt", "mouth-depression", 1.0, "L")],
    "mouthFrownRight": [("sculpt", "mouth-depression", 1.0, "R")],
    "mouthDimpleLeft": [("sculpt", "mouth-retraction", 1.0, "L")],
    "mouthDimpleRight": [("sculpt", "mouth-retraction", 1.0, "R")],
    "mouthStretchLeft": [("sculpt", "mouth-depression-retraction", 1.0, "L")],
    "mouthStretchRight": [("sculpt", "mouth-depression-retraction", 1.0, "R")],
    "mouthRollLower": [("pose", "lowerLipBackward", 1.0, None)],
    "mouthRollUpper": [("pose", "UpperLipBackward", 1.0, None)],
    "mouthShrugLower": [("pose", "lowerLipUp", 1.0, None)],
    "mouthShrugUpper": [("pose", "UpperLipUp", 1.0, None)],
    "mouthPressLeft": [("sculpt", "mouth-compression", 1.0, "L")],
    "mouthPressRight": [("sculpt", "mouth-compression", 1.0, "R")],
    "mouthLowerDownLeft": [("pose", "lowerLipDown", 1.0, "L")],
    "mouthLowerDownRight": [("pose", "lowerLipDown", 1.0, "R")],
    "mouthUpperUpLeft": [("sculpt", "mouth-elevation", 1.0, "L")],
    "mouthUpperUpRight": [("sculpt", "mouth-elevation", 1.0, "R")],
    "browDownLeft": [("sculpt", "eyebrows-left-down", 1.0, None)],
    "browDownRight": [("sculpt", "eyebrows-right-down", 1.0, None)],
    "browInnerUp": [("pose", "LeftInnerBrowUp", 1.0, None), ("pose", "RightInnerBrowUp", 1.0, None)],
    "browOuterUpLeft": [("pose", "LeftOuterBrowUp", 1.0, None)],
    "browOuterUpRight": [("pose", "RightOuterBrowUp", 1.0, None)],
    "cheekPuff": [("pose", "CheeksPump", 1.0, None)],
    "cheekSquintLeft": [("pose", "LeftCheekUp", 1.0, None)],
    "cheekSquintRight": [("pose", "RightCheekUp", 1.0, None)],
    "noseSneerLeft": [("sculpt", "nose-left-elevation", 1.0, None)],
    "noseSneerRight": [("sculpt", "nose-right-elevation", 1.0, None)],
    "tongueOut": [("pose", "TongueOut", 1.0, None)],
}
ARKIT_NAMES = list(ARKIT)
SETS = {"arkit52": ARKIT_NAMES, "none": []}

# Named expressions for previews (`kankuro render --expression smile`), as ARKit weights.
PRESETS = {
    "smile": {"mouthSmileLeft": 1.0, "mouthSmileRight": 1.0, "cheekSquintLeft": 0.5, "cheekSquintRight": 0.5,
              "eyeSquintLeft": 0.3, "eyeSquintRight": 0.3},
    "laugh": {"mouthSmileLeft": 1.0, "mouthSmileRight": 1.0, "jawOpen": 0.35, "cheekSquintLeft": 0.7,
              "cheekSquintRight": 0.7, "eyeSquintLeft": 0.5, "eyeSquintRight": 0.5},
    "surprise": {"browInnerUp": 1.0, "browOuterUpLeft": 1.0, "browOuterUpRight": 1.0, "eyeWideLeft": 1.0,
                 "eyeWideRight": 1.0, "jawOpen": 0.4},
    "angry": {"browDownLeft": 1.0, "browDownRight": 1.0, "noseSneerLeft": 0.6, "noseSneerRight": 0.6,
              "mouthPressLeft": 0.6, "mouthPressRight": 0.6, "eyeSquintLeft": 0.4, "eyeSquintRight": 0.4},
    "sad": {"browInnerUp": 0.8, "mouthFrownLeft": 1.0, "mouthFrownRight": 1.0, "mouthShrugLower": 0.4},
    "blink": {"eyeBlinkLeft": 1.0, "eyeBlinkRight": 1.0},
    "kiss": {"mouthPucker": 1.0},
}


def parse_expression(text):
    """'smile' | 'jawOpen=0.6,mouthSmileLeft=1' | 'smile,jawOpen=0.2' -> {ARKit name: weight}."""
    out = {}
    for item in [x.strip() for x in (text or "").split(",") if x.strip()]:
        name, _, val = item.partition("=")
        if name in PRESETS and not val:
            out.update(PRESETS[name])
            continue
        if name not in ARKIT:
            return None, name
        try:
            out[name] = float(val) if val else 1.0
        except ValueError:
            return None, item
    return out, None


@lru_cache(maxsize=1)
def data():
    return np.load(os.path.join(DATA, "face_units.npz"))


@lru_cache(maxsize=1)
def _joints():
    return json.load(open(os.path.join(DATA, "mh_joints.json")))["joints"]


@lru_cache(maxsize=1)
def _lip_verts():
    """Vertices skinned to the lip ring (MakeHuman's oris bones)."""
    d = data()
    vs = [d[f"w|{b}|i"] for b in d["bone_names"] if str(b).startswith("oris")]
    return np.unique(np.concatenate(vs))


def unit_names():
    return [str(u) for u in data()["unit_names"]] + [str(s) for s in data()["sculpt_names"]]


def pose_delta(co, unit):
    """Deltas of every vertex of `co` (pre-T-pose, Blender space) when one pose unit is applied fully."""
    d = data()
    f = [str(u) for u in d["unit_names"]].index(unit)
    names = [str(b) for b in d["bone_names"]]
    J = _joints()
    heads = [co[np.asarray(J[str(h)])].mean(0) for h in d["bone_head_joint"]]
    G, P = [None] * len(names), [None] * len(names)
    for j, p in enumerate(d["bone_parents"]):
        R = d["unit_rot"][f, j].astype(np.float64)
        if p < 0:
            G[j], P[j] = R, heads[j]
        else:
            G[j] = G[p] @ R
            P[j] = P[p] + G[p] @ (heads[j] - heads[p])
    out = np.zeros_like(co)
    for j, b in enumerate(names):
        if np.allclose(G[j], np.eye(3)) and np.allclose(P[j], heads[j]):
            continue
        vi, w = d[f"w|{b}|i"], d[f"w|{b}|w"]
        if not len(vi):
            continue
        moved = (co[vi] - heads[j]) @ G[j].T + P[j]
        out[vi] += w[:, None] * (moved - co[vi])
    tot = d["weight_total"].astype(np.float64)
    tot[tot == 0] = 1
    return out / tot[:, None]


def _face_scale(co):
    """Size of this face relative to the MakeHuman base face (sculpted deltas were made on the base)."""
    J = _joints()
    base = morph.base()["coords"].astype(np.float64)

    def span(c):
        return np.linalg.norm(c[np.asarray(J["eye.L____head"])].mean(0) - c[np.asarray(J["eye.R____head"])].mean(0))
    return span(co) / span(base)


def ethnicity_weights(macros=None):
    m = macros or {}
    w = np.array([float(m.get(e, 1.0 / 3)) for e in ETHNICITIES])
    return w / w.sum() if w.sum() > 0 else np.full(3, 1.0 / 3)


def sculpt_delta(co, unit, eth_w, scale):
    d = data()
    out = np.zeros_like(co)
    for e, w in zip(ETHNICITIES, eth_w):
        if w > 1e-6:
            out[d[f"s|{e}|{unit}|i"]] += w * d[f"s|{e}|{unit}|d"]
    return out * scale


def _side_mask(co, side):
    if side == "lips":
        m = np.zeros(len(co))
        m[_lip_verts()] = 1.0
        return m
    t = np.clip(0.5 + co[:, 0] / (2 * SIDE_BLEND), 0.0, 1.0)
    t = t * t * (3 - 2 * t)
    return t if side == "L" else 1.0 - t


def deltas(co, names, macros=None):
    """{ARKit name: (nverts, 3) deltas} for the morphed pre-T-pose coords `co`."""
    eth_w = ethnicity_weights(macros)
    scale = _face_scale(co)
    cache = {}
    out = {}
    for n in names:
        total = np.zeros_like(co)
        for src, unit, amount, side in ARKIT[n]:
            key = (src, unit)
            if key not in cache:
                cache[key] = pose_delta(co, unit) if src == "pose" else sculpt_delta(co, unit, eth_w, scale)
            dlt = cache[key] * amount
            if side:
                dlt = dlt * _side_mask(co, side)[:, None]
            total += dlt
        out[n] = total
    return out
