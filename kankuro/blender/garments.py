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


def flat_sketch_uv(obj, margin=0.03, unsquash=True):
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
    if unsquash:
        data, s = _unsquash_uv(me, co, data, is_front, s, margin)
    uv.data.foreach_set("uv", data.ravel())
    return {"scale_px_per_m": s, "front_center_u": 0.25, "back_center_u": 0.75}


def _unsquash_uv(me, co, data, is_front, s, margin, iters=300):
    """Relax a front/back projection towards an as-rigid-as-possible flattening of each panel.

    A straight projection squashes whatever is seen edge-on (the sides of the body and legs, the
    crotch, the underside of sleeves): the fabric weave baked there comes out stretched into
    stripes or blurred into fuzzy patches. Each triangle is pulled towards its true shape (rotated
    to fit), with a weak pull back to the projection so the template still reads as a front and a
    back view. Each panel is then put back in its half at one common scale (pixels per metre)."""
    loops_v = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", loops_v)
    poly_of_loop = np.empty(len(me.loops), dtype=np.int64)
    for p in me.polygons:
        poly_of_loop[p.loop_start:p.loop_start + p.loop_total] = p.index
    side = is_front[poly_of_loop].astype(np.int64)
    keys, uvid = np.unique(loops_v * 2 + side, return_inverse=True)
    n = len(keys)
    U0 = np.zeros((n, 2))
    np.add.at(U0, uvid, data)
    U0 /= np.bincount(uvid, minlength=n)[:, None]
    tris = []
    for p in me.polygons:
        li = list(p.loop_indices)
        tris += [(li[0], li[k], li[k + 1]) for k in range(1, len(li) - 1)]
    tl = np.array(tris)                       # loop indices
    tu = uvid[tl]                             # uv vertices
    P = co[loops_v[tl]] * s                   # 3D corners, in uv units
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    l1 = np.linalg.norm(e1, axis=1)
    ok = l1 > 1e-12
    x = e1 / np.maximum(l1, 1e-12)[:, None]
    nrm = np.cross(e1, e2)
    ok &= np.linalg.norm(nrm, axis=1) > 1e-14
    y = np.cross(nrm, e1)
    y /= np.maximum(np.linalg.norm(y, axis=1), 1e-12)[:, None]
    R2 = np.zeros((len(tl), 3, 2))            # rest shape of each triangle, flattened
    R2[:, 1, 0] = l1
    R2[:, 2, 0] = np.sum(e2 * x, axis=1)
    R2[:, 2, 1] = np.sum(e2 * y, axis=1)
    # the projection mirrors one panel relative to the other: give every triangle of a panel the
    # handedness most of that panel has (squashed triangles at its sides may be folded over)
    ar = (U0[tu[:, 1]] - U0[tu[:, 0]])
    br = (U0[tu[:, 2]] - U0[tu[:, 0]])
    area = ar[:, 0] * br[:, 1] - ar[:, 1] * br[:, 0]
    tri_side = side[tl[:, 0]]
    flip = np.zeros(len(tl), dtype=bool)
    for f in (0, 1):
        m = tri_side == f
        if m.any():
            flip[m] = np.sum(area[m]) < 0
    R2[flip, :, 1] *= -1
    tl, tu, R2 = tl[ok], tu[ok], R2[ok]
    E = [(0, 1), (1, 2), (2, 0)]
    deg = np.zeros(n)
    for a, b in E:
        deg += np.bincount(tu[:, a], minlength=n) + np.bincount(tu[:, b], minlength=n)
    deg = np.maximum(deg, 1)
    U = U0.copy()
    anchor = 0.02
    for _ in range(iters):
        S = np.zeros((len(tu), 2, 2))
        for a, b in E:
            e = U[tu[:, b]] - U[tu[:, a]]
            r = R2[:, b] - R2[:, a]
            S += e[:, :, None] * r[:, None, :]
        th = np.arctan2(S[:, 1, 0] - S[:, 0, 1], S[:, 0, 0] + S[:, 1, 1])
        c, sn = np.cos(th), np.sin(th)
        acc = np.zeros((n, 2))
        for a, b in E:
            r = R2[:, b] - R2[:, a]
            t = np.stack([c * r[:, 0] - sn * r[:, 1], sn * r[:, 0] + c * r[:, 1]], 1)
            np.add.at(acc, tu[:, b], U[tu[:, a]] + t)
            np.add.at(acc, tu[:, a], U[tu[:, b]] - t)
        U += 0.8 * (acc / deg[:, None] - U) + anchor * (U0 - U)
    # put each panel back where the projection had it (best rotation + translation), then fit both
    # halves at one scale
    uv_side = keys % 2
    for f in (0, 1):
        m = uv_side == f
        if not m.any():
            continue
        a, b0 = U[m] - U[m].mean(0), U0[m] - U0[m].mean(0)
        H = a.T @ b0
        th = np.arctan2(H[0, 1] - H[1, 0], H[0, 0] + H[1, 1])
        Rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        U[m] = a @ Rm.T + U0[m].mean(0)
    k = 1.0
    for f in (0, 1):
        m = uv_side == f
        if m.any():
            ext = np.ptp(U[m], axis=0)
            k = min(k, (0.5 - 2 * margin) / max(ext[0], 1e-6), (1 - 2 * margin) / max(ext[1], 1e-6))
    for f, cx in ((1, 0.25), (0, 0.75)):
        m = uv_side == f
        if m.any():
            lo, hi = U[m].min(0), U[m].max(0)
            U[m] = (U[m] - (lo + hi) / 2) * k + np.array([cx, 0.5])
    return U[uvid], s * k


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


