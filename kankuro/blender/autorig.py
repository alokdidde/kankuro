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
from . import anim, body, extras, motion, render, rig, util


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
    # crotch: the x~0 column is deep through the torso; between the legs it is empty, or only a thin
    # sliver where the inner thighs touch. Walk up from the feet to the first height where the
    # column becomes as deep as the torso above it (walking down from the top would stop at the
    # neck of a big-headed cartoon).
    col = co[np.abs(co[:, 0]) < H * 0.006]
    zs = np.arange(0.05, 0.8, 0.005) * H
    depth = np.zeros(len(zs))
    for i, z in enumerate(zs):
        s = col[np.abs(col[:, 2] - z) < tol]
        depth[i] = s[:, 1].max() - s[:, 1].min() if len(s) else 0.0
    crotch = None
    torso = np.percentile(depth[depth > 0], 75) if np.any(depth > 0) else 0.0
    for i in range(len(zs) - 4):
        if torso > 0.04 * H and np.all(depth[i:i + 4] > 0.6 * torso):
            crotch = zs[i] - 0.0025 * H
            break
    if crotch is None or crotch < 0.1 * H:
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
    L["neck"] = _find_neck(co, H, crotch, tol, gap)
    z_chest = crotch + ((L["neck"] or crotch + (H - crotch) * 0.7) - crotch) * 0.65
    # torso half width over the chest region; arms that touch the sides (A-pose) widen some of the
    # slices, so take a low percentile rather than the slice at z_chest alone
    neck_z = L["neck"] or crotch + (H - crotch) * 0.7
    widths = [torso_half_width(crotch + (neck_z - crotch) * f)[0] for f in np.linspace(0.4, 0.75, 8)]
    widths = [w for w in widths if w is not None]
    if not widths:
        raise CliError("autorig_failed", "Could not find the torso at chest height")
    hw = float(np.percentile(widths, 25))
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
    # hand tips: the points furthest from the chest along the surface on each side, above the knees
    # (in a T-pose these are the outermost points; with arms down, the outermost point is an elbow or hip)
    L["tip_l"], L["tip_r"] = _hand_tips(co, H, crotch, z_chest, L["neck"] or crotch + 0.75 * (H - crotch))
    # legs: below the crotch, split by side
    for side, sg in (("l", 1), ("r", -1)):
        leg = co[(co[:, 2] < crotch) & (co[:, 0] * sg > 0)]
        L[f"leg_{side}"] = leg
        if len(leg) == 0:
            raise CliError("autorig_failed", f"No {side} leg found below the crotch")
    return L


def _hand_tips(co, H, crotch, z_chest, z_neck, cell=0.012):
    """Geodesic extremities for the hands: Dijkstra over a voxelisation of the surface points,
    from the chest centre."""
    import heapq
    vox = np.floor(co / (H * cell)).astype(np.int64)
    keys, inv = np.unique(vox, axis=0, return_inverse=True)
    inv = inv.ravel()
    centre = np.zeros((len(keys), 3))
    np.add.at(centre, inv, co)
    centre /= np.bincount(inv, minlength=len(keys))[:, None]
    index = {tuple(k): i for i, k in enumerate(keys.tolist())}
    offs = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if dx or dy or dz]
    dist = np.full(len(keys), np.inf)
    src = np.nonzero((np.abs(centre[:, 0]) < H * 0.03) & (np.abs(centre[:, 2] - z_chest) < H * 0.03))[0]
    heap = [(0.0, int(i)) for i in src]
    dist[src] = 0.0
    kl = keys.tolist()
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist[i]:
            continue
        x, y, z = kl[i]
        for dx, dy, dz in offs:
            j = index.get((x + dx, y + dy, z + dz))
            if j is None:
                continue
            nd = d + float(np.linalg.norm(centre[j] - centre[i]))
            if nd < dist[j]:
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    tips = []
    for sg in (1, -1):
        # below the neck (long hair and ears are far too), above the knees
        ok = (np.isfinite(dist) & (centre[:, 0] * sg > H * 0.03) & (centre[:, 2] > max(crotch * 0.75, H * 0.25))
              & (centre[:, 2] < z_neck))
        if not np.any(ok):
            tips.append(co[np.argmax(co[:, 0] * sg)])
            continue
        v = np.nonzero(ok)[0][np.argmax(dist[ok])]
        pts = co[inv == v]
        shoulder = np.array([sg * H * 0.1, 0.0, z_neck])
        tips.append(pts[np.argmax(np.linalg.norm(pts - shoulder, axis=1))])
    return tips[0], tips[1]


