"""Body stage: morph the MakeHuman base mesh, fit the Mesh2Motion skeleton, convert to T-pose."""
import os
from functools import lru_cache

import bpy
import numpy as np
from mathutils import kdtree

from .. import face, morph
from . import rig, util

DATA = rig.DATA


@lru_cache(maxsize=1)
def base_weight_matrix():
    """(nverts, n_deform_bones) Mesh2Motion weights for every MakeHuman base vertex."""
    names = rig.deform_bone_names()
    w = np.load(os.path.join(DATA, "m2m_weights.npz"))
    nverts = len(morph.base()["coords"])
    W = np.zeros((nverts, len(names)))
    for j, n in enumerate(names):
        if n + "|i" in w.files:
            W[w[n + "|i"], j] = w[n + "|w"]
    return W


@lru_cache(maxsize=None)
def group_verts(group):
    faces, _ = morph.faces_of_group(group)
    return np.unique(np.concatenate([np.asarray(f) for f in faces]))


def _complete_weights(W, co):
    """Vertices with no weight (some helper verts) copy the nearest body vertex."""
    s = W.sum(1)
    missing = np.nonzero(s < 0.5)[0]
    body = group_verts("body")
    if len(missing):
        kd = kdtree.KDTree(len(body))
        for i, v in enumerate(body):
            kd.insert(co[v], i)
        kd.balance()
        for m in missing:
            _, i, _ = kd.find(co[m])
            W[m] = W[body[i]]
    s = W.sum(1, keepdims=True)
    s[s == 0] = 1
    return W / s


def soften_toe_crease(W, co, pos, half=0.12):
    """Blend foot -> ball weights smoothly across the ball of the foot.

    MakeHuman hands the toes over from foot to toe bones within about 2 cm, so a 25-35 degree toe-off
    folds the skin sharply. Here the foot+ball weight of each vertex is split by a smoothstep of its
    distance ahead of the ball pivot, over `half` x (ankle to toe tip) on each side (about 2.5 cm)."""
    names = rig.deform_bone_names()
    for s in ("l", "r"):
        fi, bi = names.index(f"foot_{s}"), names.index(f"ball_{s}")
        ankle, ball = np.asarray(pos[f"foot_{s}"][0]), np.asarray(pos[f"ball_{s}"][0])
        fwd = ball - ankle
        fwd[2] = 0.0
        fwd /= np.linalg.norm(fwd)
        tot = W[:, fi] + W[:, bi]
        sel = tot > 1e-6
        d = (co[sel] - ball) @ fwd
        reach = float(d.max())                       # ball to toe tip
        w = half * (np.linalg.norm((ball - ankle)[:2]) + reach)
        x = np.clip((d + w) / (2 * w), 0.0, 1.0)
        t = x * x * (3 - 2 * x)
        W[sel, bi] = tot[sel] * t
        W[sel, fi] = tot[sel] * (1 - t)
    return W


class BodyResult:
    """Everything later stages need: the T-posed armature, T-posed coords of every base vertex, weights."""

    def __init__(self, arm, coords, W, keys=None):
        self.arm = arm
        self.coords = coords
        self.W = W
        self.bones = rig.deform_bone_names()
        self.keys = keys or {}  # facial blendshape name -> T-posed coords of every base vertex


def build(macros=None, modifiers=None, height_cm=None, face_keys=()):
    co = morph.morphed_coords(macros, modifiers)
    body = group_verts("body")
    co[:, 2] -= co[body, 2].min()
    if height_cm:
        h = co[body, 2].max()
        co *= (float(height_cm) / 100.0) / h
    pos = rig.fit_from_makehuman(co)
    W = soften_toe_crease(_complete_weights(base_weight_matrix().copy(), co), co, pos)

    # A temporary mesh with every base vertex (body + helpers) rides along the T-pose conversion
    b = morph.base()
    sizes = b["face_sizes"]
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    fv = b["face_verts"]
    faces = [fv[s:s + n] for s, n in zip(starts, sizes)]
    tmp = util.make_mesh("_full", co, faces)
    names = rig.deform_bone_names()
    util.set_weight_matrix(tmp, W, names, max_influences=None, threshold=1e-4)
    if face_keys:
        # facial blendshapes ride the T-pose conversion as shape keys (rig._posed_coords bakes them)
        tmp.shape_key_add(name="Basis")
        for name, d in face.deltas(co, list(face_keys), macros).items():
            kb = tmp.shape_key_add(name=name, from_mix=False)
            kb.value = 0.0  # bpy 5.2 starts new keys at 1.0
            kb.data.foreach_set("co", (co + d).ravel())

    arm = rig.create_armature(pos)
    util.add_armature_modifier(tmp, arm)
    rig.pose_to_tpose(arm)
    rig.apply_pose_as_rest(arm, [tmp])
    coords_t = util.get_coords(tmp)
    keys = {}
    if face_keys:
        for kb in tmp.data.shape_keys.key_blocks[1:]:
            k = np.empty(len(coords_t) * 3)
            kb.data.foreach_get("co", k)
            keys[kb.name] = k.reshape(-1, 3)
    bpy.data.objects.remove(tmp, do_unlink=True)
    return BodyResult(arm, coords_t, W, keys)


def add_face_keys(obj, keys):
    """Add shape keys {name: coords of obj's vertices}, skipping ones that don't move obj."""
    moving = {k: v for k, v in keys.items() if np.abs(v - util.get_coords(obj)).max() > 1e-5}
    if not moving:
        return
    obj.shape_key_add(name="Basis")
    for name in keys:
        kb = obj.shape_key_add(name=name, from_mix=False)
        kb.value = 0.0  # bpy 5.2 starts new keys at 1.0
        if name in moving:
            kb.data.foreach_set("co", moving[name].ravel())


