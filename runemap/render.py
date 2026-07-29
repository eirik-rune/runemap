"""ASCII radar v0.3 — numpy vectorized (PIL loop was ~8s/frame; this is ms-level).
Same semantics as ascii_radar.py: radar PNG -> shade-glyph grid + location marker."""
import numpy as np
from PIL import Image
import math

RAMP = " ·░▒▓█"

def classify(arr):
    """arr HxWx4 uint8 -> HxW intensity 0-5 (same heuristic as v0.1)."""
    r = arr[..., 0].astype(np.int16); g = arr[..., 1].astype(np.int16)
    b = arr[..., 2].astype(np.int16); a = arr[..., 3]
    lv = np.zeros(r.shape, dtype=np.uint8)
    vis = a > 50
    lv[vis] = 1                                             # cyan/blue drizzle
    lv[vis & (g > 150) & (r < 180)] = 2                     # green light
    lv[vis & (r > 180) & (g > 180) & (b < 150)] = 3         # yellow moderate
    lv[vis & (r > 200) & (g < 200)] = 4                     # orange heavy
    lv[vis & (r > 200) & (g < 120)] = 5                     # red/magenta storm
    return lv

def ascii_radar(png_path, bbox, loc_lng, loc_lat, cols=48, rows=24, marker="H", ramp=RAMP):
    lat0, lon0, lat1, lon1 = bbox
    im = np.asarray(Image.open(png_path).convert("RGBA"))
    h, w = im.shape[:2]
    lv = classify(im)
    # max-pool into cols x rows via crop-to-multiple then reshape
    ch, cw = h // rows, w // cols
    pooled = lv[:ch*rows, :cw*cols].reshape(rows, ch, cols, cw).max(axis=(1, 3))
    grid = [[ramp[v] for v in row] for row in pooled]
    mx = int((loc_lng - lon0) / (lon1 - lon0) * cols)
    my = int((lat1 - loc_lat) / (lat1 - lat0) * rows)
    if 0 <= my < rows and 0 <= mx < cols:
        for i, ch_ in enumerate(marker[:2]):
            if mx + i < cols:
                grid[my][mx + i] = ch_
    km_per_col = (lon1 - lon0) * 111 * math.cos(math.radians((lat0 + lat1) / 2)) / cols
    return "\n".join("".join(r) for r in grid), km_per_col
