"""Render one example image per material preset (docs/images/materials/<preset>.jpg) in the default
`render` lighting: a sphere and a ring (a faceted stone for `gem`).
Run: python tools/material_swatches.py [--samples 32] [--size 320]"""
import argparse
import math
import os
import sys

import bpy
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kankuro import matlib  # noqa: E402
from kankuro.blender import materials, render  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "images", "materials"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for name in matlib.MATERIALS:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mat = materials.make(name, **materials.preset_kwargs(matlib.resolve(name)))
        if name == "gem":
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.1, location=(-0.06, 0, 0))
        else:
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(-0.06, 0, 0), segments=64, ring_count=32)
            bpy.ops.object.shade_smooth()
        a_obj = bpy.context.object
        bpy.ops.mesh.primitive_torus_add(major_radius=0.07, minor_radius=0.014, location=(0.15, 0, -0.02),
                                         rotation=(math.radians(70), 0, math.radians(-25)), major_segments=96,
                                         minor_segments=24)
        bpy.ops.object.shade_smooth()
        b_obj = bpy.context.object
        for o in (a_obj, b_obj):
            o.data.materials.append(mat)
        render.render_views([a_obj, b_obj], a.out, views=("three_quarter",), size=a.size, samples=a.samples,
                            prefix=name, bbox=((-0.17, -0.1, -0.12), (0.23, 0.1, 0.12)))
        png = os.path.join(a.out, f"{name}_three_quarter.png")
        im = Image.open(png).convert("RGB")
        w, h = im.size
        im.crop((0, h // 5, w, h - h // 5)).save(os.path.join(a.out, f"{name}.jpg"), quality=88)
        os.remove(png)
        os.remove(os.path.join(a.out, f"{name}_sheet.png"))
        print(name)


if __name__ == "__main__":
    main()
