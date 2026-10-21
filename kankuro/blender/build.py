"""Turn a character spec into a rigged scene and export it."""
import os
import time

import bpy
import numpy as np
from mathutils import Vector, interpolate
from mathutils.bvhtree import BVHTree

from .. import catalog, face, hairtex, morph, textures
from .. import spec as specmod
from ..errors import CliError
from . import accessories, anim, body, extras, garments, hair, hair_cards, materials, motion, rig, util


class Built:
    def __init__(self):
        self.arm = None
        self.body = None
        self.meshes = []
        self.warnings = []
        self.timings = {}
        self.uv_info = {}
        self.spec = {}
        self.hair = None
        self.chains = []  # extra bone chains with secondary motion (motion.py)
        self.grips = []  # held props: finger poses, two-hand IK (motion.py)
        self.capsules = {}


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


def import_mesh_file(path, name, any_pose=False, keep_parts=False):
    """Import a .glb/.gltf/.obj/.fbx and join its meshes into one object (armatures are discarded).

    Skinned meshes keep their bind (rest) shape. With any_pose, a rest shape that is visibly broken
    (lying down, or parts scattered because the file only assembles them through the skin) is
    replaced by the pose the file shows. With keep_parts, each vertex records the mesh object it came
    from (int attribute "part", names in obj["parts"]) and its vertex groups (obj["groups"]: name ->
    vertex indices), so a part can be picked out later (autorig --extra-chain)."""
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
    if any_pose and any(o.type == "ARMATURE" for o in new):
        _bake_shown_pose(new, meshes)
    parts, gnames = [], set()
    for k, m in enumerate(meshes):
        if keep_parts:
            parts.append(m.name)
            m.data.attributes.new("part", "INT", "POINT").data.foreach_set("value", [k] * len(m.data.vertices))
            for vg in m.vertex_groups:
                flag = [any(g.group == vg.index and g.weight > 0.5 for g in v.groups) for v in m.data.vertices]
                if any(flag):
                    m.data.attributes.new("g:" + vg.name, "BOOLEAN", "POINT").data.foreach_set("value", flag)
                    gnames.add(vg.name)
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
    if keep_parts:
        obj["parts"] = parts
        groups = {}
        for gn in gnames:
            at = obj.data.attributes.get("g:" + gn)
            if at is None:
                continue
            flag = np.zeros(len(obj.data.vertices), bool)
            at.data.foreach_get("value", flag)
            groups[gn] = np.nonzero(flag)[0].tolist()
            obj.data.attributes.remove(at)
        obj["groups"] = groups
    return obj


def _surface_samples(ms, n=40000):
    """World-space points spread over the evaluated surfaces of ms."""
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for m in ms:
        ev = m.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) @ np.array(m.matrix_world)[:3, :3].T + np.array(m.matrix_world)[:3, 3]
        tri = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        ev.to_mesh_clear()
        if len(tri):
            pts.append((co, tri.reshape(-1, 3)))
    co = np.concatenate([c for c, _ in pts])
    off = np.cumsum([0] + [len(c) for c, _ in pts[:-1]])
    tri = np.concatenate([t + o for (_, t), o in zip(pts, off)])
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    rng = np.random.default_rng(0)
    idx = rng.choice(len(tri), size=n, p=area / area.sum())
    r1, r2 = np.sqrt(rng.random(n)), rng.random(n)
    return a[idx] * (1 - r1)[:, None] + b[idx] * (r1 * (1 - r2))[:, None] + c[idx] * (r1 * r2)[:, None]


