"""Turn a character spec into a rigged scene and export it."""
import os
import time

import bpy
import numpy as np
from mathutils import Vector, interpolate
from mathutils.bvhtree import BVHTree

from .. import catalog, morph, textures
from ..errors import CliError
from . import anim, body, garments, hair, materials, rig, util


class Built:
    def __init__(self):
        self.arm = None
        self.body = None
        self.meshes = []
        self.warnings = []
        self.timings = {}
        self.uv_info = {}


def _tick(b, key, t0):
    b.timings[key] = round(time.time() - t0, 3)
    return time.time()


def _body_tris():
    faces, _ = morph.faces_of_group("body")
    tris = []
    for f in faces:
        tris.append((f[0], f[1], f[2]))
        if len(f) == 4:
            tris.append((f[0], f[2], f[3]))
    return np.array(tris)


def conform_imported(obj, ref_coords, res, bone_filter=None, k=24):
    """Move an object authored on the reference body onto this body and skin it.

    Each vertex moves by a smooth, distance-weighted average of how the nearby body vertices moved
    (reference body -> this body), so loose shapes such as hats or capes keep their form. Weights are
    blended the same way from those body vertices."""
    from mathutils import kdtree
    body_v = body.group_verts("body")
    kd = kdtree.KDTree(len(body_v))
    for i, v in enumerate(body_v):
        kd.insert(ref_coords[v], i)
    kd.balance()
    disp = res.coords[body_v] - ref_coords[body_v]
    co = util.get_coords(obj)
    new = np.zeros_like(co)
    W = np.zeros((len(co), len(res.bones)))
    cols = [res.bones.index(b) for b in bone_filter] if bone_filter else None
    for i, p in enumerate(co):
        hits = kd.find_n(p, k)
        idx = np.array([h[1] for h in hits])
        d = np.array([h[2] for h in hits])
        sigma = max(d.min(), 0.01) * 1.5
        w = np.exp(-((d - d.min()) / sigma) ** 2)
        w /= w.sum()
        new[i] = p + (disp[idx] * w[:, None]).sum(0)
        ww = (res.W[body_v[idx]] * w[:, None]).sum(0)
        if cols is not None:
            f = np.zeros_like(ww)
            f[cols] = ww[cols]
            ww = f if f.sum() > 1e-6 else np.eye(len(ww))[cols[0]]
        W[i] = ww
    util.set_coords(obj, new)
    util.set_weight_matrix(obj, W, res.bones)


def import_mesh_file(path, name):
    """Import a .glb/.gltf/.obj/.fbx and join its meshes into one object (armatures are discarded)."""
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise CliError("bad_format", f"Unsupported mesh format '{ext}'", hint="Use .glb, .gltf, .obj or .fbx")
    new = [o for o in bpy.data.objects if o not in before]
    shapes = {pb.custom_shape for o in new if o.type == "ARMATURE" for pb in o.pose.bones if pb.custom_shape}
    meshes = [o for o in new if o.type == "MESH" and o not in shapes and o.visible_get() and not o.hide_render]
    # A rigged file may carry props/floors next to the character: keep only the skinned meshes then
    skinned = [o for o in meshes if any(m.type == "ARMATURE" for m in o.modifiers)
               or (o.parent and o.parent.type == "ARMATURE")]
    if skinned:
        meshes = skinned
    if not meshes:
        raise CliError("no_mesh", f"No mesh found in {path}")
    for m in meshes:
        mw = m.matrix_world.copy()
        m.parent = None
        m.matrix_world = mw
        m.modifiers.clear()
        m.vertex_groups.clear()
        m.data.transform(m.matrix_world)
        m.matrix_world.identity()
    for o in new:
        if o not in meshes:
            bpy.data.objects.remove(o, do_unlink=True)
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=meshes[0], selected_editable_objects=meshes, object=meshes[0]):
            bpy.ops.object.join()
    obj = meshes[0]
    obj.name = name
    return obj


