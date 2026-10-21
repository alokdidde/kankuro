"""Per-garment shading data baked from the dressed character: ambient occlusion and joint creases.

Both are computed per vertex in Blender, then rasterised into the garment's UV layout (fabric.raster_attr)
so they end up in the exported albedo/normal maps and work in any glTF viewer.
"""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .. import fabric
from . import rig, util

# chains of bones along which cloth bunches; creases are rings of constant distance along the chain.
# Joints: (bone whose head is the joint, sigma m, strength). No joints sit where chains meet (shoulder,
# hip) because the distance coordinate jumps there.
CHAINS = {
    "{s}arm": (["upperarm_{s}", "lowerarm_{s}", "hand_{s}"],
               [("lowerarm_{s}", 0.055, 1.0), ("hand_{s}", 0.04, 0.7)]),
    "{s}leg": (["thigh_{s}", "calf_{s}", "foot_{s}"],
               [("calf_{s}", 0.065, 0.9), ("foot_{s}", 0.07, 0.9)]),
}
TORSO = (["pelvis", "spine_01", "spine_02", "spine_03"], [("spine_01", 0.07, 0.3)])
AO_RAYS = 16
AO_DIST = 0.07  # m: local occlusion (collars, armpits, layer overlaps), not whole-body shadowing


def _chains(legs=True):
    out = [TORSO]
    for side in ("l", "r"):
        for key, (bones, joints) in CHAINS.items():
            if key.endswith("leg") and not legs:
                joints = []
            out.append(([b.format(s=side) for b in bones], [(j.format(s=side), sg, a) for j, sg, a in joints]))
    return out


def scene_bvh(objs):
    verts, polys = [], []
    off = 0
    for o in objs:
        co = util.get_coords(o)
        mw = np.array(o.matrix_world)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        verts.append(co)
        polys += [[i + off for i in p.vertices] for p in o.data.polygons]
        off += len(co)
    return BVHTree.FromPolygons([Vector(v) for v in np.concatenate(verts)], polys)


def _hemisphere(k, rng):
    u, v = rng.random(k), rng.random(k)
    r, phi = np.sqrt(u), 2 * np.pi * v
    return np.stack([r * np.cos(phi), r * np.sin(phi), np.sqrt(1 - u)], 1)  # cosine weighted, +Z


def vertex_ao(obj, bvh, rng):
    me = obj.data
    mw = np.array(obj.matrix_world)
    co = util.get_coords(obj) @ mw[:3, :3].T + mw[:3, 3]
    nrm = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3) @ mw[:3, :3].T
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9
    dirs = _hemisphere(AO_RAYS, rng)
    up = np.where(np.abs(nrm[:, 2:3]) < 0.9, [[0, 0, 1]], [[1, 0, 0]])
    t = np.cross(nrm, up)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    bt = np.cross(nrm, t)
    world = (dirs[None, :, 0:1] * t[:, None] + dirs[None, :, 1:2] * bt[:, None]
             + dirs[None, :, 2:3] * nrm[:, None]).tolist()
    origins = (co + nrm * 0.002).tolist()
    occ = np.zeros(len(co))
    cast = bvh.ray_cast
    for i, o in enumerate(origins):
        o = Vector(o)
        acc = 0.0
        for d in world[i]:
            hit = cast(o, Vector(d), AO_DIST)
            if hit[0] is not None:
                acc += 1 - (hit[3] / AO_DIST) ** 0.5
        occ[i] = acc
    return 1 - occ / AO_RAYS


def vertex_creases(obj, arm, body_bvh, bones, legs=True):
    """Distance along the limb chain (s) and crease weight per vertex. Weight is blended over the vertex's
    skin weights (no seams where the dominant bone changes) and fades out where cloth hangs loose."""
    pos = rig.bone_positions(arm)
    mw = np.array(obj.matrix_world)
    co = util.get_coords(obj) @ mw[:3, :3].T + mw[:3, 3]
    W = util.weight_matrix(obj, bones)
    col = {b: i for i, b in enumerate(bones)}
    chains = _chains(legs)
    s = np.zeros((len(chains), len(co)))
    s_w = np.zeros((len(chains), len(co)))
    crease = np.zeros(len(co))
    for ci, (chain, joints) in enumerate(chains):
        if any(b not in pos for b in chain):
            continue
        start, cum = 0.0, {}
        for b in chain:
            cum[b] = start
            start += np.linalg.norm(pos[b][1] - pos[b][0])
        for b in chain:
            if b not in col:
                continue
            w = W[:, col[b]]
            sel = w > 1e-3
            if not sel.any():
                continue
            h, tl = pos[b]
            d = tl - h
            ln = np.linalg.norm(d)
            t = np.clip((co[sel] - h) @ (d / ln), -0.15, ln + 0.15)
            sb = cum[b] + t
            s[ci, sel] += w[sel] * sb
            s_w[ci, sel] += w[sel]
            c = np.zeros(sel.sum())
            for jb, sigma, amp in joints:
                c = np.maximum(c, amp * np.exp(-0.5 * ((sb - cum[jb]) / sigma) ** 2))
            crease[sel] += w[sel] * c
    # distance along the chain that holds most of the vertex's weight (mixing chains is meaningless)
    best = np.argmax(s_w, axis=0)
    idx = np.arange(len(co))
    s = np.where(s_w[best, idx] > 0, s[best, idx] / np.maximum(s_w[best, idx], 1e-9), 0)
    # loose cloth (skirts, dhoti, saree) doesn't bunch at the knee: fade with distance from the skin
    gap = np.ones(len(co))
    for i, p in enumerate(co):
        hit = body_bvh.find_nearest(Vector(p))
        if hit[0] is not None:
            gap[i] = hit[3]
    crease *= np.clip((0.04 - gap) / 0.025, 0, 1)
    return s, crease


