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
_TTL = {"radar_json": 300, "png": 1800, "weather": 300}   # radar refreshes ~6min; png urls are timestamped
_orig_get = R._get

import datetime
MAX_CALLS = int(os.environ.get("RUNEMAP_MAX_CALLS", "1000"))

def _track_outbound():
    today = datetime.date.today().isoformat()
    usage_file = os.path.join(CACHE, f"usage_{today}.txt")
    try:
        calls = int(open(usage_file).read().strip())
    except Exception:
        calls = 0
    if calls >= MAX_CALLS:
        raise RuntimeError(f"Circuit breaker tripped: {MAX_CALLS} API calls reached today")
    open(usage_file, "w").write(str(calls + 1))

_STALE_MAX = 6          # serve a stale-but-good entry up to 6x TTL when upstream is sick

def _usable(kind, b):
    """A payload is cacheable only if it is actually usable. Upstream returns
    HTTP 200 with {"status":"failed"} (24 bytes) -- caching that poisons the
    entry for a whole TTL and makes a covered city report 'no coverage'."""
    if not b:
        return False
    if kind == "png":
        return len(b) > 512
    try:
        j = _json.loads(b)
    except Exception:
        return False
    if j.get("status") != "ok":
        return False
    if kind == "radar_json" and not j.get("images"):
        return False
    return True

def _cached_get(url, timeout=None):
    kind = "png" if ".png" in url else ("radar_json" if "/radar/" in url else "weather")
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + "." + kind)
    have = os.path.exists(key)
    age = (time.time() - os.path.getmtime(key)) if have else None
    if have and age < _TTL[kind]:
        return open(key, "rb").read()
    _track_outbound()
    try:
        b = _orig_get(url, timeout)
    except Exception:
        if have and age < _TTL[kind] * _STALE_MAX:
            return open(key, "rb").read()
        raise
    if _usable(kind, b):
        tmp = key + ".part"
        open(tmp, "wb").write(b); os.replace(tmp, key)
        return b
    # bad payload: never poison the cache; last good beats nothing
    if have and age < _TTL[kind] * _STALE_MAX:
        return open(key, "rb").read()
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
