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

def _cached_get(url, timeout=15):
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
        # Unique temp per writer: the fixed key+".part" name raced when two
        # threads fetched the same URL (motion thread overlapping the map
        # fetch after the 18:51 parallelization) -- one os.replace won, the
        # other crashed FileNotFoundError and the request 502d.
        import tempfile as _tf
        _fd, _tmpu = _tf.mkstemp(prefix=os.path.basename(key) + ".", suffix=".part", dir=os.path.dirname(key))
        with os.fdopen(_fd, "wb") as _f:
            _f.write(b)
        os.replace(_tmpu, key)
        return b
    # bad payload: never poison the cache; last good beats nothing
    if have and age < _TTL[kind] * _STALE_MAX:
        return open(key, "rb").read()
    return b

def _cached_peek(url):
    """Cache-only read: bytes if the disk pool can answer, else None.

    Never touches the network. This is what lets the user path be structurally
    incapable of waiting on an upstream -- not "we set a short timeout", but
    "there is no socket on this code path at all". A miss is not an error, it
    is state 2 (fetching), and a background thread turns it into a hit.

    Staleness: accepted up to _STALE_MAX x TTL, the same window _cached_get
    already serves from when upstream is sick. Slightly old rain beats no rain,
    and the frame carries its own timestamp so nobody is misled about its age.
    """
    kind = "png" if ".png" in url else ("radar_json" if "/radar/" in url else "weather")
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + "." + kind)
    try:
        age = time.time() - os.path.getmtime(key)
    except OSError:
        return None
    if age >= _TTL[kind] * _STALE_MAX:
        return None
    try:
        b = open(key, "rb").read()
    except OSError:
        return None
    return b if _usable(kind, b) else None


R._get = _cached_get
R._peek = _cached_peek     # cache-only reader, see render_scene._peek


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

    import net_budget
    budget = float(os.environ.get("RUNEMAP_SCENE_BUDGET", "3"))
    # One resolution path, not two. This used to call radar_art directly, so the
    # CLI and the service could disagree about what state a sky was in -- and the
    # CLI is the tool anyone reaches for to check what the service is doing.
    # An instrument that does not share the code path it measures will eventually
    # tell you the system is fine while it is not.
    with net_budget.request_budget(budget):     # same ceiling as the service
        wx = R.weather(a.lon, a.lat, token, "en_US" if a.lang == "en" else "zh_CN")
        state, rb = R.radar_resolve(code, a.lon, a.lat, token)
    sys.stdout.write(R.build(a.lang, label, code, label, a.lon, a.lat, tzh, wx, rb,
                             radar_state=state))
    if state != R.STATE_OK:
        # The background warm outlives this process only if we let it finish.
        # A CLI that exits the instant it prints "fetching" never warms anything,
        # so the second run would be just as cold -- and the promise "ask again"
        # would be false here in exactly the way it is false in the service.
        R.drain_warms(timeout=float(os.environ.get("RUNEMAP_CLI_WARM_WAIT", "60")))


if __name__ == "__main__":
    main()
