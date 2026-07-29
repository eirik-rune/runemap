#!/usr/bin/env python3
"""runemap scene at an arbitrary coordinate.

Usage:
  CAIYUN_TOKEN=xxx python3 scripts/scene_at.py --lat 18.7883 --lon 98.9853 [--lang zh] [--label chiangmai]

Prints one screen to stdout: headline + 2h rain curve + radar map + legend.
No files written, no service exposed. You bring your own caiyunapp.com token."""
import argparse, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_scene as R

# --- radar cache: PNG bytes + images-API responses (weather stays live) ---
import hashlib, json as _json
CACHE = os.environ.get("RUNEMAP_CACHE", os.path.expanduser("~/.cache/runemap"))
os.makedirs(CACHE, exist_ok=True)
_TTL = {"radar_json": 300, "png": 1800}   # radar refreshes ~6min; png urls are timestamped
_orig_get = R._get

def _cached_get(url, timeout=15):
    kind = "png" if ".png" in url else ("radar_json" if "/radar/" in url else None)
    if kind is None:
        return _orig_get(url, timeout)            # weather: always live
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + "." + kind)
    if os.path.exists(key) and time.time() - os.path.getmtime(key) < _TTL[kind]:
        return open(key, "rb").read()
    b = _orig_get(url, timeout)
    tmp = key + ".part"
    open(tmp, "wb").write(b); os.replace(tmp, key)
    return b

R._get = _cached_get


def main():
    ap = argparse.ArgumentParser(prog="scene_at")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--lang", default="en", choices=["en", "zh"])
    ap.add_argument("--label", default=None, help="name shown in headline (default: the coordinate)")
    ap.add_argument("--tz", type=float, default=None, help="local UTC offset in hours (default: lon/15)")
    ap.add_argument("--code", default="><", help="2-char marker drawn at the point on the radar map")
    a = ap.parse_args()

    token = os.environ.get("CAIYUN_TOKEN")
    if not token:
        sys.exit("CAIYUN_TOKEN missing (get one at dashboard.caiyunapp.com)")

    label = a.label or ("%.4f,%.4f" % (a.lon, a.lat))
    tzh = a.tz if a.tz is not None else round(a.lon / 15.0)
    code = (a.code + "><")[:2]

    wx = R.weather(a.lon, a.lat, token, "en_US" if a.lang == "en" else "zh_CN")
    rb = R.radar_art(code, a.lon, a.lat, token)
    sys.stdout.write(R.build(a.lang, label, code, label, a.lon, a.lat, tzh, wx, rb))


if __name__ == "__main__":
    main()
