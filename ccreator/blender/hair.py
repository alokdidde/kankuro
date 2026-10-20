"""Procedural hair styles, grown from the current body's scalp so they always fit the head."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from .. import catalog
from . import garments, util

HEAD_BONES = ["head", "neck_01", "spine_03", "spine_02"]


def _head_frame(res, body_obj):
    co = util.get_coords(body_obj)
    hcol = res.bones.index("head")
    W = util.weight_matrix(body_obj, res.bones)
    head_v = np.nonzero(W[:, hcol] > 0.5)[0]
    hb = res.arm.data.bones["head"]
    z_ref = hb.head_local.z
    z_top = co[head_v, 2].max()
    yc = co[head_v, 1].mean()
    return co, W, head_v, z_ref, z_top, yc


def _theta(p, yc):
    """0 at the face (-Y), +/-pi at the back."""
    return math.atan2(p[0], -(p[1] - yc))


def _hairline(theta, z_ref, z_top, style):
    c = (1 + math.cos(theta)) / 2  # 1 front, 0 back
    front, side, back = style.get("hairline", (0.74, 0.55, 0.1))
    # piecewise blend: front->side for |theta|<90deg, side->back beyond
    if c >= 0.5:
        k = (c - 0.5) * 2
        f = side + (front - side) * k
    else:
        k = c * 2
        f = back + (side - back) * k
    return z_ref + (z_top - z_ref) * f


def _cap(res, body_obj, style, name):
    co, W, head_v, z_ref, z_top, yc = _head_frame(res, body_obj)
    ok = np.zeros(len(co), dtype=bool)
    hv = set(head_v.tolist())
    crest = style.get("crest")
    for i in head_v:
        p = co[i]
        if p[2] > _hairline(_theta(p, yc), z_ref, z_top, style):
            ok[i] = True
    me = body_obj.data
    faces = [list(p.vertices) for p in me.polygons if all(ok[v] for v in p.vertices)]
    used = np.unique(np.concatenate([np.array(f) for f in faces]))
    remap = -np.ones(len(co), dtype=np.int64)
    remap[used] = np.arange(len(used))
    obj = util.make_mesh(name, co[used], [remap[np.array(f)].tolist() for f in faces])
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    garments._largest_components(bm, min_frac=0.2)
    bm.to_mesh(obj.data)
    bm.free()
    sub = obj.modifiers.new("sub", "SUBSURF")
    sub.levels = 1
    garments.apply_modifier(obj, sub)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    garments._smooth_boundary(bm, iterations=10)
    bm.to_mesh(obj.data)
    bm.free()
    # Smooth away ears/face detail so hair reads as one mass, then sit it on the scalp
    sm = obj.modifiers.new("smooth", "SMOOTH")
    sm.factor = 1.0
    sm.iterations = 8
    garments.apply_modifier(obj, sm)
    bvh = garments.body_bvh(body_obj)
    garments.offset_along_normals(obj, style["offset"])
    if style.get("round"):
        co2 = util.get_coords(obj)
        c = np.array([0.0, yc, (z_ref + z_top) / 2])
        r = np.linalg.norm(co2 - c, axis=1)
        target = r.max()
        co2 = c + (co2 - c) * ((1 - style["round"]) + style["round"] * target / r)[:, None]
        util.set_coords(obj, co2)
    garments.conform(obj, bvh, style["offset"] * 0.9)
    if crest:
        co2 = util.get_coords(obj)
        k = np.clip(1 - (co2[:, 0] / crest) ** 2, 0, 1)
        obj.data.update()
        n = np.empty(len(co2) * 3)
        obj.data.vertices.foreach_get("normal", n)
        co2 += n.reshape(-1, 3) * (0.05 * k)[:, None]
        util.set_coords(obj, co2)
    return obj, (yc, z_ref, z_top)


def _curtain(res, body_obj, style, yc, z_ref, z_top, name="hair_curtain"):
    """Hair falling from the hairline: a smooth sheet around the head, grown downwards.

    For each angle around the head we cast rays at the body to find how far out the hair must sit,
    keep that radius non-decreasing as it falls (hair drapes outward over shoulders/back), then
    smooth. Side columns stop above the shoulders; back columns use the full length."""
    length = style.get("length", 0.0)
    if length <= 0:
        return None
    off = style["offset"] + 0.006
    bvh = garments.body_bvh(body_obj)
    bones = res.arm.data.bones
    z_sh = bones["upperarm_l"].head_local.z + 0.05
    th0 = math.radians(78)
    cols = 48
    thetas = np.linspace(th0, 2 * math.pi - th0, cols)
    thetas = np.where(thetas > math.pi, thetas - 2 * math.pi, thetas)
    step = 0.012
    z_bot = z_ref + 0.03 - length
    # start high on the head so the sheet overlaps the cap (no gaps at the back of the head)
    z_tops = np.array([max(_hairline(t, z_ref, z_top, style) + 0.035, z_ref + 0.62 * (z_top - z_ref))
                       for t in thetas])
    z_hi = z_tops.max()
    rows = int(math.ceil((z_hi - z_bot) / step)) + 1
    zs = z_hi - np.arange(rows) * step
    R = np.zeros((rows, cols))
    valid = np.zeros((rows, cols), dtype=bool)
    for j, t in enumerate(thetas):
        d = Vector((math.sin(t), -math.cos(t), 0))
        back = abs(t) > math.radians(125)
        floor_z = z_bot if back else max(z_bot, z_sh)
        for i, z in enumerate(zs):
            if z > z_tops[j] or z < floor_z:
                continue
            origin = Vector((0, yc, z)) + d * 0.32
            hit = bvh.ray_cast(origin, -d, 0.32)
            r = 0.32 - hit[3] if hit[0] is not None else 0.0
            R[i, j] = r
            valid[i, j] = True
    # hair falls outward: radius never shrinks going down; then smooth across angle and height
    for j in range(cols):
        run = 0.0
        for i in range(rows):
            if valid[i, j]:
                run = max(run, R[i, j])
                R[i, j] = run
    k = np.array([1, 2, 3, 2, 1], dtype=float)
    k /= k.sum()
    for _ in range(2):
        Rp = np.pad(R, ((0, 0), (2, 2)), mode="edge")
        R = np.stack([np.convolve(Rp[i], k, mode="valid") for i in range(rows)])
        Rp = np.pad(R, ((2, 2), (0, 0)), mode="edge")
        R = np.stack([np.convolve(Rp[:, j], k, mode="valid") for j in range(cols)], axis=1)
    bm = bmesh.new()
    vid = {}
    for i in range(rows):
        for j in range(cols):
            if not valid[i, j]:
                continue
            t = thetas[j]
            depth = max(0.0, z_tops[j] - zs[i])
            r = R[i, j] + off + 0.02 * min(1.0, depth / 0.15)
            x, y, z = math.sin(t) * r, yc - math.cos(t) * r, zs[i]
            if z < z_sh:
                # below the shoulders the hair lies on the back as a narrowing panel
                k = min(1.0, (z_sh - z) / 0.06)
                half = 0.11 - 0.03 * min(1.0, (z_sh - z) / 0.3)
                xb = max(-half, min(half, x * (half / 0.16)))
                hit = bvh.ray_cast(Vector((xb, yc + 0.4, z)), Vector((0, -1, 0)), 0.8)
                yb = (hit[0].y if hit[0] is not None else yc) + off + 0.01
                x = x + (xb - x) * k
                y = y + (yb - y) * k
            vid[i, j] = bm.verts.new((x, y, z))
    for i in range(rows - 1):
        for j in range(cols - 1):
            q = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]
            if all(x in vid for x in q):
                bm.faces.new([vid[x] for x in q])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = util.link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    obj.data.flip_normals() if hasattr(obj.data, "flip_normals") else None
    return obj


def _tube(name, points, radii, segs=12):
    bm = bmesh.new()
    rings = []
    for i, (p, r) in enumerate(zip(points, radii)):
        d = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
        a = d.orthogonal().normalized()
        b = d.cross(a).normalized()
        ring = [bm.verts.new(p + (a * math.cos(t) + b * math.sin(t)) * r)
                for t in np.linspace(0, 2 * math.pi, segs, endpoint=False)]
        rings.append(ring)
    for r0, r1 in zip(rings[:-1], rings[1:]):
        for j in range(segs):
            bm.faces.new((r0[j], r0[(j + 1) % segs], r1[(j + 1) % segs], r1[j]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = util.link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    return obj


def _extras(style, cap, yc, z_ref, z_top):
    co = util.get_coords(cap)
    back = co[np.argmax(co[:, 1] - 0.0 * co[:, 2])]
    objs = []
    hh = z_top - z_ref
    for kind in style.get("extras", []):
        if kind == "ponytail":
            base = Vector((0, co[:, 1].max() - 0.01, z_ref + hh * 0.55))
            pts = [base + Vector((0, 0.03 * min(i, 2) + 0.004 * i, -0.035 * max(0, i - 1)))
                   for i in range(10)]
            radii = [0.03, 0.033, 0.03, 0.027, 0.024, 0.021, 0.018, 0.014, 0.01, 0.004]
            objs.append(_tube("hair_ponytail", pts, radii))
        elif kind == "bun":
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.045)
            me = bpy.data.meshes.new("hair_bun")
            bm.to_mesh(me)
            bm.free()
            o = util.link(bpy.data.objects.new("hair_bun", me))
            c = Vector((0, co[:, 1].max() + 0.015, z_ref + hh * 0.75))
            util.set_coords(o, util.get_coords(o) * np.array([1.0, 0.8, 0.85]) + np.array(c))
            for p in me.polygons:
                p.use_smooth = True
            objs.append(o)
    return objs


def cylindrical_uv(obj, yc, zmin, zmax):
    me = obj.data
    co = util.get_coords(obj)
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    data = np.zeros((len(me.loops), 2))
    for p in me.polygons:
        th = [(_theta(co[me.loops[li].vertex_index], yc) + math.pi) / (2 * math.pi) for li in p.loop_indices]
        # keep faces that straddle the back seam on one side
        if max(th) - min(th) > 0.5:
            th = [t if t > 0.5 else t + 1 for t in th]
        for li, t in zip(p.loop_indices, th):
            z = co[me.loops[li].vertex_index][2]
            data[li] = (t, (z - zmin) / max(zmax - zmin, 1e-6))
    uv.data.foreach_set("uv", data.ravel())


def skin_hair(obj, res, body_obj):
    """Hair above the neck follows the head; long strands blend into neck/upper spine."""
    co = util.get_coords(obj)
    from mathutils import kdtree
    bco = util.get_coords(body_obj)
    BW = util.weight_matrix(body_obj, res.bones)
    kd = kdtree.KDTree(len(bco))
    for i, p in enumerate(bco):
        kd.insert(p, i)
    kd.balance()
    cols = [res.bones.index(b) for b in HEAD_BONES]
    z_neck = res.arm.data.bones["head"].head_local.z
    W = np.zeros((len(co), len(res.bones)))
    for i, p in enumerate(co):
        if p[2] >= z_neck:
            W[i, cols[0]] = 1
            continue
        _, j, _ = kd.find(p)
        w = BW[j, cols]
        if w.sum() < 1e-6:
            w = np.array([0, 0, 1.0, 0])
        W[i, cols] = w / w.sum()
    util.set_weight_matrix(obj, W, res.bones)


def make(res, body_obj, style_name):
    style = catalog.HAIR_STYLES[style_name]
    cap, (yc, z_ref, z_top) = _cap(res, body_obj, style, "Hair")
    curtain = _curtain(res, body_obj, style, yc, z_ref, z_top)
    parts = [cap] + ([curtain] if curtain else []) + _extras(style, cap, yc, z_ref, z_top)
    if len(parts) > 1:
        with bpy.context.temp_override(active_object=cap, selected_editable_objects=parts, object=cap):
            bpy.ops.object.join()
    obj = cap
    sol = obj.modifiers.new("thickness", "SOLIDIFY")
    sol.thickness = style["thickness"]
    sol.offset = -1.0
    garments.apply_modifier(obj, sol)
    co = util.get_coords(obj)
    cylindrical_uv(obj, yc, co[:, 2].min(), co[:, 2].max())
    skin_hair(obj, res, body_obj)
    util.add_armature_modifier(obj, res.arm)
    obj["hair_style"] = style_name
    return obj