def _find_neck(co, H, crotch, tol, gap):
    """Height of the neck: walking down from the top of the head, the narrowest centre cross-section
    after the head and before the shoulders widen it again. None when there is no clear neck
    (e.g. long hair over the shoulders)."""
    zs = np.arange(0.985, 0.0, -0.005) * H
    zs = zs[zs > crotch + (H - crotch) * 0.35]
    w = []
    for z in zs:
        s = _slice(co, z, tol)
        hw = np.nan
        for lo, hi in _components_1d(s[:, 0], gap):
            if lo <= 0 <= hi:
                hw = hi - lo
        w.append(hw)
    w = np.array(w)
    head = 0.0
    neck, neck_w = None, None
    for z, x in zip(zs, w):
        if np.isnan(x):
            continue
        if neck is None:
            head = max(head, x)
            if x < 0.8 * head:
                neck, neck_w = z, x
        elif x < neck_w:
            neck, neck_w = z, x
        elif x > 1.5 * neck_w:
            if neck < 0.92 * H:   # higher up it is a snout, a hat brim... not a neck
                return float(neck)
            head, neck, neck_w = x, None, None
    return None


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

    # spine heights map piecewise: crotch -> neck -> top of the head (big cartoon heads keep their
    # shoulders where they are)
    t_neck = T["neck"] or T["crotch"] + 0.75 * (T["H"] - T["crotch"])
    g_neck = G["neck"] or G["crotch"] + (t_neck - T["crotch"]) * (G["H"] - G["crotch"]) / (T["H"] - T["crotch"])

    def map_z(z0):
        return float(np.interp(z0, [T["crotch"], t_neck, T["H"]], [G["crotch"], g_neck, G["H"]],
                               left=None, right=None)) if T["crotch"] <= z0 <= T["H"] else \
            G["crotch"] + (z0 - T["crotch"]) * (g_neck - G["crotch"]) / (t_neck - T["crotch"])

    def spine_map(p):
        z = map_z(p[2])
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
        g_hip_z = map_z(t_hip[2])
        g_hip = _leg_center(G, side, G["crotch"] - G["H"] * 0.04)
        g_hip[2] = g_hip_z
        g_ank = _leg_center(G, side, t_ank[2] * G["crotch"] / T["crotch"])
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
    util.deselect_all()
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
    """Copy weights from src to dst: barycentric weights of the nearest point on src's surface.
    (Done by hand rather than with a Data Transfer modifier, which can't be applied to meshes
    with shape keys.)"""
    from mathutils.bvhtree import BVHTree
    names = rig.deform_bone_names()
    W = util.weight_matrix(src, names)
    sco = util.get_coords(src)
    me = src.data
    me.calc_loop_triangles()
    tris = np.array([t.vertices[:] for t in me.loop_triangles])
    bvh = BVHTree.FromPolygons(sco.tolist(), tris.tolist())
    dco = util.get_coords(dst)
    out = np.zeros((len(dco), len(names)))
    for k, p in enumerate(dco):
        loc, _, ti, _ = bvh.find_nearest(Vector(p))
        if ti is None:
            continue
        a, b, c = sco[tris[ti]]
        v0, v1, v2 = b - a, c - a, np.array(loc) - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-18:
            bw = np.array([1.0, 0, 0])
        else:
            v = (d11 * d20 - d01 * d21) / den
            w = (d00 * d21 - d01 * d20) / den
            bw = np.clip(np.array([1 - v - w, v, w]), 0, 1)
        out[k] = bw @ W[tris[ti]]
    util.set_weight_matrix(dst, out, names)


def _proxy(obj, kind, size):
    """A copy of obj that bone heat can solve: vertices welded (glTF splits them at every UV seam),
    or a watertight voxel remesh."""
    import bmesh
    proxy = obj.copy()
    proxy.data = obj.data.copy()
    proxy.modifiers.clear()
    proxy.vertex_groups.clear()
    proxy.parent = None
    bpy.context.scene.collection.objects.link(proxy)
    if proxy.data.shape_keys:
        proxy.shape_key_clear()
    if kind == "weld":
        bm = bmesh.new()
        bm.from_mesh(proxy.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size)
        bm.to_mesh(proxy.data)
        bm.free()
    else:
        rm = proxy.modifiers.new("remesh", "REMESH")
        rm.mode = "VOXEL"
        rm.voxel_size = size
        with bpy.context.temp_override(object=proxy, active_object=proxy, selected_objects=[proxy]):
            bpy.ops.object.modifier_apply(modifier=rm.name)
    return proxy


def _detach(obj):
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.parent = None


