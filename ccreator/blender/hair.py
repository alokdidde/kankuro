"""Procedural hair styles, grown from the current body's scalp so they always fit the head."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from .. import catalog
from . import garments, hair_cards, util

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
    """Height of the hairline around the head (theta 0 at the face, +/-pi at the back).

    Not a plain arch: the centre dips a little, the hair recedes at the temples (the "M" of a real
    hairline), comes down again in front of the ear and rises over it before dropping to the nape."""
    front, side, back = style.get("hairline", (0.74, 0.55, 0.1))
    temple = style.get("temple", 0.05)
    deg = abs(math.degrees(theta))
    f = np.interp(deg, [0, 18, 38, 58, 78, 95, 130, 180],
                  [front - 0.015, front, front + temple, (front + side) / 2 + temple * 0.6,
                   side - 0.04, side, (side + back) / 2, back])
    return z_ref + (z_top - z_ref) * float(f)


def coverage_mask(res, hair_obj, smooth=2):
    """Per base-vertex weight of the scalp actually under hair_obj's base layer (material 0): 1 where a ray
    out of the skin meets the hair, softened over a couple of mesh rings. It follows the hair as built
    (tapers, a pulled-up nape), so the tint never shows as a band below the hair."""
    from mathutils.bvhtree import BVHTree
    from .. import morph
    hco = util.get_coords(hair_obj)
    faces = [list(p.vertices) for p in hair_obj.data.polygons if p.material_index == 0]
    if not faces:
        return None
    bvh = BVHTree.FromPolygons([Vector(p) for p in hco], faces)
    co = res.coords
    nrm = np.zeros_like(co)
    edges = []
    for f in morph.faces_of_group("body")[0]:
        f = list(f)
        for k in range(1, len(f) - 1):
            n = np.cross(co[f[k]] - co[f[0]], co[f[k + 1]] - co[f[0]])
            nrm[[f[0], f[k], f[k + 1]]] += n
        edges += [(f[k], f[(k + 1) % len(f)]) for k in range(len(f))]
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    m = np.zeros(len(co))
    head = (res.W[:, res.bones.index("head")] > 0.5) & (np.abs(nrm).sum(1) > 0)  # not the shoulders under long hair
    for i in np.nonzero(head)[0]:
        n = Vector(nrm[i])
        hit = bvh.ray_cast(Vector(co[i]) - n * 0.002, n, 0.06)
        m[i] = hit[0] is not None
    edges = np.array(edges)
    deg = np.bincount(edges.ravel(), minlength=len(co)) / 2 + 1.0
    for _ in range(smooth):
        acc = m.copy()
        np.add.at(acc, edges[:, 0], m[edges[:, 1]] * 0.5)
        np.add.at(acc, edges[:, 1], m[edges[:, 0]] * 0.5)
        m = acc / deg
    return m


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
    # pinholes in the scalp selection would become bald spots once the hairline edge is trimmed
    bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=16)
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
        target = np.percentile(r, 75)
        # round out the top; near the hairline the hair stays close to the head instead of flaring into a brim
        hh = z_top - z_ref
        k = style["round"] * np.clip((co2[:, 2] - (z_ref + 0.45 * hh)) / (0.35 * hh), 0, 1)
        co2 = c + (co2 - c) * ((1 - k) + k * target / r)[:, None]
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


def _tube(name, points, radii, segs=20):
    bm = bmesh.new()
    rings, flow = [], []
    for i, (p, r) in enumerate(zip(points, radii)):
        d = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
        a = d.orthogonal().normalized()
        b = d.cross(a).normalized()
        ring = [bm.verts.new(p + (a * math.cos(t) + b * math.sin(t)) * r)
                for t in np.linspace(0, 2 * math.pi, segs, endpoint=False)]
        rings.append(ring)
        flow += [tuple(d)] * segs
    for r0, r1 in zip(rings[:-1], rings[1:]):
        for j in range(segs):
            bm.faces.new((r0[j], r0[(j + 1) % segs], r1[(j + 1) % segs], r1[j]))
    bm.faces.new(list(reversed(rings[0])))  # closes the root, where the ponytail meets the head
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = util.link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    hair_cards.orient_outward(obj)
    hair_cards.set_flow(obj, flow)
    return obj


def _torus(name, centre, axis, R, r, segs=16, ring=8):
    """A hair tie round the ponytail. No flow, so no cards grow on it."""
    axis = Vector(axis).normalized()
    a = axis.orthogonal().normalized()
    b = axis.cross(a)
    bm = bmesh.new()
    vs = []
    for i in range(segs):
        t = 2 * math.pi * i / segs
        radial = a * math.cos(t) + b * math.sin(t)
        vs.append([bm.verts.new(Vector(centre) + radial * (R + r * math.cos(s)) + axis * (r * math.sin(s)))
                   for s in np.linspace(0, 2 * math.pi, ring, endpoint=False)])
    for i in range(segs):
        for j in range(ring):
            i2, j2 = (i + 1) % segs, (j + 1) % ring
            bm.faces.new((vs[i][j], vs[i2][j], vs[i2][j2], vs[i][j2]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    bmesh_obj = util.link(bpy.data.objects.new(name, me))
    for p in me.polygons:
        p.use_smooth = True
    hair_cards.orient_outward(bmesh_obj)
    hair_cards.set_flow(bmesh_obj, np.zeros((len(me.vertices), 3)))
    return bmesh_obj


def _hang(bvh, start, length, clear, direction=(0, 0.25, -1), step=0.01):
    """A path falling from start under gravity that keeps `clear` metres off the body (down the back)."""
    pts = [Vector(start)]
    d = Vector(direction).normalized()
    down = Vector((0, 0, -1))
    for _ in range(int(length / step)):
        p = pts[-1] + d * step
        loc, nrm, _, _ = bvh.find_nearest(p)
        if loc is not None:
            h = (p - loc).dot(nrm)
            if h < clear:
                p = p + nrm * (clear - h)
        d = ((p - pts[-1]).normalized() * 0.6 + down * 0.4).normalized()
        pts.append(p)
    return pts


def _frames(pts, out_hint):
    """Tangent, out (away from the head/body) and side axes along a path."""
    T, N, S = [], [], []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        o = Vector(out_hint[i]) if hasattr(out_hint[0], "__len__") else Vector(out_hint)
        n = (o - t * o.dot(t)).normalized()
        T.append(t)
        N.append(n)
        S.append(n.cross(t).normalized())
    return T, N, S


def _braid(pts, normals, width, period, prefix="hair_strand"):
    """A three-strand plait along pts: one tube per strand, weaving side to side and over/under
    (x = A sin(phi), out = B sin(2 phi), strands a third of a turn apart). width(s) is the plait's
    half-width at arc length s; the strands carry their own combing direction, so cards follow them."""
    arc = [0.0]
    for a, b in zip(pts[:-1], pts[1:]):
        arc.append(arc[-1] + (b - a).length)
    total = arc[-1]
    # resample densely enough for the weave
    n = max(8, int(total / (period / 18)))
    ss = np.linspace(0, total, n)
    P = [Vector(np.array([np.interp(s, arc, [p[k] for p in pts]) for k in range(3)])) for s in ss]
    Nn = [Vector(np.array([np.interp(s, arc, [q[k] for q in normals]) for k in range(3)])) for s in ss]
    T, N, S = _frames(P, Nn)
    objs = []
    for k in range(3):
        cs, rs = [], []
        for i, s in enumerate(ss):
            A = width(s / total)
            phi = 2 * math.pi * s / period + 2 * math.pi * k / 3
            cs.append(P[i] + S[i] * (A * math.sin(phi)) + N[i] * (0.38 * A * math.sin(2 * phi)))
            rs.append(A * 0.52)
        objs.append(_tube(f"{prefix}_{k}", cs, rs, segs=12))
    return objs


def _extras(style, cap, body_obj, yc, z_ref, z_top):
    """Ponytail/bun/braid shapes, the point the hair is pulled back to (None if nothing ties it) and,
    for a French braid, the line on the scalp the hair is gathered into."""
    co = util.get_coords(cap)
    objs, tie, line = [], None, None
    hh = z_top - z_ref
    for kind in style.get("extras", []):
        if kind == "braid":
            # a single plait from the nape down the back (the Indian "choti"), tied off near the end
            bvh = garments.body_bvh(body_obj)
            start = Vector((0, co[:, 1].max() - 0.01, z_ref + hh * 0.3))
            A = style.get("braid_width", 0.015)
            pts = _hang(bvh, start, style.get("braid_length", 0.42), A * 1.4 + 0.012)
            nrm = [Vector((0, 1, 0))] * len(pts)
            objs += _braid(pts, nrm, lambda t: A * (1.0 - 0.5 * t), style.get("braid_period", 0.05))
            end, d = pts[-1], (pts[-1] - pts[-2]).normalized()
            objs.append(_torus("hair_tie_end", end, d, A * 0.55 + 0.002, 0.003))
            tail = [end + d * (0.008 * k) for k in range(7)]
            objs.append(_tube("hair_strand_tail", tail, [A * 0.5, A * 0.55, A * 0.6, A * 0.6, A * 0.5, A * 0.3,
                                                         0.002], segs=12))
            tie = np.array(start)
        elif kind == "french_braid":
            # woven along the top and back of the head from the forehead, gathering hair from the sides,
            # then hanging free from the nape
            from mathutils.bvhtree import BVHTree
            faces = [list(p.vertices) for p in cap.data.polygons]
            cbvh = BVHTree.FromPolygons([Vector(p) for p in co], faces)
            c = Vector((0, yc, (z_ref + z_top) / 2))
            A0, A1 = style.get("braid_width", 0.016) * 0.35, style.get("braid_width", 0.016)
            pts, nrms = [], []
            for al in np.linspace(math.radians(-24), math.radians(128), 40):
                d = Vector((0, math.sin(al), math.cos(al)))
                hit = cbvh.ray_cast(c + d * 0.3, -d, 0.3)
                if hit[0] is None:
                    continue
                n = (hit[0] - c).normalized()
                pts.append(hit[0])
                nrms.append(n)
            k_scalp = len(pts)
            line = np.array([tuple(p) for p in pts])
            bvh = garments.body_bvh(body_obj)
            hang = _hang(bvh, pts[-1], style.get("braid_length", 0.22), A1 * 1.4 + 0.012)[1:]
            pts += hang
            nrms += [Vector((0, 1, 0))] * len(hang)
            frac = k_scalp / len(pts)

            def width(t):  # starts from nothing, grows as hair is taken in along the head, tapers down the hang
                if t < frac:
                    return (A0 + (A1 - A0) * t / frac) * min(1.0, 0.15 + t / 0.12)
                return A1 * (1 - 0.45 * (t - frac) / (1 - frac))
            # the scalp part sits on the hair: lift each lobe by its own thickness
            lifted = [p + n * (width(i / len(pts)) * 0.15) if i < k_scalp else p
                      for i, (p, n) in enumerate(zip(pts, nrms))]
            objs += _braid(lifted, nrms, width, style.get("braid_period", 0.045))
            end, d = pts[-1], (pts[-1] - pts[-2]).normalized()
            objs.append(_torus("hair_tie_end", end, d, A1 * 0.55 * 0.55 + 0.002, 0.003))
            tail = [end + d * (0.008 * k) for k in range(6)]
            objs.append(_tube("hair_strand_tail", tail, [A1 * 0.3, A1 * 0.33, A1 * 0.35, A1 * 0.3, A1 * 0.2,
                                                         0.002], segs=12))
            tie = np.array(pts[k_scalp - 1])
        if kind == "ponytail":
            # out of the back of the head, then a smooth bend into the hanging tail
            base = Vector((0, co[:, 1].max() - 0.012, z_ref + hh * 0.55))
            ctrl = base + Vector((0, 0.06, 0))
            bend_end = base + Vector((0, 0.06, -0.08))
            pts = []
            for t in np.linspace(0, 1, 6):
                pts.append(base * (1 - t) ** 2 + ctrl * (2 * t * (1 - t)) + bend_end * t ** 2)
            for k in range(1, 7):
                pts.append(bend_end + Vector((0, 0.008 * k, -0.035 * k)))
            radii = [0.026, 0.026, 0.027, 0.027, 0.026, 0.025, 0.023, 0.021, 0.018, 0.015, 0.011, 0.007, 0.003]
            objs.append(_tube("hair_ponytail", pts, radii))
            # the tie sits close to the scalp, where the hair gathers
            objs.append(_torus("hair_tie", pts[1], pts[2] - pts[0], radii[1] + 0.0015, 0.005))
            tie = np.array(pts[1])
        elif kind == "bun":
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.045)
            me = bpy.data.meshes.new("hair_bun")
            bm.to_mesh(me)
            bm.free()
            o = util.link(bpy.data.objects.new("hair_bun", me))
            c = np.array((0, co[:, 1].max() + 0.015, z_ref + hh * 0.75))
            util.set_coords(o, util.get_coords(o) * np.array([1.0, 0.8, 0.85]) + c)
            for p in me.polygons:
                p.use_smooth = True
            hair_cards.orient_outward(o)
            # hair wraps round the bun (axis points backwards, out of the head)
            bco = util.get_coords(o) - c
            swirl = np.cross(np.array([0.0, 1.0, 0.0]), bco) + np.array([0, 0.006, 0])
            hair_cards.set_flow(o, swirl / (np.linalg.norm(swirl, axis=1, keepdims=True) + 1e-9))
            objs.append(o)
            tie = c - np.array([0, 0.03, 0])
    return objs, tie, line


def _cap_flow(co, style, yc, z_ref, z_top, tie, line=None):
    """Combing direction over the scalp cap."""
    kind = style.get("flow", "crown")
    hh = z_top - z_ref
    if kind == "braid" and line is not None:
        # into the nearest point of the braid, turning along it as the hair joins in
        d = co[:, None, :] - line[None, :, :]
        j = np.argmin((d ** 2).sum(-1), axis=1)
        to = line[j] - co
        dist = np.linalg.norm(to, axis=1, keepdims=True)
        along = line[np.minimum(j + 1, len(line) - 1)] - line[np.maximum(j - 1, 0)]
        along /= np.linalg.norm(along, axis=1, keepdims=True) + 1e-9
        f = to / (dist + 1e-9) + along * (0.4 + 1.5 * np.clip(1 - dist / 0.03, 0, 1))
        return f / (np.linalg.norm(f, axis=1, keepdims=True) + 1e-9)
    if kind == "back":
        if tie is None:
            tie = np.array([0, yc + 0.12, z_ref + 0.2 * hh])
        d = tie[None, :] - co
        r = np.linalg.norm(d, axis=1, keepdims=True)
        f = d / (r + 1e-9)
        if style.get("part") is not None:
            # parted, then pulled back: the front is combed sideways off the part line before it turns
            # back towards the tie, so the front doesn't read as one smooth dome
            xp = style["part"]
            front = np.clip((yc + 0.02 - co[:, 1]) / 0.07, 0, 1)
            side = np.sign(co[:, 0] - xp + 1e-6) * np.exp(-np.abs(co[:, 0] - xp) / 0.025)
            f[:, 0] += 1.6 * front * side
            f /= np.linalg.norm(f, axis=1, keepdims=True) + 1e-9
        # cards run into the ponytail/bun and carry on along it; only right at the tie point is there no direction
        return f * np.clip((r - 0.005) / 0.01, 0, 1)
    if kind == "part":
        xp = style.get("part", 0.0)
        line = np.stack([np.full(len(co), xp), co[:, 1], np.full(len(co), z_top + 0.02)], axis=1)
        f = co - line
        f /= np.linalg.norm(f, axis=1, keepdims=True) + 1e-9
        # front hair is swept sideways off the face and back, away from the part
        front = np.clip((yc - co[:, 1]) / 0.05, 0, 1)
        side = np.sign(co[:, 0] - xp + 1e-6)
        f[:, 0] += 1.4 * front * side
        f[:, 1] += 0.6 * front
        return f
    crown = np.array([0, yc + 0.04, z_top - 0.01])
    f = co - crown[None, :] + np.array([0, 0, -0.02])
    return f / (np.linalg.norm(f, axis=1, keepdims=True) + 1e-9)


def _taper_to_scalp(obj, body_obj, rings=5, gap=0.0006, near=0.02, keep=None):
    """Bring the hair volume down onto the scalp over the last few edge rings at its open border, so the
    hairline starts at the skin instead of a step the height of the hair."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    ring = {v.index: 0 for v in bm.verts if v.is_boundary and not (keep and keep(v.co))}
    front = [bm.verts[i] for i in ring]
    for k in range(1, rings):
        nxt = []
        for v in front:
            for e in v.link_edges:
                o = e.other_vert(v)
                if o.index not in ring:
                    ring[o.index] = k
                    nxt.append(o)
        front = nxt
    bvh = garments.body_bvh(body_obj)
    for i, k in ring.items():
        v = bm.verts[i]
        loc, nrm, _, dist = bvh.find_nearest(v.co)
        if loc is None or dist > near:
            continue
        h = (v.co - loc).dot(nrm)
        f = (k / rings) ** 0.7
        v.co = v.co + nrm * ((gap + (h - gap) * f) - h)
    bm.to_mesh(obj.data)
    bm.free()


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


