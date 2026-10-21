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
        if "neckline" in gdef:
            inc &= ~_neck_hole(co, heads["neck_01"], **gdef["neckline"])
    else:
        z = co[:, 2]
        top, bot = z.max(), z.min()
        inc = z >= top - gdef.get("length", 1.0) * (top - bot)
    keep = [i for i, f in enumerate(faces_local) if inc[f].mean() >= 0.5]
    return keep


def _neck_hole(co, neck, radius, front, back):
    """Vertices inside a crew/scoop neck opening: a disc of `radius` around the neck base, cut from
    `back` metres below the neck base at the back down to `front` metres below it at the front."""
    d = co[:, :2] - np.array([neck.x, neck.y])
    r = np.linalg.norm(d, axis=1)
    fwd = np.clip(-d[:, 1] / np.maximum(r, 1e-6), -1, 1)  # +1 straight ahead (characters face -Y)
    w = (0.5 + 0.5 * fwd) ** 2
    drop = back + (front - back) * w
    # the neck is set back on the shoulders, so the opening reaches further forward than back:
    # a scoop that clears the hollow of the throat instead of leaving a tab standing up there
    rad = radius * (1 + 0.6 * w)
    return (r < rad) & (co[:, 2] > neck.z - drop)


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


def _boundary_loops(bm):
    """Boundary edge loops, each as an ordered list of verts."""
    seen, loops = set(), []
    for v in bm.verts:
        if v in seen or not v.is_boundary:
            continue
        loop, prev, cur = [], None, v
        while cur is not None and cur not in seen:
            seen.add(cur)
            loop.append(cur)
            nb = [e.other_vert(cur) for e in cur.link_edges if e.is_boundary]
            nxt = [y for y in nb if y is not prev and y not in seen]
            prev, cur = cur, (nxt[0] if nxt else None)
        loops.append(loop)
    return loops


def _fade_into(delta, loop, rings):
    """Spread per-vertex offsets on a hem loop over the next `rings` rings of vertices, fading out."""
    front, done = list(loop), set(loop)
    for r in range(1, rings + 1):
        nxt = []
        for v in front:
            for e in v.link_edges:
                y = e.other_vert(v)
                if y not in done:
                    done.add(y)
                    delta[y] = delta[v] * (1 - r / (rings + 1))
                    nxt.append(y)
        front = nxt
    for v, d in delta.items():
        v.co += d


def _smooth_loops(bm, harmonics=5, rings=3):
    """Low-pass every hem/neck/cuff loop (keep the first Fourier harmonics). Region cuts follow the
    mesh's diagonal edges, so openings come out jagged; this makes them clean, round curves."""
    for loop in _boundary_loops(bm):
        n = len(loop)
        if n < 4 * harmonics:
            continue
        co = np.array([v.co for v in loop])
        f = np.fft.rfft(co, axis=0)
        f[harmonics + 1:] = 0
        sm = np.fft.irfft(f, n=n, axis=0)
        _fade_into({v: Vector(sm[i] - co[i]) for i, v in enumerate(loop)}, loop, rings)


def _level_hems(bm, z0, z1, rings=3):
    """Make waist-height hems and waistbands level: flatten each roughly horizontal loop around the
    torso to its mean height and fade the correction over the next few rings of vertices."""
    for loop in _boundary_loops(bm):
        co = np.array([v.co for v in loop])
        zm = co[:, 2].mean()
        extent = max(np.ptp(co[:, 0]), np.ptp(co[:, 1]))
        if not (z0 - 0.08 < zm < z0 + 0.6 * (z1 - z0)) or np.ptp(co[:, 2]) > 0.35 * extent:
            continue
        _fade_into({v: Vector((0, 0, zm - v.co.z)) for v in loop}, loop, rings)


def apply_modifier(obj, mod):
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def mesh_bvh(objs):
    """BVH over the rest-pose surfaces of one or more mesh objects."""
    co, polys = [], []
    for o in objs:
        off = len(co)
        co += [v.co.copy() for v in o.data.vertices]
        polys += [[off + i for i in p.vertices] for p in o.data.polygons]
    return BVHTree.FromPolygons(co, polys)


def body_bvh(body_obj):
    return mesh_bvh([body_obj])


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