def bake_maps(obj, arm, body_obj, scene_objs, bones, size, seed=3, leg_creases=True):
    """Rasterised (ao, chain_s, crease_w, detail) maps in obj's UV layout, or Nones without UVs.
    detail is 1 where texels are evenly spread and falls toward 0 where the UVs are squeezed.
    leg_creases=False for skirts and drapes: they hang across the legs, so knees don't bunch them."""
    me = obj.data
    if not me.uv_layers:
        return None, None, None, None
    rng = np.random.default_rng(seed)
    ao = vertex_ao(obj, scene_bvh(scene_objs), rng)
    s, cw = vertex_creases(obj, arm, scene_bvh([body_obj]), bones, leg_creases)
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get("loops", tl)
    tv = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tv)
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    tri_uv = uv[tl].reshape(nt, 3, 2)
    vals = np.stack([ao, s, cw], 1)[tv].reshape(nt, 3, 3)
    # texel density per triangle (3D area / UV area): the flat-sketch projection squeezes the sides of the
    # body into a thin strip, where fine detail would smear into streaks
    mw = np.array(obj.matrix_world)
    co = util.get_coords(obj) @ mw[:3, :3].T
    p3 = co[tv].reshape(nt, 3, 3)
    a3 = 0.5 * np.linalg.norm(np.cross(p3[:, 1] - p3[:, 0], p3[:, 2] - p3[:, 0]), axis=1)
    e1, e2 = tri_uv[:, 1] - tri_uv[:, 0], tri_uv[:, 2] - tri_uv[:, 0]
    a2 = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    dens = np.sqrt(a3 / np.maximum(a2, 1e-12))
    ref = np.median(dens[a2 > 0])
    # anisotropy: singular values of the 3D -> UV map. Squeezed in one direction only keeps the area but
    # still smears detail, and its tangent frame is unreliable for normal mapping
    q1, q2 = p3[:, 1] - p3[:, 0], p3[:, 2] - p3[:, 0]
    ex = q1 / np.maximum(np.linalg.norm(q1, axis=1, keepdims=True), 1e-12)
    ey = q2 - (q2 * ex).sum(1, keepdims=True) * ex
    ey /= np.maximum(np.linalg.norm(ey, axis=1, keepdims=True), 1e-12)
    A = np.stack([np.stack([(q1 * ex).sum(1), (q2 * ex).sum(1)], 1),
                  np.stack([(q1 * ey).sum(1), (q2 * ey).sum(1)], 1)], 1)  # 3D edges in the triangle plane
    U = np.stack([e1, e2], 2)  # UV edges as columns
    with np.errstate(all="ignore"):
        J = U @ np.linalg.pinv(A)
        sv = np.linalg.svd(J, compute_uv=False)
        aniso = sv[:, 0] / np.maximum(sv[:, 1], 1e-12)
    aniso = np.nan_to_num(aniso, nan=1e3, posinf=1e3)
    detail = np.minimum(np.clip(ref / np.maximum(dens, 1e-9), 0, 1) ** 1.5, np.clip(2.5 / aniso, 0, 1) ** 2)
    # smooth fields: rasterise small and upscale
    r = min(size, 1024)
    m, cov = fabric.raster_attr(tri_uv, vals, r, max_channels=(0,))
    m[..., 0][m[..., 0] == 0] = 1.0  # beyond the bleed: no occlusion
    out = [fabric.upscale(m[..., k], size) for k in range(3)]
    # the squeezed strips are thin in UV, so they need full resolution (only those triangles)
    # per-vertex (mean of its triangles) so the fade interpolates smoothly instead of in triangle blocks
    acc = np.zeros(len(me.vertices))
    cnt = np.zeros(len(me.vertices))
    np.add.at(acc, tv.reshape(nt, 3), detail[:, None])
    np.add.at(cnt, tv.reshape(nt, 3), 1)
    vdet = (acc / np.maximum(cnt, 1))[tv].reshape(nt, 3)
    sq = np.nonzero(vdet.min(1) < 0.98)[0]
    fade = np.zeros((size, size), np.float32)
    if len(sq):
        fm, _ = fabric.raster_attr(tri_uv[sq], (1 - vdet[sq])[:, :, None], size, max_channels=(0,), bleed=0)
        fade = fabric.blur(fm[..., 0], 2)
    return out[0], out[1], out[2], np.clip(1 - fade, 0, 1)
