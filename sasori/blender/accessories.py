"""Rigid accessories (crowns, earrings, necklaces, armlets, bangles) attached to one bone.

An accessory is modelled on the reference body (or is a built-in made there). It is carried onto the
current body by the similarity transform (rotation, translation, uniform scale) that best maps the
reference body's surface around its bone onto this body's, so it lands in the same place on any body
shape and keeps its own shape. Fits then settle it against the body:
  none   rigid; if it would cut into the body (or the clothes under it) it slides along the bone until
         it is clear: a crown rides up a bigger head instead of sinking into it
  wrap   a uniform radial scale about the bone so a bangle or armlet hugs a thicker or thinner limb
  chest  / neck: the lower part settles onto the chest (or the clothes) at a small gap, like a necklace
  pierce rigid and left where it is, through the body (earrings, a nose ring)
It is weighted 100% to its bone, or to a short hanging chain of extra bones (`hang`)."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from .. import catalog, morph
from ..errors import CliError
from . import extras, garments, rig, util

GAP = 0.002
HANG_SPRING = {"stiffness": 0.6, "damping": 0.35, "gravity": 1.0}

BUILTINS = catalog.ACCESSORIES
FITS = catalog.ACCESSORY_FITS


# ---------------------------------------------------------------- built-in meshes (reference body)

def _torus(R, r, center, normal, seg=64, rseg=12, squash=1.0):
    """Torus points/faces around `normal` through `center` (squash < 1 flattens the tube along normal)."""
    n = Vector(normal).normalized()
    a = n.orthogonal().normalized()
    bvec = n.cross(a)
    verts, faces = [], []
    for i in range(seg):
        t = 2 * math.pi * i / seg
        d = a * math.cos(t) + bvec * math.sin(t)
        for j in range(rseg):
            s = 2 * math.pi * j / rseg
            p = Vector(center) + d * (R + r * math.cos(s)) + n * (r * squash * math.sin(s))
            verts.append(p)
    for i in range(seg):
        for j in range(rseg):
            i2, j2 = (i + 1) % seg, (j + 1) % rseg
            faces.append([i * rseg + j, i2 * rseg + j, i2 * rseg + j2, i * rseg + j2])
    return np.array(verts), faces


def _mesh(name, verts, faces):
    obj = util.make_mesh(name, verts, faces)
    for p in obj.data.polygons:
        p.use_smooth = True
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def _lobe(ref, side):
    t = morph.targets()
    idx = t[f"ears/{side}-ear-lobe-incr|i"]
    d = np.linalg.norm(t[f"ears/{side}-ear-lobe-incr|d"], axis=1)
    top = idx[np.argsort(-d)[:6]]
    return ref.coords[top].mean(0)


def _body_coords(ref):
    from . import body
    return ref.coords[body.group_verts("body")]


def make_builtin(name, ref):
    """Build a built-in accessory on the reference body `ref` (body.BodyResult)."""
    arm = ref.arm
    co = _body_coords(ref)
    if name == "circlet":
        head = arm.data.bones["head"]
        top = co[:, 2].max()
        zc = top - 0.075
        ring = co[np.abs(co[:, 2] - zc) < 0.006]
        c = ring[:, :2].mean(0)
        ang = np.arctan2(ring[:, 1] - c[1], ring[:, 0] - c[0])
        rad = np.hypot(ring[:, 0] - c[0], ring[:, 1] - c[1])
        bins = 72
        rmax = np.zeros(bins)
        for k, a in zip(((ang + math.pi) / (2 * math.pi) * bins).astype(int) % bins, rad):
            rmax[k] = max(rmax[k], a)
        for k in range(bins):  # fill empty bins
            if rmax[k] == 0:
                rmax[k] = max(rmax[(k - 1) % bins], rmax[(k + 1) % bins])
        f = np.fft.rfft(rmax)
        f[6:] = 0  # a smooth band, not every bump of the scalp
        rmax = np.fft.irfft(f, bins) + 0.004
        h, th = 0.014, 0.0025
        verts, faces = [], []
        for k in range(bins):
            a = -math.pi + 2 * math.pi * (k + 0.5) / bins
            d = np.array([math.cos(a), math.sin(a), 0])
            base = np.array([c[0], c[1], zc]) + rmax[k] * d
            # a slight dip at the front (characters face -Y): the band sits lower on the forehead
            dip = 0.008 * max(0.0, -math.sin(a)) ** 4
            for dz, dr in ((-h / 2, 0), (h / 2, 0), (h / 2, th), (-h / 2, th)):
                verts.append(base + np.array([0, 0, dz - dip]) + dr * d)
        for k in range(bins):
            k2 = (k + 1) % bins
            for j in range(4):
                j2 = (j + 1) % 4
                faces.append([k * 4 + j, k * 4 + j2, k2 * 4 + j2, k2 * 4 + j])
        # front ornament: a small diamond plate standing on the band
        a = -math.pi / 2
        d = np.array([math.cos(a), math.sin(a), 0])
        k = int((a + math.pi) / (2 * math.pi) * bins) % bins
        fc = np.array([c[0], c[1], zc - 0.008]) + (rmax[k] + th) * d
        o = len(verts)
        for p in ((0, 0, 0.026), (0.011, 0, 0.012), (0, 0, -0.002), (-0.011, 0, 0.012)):
            verts.append(fc + np.array(p) + d * 0.0015)
        for p in ((0, 0, 0.026), (0.011, 0, 0.012), (0, 0, -0.002), (-0.011, 0, 0.012)):
            verts.append(fc + np.array(p) - d * 0.0005)
        faces += [[o, o + 1, o + 2, o + 3], [o + 7, o + 6, o + 5, o + 4]]
        faces += [[o + j, o + 4 + j, o + 4 + (j + 1) % 4, o + (j + 1) % 4] for j in range(4)]
        return _mesh(name, np.array(verts), faces)
    if name.startswith("ring_earring_"):
        side = name[-1]
        p = _lobe(ref, side)
        sx = 1 if side == "l" else -1
        R = 0.011
        v, f = _torus(R, 0.0013, p + np.array([0.002 * sx, 0, -R + 0.004]), (1, 0, 0), seg=48, rseg=8)
        return _mesh(name, v, f)
    if name.startswith("bangle_"):
        side = name[-1]
        bone = arm.data.bones[f"lowerarm_{side}"]
        h, t = np.array(bone.head_local), np.array(bone.tail_local)
        c = h + 0.88 * (t - h)
        ax = (t - h) / np.linalg.norm(t - h)
        near = co[np.abs((co - c) @ ax) < 0.008]
        rad = np.linalg.norm((near - c) - np.outer((near - c) @ ax, ax), axis=1)
        R = float(np.percentile(rad, 95)) + 0.006 if len(rad) else 0.035
        v, f = _torus(R, 0.0035, c, ax, seg=64, rseg=12, squash=1.6)
        return _mesh(name, v, f)
    raise CliError("unknown_accessory", f"Unknown built-in accessory '{name}'", hint="Valid: " + ", ".join(BUILTINS))


# ---------------------------------------------------------------- reference -> current body

def _umeyama(src, dst):
    """Similarity transform (s, R, t) minimising |s R src + t - dst|."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.eye(3)
    if np.linalg.det(U @ Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / ((a * a).sum() / len(src)))
    return s, R, md - s * R @ ms


