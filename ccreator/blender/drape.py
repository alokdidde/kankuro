"""Saree (Nivi drape): a floor-length skirt with front pleats, plus the pallu, the loose end of the
saree that crosses the chest from the right hip, is gathered on the left shoulder and hangs down the
back.

The pallu is a strip of cloth laid along a spline path on the body (right hip, across the chest, over
the left shoulder, down the back), wrapped onto the body and the clothes under it, and smoothed. It
uses a fixed grid, so its topology and UVs are the same on every body."""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import util

# The pallu follows the torso (and the left clavicle where it sits on the shoulder), not the arms or legs
PALLU_BONES = ("pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l")
ROWS, COLS = 96, 13
UV_MARGIN = 0.03


def _heads(res):
    return {b.name: np.array(b.head_local) for b in res.arm.data.bones}


def shape_skirt(obj, res, gdef):
    """Lengthen the skirt to just above the floor and fold the front pleats into it."""
    co = util.get_coords(obj)
    top, bot = co[:, 2].max(), co[:, 2].min()
    hem = gdef.get("hem", 0.03)
    # stretch the part below the hips down to the hem height, keeping the waist and hips as they are
    hips = _heads(res)["pelvis"][2] - 0.05
    low = co[:, 2] < hips
    co[low, 2] = hem + (co[low, 2] - bot) * (hips - hem) / max(hips - bot, 1e-6)
    # Front pleats: a panel of folds at the centre front, flat at the waistband and opening out
    # towards the hem, where the panel also flares forward a little
    p = gdef.get("pleats", {})
    x0, x1 = p.get("x", (-0.075, 0.085))
    n_folds = p.get("folds", 7)
    yc = (co[:, 1].min() + co[:, 1].max()) / 2
    front = co[:, 1] < yc
    f = np.clip((top - 0.08 - co[:, 2]) / max(top - 0.08 - hem, 1e-6), 0, 1)  # 0 at waistband, 1 at hem
    s = np.clip((co[:, 0] - x0) / (x1 - x0), 0, 1)
    window = np.sin(np.pi * s) ** 0.6
    fold = 0.5 - 0.5 * np.cos(2 * np.pi * n_folds * s)
    out = front * window * (f ** 0.8) * (p.get("depth", 0.014) * fold + p.get("flare", 0.03) * f)
    co[:, 1] -= out
    util.set_coords(obj, co)


def _catmull_rom(pts, n):
    """n points evenly spaced by arc length on a Catmull-Rom spline through pts; also each anchor's
    arc-length fraction."""
    P = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    dense = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, 40, endpoint=False):
            dense.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    dense.append(pts[-1])
    dense = np.array(dense)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))])
    frac = arc / arc[-1]
    s = np.linspace(0, 1, n)
    out = np.stack([np.interp(s, frac, dense[:, k]) for k in range(3)], axis=1)
    anchor_frac = frac[np.arange(len(pts)) * 40]
    return out, anchor_frac


def _wrap(P, bvhs, gap):
    """Lay points on the body and whatever is worn over it: take the nearest point on the skin, then
    step out along the skin normal past every layer that normal passes through (like conform_over)."""
    body, outer = bvhs[0], bvhs[1:]
    for i, p in enumerate(P):
        loc, nrm, _, _ = body.find_nearest(Vector(p))
        if loc is None:
            continue
        h = 0.0
        for b in outer:
            hit = b.ray_cast(loc + nrm * 0.0005, nrm, 0.15)
            if hit[0] is not None:
                h = max(h, hit[3])
        P[i] = np.array(loc + nrm * (h + gap))
    return P


def _ray(bvhs, origin, direction):
    """First hit of a ray on any of the surfaces."""
    hits = [bvh.ray_cast(Vector(origin), Vector(direction).normalized(), 3.0) for bvh in bvhs]
    hits = [h for h in hits if h[0] is not None]
    return np.array(min(hits, key=lambda h: h[3])[0]) if hits else None


