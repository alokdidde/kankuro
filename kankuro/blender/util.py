"""Small bpy helpers shared by the build steps."""
import contextlib
import os
import sys

import bpy
import numpy as np


@contextlib.contextmanager
def quiet(log_path=None):
    """Silence Blender's C-level stdout chatter (keeps our JSON stdout clean).

    Output is appended to log_path when given, else discarded."""
    sys.stdout.flush()
    sys.stderr.flush()
    target = open(log_path, "a") if log_path else open(os.devnull, "w")
    saved_out, saved_err = os.dup(1), os.dup(2)
    os.dup2(target.fileno(), 1)
    os.dup2(target.fileno(), 2)
    try:
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        target.close()


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_mesh(name, coords, faces, uvs=None, face_uvs=None):
    """Create a mesh object. faces: list of vertex-index lists. uvs/face_uvs optional (per-corner indices)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c) for c in coords], [], [list(f) for f in faces])
    if uvs is not None and face_uvs is not None:
        layer = me.uv_layers.new(name="UVMap")
        flat = np.array([i for f in face_uvs for i in f])
        layer.data.foreach_set("uv", np.asarray(uvs, dtype=np.float32)[flat].ravel())
    me.validate()
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    return link(bpy.data.objects.new(name, me))


def get_coords(obj, evaluated=False):
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        ev.to_mesh_clear()
    else:
        me = obj.data
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def set_coords(obj, co):
    obj.data.vertices.foreach_set("co", np.asarray(co, dtype=np.float64).ravel())
    obj.data.update()


def set_weights(obj, weights):
    """weights: dict bone -> (vertex_indices, values)."""
    for bone, (idx, w) in weights.items():
        vg = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
        for i, x in zip(np.asarray(idx).tolist(), np.asarray(w).tolist()):
            vg.add([i], x, "REPLACE")


def weight_matrix(obj, bone_names):
    """Dense (nverts, nbones) weight matrix of obj's vertex groups in bone_names order."""
    n = len(obj.data.vertices)
    W = np.zeros((n, len(bone_names)))
    col = {}
    for vg in obj.vertex_groups:
        if vg.name in bone_names:
            col[vg.index] = bone_names.index(vg.name)
    for v in obj.data.vertices:
        for g in v.groups:
            c = col.get(g.group)
            if c is not None:
                W[v.index, c] = g.weight
    return W


def set_weight_matrix(obj, W, bone_names, threshold=1e-3, max_influences=4):
    """Write a dense weight matrix as vertex groups (top-N influences, normalised)."""
    obj.vertex_groups.clear()
    groups = [obj.vertex_groups.new(name=b) for b in bone_names]
    W = np.asarray(W, dtype=np.float64)
    if max_influences and W.shape[1] > max_influences:
        idx = np.argsort(-W, axis=1)[:, max_influences:]
        np.put_along_axis(W, idx, 0.0, axis=1)
    W[W < threshold] = 0.0
    s = W.sum(1, keepdims=True)
    s[s == 0] = 1.0
    W = W / s
    for j, g in enumerate(groups):
        nz = np.nonzero(W[:, j])[0]
        for i in nz.tolist():
            g.add([i], float(W[i, j]), "REPLACE")
    return W


def add_armature_modifier(obj, arm):
    obj.parent = arm
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return mod


def deselect_all():
    # view_layer.objects can hold dangling entries after objects are removed; go through bpy.data
    vl = bpy.context.view_layer
    vl.update()
    for o in bpy.data.objects:
        if o.name in vl.objects:
            o.select_set(False)


def select_only(obj):
    deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
