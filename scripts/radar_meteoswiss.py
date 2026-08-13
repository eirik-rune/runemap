"""Switzerland: MeteoSwiss RZC, the 5-minute precipitation rate composite.

Feasibility and every measurement behind the constants here are in
`docs/switzerland_meteoswiss_feasibility.md`. Three things are worth knowing
before reading the code:

* **Blind and dry are stated, not inferred.** The file gives `nodata=NaN` and
  `undetect=0.0`, so "the radars cannot see this cell" and "there is no rain in
  this cell" arrive as different values. That conflation is the failure this
  fleet keeps meeting; here it costs nothing to get right, so `level_at()`
  returns -1 and 0 respectively and never confuses them.

* **This source is mm/h and the fleet classifies in dBZ.** The conversion is
  Marshall-Palmer, and it is an approximation: MeteoSwiss derive RZC with their
  own Z-R relation, which is not necessarily this one. It goes through the one
  shared `dbz.py` table rather than growing a second ramp here -- a table copied
  into three modules is what drew clear air as rain in three countries.

* **The payload's orientation is NOT verified.** The projection is (7 cm against
  swisstopo's own worked example, and the file's four corners reproduce its
  declared 710x640 km grid to ~6 m). But the corner check and my arithmetic both
  come from the same file, so they agree whatever the array does. The usual
  control -- the blind mask against the radar sites -- was tried with the real
  OSCAR positions and **has no power here**: MeteoSwiss centre the composite on
  their own network, so an upside-down read maps the mask almost onto itself
  (140.6 km vs 142.0 km). Settling it needs a look at their own rendering during
  rain. Until then this adapter is not in the production chain.
"""
import hashlib
import math
import os
import sys
import tempfile
import time
import urllib.request

NAME = "MeteoSwiss"
# Who this source is added FOR, as opposed to what it can SEE.
SERVES = ("CH",)
ATTRIB = "MeteoSwiss opendata.swiss, CC BY 4.0"

BASE = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-radar-precip"
UA = "runemap/1.0 (+https://echorune.net; contact luoshu@echorune.net)"
TIMEOUT = 12.0

STEP = 300.0                 # a frame every 5 minutes
LOOKBACK = 8                 # 40 minutes of candidates
FRAME_MAX_AGE = 1800.0
# Measured publication latency is under 2 minutes; this is the useful range of
# the composite as MeteoSwiss themselves declare it in the STAC collection
# (bbox 5.96 45.82 10.49 47.81), not a box drawn round the country by me.
COVERAGE = (45.82, 5.96, 47.81, 10.49)
MAX_NODATA_SHARE = 0.4

# Grid, derived in the feasibility note from the file's own stated corners and
# asserted against them there: LV95, 710x640 cells of 1000 m, row 0 north.
E0, N0, CELL_M = 2255000.0, 1480000.0, 1000.0
NX, NY = 710, 640

CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")


def covers(lng, lat):
    la0, lo0, la1, lo1 = COVERAGE
    return la0 <= lat <= la1 and lo0 <= lng <= lo1


def have_h5py():
    try:
        import h5py           # noqa: F401
        return True
    except Exception:
        return False


def unavailable():
    """-> a sentence naming why this source cannot work, or None.

    A missing reader and a dead upstream both reach a reader as an empty grid.
    One word for both sends the next hour to the wrong place.
    """
    if not have_h5py():
        return "h5py is not installed; install runemap[hdf5] to read MeteoSwiss"
    return None


def frame_name(ts):
    """-> the asset key for a 5-minute slot, e.g. rzc262252120vl.001.h5.

    Their naming is year-of-century plus day-of-year plus HHMM, all UTC.
    """
    t = time.gmtime(ts)
    return "rzc%02d%03d%02d%02dvl.001.h5" % (t.tm_year % 100, t.tm_yday,
                                             t.tm_hour, t.tm_min)


def frame_url(ts):
    return "%s/%s-ch/%s" % (BASE, time.strftime("%Y%m%d", time.gmtime(ts)),
                            frame_name(ts))


def stamps(now=None):
    """-> candidate frame times, newest first, snapped to the 5-minute grid."""
    now = time.time() if now is None else now
    top = math.floor(now / STEP) * STEP
    return [top - i * STEP for i in range(LOOKBACK)]


def _cache_path(ts):
    key = "meteoswiss-rzc|%s" % (frame_name(ts),)
    return os.path.join(CACHE,
                        "chrzc-" + hashlib.sha1(key.encode()).hexdigest() + ".hdf")


def download(ts, get=None):
    """-> cache path, or None. Never raises for an absent frame.

    **A 404 here arrives as 403.** The bucket denies listing, so a key that does
    not exist yet answers "forbidden" rather than "not found". Treating that as
    a ban is a mistake I have made before and built a whole self-consistent
    story on, so it is named here: absent and blocked are indistinguishable on
    this endpoint, and neither is a reason to stop walking the clock back.
    """
    p = _cache_path(ts)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p
    try:
        raw = (get or (lambda u: urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA}),
            timeout=TIMEOUT).read()))(frame_url(ts))
    except Exception:
        return None
    if not raw or raw[:8] != b"\x89HDF\r\n\x1a\n":
        sys.stderr.write("CHRZC-NOT-HDF5 %s %d bytes\n"
                         % (frame_name(ts), len(raw or b"")))
        return None
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = p + ".%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, p)
        return p
    except Exception as e:
        sys.stderr.write("CHRZC-CACHE-FAILED %r\n" % (e,))
        return None