def _cut_part(obj, xp, y_max):
    """Open a parting: drop the strip of faces straddling x = xp in front of y_max. The strip's edges then
    taper onto the scalp and get hairline cards like any other hairline."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    kill = []
    for f in bm.faces:
        xs = [v.co.x - xp for v in f.verts]
        if min(xs) < 0 < max(xs) and f.calc_center_median().y < y_max:
            kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()


def _trim_edge(obj, keep=None):
    """Remove the outermost ring of base faces, so the hairline cards (rooted on it) overhang the tinted
    scalp instead of ending on a strip of solid base."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    kill = [f for f in bm.faces
            if any(v.is_boundary and not (keep and keep(v.co)) for v in f.verts)]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()


def make(res, body_obj, style_name):
    """Hair as an opaque base layer (the hair volume, darker) under layered strand cards.

    Material slot 0 is the base, slot 1 the cards."""
    style = catalog.HAIR_STYLES[style_name]
    cap, (yc, z_ref, z_top) = _cap(res, body_obj, style, "Hair")
    head_c = np.array([0.0, yc, (z_ref + z_top) / 2])
    hair_cards.orient_outward(cap, head_c)
    part = None
    if style.get("part") is not None:
        # a back-combed part only runs over the front; a hanging style's part runs back to the crown
        part = (style["part"], yc + (0.02 if style.get("flow") == "back" else 0.05))
        _cut_part(cap, *part)
    extras, tie, line = _extras(style, cap, body_obj, yc, z_ref, z_top)
    hair_cards.set_flow(cap, _cap_flow(util.get_coords(cap), style, yc, z_ref, z_top, tie, line))
    curtain = _curtain(res, body_obj, style, yc, z_ref, z_top)
    if curtain:
        hair_cards.orient_outward(curtain, head_c)
        # melt the curtain's top edge onto the cap so the two read as one head of hair, not a step
        _taper_to_scalp(curtain, cap, rings=4, gap=0.0015, near=0.03)
        hair_cards.set_flow(curtain, np.tile([0.0, 0.0, -1.0], (len(curtain.data.vertices), 1)))
    # the hair tie joins the base after the cards are grown, so it never bends the combing directions
    ties = [o for o in extras if o.name.startswith("hair_tie")]
    # braid strands get their own short cards (and never pull the scalp's combing towards them)
    strands = [o for o in extras if o.name.startswith("hair_strand")]
    ties += strands
    inner = None
    if curtain:
        # the face side of hanging hair needs strands too: a flipped copy just inside the curtain
        inner = curtain.copy()
        inner.data = curtain.data.copy()
        util.link(inner)
        for p in inner.data.polygons:
            p.flip()
        inner.data.update()
        garments.offset_along_normals(inner, 0.0025)
    parts = [cap] + ([curtain] if curtain else []) + [o for o in extras if o not in ties]
    if len(parts) > 1:
        with bpy.context.temp_override(active_object=cap, selected_editable_objects=parts, object=cap):
            bpy.ops.object.join()
    obj = cap
    # where the cap's edge is hidden under hanging hair it is not a hairline: no taper, no edge cards
    covered = (lambda p: abs(_theta(p, yc)) > math.radians(80)) if curtain else None
    # big volumes (afro) need a wider taper to come down to the hairline
    _taper_to_scalp(obj, body_obj, rings=5 + int(style["offset"] / 0.006), near=style["offset"] * 2.5 + 0.03,
                    keep=covered)
    cards = hair_cards.grow(obj, style, skip_edge=covered) if style.get("cards", True) else None
    n_cards = cards["cards"] if cards else 0
    if inner and cards:
        inner_cards = hair_cards.grow(inner, style, seed=2, hairline=False)
        n_cards += inner_cards["cards"]
        bpy.data.objects.remove(inner, do_unlink=True)
        with bpy.context.temp_override(active_object=cards, selected_editable_objects=[cards, inner_cards],
                                       object=cards):
            bpy.ops.object.join()
    elif inner:
        bpy.data.objects.remove(inner, do_unlink=True)
    if strands and style.get("cards", True):
        sstyle = dict(style, card_len=style.get("braid_period", 0.05) * 0.7, card_width=0.008, card_lift=0.0008,
                      card_density=4.0, card_jitter=0.04)
        grown = [hair_cards.grow(o, sstyle, seed=10 + i, hairline=False) for i, o in enumerate(strands)]
        grown = [g for g in grown if len(g.data.polygons)]
        n_cards += sum(g["cards"] for g in grown)
        if grown:
            if cards is None:
                cards, grown = grown[0], grown[1:]
            if grown:
                with bpy.context.temp_override(active_object=cards, selected_editable_objects=[cards] + grown,
                                               object=cards):
                    bpy.ops.object.join()
    if cards:
        _trim_edge(obj, keep=covered)
    # the base sits just under the card roots (and, at the tapered hairline, just under the skin)
    garments.offset_along_normals(obj, -0.0008)
    if ties:
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj] + ties, object=obj):
            bpy.ops.object.join()
    co = util.get_coords(obj)
    cylindrical_uv(obj, yc, co[:, 2].min(), co[:, 2].max())
    n_base = len(obj.data.polygons)
    if cards:
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj, cards], object=obj):
            bpy.ops.object.join()
    obj.data.materials.clear()
    for _ in range(2):  # slots must exist, or the card faces' material index is dropped
        obj.data.materials.append(None)
    mi = np.zeros(len(obj.data.polygons), dtype=np.int32)
    mi[n_base:] = 1  # the active object's faces come first after a join
    obj.data.polygons.foreach_set("material_index", mi)
    if "flow" in obj.data.attributes:
        obj.data.attributes.remove(obj.data.attributes["flow"])
    skin_hair(obj, res, body_obj)
    util.add_armature_modifier(obj, res.arm)
    obj["hair_style"] = style_name
    obj["hair_cards"] = n_cards
    return obj