PROXIES = (("weld", 0.002), ("voxel", 1 / 160), ("voxel", 1 / 110), ("voxel", 1 / 75), ("voxel", 1 / 50))


def skin(obj, arm, method="auto"):
    """Bone heat on the mesh itself, else on proxies (welded, then voxel remeshes from fine to
    coarse) with the weights copied back by nearest surface point, else distance weights."""
    report = {"tried": {}}
    H = max(obj.dimensions)
    if method in ("auto", "heat"):
        frac = _heat(obj, arm)
        report["tried"]["heat"] = round(frac, 4)
        if frac < 0.01:
            report["method"] = "heat"
            report["filled_vertices"] = _fill_unweighted(obj)
            return report
        if method == "heat":
            raise CliError("autorig_failed", f"Bone heat left {frac:.1%} of vertices unweighted",
                           hint="Try --method auto (uses proxies) or --method proximity")
        best = None
        for kind, size in PROXIES:
            proxy = _proxy(obj, kind, H * size)
            pf = _heat(proxy, arm)
            name = f"{kind}_{len(proxy.data.vertices)}v"
            report["tried"][name] = round(pf, 4)
            if best is None or pf < best[0]:
                if best:
                    bpy.data.objects.remove(best[2], do_unlink=True)
                best = (pf, name, proxy)
            else:
                bpy.data.objects.remove(proxy, do_unlink=True)
            if pf < 0.01:
                break
        pf, name, proxy = best
        if pf < 0.25:   # islands heat could not reach (loose hair cards...) take their neighbours' weights
            _detach(obj)
            _fill_unweighted(proxy)
            _transfer(proxy, obj)
            bpy.data.objects.remove(proxy, do_unlink=True)
            report["filled_vertices"] = _fill_unweighted(obj)
            util.add_armature_modifier(obj, arm)
            report["method"] = "heat_proxy"
            report["proxy"] = name
            return report
        bpy.data.objects.remove(proxy, do_unlink=True)
    _detach(obj)
    _proximity(obj, arm)
    util.add_armature_modifier(obj, arm)
    report["method"] = "proximity"
    return report


# ---------------------------------------------------------------- pipeline

FACING_YAW = {"-y": 0.0, "+y": math.pi, "+x": -math.pi / 2, "-x": math.pi / 2}   # rotation that turns it to -Y


def _normalise(objs, facing):
    """Stand the mesh on z=0, centred, facing -Y, in metres. Returns (facing, offset, scale)."""
    co = np.concatenate([util.get_coords(o) for o in objs])
    lo, hi = co.min(0), co.max(0)
    H = hi[2] - lo[2]
    if max(hi[0] - lo[0], hi[1] - lo[1]) > 2.5 * H:
        raise CliError("autorig_failed", "Mesh does not look upright (height is not the largest extent)",
                       hint="Export the model Z-up (glTF Y-up), standing")
    if facing == "auto":
        pts = np.concatenate([surface_points(o, 60000) for o in objs])   # low-poly shins have few vertices
        # arms (T/A-pose) and shoulders span the side-to-side axis
        upper = pts[pts[:, 2] > lo[2] + H * 0.6]
        ext = upper.max(0) - upper.min(0)
        axis = 0 if ext[1] > 1.15 * ext[0] else 1          # forward axis index: x if the span is along y
        # feet reach much further forward of the shin than behind it
        low = pts[pts[:, 2] < lo[2] + H * 0.04]
        shin = pts[(pts[:, 2] > lo[2] + H * 0.08) & (pts[:, 2] < lo[2] + H * 0.12)]
        toe_dir = -1.0
        if len(low) and len(shin):
            c = (shin[:, axis].min() + shin[:, axis].max()) / 2
            toe_dir = (low[:, axis].max() - c) - (c - low[:, axis].min())
        facing = ("-" if toe_dir <= 0 else "+") + "xy"[axis]
    # glTF is metres; a body taller than 20 units was modelled in centimetres
    scale = 0.01 if H > 20 else 1.0
    M = Matrix.Scale(scale, 4) @ Matrix.Rotation(FACING_YAW[facing], 4, "Z")
    for o in objs:
        o.data.transform(M, shape_keys=True)
    co = np.concatenate([util.get_coords(o) for o in objs])
    c = np.array([(co[:, 0].min() + co[:, 0].max()) / 2, (co[:, 1].min() + co[:, 1].max()) / 2, co[:, 2].min()])
    for o in objs:
        o.data.transform(Matrix.Translation(Vector(-c)), shape_keys=True)
        o.data.update()
    return facing, c, scale


