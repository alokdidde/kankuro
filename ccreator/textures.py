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


def skin_texture(skin_hex, out, size=1024, lips=True, brows=True, brow_hex=None):
    """Flat skin tone with soft lips and brows painted on the MakeHuman body UV layout."""
    from .blender_free import hex_rgb
    tone = np.array(hex_rgb(skin_hex))
    img = np.ones((size, size, 3), dtype=np.float32) * tone
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
        br = _blur(br, 1)[..., None]
        bc = np.array(hex_rgb(brow_hex)) if brow_hex else tone * 0.35
        img = img * (1 - 0.85 * br) + bc * 0.85 * br
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(out)
    return out


def uv_template(polys_uv, out, title, size=2048, labels=(("FRONT", 0.25), ("BACK", 0.75)), mask_out=None):
    """Draw a UV template sheet: garment area filled light grey, wireframe, panel labels.

    polys_uv: list of polygons, each a list of (u, v). Returns paths."""
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
    for text, u in labels:
        w = dr.textlength(text, font=f)
        dr.text((u * size - w / 2, size * 0.012), text, fill=(40, 40, 60), font=f)
    dr.text((size * 0.01, size - size // 22), title, fill=(90, 90, 110), font=_font(size // 45))
    dr.line([(size / 2, 0), (size / 2, size)], fill=(200, 80, 80), width=2)
    im.save(out)
    if mask_out:
        mask.save(mask_out)
    return out
