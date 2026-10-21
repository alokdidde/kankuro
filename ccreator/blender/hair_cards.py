"""Hair cards: narrow ribbons with a strand alpha texture, grown over a guide surface.

The guide is the hair volume (scalp cap, curtain, ponytail, ...) with a per-vertex "flow" attribute that
says which way the hair is combed there. Each card starts at a root on the guide and is walked along the
flow over the surface, lifted a little off it, so cards overlap in layers like real clumps of hair.
Eyebrows are grown the same way over the skin, as single tapered hairs."""
import math

import bpy
import numpy as np
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

from . import body as bodymod, util

COLUMNS = 4  # strand variants side by side in the atlas (hairtex.COLUMNS)


def set_flow(obj, vecs):
    att = obj.data.attributes.get("flow") or obj.data.attributes.new("flow", "FLOAT_VECTOR", "POINT")
    att.data.foreach_set("vector", np.asarray(vecs, dtype=np.float32).ravel())


def get_flow(obj):
    att = obj.data.attributes.get("flow")
    out = np.zeros(len(obj.data.vertices) * 3, dtype=np.float32)
    if att:
        att.data.foreach_get("vector", out)
    return out.reshape(-1, 3)


def orient_outward(obj, ref=None):
    """Flip an open surface so most faces point away from ref (default: its centroid)."""
    me = obj.data
    co = util.get_coords(obj)
    c = co.mean(0) if ref is None else np.asarray(ref)
    s = 0.0
    for p in me.polygons:
        s += np.dot(np.array(p.normal), np.array(p.center) - c) * p.area
    if s < 0:
        for p in me.polygons:
            p.flip()
        me.update()


class _Surface:
    def __init__(self, co, faces, flow=None):
        self.co = co
        self.bvh = BVHTree.FromPolygons([Vector(p) for p in co], faces)
        self.flow = flow
        if flow is not None:
            self.kd = kdtree.KDTree(len(co))
            for i, p in enumerate(co):
                self.kd.insert(Vector(p), i)
            self.kd.balance()

    def nearest(self, p):
        loc, nrm, _, dist = self.bvh.find_nearest(Vector(p))
        if loc is None:
            return None, None, 1e9
        return np.array(loc), np.array(nrm), dist

    def flow_at(self, p):
        hits = self.kd.find_n(Vector(p), 4)
        w = np.array([1.0 / (d + 1e-4) for _, _, d in hits])
        f = sum(wi * self.flow[i] for wi, (_, i, _) in zip(w, hits)) / w.sum()
        return f


def _tangent(v, n):
    t = v - n * np.dot(v, n)
    l = np.linalg.norm(t)
    return t / l if l > 1e-6 else None


def _rotate(v, n, a):
    """Rotate v about axis n by angle a."""
    return v * math.cos(a) + np.cross(n, v) * math.sin(a) + n * np.dot(n, v) * (1 - math.cos(a))


def _walk(surf, root, length, step, direction, lift, curl=0.0, rng=None):
    """Points of one strand walked over the surface. direction(p, n) -> tangent direction or None."""
    p, n, _ = surf.nearest(root)
    if p is None:
        return None
    pts, nrms = [], []
    s, steps = 0.0, max(2, int(math.ceil(length / step)))
    h = step if steps * step <= length else length / steps
    phase = rng.uniform(0, 6.28) if rng is not None else 0.0
    for k in range(steps + 1):
        t = s / length
        pts.append(p + n * lift(t))
        nrms.append(n)
        if k == steps:
            break
        d = direction(p, n)
        if d is None:
            break
        if curl:
            d = _rotate(d, n, curl * math.sin(phase + 9.0 * t))
        q = p + d * h
        p2, n2, dist = surf.nearest(q)
        if p2 is None or dist > h * 0.7:  # walked off the edge of the surface
            break
        p, n = p2, n2
        s += h
    return (np.array(pts), np.array(nrms)) if len(pts) >= 3 else None


