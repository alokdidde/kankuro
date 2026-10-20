"""Auto-rig any humanoid mesh (T- or A-pose) to the Mesh2Motion human skeleton.

1. Normalise: join meshes, feet on z=0, centred, facing -Y (auto-detected from the feet).
2. Landmarks (same detector on the target and on our neutral template body): crotch, legs,
   torso centre line, hand tips, shoulders.
3. Fit: template joints are mapped chain by chain (spine scaled between crotch and head top,
   arms/legs by a similarity transform from shoulder->hand tip / hip->ankle).
4. Skin: Blender bone-heat weights; falls back to a voxel-remeshed proxy and then to
   distance weights for meshes heat cannot solve (non-manifold, many parts).
5. Convert to the Mesh2Motion T-pose rest with exact bone orientations, export GLB.
"""
import math
import os
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector

from ..errors import CliError
from . import anim, body, render, rig, util


# ---------------------------------------------------------------- landmarks

def surface_points(obj, n=150000, seed=0):
    """Area-weighted random points on the mesh surface (robust to low-poly meshes)."""
    me = obj.data
    me.calc_loop_triangles()
    co = util.get_coords(obj)
    tris = np.array([t.vertices[:] for t in me.loop_triangles])
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(tris), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    pts = a[idx] * (1 - s)[:, None] + b[idx] * (s * (1 - r2))[:, None] + c[idx] * (s * r2)[:, None]
    return np.concatenate([pts, co])


def _slice(co, z, tol):
    return co[np.abs(co[:, 2] - z) < tol]


def _components_1d(xs, gap):
    xs = np.sort(xs)
    if len(xs) == 0:
        return []
    splits = np.nonzero(np.diff(xs) > gap)[0]
    out, start = [], 0
    for s in list(splits) + [len(xs) - 1]:
        out.append((xs[start], xs[s]))
        start = s + 1
    return out


def landmarks(co):
    H = co[:, 2].max()
    tol = H * 0.006
    gap = H * 0.012
    L = {"H": H}
    # crotch: lowest height where the centre line x~0 hits the mesh
    crotch = None
    for z in np.arange(0.2, 0.7, 0.004) * H:
        s = _slice(co, z, tol)
        if len(s) and np.any(np.abs(s[:, 0]) < H * 0.012):
            crotch = z
            break
    if crotch is None:
        raise CliError("autorig_failed", "Could not find the crotch (legs must be apart, no long skirt/robe)",
                       hint="Rig the body without long garments, legs slightly apart")
    L["crotch"] = crotch
    # torso half width at chest level: component containing x~0
    def torso_half_width(z):
        s = _slice(co, z, tol)
        for lo, hi in _components_1d(s[:, 0], gap):
            if lo <= 0 <= hi:
                return max(-lo, hi), s
        return None, s
    z_chest = crotch + (H - crotch) * 0.45
    hw, s = torso_half_width(z_chest)
    if hw is None:
        raise CliError("autorig_failed", "Could not find the torso at chest height")
    L["chest_half_width"] = hw
    L["chest_z"] = z_chest
    # torso centre line (y) per height from points near x=0
    zs = np.linspace(crotch, H, 40)
    ys = []
    for z in zs:
        s = _slice(co, z, tol * 2)
        s = s[np.abs(s[:, 0]) < H * 0.03]
        ys.append((s[:, 1].min() + s[:, 1].max()) / 2 if len(s) else np.nan)
    ys = np.array(ys)
    ok = ~np.isnan(ys)
    L["center_y"] = (zs[ok], ys[ok])
    L["depth"] = {}
    # hand tips: extreme x on each side
    L["tip_l"] = co[np.argmax(co[:, 0])]
    L["tip_r"] = co[np.argmin(co[:, 0])]
    # legs: below the crotch, split by side
    for side, sg in (("l", 1), ("r", -1)):
        leg = co[(co[:, 2] < crotch) & (co[:, 0] * sg > 0)]
        L[f"leg_{side}"] = leg
        if len(leg) == 0:
            raise CliError("autorig_failed", f"No {side} leg found below the crotch")
    return L


def _leg_center(L, side, z):
    leg = L[f"leg_{side}"]
    H = L["H"]
    s = leg[np.abs(leg[:, 2] - z) < H * 0.01]
    if len(s) == 0:
        s = leg[np.argsort(np.abs(leg[:, 2] - z))[:20]]
    return np.array([(s[:, 0].min() + s[:, 0].max()) / 2, (s[:, 1].min() + s[:, 1].max()) / 2, z])


