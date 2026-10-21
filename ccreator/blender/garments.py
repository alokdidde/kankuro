"""Standard garments: cut from MakeHuman helper surfaces, conformed to the body, skinned, and UV
mapped with a front/back "flat sketch" layout that is easy to repaint with an image model."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .. import catalog, morph
from . import body as body_mod
from . import util


TORSO = ["pelvis", "spine_01", "spine_02", "spine_03"]


def _expand_regions(regions):
    out = {}
    for k, v in regions.items():
        if k.endswith("_*"):
            out[k[:-1] + "l"] = v
            out[k[:-1] + "r"] = v
        else:
            out[k] = v
    return out


def _bone_param(res, co, W):
    """Dominant bone name and parameter t along it for each vertex."""
    pos = {b.name: (np.array(b.head_local), np.array(b.tail_local)) for b in res.arm.data.bones}
    dom = W.argmax(1)
    names = np.array(res.bones)[dom]
    t = np.zeros(len(co))
    for i, n in enumerate(names):
        h, tl = pos[n]
        d = tl - h
        t[i] = np.dot(co[i] - h, d) / max(np.dot(d, d), 1e-9)
    return names, t


def select_faces(res, gdef, verts, faces_local):
    co = res.coords[verts]
    W = res.W[verts]
    if "regions" in gdef:
        regions = _expand_regions(gdef["regions"])
        names, t = _bone_param(res, co, W)
        # Torso bones use one shared height parameter (0 = hip joints, 1 = neck base) so hems
        # and waistbands are level instead of following each spine bone's tilt.
        heads = {b.name: b.head_local for b in res.arm.data.bones}
        z0, z1 = heads["pelvis"].z, heads["neck_01"].z
        torso = np.isin(names, TORSO)
        t[torso] = (co[torso, 2] - z0) / (z1 - z0)
        names = np.where(torso, "torso", names)
        # A range starting at exactly 0 or ending at exactly 1 is open-ended: projections overshoot slightly near joints
        lim = {n: (-np.inf if a == 0 else a, np.inf if b == 1 else b) for n, (a, b) in regions.items()}
        inc = np.array([n in lim and lim[n][0] <= ti <= lim[n][1] for n, ti in zip(names, t)])
    else:
        z = co[:, 2]
        top, bot = z.max(), z.min()
        inc = z >= top - gdef.get("length", 1.0) * (top - bot)
    keep = [i for i, f in enumerate(faces_local) if inc[f].mean() >= 0.5]
    return keep


def _largest_components(bm, min_frac=0.03):
    """Drop tiny disconnected islands produced by region cuts."""
    seen, comps = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            x = stack.pop()
            comp.append(x)
            for e in x.edges:
                for y in e.link_faces:
                    if y.index not in seen:
                        seen.add(y.index)
                        stack.append(y)
        comps.append(comp)
    total = len(bm.faces)
    drop = [f for c in comps if len(c) < min_frac * total for f in c]
    if drop:
        bmesh.ops.delete(bm, geom=drop, context="FACES")


def _smooth_boundary(bm, iterations=4):
    for _ in range(iterations):
        new = {}
        for v in bm.verts:
            if not v.is_boundary:
                continue
            nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if len(nb) == 2:
                new[v] = (v.co * 0.5 + (nb[0].co + nb[1].co) * 0.25)
        for v, c in new.items():
            v.co = c


def apply_modifier(obj, mod):
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def body_bvh(body_obj):
    me = body_obj.data
    co = [v.co.copy() for v in me.vertices]
    polys = [list(p.vertices) for p in me.polygons]
    return BVHTree.FromPolygons(co, polys)


def conform(obj, bvh, gap):
    """Push vertices that are inside the body or closer than `gap` out along the body normal."""
    co = util.get_coords(obj)
    moved = 0
    for i, p in enumerate(co):
        loc, nrm, _, dist = bvh.find_nearest(Vector(p))
        if loc is None:
            continue
        d = Vector(p) - loc
        signed = d.dot(nrm)
        if signed < gap:
            co[i] = np.array(loc + nrm * gap)
            moved += 1
    util.set_coords(obj, co)
    return moved


def offset_along_normals(obj, dist):
    obj.data.update()
    n = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("normal", n)
    co = util.get_coords(obj) + n.reshape(-1, 3) * dist
    util.set_coords(obj, co)


def flat_sketch_uv(obj, margin=0.03):
    """Front faces on the left half, back faces (seen from behind) on the right half, same scale."""
    me = obj.data
    co = util.get_coords(obj)
    lo, hi = co.min(0), co.max(0)
    xc, zc = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    w, h = hi[0] - lo[0], hi[2] - lo[2]
    s = min((0.5 - 2 * margin) / max(w, 1e-6), (1 - 2 * margin) / max(h, 1e-6))
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    me.uv_layers.active = uv
    data = np.zeros((len(me.loops), 2))
    for p in me.polygons:
        front = p.normal.y <= 0  # characters face -Y
        cx = 0.25 if front else 0.75
        sgn = 1 if front else -1
        for li in p.loop_indices:
            v = co[me.loops[li].vertex_index]
            data[li] = (cx + sgn * (v[0] - xc) * s, 0.5 + (v[2] - zc) * s)
    uv.data.foreach_set("uv", data.ravel())
    return {"scale_px_per_m": s, "front_center_u": 0.25, "back_center_u": 0.75}


def _shape(res, gdef, gid, verts, faces_local, keep):
    """Garment surface for one body: cut, clean, subdivide, smooth hems. Same topology for any body."""
    obj = util.make_mesh(gid, res.coords[verts], [faces_local[i].tolist() for i in keep])
    util.set_weight_matrix(obj, res.W[verts], res.bones)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    _largest_components(bm)
    bm.to_mesh(obj.data)
    bm.free()
    sub = obj.modifiers.new("sub", "SUBSURF")
    sub.levels = 1
    apply_modifier(obj, sub)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    _smooth_boundary(bm)
    bm.to_mesh(obj.data)
    bm.free()
    if gdef.get("sole"):
        # Shoes: smooth away toes, flatten the bottom into a sole
        sm = obj.modifiers.new("smooth", "SMOOTH")
        sm.factor = 1.0
        sm.iterations = 30
        apply_modifier(obj, sm)
        co = util.get_coords(obj)
        co[:, 2] = np.where(co[:, 2] < 0.012, 0.0, co[:, 2])
        util.set_coords(obj, co)
    return obj


_UV_CACHE = {}


def skin_from_body(obj, body_obj, bones, smooth_iters=10, smooth_factor=0.5):
    """Skin weights for clothing: copy the weights of the nearest point on the body surface, then
    smooth them across the garment so it bends in broad, cloth-like folds instead of creasing
    sharply where body weights change fast (shoulders, hips)."""
    from mathutils import interpolate
    BW = util.weight_matrix(body_obj, bones)
    bme = body_obj.data
    bco = util.get_coords(body_obj)
    polys = [list(p.vertices) for p in bme.polygons]
    bvh = BVHTree.FromPolygons([Vector(c) for c in bco], polys)
    co = util.get_coords(obj)
    W = np.zeros((len(co), len(bones)))
    for i, p in enumerate(co):
        loc, _, fi, _ = bvh.find_nearest(Vector(p))
        vs = polys[fi]
        bary = interpolate.poly_3d_calc([Vector(bco[v]) for v in vs], loc)
        W[i] = (BW[vs] * np.array(bary)[:, None]).sum(0)
    # Laplacian smoothing of weights over the garment's own edges
    me = obj.data
    e = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", e)
    e = e.reshape(-1, 2)
    deg = np.bincount(e.ravel(), minlength=len(co)).astype(float)
    deg[deg == 0] = 1
    for _ in range(smooth_iters):
        acc = np.zeros_like(W)
        np.add.at(acc, e[:, 0], W[e[:, 1]])
        np.add.at(acc, e[:, 1], W[e[:, 0]])
        W = (1 - smooth_factor) * W + smooth_factor * acc / deg[:, None]
    util.set_weight_matrix(obj, W, bones)


def make(res, ref_res, body_obj, gid, gtype, layer_rank=0):
    """Build a standard garment on `res`'s body. The face cut and the UV layout come from the neutral
    reference body (`ref_res`), so one texture fits the garment on every body shape."""
    gdef = catalog.GARMENTS[gtype]
    group = gdef.get("source_group", "helper-tights")
    faces, _ = morph.faces_of_group(group)
    verts = np.unique(np.concatenate([np.asarray(f) for f in faces]))
    remap = -np.ones(len(res.coords), dtype=np.int64)
    remap[verts] = np.arange(len(verts))
    faces_local = [remap[np.asarray(f)] for f in faces]
    if gtype not in _UV_CACHE:
        keep = select_faces(ref_res, gdef, verts, faces_local)
        ref = _shape(ref_res, gdef, "_ref_" + gid, verts, faces_local, keep)
        uvinfo = flat_sketch_uv(ref)
        uv = np.empty(len(ref.data.loops) * 2)
        ref.data.uv_layers["UVMap"].data.foreach_get("uv", uv)
        _UV_CACHE[gtype] = (keep, uv, uvinfo)
        bpy.data.objects.remove(ref, do_unlink=True)
    keep, uv, uvinfo = _UV_CACHE[gtype]
    obj = _shape(res, gdef, gid, verts, faces_local, keep)
    gap = gdef["offset"] + 0.003 * layer_rank
    skin_from_body(obj, body_obj, res.bones, smooth_iters=gdef.get("weight_smooth", 10))
    offset_along_normals(obj, gap)
    conform(obj, body_bvh(body_obj), gap * 0.8)
    if gdef.get("sole"):
        co = util.get_coords(obj)
        co[:, 2] = np.maximum(co[:, 2], 0.0)
        util.set_coords(obj, co)
    layer = obj.data.uv_layers.get("UVMap") or obj.data.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv)
    sol = obj.modifiers.new("thickness", "SOLIDIFY")
    sol.thickness = 0.003
    sol.offset = 1.0
    sol.use_rim = True
    sol.use_quality_normals = True
    apply_modifier(obj, sol)
    for p in obj.data.polygons:
        p.use_smooth = True
    util.add_armature_modifier(obj, res.arm)
    obj["garment_type"] = gtype
    return obj, uvinfo


def uv_polygons(obj, outer_only=True):
    """UV polygons of a garment (outer shell only: solidify duplicates faces after the originals)."""
    me = obj.data
    uv = me.uv_layers["UVMap"].data
    n = len(me.polygons)
    polys = []
    for p in me.polygons:
        polys.append([tuple(uv[li].uv) for li in p.loop_indices])
    return polys
