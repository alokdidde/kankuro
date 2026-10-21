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


def _brow_mask():
    """Per-vertex brow strength: an arc above each eye on the front of the neutral base face."""
    b = morph.base()
    co = b["coords"].astype(float)
    names = list(b["group_names"])
    sizes = b["face_sizes"]
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    m = np.zeros(len(co))
    body = np.unique(np.concatenate(morph.faces_of_group("body")[0]))
    for side in ("l", "r"):
        gid = names.index(f"helper-{side}-eye")
        fids = np.nonzero(b["face_group"] == gid)[0]
        vs = np.unique(np.concatenate([b["face_verts"][starts[f]:starts[f] + sizes[f]] for f in fids]))
        e = co[vs].mean(0)
        r = np.ptp(co[vs][:, 0]) / 2  # eye radius
        p = co[body]
        dx = (p[:, 0] - e[0]) * (1 if side == "l" else -1)  # + towards the temple
        u = dx / (r * 2.1)  # -1 inner end .. +1 outer end
        arc = e[2] + r * (1.45 + 0.35 * (1 - u ** 2)) - r * 0.25 * np.clip(u, 0, 1)
        thick = r * (0.32 - 0.12 * np.clip(u, 0, 1))
        w = np.exp(-((p[:, 2] - arc) / thick) ** 2) * (np.abs(u) < 1.05) * (p[:, 1] < e[1] + r * 0.3)
        w *= np.clip((1.05 - np.abs(u)) * 4, 0, 1)
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


def skin_texture(skin_hex, out, size=1024, lips=True, brows=True, brow_hex=None, scalp=None, scalp_hex=None):
    """Flat skin tone with soft lips and brows painted on the MakeHuman body UV layout.

    scalp: optional per base-vertex weight (hair.scalp_mask) tinted towards scalp_hex, with a speckled
    edge, so the hairline reads as hair growing out of the skin rather than a layer laid on top."""
    from .blender_free import hex_rgb
    tone = np.array(hex_rgb(skin_hex))
    img = np.ones((size, size, 3), dtype=np.float32) * tone
    # subtle blotchy variation (slightly redder/darker patches) so the tone isn't a flat paint
    from .fabric import _noise
    rng = np.random.default_rng(3)
    blot = _noise((size, size), size / 40, rng) * 0.5 + _noise((size, size), size / 140, rng) * 0.5
    img = img * (1 + 0.035 * blot[..., None] * np.array([0.6, 1.0, 1.1]))
    tv, tuv = _body_uv_tris()
    if lips:
        m = _target_mask(["mouth/mouth-upperlip-volume-incr", "mouth/mouth-lowerlip-volume-incr"])
        m = np.clip((m - 0.35) / 0.4, 0, 1)
        lip = raster_scalar(tuv, m[tv], size)
        lip = _blur(lip, 2)[..., None]
        lip_col = tone * np.array([0.82, 0.55, 0.55])
        img = img * (1 - 0.75 * lip) + lip_col * 0.75 * lip
    if brows:
        m = _brow_mask()
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


def skin_detail(out_prefix, size=2048, seed=5):
    """Pore/micro-wrinkle normal map for the body UV layout. Fine surface detail breaks up specular
    highlights, which is most of what makes bare skin look like plastic."""
    from .fabric import _noise, normal_from_height
    rng = np.random.default_rng(seed)
    pores = -np.clip(_noise((size, size), 1.2, rng), 0.6, None)  # small pits
    micro = _noise((size, size), 3.0, rng, aniso=(0.4, 1.6)) * 0.35
    h = pores + micro
    n = normal_from_height(h.astype(np.float32), 0.06)
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
