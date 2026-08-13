"""Czechia, from CHMI's MAX_Z radar composite, in values rather than colours.

Licence: CC BY 4.0, and this is the first source in the fleet where that is a
machine-readable fact rather than a sentence I had to read and interpret. The
Czech national open-data catalogue publishes the terms for this exact
distribution as RDF:

    autorské-dílo            https://creativecommons.org/licenses/by/4.0/
    databáze-jako-autorské-dílo  https://creativecommons.org/licenses/by/4.0/
    databáze-chráněná-...    není chráněna zvláštním právem pořizovatele
    osobní-údaje             neobsahuje osobní údaje
    autor                    Český hydrometeorologický ústav

Denmark is refused three directories away from a working download because its
terms could not be read at all. That contrast is the whole reason to prefer a
catalogue entry to a PDF: `ops/chmi_terms.py` re-asks the catalogue and fails if
the answer changes.

What we take is MAX_Z: the maximum reflectivity in the vertical column over each
grid point, composited from the Brdy-Praha and Skalky radars, 1x1 km, every five
minutes. It is an observation, not a nowcast -- the neighbouring directories
carry `fct_maxz` and `fct_pseudocappi2km`, which are extrapolation forecasts, and
taking one of those under a line that reads `radar: obs` is the JMA mistake in
another costume.

Two shapes worth naming, because both were nearly stepped in today:

  * The PNG twin of this product is in EPSG:3857 and needs no HDF5 reader at
    all -- and it is drawn with borders and coastlines on it. Those are opaque
    pixels a classifier reads as echo. A picture that already contains
    decoration cannot be turned back into values, so this module takes the
    numbers.
  * The directory listing is 301 KB of HTML, and reading only the first 200 KB
    of it returns a newest frame three days old, with no truncation marker.
    Nothing here parses that listing: filenames are stated in the docs and
    derived from the clock, and we walk backwards from now.

Everything else -- the scale, the corners, the grid size -- is read out of each
file's own attributes rather than restated here. The gain and offset happen to
be 0.5/-32.0, which is Denmark's pair and NOT Sweden's 0.4/-30.0: a restated
constant would draw the right map at the wrong intensity, and look normal.
"""
import hashlib
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

NAME = "CHMI"
# Who this source is added FOR, as opposed to what it can SEE.
# covers() answers the second question and must not be read as the
# first: a box that holds all of Czechia holds neighbours too.
SERVES = ("CZ",)
ATTRIB = "Czech Hydrometeorological Institute, CC BY 4.0"
BASE = ("https://opendata.chmi.cz/meteorology/weather/radar/composite/maxz/hdf5/"
        "T_PABV23_C_OKPR_%s.hdf")
UA = "runemap/1.0 (+https://echorune.net)"
TIMEOUT = 12.0

STEP = 300.0                 # their publication cadence, stated in the docs
FRAME_MAX_AGE = 1800.0       # five missed beats; the probe reports STALE past it
LOOKBACK = 6                 # frames to walk back before giving up

# The composite's own corners, which reach into Germany, Austria, Poland and
# Slovakia -- it really does see them, and says so (foreign radars are merged in
# when a Czech one is out). The rectangle is honest about that rather than
# pretending to stop at the border, and DWD is asked before this module, so
# Germany is answered by its own service. Where the composite has no data, the
# nodata share below declines the window instead of drawing fair weather.
COVERAGE = (48.05, 11.27, 51.46, 19.62)
MAX_NODATA_SHARE = 0.25

CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")


def covers(lng, lat):
    s, w, n, e = COVERAGE
    return s <= lat <= n and w <= lng <= e


def stamps(now=None):
    """Candidate frame names, newest first.

    Their stamp is the END of the five-minute interval, in UTC, so the newest
    one that can exist is the last multiple of 300s that has already passed.
    """
    t = time.time() if now is None else now
    base = math.floor(t / STEP) * STEP
    return [time.strftime("%Y%m%d%H%M%S", time.gmtime(base - i * STEP))
            for i in range(LOOKBACK)]


def frame_ts(stamp):
    return time.mktime(time.strptime(stamp, "%Y%m%d%H%M%S")) - time.timezone


def _cache_path(stamp):
    key = "chmi-maxz|%s" % (stamp,)
    return os.path.join(CACHE, "chmi-" + hashlib.sha1(key.encode()).hexdigest() + ".hdf")


def have_h5py():
    try:
        import h5py           # noqa: F401
        return True
    except Exception:
        return False


def unavailable():
    """-> a sentence if this source cannot work here at all, else None.

    The health probe asks this before calling a decline NO-MAP. Missing h5py
    and a dead upstream both reach a reader as an empty grid, but they are
    different failures with different repairs, and a probe that prints one word
    for both sends the next hour of debugging to the wrong place.
    """
    if not have_h5py():
        return "h5py is not installed (pip install 'runemap[hdf5]')"
    return None


