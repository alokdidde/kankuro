"""Dupatta: a long scarf laid along a path
over the body. The strip is a fixed grid, so its UVs (unrolled strip) are the same on every body."""
import numpy as np
from mathutils import Vector

from . import garments, util

ROWS, COLS = 240, 11


def _cast(bvhs, origin, direction):
    """First hit of a ray against several BVHs (body and worn garments): (point, normal) or None."""
    best = None
    for b in bvhs:
        hit, nrm, _, d = b.ray_cast(Vector(origin), Vector(direction), 3.0)
        if hit is not None and (best is None or d < best[2]):
            best = (np.array(hit), np.array(nrm), d)
    return best


def _centerline(res, bvhs, gdef):
    """Path of the dupatta: down the back from the right shoulder, over it, across the front in a
    U under the bust, over the left shoulder and down the back. Returns points, normals, widths."""
    heads = {b.name: b.head_local for b in res.arm.data.bones}
    neck = heads["neck_01"]
    xs = 0.68 * heads["upperarm_l"].x  # where the scarf crosses the shoulders, between neck and shoulder joint
    z_low = heads["spine_02"].z + gdef["drop"] * (neck.z - heads["spine_02"].z)  # bottom of the front U
    z_end = heads["thigh_l"].z + gdef["end"] * (heads["calf_l"].z - heads["thigh_l"].z)
    pts, nrms = [], []

    wid = []

    def add(p, w):
        if p is not None:
            pts.append(p[0])
            nrms.append(p[1] if p[1][2] > -0.9 else -p[1])
            wid.append(w)

    # front U (left shoulder to right shoulder via the low point under the bust)
    front = []
    for u in np.linspace(1, -1, 61):
        x = xs * u * (1 + 0.25 * (1 - abs(u)))  # a little wider than straight lines from the shoulders
        z = z_low + (neck.z - 0.04 - z_low) * abs(u) ** 2.2
        front.append(_cast(bvhs, (x, -1.0, z), (0, 1, 0)))
    # over each shoulder: rays straight down at fixed x, sweeping from the front surface to the back
    def over(x, y0, y1):
        return [_cast(bvhs, (x, y, neck.z + 0.1), (0, 0, -1)) for y in np.linspace(y0, y1, 15)]

    # down the back, ends spreading slightly outwards
    def back(sign):
        return [_cast(bvhs, (sign * (xs + 0.015 * t), 1.0, neck.z - 0.03 - t * (neck.z - 0.03 - z_end)), (0, -1, 0))
                for t in np.linspace(0, 1, 60)]

    y_front = front[0][0][1] if front[0] else neck.y - 0.08
    y_back = neck.y + 0.08
    # (front[::-1] runs from -x to +x, so the whole path is continuous). Widths: the cloth is folded
    # narrow over the shoulders, a little wider across the chest, and opens out down the back.
    wb, wf, ws = gdef["width"], gdef["width"] * 0.5, gdef["width"] * 0.3
    tb = np.linspace(0, 1, 60)
    seq = list(zip(back(-1)[::-1], (ws + (wb - ws) * tb ** 0.6)[::-1]))
    seq += [(p, ws) for p in over(-xs, y_back, y_front)]
    seq += list(zip(front[::-1], ws + (wf - ws) * (1 - np.abs(np.linspace(-1, 1, 61))) ** 0.5))
    seq += [(p, ws) for p in over(xs, y_front, y_back)]
    seq += list(zip(back(1), ws + (wb - ws) * tb ** 0.6))
    for p, w in seq:
        add(p, w)
    pts, nrms, wid = np.array(pts), np.array(nrms), np.array(wid)
    # smooth the path and resample it evenly
    for _ in range(6):
        pts[1:-1] = 0.5 * pts[1:-1] + 0.25 * (pts[:-2] + pts[2:])
        nrms[1:-1] = 0.5 * nrms[1:-1] + 0.25 * (nrms[:-2] + nrms[2:])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], ROWS)
    P = np.stack([np.interp(t, s, pts[:, k]) for k in range(3)], 1)
    N = np.stack([np.interp(t, s, nrms[:, k]) for k in range(3)], 1)
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    for _ in range(10):
        wid[1:-1] = 0.5 * wid[1:-1] + 0.25 * (wid[:-2] + wid[2:])
    W = np.interp(t, s, wid)
    P += N * gdef["offset"]
    return P, N, W, t / s[-1], s[-1]


def make(res, body_obj, gid, gdef, layer_rank=0, worn=None):
    bvh = garments.body_bvh(body_obj)
    bvhs = [bvh] + ([worn] if worn is not None else [])
    P, N, W, S, length = _centerline(res, bvhs, gdef)
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    B = np.cross(T, N)
    B /= np.linalg.norm(B, axis=1, keepdims=True)
    v = np.linspace(-0.5, 0.5, COLS)
    gathered = (1 - W / W.max())[:, None]
    # soft pleats across the width, deeper where the cloth is gathered on the shoulders
    pleat = (0.001 + 0.004 * gathered) * np.sin(2 * np.pi * 2.5 * (v[None, :] + 0.5))
    co = P[:, None, :] + B[:, None, :] * (W[:, None] * v[None, :])[..., None] + N[:, None, :] * pleat[..., None]
    co = co.reshape(-1, 3)
    faces = [[r * COLS + c, r * COLS + c + 1, (r + 1) * COLS + c + 1, (r + 1) * COLS + c]
             for r in range(ROWS - 1) for c in range(COLS - 1)]
    obj = util.make_mesh(gid, co, faces)
    gap = gdef["offset"] + 0.001 * layer_rank
    garments.conform(obj, bvh, gap)
    if worn is not None:
        garments.conform_over(obj, bvh, worn, 0.005)
    # unrolled strip UVs: length along u, width along v, same scale both ways
    sc = 0.96 / length
    me = obj.data
    uv = me.uv_layers.new(name="UVMap")
    data = np.zeros((len(me.loops), 2))
    for p in me.polygons:
        for li in p.loop_indices:
            vi = me.loops[li].vertex_index
            r, c = divmod(vi, COLS)
            data[li] = (0.02 + S[r] * 0.96, 0.5 + W.max() * v[c] * sc)
    uv.data.foreach_set("uv", data.ravel())
    # skin: nearest body weights, but the hanging ends follow the back rather than the legs
    zc = res.arm.data.bones["pelvis"].head_local.z + 0.08
    real = util.get_coords(obj)
    util.set_coords(obj, np.column_stack([real[:, :2], np.maximum(real[:, 2], zc)]))
    garments.skin_from_body(obj, body_obj, res.bones, smooth_iters=20)
    util.set_coords(obj, real)
    sol = obj.modifiers.new("thickness", "SOLIDIFY")
    sol.thickness = 0.001
    sol.offset = 1.0
    sol.use_rim = True
    garments.apply_modifier(obj, sol)
    for p in obj.data.polygons:
        p.use_smooth = True
    util.add_armature_modifier(obj, res.arm)
    obj["garment_type"] = gdef.get("type", "dupatta")
    return obj, {"scale_px_per_m": sc, "layout": "unrolled strip: u along the length, v across the width"}