def _ribbon(pts, nrms, width, column, bulge, out, v_top=1.0):
    """Append a 3-wide ribbon along pts to out (verts, faces, uvs, normals). Root at v=v_top, tip at v=0."""
    verts, faces, uvs, normals = out
    n_pts = len(pts)
    seg = np.diff(pts, axis=0)
    lens = np.concatenate([[0], np.cumsum(np.linalg.norm(seg, axis=1))])
    tt = lens / max(lens[-1], 1e-6)
    u0, u1 = column / COLUMNS + 0.01, (column + 1) / COLUMNS - 0.01
    base = len(verts)
    for i in range(n_pts):
        d = pts[min(i + 1, n_pts - 1)] - pts[max(i - 1, 0)]
        side = np.cross(nrms[i], d)
        side /= max(np.linalg.norm(side), 1e-9)
        w = width * (1 - 0.35 * tt[i]) / 2
        verts += [pts[i] - side * w, pts[i] + nrms[i] * bulge * (1 - tt[i] * 0.5), pts[i] + side * w]
        v = v_top * (1 - tt[i])
        uvs += [(u0, v), ((u0 + u1) / 2, v), (u1, v)]
        normals += [nrms[i]] * 3
    for i in range(n_pts - 1):
        a, b = base + 3 * i, base + 3 * (i + 1)
        faces += [(a, b, b + 1, a + 1), (a + 1, b + 1, b + 2, a + 2)]


def _mesh(name, verts, faces, uvs, normals):
    """Cards shade with the normals of the surface they lie on (not their own), so the hair reads as one
    smoothly lit volume broken up by strands, instead of a pile of separately lit planks."""
    flat_faces = [list(f) for f in faces]
    obj = util.make_mesh(name, np.array(verts), flat_faces)
    me = obj.data
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    loop_v = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", loop_v)
    uv.data.foreach_set("uv", np.asarray(uvs, dtype=np.float32)[loop_v].ravel())
    for p in me.polygons:
        p.use_smooth = True
    me.normals_split_custom_set_from_vertices([tuple(n) for n in normals])
    return obj


def _sample_surface(co, tris, n, rng):
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    idx = rng.choice(len(tris), size=n, p=area / area.sum())
    r1, r2 = np.sqrt(rng.random(n)), rng.random(n)
    return a[idx] * (1 - r1)[:, None] + b[idx] * (r1 * (1 - r2))[:, None] + c[idx] * (r1 * r2)[:, None], area.sum()


def _tris(obj):
    tris = []
    for p in obj.data.polygons:
        v = list(p.vertices)
        tris += [(v[0], v[i], v[i + 1]) for i in range(1, len(v) - 1)]
    return np.array(tris)


def _boundary_points(obj, spacing):
    """Points spaced along the open edges of the guide (the hairline)."""
    me = obj.data
    co = util.get_coords(obj)
    count = {}
    for p in me.polygons:
        for e in p.edge_keys:
            count[e] = count.get(e, 0) + 1
    pts = []
    for (a, b), c in count.items():
        if c != 1:
            continue
        l = np.linalg.norm(co[b] - co[a])
        k = max(1, int(round(l / spacing)))
        pts += [co[a] + (co[b] - co[a]) * (i + 0.5) / k for i in range(k)]
    return np.array(pts) if pts else np.zeros((0, 3))