def _reground(obj, arm):
    """Straightening A-posed or splayed legs to the T-pose lifts or sinks the feet: put them back on
    z=0 (root stays at the origin, as in Mesh2Motion)."""
    dz = float(util.get_coords(obj)[:, 2].min())
    if abs(dz) < 1e-4:
        return
    obj.data.transform(Matrix.Translation((0, 0, -dz)), shape_keys=True)
    obj.data.update()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in arm.data.edit_bones:
        if eb.name != "root":
            eb.translate(Vector((0, 0, -dz)))
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def chain_from_part(obj, arm, cid, verts, count=6):
    """Extra bone chain through a part of the mesh (a tail): from where it meets the rest of the body to
    its far end, through the centroids of slices at growing distance. Weights the part to the chain.
    Returns the chain record for motion.py, or None if the part is too small."""
    from mathutils import kdtree
    co = util.get_coords(obj)
    part = np.zeros(len(co), bool)
    part[list(verts)] = True
    if part.sum() < 20 or (~part).sum() < 20:
        return None
    kd = kdtree.KDTree(int((~part).sum()))
    for i in np.nonzero(~part)[0]:
        kd.insert(Vector(co[i]), int(i))
    kd.balance()
    pidx = np.nonzero(part)[0]
    near = np.array([kd.find(Vector(co[i]))[2] for i in pidx])
    root = co[pidx[np.argsort(near)[:10]]].mean(0)
    d = np.linalg.norm(co[pidx] - root, axis=1)
    edges = np.linspace(0, d.max() + 1e-6, count * 3 + 1)
    cents = [root]
    for a, b in zip(edges[:-1], edges[1:]):
        m = (d >= a) & (d < b)
        if m.sum() >= 3:
            cents.append(co[pidx[m]].mean(0))
    cents.append(co[pidx[np.argmax(d)]])
    cents = np.array(cents)
    seg = np.linalg.norm(np.diff(cents, axis=0), axis=1)
    sc = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, sc[-1], count + 1)
    pts = np.stack([np.interp(t, sc, cents[:, k]) for k in range(3)], 1)
    # parent: the standard bone nearest to where the part attaches (a tail's root is by the pelvis)
    names = rig.deform_bone_names()
    W = util.weight_matrix(obj, names)

    def seg_dist(n):
        bb = arm.data.bones[n]
        h, t = np.array(bb.head_local), np.array(bb.tail_local)
        ab = t - h
        u = np.clip((root - h) @ ab / max(ab @ ab, 1e-12), 0, 1)
        return float(np.linalg.norm(root - (h + u * ab)))
    parent = min(names, key=seg_dist)
    bones = extras.chain_bones(cid, parent, pts)
    extras.add_bones(arm, bones)
    cn = [x["name"] for x in bones]
    Wc, _ = extras._segment_weights(co[pidx], pts, cn)
    allb = names + cn
    Wall = np.zeros((len(co), len(allb)))
    Wall[:, :len(names)] = W
    Wall[pidx] = 0
    Wall[pidx, len(names):] = Wc
    util.set_weight_matrix(obj, Wall, allb)
    return {"id": cid, "bones": cn, "parent": parent, "spring": dict(extras.SPRING), "radius": 0.03,
            "enabled": True}


def _extras(obj, arm, props, chains):
    """Props in the hands and extra chains on an autorigged character (a stand-in for build.Built)."""
    from types import SimpleNamespace

    from . import props as props_mod
    b = SimpleNamespace(arm=arm, body=obj, meshes=[obj], res=SimpleNamespace(bones=rig.deform_bone_names()),
                        grips=[], chains=[], warnings=[], hair=None, capsules={}, spec={})
    for cid, part, count in chains:
        parts = list(obj.get("parts", []))
        groups = obj.get("groups", {})
        if part in parts:
            at = np.zeros(len(obj.data.vertices), np.int32)
            obj.data.attributes["part"].data.foreach_get("value", at)
            verts = np.nonzero(at == parts.index(part))[0].tolist()
        elif part in groups:
            verts = list(groups[part])
        else:
            raise CliError("unknown_part", f"--extra-chain {cid}: no mesh part or vertex group '{part}'",
                           hint="Mesh parts: " + (", ".join(parts) or "(one mesh)") + "; vertex groups: "
                           + (", ".join(groups.keys()) or "(none)"))
        ch = chain_from_part(obj, arm, cid, verts, count)
        if ch is None:
            raise CliError("bad_value", f"--extra-chain {cid}: part '{part}' is too small or is the whole mesh")
        b.chains.append(ch)
    if props:
        props_mod.build_all(b, {"props": list(props)}, os.getcwd())
    b.capsules = motion.leg_capsules(b)
    return b


