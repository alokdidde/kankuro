"""Image helpers (numpy + PIL): UV rasterisation, generated skin maps and UV template sheets."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import morph


def _font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def raster_scalar(tris_uv, tris_val, size):
    """Rasterise per-corner scalar values on UV triangles into a (size, size) float image (max blend)."""
    img = np.zeros((size, size), dtype=np.float32)
    for (a, b, c), (va, vb, vc) in zip(tris_uv, tris_val):
        if max(va, vb, vc) <= 0:
            continue
        P = np.array([a, b, c]) * (size - 1)
        P[:, 1] = (size - 1) - P[:, 1]
        x0, y0 = np.floor(P.min(0)).astype(int)
        x1, y1 = np.ceil(P.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (P[1, 1] - P[2, 1]) * (P[0, 0] - P[2, 0]) + (P[2, 0] - P[1, 0]) * (P[0, 1] - P[2, 1])
        if abs(d) < 1e-12:
            continue
        l1 = ((P[1, 1] - P[2, 1]) * (xs - P[2, 0]) + (P[2, 0] - P[1, 0]) * (ys - P[2, 1])) / d
        l2 = ((P[2, 1] - P[0, 1]) * (xs - P[2, 0]) + (P[0, 0] - P[2, 0]) * (ys - P[2, 1])) / d
        l3 = 1 - l1 - l2
        inside = (l1 >= -0.01) & (l2 >= -0.01) & (l3 >= -0.01)
        val = l1 * va + l2 * vb + l3 * vc
        sub = img[y0:y1 + 1, x0:x1 + 1]
        np.maximum(sub, np.where(inside, val, 0), out=sub)
    return img


def _target_mask(names):
    t = morph.targets()
    n = len(morph.base()["coords"])
    m = np.zeros(n)
    for name in names:
        d = np.linalg.norm(t[name + "|d"], axis=1)
        m[t[name + "|i"]] = np.maximum(m[t[name + "|i"]], d / d.max())
    return m


def brow_arc(u, e, r, arch=0.0):
    """Height of the brow line above eye centre e (eye radius r) at u (-1 inner end .. +1 outer end)."""
    u = np.asarray(u, dtype=float)
    up = np.clip(u, 0, None)
    z = e[2] + r * (1.45 + 0.35 * (1 - u ** 2)) - r * 0.25 * np.clip(up, 0, 1)
    return z + r * 0.3 * arch * np.clip(1 - (u - 0.3) ** 2 / 1.69, 0, None)


def brow_thick(u, r, thickness=1.0):
    """Half-height of the brow band at u."""
    u = np.asarray(u, dtype=float)
    return r * (0.29 - 0.15 * np.clip(u, 0, 1)) * np.where(u < -0.6, 1.15, 1.0) * thickness


def eye_frame_base(side):
    """Centre and radius of an eye on the neutral base mesh."""
    b = morph.base()
    co = b["coords"].astype(float)
    names = list(b["group_names"])
    sizes = b["face_sizes"]
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    gid = names.index(f"helper-{side}-eye")
    fids = np.nonzero(b["face_group"] == gid)[0]
    vs = np.unique(np.concatenate([b["face_verts"][starts[f]:starts[f] + sizes[f]] for f in fids]))
    return co[vs].mean(0), np.ptp(co[vs][:, 0]) / 2


def _brow_mask(thickness=1.0, arch=0.0, length=1.0):
    """Per-vertex brow strength on the neutral base face: the band the brow hairs
    (blender/hair_cards.brows) are rooted in, so paint and hairs always coincide."""
    co = morph.base()["coords"].astype(float)
    m = np.zeros(len(co))
    body = np.unique(np.concatenate(morph.faces_of_group("body")[0]))
    for side in ("l", "r"):
        e, r = eye_frame_base(side)
        p = co[body]
        dx = (p[:, 0] - e[0]) * (1 if side == "l" else -1)  # + towards the temple
        u = dx / (r * 2.1)  # -1 inner end .. +1 outer end
        arc = brow_arc(u, e, r, arch)
        thick = brow_thick(u, r, thickness) * 1.1
        w = np.exp(-((p[:, 2] - arc) / thick) ** 2) * (u > -0.97) * (u < length + 0.05) * (p[:, 1] < e[1] + r * 0.3)
        w *= np.clip((1.05 + u) * 4, 0, 1) * np.clip((length + 0.05 - u) * 4 / max(length, 0.3), 0, 1)
        m[body] = np.maximum(m[body], w)
    return m


def _body_uv_tris():
    faces, fuvs = morph.faces_of_group("body")
    uvs = morph.base()["uvs"]
    tris_v, tris_uv = [], []
    for f, fu in zip(faces, fuvs):
        for a, b, c in ((0, 1, 2), (0, 2, 3)) if len(f) == 4 else ((0, 1, 2),):
            tris_v.append((f[a], f[b], f[c]))
            tris_uv.append((uvs[fu[a]], uvs[fu[b]], uvs[fu[c]]))
    return np.array(tris_v), np.array(tris_uv)


def _blur(a, r=2):
    k = np.ones(2 * r + 1) / (2 * r + 1)
    a = np.apply_along_axis(lambda x: np.convolve(x, k, mode="same"), 0, a)
    return np.apply_along_axis(lambda x: np.convolve(x, k, mode="same"), 1, a)


def face_regions():
    """Per base-vertex weights (0..1) of facial regions used for natural skin tone variation:
    cheeks, nose, upper lids / eye sockets, lash lines, under-eye, T-zone (forehead and nose bridge)."""
    co = morph.base()["coords"].astype(float)
    r = {}
    r["cheeks"] = np.clip(_target_mask(["cheek/l-cheek-volume-incr", "cheek/r-cheek-volume-incr",
                                        "cheek/l-cheek-bones-incr", "cheek/r-cheek-bones-incr"]) * 1.4 - 0.2, 0, 1)
    r["nose"] = np.clip(_target_mask(["nose/nose-volume-incr", "nose/nose-point-width-incr",
                                      "nose/nose-flaring-incr"]) * 1.3 - 0.15, 0, 1)
    lids = np.zeros(len(co))
    lash = np.zeros(len(co))
    under = np.zeros(len(co))
    for side in ("l", "r"):
        e, rad = eye_frame_base(side)
        d = co - e
        dist = np.linalg.norm(d[:, [0, 2]], axis=1) / rad  # in the face plane, in eye radii
        front = d[:, 1] < rad * 0.9  # skin in front of the eyeball (characters face -Y)
        up = d[:, 2] > -0.15 * rad
        lids = np.maximum(lids, front * up * np.clip(1 - np.abs(dist - 1.35) / 0.55, 0, 1))
        lash = np.maximum(lash, front * (d[:, 2] > 0.05 * rad) * np.clip(1 - np.abs(dist - 1.0) / 0.18, 0, 1))
        under = np.maximum(under, front * (d[:, 2] < -0.3 * rad) * np.clip(1 - np.abs(dist - 1.4) / 0.45, 0, 1))
    e_l, rad = eye_frame_base("l")
    head_front = (co[:, 1] < e_l[1] + rad) & (np.abs(co[:, 0]) < 3.2 * rad)
    tz = head_front * np.clip((co[:, 2] - (e_l[2] + 2.2 * rad)) / (1.5 * rad), 0, 1) * (co[:, 2] < e_l[2] + 9 * rad)
    r.update(lids=lids, lash=lash, under=under, tzone=np.maximum(tz, r["nose"]))
    return r


def skin_texture(skin_hex, out, size=1024, lips=True, brows=True, brow_hex=None, scalp=None, scalp_hex=None,
                 brow_shape=None, detail=True, ao=None):
    """Skin tone with soft lips and brows painted on the MakeHuman body UV layout.

    scalp: optional per base-vertex weight (hair.coverage_mask) tinted towards scalp_hex, with a speckled
    edge, so the hairline reads as hair growing out of the skin rather than a layer laid on top.
    detail: natural tone variation (warmer cheeks and nose, darker lids and lash lines, a little shadow
    under the eyes) so the face reads at any skin tone instead of as one flat paint.
    ao: optional per base-vertex ambient occlusion (1 = open) baked into the folds of the face and body,
    which keeps the face's shape readable on dark skin and in viewers without AO."""
    from .blender_free import hex_rgb
    tone = np.array(hex_rgb(skin_hex))
    img = np.ones((size, size, 3), dtype=np.float32) * tone
    # subtle blotchy variation (slightly redder/darker patches) so the tone isn't a flat paint
    from .fabric import _noise
    rng = np.random.default_rng(3)
    blot = _noise((size, size), size / 40, rng) * 0.5 + _noise((size, size), size / 140, rng) * 0.5
    img = img * (1 + (0.05 if detail else 0.035) * blot[..., None] * np.array([0.6, 1.0, 1.1]))
    tv, tuv = _body_uv_tris()
    if detail:
        reg = face_regions()

        def paint(m, mul, blur=2):
            w = _blur(raster_scalar(tuv, m[tv], size), blur)[..., None]
            return img * (1 + w * (np.array(mul) - 1))
        img = paint(reg["cheeks"], (1.06, 0.95, 0.94), 4)      # blood flow: warmer, redder cheeks
        img = paint(reg["nose"], (1.05, 0.95, 0.95), 3)        # and nose
        img = paint(reg["lids"], (0.86, 0.83, 0.84), 2)        # darker upper lids / sockets
        img = paint(reg["under"], (0.94, 0.92, 0.95), 3)       # a hint of shadow under the eyes
        img = paint(reg["lash"], (0.55, 0.5, 0.5), 1)          # lash line: frames the eye
    if ao is not None:
        a = _blur(raster_scalar(tuv, (1 - np.clip(ao, 0, 1))[tv], size), 2)[..., None]
        img = img * (1 - 0.45 * a)
    if lips:
        m = _target_mask(["mouth/mouth-upperlip-volume-incr", "mouth/mouth-lowerlip-volume-incr"])
        m = np.clip((m - 0.35) / 0.4, 0, 1)
        lip = raster_scalar(tuv, m[tv], size)
        lip = _blur(lip, 2)[..., None]
        lip_col = tone * np.array([0.82, 0.55, 0.55])
        img = img * (1 - 0.75 * lip) + lip_col * 0.75 * lip
    if brows:
        m = _brow_mask(**(brow_shape or {}))
        br = raster_scalar(tuv, m[tv], size)
        # only a faint shadow under the brow hairs (blender/hair_cards.brows); a solid paint reads as a smudge
        br = _blur(br, 2)[..., None]
        bc = np.array(hex_rgb(brow_hex)) if brow_hex else tone * 0.35
        img = img * (1 - 0.4 * br) + bc * 0.4 * br
    if scalp is not None and scalp_hex:
        sc = _blur(raster_scalar(tuv, scalp[tv], size), 2)
        speck = np.clip(_noise((size, size), 1.5, rng) * 0.6 + 0.5, 0, 1)
        # the fade below the hairline is broken into fine dots (follicles / baby hairs), not a soft smear
        sc = np.where(sc < 0.95, sc * (0.35 + 0.9 * speck), sc).clip(0, 1)[..., None]
        hc = tone * 0.45 + np.array(hex_rgb(scalp_hex)) * 0.55
        img = img * (1 - 0.8 * sc) + hc * 0.8 * sc
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(out)
    return out


