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
         sheen_tint=(1.0, 1.0, 1.0), roughness_path=None, subsurface_radius=(1.0, 0.35, 0.2), coat=0.0,
         coat_roughness=0.03, metallic_path=None, transmission=0.0, ior=None, anisotropy=0.0, thin_film=0.0):
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
    if roughness_path:
        # glTF metallicRoughness: roughness in G (the exporter recognises Separate Color -> Roughness)
        rtex = nt.nodes.new("ShaderNodeTexImage")
        rtex.image = bpy.data.images.load(os.path.abspath(roughness_path))
        rtex.image.colorspace_settings.name = "Non-Color"
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(rtex.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        if metallic_path == roughness_path:  # one glTF metallicRoughness map: metallic in B
            nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    bsdf.inputs["Metallic"].default_value = metallic
    if coat:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if transmission:  # gems: exports as KHR_materials_transmission + KHR_materials_ior
        bsdf.inputs["Transmission Weight"].default_value = transmission
    if ior:
        bsdf.inputs["IOR"].default_value = ior
    if anisotropy:
        bsdf.inputs["Anisotropic"].default_value = anisotropy
    if thin_film:  # nacre shimmer (KHR_materials_iridescence)
        bsdf.inputs["Thin Film Thickness"].default_value = thin_film
        bsdf.inputs["Thin Film IOR"].default_value = 1.5
    if subsurface:
        # skin: light scatters further in red, which softens shading and kills the plastic look
        bsdf.subsurface_method = "RANDOM_WALK_SKIN"
        bsdf.inputs["Subsurface Weight"].default_value = subsurface
        bsdf.inputs["Subsurface Radius"].default_value = subsurface_radius
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


def preset_kwargs(p):
    """materials.make() keyword arguments for a resolved matlib preset (matlib.resolve)."""
    kw = dict(color=p["color"], metallic=p["metallic"], roughness=p["roughness"])
    for k in ("specular", "coat", "coat_roughness", "transmission", "ior", "anisotropy", "thin_film", "subsurface"):
        if p.get(k):
            kw[k] = p[k]
    if p.get("subsurface"):
        kw["subsurface_radius"] = (0.6, 0.5, 0.4)
    return kw


def make_hair(name, image_path, roughness=0.55, anisotropic=0.45, cutoff=0.4):
    """Strand-card material: colour + alpha from an RGBA atlas, alpha-clipped (exports as glTF MASK, which
    needs no sorting in game engines), with a highlight stretched across the strands."""
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(os.path.abspath(image_path))
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    # glTF alpha clip pattern: 1 - (alpha < cutoff)
    lt = nt.nodes.new("ShaderNodeMath")
    lt.operation = "LESS_THAN"
    lt.inputs[1].default_value = cutoff
    nt.links.new(tex.outputs["Alpha"], lt.inputs[0])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(lt.outputs[0], inv.inputs[1])
    nt.links.new(inv.outputs[0], bsdf.inputs["Alpha"])
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = 0.25
    if anisotropic:
        # cards run along V, so the UV tangent (along U) lies across the strands
        tan = nt.nodes.new("ShaderNodeTangent")
        tan.direction_type = "UV_MAP"
        tan.uv_map = "UVMap"
        bsdf.inputs["Anisotropic"].default_value = anisotropic
        nt.links.new(tan.outputs["Tangent"], bsdf.inputs["Tangent"])
    mat.use_backface_culling = False
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
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


def skin_shading(hex_color, roughness):
    """Principled settings tuned to the skin tone. Darker skin has more melanin, which absorbs the
    light scattered under the surface: less visible subsurface glow (that is what washes out the shape
    and reads as wax) and a crisper, more visible specular sheen that carries the form."""
    lum = float(np.dot(srgb_to_linear(hex_rgb(hex_color)), [0.2126, 0.7152, 0.0722]))
    dark = float(np.clip((0.35 - lum) / 0.3, 0, 1))  # 0 for fair skin .. 1 for deep brown
    return dict(subsurface=0.3 - 0.12 * dark, subsurface_radius=(1.0, 0.35 - 0.1 * dark, 0.2 - 0.08 * dark),
                specular=0.35 + 0.15 * dark, roughness=roughness - 0.06 * dark)


def eye_texture(src, out, iris_color=None):
    """MakeHuman's eye texture with a clean, bright sclera (whites read at any skin tone) and,
    optionally, the iris recoloured."""
    im = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) / 255
    mx, mn = im.max(-1), im.min(-1)
    sat = (mx - mn) / (mx + 1e-6)
    lum = im.mean(-1)
    sclera = (sat < 0.25) & (lum > 0.45)
    k = np.clip((lum - 0.45) / 0.2, 0, 1)[..., None] * sclera[..., None]
    white = np.array([0.95, 0.93, 0.9])
    im = im * (1 - 0.6 * k) + white * 0.6 * k
    Image.fromarray((np.clip(im, 0, 1) * 255).astype(np.uint8)).save(out)
    return recolor_iris(out, iris_color, out) if iris_color else out


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
