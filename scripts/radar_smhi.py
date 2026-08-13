"""Sweden, from SMHI's open-data radar composite -- values, not colours.

Every other source in this directory hands us a picture and makes us work out
what its colours mean. SMHI hands us the numbers. Their open-data file API
publishes the national composite as a single-band GeoTIFF whose pixel values
are reflectivity, and the companion ODIM HDF5 of the same frame states the
scale in its own attributes:

    /dataset1/data1/what: quantity=DBZH, gain=0.4, offset=-30.0,
                          nodata=255.0, undetect=0.0

so dBZ = 0.4 * DN - 30, with 0 meaning "looked, saw nothing" and 255 meaning
"did not look here". Those are two different facts and they must not collapse:
undetect is a clear sky, nodata is the edge of the composite, and a window that
is mostly nodata has to be declined rather than drawn as fair weather.
`ops/smhi_scale.py` re-reads those attributes from the source and fails if they
ever change, because a constant copied out of a file is a constant that can rot.

Licence: SMHI open data is Creative Commons Attribution 4.0 SE. Commercial use
is permitted; the terms require naming SMHI as the source and indicating that
the material has been changed. We print both, the second through the shared
`radar-data-note` line, because a 48x24 character grid is a change.

The awkward part is the projection. The GeoTIFF is UTM zone 33 North -- stated
by its own GeoKeys, not assumed -- so a reader's latitude and longitude have to
be projected before a pixel can be read. `ops/utm.py` does that, and it is
checked against the four corner coordinates SMHI writes into the HDF5, which
were computed on an entirely different grid.

One file serves the whole country, so this fetches once per refresh cycle for
every Swedish reader rather than once per sky.
"""
import hashlib
import math
import os
import sys
import tempfile
import time
import urllib.request

# This module must not depend on how it was reached. The test suite and
# render_scene both happen to run with the repo root importable; the standalone
# health probe does not, and it caught `ModuleNotFoundError: runemap` the first
# time it ran -- a packaging fault 331 green tests could not see, because they
# were all standing on a path a reader never stands on.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "ops")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NAME = "SMHI"
ATTRIB = "SMHI opendata.smhi.se, CC BY 4.0"
URL = ("https://opendata-download-radar.smhi.se/api/version/latest"
       "/area/sweden/product/comp/latest.tif")
UA = "runemap/1.0 (+https://echorune.net)"
REFRESH = float(os.environ.get("RUNEMAP_SMHI_REFRESH", "300"))
TIMEOUT = 12.0

# From the companion HDF5's own attributes -- see ops/smhi_scale.py, which
# re-reads them and fails if they move.
GAIN, OFFSET = 0.4, -30.0
UNDETECT, NODATA = 0, 255

# The bands live in scripts/dbz.py now -- one table, not one copy per source.
# The name is kept because tests and ops tools refer to it.
import dbz as _dbz                                            # noqa: E402
DBZ_LEVELS = _dbz.LEVELS

# The Nordic area this composite actually sees, not "Sweden": its own corners
# run 53.7N-69.8N and 5.3E-29.8E, and it genuinely observes southern Norway and
# the Danish straits. Drawing those is honest -- the credit says SMHI and the
# echo is really there -- and it is the same judgement already pinned for NEXRAD
# over Toronto. What the rectangle does exclude is Finland at 24.2E, because FMI
# is the better source there and is asked first.
#
# The first version of this comment said "deliberately only Sweden" while the
# rectangle contained Oslo. A rectangle that annexes the neighbour is the JMA
# mistake, and writing the intention above the code does not make the code do
# it. The real boundary is the pixels: where the composite has no data, the
# share below declines the window rather than drawing fair weather.
COVERAGE = (55.0, 10.5, 69.2, 24.2)
MAX_NODATA_SHARE = 0.25

CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")


def covers(lng, lat):
    s, w, n, e = COVERAGE
    return s <= lat <= n and w <= lng <= e


