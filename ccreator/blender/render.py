"""Preview renders (Cycles on CPU, so it works headless with no GPU)."""
import math
import os

import bpy
import numpy as np
from mathutils import Vector

VIEWS = {
    "front": 0.0,
    "three_quarter": 35.0,
    "side": 90.0,
    "back": 180.0,
}


def _bbox(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        mw = np.array(ev.matrix_world)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        pts.append(co)
        ev.to_mesh_clear()
    pts = np.concatenate(pts)
    return pts.min(0), pts.max(0)


def _setup(size, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = False
    sc.render.resolution_x = size
    sc.render.resolution_y = size
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    if not sc.world:
        sc.world = bpy.data.worlds.new("World")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.82, 0.84, 0.88, 1)
    bg.inputs[1].default_value = 0.8
    if "_key" not in bpy.data.objects:
        # soft, broad suns (studio-like): hard pin-point light makes cloth read as plastic
        for name, rot, energy, ang in (("_key", (50, 0, -35), 3.0, 14), ("_fill", (60, 0, 140), 1.0, 30),
                                       ("_rim", (110, 0, 170), 1.2, 10)):
            ld = bpy.data.lights.new(name, "SUN")
            ld.energy = energy
            ld.angle = math.radians(ang)
            lo = bpy.data.objects.new(name, ld)
            lo.rotation_euler = [math.radians(a) for a in rot]
            sc.collection.objects.link(lo)


def render_views(objs, out_dir, views=("front", "three_quarter", "side", "back"), size=512, samples=12, prefix="view",
                 bbox=None):
    """Render each view to out_dir/<prefix>_<view>.png and a combined sheet. Returns list of paths."""
    _setup(size, samples)
    sc = bpy.context.scene
    lo, hi = bbox if bbox is not None else _bbox(objs)
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    center = (lo + hi) / 2
    extent = float(max(hi[2] - lo[2], (hi[0] - lo[0]), (hi[1] - lo[1]))) * 1.08
    cam_data = bpy.data.cameras.get("_cam") or bpy.data.cameras.new("_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = extent
    cam = bpy.data.objects.get("_cam") or bpy.data.objects.new("_cam", cam_data)
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for v in views:
        ang = math.radians(VIEWS[v])
        # Characters face -Y; a camera at -Y looks at the front.
        d = Vector((math.sin(ang), -math.cos(ang), 0.0))
        cam.location = Vector(center) + d * 10
        cam.rotation_euler = (math.radians(90), 0, ang)
        cam_data.clip_end = 100
        p = os.path.join(out_dir, f"{prefix}_{v}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
    sheet = os.path.join(out_dir, f"{prefix}_sheet.png")
    _sheet(paths, sheet)
    return paths, sheet


def _sheet(paths, out):
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    w, h = ims[0].size
    s = Image.new("RGB", (w * len(ims), h), "white")
    for i, im in enumerate(ims):
        s.paste(im, (i * w, 0))
    s.save(out)