def run(src, out, facing="auto", animations=(), render_dir=None, method="auto", props=(), chains=()):
    """props: prop specs (as in character.json) to put in the hands; chains: (id, part or vertex group,
    count) extra chains to cut out of the mesh (a tail)."""
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

    before_actions = set(bpy.data.actions)
    obj = import_mesh_file(src, "Character", any_pose=True, keep_parts=bool(chains))
    # clips that came with the file would clash with Mesh2Motion clip names (Walk, Idle...)
    for a in [a for a in bpy.data.actions if a not in before_actions]:
        bpy.data.actions.remove(a)
    facing, offset, scale = _normalise([obj], facing)
    co = surface_points(obj)
    pos, G = fit_skeleton(co, tmpl_co, tmpl_pos)
    to_input = (Matrix.Rotation(FACING_YAW[facing], 4, "Z").inverted() @ Matrix.Scale(1 / scale, 4)
                @ Matrix.Translation(Vector(offset)))
    joints = {n: [round(float(x), 4) for x in to_input @ Vector(h)] for n, (h, _) in pos.items()}
    arm = rig.create_armature(pos)
    report = skin(obj, arm, method)
    if obj.parent != arm:
        util.add_armature_modifier(obj, arm)
    # A-pose (or any pose) -> Mesh2Motion T-pose rest with exact bone orientations
    rig.pose_to_tpose(arm)
    rig.apply_pose_as_rest(arm, [obj])
    _reground(obj, arm)
    extra = _extras(obj, arm, props, chains) if (props or chains) else None
    with_anims = anim.attach(arm, list(animations)) if animations else []
    warnings = []
    if extra is not None and with_anims:
        for tr in arm.animation_data.nla_tracks:
            for st in tr.strips:
                warnings += motion.prepare(extra, st.action)
    renders = None
    if render_dir:
        clip = with_anims[0] if with_anims else None
        shown = extra.meshes if extra is not None else [obj]
        paths, sheet = render.render_views(shown, render_dir, views=("front", "side"), size=512, samples=10,
                                           prefix="autorig_tpose")
        renders = {"tpose": sheet}
        if clip:
            arm.animation_data.action = bpy.data.actions[clip]
            if hasattr(arm.animation_data, "action_slot") and len(bpy.data.actions[clip].slots):
                arm.animation_data.action_slot = bpy.data.actions[clip].slots[0]
            fr = bpy.data.actions[clip].frame_range
            bpy.context.scene.frame_set(int(fr[0] + (fr[1] - fr[0]) * 0.3))
            _, sheet2 = render.render_views(shown, render_dir, views=("front", "side"), size=512, samples=10,
                                            prefix=f"autorig_{clip}")
            renders["posed"] = sheet2
            arm.animation_data.action = None
            bpy.context.scene.frame_set(0)
    for o in bpy.data.objects:
        if o.name in bpy.context.view_layer.objects:
            o.select_set(o in (obj, arm) or (extra is not None and o in extra.meshes))
    bpy.context.view_layer.objects.active = arm
    kwargs = dict(filepath=out, export_format="GLB", use_selection=True, export_skins=True,
                  export_animations=bool(with_anims))
    if with_anims:
        kwargs["export_animation_mode"] = "NLA_TRACKS"
    bpy.ops.export_scene.gltf(**kwargs)
    return {
        "glb": out, "skinning": report, "facing_detected": facing,
        "moved_by": [round(float(x), 4) for x in -offset], "scaled_by": scale, "height_m": round(float(G["H"]), 3),
        "landmarks": {"crotch_z": round(float(G["crotch"]), 3), "chest_half_width": round(float(G["chest_half_width"]), 3),
                      "hand_tip_l": [round(float(x), 3) for x in G["tip_l"]],
                      "hand_tip_r": [round(float(x), 3) for x in G["tip_r"]]},
        "joints": joints,
        "skeleton": {"standard": "mesh2motion-human", "bones": len(arm.data.bones), "rest_pose": "T"},
        "animations": with_anims, "renders": renders, "seconds": round(time.time() - t0, 2),
        **({"extra_bones": [b.name for b in arm.data.bones if b.name not in set(rig.m2m_bone_names())],
            "warnings": warnings + extra.warnings} if extra is not None else {}),
        "tip": "Check renders: limbs should bend at the joints. If the fit is off, make sure the model "
               "stands upright in T- or A-pose with legs apart, then retry.",
    }
