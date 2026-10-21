"""Procedural headwear grown from the current head, like hair, so it always fits."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import garments, hair, util


def _smooth_rows(R, k, passes):
    """Smooth each row around the head (rows wrap at the back)."""
    k = np.asarray(k, float) / sum(k)
    h = len(k) // 2
    for _ in range(passes):
        Rp = np.pad(R, ((0, 0), (h, h)), mode="wrap")
        R = np.stack([np.convolve(row, k, mode="valid") for row in Rp])
    return R


def turban(res, body_obj, gid, gdef):
    """Wrapped turban (pagdi): a cloth shell around the skull that sits on the forehead and above the
    ears, swells out and up towards the crown, and carries the wraps as ridges that rise towards the
    front so the layers cross in a V over the forehead. The bottom edge is one clean ring that hugs
    the head. Rigged fully to `head`."""
    t = gdef["turban"]
    _, _, _, z_ref, z_top, yc = hair._head_frame(res, body_obj)
    bvh = garments.body_bvh(body_obj)
    c = Vector((0.0, yc, z_ref + 0.5 * (z_top - z_ref)))
    cols, rows = 72, 36
    thetas = np.linspace(-math.pi, math.pi, cols, endpoint=False)
    line_z = np.array([hair._hairline(th, z_ref, z_top, {"hairline": tuple(t["line"])}) for th in thetas])

    def direction(phi, th):
        return Vector((math.sin(phi) * math.sin(th), -math.sin(phi) * math.cos(th), math.cos(phi)))

    def head_radius(d):
        hit = bvh.ray_cast(c + d * 0.3, -d, 0.3)
        return 0.3 - hit[3] if hit[0] is not None else 0.0

    # for each column, the polar angle (from straight up) where the head surface drops to the wrap line
    phi_end = np.zeros(cols)
    for j, th in enumerate(thetas):
        for phi in np.linspace(0.05, 2.6, 200):
            d = direction(phi, th)
            if c.z + d.z * head_radius(d) < line_z[j]:
                break
        phi_end[j] = phi
    phi_end = _smooth_rows(phi_end[None], [1, 2, 3, 2, 1], 3)[0]
    f = np.linspace(0, 1, rows)  # 0 crown, 1 wrap line
    R = np.zeros((rows, cols))
    dirs = np.zeros((rows, cols, 3))
    for i, fi in enumerate(f):
        for j, th in enumerate(thetas):
            d = direction(max(fi, 0.02) * phi_end[j], th)
            dirs[i, j] = d
            R[i, j] = head_radius(d)
    # a smooth envelope of the skull: no ears or brow detail shows through the cloth
    R = np.maximum(R, _smooth_rows(R, [1, 2, 3, 4, 3, 2, 1], 4))
    R = _smooth_rows(R, [1, 2, 3, 2, 1], 2)
    # bulk: hugs the head at the hem, swells to full thickness a few centimetres up, lifts at the crown
    up = 1 - f
    swell = t["bulk"] * np.clip(up / 0.35, 0, 1) ** 0.6
    P = np.array(c)[None, None, :] + dirs * (R + gdef["offset"] + swell[:, None])[:, :, None]
    P[:, :, 2] += (t["crown"] * up ** 2)[:, None]
    # wraps: bands climbing towards the forehead; ridges fade out at the hem and on the crown
    front = (1 + np.cos(thetas)) / 2
    s = ((P[:, :, 2] - P[-1, :, 2].min()) + t["rise"] * front[None, :]) / t["band"]
    ridge = np.abs(np.sin(math.pi * s)) ** 0.4
    fade = np.clip((1 - f) / 0.1, 0, 1) * np.clip(f / 0.35, 0, 1)
    P += dirs * (t["depth"] * ridge * fade[:, None])[:, :, None]
    bm = bmesh.new()
    V = [[bm.verts.new(P[i, j]) for j in range(cols)] for i in range(1, rows)]
    pole = bm.verts.new(P[0].mean(0))
    for j in range(cols):
        bm.faces.new((pole, V[0][(j + 1) % cols], V[0][j]))
    for i in range(rows - 2):
        for j in range(cols):
            jn = (j + 1) % cols
            bm.faces.new((V[i][j], V[i][jn], V[i + 1][jn], V[i + 1][j]))
    bm.normal_update()
    me = bpy.data.meshes.new(gid)
    bm.to_mesh(me)
    bm.free()
    obj = util.link(bpy.data.objects.new(gid, me))
    sub = obj.modifiers.new("sub", "SUBSURF")
    sub.levels = 1
    garments.apply_modifier(obj, sub)
    garments.conform(obj, bvh, gdef["offset"] * 0.5)
    uvinfo = garments.flat_sketch_uv(obj)
    sol = obj.modifiers.new("thickness", "SOLIDIFY")
    sol.thickness = 0.004
    sol.offset = -1.0
    sol.use_rim = True
    sol.use_quality_normals = True
    garments.apply_modifier(obj, sol)
    for p in obj.data.polygons:
        p.use_smooth = True
    W = np.zeros((len(obj.data.vertices), len(res.bones)))
    W[:, res.bones.index("head")] = 1.0
    util.set_weight_matrix(obj, W, res.bones)
    util.add_armature_modifier(obj, res.arm)
    return obj, uvinfo