def read(path):
    """-> (array, projdef) with the grid asserted against the file's own words.

    The shape and projection are checked rather than trusted: a silent upstream
    change of grid would still deliver numbers, still scale them correctly, and
    put the weather somewhere else.
    """
    import h5py
    import somerc
    with h5py.File(path, "r") as f:
        arr = f["dataset1/data1/data"][:]
        where = f["where"].attrs
        what = f["dataset1/data1/what"].attrs

        def s(v):
            return v.decode() if isinstance(v, bytes) else v
        projdef = s(where["projdef"])
        somerc.assert_proj4(projdef)
        if (int(where["xsize"]), int(where["ysize"])) != (NX, NY):
            raise ValueError("grid is %sx%s, expected %dx%d"
                             % (where["xsize"], where["ysize"], NX, NY))
        if float(where["xscale"]) != CELL_M or float(where["yscale"]) != CELL_M:
            raise ValueError("cell size changed: %s/%s"
                             % (where["xscale"], where["yscale"]))
        quantity = s(what["quantity"])
        unit = s(what["unit"])
        if quantity != "RATE" or unit != "mm/h":
            # Reading a reflectivity product as a rain rate would classify
            # every cell wrongly while looking entirely healthy.
            raise ValueError("expected RATE in mm/h, got %r in %r"
                             % (quantity, unit))
    return arr, projdef


def dbz_of(rate_mm_h):
    """mm/h -> dBZ by Marshall-Palmer (Z = 200 R^1.6).

    An approximation, and labelled one: MeteoSwiss derive RZC using their own
    Z-R relation. It exists so this source reaches the single shared ramp in
    dbz.py instead of growing a second one here.
    """
    if rate_mm_h <= 0:
        return None
    return 10.0 * math.log10(200.0 * rate_mm_h ** 1.6)


def level_at(value):
    """-> -1 blind, 0 seen-and-dry, else the shared table's level.

    The three cases are kept apart on purpose. NaN is the radars' blindness and
    must never render as "no rain"; 0.0 is a real observation of no rain.
    """
    import dbz
    if value is None or value != value:        # NaN
        return -1
    if value <= 0.0:
        return 0
    d = dbz_of(value)
    if d is None:
        return 0
    return dbz.level_for(d)


def cell_of(lat, lng):
    """-> (row, col), or None when the point falls outside the grid."""
    import somerc
    e, n = somerc.forward(lat, lng)
    col = int((e - E0) // CELL_M)
    row = int((N0 - n) // CELL_M)
    if not (0 <= row < NY and 0 <= col < NX):
        return None
    return row, col


def window(arr, lng, lat, span_km, cols, rows):
    """-> (levels, nodata_share) for a grid of cells centred on the reader.

    A blind cell is stored as **-1**, not 0, so it renders as `OUTSIDE` ("?")
    rather than as blank. `runemap/render.py` says why in one line: `OUTSIDE =
    "?"  # not " ": empty means "no rain", this means "no radar here"`. The
    older DMI adapter leaves those cells at 0 and therefore draws the edge of
    its own coverage as clear sky; that is a real difference and it is
    deliberate here, not an accident of copying.
    """
    import numpy as np
    out = np.zeros((rows, cols), dtype=np.int16)
    missing = 0
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    for r in range(rows):
        cell_lat = lat + half_lat - (2 * half_lat) * (r + 0.5) / rows
        for c in range(cols):
            cell_lng = lng - half_lng + (2 * half_lng) * (c + 0.5) / cols
            rc = cell_of(cell_lat, cell_lng)
            if rc is None:
                out[r, c] = -1
                missing += 1
                continue
            lv = level_at(float(arr[rc[0], rc[1]]))
            if lv < 0:
                out[r, c] = -1
                missing += 1
                continue
            out[r, c] = lv
    return out, missing / float(rows * cols)


def draw(code, lng, lat, small=False, get=None, cached_only=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None."""
    if not covers(lng, lat):
        return None
    why = unavailable()
    if why:
        sys.stderr.write("CHRZC-NO-READER %s\n" % (why,))
        return None
    # Newest first, and cache-or-download PER SLOT rather than scanning the
    # whole cache first.
    #
    # The first version scanned every cached slot before trying any download,
    # so a single stale cached frame beat a fresher downloadable one: with
    # frames published up to 22:35 the probe chose one from 22:05, then
    # correctly rejected it as too old and declined the country entirely.
    # "Prefer the cache" is right; "prefer ANY cached frame over a newer one"
    # is not, and the two look identical until the cache holds exactly one old
    # entry.
    path = ts = None
    for cand in stamps():
        p = _cache_path(cand)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            path, ts = p, cand
            break
        if cached_only:
            # This reader already holds a map; buying them a fresher one at the
            # price of an upstream round trip is a trade nobody asked for. Keep
            # walking back through the cache, but open no socket.
            continue
        p = download(cand, get)
        if p is not None:
            path, ts = p, cand
            break
    if path is None:
        return None
    age = time.time() - ts
    if age > FRAME_MAX_AGE:
        sys.stderr.write("CHRZC-FRAME-TOO-OLD age=%.0fs\n" % (age,))
        return None
    try:
        arr, _projdef = read(path)
    except Exception as e:
        sys.stderr.write("CHRZC-READ-FAILED %r\n" % (e,))
        return None
    cols, rows = (24, 12) if small else (48, 24)
    span = float(os.environ.get("RUNEMAP_SPAN_KM", "280") or 280)
    try:
        levels, share = window(arr, lng, lat, span, cols, rows)
    except Exception as e:
        sys.stderr.write("CHRZC-WINDOW-FAILED %r\n" % (e,))
        return None
    if share > MAX_NODATA_SHARE:
        sys.stderr.write("CHRZC-MOSTLY-BLIND %.2f,%.2f %.0f%% > %.0f%%\n"
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
