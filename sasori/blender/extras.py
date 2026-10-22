"""Extra bones beyond the Mesh2Motion skeleton: chains (a tail, a braid, an earring's dangling part) and
prop sockets. They always hang under a standard bone and never rename, reorder or re-parent the
standard ones, so Mesh2Motion clips still play unchanged. With none, the skeleton is untouched.

Chains carry their own mesh (a tapered tube for a tail) or take over part of an existing one (the
hair's braid with follow="hair"); motion.py bakes their follow-through into each exported clip."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import garments, util

# defaults for a chain's spring (motion.py): how strongly it returns to its rest shape, how much of its
# swing it loses per frame, and how much gravity pulls it
SPRING = {"stiffness": 0.35, "damping": 0.25, "gravity": 1.0}


def add_bones(arm, bones):
    """Add bones [{name, parent, head, tail, deform, roll}] (armature space) to `arm`; roll = the
    direction the bone's Z axis should face."""
    if not bones:
        return
    bpy.context.view_layer.objects.active = arm
    util.deselect_all()
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for b in bones:
        e = eb.new(b["name"])
        e.head = Vector(b["head"])
        e.tail = Vector(b["tail"])
        if (e.tail - e.head).length < 1e-4:
            e.tail = e.head + Vector((0, 0, -0.01))
        e.parent = eb[b["parent"]]
        d = (e.tail - e.head).normalized()
        if b.get("roll") is not None:
            e.align_roll(Vector(b["roll"]))
        else:
            e.align_roll(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((0, -1, 0)))
        e.use_deform = b.get("deform", True)
    bpy.ops.object.mode_set(mode="OBJECT")


def chain_names(cid, count):
    return [f"{cid}_{k + 1:02d}" for k in range(count)]


def _behind(body_obj, p):
    """The point on the body surface straight behind p (characters face -Y)."""
    bvh = garments.body_bvh(body_obj)
    hit = bvh.ray_cast(Vector(p) + Vector((0, 0.5, 0)), Vector((0, -1, 0)), 1.0)
    return np.array(hit[0]) if hit[0] is not None else np.array(p) + np.array([0, 0.1, 0])


def chain_points(c, arm, body_obj):
    """Joint positions (count + 1) of a free chain: from the body surface behind its parent bone, out
    backwards and down, bending up (curve.up) or down (curve.down) along its length; bones get shorter
    towards the tip by `taper`."""
    n = int(c.get("count", 6))
    length = float(c.get("length", 0.6))
    taper = float(c.get("taper", 0.5))
    parent = arm.data.bones[c["parent"]]
    if c.get("start"):
        p0 = np.array(c["start"], float)
    else:
        h = np.array(parent.head_local)
        p0 = _behind(body_obj, h - np.array([0, 0, 0.04]) if c["parent"] == "pelvis" else h)
    curve = c.get("curve") or {}
    bend = math.pi * (float(curve.get("up", 0.0)) - float(curve.get("down", 0.0)))
    a0 = math.radians(float(c.get("angle", -35)))  # start: back and this far below horizontal
    seg = (1 - taper * np.linspace(0, 1, n)) if n > 1 else np.ones(1)
    seg = seg / seg.sum() * length
    pts = [p0]
    for k in range(n):
        a = a0 + bend * (k + 0.5) / n
        pts.append(pts[-1] + seg[k] * np.array([0.0, math.cos(a), math.sin(a)]))
    return np.array(pts)


def chain_bones(cid, parent, pts):
    names = chain_names(cid, len(pts) - 1)
    return [{"name": nm, "parent": parent if k == 0 else names[k - 1], "head": pts[k], "tail": pts[k + 1]}
            for k, nm in enumerate(names)]