def _anchors(res, bvh, waist_z, drop):
    """Path of the pallu's centre line, as points on the surface it lies on."""
    H = _heads(res)
    pz, nz = H["pelvis"][2], H["neck_01"][2]
    sh, neck = H["upperarm_l"], H["neck_01"]
    tz = lambda t: pz + t * (nz - pz)
    yc = H["spine_02"][1]
    sx = 0.4 * neck[0] + 0.6 * sh[0]          # on the shoulder, between the neck and the arm
    front = lambda x, z: _ray(bvh, (x, -1.0, z), (0, 1, 0))
    back = lambda x, z: _ray(bvh, (x, 1.0, z), (0, -1, 0))
    pts = [
        _ray(bvh, (-1.0, yc, waist_z), (1, 0, 0)),      # right side of the waist, where it comes round
        front(-0.07, tz(0.42)),
        front(0.06, tz(0.70)),
        front(sx - 0.02, tz(0.9)),
        _ray(bvh, (sx, yc, 3.0), (0, 0, -1)),          # gathered on top of the left shoulder
        back(sx - 0.02, tz(0.86)),
        back(0.08, tz(0.55)),
        back(0.05, waist_z),
        back(0.04, waist_z - drop),                    # hanging end
    ]
    widths = [0.14, 0.22, 0.25, 0.14, 0.10, 0.18, 0.26, 0.27, 0.28]
    if any(p is None for p in pts):
        raise RuntimeError("pallu path missed the body")
    return np.array(pts), np.array(widths), 4


def _relax(P, pinned, bvhs, gap, iters=12):
    """Smooth out wrinkles from the initial wrap: Laplacian smoothing over the grid (along the strip
    only on its long edges, so it keeps its width), each step wrapped back onto the surface it lies on."""
    X = P.copy()
    free = ~pinned
    for _ in range(iters):
        L = np.zeros_like(X)
        L[1:-1] += 0.5 * (X[:-2] + X[2:]) - X[1:-1]
        L[:, 1:-1] += 0.5 * (X[:, :-2] + X[:, 2:]) - X[:, 1:-1]
        X[free] += 0.4 * L[free]
        X = _wrap(X.reshape(-1, 3), bvhs, gap).reshape(X.shape)
    return X


