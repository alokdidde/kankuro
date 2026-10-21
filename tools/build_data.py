"""Compile third-party CC0 source assets into the compact files under kankuro/data.

Sources (both CC0):
  * MakeHuman  https://github.com/makehumancommunity/makehuman  (base mesh, morph targets, weights, eyes,
    face pose units and expression targets)
  * Mesh2Motion https://github.com/scottpetrovic/mesh2motion-app (human rig, animations)

Usage:
  python tools/build_data.py --makehuman /path/to/makehuman/makehuman/data --mesh2motion /path/to/mesh2motion-app

Coordinates: MakeHuman is Y-up, decimetres, facing +Z. We convert to Blender's
Z-up metres facing -Y (the Mesh2Motion convention): (x, y, z) -> (x, -z, y) * 0.1
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "kankuro", "data")


def mh_to_bl(a):
    a = np.asarray(a, dtype=np.float64)
    return np.stack([a[..., 0], -a[..., 2], a[..., 1]], axis=-1) * 0.1


def parse_obj(path):
    verts, uvs, faces, fuvs, fgroup, groups = [], [], [], [], [], []
    gidx = {}
    cur = 0
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("vt "):
                uvs.append([float(x) for x in line.split()[1:3]])
            elif line.startswith("g "):
                name = line.split()[1]
                if name not in gidx:
                    gidx[name] = len(groups)
                    groups.append(name)
                cur = gidx[name]
            elif line.startswith("f "):
                fv, ft = [], []
                for tok in line.split()[1:]:
                    p = tok.split("/")
                    fv.append(int(p[0]) - 1)
                    ft.append(int(p[1]) - 1 if len(p) > 1 and p[1] else -1)
                faces.append(fv)
                fuvs.append(ft)
                fgroup.append(cur)
    return np.array(verts), np.array(uvs), faces, fuvs, np.array(fgroup), groups


def build_base(mh):
    v, uv, faces, fuvs, fgroup, groups = parse_obj(os.path.join(mh, "3dobjs", "base.obj"))
    sizes = np.array([len(f) for f in faces], dtype=np.int32)
    np.savez_compressed(
        os.path.join(DATA, "base_mesh.npz"),
        coords=mh_to_bl(v).astype(np.float32),
        uvs=uv.astype(np.float32),
        face_sizes=sizes,
        face_verts=np.concatenate(faces).astype(np.int32),
        face_uvs=np.concatenate(fuvs).astype(np.int32),
        face_group=fgroup.astype(np.int16),
        group_names=np.array(groups),
    )
    print("base mesh:", len(v), "verts", len(faces), "faces", groups)
    return len(v)


def build_targets(mh, nverts):
    root = os.path.join(mh, "targets")
    out = {}
    names = []
    for dirpath, _, files in os.walk(root):
        for fn in sorted(files):
            if not fn.endswith(".target"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)[: -len(".target")].replace(os.sep, "/")
            idx, d = [], []
            with open(os.path.join(dirpath, fn)) as f:
                for line in f:
                    if not line.strip() or line.startswith("#"):
                        continue
                    p = line.split()
                    idx.append(int(p[0]))
                    d.append([float(p[1]), float(p[2]), float(p[3])])
            if not idx:
                continue
            names.append(rel)
            out[rel + "|i"] = np.array(idx, dtype=np.int32)
            out[rel + "|d"] = mh_to_bl(np.array(d)).astype(np.float32)
    np.savez_compressed(os.path.join(DATA, "targets.npz"), **out)
    print("targets:", len(names))


# Mesh2Motion bone -> (MakeHuman head joint, MakeHuman tail joint)
# joints are "<mhbone>____head" / "<mhbone>____tail" keys of default.mhskel "joints"
M2M_FROM_MH = {
    "pelvis": ("root____head", "spine04____head"),
    "spine_01": ("spine04____head", "spine03____head"),
    "spine_02": ("spine03____head", "spine02____head"),
    "spine_03": ("spine02____head", "neck01____head"),
    "neck_01": ("neck01____head", "head____head"),
    "head": ("head____head", "head____tail"),
    "clavicle_{s}": ("clavicle.{S}____head", "upperarm01.{S}____head"),
    "upperarm_{s}": ("upperarm01.{S}____head", "lowerarm01.{S}____head"),
    "lowerarm_{s}": ("lowerarm01.{S}____head", "wrist.{S}____head"),
    "hand_{s}": ("wrist.{S}____head", "finger3-1.{S}____head"),
    "thumb_01_{s}": ("finger1-1.{S}____head", "finger1-2.{S}____head"),
    "thumb_02_{s}": ("finger1-2.{S}____head", "finger1-3.{S}____head"),
    "thumb_03_{s}": ("finger1-3.{S}____head", "finger1-3.{S}____tail"),
    "thigh_{s}": ("upperleg01.{S}____head", "lowerleg01.{S}____head"),
    "calf_{s}": ("lowerleg01.{S}____head", "foot.{S}____head"),
    "foot_{s}": ("foot.{S}____head", "foot.{S}____tail"),
    "ball_{s}": ("foot.{S}____tail", "toe3-1.{S}____tail"),
}
for m2m_f, mh_f in (("index", 2), ("middle", 3), ("ring", 4), ("pinky", 5)):
    M2M_FROM_MH[f"{m2m_f}_01_{{s}}"] = (f"finger{mh_f}-1.{{S}}____head", f"finger{mh_f}-2.{{S}}____head")
    M2M_FROM_MH[f"{m2m_f}_02_{{s}}"] = (f"finger{mh_f}-2.{{S}}____head", f"finger{mh_f}-3.{{S}}____head")
    M2M_FROM_MH[f"{m2m_f}_03_{{s}}"] = (f"finger{mh_f}-3.{{S}}____head", f"finger{mh_f}-3.{{S}}____tail")


def mh_bone_to_m2m(b):
    """Map a MakeHuman default-skeleton bone to the Mesh2Motion bone that receives its weights."""
    side = None
    if b.endswith(".L"):
        side, b = "l", b[:-2]
    elif b.endswith(".R"):
        side, b = "r", b[:-2]
    sfx = "_" + side if side else ""
    if b in ("root", "spine05") or b == "pelvis":
        return "pelvis"
    table = {"spine04": "spine_01", "spine03": "spine_02", "spine02": "spine_03", "spine01": "spine_03",
             "breast": "spine_03", "neck01": "neck_01", "neck02": "neck_01", "neck03": "neck_01",
             "clavicle": "clavicle", "shoulder01": "upperarm", "upperarm01": "upperarm", "upperarm02": "upperarm",
             "lowerarm01": "lowerarm", "lowerarm02": "lowerarm", "wrist": "hand",
             "metacarpal1": "hand", "metacarpal2": "hand", "metacarpal3": "hand", "metacarpal4": "hand",
             "upperleg01": "thigh", "upperleg02": "thigh", "lowerleg01": "calf", "lowerleg02": "calf",
             "foot": "foot"}
    if b in table:
        return table[b] + sfx
    if b.startswith("finger"):
        f, seg = b[len("finger"):].split("-")
        name = {"1": "thumb", "2": "index", "3": "middle", "4": "ring", "5": "pinky"}[f]
        return f"{name}_0{seg}{sfx}"
    if b.startswith("toe"):
        return "ball" + sfx
    return "head"  # face, eyes, jaw, tongue, ...


def build_skeleton(mh, nverts):
    skel = json.load(open(os.path.join(mh, "rigs", "default.mhskel")))
    w = json.load(open(os.path.join(mh, "rigs", "default_weights.mhw")))["weights"]
    acc = {}
    for b, pairs in w.items():
        t = mh_bone_to_m2m(b)
        arr = acc.setdefault(t, np.zeros(nverts, dtype=np.float64))
        for vi, wt in pairs:
            arr[vi] += wt
    out = {}
    for b, arr in acc.items():
        nz = np.nonzero(arr > 1e-4)[0]
        out[b + "|i"] = nz.astype(np.int32)
        out[b + "|w"] = arr[nz].astype(np.float32)
    np.savez_compressed(os.path.join(DATA, "m2m_weights.npz"), **out)
    fits = {}
    for k, (h, t) in M2M_FROM_MH.items():
        if "{s}" in k:
            for s, S in (("l", "L"), ("r", "R")):
                fits[k.format(s=s)] = [h.format(S=S), t.format(S=S)]
        else:
            fits[k] = [h, t]
    json.dump({"joints": skel["joints"], "fit": fits}, open(os.path.join(DATA, "mh_joints.json"), "w"))
    print("weights for", len(acc), "m2m bones")


def build_m2m(m2m):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(m2m, "static", "rigs", "rig-human.glb"))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    bones = []
    for b in arm.data.bones:
        m = arm.matrix_world @ b.matrix_local
        bones.append({
            "name": b.name,
            "parent": b.parent.name if b.parent else None,
            "head": list(arm.matrix_world @ b.head_local),
            "tail": list(arm.matrix_world @ b.tail_local),
            "z_axis": list(m.to_3x3().col[2].normalized()),
        })
    json.dump({"source": "Mesh2Motion rig-human.glb (CC0)", "bones": bones},
              open(os.path.join(DATA, "m2m_rig.json"), "w"), indent=1)
    os.makedirs(os.path.join(DATA, "animations"), exist_ok=True)
    for fn in ("human-base-animations.glb",):
        shutil.copy(os.path.join(m2m, "static", "animations", fn), os.path.join(DATA, "animations", fn))
    print("m2m rig:", len(bones), "bones")


def build_eyes(mh):
    d = os.path.join(DATA, "eyes")
    os.makedirs(d, exist_ok=True)
    for fn in ("high-poly/high-poly.obj", "high-poly/high-poly.mhclo", "materials/brown_eye.png"):
        shutil.copy(os.path.join(mh, "eyes", fn), os.path.join(d, os.path.basename(fn)))
    shutil.copy(os.path.join(mh, "modifiers", "modeling_modifiers.json"), os.path.join(DATA, "modeling_modifiers.json"))


FACE_SCULPT_ETHNICITIES = ("african", "asian", "caucasian")


def _parse_bvh(path):
    """Joint names, parent indices and per-frame per-joint 3x3 rotations of a BVH file."""
    names, parents, chans, stack, pending = [], [], [], [], None
    lines = open(path).read().splitlines()
    i = 0
    while not lines[i].startswith("MOTION"):
        tok = lines[i].split()
        if tok and tok[0] in ("ROOT", "JOINT"):
            names.append(tok[1])
            parents.append(stack[-1] if stack else -1)
            pending = len(names) - 1
        elif tok and tok[0] == "End":
            pending = None
        elif tok and tok[0] == "{":
            stack.append(pending)
        elif tok and tok[0] == "}":
            stack.pop()
        elif tok and tok[0] == "CHANNELS":
            chans.append(tok[2:])
        i += 1
    frames = np.array([[float(x) for x in l.split()] for l in lines[i + 3:] if l.strip()])

    def rot(axis, deg):
        a = np.radians(deg)
        c, s = np.cos(a), np.sin(a)
        return {"X": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]),
                "Y": np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
                "Z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]

    R = np.tile(np.eye(3), (len(frames), len(names), 1, 1))
    for f, row in enumerate(frames):
        k = 0
        for j, ch in enumerate(chans):
            for c in ch:
                if c.endswith("rotation") and abs(row[k]) > 1e-4:
                    R[f, j] = R[f, j] @ rot(c[0], row[k])
                k += 1
    return names, parents, R


def build_face(mh):
    """Facial expression data (CC0): MakeHuman's 59 face pose units and its sculpted expression units.

    The pose-unit BVH is Z-up (MakeHuman auto-detects that), so its rotations already use Blender axes.
    Each rotation is world-aligned about the bone head and chains to the parent (MakeHuman's setPose).
    """
    names, parents, R = _parse_bvh(os.path.join(mh, "poseunits", "face-poseunits.bvh"))
    units = json.load(open(os.path.join(mh, "poseunits", "face-poseunits.json")))["framemapping"]
    skel = json.load(open(os.path.join(mh, "rigs", "default.mhskel")))
    w = json.load(open(os.path.join(mh, "rigs", "default_weights.mhw")))["weights"]
    # keep only joints that some unit rotates, plus their ancestors
    moving = np.abs(R - np.eye(3)).max(axis=(0, 2, 3)) > 1e-6
    keep = set()
    for j in np.nonzero(moving)[0]:
        while j >= 0 and j not in keep:
            keep.add(j)
            j = parents[j]
    keep = sorted(keep)
    remap = {j: i for i, j in enumerate(keep)}
    out = {
        "unit_names": np.array(units),
        "bone_names": np.array([names[j] for j in keep]),
        "bone_parents": np.array([remap.get(parents[j], -1) for j in keep]),
        "bone_head_joint": np.array([skel["bones"][names[j]]["head"] for j in keep]),
        "unit_rot": R[:, keep].astype(np.float32),
    }
    nverts = len(np.load(os.path.join(DATA, "base_mesh.npz"))["coords"])
    total = np.zeros(nverts)
    for b, pairs in w.items():
        for vi, wt in pairs:
            total[vi] += wt
    out["weight_total"] = total.astype(np.float32)
    for b in out["bone_names"]:
        pairs = w.get(str(b), [])
        out["w|" + b + "|i"] = np.array([p[0] for p in pairs], dtype=np.int32)
        out["w|" + b + "|w"] = np.array([p[1] for p in pairs], dtype=np.float32)
    sculpt = []
    for eth in FACE_SCULPT_ETHNICITIES:
        d = os.path.join(mh, "targets", "expression", "units", eth)
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".target"):
                continue
            rows = [l.split() for l in open(os.path.join(d, fn)) if l.strip() and not l.startswith("#")]
            key = f"s|{eth}|{fn[:-7]}"
            out[key + "|i"] = np.array([int(r[0]) for r in rows], dtype=np.int32)
            out[key + "|d"] = mh_to_bl([[float(x) for x in r[1:4]] for r in rows]).astype(np.float32)
            if eth == FACE_SCULPT_ETHNICITIES[0]:
                sculpt.append(fn[:-7])
    out["sculpt_names"] = np.array(sculpt)
    np.savez_compressed(os.path.join(DATA, "face_units.npz"), **out)
    print("face:", len(units), "pose units over", len(keep), "bones;", len(sculpt), "sculpted units")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--makehuman", required=True, help="path to makehuman/makehuman/data")
    ap.add_argument("--mesh2motion", help="path to mesh2motion-app checkout")
    ap.add_argument("--only", choices=["face"], help="rebuild just one data file")
    a = ap.parse_args()
    os.makedirs(DATA, exist_ok=True)
    if a.only == "face":
        return build_face(a.makehuman)
    n = build_base(a.makehuman)
    build_targets(a.makehuman, n)
    build_skeleton(a.makehuman, n)
    build_eyes(a.makehuman)
    build_face(a.makehuman)
    build_m2m(a.mesh2motion)


if __name__ == "__main__":
    sys.exit(main())