def _center_y(L, z):
    zs, ys = L["center_y"]
    return float(np.interp(z, zs, ys))


def _similarity(a0, a1, b0, b1):
    """Matrix mapping segment a0->a1 onto b0->b1 (rotation by the minimal arc + uniform scale)."""
    va, vb = Vector(a1 - a0), Vector(b1 - b0)
    q = va.normalized().rotation_difference(vb.normalized())
    s = vb.length / max(va.length, 1e-9)
    return (Matrix.Translation(Vector(b0)) @ q.to_matrix().to_4x4() @ Matrix.Scale(s, 4)
            @ Matrix.Translation(-Vector(a0)))


ARM = ["clavicle", "upperarm", "lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky"]
LEG = ["thigh", "calf", "foot", "ball"]


def fit_skeleton(co, tmpl_co, tmpl_pos):
    """Map template joint positions onto the target mesh. Returns {bone: [head, tail]}."""
    T = landmarks(tmpl_co)
    G = landmarks(co)
    out = {}

    def spine_map(p):
        f = (p[2] - T["crotch"]) / (T["H"] - T["crotch"])
        z = G["crotch"] + f * (G["H"] - G["crotch"])
        sy = G["chest_half_width"] / T["chest_half_width"]
        y = _center_y(G, z) + (p[1] - _center_y(T, p[2])) * sy
        return np.array([p[0] * sy, y, z])

    # arms: shoulder anchor from the template's upperarm head, mapped to the target torso width
    arm_maps = {}
    for side, sg in (("l", 1), ("r", -1)):
        t_sh = np.array(tmpl_pos[f"upperarm_{side}"][0])
        g_sh = spine_map(t_sh)
        g_sh[0] = sg * abs(t_sh[0]) * G["chest_half_width"] / T["chest_half_width"]
        arm_maps[side] = _similarity(t_sh, T[f"tip_{side}"], g_sh, G[f"tip_{side}"])
        # legs: hip -> ankle
        t_hip = np.array(tmpl_pos[f"thigh_{side}"][0])
        t_ank = np.array(tmpl_pos[f"foot_{side}"][0])
        g_hip_z = G["crotch"] + (t_hip[2] - T["crotch"]) * (G["H"] / T["H"])
        g_hip = _leg_center(G, side, G["crotch"] - G["H"] * 0.04)
        g_hip[2] = g_hip_z
        g_ank = _leg_center(G, side, t_ank[2] * G["H"] / T["H"])
        t_hip_c = _leg_center(T, side, T["crotch"] - T["H"] * 0.04)
        t_hip_c[2] = t_hip[2]
        t_ank_c = _leg_center(T, side, t_ank[2])
        M = _similarity(t_hip_c, t_ank_c, g_hip, g_ank)
        arm_maps["leg_" + side] = M

    for name, (h, t) in tmpl_pos.items():
        if name == "root":
            continue
        side = name[-1] if name[-2:] in ("_l", "_r") else None
        base = name.split("_")[0]
        if side and base in ARM:
            M = arm_maps[side]
            if base == "clavicle":
                out[name] = [spine_map(np.array(h)), np.array(M @ Vector(t))]
                continue
            out[name] = [np.array(M @ Vector(h)), np.array(M @ Vector(t))]
        elif side and base in LEG:
            M = arm_maps["leg_" + side]
            out[name] = [np.array(M @ Vector(h)), np.array(M @ Vector(t))]
        else:
            out[name] = [spine_map(np.array(h)), spine_map(np.array(t))]
    # keep chains connected: child heads equal parent tails where the template had them equal
    for b in rig.m2m_rig():
        par = b["parent"]
        if par and par in out and b["name"] in out:
            ph, pt = tmpl_pos[par]
            ch, _ = tmpl_pos[b["name"]]
            if np.linalg.norm(np.array(ch) - np.array(pt)) < 1e-4:
                out[par][1] = out[b["name"]][0].copy()
    pel = out["pelvis"][0]
    out["root"] = [np.zeros(3), np.array([0.0, float(pel[2]), 0.0])]
    return out, G


# ---------------------------------------------------------------- weights

def _unweighted_fraction(obj):
    n = len(obj.data.vertices)
    bad = sum(1 for v in obj.data.vertices if sum(g.weight for g in v.groups) < 1e-3)
    return bad / max(n, 1)


