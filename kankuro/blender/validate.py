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