def _parts(pts, cells=40):
    """Surface shares of the 26-connected blobs of a coarse voxel grid, biggest first (a body in one
    piece is one blob; parts that only the skin brings together fall apart into several)."""
    lo = pts.min(0)
    size = (pts.max(0) - lo).max() / cells
    vox = np.floor((pts - lo) / size).astype(int)
    keys, counts = np.unique(vox, axis=0, return_counts=True)
    index = {tuple(k): i for i, k in enumerate(keys)}
    seen = np.zeros(len(keys), bool)
    blobs = []
    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)]
    for s in range(len(keys)):
        if seen[s]:
            continue
        seen[s] = True
        stack, total = [s], 0
        while stack:
            i = stack.pop()
            total += counts[i]
            x, y, z = keys[i]
            for dx, dy, dz in offsets:
                j = index.get((x + dx, y + dy, z + dz))
                if j is not None and not seen[j]:
                    seen[j] = True
                    stack.append(j)
        blobs.append(total / len(pts))
    return sorted(blobs, reverse=True)


def _looks_standing(ms):
    pts = _surface_samples(ms)
    ext = pts.max(0) - pts.min(0)
    return ext[2] > 0.4 * max(ext[0], ext[1]) and ext[2] > ext[1] and sum(b > 0.02 for b in _parts(pts)) == 1


def _bake_shown_pose(new, meshes):
    arms = [o for o in new if o.type == "ARMATURE"]

    for a in arms:
        a.data.pose_position = "REST"
    bpy.context.view_layer.update()
    if _looks_standing(meshes):
        return
    for a in arms:
        a.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    if not _looks_standing(meshes):
        for a in arms:
            a.data.pose_position = "REST"
        return
    for m in meshes:
        if any(md.type == "ARMATURE" and md.object for md in m.modifiers):
            rig.bake_evaluated(m)


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


def _covered(body_obj, covers, max_dist):
    """Body vertices that have clothing within max_dist along their normal."""
    co = util.get_coords(body_obj)
    hidden = np.zeros(len(co), dtype=bool)
    if not covers:
        return hidden
    tris, cos = [], []
    off = 0
    for o in covers:
        gco = util.get_coords(o)
        o.data.calc_loop_triangles()
        for t in o.data.loop_triangles:
            tris.append([off + v for v in t.vertices])
        cos.extend(gco.tolist())
        off += len(gco)
    bvh = BVHTree.FromPolygons([Vector(c) for c in cos], tris)
    me = body_obj.data
    me.update()
    nrm = np.empty(len(co) * 3)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    for i in range(len(co)):
        n = Vector(nrm[i])
        hidden[i] = bvh.ray_cast(Vector(co[i]) + n * 0.0005, n, max_dist)[0] is not None
    return hidden


def _leg_verts(body_obj, res):
    """Body vertices on the legs below the hip joints."""
    W = util.weight_matrix(body_obj, res.bones)
    legs = [res.bones.index(b) for side in "lr" for b in garments.LEG_CHAINS[side] if b in res.bones]
    z = util.get_coords(body_obj)[:, 2]
    return (W[:, legs].sum(1) > 0.5) & (z < res.arm.data.bones["thigh_l"].head_local.z)


def hide_body(body_obj, covers, max_dist=0.06, hanging=(), legs=None):
    """Delete body faces fully covered by clothing (prevents skin poking through when animated).
    `hanging` garments (skirts, saree, a tunic's skirt) swing away from the legs on a stride, so
    they never hide the leg vertices (`legs` mask): only fitted garments do."""
    if not covers:
        return 0
    me = body_obj.data
    co = util.get_coords(body_obj)
    hidden = _covered(body_obj, covers, max_dist)
    if hanging and legs is not None:
        fitted = _covered(body_obj, [o for o in covers if o not in hanging], max_dist)
        hidden = np.where(legs, fitted, hidden)
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