def _fill_unweighted(obj):
    """Give vertices heat missed (loose bits, buttons...) the weights of the nearest weighted vertex."""
    from mathutils import kdtree
    names = rig.deform_bone_names()
    W = util.weight_matrix(obj, names)
    s = W.sum(1)
    bad = np.nonzero(s < 1e-3)[0]
    if len(bad) == 0:
        return 0
    good = np.nonzero(s >= 1e-3)[0]
    co = util.get_coords(obj)
    kd = kdtree.KDTree(len(good))
    for i, g in enumerate(good):
        kd.insert(co[g], i)
    kd.balance()
    for b in bad:
        _, i, _ = kd.find(co[b])
        W[b] = W[good[i]]
    util.set_weight_matrix(obj, W, names)
    return int(len(bad))


def _heat(obj, arm):
    obj.vertex_groups.clear()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    return _unweighted_fraction(obj)


def _proximity(obj, arm, power=4.0):
    co = util.get_coords(obj)
    names = rig.deform_bone_names()
    segs = [(np.array(arm.data.bones[n].head_local), np.array(arm.data.bones[n].tail_local)) for n in names]
    D = np.zeros((len(co), len(names)))
    for j, (h, t) in enumerate(segs):
        d = t - h
        tt = np.clip(((co - h) @ d) / max(d @ d, 1e-9), 0, 1)
        D[:, j] = np.linalg.norm(co - (h + tt[:, None] * d), axis=1)
    W = 1.0 / np.maximum(D, 1e-4) ** power
    util.set_weight_matrix(obj, W, names, max_influences=4)


def _transfer(src, dst):
    """Copy weights from src to dst by nearest surface point (Data Transfer modifier)."""
    dst.vertex_groups.clear()
    for vg in src.vertex_groups:
        dst.vertex_groups.new(name=vg.name)
    mod = dst.modifiers.new("dt", "DATA_TRANSFER")
    mod.object = src
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    with bpy.context.temp_override(object=dst, active_object=dst, selected_objects=[dst]):
        bpy.ops.object.datalayout_transfer(modifier=mod.name)
        bpy.ops.object.modifier_apply(modifier=mod.name)


def skin(obj, arm, method="auto"):
    report = {}
    if method in ("auto", "heat"):
        frac = _heat(obj, arm)
        report["heat_unweighted"] = round(frac, 4)
        if frac < 0.01:
            report["method"] = "heat"
            report["filled_vertices"] = _fill_unweighted(obj)
            return report
        if method == "heat":
            raise CliError("autorig_failed", f"Bone heat left {frac:.1%} of vertices unweighted",
                           hint="Try --method auto (uses a remeshed proxy) or --method proximity")
        # proxy: watertight voxel remesh, heat there, transfer back
        proxy = obj.copy()
        proxy.data = obj.data.copy()
        proxy.modifiers.clear()
        proxy.parent = None
        bpy.context.scene.collection.objects.link(proxy)
        rm = proxy.modifiers.new("remesh", "REMESH")
        rm.mode = "VOXEL"
        rm.voxel_size = max(obj.dimensions) / 220
        with bpy.context.temp_override(object=proxy, active_object=proxy, selected_objects=[proxy]):
            bpy.ops.object.modifier_apply(modifier=rm.name)
        pf = _heat(proxy, arm)
        report["proxy_unweighted"] = round(pf, 4)
        if pf < 0.01:
            for m in list(obj.modifiers):
                obj.modifiers.remove(m)
            obj.parent = None
            _transfer(proxy, obj)
            bpy.data.objects.remove(proxy, do_unlink=True)
            report["filled_vertices"] = _fill_unweighted(obj)
            util.add_armature_modifier(obj, arm)
            report["method"] = "heat_proxy"
            return report
        bpy.data.objects.remove(proxy, do_unlink=True)
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.parent = None
    _proximity(obj, arm)
    util.add_armature_modifier(obj, arm)
    report["method"] = "proximity"
    return report


# ---------------------------------------------------------------- pipeline

