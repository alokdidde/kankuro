"""Turn the rigged reference body into an awkward autorig input: arms 45 degrees down, facing +X,
modelled in centimetres, with a shape key and no rig. Writes the GLB and the true joint positions
(in the input's own frame) next to it.  Usage: python make_autorig_variant.py ref_rigged.glb out.glb"""
import json
import math
import sys

import bpy
from mathutils import Matrix

src, out = sys.argv[1], sys.argv[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
for side, sg in (("l", 1), ("r", -1)):
    pb = arm.pose.bones[f"upperarm_{side}"]
    head = arm.matrix_world @ pb.head
    R = Matrix.Translation(head) @ Matrix.Rotation(math.radians(45 * sg), 4, "Y") @ Matrix.Translation(-head)
    pb.matrix = arm.matrix_world.inverted() @ R @ arm.matrix_world @ pb.matrix
    bpy.context.view_layer.update()
T = Matrix.Rotation(math.pi / 2, 4, "Z") @ Matrix.Scale(100, 4)   # -Y facing turned to face +X
joints = {n: list(T @ (arm.matrix_world @ arm.pose.bones[n].head))
          for n in ("upperarm_l", "lowerarm_l", "hand_l", "thigh_l", "calf_l", "foot_l", "neck_01")}
dg = bpy.context.evaluated_depsgraph_get()
meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
baked = []
for m in meshes:
    me = bpy.data.meshes.new_from_object(m.evaluated_get(dg))
    me.transform(T @ m.matrix_world)
    o = bpy.data.objects.new("body", me)
    bpy.context.scene.collection.objects.link(o)
    o.shape_key_add(name="Basis")
    o.shape_key_add(name="smile")
    baked.append(o)
for o in list(bpy.data.objects):
    if o not in baked:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
json.dump(joints, open(out[:-4] + ".joints.json", "w"))
