"""How cloudy is the sky over a point, observed: Himawari-9's own cloud mask.

The product is JMA's operational L2 cloud mask (AHI-L2-FLDK-Clouds, CloudMask:
0 clear, 1 probably clear, 2 probably cloudy, 3 cloudy; 2 km; every 10 min),
distributed by NOAA Open Data (bucket noaa-himawari9). Free to use including
commercially; attribution required; no implied endorsement. ATTRIB below is
the line the pages print whenever an answer used it.

A feeder outside the request path (Qianlu's cmsk_feed.py, run where memory is
plentiful) keeps the last frames here as raw 5500x5500 one-byte files named
cmsk_<YYYYmmddTHHMMZ>.u8. This module only reads them: mmap, stdlib, ~10 ms a
point. Ported from her sat_cmsk.py; the projection was checked by her against
the file's own lat/lon arrays (<= 0.03 deg at 39 airports).

Anything wrong -- no file, frame older than MAX_AGE, point off the disk or at
its edge, half the box invalid -- returns (None, None), and the caller falls
back to what it did before this existed. A missing observation must never be
read as a clear sky.
"""
import glob
import math
import mmap
import os
import threading
from datetime import datetime, timedelta, timezone

N = 5500
DIR = os.environ.get("RUNEMAP_CMSK_DIR", "/srv/notes/skyfix/cmsk")
# A frame is in use until the next one lands. NOAA posts a frame 22-28 min
# after its start (cmsk/feed.log, 11-11), the feed looks every 5 min and frames
# are 10 min apart, so the one in use is up to ~43 min old -- and Himawari
# takes no full-disk scan at 02:40 and 14:40 UTC (housekeeping; the bucket has
# no CMSK for those slots), which adds 10: up to ~53. The first value, 45, would
# have dropped Shenzhen from clear to partly cloudy around 11:15 Beijing time
# every day until the 02:50 frame arrived (Qianlu's catch). The watchdog
# (ops/cmsk_watch.sh) reads this number, so it rings when the reader gives up.
MAX_AGE = timedelta(minutes=60)
HALF = 5                                   # 11x11 pixels, about 22 km
ATTRIB = {
    "en": "cloud mask: Himawari-9 (JMA) via NOAA Open Data",
    "zh": "云检测: 向日葵9号 (JMA), 经 NOAA Open Data 分发",
    "ja": "雲検出: ひまわり9号 (JMA), NOAA Open Data 経由",
}

_lock = threading.Lock()
_open = {}                                 # path -> (file, mmap, frame time)


def _px(lon, lat, n=N, sub=140.7):
    """lon/lat -> (column, row) on the full-disk 2 km grid, or None off-disk."""
    a, b, h = 6378.137, 6356.7523, 42164.0
    lam, phi = math.radians(lon - sub), math.radians(lat)
    cl = math.atan((b * b) / (a * a) * math.tan(phi))
    rl = b / math.sqrt(1 - (a * a - b * b) / (a * a) * math.cos(cl) ** 2)
    r1 = h - rl * math.cos(cl) * math.cos(lam)
    r2 = -rl * math.cos(cl) * math.sin(lam)
    r3 = rl * math.sin(cl)
    if r1 * (r1 - h) + r2 * r2 + r3 * r3 * (a * a) / (b * b) > 0:
        return None                        # the far side of the disk
    k = 40932549 / 65536 * (n / 11000)
    rn = math.sqrt(r1 * r1 + r2 * r2 + r3 * r3)
    return (n / 2 + math.degrees(math.atan(-r2 / r1)) * k,
            n / 2 + math.degrees(math.asin(-r3 / rn)) * k)


def _frame(path):
    if path not in _open:
        for f, mm, _ in _open.values():
            mm.close(); f.close()
        _open.clear()
        f = open(path, "rb")
        try:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            f.close(); raise
        if len(mm) != N * N:
            mm.close(); f.close()
            return None
        t = datetime.strptime(os.path.basename(path)[5:19], "%Y%m%dT%H%MZ").replace(tzinfo=timezone.utc)
        _open[path] = (f, mm, t)
    return _open[path][1:]


def cloud_fraction(lon, lat, now=None, d=None):
    """(share of cloudy pixels around the point, frame time) or (None, None)."""
    try:
        lon, lat = float(lon), float(lat)
        if lon < 0:
            lon += 360
        if not 80 <= lon <= 200 or abs(lat) > 60:
            return None, None
        files = sorted(glob.glob(os.path.join(d or DIR, "cmsk_*.u8")))
        if not files:
            return None, None
        with _lock:
            fr = _frame(files[-1])
            if fr is None:
                return None, None
            mm, t = fr
            if (now or datetime.now(timezone.utc)) - t > MAX_AGE:
                return None, None
            p = _px(lon, lat)
            if p is None:
                return None, None
            c, r = int(round(p[0] - .5)), int(round(p[1] - .5))
            if not (HALF <= c < N - HALF and HALF <= r < N - HALF):
                return None, None
            ok = cloudy = 0
            for rr in range(r - HALF, r + HALF + 1):
                for v in mm[rr * N + c - HALF: rr * N + c + HALF + 1]:
                    if v <= 3:
                        ok += 1
                        cloudy += v >= 2
        if ok < (2 * HALF + 1) ** 2 / 2:
            return None, None
        return cloudy / ok, t
    except Exception:
        return None, None
