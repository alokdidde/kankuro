"""Dhoti details: the pleated front panel (the gathered end tucked in at the front of the waist and
hanging down between the legs), the rolled waist and the kachha tuck at the back.

The legs of the dhoti are the loose trouser legs from garments.loosen_legs; these details are what
make it read as a wrapped cloth rather than baggy trousers."""
import numpy as np
from mathutils import Vector, interpolate

from . import drape, garments, util

ROWS, COLS = 70, 33


def _normals(obj):
    obj.data.update()
    n = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("normal", n)
    return n.reshape(-1, 3)


def waist_roll(obj, height=0.045, bulge=0.007):
    """Roll the top `height` metres of the cloth over into a soft rounded band."""
    co = util.get_coords(obj)
    top = co[:, 2].max()
    t = np.clip((top - co[:, 2]) / height, 0, 1)
    prof = np.sin(np.pi * t) ** 0.8 * (t < 1)
    util.set_coords(obj, co + _normals(obj) * (bulge * prof)[:, None])


def back_tuck(obj, res, depth=0.02, width=0.05, length=0.26, folds=4):
    """The kachha: the cloth gathered and tucked in at the centre back of the waist, a short bunch of
    vertical folds that fills the small of the back and the top of the seat."""
    co = util.get_coords(obj)
    top = co[:, 2].max()
    yc = res.arm.data.bones["pelvis"].head_local.y
    back = co[:, 1] > yc
    s = np.clip(co[:, 0] / width, -1, 1)
    f = np.clip((top - co[:, 2]) / length, 0, 1)
    env = (1 - s * s) ** 1.5 * np.sin(np.pi * np.sqrt(f)) * (np.abs(co[:, 0]) < width) * (f < 1)
    ridge = 0.6 + 0.4 * np.abs(np.sin(np.pi * folds * (s + 1) / 2))
    co[:, 1] += back * depth * env * ridge
    util.set_coords(obj, co)


def _uv_from(surface, P):
    """UV of the nearest point on `surface` for each point (the panel reuses the cloth under it)."""
    me = surface.data
    sco = util.get_coords(surface)
    n = surface.get("shell_faces", len(me.polygons))
    polys = [list(p.vertices) for p in me.polygons[:n]]
    bvh = garments.BVHTree.FromPolygons([Vector(c) for c in sco], polys)
    uv = me.uv_layers["UVMap"].data
    out = np.zeros((len(P), 2))
    for i, p in enumerate(P):
        loc, _, fi, _ = bvh.find_nearest(Vector(p))
        poly = me.polygons[fi]
        w = interpolate.poly_3d_calc([Vector(sco[v]) for v in poly.vertices], loc)
        out[i] = sum(wk * np.array(uv[li].uv) for wk, li in zip(w, poly.loop_indices))
    return out


def front_pleats(res, body_obj, dhoti_obj, p):
    """Build the pleated front panel over the dhoti: a strip of cloth from the front of the waist down
    between the legs, folded into knife pleats that open towards the hem. Returns the mesh object."""
    gap = p.get("gap", 0.004)
    co = util.get_coords(dhoti_obj)
    top, bot = co[:, 2].max(), co[:, 2].min()
    z0 = top - 0.03
    z1 = bot + p.get("hem_up", 0.04)
    x0, x1 = p.get("x", (-0.075, 0.075))
    bvh = [garments.body_bvh(body_obj), garments.mesh_bvh([dhoti_obj])]
    xs = np.linspace(x0, x1, COLS)
    zs = np.linspace(z0, z1, ROWS)
    # lay it on the front of the dhoti; where a ray runs deep into the gap between the legs, the
    # cloth spans across instead (filled in from the columns either side)
    Y = np.full((ROWS, COLS), np.nan)
    for i, z in enumerate(zs):
        for j, x in enumerate(xs):
            hit = drape._ray(bvh, (x, -1.0, z), (0, 1, 0))
            if hit is not None:
                Y[i, j] = hit[1]
        good = ~np.isnan(Y[i])
        if good.any():
            deep = Y[i] > np.nanmin(Y[i]) + 0.035
            good &= ~deep
            Y[i] = np.interp(xs, xs[good], Y[i][good])
        elif i:
            Y[i] = Y[i - 1]
    P = np.stack(np.broadcast_arrays(xs[None, :], Y - gap, zs[:, None]), -1).astype(float)
    pinned = np.zeros((ROWS, COLS), dtype=bool)
    pinned[0] = True  # tucked in at the waist
    P = drape._relax(P, pinned, bvh, gap, 20)
    # knife pleats: folds across the width, flat at the waist and opening up towards the hem; hand
    # folded, so not all the same width
    s = np.linspace(0, 1, COLS)
    f = np.linspace(0, 1, ROWS)
    n = p.get("folds", 6)
    rng = np.random.default_rng(7)
    edges = np.cumsum(np.concatenate([[0], 1 + 0.35 * rng.uniform(-1, 1, n)]))
    ph = np.interp(s, edges / edges[-1], np.arange(n + 1))
    saw = np.abs((ph % 1.0) - 0.5) * 2  # 1 at the fold edges, 0 between
    fold = p.get("depth", 0.012) * (0.25 + 0.75 * f[:, None] ** 0.7) * saw[None, :] ** 1.5
    P[:, :, 1] -= fold
    P[:, :, 0] += (s[None, :] - 0.5) * p.get("flare", 0.04) * f[:, None] ** 1.5  # fans out a little
    idx = np.arange(ROWS * COLS).reshape(ROWS, COLS)
    faces = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], axis=-1).reshape(-1, 4)
    flat = P.reshape(-1, 3)
    uvs = _uv_from(dhoti_obj, flat - np.array([0, -gap - 0.004, 0]))
    obj = util.make_mesh("_dhoti_pleats", flat, faces.tolist(), uvs, faces.tolist())
    a, b, c = flat[faces[0, :3]]
    if np.cross(b - a, c - a)[1] > 0:  # face the front (-Y)
        obj.data.flip_normals()
    garments.skin_from_body(obj, body_obj, res.bones, smooth_iters=10)
    garments.skirt_weights(obj, res)
    return obj