def grow(guide, style, seed=1, hairline=True, skip_edge=None):
    """Cards over the guide object (which carries a 'flow' attribute). Returns the new object."""
    rng = np.random.default_rng(seed)
    co = util.get_coords(guide)
    faces = [list(p.vertices) for p in guide.data.polygons]
    surf = _Surface(co, faces, get_flow(guide))
    L = style.get("card_len", 0.07)
    W = style.get("card_width", 0.016)
    lift_max = style.get("card_lift", 0.006)
    density = style.get("card_density", 3.0)
    curl = style.get("curl", 0.0)
    step = min(0.012, L / 4)
    tris = _tris(guide)
    _, area = _sample_surface(co, tris, 1, rng)
    n = int(density * area / (W * L * 0.75))
    roots, _ = _sample_surface(co, tris, n, rng)
    hairline = _boundary_points(guide, W * 0.4) if hairline else np.zeros((0, 3))
    if skip_edge and len(hairline):
        hairline = np.array([p for p in hairline if not skip_edge(p)]).reshape(-1, 3)
    out = ([], [], [], [])
    made = 0

    def direction_for(angle):
        def f(p, nrm):
            v = surf.flow_at(p)
            if np.linalg.norm(v) < 0.15:  # no combing direction here (hair tie, or the end of the flow)
                return None
            t = _tangent(v / np.linalg.norm(v), nrm)
            return None if t is None else _rotate(t, nrm, angle)
        return f

    def backwards(p, nrm):
        d = direction_for(0.0)(p, nrm)
        return None if d is None else -d

    jobs = [(r, False) for r in roots] + [(r, True) for r in hairline]
    for r, edge in jobs:
        length = L * rng.uniform(0.55, 1.0)
        starts = [r]
        if edge:
            # stagger the hairline a few millimetres so it isn't one clean cut line
            fwd = _walk(surf, r, rng.uniform(0.0, 0.006), 0.002, direction_for(0.0), lambda t: 0.0)
            if fwd is not None:
                starts = [fwd[0][-1], r]
        else:
            # a sample point is covered by a card rooted somewhere up-flow of it: walk back to that root.
            # Rooting at the samples themselves would leave a bald band just behind every hairline.
            back = _walk(surf, r, length * rng.uniform(0.0, 0.9), step, backwards, lambda t: 0.0)
            if back is not None:
                starts.insert(0, back[0][-1])
        # roots tuck into the layer below; the card rises off it towards the tip, then settles
        top = 0.0006 if edge else rng.uniform(0.0008, lift_max)

        def lift(t, a=top):
            return 0.0002 + a * math.sin(min(t, 1.0) * math.pi * 0.6) / math.sin(math.pi * 0.6)
        direction = direction_for(rng.normal(0, style.get("card_jitter", 0.06)))
        for r in starts:  # the walked-back root can be a dead end (e.g. the hidden end of a ponytail)
            res = _walk(surf, r, length, step, direction, lift, curl, rng)
            if res is not None:
                break
        if res is None:
            continue
        pts, nrms = res
        w = W * rng.uniform(0.75, 1.2) * (0.6 if edge else 1.0)
        # hairline cards skip the faded-in root of the texture: nothing lies under them to fade into
        _ribbon(pts, nrms, w, int(rng.integers(COLUMNS)), w * 0.08, out, v_top=0.85 if edge else 1.0)
        made += 1
    obj = _mesh("hair_cards", *out)
    obj["cards"] = made
    return obj


# --- eyebrows -----------------------------------------------------------------------------------------

def _eye_frame(res, side):
    vs = bodymod.group_verts(f"helper-{side}-eye")
    p = res.coords[vs]
    return p.mean(0), np.ptp(p[:, 0]) / 2