def pallu(res, body_obj, skirt_obj, worn, gdef, uvinfo):
    """Build the pallu on this body, skinned to the torso. Returns the new mesh object."""
    from . import garments
    p = gdef.get("pallu", {})
    gap = p.get("gap", 0.005)
    bvh = [garments.body_bvh(body_obj), garments.mesh_bvh([skirt_obj])] + ([worn] if worn is not None else [])
    waist_z = util.get_coords(skirt_obj)[:, 2].max() - 0.015
    anchors, widths, pin_anchor = _anchors(res, bvh, waist_z, p.get("drop", 0.45))
    C, afrac = _catmull_rom(anchors, ROWS)
    s = np.linspace(0, 1, ROWS)
    w = np.interp(s, afrac, widths)
    # width direction: across the path, along the surface
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    N = np.array([np.array(bvh[0].find_nearest(Vector(c))[1]) for c in C])
    B = np.cross(T, N)
    B /= np.linalg.norm(B, axis=1, keepdims=True)
    for i in range(1, ROWS):  # no twists
        if np.dot(B[i], B[i - 1]) < 0:
            B[i] = -B[i]
    across = np.linspace(-0.5, 0.5, COLS)
    P = C[:, None, :] + B[:, None, :] * (w[:, None] * across[None, :])[..., None]
    P = _wrap(P.reshape(-1, 3), bvh, gap).reshape(ROWS, COLS, 3)
    pinned = np.zeros((ROWS, COLS), dtype=bool)
    pinned[0] = pinned[-1] = True
    pin = int(round(afrac[pin_anchor] * (ROWS - 1)))
    pinned[pin] = True
    P = _relax(P, pinned, bvh, gap, p.get("relax", 12))
    # Down the back the pallu hangs from the shoulder blades instead of hugging the small of the back
    # and the hips: going down, each column never comes closer to the body than it was above
    # (characters face -Y, so the back is +Y), and below the hips it falls straight. Soft vertical
    # folds open up towards the hanging end.
    i0 = pin + 1
    P[i0:, :, 1] = np.maximum.accumulate(P[i0:, :, 1], axis=0)
    hang = C[i0:, 2] < waist_z + 0.1  # below the waist it hangs flat rather than wrapping round the hips
    P[i0:][hang, :, 0] = C[i0:][hang, None, 0] + B[i0:][hang, None, 0] * (w[i0:][hang, None] * across[None, :])
    k = np.clip((C[i0, 2] - C[i0:, 2]) / max(C[i0, 2] - C[-1, 2], 1e-6), 0, 1)
    ripple = np.sin(np.pi * 3 * (across + 0.5)) ** 2
    P[i0:, :, 1] += p.get("folds", 0.012) * (k ** 1.5)[:, None] * ripple[None, :]
    # faces + UVs: the strip unrolled along the top of the texture
    idx = np.arange(ROWS * COLS).reshape(ROWS, COLS)
    faces = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], axis=-1).reshape(-1, 4)
    S = uvinfo["scale_px_per_m"]
    v0 = uvinfo["pallu_v0"]
    uu = UV_MARGIN + s * (1 - 2 * UV_MARGIN)
    vv = v0 + (across + 0.5) * p.get("uv_width", 0.42) * S
    uvs = np.stack(np.meshgrid(uu, vv, indexing="ij"), axis=-1).reshape(-1, 2)
    # make faces point outwards (away from the surface under the strip)
    a, b, c = P.reshape(-1, 3)[faces[0, :3]]
    if np.dot(np.cross(b - a, c - a), N[0]) < 0:
        faces = faces[:, ::-1]
    obj = util.make_mesh("_pallu", P.reshape(-1, 3), faces.tolist(), uvs, faces.tolist())
    # weights: nearest body weights restricted to the torso, then smoothed along the strip
    garments.skin_from_body(obj, body_obj, res.bones, smooth_iters=0)
    W = util.weight_matrix(obj, res.bones)
    keep = np.array([b in PALLU_BONES for b in res.bones])
    W[:, ~keep] = 0
    W[W.sum(1) < 1e-6, res.bones.index("spine_01")] = 1.0
    W /= W.sum(1, keepdims=True)
    Wg = W.reshape(ROWS, COLS, -1)
    for _ in range(25):
        Wg[1:-1] = 0.5 * Wg[1:-1] + 0.25 * (Wg[:-2] + Wg[2:])
        Wg[:, 1:-1] = 0.5 * Wg[:, 1:-1] + 0.25 * (Wg[:, :-2] + Wg[:, 2:])
    util.set_weight_matrix(obj, Wg.reshape(len(W), -1), res.bones)
    return obj


def saree_uv(uv, uvinfo):
    """Fit the skirt's front/back flat sketch into the lower part of the texture, leaving a band
    across the top for the pallu strip, all at the same scale (pixels per metre)."""
    S_pallu = (1 - 2 * UV_MARGIN) / 1.75   # the pallu (~1.75 m) spans the width of the texture
    k = S_pallu / uvinfo["scale_px_per_m"]
    uv = uv.reshape(-1, 2).copy()
    uv[:, 0] = 0.5 + (uv[:, 0] - 0.5) * k
    uv[:, 1] = UV_MARGIN + uv[:, 1] * k
    top = uv[:, 1].max()
    info = dict(uvinfo, scale_px_per_m=S_pallu, front_center_u=0.5 - 0.25 * k, back_center_u=0.5 + 0.25 * k,
                pallu_v0=top + 0.04, layout="saree",
                labels=[("SKIRT FRONT", 0.5 - 0.25 * k, top + 0.035), ("SKIRT BACK", 0.5 + 0.25 * k, top + 0.035),
                        ("PALLU: waist end -> shoulder -> hanging end", 0.5, 0.985)])
    return uv.ravel(), info