def _fetch(stamp, get=None):
    """-> cache path, or None. Never raises for an absent frame."""
    p = _cache_path(stamp)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p
    url = BASE % stamp
    try:
        raw = (get or (lambda u: urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA}),
            timeout=TIMEOUT).read()))(url)
    except Exception as e:
        sys.stderr.write("CHMI-FETCH-FAILED %s %r\n" % (stamp, e))
        return None
    if not raw or raw[:8] != b"\x89HDF\r\n\x1a\n":
        # A 404 page, a portal redirect, or a truncated body all arrive here as
        # bytes that are not an HDF5 file. Saying so is cheaper than finding out
        # inside the reader.
        sys.stderr.write("CHMI-NOT-HDF5 %s %d bytes %r\n"
                         % (stamp, len(raw or b""), (raw or b"")[:24]))
        return None
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = p + ".%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, p)
        return p
    except Exception as e:
        sys.stderr.write("CHMI-CACHE-FAILED %r\n" % (e,))
        tmp = os.path.join(tempfile.gettempdir(), "chmi-%d.hdf" % os.getpid())
        with open(tmp, "wb") as fh:
            fh.write(raw)
        return tmp


def read(path):
    """-> (array, scale dict, corners dict) from the file's own attributes.

    Nothing here is a constant of ours. The quantity is asserted because the
    same directory tree publishes radial velocity, differential phase and
    correlation coefficient in the identical container: reading one of those
    with a reflectivity scale would produce a plausible, entirely wrong map.
    """
    import h5py
    with h5py.File(path, "r") as f:
        w = dict(f["/dataset1/data1/what"].attrs)
        quantity = w.get("quantity")
        if isinstance(quantity, bytes):
            quantity = quantity.decode()
        if quantity != "DBZH":
            raise ValueError("expected DBZH, got %r" % (quantity,))
        where = dict(f["/where"].attrs)
        arr = f["/dataset1/data1/data"][:]
        top = dict(f["/what"].attrs)
    scale = {"gain": float(w["gain"]), "offset": float(w["offset"]),
             "undetect": float(w["undetect"]), "nodata": float(w["nodata"])}
    corners = {k: float(where[k]) for k in
               ("LL_lat", "LL_lon", "UR_lat", "UR_lon")}
    if not (corners["UR_lat"] > corners["LL_lat"]
            and corners["UR_lon"] > corners["LL_lon"]):
        raise ValueError("corners are not a rectangle: %r" % (corners,))
    date = top.get("date")
    tm = top.get("time")
    stamp = ((date.decode() if isinstance(date, bytes) else date or "")
             + (tm.decode() if isinstance(tm, bytes) else tm or ""))
    return arr, scale, corners, stamp


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


def _merc_y(lat):
    lat = max(-85.0, min(85.0, float(lat)))
    return math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))


def window(arr, scale, corners, lng, lat, span_km, cols, rows):
    """-> (levels, nodata_share) for a grid of cells centred on the reader.

    The grid is spherical Mercator (the file says so: `+proj=merc ... +a=+b=
    6378137`), which is linear in longitude and in log-tangent latitude, so a
    cell maps to a pixel with two divisions and no projection library. The
    corners come from the file, so a product that moves is read where it moved
    to rather than where it used to be.
    """
    import numpy as np
    h, w = arr.shape
    x0, x1 = corners["LL_lon"], corners["UR_lon"]
    y0, y1 = _merc_y(corners["LL_lat"]), _merc_y(corners["UR_lat"])
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    out = np.zeros((rows, cols), dtype=np.int16)
    missing = 0
    for r in range(rows):
        cell_lat = lat + half_lat - (2 * half_lat) * (r + 0.5) / rows
        my = _merc_y(cell_lat)
        py = int((y1 - my) / (y1 - y0) * h)
        for c in range(cols):
            cell_lng = lng - half_lng + (2 * half_lng) * (c + 0.5) / cols
            px = int((cell_lng - x0) / (x1 - x0) * w)
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
        # An optional dependency that is missing must say so. Declining quietly
        # would hand the reader an empty grid, which reads as "no rain" rather
        # than "no reader for this format" -- and the health probe would report
        # NO-MAP for a network that is perfectly fine.
        sys.stderr.write("CHMI-NO-H5PY install runemap[hdf5] to read this source\n")
        return None
    cand = stamps()
    path = ts = None
    for stamp in cand:
        p = _cache_path(stamp)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            path, ts = p, frame_ts(stamp)
            break
    if path is None:
        if cached_only:
            return None      # see radar_wms.draw: never spend a reader's time
        for stamp in cand:
            p = _fetch(stamp, get)
            if p is not None:
                path, ts = p, frame_ts(stamp)
                break
    if path is None:
        sys.stderr.write("CHMI-NO-FRAME newest tried %s\n" % (cand[0],))
        return None
    age = time.time() - ts
    if age > FRAME_MAX_AGE:
        sys.stderr.write("CHMI-FRAME-TOO-OLD age=%.0fs\n" % (age,))
        return None
    try:
        arr, scale, corners, _stamp = read(path)
    except Exception as e:
        sys.stderr.write("CHMI-READ-FAILED %r\n" % (e,))
        return None
    cols, rows = (24, 12) if small else (48, 24)
    span = float(os.environ.get("RUNEMAP_SPAN_KM", "280") or 280)
    try:
        levels, share = window(arr, scale, corners, lng, lat, span, cols, rows)
    except Exception as e:
        sys.stderr.write("CHMI-WINDOW-FAILED %r\n" % (e,))
        return None
    if share > MAX_NODATA_SHARE:
        sys.stderr.write("CHMI-MOSTLY-BLIND %.2f,%.2f %.0f%% > %.0f%%\n"
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