def region_mask(gobj, name, size, uv_per_m, width, project=None, mask_path=None):
    """0..1 mask (size x size) of a material region on a garment's UV template: a user PNG (white =
    in the region), or a band `width` metres wide (measured on the cloth) along its open edges
    ("border") or lowest hems ("hem")."""
    from PIL import Image

    from .. import fabric
    if mask_path:
        im = Image.open(os.path.join(project, mask_path) if project else mask_path).convert("L")
        return np.asarray(im.resize((size, size), Image.BILINEAR)).astype(np.float32) / 255
    d = garments.edge_distance(gobj, name, cap=2 * width, uv_scale=uv_per_m)
    me = gobj.data
    me.calc_loop_triangles()
    n = gobj.get("shell_faces", len(me.polygons))
    tris = [t for t in me.loop_triangles if t.polygon_index < n]
    uv = me.uv_layers["UVMap"].data
    tri_uv = np.array([[uv[li].uv for li in t.loops] for t in tris])
    tri_d = np.array([[d[v] for v in t.vertices] for t in tris])[..., None]
    dm, cov = fabric.raster_attr(tri_uv, tri_d, size, bleed=4)
    # distance is interpolated per texel, so the band's inner edge is a clean line, slightly softened
    soft = 0.0015
    return np.clip((width - dm[..., 0]) / soft * 0.5 + 0.5, 0, 1) * fabric.blur(cov.astype(np.float32), 1, 1)


def _regions(g, gobj, size, uv_per_m, project):
    """[(mask, resolved preset)] for a garment's material_regions."""
    from .. import matlib
    out = []
    width0 = catalog.GARMENTS.get(g.get("type"), {}).get("border", 0.025)
    for name, ref in (g.get("material_regions") or {}).items():
        ref = matlib.normalize(ref)
        m = region_mask(gobj, name, size, uv_per_m, ref.get("width", width0), project, ref.get("mask"))
        out.append((m, matlib.resolve(ref)))
    return out


def _garment_materials(items, project, work_dir, spec, b):
    """Bake albedo + normal maps for garments (fabric preset, stitching, creases, AO, optional user maps)
    and assign their materials.

    Runs once every garment exists, so occlusion from outer layers, hair and the body is included.
    The Blender-side sampling runs first; the numpy texture bakes then run in parallel threads."""
    from concurrent.futures import ThreadPoolExecutor

    from .. import fabric, matlib
    from . import clothshade
    size = int(spec["export"].get("texture_size", 2048))
    jobs = []
    for g, gobj in items:
        gdef = catalog.GARMENTS.get(g.get("type"), {})
        fab = g.get("fabric", gdef.get("fabric", "cotton"))
        color = g.get("color") or "#8a8f99"
        tex = os.path.join(project, g["texture"]) if g.get("texture") else None
        finish = matlib.resolve(g["material"], g.get("color"), g.get("roughness")) if g.get("material") else None
        gobj.data.materials.clear()
        if not gobj.data.uv_layers or (fab == "none" and not g.get("normal") and not g.get("height")
                                       and not g.get("material_regions")):
            kw = materials.preset_kwargs(finish) if finish else dict(color=color, roughness=g.get("roughness", 0.8))
            gobj.data.materials.append(materials.make(f"Garment_{g['id']}", image_path=tex, double_sided=True, **kw))
            continue
        mask, uv_per_m, seams = None, 0.45, None
        if g["id"] in b.uv_info:
            mask = fabric.mask_from_polys(garments.uv_polygons(gobj), size)
            uv_per_m = b.uv_info[g["id"]]["scale_px_per_m"]
            seams = garments.seam_segments(gobj)
        hangs = gdef.get("source_group") == "helper-skirt" or any(k in gdef for k in ("drape", "loose", "flare"))
        ao, chain_s, crease_w, detail = clothshade.bake_maps(gobj, b.arm, b.body, b.meshes, b.res.bones, size,
                                                             leg_creases=not hangs)
        kw = dict(mask=mask, color=color, albedo_path=tex, fabric=fab,
                  height_path=os.path.join(project, g["height"]) if g.get("height") else None,
                  normal_path=os.path.join(project, g["normal"]) if g.get("normal") else None,
                  strength=float(g.get("normal_strength", 1.0)), ao=ao, chain_s=chain_s, crease_w=crease_w,
                  detail=detail, seams=seams, placket_spec=(b.uv_info.get(g["id"]) or {}).get("placket"),
                  finish=finish, roughness=g.get("roughness"),
                  regions=_regions(g, gobj, size, uv_per_m, project) if gobj.data.uv_layers else ())
        jobs.append((g, gobj, os.path.join(work_dir, f"garment_{g['id']}"), uv_per_m, kw))
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(jobs)))) as ex:
        results = list(ex.map(lambda j: fabric.bake(j[2], size, j[3], **j[4]), jobs))
    for (g, gobj, *_, kw), (albedo, normal, m) in zip(jobs, results):
        extra = materials.preset_kwargs(kw["finish"]) if kw["finish"] else {}
        extra.pop("color", None)
        extra.setdefault("specular", m["specular"])
        extra.update(roughness=m["roughness"], metallic=m["metallic"])
        gobj.data.materials.append(materials.make(
            f"Garment_{g['id']}", image_path=albedo, double_sided=True, normal_path=normal,
            roughness_path=m["mr"], metallic_path=m["mr"], sheen=m["sheen"],
            sheen_roughness=m["sheen_roughness"], sheen_tint=m["sheen_tint"], **extra))


