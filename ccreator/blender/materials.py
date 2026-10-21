"""glTF-friendly materials (Principled BSDF + optional base colour image)."""
import os

import bpy
import numpy as np
from PIL import Image


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_linear(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def make(name, color=None, image_path=None, roughness=0.6, metallic=0.0, double_sided=False,
         normal_path=None, normal_strength=1.0, subsurface=0.0, specular=None, sheen=0.0, sheen_roughness=0.5,
         sheen_tint=(1.0, 1.0, 1.0)):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if normal_path:
        ntex = nt.nodes.new("ShaderNodeTexImage")
        ntex.image = bpy.data.images.load(os.path.abspath(normal_path))
        ntex.image.colorspace_settings.name = "Non-Color"
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = normal_strength
        nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if subsurface:
        # skin: light scatters further in red, which softens shading and kills the plastic look
        bsdf.subsurface_method = "RANDOM_WALK_SKIN"
        bsdf.inputs["Subsurface Weight"].default_value = subsurface
        bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
        bsdf.inputs["Subsurface Scale"].default_value = 0.006
    if specular is not None:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    if sheen:
        # cloth: soft rim brightening from fibres instead of a sharp highlight (exports as KHR_materials_sheen)
        bsdf.inputs["Sheen Weight"].default_value = sheen
        bsdf.inputs["Sheen Roughness"].default_value = sheen_roughness
        bsdf.inputs["Sheen Tint"].default_value = (*srgb_to_linear(sheen_tint), 1)
    if image_path:
        img = bpy.data.images.load(os.path.abspath(image_path))
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    elif color:
        r, g, b = srgb_to_linear(hex_rgb(color))
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
    mat.use_backface_culling = not double_sided
    return mat


def tinted_image(src, color, out):
    """Multiply an image by a colour (so a texture + tint exports as one glTF base colour map)."""
    im = Image.open(src).convert("RGBA")
    a = np.asarray(im).astype(np.float32) / 255
    if color:
        a[..., :3] *= np.array(hex_rgb(color), dtype=np.float32)
    Image.fromarray((a * 255).clip(0, 255).astype(np.uint8)).save(out)
    return out


def hair_texture(color, out, size=512, seed=7):
    """Strand-like streaks along V, tinted with the hair colour."""
    rng = np.random.default_rng(seed)
    cols = rng.normal(0, 1, size)
    for _ in range(3):
        cols = np.convolve(cols, [0.25, 0.5, 0.25], mode="same")
    cols = (cols - cols.min()) / (np.ptp(cols) + 1e-9)
    fine = rng.random(size) * 0.25
    stripe = 0.68 + 0.27 * cols + fine
    v = np.linspace(0, 1, size)[:, None]
    shade = 0.85 + 0.15 * v  # slightly darker at the roots/ends
    img = np.clip(stripe[None, :] * shade, 0, 1)
    rgb = img[..., None] * np.array(hex_rgb(color))[None, None, :]
    Image.fromarray((rgb * 255).astype(np.uint8)).save(out)
    return out


def recolor_iris(src, color, out):
    """Replace the iris hue of MakeHuman's eye texture with `color`, keeping its detail."""
    im = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) / 255
    mx, mn = im.max(-1), im.min(-1)
    sat = (mx - mn) / (mx + 1e-6)
    lum = im.mean(-1)
    iris = (sat > 0.18) & (lum < 0.8)
    target = np.array(hex_rgb(color))
    rel = lum / (np.median(lum[iris]) + 1e-6) if iris.any() else lum
    new = np.clip(rel[..., None] * target[None, None, :], 0, 1)
    res = np.where(iris[..., None], new, im)
    Image.fromarray((res * 255).astype(np.uint8)).save(out)
    return out