def conform_over(obj, body_bvh_, worn_bvh, gap):
    """Keep an outer garment outside garments already worn: measure each vertex's height above the
    skin, ray-cast the worn layers along the same skin normal, and lift the vertex just past them."""
    co = util.get_coords(obj)
    lift = np.zeros(len(co))
    for i, p in enumerate(co):
        loc, nrm, _, _ = body_bvh_.find_nearest(Vector(p))
        if loc is None:
            continue
        h = (Vector(p) - loc).dot(nrm)
        hit, _, _, dist = worn_bvh.ray_cast(loc + nrm * 0.0005, nrm, 0.15)
        if hit is not None and h < dist + gap:
            lift[i] = dist + gap - h
            co[i] = np.array(Vector(p) + nrm * lift[i])
    util.set_coords(obj, co)
    return int((lift > 0).sum())


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
    cen = np.array([p.center for p in me.polygons])
    nrm_y = np.array([p.normal.y for p in me.polygons])
    # Front/back split like a sewn pattern: side seams at mid-depth of the torso (straight down from
    # under the armpit) and sleeve seams along the middle of the arm, rather than wherever the
    # surface turns sideways (which drifts forward over the chest).
    # (UVs are laid out on the neutral reference body, whose arms start ~0.15 m from the centre line)
    arm = np.abs(cen[:, 0]) > 0.15
    key = np.where(arm, np.abs(cen[:, 0]), cen[:, 2])
    mid = np.zeros(len(cen))
    for part in (arm, ~arm):
        if not part.any():
            continue
        edges = np.linspace(key[part].min(), key[part].max() + 1e-6, 25)
        idx = np.digitize(key[part], edges)
        ys = cen[part, 1]
        means = {i: (ys[idx == i].min() + ys[idx == i].max()) / 2 for i in np.unique(idx)}
        mid[part] = [means[i] for i in idx]
    is_front = np.where(np.abs(cen[:, 1] - mid) > 1e-4, cen[:, 1] < mid, nrm_y <= 0)
    for p in me.polygons:
        front = bool(is_front[p.index])  # characters face -Y
        cx = 0.25 if front else 0.75
        sgn = 1 if front else -1
        for li in p.loop_indices:
            v = co[me.loops[li].vertex_index]
            data[li] = (cx + sgn * (v[0] - xc) * s, 0.5 + (v[2] - zc) * s)
    uv.data.foreach_set("uv", data.ravel())
    return {"scale_px_per_m": s, "front_center_u": 0.25, "back_center_u": 0.75}


def _source_faces(gdef):
    """Base-mesh faces a garment is cut from, and which part each belongs to (0 = main source group,
    1 = the skirt helper that a "flare" hangs from the waist of a top)."""
    groups = [gdef.get("source_group", "helper-tights")] + (["helper-skirt"] if "flare" in gdef else [])
    faces, part = [], []
    for k, g in enumerate(groups):
        f, _ = morph.faces_of_group(g)
        faces += f
        part += [k] * len(f)
    return faces, np.array(part)


def _flare_heights(res, gdef):
    """Seam height where a top joins its flared skirt, and the hem height (from body landmarks)."""
    heads = {b.name: b.head_local for b in res.arm.data.bones}
    z0, z1 = heads["pelvis"].z, heads["neck_01"].z
    seam = z0 + gdef["regions"]["torso"][0] * (z1 - z0)
    hip, knee = heads["thigh_l"].z, heads["calf_l"].z
    hem = hip + gdef["flare"]["hem"] * (knee - hip)
    return seam, hem


def select_flare(res, gdef, verts, faces_local, part):
    """Skirt-helper faces between the waist seam and the hem."""
    seam, hem = _flare_heights(res, gdef)
    co = res.coords[verts]
    return [i for i, f in enumerate(faces_local) if part[i] == 1 and hem <= co[f, 2].mean() <= seam]


def _loop_angles(loop, c):
    co = np.array([v.co for v in loop])
    return np.arctan2(co[:, 1] - c[1], co[:, 0] - c[0])


def _bridge(bm, a, b):
    """Join two closed boundary loops that ring the body with a strip of triangles, walking both
    loops around the body axis together (the loops may have different vertex counts)."""
    c = np.array([v.co for v in a + b]).mean(0)
    loops = []
    for lp in (a, b):
        ang = _loop_angles(lp, c)
        if np.sum(np.sin(np.diff(np.unwrap(ang)))) < 0:  # make both run counter-clockwise
            lp, ang = lp[::-1], ang[::-1]
        k = int(np.argmin(ang))
        lp = lp[k:] + lp[:k]
        ang = np.unwrap(np.roll(ang, -k))
        ang = ang - ang[0] + np.arctan2(lp[0].co.y - c[1], lp[0].co.x - c[0])
        loops.append((lp + [lp[0]], np.append(ang, ang[0] + 2 * np.pi)))
    (la, aa), (lb, ab) = loops
    i = j = 0
    new = []
    while i < len(la) - 1 or j < len(lb) - 1:
        if j == len(lb) - 1 or (i < len(la) - 1 and aa[i + 1] <= ab[j + 1]):
            tri = (la[i], la[i + 1], lb[j])
            i += 1
        else:
            tri = (la[i], lb[j + 1], lb[j])
            j += 1
        if len(set(tri)) == 3:
            new.append(bm.faces.new(tri))
    return new