def region_transform(bone, ref, res):
    """Similarity transform from the reference body to this body around `bone` (fitted to the body
    vertices that bone moves; parents are tried for bones that move none, like leaf bones)."""
    names = res.bones
    rig_parent = {b["name"]: b["parent"] for b in rig.m2m_rig()}
    b = bone
    while b is not None:
        if b in names:
            sel = np.nonzero(res.W[:, names.index(b)] > 0.5)[0]
            if len(sel) >= 30:
                return _umeyama(ref.coords[sel], res.coords[sel])
        b = rig_parent.get(b)
    h0 = np.array(ref.arm.data.bones[bone].head_local)
    h1 = np.array(res.arm.data.bones[bone].head_local)
    return 1.0, np.eye(3), h1 - h0


def _euler(deg):
    from mathutils import Euler
    return np.array(Euler([math.radians(x) for x in deg], "XYZ").to_matrix())


def _surfaces(b, layer):
    """BVH of the body and of the garments under this accessory's layer."""
    from . import build
    under = [m for m in b.meshes if m.get("garment_id") and build.layer_of(_garment(b, m)) < layer]
    return garments.mesh_bvh([b.body] + under)


def _garment(b, m):
    for g in b.spec.get("garments", []):
        if g["id"] == m.get("garment_id"):
            return g
    return {}


def _min_clearance(co, bvh):
    """Signed distance of each point to the surface (negative = inside)."""
    out = np.empty(len(co))
    for i, p in enumerate(co):
        loc, nrm, _, dist = bvh.find_nearest(Vector(p))
        out[i] = (Vector(p) - loc).dot(nrm) if loc is not None else 1.0
    return out


