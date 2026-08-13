"""Denmark, from DMI's national radar composite, in values rather than colours.

Licence: CC BY 4.0, from DMI's own page -- the API's `collections` response
carries a link titled "License for the data in this service", and it grants
*"Adapt -- remix, transform, and build upon the material for any purpose, even
commercially"*. This module exists because I refused this source once on the
strength of a third-party paraphrase that said the opposite, adopted because
their docs host 404'd. The rule that came out of it is on the stone: ask the
service where its terms are, and ask the catalogue what licence it registers,
before recording a refusal. The EU open-data portal independently registers the
same access URL as `CC_BY_4_0`, publisher Danmarks Meteorologiske Institut.

The product is `dk.com.*.500_max.h5`: column-maximum reflectivity, 500 m cells,
every five minutes, no key required. It is an observation, not a nowcast.

**The projection is a third family**, oblique stereographic (`lat_0=56
lon_0=10.5666`), not the polar aspect KNMI uses -- see ops/stereo_oblique.py,
which is validated against DMI's own stated corners and which found that one of
those four corners is wrong in their file. The grid here is therefore built
from ONE anchor corner and the scale, exactly as that module recommends.

Two things read out of the file rather than restated:

  * gain/offset/undetect/nodata live at `/what` in these files, not under
    `/dataset1/data1/what` where CHMI and KNMI keep them. dBZ = 0.5*DN - 32
    today, which is Czechia's pair and NOT Sweden's 0.4/-30.0 -- a restated
    constant would draw the right map at the wrong intensity and look normal.
  * the newest frame comes from one listing request against their items API,
    sorted descending, limit 1. Nothing walks a range of candidate timestamps:
    that pattern cost KNMI's shared anonymous quota 18 requests in a burst, and
    the cost of that fell on strangers.

Coverage is measured, not assumed. On the 2026-08-13 15:35 frame, 21% of the
grid is anything other than nodata, and that region spans about 54.0-58.5 N,
6.3-16.6 E -- Denmark plus the near edges of Sweden, Norway and Germany. The
rectangle below is that measurement; the nodata guard declines windows that
fall in the blind parts of it rather than drawing fair weather there.
"""
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "ops")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NAME = "DMI"
# Who this source is added FOR, as opposed to what it can SEE.
# covers() answers the second question and must not be read as the
# first: a box that holds all of Denmark holds neighbours too.
SERVES = ("DK",)
ATTRIB = "Danish Meteorological Institute, CC BY 4.0"
API = ("https://dmigw.govcloud.dk/v1/radardata/collections/composite/items"
       "?limit=1&sortorder=datetime,DESC")
DOWNLOAD = "https://dmigw.govcloud.dk/v1/radardata/download/%s"
UA = "runemap/1.0 (+https://echorune.net)"
TIMEOUT = 12.0

STEP = 300.0                 # their publication cadence
FRAME_MAX_AGE = 1800.0       # five missed beats
SCALE_M = 500.0              # cell size, also stated per file and asserted

COVERAGE = (54.0, 6.3, 58.5, 16.6)
CACHE_SLOTS = tuple(range(6))
# How stale a cached frame may be before we go and ask what is newest. Two
# slots is ten minutes: still a cache hit for most readers inside one
# publication cycle, without letting an old entry pin the source.
CACHE_ACCEPT_SLOTS = 2
MAX_NODATA_SHARE = 0.25

CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")


def covers(lng, lat):
    s, w, n, e = COVERAGE
    return s <= lat <= n and w <= lng <= e


def have_h5py():
    try:
        import h5py           # noqa: F401
        return True
    except Exception:
        return False


def unavailable():
    """-> a sentence if this source cannot work here at all, else None.

    Missing h5py and a dead upstream both reach a reader as an empty grid, but
    they are different failures with different repairs, and one word for both
    sends the next hour of debugging to the wrong place.
    """
    if not have_h5py():
        return "h5py is not installed (pip install 'runemap[hdf5]')"
    return None


def stamp_of(name):
    """`dk.com.202608131535.500_max.h5` -> epoch seconds, or None.

    Parsed from the filename rather than trusted from the listing's `datetime`,
    because the filename is what we then ask for: if those two ever disagree,
    the age we print must describe the file we actually read.
    """
    parts = str(name).split(".")
    for p in parts:
        if len(p) == 12 and p.isdigit():
            try:
                return time.mktime(time.strptime(p, "%Y%m%d%H%M")) - time.timezone
            except ValueError:
                return None
    return None