def _segment_weights(co, pts, names):
    """Weights of points to a polyline of bones: each point's position along the chain, blended linearly
    between the middles of neighbouring bones (smooth bending). Returns (W, position in bones)."""
    n = len(pts) - 1
    W = np.zeros((len(co), n))
    best = np.full(len(co), np.inf)
    tpar = np.zeros(len(co))
    for k in range(n):
        a, b = pts[k], pts[k + 1]
        ab = b - a
        t = np.clip(((co - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        d = np.linalg.norm(co - (a + t[:, None] * ab), axis=1)
        m = d < best
        best[m], tpar[m] = d[m], k + t[m]
    s = tpar - 0.5
    k0 = np.clip(np.floor(s).astype(int), 0, n - 1)
    f = np.clip(s - k0, 0, 1)
    k1 = np.minimum(k0 + 1, n - 1)
    rows = np.arange(len(co))
    W[rows, k0] += 1 - f
    W[rows, k1] += f
    return W, tpar


def tube_mesh(name, pts, radius, taper, sides=14, per_bone=4):
    """A tapered tube along the chain with a rounded tip, with cylindrical UVs."""
    n = len(pts) - 1
    samples = []
    for k in range(n):
        for j in range(per_bone):
            samples.append((k + j / per_bone, pts[k] + (pts[k + 1] - pts[k]) * j / per_bone))
    samples.append((float(n), pts[-1]))
    verts, uvs_v, rings = [], [], []
    up = np.array([0.0, 0.0, 1.0])
    L = len(samples)
    for i, (s, p) in enumerate(samples):
        k = min(int(s), n - 1)
        d = pts[k + 1] - pts[k]
        d = d / (np.linalg.norm(d) + 1e-12)
        x = np.cross(d, up)
        if np.linalg.norm(x) < 1e-6:
            x = np.array([1.0, 0, 0])
        x /= np.linalg.norm(x)
        y = np.cross(x, d)
        r = radius * (1 - taper * s / n)
        if i == L - 1:
            r *= 0.6
        ring = []
        for j in range(sides):
            a = 2 * math.pi * j / sides
            ring.append(len(verts))
            verts.append(p + r * (math.cos(a) * x + math.sin(a) * y))
        rings.append(ring)
    tip = len(verts)
    dl = pts[-1] - pts[-2]
    verts.append(pts[-1] + dl / (np.linalg.norm(dl) + 1e-12) * radius * (1 - taper) * 0.8)
    faces, fuv = [], []
    for i in range(L - 1):
        for j in range(sides):
            a, b = rings[i][j], rings[i][(j + 1) % sides]
            c, d = rings[i + 1][(j + 1) % sides], rings[i + 1][j]
            faces.append([a, b, c, d])
            u0, u1 = j / sides, (j + 1) / sides
            v0, v1 = i / L, (i + 1) / L
            fuv.append([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
    for j in range(sides):
        faces.append([rings[-1][j], rings[-1][(j + 1) % sides], tip])
        fuv.append([(j / sides, (L - 1) / L), ((j + 1) / sides, (L - 1) / L), ((j + 0.5) / sides, 1.0)])
    uv_list, uv_faces = [], []
    for fu in fuv:
        idx = []
        for uv in fu:
            idx.append(len(uv_list))
            uv_list.append(uv)
        uv_faces.append(idx)
    obj = util.make_mesh(name, np.array(verts), faces, np.array(uv_list), uv_faces)
    for p in obj.data.polygons:
        p.use_smooth = True
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return obj


def follow_hair(c, arm, hair_obj, body_obj):
    """Chain points along the hanging part of the hair (a braid or ponytail): the slice centroids of the
    hair below the nape and behind the neck, resampled into `count` bones."""
    co = util.get_coords(hair_obj)
    bones = arm.data.bones
    nape = bones["neck_01"].head_local
    hang = co[(co[:, 2] < nape.z) & (co[:, 1] > nape.y - 0.02)]
    if len(hang) < 20:
        return None
    zs = np.linspace(hang[:, 2].max(), hang[:, 2].min(), 24)
    cents = []
    for z0, z1 in zip(zs[:-1], zs[1:]):
        m = (hang[:, 2] <= z0) & (hang[:, 2] >= z1)
        if m.sum() >= 3:
            cents.append(hang[m].mean(0))
    if len(cents) < 3:
        return None
    cents = np.array(cents)
    cents[0, 2] = hang[:, 2].max()
    cents[-1, 2] = hang[:, 2].min()
    seglen = np.linalg.norm(np.diff(cents, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seglen)])
    n = int(c.get("count", 5))
    t = np.linspace(0, s[-1], n + 1)
    return np.stack([np.interp(t, s, cents[:, k]) for k in range(3)], 1)


def bind_hair(hair_obj, pts, names, deform_bones, fade=0.04):
    """Weight the hanging hair to the chain (fading in over `fade` below the chain's start)."""
    co = util.get_coords(hair_obj)
    allb = list(deform_bones) + [n for n in names if n not in deform_bones]
    W0 = util.weight_matrix(hair_obj, allb)
    Wc, _ = _segment_weights(co, pts, names)
    w = np.clip((pts[0][2] - co[:, 2]) / fade, 0, 1) * (co[:, 1] > pts[0][1] - 0.06)
    W = W0 * (1 - w[:, None])
    for k, nm in enumerate(names):
        W[:, allb.index(nm)] += w * Wc[:, k]
    util.set_weight_matrix(hair_obj, W, allb)


def build_chains(b, spec):
    """Create every spec["extra_bones"] chain: bones, its tube mesh or the hair it takes over. Records
    b.chains for motion.py."""
    from . import materials
    from .. import matlib
    chains = spec.get("extra_bones") or []
    if not chains:
        return
    arm = b.arm
    bones, made = [], []
    for c in chains:
        pts = None
        if c.get("follow") == "hair" and getattr(b, "hair", None) is not None:
            pts = follow_hair(c, arm, b.hair, b.body)
            if pts is None:
                b.warnings.append({"code": "no_hanging_hair",
                                   "message": f"extra_bones '{c['id']}': follow=hair found no hanging hair; "
                                              "using a free chain"})
        if pts is None:
            pts = chain_points(c, arm, b.body)
        bones += chain_bones(c["id"], c["parent"], pts)
        made.append((c, pts))
    add_bones(arm, bones)
    for c, pts in made:
        names = chain_names(c["id"], len(pts) - 1)
        b.chains.append({"id": c["id"], "bones": names, "parent": c["parent"],
                         "spring": {**SPRING, **(c.get("secondary_motion") or {})},
                         "radius": float(c.get("radius", 0.03)), "enabled": c.get("secondary_motion") is not False})
        if c.get("follow") == "hair" and getattr(b, "hair", None) is not None and pts is not None:
            bind_hair(b.hair, pts, names, b.res.bones)
            continue
        r = float(c.get("radius", 0.03))
        if r <= 0:
            continue
        obj = tube_mesh(c["id"], pts, r, float(c.get("taper", 0.5)))
        W, _ = _segment_weights(util.get_coords(obj), pts, names)
        util.set_weight_matrix(obj, W, names)
        if c.get("material"):
            kw = materials.preset_kwargs(matlib.resolve(c["material"], c.get("color")))
        else:
            hs = spec.get("hair") or {}
            kw = dict(color=c.get("color") or hs.get("color") or "#5a3d28", roughness=0.75, sheen=0.6)
        obj.data.materials.append(materials.make(f"Extra_{c['id']}", **kw))
        util.add_armature_modifier(obj, arm)
        obj["extra_chain"] = c["id"]
        b.meshes.append(obj)
