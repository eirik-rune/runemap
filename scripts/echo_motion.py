"""Echo motion via brute-force cross-correlation (degenerate TREC).
Median displacement over ~3 frame pairs spanning the last hour -> global
motion vector. Gates: corr > 0.35, speed >= 5 km/h (below = quasi-stationary).
Zero deps beyond numpy/PIL (already required by runemap.render)."""
import math, os, sys, tempfile, urllib.request
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runemap.render import classify

ARROWS = {0: ">", 45: "NE", 90: "^"}  # placeholder, real table below
ARROW8 = {0: "\u2192", 45: "\u2197", 90: "\u2191", 135: "\u2196",
          180: "\u2190", 225: "\u2199", 270: "\u2193", 315: "\u2198"}
COMPASS8 = {0: "E", 45: "NE", 90: "N", 135: "NW",
            180: "W", 225: "SW", 270: "S", 315: "SE"}
CN8 = {"E": "\u5411\u4e1c", "NE": "\u5411\u4e1c\u5317", "N": "\u5411\u5317",
       "NW": "\u5411\u897f\u5317", "W": "\u5411\u897f", "SW": "\u5411\u897f\u5357",
       "S": "\u5411\u5357", "SE": "\u5411\u4e1c\u5357"}

def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "runemap/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _load_lv(url):
    png = _get(url)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png); p = f.name
    try:
        return classify(np.asarray(Image.open(p).convert("RGBA"))).astype(np.float32)
    finally:
        os.unlink(p)

def _pool(a, k):
    h, w = a.shape
    return a[:h//k*k, :w//k*k].reshape(h//k, k, w//k, k).mean(axis=(1, 3))

def _shift_corr(a, b, max_s=15):
    best = (0, 0, -2.0)
    for dy in range(-max_s, max_s + 1):
        for dx in range(-max_s, max_s + 1):
            ay0, ay1 = max(0, -dy), a.shape[0] - max(0, dy)
            ax0, ax1 = max(0, -dx), a.shape[1] - max(0, dx)
            sa = a[ay0:ay1, ax0:ax1]
            sb = b[max(0, dy):max(0, dy)+sa.shape[0], max(0, dx):max(0, dx)+sa.shape[1]]
            if sa.size < 100:
                continue
            va, vb = sa - sa.mean(), sb - sb.mean()
            den = math.sqrt(float((va*va).sum()) * float((vb*vb).sum()))
            if den < 1e-6:
                continue
            c = float((va*vb).sum() / den)
            if c > best[2]:
                best = (dx, dy, c)
    return best

def echo_motion(frames, pool_k=4, min_corr=0.35, min_speed=5.0):
    """frames: list of (url, ts, bbox) obs frames (bbox=[lat0,lon0,lat1,lon1]).
    Returns dict {kind: 'moving'|'stationary'|None, arrow, dir_en, dir_cn, kmh}."""
    frames = [f for f in frames if len(f) >= 3 and f[2]]
    if len(frames) < 4:
        return {"kind": None}
    frames = sorted(frames, key=lambda f: f[1])
    bbox = frames[-1][2]
    lat0, lon0, lat1, lon1 = bbox
    now = frames[-1][1]
    nearest = lambda t: min(frames, key=lambda f: abs(f[1] - t))
    pairs, seen = [], set()
    for b0, b1 in [(3600, 1800), (2700, 900), (1800, 0)]:
        fa, fb = nearest(now - b0), nearest(now - b1)
        key = (fa[0], fb[0])
        if fb[1] - fa[1] >= 600 and key not in seen:
            seen.add(key); pairs.append((fa, fb))
    if not pairs:
        return {"kind": None}
    cache = {}
    def lv(f):
        if f[0] not in cache:
            cache[f[0]] = _load_lv(f[0])
        return cache[f[0]]
    good = []
    for fa, fb in pairs:
        try:
            a, b = _pool(lv(fa), pool_k), _pool(lv(fb), pool_k)
        except Exception:
            continue
        if float((a > 0.1).mean()) < 0.01:
            continue
        dx, dy, c = _shift_corr(a, b)
        if c > min_corr:
            good.append((dx, dy, c, fb[1] - fa[1]))
    if not good:
        return {"kind": None}
    h, w = next(iter(cache.values())).shape
    km_x = (lon1 - lon0) * 111 * math.cos(math.radians((lat0 + lat1) / 2)) / (w / pool_k)
    km_y = (lat1 - lat0) * 111 / (h / pool_k)
    vx = float(np.median([g[0] / g[3] for g in good])) * km_x * 3600
    vy = float(np.median([g[1] / g[3] for g in good])) * km_y * 3600
    speed = math.hypot(vx, vy)
    if speed < min_speed:
        return {"kind": "stationary", "kmh": speed}
    ang = (math.degrees(math.atan2(-vy, vx)) + 360) % 360
    a8 = min(ARROW8, key=lambda k: min(abs(ang - k), 360 - abs(ang - k)))
    d = COMPASS8[a8]
    return {"kind": "moving", "arrow": ARROW8[a8], "dir_en": d,
            "dir_cn": CN8[d], "kmh": speed}