def newest_frame(get=None):
    """-> filename of the newest published frame, or None. ONE request."""
    try:
        raw = (get or (lambda u: urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA}),
            timeout=TIMEOUT).read()))(API)
        feats = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        feats = feats.get("features") or []
    except Exception as e:
        sys.stderr.write("DMI-LIST-FAILED %r\n" % (e,))
        return None
    if not feats:
        # An empty list is not "no weather": it is a service that answered and
        # had nothing to offer, and it must not be confused with a clear sky.
        sys.stderr.write("DMI-LIST-EMPTY\n")
        return None
    return feats[0].get("id")


def _cache_path(name):
    key = "dmi-comp|%s" % (name,)
    return os.path.join(CACHE, "dmi-" + hashlib.sha1(key.encode()).hexdigest() + ".hdf")


def download(name, get=None):
    """-> cache path, or None. Never raises for an absent frame."""
    p = _cache_path(name)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p
    try:
        raw = (get or (lambda u: urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA}),
            timeout=TIMEOUT).read()))(DOWNLOAD % name)
    except Exception as e:
        sys.stderr.write("DMI-FETCH-FAILED %s %r\n" % (name, e))
        return None
    if not raw or raw[:8] != b"\x89HDF\r\n\x1a\n":
        sys.stderr.write("DMI-NOT-HDF5 %s %d bytes %r\n"
                         % (name, len(raw or b""), (raw or b"")[:24]))
        return None
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = p + ".%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, p)
        return p
    except Exception as e:
        sys.stderr.write("DMI-CACHE-FAILED %r\n" % (e,))
        tmp = os.path.join(tempfile.gettempdir(), "dmi-%d.hdf" % os.getpid())
        with open(tmp, "wb") as fh:
            fh.write(raw)
        return tmp


def _one(v):
    """HDF5 attributes here are 1-element arrays as often as scalars."""
    try:
        return float(v[0])
    except (TypeError, IndexError, KeyError):
        return float(v)


def read(path):
    """-> (array, scale dict, corners dict, scale_m) from the file's own attrs.

    The quantity is asserted: the same container carries other moments in other
    products, and reading one of those with a reflectivity scale produces a
    plausible, entirely wrong map. The projection is asserted too, by value --
    a grid that silently moved would otherwise be read where it used to be.
    """
    import h5py
    with h5py.File(path, "r") as f:
        top = dict(f["/what"].attrs)
        where = dict(f["/where"].attrs)
        arr = f["/dataset1/data1/data"][:]
    product = top.get("product")
    if isinstance(product, bytes):
        product = product.decode()
    if product != "DBZH":
        raise ValueError("expected DBZH, got %r" % (product,))
    import stereo_oblique as SO
    SO.assert_proj4(where["projdef"])
    xs, ys = _one(where["xscale"]), _one(where["yscale"])
    if abs(xs - ys) > 1e-6:
        raise ValueError("non-square cells: %r x %r" % (xs, ys))
    scale = {"gain": _one(top["gain"]), "offset": _one(top["offset"]),
             "undetect": _one(top["undetect"]), "nodata": _one(top["nodata"])}
    corners = {k: _one(where[k]) for k in
               ("LL_lat", "LL_lon", "LR_lat", "LR_lon",
                "UL_lat", "UL_lon", "UR_lat", "UR_lon")}
    return arr, scale, corners, xs


def level_of(dn, scale):
    """DN -> our 0-5 scale, or -1 for nodata.

    undetect and nodata are two different facts -- "looked, saw nothing" and
    "did not look here" -- and only the first means no rain. They must not share
    a return value: every failure this fleet has had reaches the reader as an
    empty grid, which is exactly what a clear sky looks like.
    """
    if dn == scale["nodata"]:
        return -1
    if dn == scale["undetect"]:
        return 0
    import dbz as _dbz
    return _dbz.level_for(scale["gain"] * dn + scale["offset"])


