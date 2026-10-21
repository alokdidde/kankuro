"""Strand textures for hair cards (numpy + PIL, no Blender).

An atlas is a square RGBA image split into `columns` vertical strips. Each strip is one card variant:
strands run top (root, v=1) to bottom (tip, v=0), alpha is strand coverage, so a card reads as a clump
of separate hairs instead of a solid sheet. Cards pick a strip with their U range."""
import numpy as np
from PIL import Image

from .blender_free import hex_rgb

COLUMNS = 4


def _strand_layer(h, w, rng, n, width_px, wave, taper_from, clumps=3):
    """Coverage (h, w) and per-pixel strand brightness for n strands in a w-wide strip.

    Strands are gathered into `clumps` locks that narrow to a point towards the tip, with gaps between
    them, so a card reads as separate locks of hair rather than a flat band."""
    cov = np.zeros((h, w), np.float32)
    shade = np.zeros((h, w), np.float32)
    t = np.arange(h, dtype=np.float32) / (h - 1)  # 0 at the root (top row) .. 1 at the tip
    xs = np.arange(w, dtype=np.float32)[None, :]
    if clumps <= 1:
        centres, spreads = [w / 2], [w * 0.04]
    else:
        centres = (np.arange(clumps) + 0.5 + rng.uniform(-0.15, 0.15, clumps)) * w / clumps
        spreads = rng.uniform(0.07, 0.11, clumps) * w
    lock_shade = rng.uniform(0.75, 1.2, len(centres))
    for k in range(n):
        c = int(rng.integers(len(centres)))
        xc, sp = centres[c], spreads[c]
        x0 = xc + rng.normal(0, sp)
        tip_x = xc + (x0 - xc) * rng.uniform(0.1, 0.4)  # locks narrow towards the tip
        ph, fr = rng.uniform(0, 6.28), rng.uniform(1.0, 2.5)
        x = x0 + (tip_x - x0) * t ** 1.2 + wave * w * np.sin(ph + fr * 6.28 * t) * t
        x = np.clip(x, 1, w - 2)
        end = rng.uniform(taper_from, 1.0)  # strands stop at different lengths
        wid = width_px * rng.uniform(0.7, 1.3) * np.clip((end - t) / max(end * 0.3, 1e-3), 0, 1) ** 0.6
        a = np.clip(1.0 - np.abs(xs - x[:, None]) / np.maximum(wid[:, None], 0.35), 0, 1)
        a *= (t < end)[:, None] * rng.uniform(0.8, 1.0)
        b = lock_shade[c] * rng.uniform(0.75, 1.25)
        over = a > cov
        shade = np.where(over, b, shade)
        cov = np.maximum(cov, a)
    return cov, shade


def strand_atlas(color, out, size=1024, columns=COLUMNS, strands=120, width_px=3.0, wave=0.02,
                 taper_from=0.5, seed=11, root_dark=0.85, clumps=3, root_fade=0.15):
    """Write an RGBA strand atlas tinted with `color` (hex). Returns the path."""
    rng = np.random.default_rng(seed)
    base = np.array(hex_rgb(color), np.float32)
    w = size // columns
    rgba = np.zeros((size, size, 4), np.float32)
    t = np.linspace(0, 1, size, dtype=np.float32)[:, None]
    for c in range(columns):
        cov, shade = _strand_layer(size, w, rng, strands, width_px, wave, taper_from, clumps)
        # darker towards the root (shadowed by the hair above it), a little lighter at the tips
        tone = (root_dark + (1 - root_dark) * np.clip(t * 1.6, 0, 1)) * (0.92 + 0.16 * t)
        # coarse light/dark streaks across the strip: individual hairs are sub-pixel at normal viewing
        # distance, so the strand direction has to come from streaks a few hairs wide
        streak = np.convolve(rng.normal(0, 1, w + 16), np.ones(9) / 9, mode="same")[8:-8]
        streak = 1 + 0.35 * streak / (np.abs(streak).max() + 1e-6)
        col = base[None, None, :] * (shade * tone * streak[None, :])[..., None]
        # very dark hair still needs some value range or the strands vanish into a flat black
        col = np.maximum(col, (0.05 * shade * tone)[..., None])
        rgba[:, c * w:(c + 1) * w, :3] = col
        # fade in at the root so a card's top edge melts into the layer under it
        fade = np.clip(t / root_fade, 0, 1) ** 2 if root_fade else 1.0
        rgba[:, c * w:(c + 1) * w, 3] = cov * fade
    # bleed colour into transparent pixels so mipmaps/filtering don't pull in black fringes
    a = rgba[..., 3:4]
    mean = (rgba[..., :3] * a).sum((0, 1)) / max(a.sum(), 1e-6)
    rgba[..., :3] = np.where(a < 1e-3, mean, rgba[..., :3])
    Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA").save(out)
    return out


def brow_atlas(color, out, size=512, seed=23):
    """Brow hairs: a few fine, slightly curved strands per strip, tapering to sharp tips."""
    return strand_atlas(color, out, size=size, strands=1, width_px=size / COLUMNS * 0.42, wave=0.03,
                        taper_from=0.85, seed=seed, root_dark=0.85, clumps=1,
                        root_fade=0.0)


def base_texture(color, out, size=1024, seed=7):
    """Opaque layer under the cards: fine streaks, darker than the hair so gaps read as depth."""
    rng = np.random.default_rng(seed)
    cols = rng.normal(0, 1, size)
    cols = np.convolve(cols, [0.25, 0.5, 0.25], mode="same")
    cols = (cols - cols.min()) / (np.ptp(cols) + 1e-9)
    img = 0.6 + 0.45 * cols[None, :] + rng.random((size, size)) * 0.1
    rgb = np.clip(img, 0, 1)[..., None] * np.array(hex_rgb(color))[None, None, :]
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(out)
    return out


def stubble_texture(color, out, size=1024, seed=5):
    """Buzz cut: dense short dashes over a darker scalp tone (no cards; the hair is too short for them)."""
    rng = np.random.default_rng(seed)
    base = np.array(hex_rgb(color), np.float32)
    img = np.full((size, size), 0.55, np.float32)
    n = size * 60
    xs, ys = rng.integers(0, size, n), rng.integers(0, size, n)
    ln = rng.integers(2, 6, n)
    val = rng.uniform(0.7, 1.15, n)
    for k in range(6):
        m = ln > k
        img[(ys[m] + k) % size, xs[m]] = val[m]
    rgb = img[..., None] * base[None, None, :]
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(out)
    return out