def _fit_none(co, bvh, axis, gap):
    """Slide along the bone (either way, up to 6 cm) to the nearest position clear of the surface."""
    if _min_clearance(co, bvh).min() >= gap * 0.5:
        return co
    for step in np.arange(0.002, 0.061, 0.002):
        for sgn in (1, -1):
            c2 = co + sgn * step * axis
            if _min_clearance(c2, bvh).min() >= gap * 0.5:
                return c2
    return co


def _fit_wrap(co, bvh, head, axis, gap):
    """Uniform radial scale about the bone axis: as small as it can be without cutting in."""
    rel = co - head
    along = rel @ axis
    radial = rel - np.outer(along, axis)
    r = np.linalg.norm(radial, axis=1)
    need = []
    for i in range(0, len(co), max(1, len(co) // 400)):
        if r[i] < 1e-4:
            continue
        d = radial[i] / r[i]
        start = head + along[i] * axis
        hit = bvh.ray_cast(Vector(start + d * 0.25), Vector(-d), 0.25)
        if hit[0] is not None:
            R = float(np.linalg.norm(np.array(hit[0]) - start))
            need.append((R + gap) / r[i])
    if not need:
        return co
    s = max(need)
    return head + np.outer(along, axis) + radial * s


def _fit_chest(co, bvh, gap, me):
    """Settle the lower part onto the surface at `gap` (pushed out where it cuts in, pulled down where it
    floats), fading to rigid at the top; the displacement is smoothed over the mesh."""
    z = co[:, 2]
    w = np.clip((z.max() - z) / max(np.ptp(z), 1e-6) * 1.5, 0, 1)
    disp = np.zeros_like(co)
    for i, p in enumerate(co):
        loc, nrm, _, dist = bvh.find_nearest(Vector(p))
        if loc is None:
            continue
        d = (Vector(p) - loc).dot(nrm)
        if d < gap or (d < 0.05 and w[i] > 0):
            k = 1.0 if d < gap else w[i]
            disp[i] = np.array(nrm) * (gap - d) * k
    e = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", e)
    e = e.reshape(-1, 2)
    deg = np.maximum(np.bincount(e.ravel(), minlength=len(co)), 1)
    for _ in range(6):
        acc = np.zeros_like(disp)
        np.add.at(acc, e[:, 0], disp[e[:, 1]])
        np.add.at(acc, e[:, 1], disp[e[:, 0]])
        disp = 0.5 * disp + 0.5 * acc / deg[:, None]
    co = co + disp
    # smoothing can leave a little back inside: final push-out
    for i, p in enumerate(co):
        loc, nrm, _, _ = bvh.find_nearest(Vector(p))
        if loc is not None and (Vector(p) - loc).dot(nrm) < gap:
            co[i] = np.array(loc + nrm * gap)
    return co


def squeeze_hair(hair_obj, co, head, axis, body_bvh=None, gap=0.003, fade=0.03):
    """Press hair under a band that goes round the head (a crown, circlet or headband): hair that would
    stand outside the band's inner surface is pulled in under it, fading out above and below.
    Returns the number of hair vertices moved (0 if the accessory doesn't go round the head)."""
    rel = co - head
    h = rel @ axis
    ref = np.array([1.0, 0, 0]) - axis * axis[0]
    ref /= np.linalg.norm(ref)
    ref2 = np.cross(axis, ref)
    rad = rel - np.outer(h, axis)
    ang = np.arctan2(rad @ ref2, rad @ ref)
    r = np.linalg.norm(rad, axis=1)
    bins = 48
    k = ((ang + math.pi) / (2 * math.pi) * bins).astype(int) % bins
    rin = np.full(bins, np.inf)
    np.minimum.at(rin, k, r)
    if np.isfinite(rin).mean() < 0.75:
        return 0
    for _ in range(2):  # fill gaps from the neighbours
        bad = ~np.isfinite(rin)
        rin[bad] = np.minimum(np.roll(rin, 1), np.roll(rin, -1))[bad]
    hmin, hmax = h.min(), h.max()
    hc = util.get_coords(hair_obj)
    hrel = hc - head
    hh = hrel @ axis
    hrad = hrel - np.outer(hh, axis)
    hr = np.linalg.norm(hrad, axis=1)
    hang = np.arctan2(hrad @ ref2, hrad @ ref)
    hk = ((hang + math.pi) / (2 * math.pi) * bins).astype(int) % bins
    w = np.clip(1 - np.maximum(hmin - hh, hh - hmax) / fade, 0, 1)
    limit = np.where(np.isfinite(rin[hk]), rin[hk] - gap, np.inf)
    excess = np.maximum(hr - limit, 0) * w
    m = excess > 0
    if body_bvh is not None:  # never into the scalp
        for i in np.nonzero(m)[0]:
            d = hrad[i] / hr[i]
            start = head + hh[i] * axis
            hit = body_bvh.ray_cast(Vector(start + d * 0.3), Vector(-d), 0.3)
            if hit[0] is not None:
                rs = float(np.linalg.norm(np.array(hit[0]) - start)) + 0.0015
                excess[i] = min(excess[i], max(hr[i] - rs, 0))
        m = excess > 0
    hc[m] -= hrad[m] / hr[m, None] * excess[m, None]
    util.set_coords(hair_obj, hc)
    return int(m.sum())


def build_all(b, spec, project):
    """Place every spec["accessories"] item on the built character."""
    import os

    from . import build, materials
    from .. import matlib
    items = spec.get("accessories") or []
    if not items:
        return
    ref = build.reference_body()
    arm = b.arm
    new_bones, hangs = [], []
    for a in items:
        if a.get("file"):
            obj = build.import_mesh_file(os.path.join(project, a["file"]), a["id"])
            keep = len(obj.data.materials) > 0
        else:
            obj = make_builtin(a["builtin"], ref)
            keep = False
        obj.name = a["id"]
        bone = a["bone"]
        s, R, t = region_transform(bone, ref, b.res)
        co = util.get_coords(obj)
        # the user's adjustments, about the accessory's centre on the reference body
        cen = co.mean(0)
        co = (co - cen) * float(a.get("scale", 1.0)) @ _euler(a.get("rotate", (0, 0, 0))).T + cen
        co = s * co @ R.T + t + np.array(a.get("offset", (0, 0, 0)), float)
        bb = arm.data.bones[bone]
        head = np.array(bb.head_local)
        axis = np.array(bb.tail_local - bb.head_local)
        axis /= np.linalg.norm(axis) + 1e-12
        fit = a.get("fit", "none")
        bvh = _surfaces(b, int(a.get("layer", 10)))
        if fit == "wrap":
            co = _fit_wrap(co, bvh, head, axis, a.get("gap", GAP))
        elif fit in ("chest", "neck"):
            co = _fit_chest(co, bvh, a.get("gap", GAP), obj.data)
        elif fit == "none":
            co = _fit_none(co, bvh, axis, a.get("gap", GAP))
        util.set_coords(obj, co)
        if a.get("hide_hair", bone == "head") and getattr(b, "hair", None) is not None:
            squeeze_hair(b.hair, co, head, axis, garments.body_bvh(b.body))
        # weights: the bone, or a hanging chain from the top of the accessory straight down
        n = int(a.get("hang", 0))
        if n > 0:
            top, bot = co[:, 2].max(), co[:, 2].min()
            x0 = co[co[:, 2] > top - 0.15 * (top - bot)].mean(0)
            pts = np.array([[x0[0], x0[1], top - (top - bot) * k / n] for k in range(n + 1)])
            names = extras.chain_names(a["id"], n)
            new_bones += extras.chain_bones(a["id"], bone, pts)
            hangs.append((obj, pts, names, a))
        else:
            util.set_weight_matrix(obj, np.ones((len(co), 1)), [bone])
        if a.get("material") or a.get("color") or not keep:
            obj.data.materials.clear()
            mat = a.get("material")
            if mat:
                kw = materials.preset_kwargs(matlib.resolve(mat, a.get("color"), a.get("roughness")))
            else:
                kw = dict(color=a.get("color") or "#c9a14a", roughness=a.get("roughness", 0.4))
            obj.data.materials.append(materials.make(f"Accessory_{a['id']}", **kw))
        util.add_armature_modifier(obj, arm)
        obj["accessory_id"] = a["id"]
        b.meshes.append(obj)
    extras.add_bones(arm, new_bones)
    for obj, pts, names, a in hangs:
        W, _ = extras._segment_weights(util.get_coords(obj), pts, names)
        util.set_weight_matrix(obj, W, names)
        b.chains.append({"id": a["id"], "bones": names, "parent": a["bone"], "radius": 0.005,
                         "spring": {**HANG_SPRING, **(a.get("secondary_motion") or {})}, "enabled": True})