def skin_roughness(base, out, size=1024):
    """Roughness map for the skin: the T-zone and nose are a little oilier (shinier), lips glossier,
    cheeks and the rest of the body drier. Breaks up the even plastic sheen of one roughness value."""
    reg = face_regions()
    tv, tuv = _body_uv_tris()
    r = np.full((size, size), base + 0.04, np.float32)
    tz = _blur(raster_scalar(tuv, reg["tzone"][tv], size), 4)
    r -= 0.14 * tz
    m = _target_mask(["mouth/mouth-upperlip-volume-incr", "mouth/mouth-lowerlip-volume-incr"])
    lip = _blur(raster_scalar(tuv, np.clip((m - 0.35) / 0.4, 0, 1)[tv], size), 2)
    r -= 0.2 * lip
    g = (np.clip(r, 0.05, 1) * 255).astype(np.uint8)
    Image.fromarray(np.stack([g, g, g], -1)).save(out)  # glTF reads roughness from G
    return out


def skin_detail(out_prefix, size=2048, seed=5):
    """Pore/micro-wrinkle normal map for the body UV layout. Fine surface detail breaks up specular
    highlights, which is most of what makes bare skin look like plastic."""
    from .fabric import _noise, normal_from_height
    rng = np.random.default_rng(seed)
    pores = -np.clip(_noise((size, size), 1.2, rng), 0.6, None)  # small pits
    micro = _noise((size, size), 3.0, rng, aniso=(0.4, 1.6)) * 0.35
    h = pores + micro
    n = normal_from_height(h.astype(np.float32), 0.09)
    n_path = out_prefix + "_normal.jpg"
    Image.fromarray(((n * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)).save(n_path, quality=94)
    return n_path


def uv_template(polys_uv, out, title, size=2048, labels=(("FRONT", 0.25), ("BACK", 0.75)), mask_out=None,
                divider=True):
    """Draw a UV template sheet: garment area filled light grey, wireframe, panel labels.

    polys_uv: list of polygons, each a list of (u, v). labels: (text, u) at the top or (text, u, v).
    Returns paths."""
    im = Image.new("RGB", (size, size), "white")
    dr = ImageDraw.Draw(im)
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    pts = [[(u * size, (1 - v) * size) for u, v in p] for p in polys_uv]
    for p in pts:
        dr.polygon(p, fill=(232, 232, 236))
        md.polygon(p, fill=255)
    for p in pts:
        dr.line(p + [p[0]], fill=(170, 170, 185), width=1)
    f = _font(size // 28)
    for text, u, *v in labels:
        w = dr.textlength(text, font=f)
        y = (1 - v[0]) * size if v else size * 0.012
        dr.text((u * size - w / 2, y), text, fill=(40, 40, 60), font=f)
    dr.text((size * 0.01, size - size // 22), title, fill=(90, 90, 110), font=_font(size // 45))
    if divider:
        dr.line([(size / 2, 0), (size / 2, size)], fill=(200, 80, 80), width=2)
    im.save(out)
    if mask_out:
        mask.save(mask_out)
    return out
