"""Fabric surface detail for garments (numpy + PIL, no Blender).

For each garment we bake three maps on its front/back UV layout:
  * albedo: the colour or supplied texture, with a little cavity darkening from the height field
  * normal: tangent-space, OpenGL convention (+Y up, what glTF expects)
  * the height field itself comes from a fabric preset (weave/knit/grain), hem and seam stitching
    along the garment outline, and optionally a user-supplied height or normal map (e.g. from Codex)
"""
import numpy as np
from PIL import Image

from .blender_free import hex_rgb

# period_mm: weave/knit repeat; amp: relative depth; rough: glTF roughness; fold: low-frequency
# wrinkle amount; stitch: draw hem/seam stitching
FABRICS = {
    "cotton": {"desc": "Jersey knit T-shirt cotton", "kind": "jersey", "period_mm": 3.5, "amp": 0.5, "rough": 0.85,
               "fold": 0.35, "stitch": True},
    "denim": {"desc": "Twill denim with diagonal weave", "kind": "twill", "period_mm": 5.0, "amp": 0.8, "rough": 0.8,
              "fold": 0.45, "stitch": True},
    "knit": {"desc": "Chunky knitted wool rib", "kind": "rib", "period_mm": 9.0, "amp": 1.0, "rough": 0.95,
             "fold": 0.3, "stitch": False},
    "canvas": {"desc": "Plain-weave canvas / jacket cloth", "kind": "plain", "period_mm": 4.0, "amp": 0.6,
               "rough": 0.8, "fold": 0.5, "stitch": True},
    "leather": {"desc": "Grained leather", "kind": "grain", "period_mm": 2.5, "amp": 0.55, "rough": 0.5,
                "fold": 0.25, "stitch": True},
    "silk": {"desc": "Smooth satin/silk", "kind": "smooth", "period_mm": 0, "amp": 0.0, "rough": 0.35,
             "fold": 0.5, "stitch": True},
    "spandex": {"desc": "Smooth stretch fabric (leggings, sportswear)", "kind": "jersey", "period_mm": 1.8,
                "amp": 0.25, "rough": 0.6, "fold": 0.1, "stitch": True},
}