def layer_of(g):
    return g.get("layer", catalog.GARMENTS.get(g.get("type"), {}).get("layer", 1))


def _skin_ao(res, body_obj, eyes):
    """Per base-vertex ambient occlusion of the skin (eye sockets, nostrils, lips, ears, folds)."""
    from . import clothshade
    ao = clothshade.vertex_ao(body_obj, clothshade.scene_bvh([body_obj, eyes]), np.random.default_rng(11))
    full = np.ones(len(res.coords))
    full[np.asarray(body_obj["mh_verts"])] = ao
    return full


def _brow_shape(skin):
    """Brow band shape shared by the brow hairs and the shadow painted under them."""
    return {"thickness": skin.get("brow_thickness") or 1.0, "arch": skin.get("brow_arch") or 0.0,
            "length": skin.get("brow_length") or 1.0}


def build_scene(spec, project, work_dir):
    """Build everything in the current Blender scene. Returns a Built."""
    b = Built()
    b.spec = spec
    t = time.time()
    util.reset_scene()
    _REF.clear()
    garments._UV_CACHE.clear()
    bd = spec["body"]
    blendshapes = face.SETS[spec.get("face", {}).get("blendshapes", "arkit52")]
    res = body.build(bd.get("macros"), specmod.effective_morphs(spec), bd.get("height_cm"), face_keys=blendshapes)
    b.arm = res.arm
    b.res = res
    t = _tick(b, "body", t)

    body_obj = body.make_group_object(res, "body", "Body")
    b.body = body_obj
    eyes = body.make_eyes(res)
    b.meshes += [body_obj, eyes]
    if blendshapes:
        # an open mouth needs something inside it
        teeth_mat = materials.make("Teeth", color="#e9e2d2", roughness=0.35)
        for group, name in (("helper-upper-teeth", "UpperTeeth"), ("helper-lower-teeth", "LowerTeeth"),
                            ("helper-tongue", "Tongue")):
            o = body.make_group_object(res, group, name, with_uv=False)
            o.data.materials.append(teeth_mat if "Teeth" in name else
                                    materials.make("Tongue", color="#a8545a", roughness=0.45, subsurface=0.2))
            b.meshes.append(o)

    t = _tick(b, "body_meshes", t)

    # hair
    h = spec.get("hair")
    hobj = None
    if h:
        color = h.get("color") or "#3b2a1e"
        if h.get("source"):
            hobj = import_mesh_file(os.path.join(project, h["source"]), "Hair")
            conform_imported(hobj, reference_coords(), res, bone_filter=hair.HEAD_BONES)
            util.add_armature_modifier(hobj, res.arm)
            if h.get("texture"):
                himg = materials.tinted_image(os.path.join(project, h["texture"]), h.get("tint"),
                                              os.path.join(work_dir, "hair.png"))
            elif hobj.data.materials and hobj.data.materials[0]:
                himg = None
            else:
                himg = materials.hair_texture(color, os.path.join(work_dir, "hair.png"))
            if himg or not hobj.data.materials:
                hobj.data.materials.clear()
                hobj.data.materials.append(materials.make("Hair", image_path=himg, color=color, roughness=0.65,
                                                          double_sided=True))
        else:
            hobj = hair.make(res, body_obj, h["style"])
            style = catalog.HAIR_STYLES[h["style"]]
            if style.get("cards", True):
                base_img = hairtex.base_texture(color, os.path.join(work_dir, "hair_base.png"))
            else:
                base_img = hairtex.stubble_texture(color, os.path.join(work_dir, "hair_base.png"))
            if h.get("texture"):  # a strand atlas (RGBA, see hairtex) replaces the generated one
                cards_img = materials.tinted_image(os.path.join(project, h["texture"]), h.get("tint"),
                                                   os.path.join(work_dir, "hair_cards.png"))
            else:
                cards_img = hairtex.strand_atlas(color, os.path.join(work_dir, "hair_cards.png"),
                                                 wave=0.025 + 0.06 * style.get("curl", 0.0))
            hobj.data.materials[0] = materials.make("HairBase", image_path=base_img, roughness=0.75)
            hobj.data.materials[1] = materials.make_hair("Hair", cards_img)
        b.meshes.append(hobj)
        b.hair = hobj
        t = _tick(b, "hair", t)
    # skin
    skin = spec["skin"]
    if skin.get("texture"):
        img = os.path.join(project, skin["texture"])
    else:
        hs = spec.get("hair") or {}
        # tint the scalp under procedural hair so it seems to grow out of the skin
        scalp = hair.coverage_mask(res, hobj) if hs.get("style") and not hs.get("source") else None
        detail = skin.get("detail", True)
        ao = _skin_ao(res, body_obj, eyes) if detail else None
        img = textures.skin_texture(skin["color"], os.path.join(work_dir, "skin.png"),
                                    lips=skin.get("lips", True), brows=skin.get("brows", True),
                                    brow_hex=skin.get("brow_color") or hs.get("color"), scalp=scalp,
                                    scalp_hex=hs.get("color") or "#3b2a1e", brow_shape=_brow_shape(skin),
                                    detail=detail, ao=ao)
    skin_n = textures.skin_detail(os.path.join(work_dir, "skin"))
    rough = skin.get("roughness", 0.6)
    if skin.get("detail", True):
        shade = materials.skin_shading(skin["color"], rough)
        rmap = textures.skin_roughness(shade.pop("roughness"), os.path.join(work_dir, "skin_roughness.png"))
    else:
        shade, rmap = dict(subsurface=0.3, specular=0.35), None
    body_obj.data.materials.append(materials.make("Skin", image_path=img, roughness=rough, normal_path=skin_n,
                                                  roughness_path=rmap, **shade))
    eye_img = materials.eye_texture(os.path.join(rig.DATA, "eyes", "brown_eye.png"), os.path.join(work_dir, "eyes.png"),
                                    spec["eyes"].get("iris_color"))
    # a wet, clear coat over the eye gives the catchlight that makes it look alive
    eyes.data.materials.append(materials.make("Eyes", image_path=eye_img, roughness=0.3, specular=0.5, coat=1.0))

    if skin.get("brows", True):
        bobj = hair_cards.brows(res, body_obj, density=skin.get("brow_density") or 1.0, **_brow_shape(skin))
        hair_cards.follow_shape_keys(bobj, body_obj)
        brow_hex = skin.get("brow_color") or (h or {}).get("color") or "#2a1d14"
        bimg = hairtex.brow_atlas(brow_hex, os.path.join(work_dir, "brows.png"))
        bobj.data.materials.append(materials.make_hair("Eyebrows", bimg, roughness=0.5, anisotropic=0.3))
        util.add_armature_modifier(bobj, res.arm)
        b.meshes.append(bobj)
        t = _tick(b, "brows", t)

    # garments, inner layers first
    covers, covers_all, to_shade, hanging = [], [], [], []
    order = sorted(spec["garments"], key=lambda g: (g.get("layer", catalog.GARMENTS.get(g.get("type"), {}).get("layer", 1))))
    for rank, g in enumerate(order):
        if g.get("source"):
            gobj = import_mesh_file(os.path.join(project, g["source"]), g["id"])
            conform_imported(gobj, reference_coords(), res)
            # keep it outside the skin and anything already worn
            garments.conform(gobj, garments.body_bvh(body_obj), 0.003 + 0.003 * rank)
            util.add_armature_modifier(gobj, res.arm)
            keep_mats = (not g.get("texture") and not g.get("color") and not g.get("material")
                         and len(gobj.data.materials) > 0)
        else:
            # stack over lower layers only; footwear always sits under hems rather than over them
            under = [o for o, l in covers_all if l < layer_of(g)]
            if catalog.GARMENTS[g["type"]].get("slot") == "feet":
                under = []
            worn = garments.mesh_bvh(under) if under else None
            gobj, info = garments.make(res, reference_body(), body_obj, g["id"], g["type"], layer_of(g), worn)
            b.uv_info[g["id"]] = info
            keep_mats = False
        if not keep_mats:
            to_shade.append((g, gobj))
        gobj["garment_id"] = g["id"]
        if g.get("hide_body", True):
            covers.append(gobj)
            gd = catalog.GARMENTS.get(g.get("type"), {})
            if gd.get("source_group") == "helper-skirt" or "flare" in gd:
                hanging.append(gobj)
        covers_all.append((gobj, layer_of(g)))
        b.meshes.append(gobj)
    if spec["garments"]:
        t = _tick(b, "garments", t)
    if to_shade:
        _garment_materials(to_shade, project, work_dir, spec, b)
        t = _tick(b, "garment_textures", t)
    if spec.get("extra_bones") or spec.get("accessories") or spec.get("props"):
        from . import props
        extras.build_chains(b, spec)
        accessories.build_all(b, spec, project)
        props.build_all(b, spec, project)
        b.capsules = motion.leg_capsules(b)
        t = _tick(b, "extras", t)
    if "res" in _REF:
        bpy.data.objects.remove(_REF.pop("res").arm, do_unlink=True)
    if spec["export"].get("hide_body_under_clothes", True) and covers:
        n = hide_body(body_obj, covers, hanging=hanging, legs=_leg_verts(body_obj, res))
        b.hidden_faces = n
        t = _tick(b, "hide_body", t)
    return b