def brows(res, body_obj, thickness=1.0, arch=0.0, density=1.0, length=1.0, hairs_per_brow=260, seed=3):
    """Eyebrow hairs on the current face. Same arc as the painted brow (textures._brow_mask):
    inner hairs stand up, the body sweeps out towards the temple, lower and upper rows meet in the middle.

    thickness scales the band height, arch (-1 flat .. +1 high) lifts the outer-middle, density scales the
    hair count, length (~0.7-1.2) is how far the tail reaches towards the temple."""
    rng = np.random.default_rng(seed)
    hairs_per_brow = int(hairs_per_brow * density * (0.6 + 0.4 * length))
    co = util.get_coords(body_obj)
    surf = _Surface(co, [list(p.vertices) for p in body_obj.data.polygons])
    out = ([], [], [], [])
    for side in ("l", "r"):
        e, r = _eye_frame(res, side)
        sgn = 1.0 if side == "l" else -1.0  # +x towards the temple on the left
        made = 0
        while made < hairs_per_brow:
            u = rng.uniform(-1.0, length)
            if rng.random() > 1 - 0.55 * max(0.0, u / max(length, 0.1)) ** 1.5:  # the tail thins out
                continue
            if u < -0.7 and rng.random() < 0.45:  # and so does the inner end
                continue
            arc = e[2] + r * (1.45 + 0.35 * (1 - u ** 2)) - r * 0.25 * max(0.0, u)
            arc += r * 0.3 * arch * max(0.0, 1 - (u - 0.3) ** 2 / 1.69)
            thick = r * (0.29 - 0.15 * max(0.0, u)) * (1.15 if u < -0.6 else 1.0) * thickness
            vn = float(np.clip(rng.normal(0, 0.55), -1.1, 1.1))  # -1 lower edge .. +1 upper edge
            x = e[0] + sgn * u * r * 2.1
            z = arc + vn * thick
            hit = surf.bvh.ray_cast(Vector((x, e[1] - 0.2, z)), Vector((0, 1, 0)), 0.4)
            if hit[0] is None:
                continue
            root = np.array(hit[0])
            # angle from vertical towards the temple
            phi = np.interp(u, [-1, -0.6, -0.2, 0.3, 1.0], [12, 30, 62, 80, 98])
            if u > -0.5:
                phi += 22 * vn  # upper hairs point down-out, lower ones up-out
            phi = math.radians(phi + rng.normal(0, 7))
            want = np.array([sgn * math.sin(phi), 0.0, math.cos(phi)])

            def direction(p, n, want=want):
                return _tangent(want, n)
            length = rng.uniform(0.005, 0.008) * (0.75 if u < -0.6 else 1.0)
            res_ = _walk(surf, root, length, length / 4, direction, lambda t: 0.00015 + 0.0006 * t)
            if res_ is None:
                continue
            pts, nrms = res_
            _ribbon(pts, nrms, rng.uniform(0.0003, 0.00045), int(rng.integers(COLUMNS)), 0.0, out)
            made += 1
    obj = _mesh("Eyebrows", *out)
    vg = obj.vertex_groups.new(name="head")
    vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    return obj


def follow_shape_keys(obj, body_obj):
    """Give obj the body's shape keys (same names), each vertex moving with its nearest body vertex, so
    brows ride along with brow raise/frown expressions. Keys that don't move obj are skipped."""
    keys = body_obj.data.shape_keys
    if not keys or len(keys.key_blocks) < 2:
        return 0
    bco = util.get_coords(body_obj)
    kd = kdtree.KDTree(len(bco))
    for i, p in enumerate(bco):
        kd.insert(Vector(p), i)
    kd.balance()
    co = util.get_coords(obj)
    near = np.array([kd.find(Vector(p))[1] for p in co])
    basis = np.empty(len(bco) * 3)
    keys.key_blocks[0].data.foreach_get("co", basis)
    basis = basis.reshape(-1, 3)
    made = 0
    for kb in keys.key_blocks[1:]:
        k = np.empty(len(bco) * 3)
        kb.data.foreach_get("co", k)
        d = (k.reshape(-1, 3) - basis)[near]
        if np.abs(d).max() < 1e-6:
            continue
        if obj.data.shape_keys is None:
            obj.shape_key_add(name="Basis", from_mix=False).value = 0.0
        nk = obj.shape_key_add(name=kb.name, from_mix=False)
        nk.value = 0.0  # bpy 5.2 creates keys at 1.0
        nk.data.foreach_set("co", (co + d).ravel())
        made += 1
    return made