def _join_flare(bm, seam):
    """Bridge the top's waist hem to the top edge of its skirt so the garment is one surface."""
    loops = [lp for lp in _boundary_loops(bm) if len(lp) > 8]
    near = sorted(loops, key=lambda lp: abs(np.mean([v.co.z for v in lp]) - seam))[:2]
    _bridge(bm, near[0], near[1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    # relax the joint so the waist flows into the skirt
    ring = {v for lp in near for v in lp}
    for _ in range(2):
        ring |= {e.other_vert(v) for v in list(ring) for e in v.link_edges}
    for _ in range(6):
        new = {v: sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges) for v in ring}
        for v, c in new.items():
            v.co = v.co * 0.5 + c * 0.5


def _cut_slits(bm, depth, opening):
    """Side slits rising `depth` metres from the lowest hem: split the mesh along the side seam and
    open the slit into a narrow V so it reads in the rest pose."""
    loops = _boundary_loops(bm)
    hem = min(loops, key=lambda lp: np.mean([v.co.z for v in lp]))
    z0 = np.mean([v.co.z for v in hem])
    for side in (-1, 1):
        v = max(hem, key=lambda x: side * x.co.x)
        chain, verts = [], [v]
        while v.co.z < z0 + depth:
            up = [e for e in v.link_edges if e.other_vert(v).co.z > v.co.z + 1e-4]
            if not up:
                break
            e = max(up, key=lambda e: (e.other_vert(v).co - v.co).normalized().z)
            chain.append(e)
            v = e.other_vert(v)
            verts.append(v)
        if not chain:
            continue
        pos = [x.co.copy() for x in verts]
        bmesh.ops.split_edges(bm, edges=chain)
        for x in bm.verts:
            for p in pos[:-1]:
                if (x.co - p).length < 1e-6:
                    fy = np.mean([f.calc_center_median().y for f in x.link_faces])
                    s = 1 - (x.co.z - z0) / depth
                    x.co.y += (-1 if fy < x.co.y else 1) * opening * max(s, 0) ** 1.5
                    break


def _gathers(obj, res, g):
    """Churidar gathers: rings of soft bunched folds over the lower leg (wavy, outward only)."""
    heads = {b.name: b.head_local for b in res.arm.data.bones}
    zk, za = heads["calf_l"].z, heads["foot_l"].z
    obj.data.update()
    n = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("normal", n)
    n = n.reshape(-1, 3)
    co = util.get_coords(obj)
    t = (zk - co[:, 2]) / (zk - za)  # 0 at the knee, 1 at the ankle
    w = np.clip((t - g["from"]) / 0.15, 0, 1)
    side = np.sign(co[:, 0])
    cx = np.array([heads["calf_l" if s > 0 else "calf_r"].x for s in side])
    ang = np.arctan2(co[:, 1], co[:, 0] - cx)
    # folds that wander, merge and fade around the leg rather than regular rings
    z = co[:, 2] / g["wavelength"]
    ph = z + 0.45 * np.sin(ang + 2.3 * z + side) + 0.25 * np.sin(3 * ang - 1.7 * z)
    am = 0.65 + 0.35 * np.sin(2 * ang + 0.9 * z + 2 * side)
    bump = g["extra"] + g["amp"] * am * np.abs(np.sin(np.pi * ph)) ** 0.7
    util.set_coords(obj, co + n * (w * bump)[:, None])


def _shape(res, gdef, gid, verts, faces_local, keep):
    """Garment surface for one body: cut, clean, subdivide, smooth hems. Same topology for any body."""
    obj = util.make_mesh(gid, res.coords[verts], [faces_local[i].tolist() for i in keep])
    util.set_weight_matrix(obj, res.W[verts], res.bones)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    _largest_components(bm)
    if "flare" in gdef:
        _join_flare(bm, _flare_heights(res, gdef)[0])
    bm.to_mesh(obj.data)
    bm.free()
    sub = obj.modifiers.new("sub", "SUBSURF")
    sub.levels = gdef.get("subdiv", 1)
    apply_modifier(obj, sub)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    _smooth_boundary(bm)
    if "regions" in gdef:
        _smooth_loops(bm)
        heads = {b.name: b.head_local for b in res.arm.data.bones}
        _level_hems(bm, heads["pelvis"].z, heads["neck_01"].z)
    if gdef.get("flare", {}).get("slits"):
        _cut_slits(bm, gdef["flare"]["slits"], 0.012)
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


def loosen_legs(obj, res, amount):
    """Draped legs (dhoti): push each trouser leg out from its bone axis, from nothing at the hips to
    `amount` at the knee and below, mostly to the front, back and outside so the legs never meet.
    Leg hems are then levelled so they hang straight."""
    bones = res.arm.data.bones
    co = util.get_coords(obj)
    z_hip = bones["thigh_l"].head_local.z
    z_knee = bones["calf_l"].head_local.z
    for side in ("l", "r"):
        chain = [bones[f"thigh_{side}"].head_local, bones[f"calf_{side}"].head_local, bones[f"foot_{side}"].head_local]
        zs = np.array([p.z for p in chain])[::-1]
        ax = np.interp(co[:, 2], zs, np.array([p.x for p in chain])[::-1])
        ay = np.interp(co[:, 2], zs, np.array([p.y for p in chain])[::-1])
        sx = np.sign(chain[0].x)
        sel = (co[:, 0] * sx > 0.02) & (co[:, 2] < z_hip + 0.05)
        d = co[:, :2] - np.stack([ax, ay], 1)
        r = np.maximum(np.linalg.norm(d, axis=1), 1e-6)
        u = d / r[:, None]
        k = np.clip((z_hip + 0.05 - co[:, 2]) / (z_hip + 0.05 - z_knee), 0, 1)
        k = k * k * (3 - 2 * k)
        outward = (1 + u[:, 0] * sx) / 2  # 1 on the outside of the leg, 0 on the inside
        push = amount * k * (0.35 + 0.65 * outward)
        new = co[:, :2] + u * push[:, None]
        new[:, 0] = np.where(sx > 0, np.maximum(new[:, 0], 0.012), np.minimum(new[:, 0], -0.012))
        co[sel, :2] = new[sel]
    util.set_coords(obj, co)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for loop in _boundary_loops(bm):
        z = np.array([v.co.z for v in loop])
        if z.mean() < z_knee:
            _fade_into({v: Vector((0, 0, z.mean() - v.co.z)) for v in loop}, loop, 3)
    bm.to_mesh(obj.data)
    bm.free()


def make(res, ref_res, body_obj, gid, gtype, layer_rank=0, worn=None):
    """Build a standard garment on `res`'s body. The face cut and the UV layout come from the neutral
    reference body (`ref_res`), so one texture fits the garment on every body shape."""
    gdef = catalog.GARMENTS[gtype]
    if "turban" in gdef:
        from . import headwear
        obj, uvinfo = headwear.turban(res, body_obj, gid, gdef)
        obj["garment_type"] = gtype
        return obj, uvinfo
    if gdef.get("drape") == "dupatta":
        from . import dupatta
        return dupatta.make(res, body_obj, gid, gdef, layer_rank, worn)
    faces, part = _source_faces(gdef)
    verts = np.unique(np.concatenate([np.asarray(f) for f in faces]))
    remap = -np.ones(len(res.coords), dtype=np.int64)
    remap[verts] = np.arange(len(verts))
    faces_local = [remap[np.asarray(f)] for f in faces]
    if gtype not in _UV_CACHE:
        keep = select_faces(ref_res, gdef, verts, faces_local)
        if "flare" in gdef:
            keep = [i for i in keep if part[i] == 0] + select_flare(ref_res, gdef, verts, faces_local, part)
        ref = _shape(ref_res, gdef, "_ref_" + gid, verts, faces_local, keep)
        uvinfo = flat_sketch_uv(ref)
        uv = np.empty(len(ref.data.loops) * 2)
        ref.data.uv_layers["UVMap"].data.foreach_get("uv", uv)
        _UV_CACHE[gtype] = (keep, uv, uvinfo)
        bpy.data.objects.remove(ref, do_unlink=True)
    keep, uv, uvinfo = _UV_CACHE[gtype]
    obj = _shape(res, gdef, gid, verts, faces_local, keep)
    # Stacking on garments already worn is handled by conform_over; the layer only nudges the gap
    gap = gdef["offset"] + 0.001 * layer_rank
    skin_from_body(obj, body_obj, res.bones, smooth_iters=gdef.get("weight_smooth", 10))
    offset_along_normals(obj, gap)
    bvh = body_bvh(body_obj)
    conform(obj, bvh, gap * 0.8)
    if gdef.get("loose"):
        loosen_legs(obj, res, gdef["loose"])
    if worn is not None:
        conform_over(obj, bvh, worn, 0.006)
    if "gathers" in gdef:
        _gathers(obj, res, gdef["gathers"])
    if gdef.get("sole"):
        co = util.get_coords(obj)
        co[:, 2] = np.maximum(co[:, 2], 0.0)
        util.set_coords(obj, co)
    layer = obj.data.uv_layers.get("UVMap") or obj.data.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv)
    sol = obj.modifiers.new("thickness", "SOLIDIFY")
    sol.thickness = 0.0015
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