def export_glb(b, out_path, animations=(), secondary=None):
    """Export the GLB. secondary: extra chain ids to bake secondary motion for (None = all enabled)."""
    t = time.time()
    clips = []
    if animations:
        clips = anim.attach(b.arm, list(animations))
        for tr in b.arm.animation_data.nla_tracks:
            for st in tr.strips:
                b.warnings += motion.prepare(b, st.action, secondary)
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


def pose_clip(b, name, frame, secondary=None):
    """Pose the character with a clip at a frame (0..1 = fraction of the clip, else a frame number),
    with its extra motion (secondary motion, grips, two-hand IK) baked in."""
    f = anim.pose_at(b.arm, name, frame)
    act = b.arm.animation_data.action.copy()
    b.warnings += motion.prepare(b, act, secondary)
    motion._assign(b.arm, act)
    bpy.context.scene.frame_set(f)
    return f


def set_expression(b, weights):
    """Set facial blendshape weights {ARKit name: 0..1} on every mesh that has them (others go to 0)."""
    for m in b.meshes:
        keys = m.data.shape_keys
        if keys:
            for kb in keys.key_blocks[1:]:
                kb.value = float(weights.get(kb.name, 0.0))


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
    std = set(rig.m2m_bone_names())
    extra = [x.name for x in b.arm.data.bones if x.name not in std]
    if extra:
        out["skeleton"]["extra_bones"] = extra
    keys = b.body.data.shape_keys
    out["blendshapes"] = {"set": "arkit52" if keys else "none", "count": len(keys.key_blocks) - 1 if keys else 0,
                          "meshes": [m.name for m in b.meshes if m.data.shape_keys]}
    return out
