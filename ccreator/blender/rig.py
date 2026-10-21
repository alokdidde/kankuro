"""Mesh2Motion human skeleton: fitting, armature creation and T-pose conversion."""
import json
import os
from functools import lru_cache

import bpy
import numpy as np
from mathutils import Matrix, Vector

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Bones whose rest direction is forced to the Mesh2Motion T-pose direction are all limb bones except
# these. The spine chain, neck and head keep the body's natural curve. Clavicles stay put too:
# Mesh2Motion's clavicle points ~40 degrees backward and up, and rotating the mesh to match it
# hunches the shoulders. (Every bone still gets Mesh2Motion's exact rest orientation afterwards, in
# match_m2m_orientation, which changes bone frames only, not the mesh.)
FREE_BONES = {"root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head", "head_leaf",
              "clavicle_l", "clavicle_r"}


@lru_cache(maxsize=1)
def m2m_rig():
    return json.load(open(os.path.join(DATA, "m2m_rig.json")))["bones"]


def m2m_bone_names():
    return [b["name"] for b in m2m_rig()]


def deform_bone_names():
    """Bones that receive skin weights (Mesh2Motion leaf bones and root carry none)."""
    return [n for n in m2m_bone_names() if "leaf" not in n and n != "root"]


@lru_cache(maxsize=1)
def mh_joints():
    return json.load(open(os.path.join(DATA, "mh_joints.json")))


def fit_from_makehuman(coords):
    """Mesh2Motion bone head/tail positions from morphed MakeHuman coordinates."""
    mj = mh_joints()
    J = {k: coords[np.asarray(v)].mean(0) for k, v in mj["joints"].items()}
    pos = {}
    for bone, (h, t) in mj["fit"].items():
        pos[bone] = [J[h].copy(), J[t].copy()]
    # Split MakeHuman's single head bone into head + head_leaf like Mesh2Motion.
    h, t = pos["head"]
    mid = h + (t - h) * 0.5
    pos["head"] = [h, mid]
    pos["head_leaf"] = [mid, t]
    _fill_leaves(pos)
    return pos


def _fill_leaves(pos):
    """Leaf bones extend their parent by the parent's length (Mesh2Motion convention)."""
    for b in m2m_rig():
        n = b["name"]
        if n in pos:
            continue
        if n == "root":
            continue
        if "leaf" in n:
            parent = b["parent"]
            h, t = pos[parent]
            pos[n] = [t.copy(), t + (t - h)]
    pel = pos["pelvis"][0]
    pos["root"] = [np.array([0.0, 0.0, 0.0]), np.array([0.0, float(pel[2]), 0.0])]


def create_armature(pos, name="Armature"):
    """Build an armature with exact Mesh2Motion names/hierarchy at the given positions."""
    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for b in m2m_rig():
        eb = arm_data.edit_bones.new(b["name"])
        h, t = pos[b["name"]]
        eb.head = Vector(h)
        eb.tail = Vector(t)
        if (eb.tail - eb.head).length < 1e-4:
            eb.tail = eb.head + Vector((0, 0, 0.01))
        ebs[b["name"]] = eb
    for b in m2m_rig():
        eb = ebs[b["name"]]
        if b["parent"]:
            eb.parent = ebs[b["parent"]]
        eb.align_roll(Vector(b["z_axis"]))
        eb.use_deform = "leaf" not in b["name"] and b["name"] != "root"
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def _hierarchy_order():
    rig = m2m_rig()
    children = {}
    for b in rig:
        children.setdefault(b["parent"], []).append(b["name"])
    order, stack = [], list(children.get(None, []))
    while stack:
        n = stack.pop(0)
        order.append(n)
        stack.extend(children.get(n, []))
    return order


def pose_to_tpose(arm):
    """Rotate limb bones (in pose mode) so they point along Mesh2Motion's T-pose directions."""
    target = {b["name"]: (Vector(b["tail"]) - Vector(b["head"])).normalized() for b in m2m_rig()}
    for n in _hierarchy_order():
        if n in FREE_BONES:
            continue
        bpy.context.view_layer.update()
        pb = arm.pose.bones[n]
        head = pb.head.copy()
        cur = (pb.tail - pb.head).normalized()
        q = cur.rotation_difference(target[n])
        M = Matrix.Translation(head) @ q.to_matrix().to_4x4() @ Matrix.Translation(-head)
        pb.matrix = M @ pb.matrix
    bpy.context.view_layer.update()


def apply_pose_as_rest(arm, meshes):
    """Bake the current pose into the meshes and make it the armature's rest pose."""
    from .util import get_coords, set_coords
    baked = [(m, get_coords(m, evaluated=True)) for m in meshes]
    heads = {pb.name: pb.head.copy() for pb in arm.pose.bones}
    tails = {pb.name: pb.tail.copy() for pb in arm.pose.bones}
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    for m, co in baked:
        set_coords(m, co)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in arm.data.edit_bones:
        eb.head = heads[eb.name]
        eb.tail = tails[eb.name]
    match_m2m_orientation(arm.data.edit_bones)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def match_m2m_orientation(edit_bones):
    """Give every bone exactly the Mesh2Motion rest orientation (direction + roll), keeping its head
    and length. Parent-relative rest rotations then equal Mesh2Motion's, so its animation clips play
    unchanged on this skeleton in any engine that maps bones by name."""
    for b in m2m_rig():
        eb = edit_bones[b["name"]]
        d = (Vector(b["tail"]) - Vector(b["head"])).normalized()
        length = max((eb.tail - eb.head).length, 0.005)
        eb.tail = eb.head + d * length
        eb.align_roll(Vector(b["z_axis"]))


def bone_positions(arm):
    mw = arm.matrix_world
    return {b.name: (np.array(mw @ b.head_local), np.array(mw @ b.tail_local)) for b in arm.data.bones}
