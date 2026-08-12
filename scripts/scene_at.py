#!/usr/bin/env python3
"""runemap scene at an arbitrary coordinate.

Usage:
  CAIYUN_TOKEN=xxx python3 scripts/scene_at.py --lat 18.7883 --lon 98.9853 [--lang zh] [--label chiangmai]

Prints one screen to stdout: headline + 2h rain curve + radar map + legend.
No files written, no service exposed. You bring your own caiyunapp.com token."""
import argparse, os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_scene as R

# --- radar cache: PNG bytes + images-API responses (weather stays live) ---
import hashlib, json as _json
CACHE = os.environ.get("RUNEMAP_CACHE", os.path.expanduser("~/.cache/runemap"))
os.makedirs(CACHE, exist_ok=True)
# A png entry is a timestamped, immutable object: a 14:09 frame is still that
# frame an hour later, byte for byte. A freshness TTL on it answers the wrong
# question -- "how old is this file" instead of "is this frame still useful" --
# and usefulness is already answered at render time by obs age, which is
# printed on the page. So why is 1800 still here? Because the cost of it is
# zero: measured 2026-08-03 11:42, across the 9 cities whose list the service
# could still see, 234 candidate frames, exactly 0 were on disk but past this
# TTL. Frame URLs come out of the list, so a fresh list implies fresh frames.
# The one combination this TTL can bite is "list fresh, frames old". Watch for
# it if radar_json's TTL is ever lowered, or if frames stop coming from the
# list (separate caches). Until one of those happens, leave it alone -- and do
# not file a card for it: a card gets picked up as a TODO and spends real time
# on a 0/234 problem.
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

# --- stale-while-revalidate -------------------------------------------------
# Serving a stale entry and scheduling its refresh were two halves of one job,
# and only the first half existed: a list 10 minutes old was served, over and
# over, for up to _STALE_MAX x TTL, while nothing asked upstream. The frame
# timestamps we print come from that list, so the observation time froze while
# the wall clock ran on -- measured 8/2: 19 of 24 servable lists were past TTL,
# p50 12.9min, and re-fetching moved the observation forward by 5-18 minutes.
#
# Not a shorter TTL: that trades staleness for "fetching", which is worse.
_SWR_LOCK = threading.Lock()
_SWR_INFLIGHT = set()
_SWR_BUDGET = 45.0        # background, outlives the response, like _radar_warm


def _swr_refresh(url):
    try:
        with R.net_budget.request_budget(_SWR_BUDGET):
            _cached_get(url, 20)          # writes the pool when the payload is usable
    except Exception as e:
        sys.stderr.write("SWR-REFRESH-FAILED %r\n" % (e,))
    finally:
        # finally, not end-of-happy-path: a url left in the set is a coordinate
        # that can never be refreshed again, and nothing would ever say so.
        with _SWR_LOCK:
            _SWR_INFLIGHT.discard(url)


def _swr_schedule(url, kind):
    """Refresh a past-TTL entry off the response path. Never blocks the reader."""
    if kind == "png":
        return            # timestamped immutable object: re-fetching buys nothing
    with _SWR_LOCK:
        if url in _SWR_INFLIGHT:
            return
        _SWR_INFLIGHT.add(url)
    try:
        threading.Thread(target=_swr_refresh, args=(url,), daemon=True).start()
    except Exception as e:
        with _SWR_LOCK:
            _SWR_INFLIGHT.discard(url)
        sys.stderr.write("SWR-SPAWN-FAILED %r\n" % (e,))