def _band_collar(bm, res, c):
    """A band (mandarin) collar: extrude the neck opening straight up by c["height"], leaning in to
    stand around the neck. Its vertices are tagged in a "collar" int layer."""
    tag = bm.verts.layers.int.get("collar") or bm.verts.layers.int.new("collar")  # (invalidates refs: first)
    neck = res.arm.data.bones["neck_01"].head_local
    loops = [lp for lp in _boundary_loops(bm) if len(lp) > 8]
    loop = min(loops, key=lambda lp: np.linalg.norm(np.mean([v.co for v in lp], 0)[:2] - np.array(neck[:2]))
               + abs(np.mean([v.co.z for v in lp]) - neck.z))
    lv = set(loop)
    edges = [e for e in bm.edges if e.is_boundary and e.verts[0] in lv and e.verts[1] in lv]
    base_z = np.mean([v.co.z for v in loop])
    for v in loop:  # a level base so the band has a straight lower edge
        v.co.z = base_z
    c0 = Vector((neck.x, neck.y, 0))
    rows = max(2, int(round(c["height"] / 0.01)))
    for k in range(rows):
        ret = bmesh.ops.extrude_edge_only(bm, edges=edges)
        new = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
        for v in new:
            d = Vector((v.co.x, v.co.y, 0)) - c0
            v.co = c0 + d * (1 - c.get("lean", 0.12) / rows) + Vector((0, 0, base_z + c["height"] * (k + 1) / rows))
            v[tag] = 1
        edges = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMEdge) and all(x in new for x in g.verts)]


def _hang_from_chest(obj, res, ease):
    """Loose tunic body: below the chest the cloth falls straight instead of following the waist in
    (each direction around the body keeps at least the chest's radius), plus `ease` metres of room.
    Sleeves are left alone."""
    co = util.get_coords(obj)
    bones = res.arm.data.bones
    z_chest = bones["spine_03"].head_local.z + 0.04
    yc = bones["spine_02"].head_local.y
    xs = abs(bones["upperarm_l"].head_local.x) * 0.9
    body = np.abs(co[:, 0]) < xs
    d = co[:, :2] - np.array([0.0, yc])
    r = np.linalg.norm(d, axis=1)
    th = np.arctan2(d[:, 1], d[:, 0])
    nb = 72
    bins = ((th + np.pi) / (2 * np.pi) * nb).astype(int) % nb
    ring = body & (np.abs(co[:, 2] - z_chest) < 0.03)
    rc = np.zeros(nb)
    for i in range(nb):
        m = ring & (bins == i)
        rc[i] = r[m].max() if m.any() else 0
    filled = rc > 0
    rc = np.interp(np.arange(nb), np.nonzero(filled)[0], rc[filled], period=nb)
    for _ in range(3):
        rc = 0.5 * rc + 0.25 * (np.roll(rc, 1) + np.roll(rc, -1))
    t = np.clip((z_chest - co[:, 2]) / 0.12, 0, 1)
    t = t * t * (3 - 2 * t)
    target = np.maximum(r, rc[bins] + ease) * t + r * (1 - t)
    sel = body & (co[:, 2] < z_chest)
    co[sel, :2] = (np.array([0.0, yc]) + d / np.maximum(r, 1e-6)[:, None] * target[:, None])[sel]
    util.set_coords(obj, co)


