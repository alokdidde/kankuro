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

# period_mm: weave/knit repeat; amp: relative depth; rough: glTF roughness; fold: random soft wrinkle
# amount; stitch: draw hem/seam stitching; sheen/sheen_rough/spec: Principled sheen + specular level
# (cloth scatters light at grazing angles instead of a plastic-like specular highlight); crease: strength
# of compression wrinkles at elbows/knees/waist; heather: fibre colour variation; weft: denim white weft
FABRICS = {
    "cotton": {"desc": "Woven cotton (plain weave: kurta, dhoti, saree, shirting)", "kind": "plain",
               "period_mm": 2.5, "amp": 0.35, "rough": 0.9, "fold": 0.4, "stitch": True, "sheen": 0.45,
               "sheen_rough": 0.5, "spec": 0.25, "crease": 1.0, "heather": 0.05},
    "jersey": {"desc": "Jersey knit T-shirt cotton", "kind": "jersey", "period_mm": 3.5, "amp": 0.5, "rough": 0.92,
               "fold": 0.35, "stitch": True, "sheen": 0.6, "sheen_rough": 0.5, "spec": 0.25, "crease": 1.0,
               "heather": 0.06},
    "denim": {"desc": "Twill denim with diagonal weave", "kind": "twill", "period_mm": 5.0, "amp": 0.8, "rough": 0.9,
              "fold": 0.45, "stitch": True, "sheen": 0.3, "sheen_rough": 0.6, "spec": 0.25, "crease": 1.2,
              "heather": 0.05, "weft": 0.22},
    "knit": {"desc": "Chunky knitted wool rib", "kind": "rib", "period_mm": 9.0, "amp": 1.0, "rough": 0.96,
             "fold": 0.3, "stitch": False, "sheen": 0.9, "sheen_rough": 0.7, "spec": 0.2, "crease": 0.6,
             "heather": 0.08},
    "canvas": {"desc": "Plain-weave canvas / jacket cloth", "kind": "plain", "period_mm": 4.0, "amp": 0.6,
               "rough": 0.9, "fold": 0.5, "stitch": True, "sheen": 0.4, "sheen_rough": 0.5, "spec": 0.25,
               "crease": 1.1, "heather": 0.06},
    "leather": {"desc": "Grained leather", "kind": "grain", "period_mm": 2.5, "amp": 0.55, "rough": 0.58,
                "fold": 0.25, "stitch": True, "sheen": 0.0, "sheen_rough": 0.5, "spec": 0.45, "crease": 0.8,
                "heather": 0.05},
    "silk": {"desc": "Smooth satin/silk", "kind": "smooth", "period_mm": 0, "amp": 0.0, "rough": 0.5,
             "fold": 0.3, "stitch": True, "sheen": 1.0, "sheen_rough": 0.3, "spec": 0.35, "crease": 0.8,
             "heather": 0.02},
    "spandex": {"desc": "Smooth stretch fabric (leggings, sportswear)", "kind": "jersey", "period_mm": 1.8,
                "amp": 0.25, "rough": 0.65, "fold": 0.1, "stitch": True, "sheen": 0.35, "sheen_rough": 0.4,
                "spec": 0.35, "crease": 0.3, "heather": 0.03},
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


def seam_band(segments, size, px_per_mm, width_mm=16):
    """Mask of a band around UV line segments (the panel edges that are sewn to each other)."""
    from PIL import ImageDraw
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    w = max(1, int(round(2 * width_mm * px_per_mm)))
    for (u0, v0), (u1, v1) in segments:
        d.line([(u0 * size, (1 - v0) * size), (u1 * size, (1 - v1) * size)], fill=255, width=w)
    return np.asarray(m) > 127


def stitching(mask, px_per_mm, seams=None):
    """Hem fold + a dashed stitch line just inside every outline (hems, cuffs, neckline). `seams`
    (a mask from seam_band) marks outline where two panels are sewn together: a straight projection
    cuts those along the mesh's edges, so stitching drawn there would zigzag."""
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
    if seams is not None:
        h[seams] = 0
    return h


def placket(size, px_per_mm, uv_per_m, u, v, length=0.16, width=0.03, buttons=3, **_):
    """Height field of a button placket running down from (u, v) (the front-centre neck point in UV):
    a raised double-stitched band with domed buttons. Returns (height, button mask)."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    x0, y0 = u * size, (1 - v) * size
    L, W = length * uv_per_m * size, width * uv_per_m * size
    dx, dy = np.abs(x - x0), y - y0
    inside = (dx < W / 2) & (dy > -2) & (dy < L)
    h = np.zeros((size, size), np.float32)
    h[inside] += 0.25
    # bottom end of the band and the stitch lines 2.5 mm inside its edges
    edge = np.clip(1 - np.abs(dx - (W / 2 - 2.5 * px_per_mm)) / (0.6 * px_per_mm), 0, 1)
    dash = (np.sin(dy * (np.pi / (3.0 * px_per_mm))) > 0).astype(np.float32)
    h += edge * dash * 0.3 * ((dy > 0) & (dy < L))
    h -= np.clip(1 - np.abs(dx - W / 2) / (0.8 * px_per_mm), 0, 1) * 0.3 * ((dy > -2) & (dy < L))
    btn = np.zeros((size, size), bool)
    rad = 4.5 * px_per_mm
    for k in range(buttons):
        cy = y0 + L * (k + 0.6) / (buttons + 0.3)
        d = np.hypot(x - x0, y - cy) / max(rad, 1)
        dome = np.clip(1 - d * d, 0, 1)
        h += 1.4 * np.sqrt(dome)
        btn |= d < 1
    return h, btn


def folds(size, px_per_mm, rng, amount):
    if amount <= 0:
        return np.zeros((size, size), np.float32)
    # soft irregular creases: a few broad mostly-horizontal ones plus random rumples, ridged so they
    # read as folds rather than a regular corrugation
    a = _noise((size, size), 22 * px_per_mm, rng, aniso=(0.5, 1.4))
    b = _noise((size, size), 30 * px_per_mm, rng)
    gate = np.clip(_noise((size, size), 60 * px_per_mm, rng) * 0.6 + 0.5, 0, 1)  # folds come and go
    ridge = 1 - np.abs(0.7 * a + 0.3 * b)
    # height in pixel units so the slope (what the normal map shows) is independent of resolution
    return 0.04 * amount * 22 * px_per_mm * (ridge - ridge.mean()) * gate


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


def raster_attr(tri_uv, tri_val, size, max_channels=(), bleed=24):
    """Rasterise per-corner values of UV triangles into a (size, size, C) map with barycentric interpolation.

    tri_uv: (T, 3, 2) UVs, tri_val: (T, 3, C). Channels in max_channels keep the largest value where
    triangles overlap (e.g. the outer and inner shell of a solidified garment); others keep the last.
    Returns (map, covered)."""
    tri_uv = np.asarray(tri_uv, np.float64)
    tri_val = np.asarray(tri_val, np.float32)
    C = tri_val.shape[2]
    mx = np.zeros(C, bool)
    mx[list(max_channels)] = True
    out = np.zeros((size, size, C), np.float32)
    out[..., mx] = -np.inf
    cov = np.zeros((size, size), bool)
    P = np.empty_like(tri_uv)
    P[..., 0] = tri_uv[..., 0] * size - 0.5
    P[..., 1] = (1 - tri_uv[..., 1]) * size - 0.5
    lo = np.clip(np.floor(P.min(1)).astype(int), 0, size - 1)
    hi = np.clip(np.ceil(P.max(1)).astype(int), 0, size - 1)
    a, b, c = P[:, 0], P[:, 1], P[:, 2]
    den = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    for t in np.nonzero(np.abs(den) > 1e-12)[0]:
        (x0, y0), (x1, y1) = lo[t], hi[t]
        xs = np.arange(x0, x1 + 1)[None, :] - c[t, 0]
        ys = np.arange(y0, y1 + 1)[:, None] - c[t, 1]
        l1 = ((b[t, 1] - c[t, 1]) * xs + (c[t, 0] - b[t, 0]) * ys) / den[t]
        l2 = ((c[t, 1] - a[t, 1]) * xs + (a[t, 0] - c[t, 0]) * ys) / den[t]
        l3 = 1 - l1 - l2
        inside = (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3)
        if not inside.any():
            continue
        yy, xx = np.nonzero(inside)
        v = (l1[yy, xx, None] * tri_val[t, 0] + l2[yy, xx, None] * tri_val[t, 1]
             + l3[yy, xx, None] * tri_val[t, 2])
        yy, xx = yy + y0, xx + x0
        old = out[yy, xx]
        out[yy, xx] = np.where(mx, np.maximum(old, v), v)
        cov[yy, xx] = True
    out[~cov] = 0
    return (_dilate(out, cov, bleed) if bleed else out), cov


def blur(img, r, passes=2):
    for _ in range(passes):
        img = _box(_box(img, r, 0), r, 1)
    return img


def upscale(img, size):
    """Bicubic resize of a float (h, w) map."""
    if img.shape[0] == size:
        return img
    return np.asarray(Image.fromarray(img.astype(np.float32), mode="F").resize((size, size), Image.BICUBIC))


def _dilate(img, cov, iters):
    """Bleed covered pixels outward so texture filtering at UV seams doesn't pick up the background."""
    img, cov = img.copy(), cov.copy()
    for _ in range(iters):
        acc = np.zeros_like(img)
        cnt = np.zeros(cov.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            c = np.roll(cov, (dy, dx), (0, 1))
            acc += np.roll(img, (dy, dx), (0, 1)) * c[..., None]
            cnt += c
        new = ~cov & (cnt > 0)
        img[new] = acc[new] / cnt[new][:, None]
        cov |= new
    return img


def creases(chain_s, weight, size, px_per_mm, rng, amount):
    """Compression wrinkles: rings around the limb (constant chain distance s) where `weight` is high,
    bent and broken up by noise so they read as cloth bunching rather than regular corrugation."""
    if amount <= 0:
        return np.zeros((size, size), np.float32)
    lam_mm = 32.0
    warp = 2.2 * _noise((size, size), 30 * px_per_mm, rng) + 0.4 * _noise((size, size), 9 * px_per_mm, rng)
    phase = 2 * np.pi * chain_s * 1000.0 / lam_mm + warp
    p = 2 * np.abs(np.sin(phase * 0.5)) - 1  # sharp valleys (the crease), rounded ridges
    gate = np.clip(0.55 + 0.7 * _noise((size, size), 22 * px_per_mm, rng), 0, 1)
    lam_px = lam_mm * px_per_mm
    return amount * 0.035 * lam_px * weight * gate * p


def bake(out_prefix, size, uv_per_m, mask=None, color="#8a8f99", albedo_path=None, fabric="cotton",
         height_path=None, normal_path=None, strength=1.0, seed=1, ao=None, chain_s=None, crease_w=None, detail=None,
         seams=None, placket_spec=None, finish=None, roughness=None, regions=()):
    """Write <prefix>_albedo.jpg and <prefix>_normal.jpg (JPEG keeps the GLB small).

    ao: (size, size) ambient occlusion baked from the dressed character (1 = open), multiplied into the
    albedo so folds, collars and layer overlaps keep their depth in viewers without AO.
    chain_s/crease_w: maps from clothshade for compression wrinkles at joints.
    detail: 0..1 map fading procedural detail where the UVs are squeezed (it would smear into streaks).
    seams: UV segments where panels are sewn together (no hem stitching drawn along them).
    placket_spec: {u, v, length, width, buttons} for a buttoned front placket (kurta).
    finish: a resolved matlib preset for the whole garment (metal armour, lacquered leather): its
    metallic/roughness replace the fabric's, and its colour is the base colour unless a texture is given.
    regions: [(mask, preset)] areas of the template (0..1 float masks) in another material, e.g. a gold
    zari border: tinted with the preset's colour, keeping the cloth's weave relief, folds and occlusion,
    and written into a metallic-roughness map (<prefix>_mr.png: G = roughness, B = metallic).
    Returns (albedo, normal, material) where material holds roughness/sheen/specular for the shader."""
    rng = np.random.default_rng(seed)
    px_per_mm = size * uv_per_m / 1000.0
    f = FABRICS.get(fabric) if fabric and fabric != "none" else None
    h = np.zeros((size, size), np.float32)
    keep = np.ones((size, size), np.float32) if detail is None else detail.astype(np.float32)
    if f:
        h += f["amp"] * weave(f["kind"], size, px_per_mm, f["period_mm"], rng)
        h += folds(size, px_per_mm, rng, f["fold"])
        if f["stitch"] and mask is not None:
            h += stitching(mask, px_per_mm, seam_band(seams, size, px_per_mm) if seams else None)
        if chain_s is not None and crease_w is not None:
            h += creases(chain_s, crease_w, size, px_per_mm, rng, f["crease"])
        h *= keep
    btn = None
    if placket_spec:
        hp, btn = placket(size, px_per_mm, uv_per_m, **placket_spec)
        h += hp
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
        alb = np.ones((size, size, 3), np.float32) * np.array(hex_rgb(finish["color"] if finish else color),
                                                             np.float32)
    alb0 = alb.copy()
    if f:
        # real cloth is never one flat colour: dye mottling, fibre heathering and (denim) white weft
        alb = alb * (1 + 0.03 * (_noise((size, size), 45 * px_per_mm, rng) * keep)[..., None])
        fib = rng.standard_normal((size, size)).astype(np.float32)
        fib = _box(_box(fib, 1, 0), 1, 1)
        alb = alb * (1 + f["heather"] * 1.8 * (fib * keep)[..., None])
        if f.get("weft"):
            wv = weave(f["kind"], size, px_per_mm, f["period_mm"], rng)
            alb = alb + f["weft"] * ((wv - 0.5) * keep)[..., None] * (0.9 - alb)
    if btn is not None and btn.any():  # buttons: horn/shell, a little darker than the cloth
        alb[btn] = alb[btn] * 0.78
    # cavity: darken grooves so creases and stitching also show without normal mapping
    if f or height_path:
        hl = h - _box(_box(h, 6, 0), 6, 1)  # local relief only
        hl = hl / (np.abs(hl).mean() + 1e-6)
        alb = alb * np.clip(1 + 0.04 * hl[..., None], 0.8, 1.06)
    if ao is not None:
        # squeezed UV strips can't hold occlusion detail either (it shows as blocks): fade it there too
        ao = 1 - (1 - np.clip(ao, 0, 1)) * keep
        alb = alb * (0.5 + 0.5 * ao)[..., None]
    rough0 = finish["roughness"] if finish else (roughness if roughness is not None else (f["rough"] if f else 0.8))
    metal0 = finish["metallic"] if finish else 0.0
    mr_path = None
    if regions:
        # the shading baked into the albedo (AO, cavities, heathering) as a factor of the plain colour,
        # carried over onto the region's colour
        shade = (alb / np.maximum(alb0, 0.02)).mean(-1, keepdims=True)
        R = np.full((size, size), rough0, np.float32)
        M = np.full((size, size), metal0, np.float32)
        for rmask, rp in regions:
            w = rmask.astype(np.float32)[..., None]
            alb = alb * (1 - w) + np.array(hex_rgb(rp["color"]), np.float32) * shade * w
            R = R * (1 - w[..., 0]) + rp["roughness"] * w[..., 0]
            M = M * (1 - w[..., 0]) + rp["metallic"] * w[..., 0]
        mr = np.zeros((size, size, 3), np.float32)
        mr[..., 1], mr[..., 2] = R, M
        mr_path = out_prefix + "_mr.png"
        Image.fromarray((np.clip(mr, 0, 1) * 255).astype(np.uint8)).save(mr_path)
    a_path = out_prefix + "_albedo.jpg"
    n_path = out_prefix + "_normal.jpg"
    Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8)).save(a_path, quality=92)
    Image.fromarray(((n * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)).save(n_path, quality=94)
    mat = {"roughness": rough0, "metallic": metal0, "mr": mr_path,
           "sheen": 0.0 if finish and finish["metallic"] > 0.5 else (f["sheen"] if f else 0.3),
           "sheen_roughness": f["sheen_rough"] if f else 0.5, "specular": f["spec"] if f else 0.3}
    m = mask if mask is not None else np.ones((size, size), bool)
    mean = alb[m].mean(0) if m.any() else np.full(3, 0.5)
    mat["sheen_tint"] = tuple(float(x) for x in (0.5 * mean / (mean.max() + 1e-6) + 0.5))
    return a_path, n_path, mat


def mask_from_polys(polys_uv, size):
    from PIL import ImageDraw
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    for p in polys_uv:
        d.polygon([(u * size, (1 - v) * size) for u, v in p], fill=255)
    return np.asarray(m) > 127
