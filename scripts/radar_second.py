"""The fallback that runs when we are about to show a stranger nothing.

It is wired at exactly one place: the line in radar_resolve() that used to
return STATE_FETCHING with no map. Everywhere else the primary upstream wins,
because it is closer, cheaper, and already warm.

Measured 8/13, paired in the same instant: mumbai and saopaulo answer
status=failed with zero frames upstream while this source carries 1665 and 998
precipitation pixels over the same coordinates. Those readers are the reason
this file exists.

Three things it must not do, each of which was a real bug first:

 · It must not draw a map with half the rain missing. The city usually sits on
   a tile seam (mumbai 0.96 across its z6 tile, london 0.98), so the tile
   rectangle comes from the span we intend to draw. See radar_rainviewer.plan.
 · It must not spend a reader's budget it does not have. A stitched frame is
   cached on disk per (sky, frame), so the fetch happens once per sky per
   frame, not once per visitor. Measured cold: 0.82-1.25s for 4-6 tiles at z7.
 · It must not take credit. Whoever's data drew the map is named in the body;
   draw() returns the source name as the last element for that purpose.
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

import radar_rainviewer as RV

NAME = "RainViewer"
ATTRIB = "RainViewer rainviewer.com"
INDEX_URL = RV.INDEX_URL
INDEX_TTL = 240.0          # the index lists a new frame every ~10 min
FRAME_MAX_AGE = 1800.0     # older than this and we would be lying about "now"
CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")
_LOCK = threading.Lock()
_INDEX = {"at": 0.0, "v": None}


def _index():
    """The frame list, refreshed at most every INDEX_TTL.

    On a refresh failure the previous list is kept and its age is what decides
    whether we may still draw: a stale index is not an error, it is an older
    frame, and the caller already refuses frames past FRAME_MAX_AGE.
    """
    now = time.time()
    with _LOCK:
        if _INDEX["v"] is not None and now - _INDEX["at"] < INDEX_TTL:
            return _INDEX["v"]
    try:
        v = json.loads(urllib.request.urlopen(INDEX_URL, timeout=8).read())
    except Exception as e:
        sys.stderr.write("SECOND-INDEX-FAILED %r\n" % (e,))
        with _LOCK:
            return _INDEX["v"]
    with _LOCK:
        _INDEX["at"], _INDEX["v"] = now, v
        return v


def newest_frame():
    idx = _index()
    if not idx:
        return None, None
    fr = RV.frames(idx)
    if not fr:
        return None, None
    ts, path = fr[-1]
    if time.time() - ts > FRAME_MAX_AGE:
        sys.stderr.write("SECOND-FRAME-TOO-OLD age=%.0fs\n" % (time.time() - ts,))
        return None, None
    return ts, path


def _cache_path(lng, lat, ts):
    key = "%s|%.1f,%.1f|%d" % (NAME, round(float(lat), 1), round(float(lng), 1), ts)
    return os.path.join(CACHE, "second-" + hashlib.sha1(key.encode()).hexdigest() + ".png")


def stitched(lng, lat, ts, path, span_km=280.0):
    """-> (png path on disk, bbox, got, wanted). Cached per sky per frame."""
    p = _cache_path(lng, lat, ts)
    xs, ys, n = RV.plan(lat, lng, span_km)
    bbox = RV.bbox_of(xs, ys, n)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p, bbox, len(xs) * len(ys), len(xs) * len(ys)
    idx = _index()
    img, bbox, got, want = RV.fetch(idx["host"], path, lat, lng, span_km=span_km)
    if not got:
        return None, bbox, 0, want
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = p + ".%d" % os.getpid()
        img.save(tmp, format="PNG")   # the temp name has no .png, so say it
        os.replace(tmp, p)          # a half-written frame must never be read
    except Exception as e:
        sys.stderr.write("SECOND-CACHE-FAILED %r\n" % (e,))
        tmp = os.path.join(tempfile.gettempdir(), "second-%d.png" % os.getpid())
        img.save(tmp, format="PNG")
        return tmp, bbox, got, want
    return p, bbox, got, want


def draw(code, lng, lat, small=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None.

    None means "we have nothing either", and the caller then says so in the
    words it already has. It never means "no radar exists here": this function
    cannot see that and must not imply it.
    """
    ts, path = newest_frame()
    if ts is None:
        return None
    p, bbox, got, want = stitched(lng, lat, ts, path)
    if not p:
        sys.stderr.write("SECOND-NO-TILES %.2f,%.2f\n" % (lng, lat))
        return None
    from render_scene import ascii_radar
    art, kmcol = ascii_radar(p, bbox, lng, lat,
                             cols=(24 if small else 48),
                             rows=(12 if small else 24), marker=code)
    if got < want:
        sys.stderr.write("SECOND-PARTIAL got=%d want=%d %.2f,%.2f\n"
                         % (got, want, lng, lat))
    return art, kmcol, float(ts), None, float(ts), NAME
