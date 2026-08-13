"""Pair a radar composite against NOAA GOES rain rate on OUR grid, not theirs.

Both sides are third-party archives, so this back-samples the last two hours
instead of waiting for them: GOES granules sit in S3 and the RainViewer index
carries ~2h of past frames, which is n=13 the moment you run it. Nothing here
touches our own cache, so measuring does not change what a real reader sees --
the mistake of 8/03, where a probe manufactured the verdict it then found.

Scope, stated so the numbers cannot grow a bigger claim than they carry: the
two products are different (radar echo vs satellite-derived rain rate), so this
answers only "when the radar says rain, does the satellite light up too". It
does not say which one is right.

Before believing a low hit rate, check the ruler: the reprojection round-trips
the full-disk maximum back to the same pixel, offset (0,0). A geometry bug and
a blind sensor produce the same number.
"""
import json, sys, math, io, urllib.request, re
import numpy as np, h5py
from PIL import Image
import os
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _R); sys.path.insert(0, os.path.join(_R, "scripts"))
from runemap.render import classify
import radar_rainviewer as RV
COLS, ROWS = 24, 12
LAT, LON = -23.55, -46.63
BB = None
def rv_grid(host, path):
    im, bb, got, want = RV.fetch(host, path, LAT, LON)
    a = np.asarray(im.convert("RGBA")); lv = classify(a)
    h, w = lv.shape; ch, cw = h // ROWS, w // COLS
    return lv[:ch*ROWS, :cw*COLS].reshape(ROWS, ch, COLS, cw).max(axis=(1, 3)), bb
def goes_grid(nc, bb):
    f = h5py.File(io.BytesIO(nc), "r")
    xa, ya = f["x"], f["y"]
    xs = xa[:] * xa.attrs["scale_factor"][0] + xa.attrs["add_offset"][0]
    ys = ya[:] * ya.attrs["scale_factor"][0] + ya.attrs["add_offset"][0]
    p = f["goes_imager_projection"].attrs
    lon0 = float(p["longitude_of_projection_origin"][0])
    H = float(p["perspective_point_height"][0]) + float(p["semi_major_axis"][0])
    req = float(p["semi_major_axis"][0]); rpol = float(p["semi_minor_axis"][0])
    v = f["RRQPE"]; sf = v.attrs["scale_factor"][0]; fill = v.attrs["_FillValue"][0]
    e2 = 1 - rpol**2 / req**2
    s, w_, n, e = bb
    g = np.zeros((ROWS, COLS))
    for j in range(ROWS):
        for i in range(COLS):
            la = math.radians(n - (j+0.5)*(n-s)/ROWS); lo = math.radians(w_ + (i+0.5)*(e-w_)/COLS)
            latc = math.atan((rpol**2/req**2)*math.tan(la)); rc = rpol/math.sqrt(1-e2*math.cos(latc)**2)
            sx = H - rc*math.cos(latc)*math.cos(lo-math.radians(lon0))
            sy = -rc*math.cos(latc)*math.sin(lo-math.radians(lon0)); sz = rc*math.sin(latc)
            if H*(H-sx) < sy**2 + (req**2/rpol**2)*sz**2: g[j,i] = np.nan; continue
            gx = math.asin(-sy/math.sqrt(sx*sx+sy*sy+sz*sz)); gy = math.atan(sz/sx)
            raw = v[int(np.abs(ys-gy).argmin()), int(np.abs(xs-gx).argmin())]
            g[j,i] = np.nan if raw == fill else raw*sf
    return g
idx = json.load(urllib.request.urlopen("https://api.rainviewer.com/public/weather-maps.json", timeout=20))
host = idx["host"]
import time as _t
_now = _t.gmtime()
_prefix = "ABI-L2-RRQPEF/%04d/%03d/%02d" % (_now.tm_year, _now.tm_yday, _now.tm_hour)
# hour-scoped prefix plus the previous hour: two hours of granules, which is
# what the RainViewer past window can be paired against
_prev = _t.gmtime(_t.mktime(_now) - 3600) if False else None
lst = ""
for _h in (max(0, _now.tm_hour - 1), _now.tm_hour):
    _p = "ABI-L2-RRQPEF/%04d/%03d/%02d" % (_now.tm_year, _now.tm_yday, _h)
    lst += urllib.request.urlopen(
        "https://noaa-goes19.s3.amazonaws.com/?list-type=2&prefix=%s&max-keys=200" % _p,
        timeout=30).read().decode()
keys = re.findall(r"<Key>([^<]+)</Key>", lst)
def gstart(k):
    """Granule start from the filename. The name is the only timestamp that is
    the same in the key and in the file, so it is what the pairing keys on."""
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", k)
    import calendar, time
    y, doy, hh, mm, ss = map(int, m.groups())
    return calendar.timegm(time.strptime("%d %d %d %d %d" % (y, doy, hh, mm, ss),
                                         "%Y %j %H %M %S"))
gk = sorted(((gstart(k), k) for k in keys))
print("GOES 归档 %d 个 granule；RainViewer past %d 帧" % (len(gk), len(idx["radar"]["past"])))
rows = []
for fr in idx["radar"]["past"]:
    t = fr["time"]
    cand = [(abs(ts - t), ts, k) for ts, k in gk if abs(ts - t) <= 600]
    if not cand: continue
    _, ts, k = min(cand)
    rg, bb = rv_grid(host, fr["path"])
    nc = urllib.request.urlopen("https://noaa-goes19.s3.amazonaws.com/" + k, timeout=60).read()
    gg = goes_grid(nc, bb)
    rw = rg > 0; gw = np.nan_to_num(gg) > 0
    rows.append((t, ts, int(rw.sum()), int(gw.sum()), int((rw & gw).sum()), float(np.nanmax(gg))))
    print("  雷达 %2d 格 | 卫星 %2d 格 | 都说有 %2d | 卫星峰值 %.2f mm/h  (Δt=%+ds)"
          % (rows[-1][2], rows[-1][3], rows[-1][4], rows[-1][5], ts - t))
R = sum(r[2] for r in rows); G = sum(r[3] for r in rows); B = sum(r[4] for r in rows)
print("n=%d 次配对 ｜ 雷达有雨格合计 %d ｜ 其中卫星也说有 %d ⇒ 命中 %.0f%% ｜ 卫星独有 %d"
      % (len(rows), R, B, 100.0*B/R if R else -1, G-B))