def _level_bottom_hem(obj, res):
    """Make a tunic's hem (one loop, or front and back pieces between slits) one straight level line:
    stacking it over trousers lifts parts of it."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    z_hip = res.arm.data.bones["thigh_l"].head_local.z
    hems = []
    for lp in _boundary_loops(bm):
        z = np.array([v.co.z for v in lp])
        if z.mean() < z_hip:
            hems.append((lp, z))
    if hems:
        zt = float(np.median(np.concatenate([z for _, z in hems])))
        for lp, z in hems:
            low = [v for v in lp if v.co.z < zt + 0.06]  # the slit edges rise from the hem: leave them
            _fade_into({v: Vector((0, 0, zt - v.co.z)) for v in low}, low, 4)
    bm.to_mesh(obj.data)
    bm.free()


def placket_info(obj, uv_layer="UVMap"):
    """UV position of the front-centre neck point (base of the collar or the neckline), for drawing a
    button placket down the front."""
    me = obj.data
    co = util.get_coords(obj)
    attr = me.attributes.get("collar")
    collar = np.zeros(len(co), bool)
    if attr is not None:
        a = np.empty(len(co), dtype=np.int32)
        attr.data.foreach_get("value", a)
        collar = a > 0
    cand = np.nonzero((np.abs(co[:, 0]) < 0.012) & (co[:, 1] < 0) & ~collar)[0]
    if not len(cand):
        return None
    vi = cand[np.argmax(co[cand, 2])]
    uv = me.uv_layers[uv_layer].data
    for lp in me.loops:
        if lp.vertex_index == vi:
            return tuple(uv[lp.index].uv)
    return None


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
    if gdef.get("collar"):
        _band_collar(bm, res, gdef["collar"])
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
    if gdef.get("drape") == "saree":
        from . import drape
        drape.shape_skirt(obj, res, gdef)
    if gdef.get("a_line"):
        _a_line(obj, res, gdef["a_line"])
    return obj


def _a_line(obj, res, amount):
    """Flare a skirt out towards the hem (A-line), from nothing at the hips to `amount` metres at the
    hem, so there is room for the legs on a stride."""
    co = util.get_coords(obj)
    z_hip = res.arm.data.bones["thigh_l"].head_local.z
    bot = co[:, 2].min()
    c = np.array([0.0, (co[:, 1].min() + co[:, 1].max()) / 2])
    d = co[:, :2] - c
    r = np.maximum(np.linalg.norm(d, axis=1), 1e-6)
    f = np.clip((z_hip - co[:, 2]) / max(z_hip - bot, 1e-6), 0, 1) ** 1.3
    co[:, :2] += d / r[:, None] * (amount * f)[:, None]
    util.set_coords(obj, co)


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


LEG_CHAINS = {side: [f"{b}_{side}" for b in ("thigh", "calf", "foot", "ball", "ball_leaf")] for side in "lr"}


def skirt_weights(obj, res, below=None):
    """Skin a skirt as one hanging tube rather than two trouser legs.

    * Leg influence depends on height only: none at the waist, full from the crotch down, so the
      cloth over the front of the thigh moves with it and the leg can't poke through.
    * It goes to the two thighs only (the knee doesn't bend the cloth like a trouser leg), shared by
      how far the vertex is to the side: the centre front and back follow both thighs equally, so the
      cloth there stretches across between the legs on a stride instead of splitting; the cloth over
      each leg follows that leg.
    * Below the knee it is scaled down so the cloth moves about as far as the knee does instead of
      flying out like a stiff cone (it hangs from the knee rather than swinging with the whole leg);
      only the cloth behind the calves follows them.
    `below`: only vertices under this height are changed (the skirt part of a tunic)."""
    bones = res.bones
    W = util.weight_matrix(obj, bones)
    co = util.get_coords(obj)
    z = co[:, 2]
    bl = res.arm.data.bones
    z_hip, z_knee = bl["thigh_l"].head_local.z, bl["calf_l"].head_local.z
    z_waist, z_crotch = bl["pelvis"].head_local.z + 0.03, z_hip - 0.1
    sel = np.ones(len(co), dtype=bool) if below is None else z < below
    hx = abs(bl["thigh_l"].head_local.x)
    li = [bones.index(b) for b in LEG_CHAINS["l"] if b in bones]
    ri = [bones.index(b) for b in LEG_CHAINS["r"] if b in bones]
    t = np.clip((z_waist - z) / (z_waist - z_crotch), 0, 1)
    leg = t * t * (3 - 2 * t)
    leg *= np.minimum(1.0, (z_hip - z_knee) / np.maximum(z_hip - z, 1e-6))
    s = np.clip(0.5 + 0.5 * co[:, 0] / (0.6 * hx), 0, 1)  # share of the left thigh (+X is the left)
    N = W.copy()
    N[:, li + ri] = 0
    rest = N.sum(1)
    N[rest < 1e-6, bones.index("pelvis")] = 1.0
    N /= N.sum(1, keepdims=True)
    # behind the calves the cloth follows them too, so a heel lifting on the back leg of a stride
    # lifts the hem instead of poking through it
    knee_y = bl["calf_l"].head_local.y
    cf = 0.8 * np.clip((co[:, 1] - knee_y) / 0.04, 0, 1) * np.clip((z_knee - z) / 0.1, 0, 1)
    N *= ((1 - leg) * (1 - cf))[:, None]
    for side, share in (("l", s), ("r", 1 - s)):
        N[:, bones.index(f"thigh_{side}")] = leg * (1 - cf) * share
        N[:, bones.index(f"calf_{side}")] = cf * share
    W[sel] = N[sel]
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
        # lay the UVs out on the cloth as it hangs, not on the body under it
        if gdef.get("loose"):
            loosen_legs(ref, ref_res, gdef["loose"])
        if gdef.get("hang"):
            _hang_from_chest(ref, ref_res, gdef["hang"])
        uvinfo = flat_sketch_uv(ref, unsquash=gdef.get("unsquash_uv", True))
        uv = np.empty(len(ref.data.loops) * 2)
        ref.data.uv_layers["UVMap"].data.foreach_get("uv", uv)
        if gdef.get("drape") == "saree":
            from . import drape
            uv, uvinfo = drape.saree_uv(uv, uvinfo)
        _UV_CACHE[gtype] = (keep, uv, uvinfo)
        bpy.data.objects.remove(ref, do_unlink=True)
    keep, uv, uvinfo = _UV_CACHE[gtype]
    obj = _shape(res, gdef, gid, verts, faces_local, keep)
    # Stacking on garments already worn is handled by conform_over; the layer only nudges the gap
    gap = gdef["offset"] + 0.001 * layer_rank
    skin_from_body(obj, body_obj, res.bones, smooth_iters=gdef.get("weight_smooth", 10))
    if gdef.get("source_group") == "helper-skirt":
        skirt_weights(obj, res)
    elif "flare" in gdef:
        skirt_weights(obj, res, below=res.arm.data.bones["thigh_l"].head_local.z)
    offset_along_normals(obj, gap)
    bvh = body_bvh(body_obj)
    conform(obj, bvh, gap * 0.8)
    if gdef.get("loose"):
        loosen_legs(obj, res, gdef["loose"])
    if gdef.get("hang"):
        _hang_from_chest(obj, res, gdef["hang"])
    if gdef.get("waist_roll") or gdef.get("tuck"):
        from . import dhoti
        if gdef.get("tuck"):
            dhoti.back_tuck(obj, res, **gdef["tuck"])
        if gdef.get("waist_roll"):
            dhoti.waist_roll(obj, **gdef["waist_roll"])
    if worn is not None:
        conform_over(obj, bvh, worn, 0.006)
    if "gathers" in gdef:
        _gathers(obj, res, gdef["gathers"])
    if gdef.get("sole"):
        co = util.get_coords(obj)
        co[:, 2] = np.maximum(co[:, 2], 0.0)
        util.set_coords(obj, co)
    if "flare" in gdef:
        _level_bottom_hem(obj, res)
    layer = obj.data.uv_layers.get("UVMap") or obj.data.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv)
    if gdef.get("placket"):
        at = placket_info(obj)
        if at is not None:
            uvinfo = dict(uvinfo, placket=dict(gdef["placket"], u=at[0], v=at[1]))
    # edges tucked in at the waist (no border is drawn along them): a bottom's waistband, the pallu's
    # and the dhoti pleats' first row
    tucked = _top_open_verts(obj, 0.08) if gdef.get("slot") == "bottom" else []
    if gdef.get("drape") == "saree":
        from . import drape
        pallu = drape.pallu(res, body_obj, obj, worn, gdef, uvinfo)
        nv = len(obj.data.vertices)
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj, pallu], object=obj):
            bpy.ops.object.join()
        tucked += range(nv, nv + drape.COLS)
    if gdef.get("pleat_panel"):
        from . import dhoti
        panel = dhoti.front_pleats(res, body_obj, obj, gdef["pleat_panel"])
        nv = len(obj.data.vertices)
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj, panel], object=obj):
            bpy.ops.object.join()
        tucked += range(nv, nv + dhoti.COLS)
    if tucked:
        flag = np.zeros(len(obj.data.vertices), np.int32)
        flag[list(tucked)] = 1
        obj.data.attributes.new("tucked", "INT", "POINT").data.foreach_set("value", flag)
    obj["shell_faces"] = len(obj.data.polygons)  # solidify appends the inner shell and rims after these
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
    n = obj.get("shell_faces", len(me.polygons)) if outer_only else len(me.polygons)
    polys = []
    for p in me.polygons[:n]:
        polys.append([tuple(uv[li].uv) for li in p.loop_indices])
    return polys


def seam_segments(obj):
    """UV segments of the sewn seams (edges where the front and back panels meet), on both sides.
    Hems are left out: they're open boundaries, not seams."""
    me = obj.data
    n = obj.get("shell_faces", len(me.polygons))
    uv = me.uv_layers["UVMap"].data
    seen = {}
    segs = []
    for p in me.polygons[:n]:
        li = list(p.loop_indices)
        for a, b in zip(li, li[1:] + li[:1]):
            va, vb = me.loops[a].vertex_index, me.loops[b].vertex_index
            key = (min(va, vb), max(va, vb))
            ua, ub = tuple(uv[a].uv), tuple(uv[b].uv)
            if va > vb:
                ua, ub = ub, ua
            if key in seen:
                oa, ob = seen.pop(key)
                if np.hypot(*np.subtract(oa, ua)) > 1e-5 or np.hypot(*np.subtract(ob, ub)) > 1e-5:
                    segs += [(oa, ob), (ua, ub)]
            else:
                seen[key] = (ua, ub)
    return segs


def _top_open_verts(obj, depth):
    """Vertices of the open edges within `depth` of the garment's top (a waistband)."""
    me = obj.data
    count = {}
    for p in me.polygons:
        vs = list(p.vertices)
        for a, b in zip(vs, vs[1:] + vs[:1]):
            k = (min(a, b), max(a, b))
            count[k] = count.get(k, 0) + 1
    co = util.get_coords(obj)
    top = co[:, 2].max()
    return sorted({v for k, c in count.items() if c == 1 for v in k if co[k[0], 2] > top - depth
                   and co[k[1], 2] > top - depth})


def edge_distance(obj, which="border", cap=0.2, uv_scale=None):
    """Per-vertex distance (m, along the cloth) to its open edges: "border" = all of them (hems, neckline,
    cuffs, a saree's long edges and pallu end), "hem" = only the lowest ones (bottom fifth of the open
    edges' height range). Edges tucked in at the waist (the "tucked" attribute) are left out.

    The distance is measured on the unfolded cloth: each step is the longer of its 3D length and its
    UV length (uv_scale = UV units per metre). Pleats squeeze the layout but not the 3D cloth; the pallu
    is gathered at the shoulder in 3D but laid out flat in UV. Vertices further than `cap` get `cap`."""
    import heapq
    me = obj.data
    n = obj.get("shell_faces", len(me.polygons))
    co = util.get_coords(obj)
    uv = me.uv_layers["UVMap"].data if uv_scale and me.uv_layers else None
    count, adj = {}, {}
    for p in me.polygons[:n]:
        vs = list(p.vertices)
        li = list(p.loop_indices)
        for i, (a, b) in enumerate(zip(vs, vs[1:] + vs[:1])):
            key = (min(a, b), max(a, b))
            count[key] = count.get(key, 0) + 1
            w = float(np.linalg.norm(co[a] - co[b]))
            if uv is not None:
                w = max(w, float(np.hypot(*np.subtract(uv[li[i]].uv, uv[li[(i + 1) % len(li)]].uv))) / uv_scale)
            adj.setdefault(a, {})[b] = max(w, adj.get(a, {}).get(b, 0.0))
            adj.setdefault(b, {})[a] = adj[a][b]
    open_ = [k for k, c in count.items() if c == 1]
    dist = np.full(len(co), cap)
    if not open_:
        return dist
    z = np.array([0.5 * (co[a, 2] + co[b, 2]) for a, b in open_])
    keep = np.ones(len(open_), bool)
    if "tucked" in me.attributes:
        t = np.zeros(len(co), np.int32)
        me.attributes["tucked"].data.foreach_get("value", t)
        keep = np.array([not (t[a] and t[b]) for a, b in open_])
    if which == "hem":
        lo, hi = z.min(), z.max()
        keep &= z < lo + 0.2 * (hi - lo) + 1e-4
    heap = []
    for (a, b), k in zip(open_, keep):
        if k:
            for v in (a, b):
                if dist[v] > 0:
                    dist[v] = 0.0
                    heap.append((0.0, v))
    heapq.heapify(heap)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        for w, step in adj[v].items():
            nd = d + step
            if nd < dist[w]:
                dist[w] = nd
                heapq.heappush(heap, (nd, w))
    return dist
