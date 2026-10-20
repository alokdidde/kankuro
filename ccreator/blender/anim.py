"""Mesh2Motion animation library: list clips and attach them to a character armature."""
import os

import bpy

from ..errors import CliError
from .rig import DATA

LIBRARIES = {"human-base": os.path.join(DATA, "animations", "human-base-animations.glb")}


_CACHE = {}


def _import_library(path):
    if path in _CACHE and all(a.name in bpy.data.actions for a in _CACHE[path]):
        return _CACHE[path]
    before_objs = set(bpy.data.objects)
    before_actions = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=path)
    new_objs = [o for o in bpy.data.objects if o not in before_objs]
    actions = [a for a in bpy.data.actions if a not in before_actions]
    for o in new_objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in actions:
        a.use_fake_user = True
        # Mesh2Motion clip names are unique; drop Blender's ".001" suffixes on re-import
        if "." in a.name and a.name.rsplit(".", 1)[1].isdigit():
            a.name = a.name.rsplit(".", 1)[0]
    _CACHE[path] = actions
    return actions


def list_clips(library="human-base"):
    acts = _import_library(LIBRARIES[library])
    out = []
    for a in acts:
        fr = a.frame_range
        out.append({"name": a.name, "frames": [int(fr[0]), int(fr[1])], "seconds": round((fr[1] - fr[0]) / 30.0, 2)})
    return out


def attach(arm, names, library="human-base"):
    """Load clips by name ('all' for everything) onto arm as NLA tracks so glTF exports each one."""
    acts = _import_library(LIBRARIES[library])
    by_name = {a.name: a for a in acts}
    if names == ["all"]:
        wanted = list(by_name)
    else:
        missing = [n for n in names if n not in by_name]
        if missing:
            raise CliError("unknown_animation", f"Unknown animation(s): {', '.join(missing)}",
                           hint="Run `ccreator animations list` for valid clip names")
        wanted = names
    bone_names = {b.name for b in arm.data.bones}
    if arm.animation_data is None:
        arm.animation_data_create()
    ad = arm.animation_data
    for n in wanted:
        act = by_name[n]
        # Keep only channels for bones that exist on this armature
        _strip_foreign_channels(act, bone_names)
        track = ad.nla_tracks.new()
        track.name = n
        strip = track.strips.new(n, int(act.frame_range[0]), act)
        if hasattr(strip, "action_slot") and len(act.slots):
            strip.action_slot = act.slots[0]
        track.mute = True
    for a in acts:
        if a.name not in wanted:
            a.use_fake_user = False
            bpy.data.actions.remove(a)
    _CACHE.clear()
    return wanted


def _strip_foreign_channels(act, bone_names):
    try:
        bags = [cb for layer in act.layers for strip in layer.strips for cb in strip.channelbags]
    except AttributeError:
        bags = [act]
    for bag in bags:
        for fc in list(bag.fcurves):
            p = fc.data_path
            if p.startswith('pose.bones["'):
                bn = p.split('"')[1]
                if bn not in bone_names:
                    bag.fcurves.remove(fc)


def pose_at(arm, name, frame, library="human-base"):
    """Pose the armature with one clip at a frame (for preview renders)."""
    acts = _import_library(LIBRARIES[library])
    by_name = {a.name: a for a in acts}
    if name not in by_name:
        raise CliError("unknown_animation", f"Unknown animation '{name}'",
                       hint="Run `ccreator animations list` for valid clip names")
    act = by_name[name]
    if arm.animation_data is None:
        arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and len(act.slots):
        arm.animation_data.action_slot = act.slots[0]
    f = int(act.frame_range[0] + (act.frame_range[1] - act.frame_range[0]) * frame) if frame <= 1 else int(frame)
    bpy.context.scene.frame_set(f)
    return f