def _normalise(objs, facing):
    from .build import import_mesh_file  # noqa
    co = np.concatenate([util.get_coords(o) for o in objs])
    lo, hi = co.min(0), co.max(0)
    H = hi[2] - lo[2]
    if hi[0] - lo[0] > 2.5 * H or hi[1] - lo[1] > 1.5 * H:
        raise CliError("autorig_failed", "Mesh does not look upright (height is not the largest extent)",
                       hint="Export the model Z-up (glTF Y-up), standing")
    # facing: toes point forward; compare lowest slice with ankle slice
    if facing == "auto":
        low = co[co[:, 2] < lo[2] + H * 0.02]
        ank = co[(co[:, 2] > lo[2] + H * 0.04) & (co[:, 2] < lo[2] + H * 0.07)]
        toe_dir = np.median(low[:, 1]) - np.median(ank[:, 1]) if len(low) and len(ank) else -1
        facing = "-y" if toe_dir <= 0 else "+y"
    M = Matrix.Identity(4)
    if facing == "+y":
        M = Matrix.Rotation(math.pi, 4, "Z")
    for o in objs:
        o.data.transform(M)
    co = np.concatenate([util.get_coords(o) for o in objs])
    c = np.array([(co[:, 0].min() + co[:, 0].max()) / 2, (co[:, 1].min() + co[:, 1].max()) / 2, co[:, 2].min()])
    for o in objs:
        util.set_coords(o, util.get_coords(o) - c)
    return facing, c


def run(src, out, facing="auto", animations=(), render_dir=None, method="auto"):
    from .build import import_mesh_file
    t0 = time.time()
    util.reset_scene()
    # template: neutral MakeHuman body with our fitted Mesh2Motion skeleton
    tres = body.build({}, {}, None)
    tmpl_obj = body.make_group_object(tres, "body", "_tmpl")
    tmpl_co = surface_points(tmpl_obj)
    tmpl_pos = {k: [np.array(h), np.array(t)] for k, (h, t) in rig.bone_positions(tres.arm).items()}
    bpy.data.objects.remove(tmpl_obj, do_unlink=True)
    bpy.data.objects.remove(tres.arm, do_unlink=True)

    obj = import_mesh_file(src, "Character")
    facing, offset = _normalise([obj], facing)
    co = surface_points(obj)
    pos, G = fit_skeleton(co, tmpl_co, tmpl_pos)
    arm = rig.create_armature(pos)
    report = skin(obj, arm, method)
    if obj.parent != arm:
        util.add_armature_modifier(obj, arm)
    # A-pose (or any pose) -> Mesh2Motion T-pose rest with exact bone orientations
    rig.pose_to_tpose(arm)
    rig.apply_pose_as_rest(arm, [obj])
    with_anims = anim.attach(arm, list(animations)) if animations else []
    renders = None
    if render_dir:
        clip = with_anims[0] if with_anims else None
        paths, sheet = render.render_views([obj], render_dir, views=("front", "side"), size=512, samples=10,
                                           prefix="autorig_tpose")
        renders = {"tpose": sheet}
        if clip:
            arm.animation_data.action = bpy.data.actions[clip]
            if hasattr(arm.animation_data, "action_slot") and len(bpy.data.actions[clip].slots):
                arm.animation_data.action_slot = bpy.data.actions[clip].slots[0]
            fr = bpy.data.actions[clip].frame_range
            bpy.context.scene.frame_set(int(fr[0] + (fr[1] - fr[0]) * 0.3))
            _, sheet2 = render.render_views([obj], render_dir, views=("front", "side"), size=512, samples=10,
                                            prefix=f"autorig_{clip}")
            renders["posed"] = sheet2
            arm.animation_data.action = None
            bpy.context.scene.frame_set(0)
    for o in bpy.data.objects:
        if o.name in bpy.context.view_layer.objects:
            o.select_set(o in (obj, arm))
    bpy.context.view_layer.objects.active = arm
    kwargs = dict(filepath=out, export_format="GLB", use_selection=True, export_skins=True,
                  export_animations=bool(with_anims))
    if with_anims:
        kwargs["export_animation_mode"] = "NLA_TRACKS"
    bpy.ops.export_scene.gltf(**kwargs)
    return {
        "glb": out, "skinning": report, "facing_detected": facing,
        "moved_by": [round(float(x), 4) for x in -offset], "height_m": round(float(G["H"]), 3),
        "landmarks": {"crotch_z": round(float(G["crotch"]), 3), "chest_half_width": round(float(G["chest_half_width"]), 3),
                      "hand_tip_l": [round(float(x), 3) for x in G["tip_l"]],
                      "hand_tip_r": [round(float(x), 3) for x in G["tip_r"]]},
        "skeleton": {"standard": "mesh2motion-human", "bones": len(arm.data.bones), "rest_pose": "T"},
        "animations": with_anims, "renders": renders, "seconds": round(time.time() - t0, 2),
        "tip": "Check renders: limbs should bend at the joints. If the fit is off, make sure the model "
               "stands upright in T- or A-pose with legs apart, then retry.",
    }