def _usable(kind, b):
    """A payload is cacheable only if it is actually usable. Upstream returns
    HTTP 200 with {"status":"failed"} (24 bytes) -- caching that poisons the
    entry for a whole TTL and makes a covered city report 'no coverage'."""
    if not b:
        return False
    if kind == "png":
        # Measured 8/2 12:16, bangkok: a rainless sky is a VALID 268-byte png
        # (223x217, colortype 6, one distinct byte after inflate -- fully
        # transparent). The old `len(b) > 512` read that as garbage, so the
        # frame was fetched, judged unusable, never stored; _peek missed for
        # ever and the sky sat in "fetching -- ask again in ~60s" permanently.
        # Every dry sky, not one city. Size was standing in for validity: the
        # emptier the sky the smaller the file, so the test was strictest on
        # exactly the answer it should have accepted. Judge the container.
        return b[:8] == b"\x89PNG\r\n\x1a\n" and b[-8:-4] == b"IEND"
    try:
        j = _json.loads(b)
    except Exception:
        return False
    if j.get("status") != "ok":
        return False
    if kind == "radar_json" and not j.get("images"):
        return False
    return True

def _ckey(url):
    """The key must name the CONTENT, not the signature.

    Frame urls carry auth_key=<epoch>-<hash>, re-signed on every request, so
    sha1(full url) rotated the entire keyspace each time the images API was
    refreshed: the 1800s png TTL was never reachable and every request paid a
    full download. Measured 2026-08-01 on 6 pairs of cached json snapshots
    299s-2699s apart: for the same frame timestamp the path is byte-identical
    (88/88 frames), so the in-path hash is content-addressed and auth_key is
    the only volatile part. Strip only that -- other params (hourlysteps, the
    weather token in the path) are part of the identity of what was asked.
    """
    head, sep, q = url.partition("?")
    if not sep:
        return url
    keep = [kv for kv in q.split("&") if not kv.startswith("auth_key=")]
    return head + ("?" + "&".join(keep) if keep else "")

def _cached_get(url, timeout=15):
    kind = "png" if ".png" in url else ("radar_json" if "/radar/" in url else "weather")
    key = os.path.join(CACHE, hashlib.sha1(_ckey(url).encode()).hexdigest() + "." + kind)
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

    Never BLOCKS on the network -- which is not the same as never touching it,
    and the older wording here said the stronger, false thing: "there is no
    socket on this code path at all". A call graph computed 2026-08-12 11:30
    finds one, four hops out:
        _cached_peek -> _swr_schedule -> _swr_refresh -> _cached_get -> _orig_get
    i.e. a past-TTL entry is served immediately AND a refresh is spawned. That
    is the design, but any caller who needs provable silence (an offline audit
    over many coordinates, say) must stub _swr_schedule and verify it by
    blocking socket.socket -- reading this docstring is not verification.

    What IS structural: the reader never waits on that refresh. A miss is not
    an error, it is state 2 (fetching), and a background thread turns it into
    a hit.

    Staleness: accepted up to _STALE_MAX x TTL, the same window _cached_get
    already serves from when upstream is sick. Slightly old rain beats no rain,
    and the frame carries its own timestamp so nobody is misled about its age.
    """
    kind = "png" if ".png" in url else ("radar_json" if "/radar/" in url else "weather")
    key = os.path.join(CACHE, hashlib.sha1(_ckey(url).encode()).hexdigest() + "." + kind)
    try:
        age = time.time() - os.path.getmtime(key)
    except OSError:
        R.note_peek_miss("nofile")        # never stored: we have not looked yet
        return None
    if age >= _TTL[kind] * _STALE_MAX:
        R.note_peek_miss("toostale")      # we looked, long ago, and gave up on it
        return None
    if age >= _TTL[kind]:
        _swr_schedule(url, kind)      # serve it AND ask for a fresh one
    try:
        b = open(key, "rb").read()
    except OSError:
        R.note_peek_miss("unreadable")    # on disk but the read failed
        return None
    if not _usable(kind, b):
        R.note_peek_miss("unusable")      # bytes present, judged not a frame
        return None
    R.note_peek_miss(None)                # a hit must not leave a stale word behind
    return b


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
    import wall as _wall
    budget = _wall.WALL             # the CLI measures the service, so it must
                                    # read the same wall the service does
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
