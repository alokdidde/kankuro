"""Check a GLB against the Mesh2Motion human standard."""
import math

import bpy
import numpy as np
from mathutils import Vector

from . import rig, util


def check(path):
    util.reset_scene()
    bpy.ops.import_scene.gltf(filepath=path)
    checks = []

    def add(name, ok, detail=None):
        checks.append({"check": name, "pass": bool(ok), **({"detail": detail} if detail is not None else {})})

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    add("one_armature", len(arms) == 1, f"{len(arms)} armatures")
    if len(arms) != 1:
        return {"glb": path, "valid": False, "checks": checks}
    arm = arms[0]
    ref = {b["name"]: b for b in rig.m2m_rig()}
    names = {b.name for b in arm.data.bones}
    missing = sorted(set(ref) - names)
    extra = sorted(names - set(ref))
    add("bone_names", not missing, {"missing": missing, "extra": extra})
    wrong_parent = [b.name for b in arm.data.bones if b.name in ref and
                    (b.parent.name if b.parent else None) != ref[b.name]["parent"]]
    add("hierarchy", not wrong_parent, {"wrong_parent": wrong_parent})
    # optional extra bones (tails, hanging ornaments, prop sockets) must hang under the standard skeleton
    groups, orphans = {}, []
    for n in extra:
        b = arm.data.bones[n]
        while b is not None and b.name not in ref:
            b = b.parent
        if b is None:
            orphans.append(n)
        else:
            groups.setdefault(b.name, []).append(n)
    add("extra_bones", not orphans, {"count": len(extra), "by_parent": groups, "unattached": orphans})
    worst, worst_bone = 0.0, None
    mw = arm.matrix_world
    for b in arm.data.bones:
        if b.name not in ref:
            continue
        m = (mw @ b.matrix_local).to_3x3()
        y = m.col[1].normalized()
        z = m.col[2].normalized()
        t = (Vector(ref[b.name]["tail"]) - Vector(ref[b.name]["head"])).normalized()
        a = max(math.degrees(y.angle(t)), math.degrees(z.angle(Vector(ref[b.name]["z_axis"]))))
        if a > worst:
            worst, worst_bone = a, b.name
    add("rest_orientation_matches_m2m", worst < 3.0, {"max_deg": round(worst, 2), "bone": worst_bone})
    # the glTF importer adds an "Icosphere" bone-display shape; it is not part of the file's content
    shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o not in shapes and o.visible_get()]
    skinned = [o for o in meshes if any(m.type == "ARMATURE" for m in o.modifiers)]
    add("meshes_skinned", meshes and len(skinned) == len(meshes),
        {"meshes": [o.name for o in meshes], "unskinned": [o.name for o in meshes if o not in skinned]})
    bad_w, max_inf, total = 0, 0, 0
    for o in skinned:
        gi = {g.index: g.name for g in o.vertex_groups}
        for v in o.data.vertices:
            ws = [g.weight for g in v.groups if g.weight > 1e-4 and gi.get(g.group) in names]
            total += 1
            max_inf = max(max_inf, len(ws))
            if abs(sum(ws) - 1) > 0.02:
                bad_w += 1
    add("weights_normalised", bad_w == 0, {"vertices": total, "bad": bad_w})
    add("max_4_influences", max_inf <= 4, {"max": max_inf})
    crease = _ball_at_crease(arm, skinned)
    if crease:
        add("ball_at_toe_crease", all(abs(v) <= 0.015 for v in crease.values()),
            {"cm_from_crease": {k: round(v * 100, 1) for k, v in crease.items()}})
    if meshes:
        co = np.concatenate([util.get_coords(o) @ np.array(o.matrix_world)[:3, :3].T + np.array(o.matrix_world)[:3, 3]
                             for o in meshes])
        add("feet_on_ground", abs(co[:, 2].min()) < 0.03, {"min_z": round(float(co[:, 2].min()), 4)})
    shape_names = {kb.name for o in meshes if o.data.shape_keys for kb in o.data.shape_keys.key_blocks[1:]}
    from ..face import ARKIT_NAMES
    if shape_names & set(ARKIT_NAMES):  # only judge files that carry (some) ARKit blendshapes
        missing_shapes = [n for n in ARKIT_NAMES if n not in shape_names]
        add("arkit_blendshapes", not missing_shapes,
            {"found": len(shape_names), "missing": missing_shapes,
             "meshes": [o.name for o in meshes if o.data.shape_keys]})
        # default morph weights must be 0, or engines show every expression at once
        on = sorted({kb.name for o in meshes if o.data.shape_keys
                     for kb in o.data.shape_keys.key_blocks[1:] if abs(kb.value) > 1e-3})
        add("blendshapes_at_rest", not on, {"nonzero_default_weights": on[:10], "count": len(on)})
    acts = [a.name for a in bpy.data.actions]
    return {"glb": path, "valid": all(c["pass"] for c in checks), "checks": checks, "animations": acts}


def _ball_at_crease(arm, meshes):
    """For each foot, how far (m, + = towards the toes) the ball bone's head is from where the skin
    hands over from foot to ball (ball share of the foot+ball weight crossing 0.5). The toes bend
    there, so a pivot far from it kinks and pinches the toes at push-off. {} when nothing is weighted
    to the ball bones."""
    mw = arm.matrix_world
    out = {}
    for s in ("l", "r"):
        fn, bn = f"foot_{s}", f"ball_{s}"
        if fn not in arm.data.bones or bn not in arm.data.bones:
            continue
        b = arm.data.bones[bn]
        head = np.array(mw @ b.head_local)
        fwd = np.array((mw.to_3x3() @ (b.tail_local - b.head_local)))
        fwd[2] = 0.0
        if np.linalg.norm(fwd) < 1e-6:
            continue
        fwd /= np.linalg.norm(fwd)
        d_all, f_all = [], []
        for o in meshes:
            gi = {g.index: g.name for g in o.vertex_groups}
            if fn not in gi.values() and bn not in gi.values():
                continue
            M = np.array(o.matrix_world)
            for v in o.data.vertices:
                wf = wb = 0.0
                for g in v.groups:
                    n = gi.get(g.group)
                    if n == fn:
                        wf = g.weight
                    elif n == bn:
                        wb = g.weight
                if wf + wb > 0.5:
                    p = M[:3, :3] @ np.array(v.co) + M[:3, 3]
                    d_all.append(float((p - head) @ fwd))
                    f_all.append(wb / (wf + wb))
        d, f = np.array(d_all), np.array(f_all)
        if not len(d) or f.max() < 0.5:
            continue
        mid = (f > 0.2) & (f < 0.8)
        # where the blend is, or for a hard step, where the toe weights begin
        crease = float(np.median(d[mid])) if mid.sum() >= 3 else float(d[f >= 0.5].min())
        out[s] = -crease
    return out