def make_group_object(res, group, name, with_uv=True):
    """Create an object from one MakeHuman face group, skinned with the base weights."""
    faces, fuvs = morph.faces_of_group(group)
    verts = np.unique(np.concatenate([np.asarray(f) for f in faces]))
    remap = -np.ones(len(res.coords), dtype=np.int64)
    remap[verts] = np.arange(len(verts))
    lf = [remap[np.asarray(f)].tolist() for f in faces]
    b = morph.base()
    obj = util.make_mesh(name, res.coords[verts], lf, b["uvs"] if with_uv else None, fuvs if with_uv else None)
    util.set_weight_matrix(obj, res.W[verts], res.bones)
    util.add_armature_modifier(obj, res.arm)
    obj["mh_verts"] = verts.tolist()
    add_face_keys(obj, {k: v[verts] for k, v in res.keys.items()})
    return obj


def fit_proxy(res, mhclo_path):
    """Place a MakeHuman proxy (.mhclo) onto the T-posed body. Returns (coords, faces, uvs, face_uvs)."""
    refs, weights, offsets = [], [], []
    scales = {}
    obj_file = None
    in_verts = False
    with open(mhclo_path) as f:
        for line in f:
            p = line.split()
            if not p or p[0].startswith("#"):
                continue
            if p[0] in ("x_scale", "y_scale", "z_scale"):
                scales[p[0][0]] = (int(p[1]), int(p[2]), float(p[3]))
            elif p[0] == "obj_file":
                obj_file = p[1]
            elif p[0] == "verts":
                in_verts = True
            elif in_verts and len(p) == 9:
                refs.append([int(x) for x in p[:3]])
                weights.append([float(x) for x in p[3:6]])
                offsets.append([float(x) for x in p[6:9]])
            elif in_verts and len(p) == 1:
                refs.append([int(p[0])] * 3)
                weights.append([1.0, 0, 0])
                offsets.append([0.0, 0.0, 0.0])
            elif in_verts:
                in_verts = False
    refs, weights, offsets = np.array(refs), np.array(weights), np.array(offsets)
    # MakeHuman scale lines are measured on the MakeHuman base (decimetres, Y-up).
    co_mh = res.coords  # metres, Z-up
    def axis_scale(key, comp):
        a, bb, ref = scales[key]
        return abs(co_mh[a, comp] - co_mh[bb, comp]) / (ref * 0.1)
    sx = axis_scale("x", 0)
    sy = axis_scale("y", 2)   # MakeHuman Y (up) -> Blender Z
    sz = axis_scale("z", 1)   # MakeHuman Z (forward) -> Blender -Y
    off = np.stack([offsets[:, 0] * 0.1 * sx, -offsets[:, 2] * 0.1 * sz, offsets[:, 1] * 0.1 * sy], axis=1)
    pts = (co_mh[refs] * weights[..., None]).sum(1) + off
    # read proxy mesh topology
    vts, faces, fuvs = [], [], []
    with open(os.path.join(os.path.dirname(mhclo_path), obj_file)) as f:
        for line in f:
            if line.startswith("vt "):
                vts.append([float(x) for x in line.split()[1:3]])
            elif line.startswith("f "):
                fv, ft = [], []
                for tok in line.split()[1:]:
                    q = tok.split("/")
                    fv.append(int(q[0]) - 1)
                    ft.append(int(q[1]) - 1)
                faces.append(fv)
                fuvs.append(ft)
    return pts, faces, np.array(vts), fuvs


def make_eyes(res):
    pts, faces, uvs, fuvs = fit_proxy(res, os.path.join(DATA, "eyes", "high-poly.mhclo"))
    # Drop the cornea shell (mapped to the small bluish disc in the corner of the eye texture);
    # glTF viewers would show it as an opaque glowing layer over the iris.
    keep = [i for i, fu in enumerate(fuvs) if not all(uvs[j][0] > 0.8 and uvs[j][1] < 0.2 for j in fu)]
    faces = [faces[i] for i in keep]
    fuvs = [fuvs[i] for i in keep]
    used = sorted({v for f in faces for v in f})
    remap = {v: i for i, v in enumerate(used)}
    pts = pts[used]
    faces = [[remap[v] for v in f] for f in faces]
    obj = util.make_mesh("Eyes", pts, faces, uvs, fuvs)
    add_face_keys(obj, _eye_keys(res, pts))
    vg = obj.vertex_groups.new(name="head")
    vg.add(list(range(len(pts))), 1.0, "REPLACE")
    util.add_armature_modifier(obj, res.arm)
    return obj


def _rigid_fit(a, b):
    """Rotation R and translation t with b ~ a @ R.T + t (Kabsch)."""
    ca, cb = a.mean(0), b.mean(0)
    U, _, Vt = np.linalg.svd((a - ca).T @ (b - cb))
    D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    return R, cb - ca @ R.T


def _eye_keys(res, pts):
    """Eyeballs turn rigidly with MakeHuman's eye helper meshes (eyeLook* shapes); other shapes leave them."""
    if not res.keys:
        return {}
    sides = [(group_verts("helper-l-eye"), pts[:, 0] > 0), (group_verts("helper-r-eye"), pts[:, 0] <= 0)]
    out = {}
    for name, kco in res.keys.items():
        p = pts.copy()
        for hv, sel in sides:
            if np.abs(kco[hv] - res.coords[hv]).max() > 1e-5:
                R, t = _rigid_fit(res.coords[hv], kco[hv])
                p[sel] = pts[sel] @ R.T + t
        out[name] = p
    return out