def _noise(shape, scale_px, rng, aniso=(1.0, 1.0)):
    """Smooth value noise with feature size ~scale_px (separable box blur of white noise).

    Large features are generated on a coarser grid and upsampled, which keeps this cheap."""
    h, w = shape
    k = max(1, int(min(scale_px * min(aniso), 64) // 4))
    gh, gw = max(4, h // k), max(4, w // k)
    n = rng.standard_normal((gh, gw)).astype(np.float32)
    ry = max(1, round(scale_px * aniso[0] / k))
    rx = max(1, round(scale_px * aniso[1] / k))
    for _ in range(2):
        n = _box(n, ry, axis=0)
        n = _box(n, rx, axis=1)
    if (gh, gw) != (h, w):
        n = np.asarray(Image.fromarray(n, mode="F").resize((w, h), Image.BICUBIC))
    n = n - n.mean()
    return n / (n.std() + 1e-9)


def _box(a, r, axis):
    c = np.cumsum(np.pad(a, [(r + 1, r) if i == axis else (0, 0) for i in range(a.ndim)], mode="wrap"), axis=axis)
    hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
    lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
    return (hi - lo) / (2 * r + 1)


def weave(kind, size, px_per_mm, period_mm, rng):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    if kind == "smooth" or period_mm <= 0:
        return np.zeros((size, size), np.float32)
    p = max(period_mm * px_per_mm, 2.2)  # never below ~2 px or it aliases into noise
    if kind == "jersey":
        # columns of little V loops
        col = np.abs(np.sin(np.pi * x / p))
        row = 0.5 + 0.5 * np.sin(2 * np.pi * (y / p + 0.5 * np.sign(np.sin(np.pi * x / p)) * (x % p) / p))
        h = col * (0.6 + 0.4 * row)
    elif kind == "twill":
        h = 0.5 + 0.5 * np.sin(2 * np.pi * (x + y) / p)
        h = h * (0.8 + 0.2 * np.sin(2 * np.pi * x / (p * 0.5)))
    elif kind == "rib":
        h = np.abs(np.sin(np.pi * x / p)) ** 0.6
        h = h * (0.75 + 0.25 * np.abs(np.sin(np.pi * y / (p * 0.6))))
    elif kind == "plain":
        h = 0.5 + 0.25 * (np.sin(2 * np.pi * x / p) * np.sign(np.sin(np.pi * y / p))
                          + np.sin(2 * np.pi * y / p) * np.sign(np.sin(np.pi * x / p)))
    elif kind == "grain":
        h = np.abs(_noise((size, size), p * 0.6, rng)) * -1 + 1
    else:
        h = np.zeros((size, size), np.float32)
    h += 0.15 * rng.standard_normal((size, size)).astype(np.float32)  # fibre irregularity
    h -= h.min()
    return h / (h.max() + 1e-9)


def _edge_distance(mask, max_px):
    """Distance (px) from each inside pixel to the nearest outside pixel, capped at max_px (4-neighbour)."""
    d = np.where(mask, max_px, 0).astype(np.float32)
    cur = mask.copy()
    for i in range(1, max_px):
        er = cur & np.roll(cur, 1, 0) & np.roll(cur, -1, 0) & np.roll(cur, 1, 1) & np.roll(cur, -1, 1)
        d[cur & ~er] = i
        cur = er
        if not cur.any():
            break
    return d


def stitching(mask, px_per_mm):
    """Hem fold + a dashed stitch line just inside every outline (hems, cuffs, neckline, side seams)."""
    max_px = int(14 * px_per_mm) + 2
    d = _edge_distance(mask, max_px) / px_per_mm  # mm from edge
    h = np.zeros(mask.shape, np.float32)
    # rolled hem: slight bulge in the first 8 mm, soft groove at ~9 mm
    h += np.clip(1 - np.abs(d - 4) / 4, 0, 1) * 0.3
    h -= np.clip(1 - np.abs(d - 9) / 1.5, 0, 1) * 0.35
    # dashed stitches at 6 mm
    y, x = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    dash = (np.sin((x + y) * (np.pi / (3.0 * px_per_mm))) > 0).astype(np.float32)
    line = np.clip(1 - np.abs(d - 6) / 0.6, 0, 1)
    h += line * dash * 0.35
    h[~mask] = 0
    return h


def folds(size, px_per_mm, rng, amount):
    if amount <= 0:
        return np.zeros((size, size), np.float32)
    # soft irregular creases: a few broad mostly-horizontal ones plus random rumples, ridged so they
    # read as folds rather than a regular corrugation
    a = _noise((size, size), 22 * px_per_mm, rng, aniso=(0.5, 1.4))
    b = _noise((size, size), 30 * px_per_mm, rng)
    gate = np.clip(_noise((size, size), 60 * px_per_mm, rng) * 0.6 + 0.5, 0, 1)  # folds come and go
    ridge = 1 - np.abs(0.7 * a + 0.3 * b)
    return 0.6 * amount * (ridge - ridge.mean()) * gate


def normal_from_height(h, strength):
    """OpenGL tangent-space normal map from a height field (image rows go down, V goes up)."""
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    gy = (np.roll(h, 1, 0) - np.roll(h, -1, 0)) * 0.5  # d/dv: up in UV is up the image
    n = np.stack([-gx * strength, -gy * strength, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n


def blend_normals(a, b):
    """Whiteout blend of two tangent-space normals (detail on top of base)."""
    n = np.stack([a[..., 0] + b[..., 0], a[..., 1] + b[..., 1], a[..., 2] * b[..., 2]], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def _load(path, size, mode):
    im = Image.open(path).convert(mode)
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


def bake(out_prefix, size, uv_per_m, mask=None, color="#8a8f99", albedo_path=None, fabric="cotton",
         height_path=None, normal_path=None, strength=1.0, seed=1):
    """Write <prefix>_albedo.jpg and <prefix>_normal.jpg (JPEG keeps the GLB small). Returns (albedo, normal, roughness)."""
    rng = np.random.default_rng(seed)
    px_per_mm = size * uv_per_m / 1000.0
    f = FABRICS.get(fabric) if fabric and fabric != "none" else None
    h = np.zeros((size, size), np.float32)
    if f:
        h += f["amp"] * weave(f["kind"], size, px_per_mm, f["period_mm"], rng)
        h += folds(size, px_per_mm, rng, f["fold"])
        if f["stitch"] and mask is not None:
            h += stitching(mask, px_per_mm)
    if height_path:
        h += 3.0 * _load(height_path, size, "L")
    # normal strength in "height units per pixel": scale so 1 mm of relief reads clearly
    n = normal_from_height(h, strength * 2.0)
    if normal_path:
        user = _load(normal_path, size, "RGB") * 2 - 1
        user /= np.linalg.norm(user, axis=-1, keepdims=True) + 1e-9
        n = blend_normals(user, n)
    if albedo_path:
        alb = _load(albedo_path, size, "RGB")
    else:
        alb = np.ones((size, size, 3), np.float32) * np.array(hex_rgb(color), np.float32)
    # cavity: darken grooves slightly so the detail also shows in viewers without normal maps
    if f or height_path:
        hl = h - _box(_box(h, 6, 0), 6, 1)  # local relief only
        alb = alb * np.clip(1 + 0.35 * hl[..., None], 0.75, 1.1)
    a_path = out_prefix + "_albedo.jpg"
    n_path = out_prefix + "_normal.jpg"
    Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8)).save(a_path, quality=92)
    Image.fromarray(((n * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)).save(n_path, quality=94)
    rough = f["rough"] if f else 0.8
    return a_path, n_path, rough


def mask_from_polys(polys_uv, size):
    from PIL import ImageDraw
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    for p in polys_uv:
        d.polygon([(u * size, (1 - v) * size) for u, v in p], fill=255)
    return np.asarray(m) > 127
