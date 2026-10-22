"""Dhoti albedo + height from the sasori mask: cream cloth, maroon/gold border at the leg hems and
waist, soft vertical pleats down the front."""
import sys
import numpy as np
from PIL import Image

mask = np.array(Image.open(sys.argv[1]).convert("L")) > 127
out = sys.argv[2]
H, W = mask.shape
cream = np.array([238, 232, 216], float)
maroon = np.array([122, 22, 38], float)
gold = np.array([200, 150, 50], float)
img = np.tile(cream, (H, W, 1))
height = np.full((H, W), 0.5)
ys = np.arange(H)[:, None]
has = mask.any(0)
tops = np.where(has, mask.argmax(0), 0)
bots = np.where(has, H - 1 - mask[::-1].argmax(0), 0)
# the islands have small steps at their sides: take each column's hem from the lowest point nearby
# so borders run level instead of climbing the side edges
win = np.lib.stride_tricks.sliding_window_view
bots_s = win(np.pad(np.where(has, bots, 0), 30, mode="edge"), 61).max(1)
tops_s = win(np.pad(np.where(has, tops, H), 30, mode="edge"), 61).min(1)
for x in range(W):
    if not has[x]:
        continue
    top, bot = tops_s[x], bots_s[x]
    d = bot - ys[:, 0]                      # px above the hem
    img[(d >= 0) & (d < 46), x] = maroon
    img[(d >= 52) & (d < 62), x] = gold
    img[(d >= 68) & (d < 74), x] = maroon
    t = ys[:, 0] - top                      # px below the waist
    img[(t >= 0) & (t < 26), x] = maroon
    img[(t >= 26) & (t < 32), x] = gold
    height[(d >= 0) & (d < 74), x] += 0.08
img[~mask] = cream
height[~mask] = 0.5
# front pleats: soft vertical folds, strongest near the front centre, from the waist to the knee
u = np.arange(W)[None, :] / W
v = np.arange(H)[:, None] / H
front = np.clip(1 - np.abs(u - 0.25) / 0.12, 0, 1) * (u < 0.5)
down = np.clip((v - 0.05) / 0.1, 0, 1) * np.clip((0.75 - v) / 0.3, 0, 1)
height += 0.25 * np.sin(2 * np.pi * u * W / 38) * front * down
Image.fromarray(img.clip(0, 255).astype(np.uint8)).save(out + ".png")
Image.fromarray((height.clip(0, 1) * 255).astype(np.uint8)).save(out + "_height.png")