def _bucket(now=None):
    return int((time.time() if now is None else now) // REFRESH)


def _cache_path(bucket):
    key = "smhi-comp|%d" % (bucket,)
    return os.path.join(CACHE, "smhi-" + hashlib.sha1(key.encode()).hexdigest() + ".tif")


def georeference(im):
    """-> (e0, n0, scale, width, height) from the file's own tags.

    Nothing here is hardcoded, and the projection is asserted rather than
    assumed: GeoTIFF key 3074 carries 16033 for UTM zone 33 North and 3076
    carries 9001 for metres. A product that quietly moved to another grid would
    otherwise be read with the old one and answer confidently about the wrong
    place -- the failure this whole directory keeps meeting.
    """
    tags = im.tag_v2
    tie = tags.get(33922)
    scale = tags.get(33550)
    if not tie or not scale:
        raise ValueError("no ModelTiepointTag/ModelPixelScaleTag: not a GeoTIFF")
    gk = tags.get(34735) or ()
    keys = {}
    for k in range(gk[3] if len(gk) > 3 else 0):
        key, loc, _count, off = gk[4 + k * 4:8 + k * 4]
        if loc == 0:
            keys[key] = off
    proj, units = keys.get(3074), keys.get(3076)
    if proj != 16033:
        raise ValueError("expected UTM 33N (GeoTIFF projection 16033), got %r" % (proj,))
    if units != 9001:
        raise ValueError("expected metres (linear unit 9001), got %r" % (units,))
    if abs(scale[0] - scale[1]) > 1e-3:
        raise ValueError("non-square pixels %r" % (scale,))
    return float(tie[3]), float(tie[4]), float(scale[0]), im.size[0], im.size[1]


def level_of(dn):
    """DN -> our 0-5 scale, or -1 for nodata.

    undetect (0) and nodata (255) are two different facts -- "looked, saw
    nothing" and "did not look here" -- and only the first one means no rain.
    They must not share a return value: this whole fleet's failures reach a
    reader as an empty grid, which is what a clear sky looks like, so a sentinel
    that can be mistaken for zero is the bug rather than a shortcut.
    """
    if dn == NODATA:
        return -1
    if dn == UNDETECT:
        return 0
    return _dbz.level_for(GAIN * dn + OFFSET)


def _fetch(get=None):
    p = _cache_path(_bucket())
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p, True
    raw = (get or (lambda u: urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": UA}), timeout=TIMEOUT).read()))(URL)
    if not raw or raw[:4] not in (b"II*\x00", b"MM\x00*"):
        sys.stderr.write("SMHI-NOT-TIFF %d bytes %r\n" % (len(raw or b""), (raw or b"")[:40]))
        return None, False
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = p + ".%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, p)
        return p, True
    except Exception as e:
        sys.stderr.write("SMHI-CACHE-FAILED %r\n" % (e,))
        tmp = os.path.join(tempfile.gettempdir(), "smhi-%d.tif" % os.getpid())
        with open(tmp, "wb") as fh:
            fh.write(raw)
        return tmp, False


def window(path, lng, lat, span_km, cols, rows):
    """-> (levels, nodata_share) for a grid of cells centred on the reader.

    The raster is projected, so this walks the OUTPUT cells and projects each
    one, rather than resampling the input into a shape it is not in. Sampling
    the cell centre is right for a 2 km grid drawn into ~10 km characters.
    """
    import numpy as np
    from PIL import Image
    import utm
    im = Image.open(path)
    e0, n0, scale, w, h = georeference(im)
    a = np.array(im)
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    out = np.zeros((rows, cols), dtype=np.uint8)
    missing = 0
    for r in range(rows):
        cell_lat = lat + half_lat - (2 * half_lat) * (r + 0.5) / rows
        for c in range(cols):
            cell_lng = lng - half_lng + (2 * half_lng) * (c + 0.5) / cols
            e, n = utm.forward(cell_lat, cell_lng)
            px = int((e - e0) / scale)
            py = int((n0 - n) / scale)
            if not (0 <= px < w and 0 <= py < h):
                missing += 1
                continue
            lv = level_of(int(a[py, px]))
            if lv < 0:
                missing += 1
                continue
            out[r, c] = lv
    return out, missing / float(rows * cols)


def frame_time(get=None):
    """-> (unix ts, label) for the frame `latest.tif` currently holds.

    One extra request per refresh cycle, not per reader, and it buys a real
    observation time. Most rows in radar_wms.py have to report our own fetch
    time because a WMS GetMap carries none; SMHI states `valid` for every file
    it publishes, so reporting anything else here would be inventing a worse
    number when a better one was offered.
    """
    import json
    url = ("https://opendata-download-radar.smhi.se/api/version/latest"
           "/area/sweden/product/comp")
    try:
        raw = (get or (lambda u: urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA}), timeout=TIMEOUT).read()))(url)
        d = json.loads(raw)
    except Exception as e:
        sys.stderr.write("SMHI-INDEX-FAILED %r\n" % (e,))
        return None, None
    best = None
    for f in d.get("lastFiles", []):
        if not any(x.get("key") == "tif" for x in f.get("formats", [])):
            continue
        v = f.get("valid")
        if not v:
            continue
        try:
            ts = time.mktime(time.strptime(v, "%Y-%m-%d %H:%M")) - time.timezone
        except Exception:
            continue
        if best is None or ts > best[0]:
            best = (ts, v)
    return best if best else (None, None)


_INDEX = {"bucket": None, "ts": None}


def _frame_ts(get=None):
    b = _bucket()
    if _INDEX["bucket"] == b:
        return _INDEX["ts"]
    ts, _label = frame_time(get)
    _INDEX["bucket"], _INDEX["ts"] = b, ts
    return ts


def draw(code, lng, lat, small=False, get=None, cached_only=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None."""
    if not covers(lng, lat):
        return None
    p = _cache_path(_bucket())
    have = os.path.exists(p) and os.path.getsize(p) > 0
    if cached_only and not have:
        return None          # see radar_wms.draw: never spend a reader's time
    if not have:
        p, _keep = _fetch(get)
        if p is None:
            return None
    ts = _frame_ts(get) if not cached_only else _INDEX.get("ts")
    if ts is None:
        # No stated frame time and we refuse to substitute our own: an age is
        # a promise, and "now" would be a promise we cannot keep.
        sys.stderr.write("SMHI-NO-FRAME-TIME\n")
        return None
    cols, rows = (24, 12) if small else (48, 24)
    span = float(os.environ.get("RUNEMAP_SPAN_KM", "280") or 280)
    try:
        import numpy as np
        levels, share = window(p, lng, lat, span, cols, rows)
    except Exception as e:
        sys.stderr.write("SMHI-WINDOW-FAILED %r\n" % (e,))
        return None
    if share > MAX_NODATA_SHARE:
        # Mostly outside the composite. Drawing it would put a clear sky in
        # front of a reader nobody is looking at -- measured over Oslo: 48%.
        sys.stderr.write("SMHI-MOSTLY-BLIND %.2f,%.2f %.0f%% > %.0f%%\n"
                         % (lng, lat, share * 100, MAX_NODATA_SHARE * 100))
        return None
    from runemap.render import RAMP, OUTSIDE
    grid = [[(RAMP[v] if v >= 0 else OUTSIDE) for v in row] for row in levels.tolist()]
    my, mx = rows // 2, cols // 2
    for i, ch in enumerate(code[:2]):
        if mx + i < cols:
            grid[my][mx + i] = ch
    art = "\n".join("".join(r) for r in grid)
    return art, span / cols, float(ts), None, float(ts), NAME