_REF = {}


def reference_body():
    """The neutral reference body (T-posed). Imported assets are authored on it and standard
    garments take their cut and UV layout from it."""
    if "res" not in _REF or _REF["res"].arm.name not in bpy.data.objects:
        res = body.build({}, {}, None)
        res.arm.name = "_reference_armature"
        _REF["res"] = res
    return _REF["res"]


def reference_coords():
    return reference_body().coords


def hide_body(body_obj, covers, max_dist=0.06):
    """Delete body faces fully covered by clothing (prevents skin poking through when animated)."""
    if not covers:
        return 0
    tris, cos = [], []
    off = 0
    for o in covers:
        co = util.get_coords(o)
        o.data.calc_loop_triangles()
        for t in o.data.loop_triangles:
            tris.append([off + v for v in t.vertices])
        cos.extend(co.tolist())
        off += len(co)
    bvh = BVHTree.FromPolygons([Vector(c) for c in cos], tris)
    me = body_obj.data
    me.update()
    co = util.get_coords(body_obj)
    nrm = np.empty(len(co) * 3)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    hidden = np.zeros(len(co), dtype=bool)
    for i in range(len(co)):
        n = Vector(nrm[i])
        hit = bvh.ray_cast(Vector(co[i]) + n * 0.0005, n, max_dist)
        if hit[0] is None:
            continue
        # also require coverage sideways so seams/hems keep some skin underneath
        hidden[i] = True
    # erode: keep a ring of skin under every hem
    adj = [[] for _ in range(len(co))]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    er = hidden.copy()
    for _ in range(2):
        er = np.array([er[i] and all(er[j] for j in adj[i]) for i in range(len(co))])
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    kill = [f for f in bm.faces if all(er[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    return len(kill)


def layer_of(g):
    return g.get("layer", catalog.GARMENTS.get(g.get("type"), {}).get("layer", 1))


def build_scene(spec, project, work_dir):
    """Build everything in the current Blender scene. Returns a Built."""
    b = Built()
    t = time.time()
    util.reset_scene()
    _REF.clear()
    garments._UV_CACHE.clear()
    bd = spec["body"]
    res = body.build(bd.get("macros"), bd.get("morphs"), bd.get("height_cm"))
    b.arm = res.arm
    b.res = res
    t = _tick(b, "body", t)

    body_obj = body.make_group_object(res, "body", "Body")
    b.body = body_obj
    eyes = body.make_eyes(res)
    b.meshes += [body_obj, eyes]

    # skin
    skin = spec["skin"]
    if skin.get("texture"):
        img = os.path.join(project, skin["texture"])
    else:
        img = textures.skin_texture(skin["color"], os.path.join(work_dir, "skin.png"),
                                    lips=skin.get("lips", True), brows=skin.get("brows", True),
                                    brow_hex=skin.get("brow_color"))
    body_obj.data.materials.append(materials.make("Skin", image_path=img, roughness=skin.get("roughness", 0.55)))
    eye_img = os.path.join(rig.DATA, "eyes", "brown_eye.png")
    if spec["eyes"].get("iris_color"):
        eye_img = materials.recolor_iris(eye_img, spec["eyes"]["iris_color"], os.path.join(work_dir, "eyes.png"))
    eyes.data.materials.append(materials.make("Eyes", image_path=eye_img, roughness=0.15))
    t = _tick(b, "body_meshes", t)

    # hair
    h = spec.get("hair")
    if h:
        if h.get("source"):
            hobj = import_mesh_file(os.path.join(project, h["source"]), "Hair")
            conform_imported(hobj, reference_coords(), res, bone_filter=hair.HEAD_BONES)
            util.add_armature_modifier(hobj, res.arm)
        else:
            hobj = hair.make(res, body_obj, h["style"])
        color = h.get("color") or "#3b2a1e"
        if h.get("texture"):
            himg = materials.tinted_image(os.path.join(project, h["texture"]), h.get("tint"),
                                          os.path.join(work_dir, "hair.png"))
        elif h.get("source") and hobj.data.materials and hobj.data.materials[0]:
            himg = None
        else:
            himg = materials.hair_texture(color, os.path.join(work_dir, "hair.png"))
        if himg or not hobj.data.materials:
            hobj.data.materials.clear()
            hobj.data.materials.append(materials.make("Hair", image_path=himg, color=color, roughness=0.65,
                                                      double_sided=True))
        b.meshes.append(hobj)
        t = _tick(b, "hair", t)

    # garments, inner layers first
    covers = []
    order = sorted(spec["garments"], key=lambda g: (g.get("layer", catalog.GARMENTS.get(g.get("type"), {}).get("layer", 1))))
    for rank, g in enumerate(order):
        if g.get("source"):
            gobj = import_mesh_file(os.path.join(project, g["source"]), g["id"])
            conform_imported(gobj, reference_coords(), res)
            # keep it outside the skin and anything already worn
            garments.conform(gobj, garments.body_bvh(body_obj), 0.003 + 0.003 * rank)
            util.add_armature_modifier(gobj, res.arm)
            keep_mats = not g.get("texture") and not g.get("color") and len(gobj.data.materials) > 0
        else:
            gobj, info = garments.make(res, reference_body(), body_obj, g["id"], g["type"], layer_of(g))
            b.uv_info[g["id"]] = info
            keep_mats = False
        if not keep_mats:
            gobj.data.materials.clear()
            img = None
            if g.get("texture"):
                img = materials.tinted_image(os.path.join(project, g["texture"]), g.get("tint"),
                                             os.path.join(work_dir, f"garment_{g['id']}.png"))
            gobj.data.materials.append(materials.make(f"Garment_{g['id']}", color=g.get("color") or "#8a8f99",
                                                      image_path=img, roughness=g.get("roughness", 0.8),
                                                      double_sided=True))
        gobj["garment_id"] = g["id"]
        if g.get("hide_body", True):
            covers.append(gobj)
        b.meshes.append(gobj)
    if spec["garments"]:
        t = _tick(b, "garments", t)
    if "res" in _REF:
        bpy.data.objects.remove(_REF.pop("res").arm, do_unlink=True)
    if spec["export"].get("hide_body_under_clothes", True) and covers:
        n = hide_body(body_obj, covers)
        b.hidden_faces = n
        t = _tick(b, "hide_body", t)
    return b


def export_glb(b, out_path, animations=()):
    t = time.time()
    clips = []
    if animations:
        clips = anim.attach(b.arm, list(animations))
    bpy.context.view_layer.update()
    for o in bpy.data.objects:
        if o.name in bpy.context.view_layer.objects:
            o.select_set(False)
    b.arm.select_set(True)
    for m in b.meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = b.arm
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    kwargs = dict(filepath=out_path, export_format="GLB", use_selection=True, export_skins=True,
                  export_animations=bool(clips), export_yup=True, export_apply=False)
    if clips:
        kwargs["export_animation_mode"] = "NLA_TRACKS"
    bpy.ops.export_scene.gltf(**kwargs)
    b.timings["export"] = round(time.time() - t, 3)
    return clips


def summary(b):
    out = {"meshes": []}
    for m in b.meshes:
        m.data.calc_loop_triangles()
        out["meshes"].append({
            "name": m.name, "vertices": len(m.data.vertices), "triangles": len(m.data.loop_triangles),
            "materials": [x.name for x in m.data.materials if x],
        })
    co = util.get_coords(b.body)
    out["height_m"] = round(float(co[:, 2].max() - co[:, 2].min()), 3)
    out["skeleton"] = {"standard": "mesh2motion-human", "bones": len(b.arm.data.bones), "pose": "T"}
    return out
