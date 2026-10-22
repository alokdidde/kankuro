"""Paint a simple silk-saree texture on the sasori saree UV template (no image model):
body colour with small gold buttis, a gold zari border along the skirt hem and both pallu edges,
and a decorated pallu end. Usage: saree_texture.py MASK.png OUT.png"""
import sys

import numpy as np
from PIL import Image

mask = np.array(Image.open(sys.argv[1]).convert("L")) > 127
H, W = mask.shape
base = np.array([0x8e, 0x12, 0x3a]) / 255.0      # deep magenta silk
gold = np.array([0xd4, 0xa2, 0x3c]) / 255.0
dark = np.array([0x5a, 0x08, 0x22]) / 255.0
img = np.ones((H, W, 3)) * base
yy, xx = np.mgrid[0:H, 0:W]

rows = np.nonzero(mask.any(1))[0]
# the pallu band is the topmost separate run of masked rows
gaps = np.nonzero(np.diff(rows) > 5)[0]
p_top, p_bot = rows[0], rows[gaps[0]]           # pallu rows (image y grows downwards)
skirt = mask.copy()
skirt[:p_bot + 1] = False
pallu = mask & ~skirt

# small buttis (dots) on a staggered grid
step = W // 40
gy, gx = yy % step, (xx + (yy // step % 2) * step // 2) % step
dot = ((gy - step / 2) ** 2 + (gx - step / 2) ** 2) < (step * 0.12) ** 2
img[dot] = gold * 0.9

def band(sel, dist, width, stripes=True):
    """Gold border of `width` px where `dist` (px from the edge) < width, with thin dark lines."""
    b = sel & (dist < width)
    img[b] = gold
    if stripes:
        for d in (width * 0.15, width * 0.85):
            img[sel & (np.abs(dist - d) < max(1, width * 0.03))] = dark
    # little triangles (temple border) along the inner side
    tri = sel & (dist >= width) & (dist < width * 1.5)
    phase = (xx % (width // 2)) / (width // 2)
    img[tri & (np.abs(phase - 0.5) * width < (width * 1.5 - dist) * 0.5)] = gold

# skirt hem: distance from the bottom of each column of the skirt
col_bot = np.where(skirt.any(0), H - 1 - np.argmax(skirt[::-1], axis=0), -1)
band(skirt, col_bot[None, :] - yy, int(H * 0.035))
# pallu edges along its length
band(pallu, np.minimum(yy - p_top, p_bot - yy), int(H * 0.018))
# pallu end panel (hanging end = right end of the strip)
cols = np.nonzero(pallu.any(0))[0]
end = cols[-1]
L = int(W * 0.16)
panel = pallu & (xx > end - L)
img[panel] = dark * 0.6 + gold * 0.4
stripe = panel & (((end - xx) // (L // 8)) % 2 == 0) & (((end - xx) % (L // 8)) < L // 40)
img[stripe] = gold
pm = panel & ((((xx // 18) + (yy // 18)) % 2) == 0)
img[pm & ~stripe] = img[pm & ~stripe] * 0.85 + gold * 0.15

Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(sys.argv[2])
print("pallu rows", p_top, p_bot)
