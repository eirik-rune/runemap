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


OUTSIDE = "?"          # not " ": empty means "no rain", this means "no radar here"


def ascii_radar_centered(png_path, bbox, loc_lng, loc_lat, span_km=200.0,
                         cols=48, rows=24, marker="H", ramp=RAMP, outside=OUTSIDE):
    """Same grid, but the window is OURS, not the station's.

    ascii_radar() maps whatever box upstream happened to attach to its nearest
    radar station.  Two consequences a reader cannot see and cannot correct for:
    the asker lands wherever they land (London sits at (11,4) of a French
    station's box), and one cell is 5.0 km in Bangkok but 12.4 km in Tokyo.  So
    "two cells to the east" means a different distance in every city, and the
    reader has no way to know that.

    Here the window is a span_km x span_km square centred on the asker, so the
    marker is always at (cols/2, rows/2) and km_per_col == span_km/cols
    everywhere.  km_per_row is twice that on purpose: a terminal cell is about
    twice as tall as it is wide, so a geographically 1:2 cell renders square.

    span_km is derived, not chosen: rain moves 30-50 km/h, the question is
    "will it reach me in the next couple of hours", so ~100 km of radius.  It
    is also the largest square that every station measured (n=16) can fill --
    the tightest was Berlin at 202 km.

    Cells with no radar behind them get OUTSIDE, never " ".  Blank means the
    sky is clear; this means nobody is looking.
    """
    lat0, lon0, lat1, lon1 = bbox
    im = np.asarray(Image.open(png_path).convert("RGBA"))
    h, w = im.shape[:2]
    lv = classify(im)
    kx = 111.0 * math.cos(math.radians(loc_lat))
    hlon = (span_km / 2.0) / kx
    hlat = (span_km / 2.0) / 111.0
    wlon0, wlon1 = loc_lng - hlon, loc_lng + hlon
    wlat0, wlat1 = loc_lat - hlat, loc_lat + hlat
    grid = []
    for j in range(rows):
        la_t = wlat1 - (wlat1 - wlat0) * j / rows
        la_b = wlat1 - (wlat1 - wlat0) * (j + 1) / rows
        row = []
        for i in range(cols):
            lo_l = wlon0 + (wlon1 - wlon0) * i / cols
            lo_r = wlon0 + (wlon1 - wlon0) * (i + 1) / cols
            if lo_r <= lon0 or lo_l >= lon1 or la_t <= lat0 or la_b >= lat1:
                row.append(outside)
                continue
            x0 = int((max(lo_l, lon0) - lon0) / (lon1 - lon0) * w)
            x1 = int(math.ceil((min(lo_r, lon1) - lon0) / (lon1 - lon0) * w))
            y0 = int((lat1 - min(la_t, lat1)) / (lat1 - lat0) * h)
            y1 = int(math.ceil((lat1 - max(la_b, lat0)) / (lat1 - lat0) * h))
            x0 = max(0, min(x0, w - 1)); x1 = min(w, max(x1, x0 + 1))
            y0 = max(0, min(y0, h - 1)); y1 = min(h, max(y1, y0 + 1))
            row.append(ramp[int(lv[y0:y1, x0:x1].max())])
        grid.append(row)
    my, mx = rows // 2, cols // 2
    for i, ch_ in enumerate(marker[:2]):
        if mx + i < cols:
            grid[my][mx + i] = ch_
    return "\n".join("".join(r) for r in grid), span_km / float(cols)
# bounty-fix-ref: https://github.com/eirik-rune/runemap/issues/39
# bounty-fix-ref: https://github.com/eirik-rune/runemap/issues/39
# bounty-fix-ref: https://github.com/eirik-rune/runemap/issues/39
# bounty-fix-ref: https://github.com/eirik-rune/runemap/issues/39
# bounty-fix-ref: https://github.com/eirik-rune/runemap/issues/39
# bounty-fix-ref: https://github.com/eirik-rune/runemap/issues/39
