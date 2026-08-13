"""Japan, from JMA's nowcast tiles, on a scale we derived instead of typing.

Licence: JMA content is under the Public Data Usage Terms v1.0 unless marked
otherwise -- attribution required, modified content must be labelled as
modified, and must not be presented as official government material. We print
the source and the change notice, and we do not claim to be them.

One rule from their side that shapes the code: the product is a NOWCAST, and
the Meteorological Business Act regulates forecasting. So only frames where
`validtime == basetime` are used -- the observed step. That is also the only
thing runemap claims to show, so the constraint and the promise agree.

The colour scale is the interesting part. JMA publishes eight discrete colours
and, as far as I could find, no machine-readable mapping from colour to rain
rate: not in the tile bundle, not in contents.json, nowhere I could reach. The
KNMI row in radar_wms.py is refused for exactly that reason, and typing
thresholds from memory here would have made that refusal decoration.

But our grid does not need rain rates. It needs an ORDER, and an order is
derivable from the pictures themselves (`ops/colour_order.py`):

  depth      heavier cores sit further inside the precipitation region.
             Measured over 192 tiles: 1.89 / 4.03 / 5.52 / 5.53 / 5.73 / 6.34
             / 7.18 / 9.90 mean erosion depth, in the order below.
  adjacency  a scale is a gradient, so each class borders its neighbours in the
             scale more than anything distant. Every one of the eight does.

Depth alone would not have earned the middle of the scale -- two of those gaps
are 0.014 and 0.203, which is not a separation. Adjacency is what settles it,
and the check is real rather than decorative: swapping either fragile pair
makes the adjacency test REFUSE (measured, both swaps, 2 of 8 classes each).

So the eight are ordered, and the five levels below are a stated bucketing of
that order, not a claim about millimetres. The two blues share a level on
purpose: they are the pair the derivation was least sure about, so nothing a
reader sees depends on a distinction nobody made.
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

NAME = "JMA"
# Who this source is added FOR, as opposed to what it can SEE.
# covers() answers the second question and must not be read as the
# first: a box that holds all of Japan holds neighbours too.
SERVES = ("JP",)
ATTRIB = "Japan Meteorological Agency jma.go.jp"
HOST = "https://www.jma.go.jp"
TIMES_URL = HOST + "/bosai/jmatile/data/nowc/targetTimes_N1.json"
# Measured 8/13 over Tokyo, one frame: z6 tiles carry data, **z7 returns the
# 334-byte fully transparent tile for every position**, z8 carries data again
# (55114 visible pixels against z6's 4704). RainViewer's DEFAULT_ZOOM is 7, so
# taking that default would have shipped a Japan whose sky is always clear --
# a wrong request that answers 200 with a valid, empty PNG. ops/jma_zoom.py
# re-runs that check; it is the reason MAX_ZOOM is now a per-service argument.
ZOOM = 8
MAX_ZOOM = 10
TILE_PX = 256           # theirs; RainViewer serves 512 and the mosaic defaults to that
INDEX_TTL = 120.0
FRAME_MAX_AGE = 1800.0
# Three rectangles, because latitude and longitude have to constrain each other
# here. One box cannot separate Japan from Korea (Yonaguni 122.9E vs Seoul
# 127.0E), and the two-box version I wrote first reached far enough west at high
# latitude to swallow Vladivostok -- caught by the test, not by me reading it.
# A sky JMA does not cover renders as an empty grid, and an empty grid reads as
# "no rain" rather than "not looking", which is why the boundary is worth three
# lines. Tsushima (129.3E) falls outside on purpose: losing an island is better
# than claiming a country.
COVERAGE = [(30.0, 129.5, 36.0, 141.0),    # Kyushu, Shikoku, western Honshu
            (35.0, 136.0, 46.0, 146.5),    # eastern Honshu and Hokkaido
            (24.0, 122.5, 28.5, 131.5)]    # Okinawa and the Sakishima islands
CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")

# Order derived and cross-checked; levels are our bucketing of that order.
PALETTE = [((242, 242, 255), 1), ((160, 210, 255), 1),
           ((33, 140, 255), 2), ((0, 65, 255), 2),      # the fragile pair
           ((250, 245, 0), 3),
           ((255, 153, 0), 4),
           ((255, 40, 0), 5), ((180, 0, 104), 5)]

_LOCK = threading.Lock()
_INDEX = {"at": 0.0, "v": None}


def covers(lng, lat):
    return any(s <= lat <= n and w <= lng <= e for s, w, n, e in COVERAGE)


def _times(cached_only=False):
    """The frame index, from memory when it is fresh enough.

    `cached_only` has to reach this far down. The tile cache alone is not the
    whole third party: this index is a second request to jma.go.jp, measured at
    0.57s, and with a 120s TTL roughly half the readers arriving on a cold
    scene were paying it -- on their own thread, for an upgrade to a map they
    already had. That is the same rule the tile gate exists for, applied one
    call earlier, and it is the half I missed the first time: the median cold
    render went from 0.9s to 1.4s and the tile gate could not explain it.

    When we decline, the background warm still fetches it, so the next reader
    finds it in memory rather than nobody ever fetching it.
    """
    now = time.time()
    with _LOCK:
        if _INDEX["v"] is not None and now - _INDEX["at"] < INDEX_TTL:
            return _INDEX["v"]
        if cached_only:
            return None
    try:
        v = json.loads(urllib.request.urlopen(TIMES_URL, timeout=8).read())
    except Exception as e:
        sys.stderr.write("JMA-TIMES-FAILED %r\n" % (e,))
        with _LOCK:
            return _INDEX["v"]
    with _LOCK:
        _INDEX["at"], _INDEX["v"] = now, v
        return v


def observed_frame(times=None, cached_only=False):
    """-> (unix ts, basetime string) for the newest OBSERVED frame, or (None, None).

    `validtime == basetime` is the observation; anything else in this file is a
    forecast step, which is both a different promise and a regulated one.
    """
    ts_list = times if times is not None else _times(cached_only=cached_only)
    if not ts_list:
        return None, None
    obs = [t for t in ts_list if t.get("basetime") == t.get("validtime")]
    if not obs:
        return None, None
    bt = max(t["basetime"] for t in obs)
    try:
        st = time.strptime(bt, "%Y%m%d%H%M%S")
    except Exception:
        sys.stderr.write("JMA-BASETIME-UNPARSEABLE %r\n" % (bt,))
        return None, None
    ts = time.mktime(st) - time.timezone      # their stamps are UTC
    if time.time() - ts > FRAME_MAX_AGE:
        sys.stderr.write("JMA-FRAME-TOO-OLD age=%.0fs\n" % (time.time() - ts,))
        return None, None
    return ts, bt


def tile_url(basetime, x, y, z, n):
    """Their URL shape, with the zoom asserted rather than assumed.

    Asking for zoom 64 instead of 6 returns 200 and a valid 334-byte PNG --
    measured. A wrong request that answers successfully is the trap this whole
    module family keeps stepping in, so the level is checked here where it is
    cheap rather than discovered in a map that looks fine.
    """
    if not (0 <= z <= MAX_ZOOM):
        raise ValueError("zoom %r is not a zoom level" % (z,))
    return ("%s/bosai/jmatile/data/nowc/%s/none/%s/surf/hrpns/%d/%d/%d.png"
            % (HOST, basetime, basetime, z, int(x) % int(n), int(y)))


def classify(arr):
    import numpy as np
    a = arr[..., :3].astype(np.int32)
    out = np.zeros(a.shape[:2], dtype=np.uint8)
    for (r, g, b), lvl in PALETTE:
        hit = (a[..., 0] == r) & (a[..., 1] == g) & (a[..., 2] == b)
        out[hit] = lvl
    out[arr[..., 3] <= 50] = 0
    return out


def _cache_path(lng, lat, bt, zoom=None):
    """The key must name every input that changes the picture.

    It did not name the zoom, and the first thing that cost was a lie to me:
    after moving from z6 to z8 the adapter kept handing back the z6 mosaic,
    identical art and identical km/col, and the change looked like it had done
    nothing. A cache key missing a parameter does not fail -- it answers an
    older question confidently.
    """
    key = "JMA|%.1f,%.1f|%s|z%s" % (round(float(lat), 1), round(float(lng), 1),
                                    bt, ZOOM if zoom is None else zoom)
    return os.path.join(CACHE, "jma-" + hashlib.sha1(key.encode()).hexdigest() + ".png")


def draw(code, lng, lat, small=False, get=None, cached_only=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None."""
    if not covers(lng, lat):
        return None
    ts, bt = observed_frame(cached_only=cached_only)
    if ts is None:
        return None
    p = _cache_path(lng, lat, bt)
    xs, ys, n = RV.plan(lat, lng, 280.0, ZOOM, max_zoom=MAX_ZOOM)
    bbox = RV.bbox_of(xs, ys, n)
    if cached_only and not (os.path.exists(p) and os.path.getsize(p) > 0):
        return None          # see radar_wms.draw: never spend a reader's time
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        kw = {"zoom": ZOOM, "max_zoom": MAX_ZOOM, "tile_px": TILE_PX,
              "url_for": lambda x, y, z, nn: tile_url(bt, x, y, z, nn)}
        if get is not None:
            kw["get"] = get
        img, bbox, got, want = RV.fetch(HOST, "", lat, lng, span_km=280.0, **kw)
        if not got:
            sys.stderr.write("JMA-NO-TILES %.2f,%.2f\n" % (lng, lat))
            return None
        if got < want:
            sys.stderr.write("JMA-PARTIAL got=%d want=%d\n" % (got, want))
        try:
            os.makedirs(CACHE, exist_ok=True)
            tmp = p + ".%d" % os.getpid()
            img.save(tmp, format="PNG")
            os.replace(tmp, p)
        except Exception as e:
            sys.stderr.write("JMA-CACHE-FAILED %r\n" % (e,))
            p = os.path.join(tempfile.gettempdir(), "jma-%d.png" % os.getpid())
            img.save(p, format="PNG")
    from render_scene import ascii_radar
    art, kmcol = ascii_radar(p, bbox, lng, lat,
                             cols=(24 if small else 48),
                             rows=(12 if small else 24), marker=code,
                             classifier=classify)
    return art, kmcol, float(ts), None, float(ts), NAME