def window(arr, scale, corners, cell_m, lng, lat, span_km, cols, rows):
    """-> (levels, nodata_share) for a grid of cells centred on the reader.

    Built from the UL corner and the cell size, with the projection doing the
    work -- see ops/stereo_oblique.check_corners for why not from all four.
    Corners are cell CENTRES, which is what makes (n-1)*scale match the stated
    span, so the anchor is the centre of cell (0, 0).
    """
    import numpy as np
    import stereo_oblique as SO
    h, w = arr.shape
    ax, ay = SO.forward(corners["UL_lat"], corners["UL_lon"])
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    out = np.zeros((rows, cols), dtype=np.int16)
    missing = 0
    for r in range(rows):
        cell_lat = lat + half_lat - (2 * half_lat) * (r + 0.5) / rows
        for c in range(cols):
            cell_lng = lng - half_lng + (2 * half_lng) * (c + 0.5) / cols
            x, y = SO.forward(cell_lat, cell_lng)
            px = int(round((x - ax) / cell_m))
            py = int(round((ay - y) / cell_m))
            if not (0 <= px < w and 0 <= py < h):
                missing += 1
                continue
            lv = level_of(int(arr[py, px]), scale)
            if lv < 0:
                missing += 1
                continue
            out[r, c] = lv
    return out, missing / float(rows * cols)


def draw(code, lng, lat, small=False, get=None, cached_only=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None."""
    if not covers(lng, lat):
        return None
    if not have_h5py():
        sys.stderr.write("DMI-NO-H5PY install runemap[hdf5] to read this source\n")
        return None
    # A cached frame is preferred over a fresh listing: the reader's request
    # must not pay for discovery when the answer is already on disk.
    path = ts = None
    now = time.time()
    # Only the freshest few slots may be answered from cache. Walking the whole
    # window meant one old cached frame won outright and upstream was never
    # asked how new it could be -- readers were served a frame up to 25 minutes
    # old with a 2-minute-old one available, and the cache only refreshed once
    # the stale entry aged out of the window. Reproduced deliberately: seeding
    # only an old slot made draw() return without a single network call.
    # MeteoSwiss had the identical shape tonight and declined outright there,
    # because its lookback exceeded its own staleness limit.
    # cached_only keeps the full window: that path must open no socket, so the
    # best it already holds is the honest answer.
    horizon = len(CACHE_SLOTS) if cached_only else CACHE_ACCEPT_SLOTS
    for i in CACHE_SLOTS[:horizon]:
        name = "dk.com.%s.500_max.h5" % time.strftime(
            "%Y%m%d%H%M", time.gmtime(math.floor((now - i * STEP) / STEP) * STEP))
        p = _cache_path(name)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            path, ts = p, stamp_of(name)
            break
    if path is None:
        if cached_only:
            return None      # see radar_wms.draw: never spend a reader's time
        name = newest_frame(get)
        if not name:
            return None
        ts = stamp_of(name)
        if ts is None:
            sys.stderr.write("DMI-UNPARSEABLE-NAME %r\n" % (name,))
            return None
        path = download(name, get)
        if path is None:
            return None
    age = time.time() - ts
    if age > FRAME_MAX_AGE:
        sys.stderr.write("DMI-FRAME-TOO-OLD age=%.0fs\n" % (age,))
        return None
    try:
        arr, scale, corners, cell_m = read(path)
    except Exception as e:
        sys.stderr.write("DMI-READ-FAILED %r\n" % (e,))
        return None
    cols, rows = (24, 12) if small else (48, 24)
    span = float(os.environ.get("RUNEMAP_SPAN_KM", "280") or 280)
    try:
        levels, share = window(arr, scale, corners, cell_m,
                               lng, lat, span, cols, rows)
    except Exception as e:
        sys.stderr.write("DMI-WINDOW-FAILED %r\n" % (e,))
        return None
    if share > MAX_NODATA_SHARE:
        sys.stderr.write("DMI-MOSTLY-BLIND %.2f,%.2f %.0f%% > %.0f%%\n"
                         % (lng, lat, share * 100, MAX_NODATA_SHARE * 100))
        return None
    from runemap.render import RAMP, OUTSIDE
    grid = [[(RAMP[v] if v >= 0 else OUTSIDE) for v in row]
            for row in levels.tolist()]
    my, mx = rows // 2, cols // 2
    for i, ch in enumerate(code[:2]):
        if mx + i < cols:
            grid[my][mx + i] = ch
    art = "\n".join("".join(r) for r in grid)
    return art, span / cols, float(ts), None, float(ts), NAME
