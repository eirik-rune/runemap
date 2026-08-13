"""Norway: MET Norway's Nordic reflectivity mosaic, read over OPeNDAP.

Measurements and the georeferencing proof are in
`docs/norway_metno_feasibility.md`. The short version:

* `equivalent_reflectivity_factor`, units stated by the file as dBZ, on a
  1694 x 2134 Lambert conformal conic grid at 1000 m, one frame every 5
  minutes, published about 25 minutes behind.
* The file carries an `is_nodata` mask, so "the radar cannot see here" and
  "there is no rain here" stay two different answers instead of collapsing
  into one empty grid.
* NLOD / CC BY 4.0, and met.no asks for a User-Agent that identifies the
  client and gives a contact address.

**Their PNG endpoint is not used and must not be.** It has coastlines,
national borders, city labels, a graticule and a legend painted onto it, in
colours a classifier reads as echo -- the same reason Czechia's PNG was turned
down. This module reads numbers.

**Nothing is downloaded whole.** A frame is 11.6 MB; a reader needs 48 x 24
samples. OPeNDAP subsets server-side, so one strided request returns about a
thousand numbers. Point-sampling at the cell centre is what every other
adapter in this fleet already does, so this is the same behaviour asked of the
server instead of of the disk.
"""
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dbz                                        # noqa: E402
import lcc                                        # noqa: E402

NAME = "MET Norway"
ATTRIB = "MET Norway thredds.met.no, NLOD / CC BY 4.0"
# met.no asks that clients identify themselves and leave a way to be reached.
UA = "runemap/1.0 (+https://echorune.net; contact luoshu@echorune.net)"
TIMEOUT = 15.0

BASE = ("https://thredds.met.no/thredds/dodsC/remotesensing/"
        "reflectivity-nordic/latest")
PREFIX = ("yrwms-nordic.mos.pcappi-0-dbz.noclass-clfilter-novpr-clcorr-block"
          ".nordiclcc-1000")

# Grid geometry, read off the file's own axes rather than assumed. Yc DECREASES
# with index, which is how row 0 is known to be the north edge -- the assumption
# that, wrong, draws a correctly scaled and freshly stamped map of the wrong
# half of a country.
X0, Y0, CELL = -796000.0, 1125000.0, 1000.0
NX, NY = 1694, 2134

# What the MOSAIC can see -- not who this adapter ought to serve. Those are two
# different questions, and answering them with one number is the mistake this
# fleet keeps meeting: Norway is not a rectangle, and any box holding both
# Finnmark and the south coast also holds Stockholm and Helsinki.
#
# `covers()` therefore answers "can this source see here", honestly, including
# for the neighbours. WHO gets served is the chain's decision, and this adapter
# must be ordered AFTER the national sources for Sweden, Denmark and Finland,
# so it never quietly replaces one of them with a second opinion nobody has
# compared. That ordering is enforced where the chain is built, not here --
# a guard in this file could only lie about the mosaic's real extent.
COVERAGE = (54.5, 0.5, 72.0, 32.0)
# The countries this adapter is being added FOR, recorded so the wiring can be
# checked against an intent rather than against a rectangle.
SERVES = ("NO",)

STEP = 300.0                 # a frame every 5 minutes
LOOKBACK = 12                # 60 minutes of stamps to try, newest first
FRAME_MAX_AGE = 3600.0
MAX_NODATA_SHARE = 0.6
FILL_MIN = 1e30              # _FillValue is 9.96921E36


# Two caches, both small and both shared by every reader in a place.
#
# Without them each reader pays the whole cost -- one discovery walk plus one
# window fetch, measured at ~2.9s -- and met.no pays a request per reader for
# an answer that is identical for all of them. A frame only changes every five
# minutes, so anything shorter than that is spending someone else's bandwidth
# to re-learn a number that did not move.
_LOCK = threading.Lock()
_STAMP = {"stamp": None, "at": 0.0}
_WINDOWS = {}
STAMP_TTL = 60.0
WINDOW_TTL = 150.0
_WINDOW_MAX = 64


def _cached_window(key):
    with _LOCK:
        hit = _WINDOWS.get(key)
    if hit and time.time() - hit[0] < WINDOW_TTL:
        return hit[1]
    return None


def _put_window(key, parsed):
    with _LOCK:
        if len(_WINDOWS) >= _WINDOW_MAX:
            # Oldest out. A cache that only grows is a slow leak in a process
            # that is meant to outlive every request it serves.
            oldest = min(_WINDOWS, key=lambda k: _WINDOWS[k][0])
            _WINDOWS.pop(oldest, None)
        _WINDOWS[key] = (time.time(), parsed)


def forget():
    """Drop both caches. For tests, and for anyone who needs to prove that a
    measurement is not just reading back something this process already had."""
    with _LOCK:
        _WINDOWS.clear()
        _STAMP.update(stamp=None, at=0.0)


def covers(lng, lat):
    s, w, n, e = COVERAGE
    return s <= lat <= n and w <= lng <= e


def stamps(now=None):
    """-> candidate frame stamps, newest first."""
    now = time.time() if now is None else now
    base = math.floor(now / STEP) * STEP
    return [time.strftime("%Y%m%dT%H%M00Z", time.gmtime(base - i * STEP))
            for i in range(LOOKBACK)]


def url_for(stamp, query):
    return "%s/%s.%s.nc.ascii?%s" % (BASE, PREFIX, stamp, query)


def _get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode(
        "utf-8", "replace")


def parse_ascii(text):
    """-> {variable: [[float, ...], ...]} plus {"time": [epoch]}.

    The DODS ascii form is a header, a rule of dashes, then one section per
    variable:

        equivalent_reflectivity_factor.equivalent_reflectivity_factor[1][3][3]
        [0][0], 17.5, 18.5, 27.0
        ...
        equivalent_reflectivity_factor.time[1]
        1786649400
    """
    out = {}
    body = text.split("-" * 20, 1)[-1]
    cur = None
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z_0-9]+)\.([A-Za-z_0-9]+)(\[[\d\]\[]*)?$", line)
        if m:
            cur = m.group(2)
            out.setdefault(cur, [])
            continue
        if cur is None:
            continue
        if line.startswith("["):
            line = line.split(",", 1)[1] if "," in line else ""
        vals = [v.strip() for v in line.split(",") if v.strip()]
        try:
            out[cur].append([float(v) for v in vals])
        except ValueError:
            continue
    return out


def frame_time(parsed):
    """-> epoch seconds of the frame, from the DATA, not from the filename.

    The response carries `time` in seconds since 1970, so the age a reader is
    told does not rest on my having parsed a filename correctly.
    """
    t = parsed.get("time") or []
    for row in t:
        for v in row:
            if v > 1e9:
                return float(v)
    return None


def cell_of(lat, lng):
    """-> (row, col) or None if the point is off the grid."""
    x, y = lcc.forward(lat, lng)
    col = int(round((x - X0) / CELL))
    row = int(round((Y0 - y) / CELL))
    if 0 <= col < NX and 0 <= row < NY:
        return row, col
    return None


def box_for(lng, lat, span_km, cols, rows):
    """-> (r0, r1, rstep, c0, c1, cstep) covering the reader's window.

    The window is stated in latitude and longitude and the grid is a conic
    projection, so the two are not aligned; the box is the bounding box of the
    window's corners, which is slightly generous. Generous is the safe
    direction -- a tight box would drop cells at the edges.
    """
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    pts = []
    for dlat in (half_lat, -half_lat):
        for dlng in (-half_lng, half_lng):
            rc = cell_of(lat + dlat, lng + dlng)
            if rc:
                pts.append(rc)
    if len(pts) < 4:
        return None
    r0, r1 = min(p[0] for p in pts), max(p[0] for p in pts)
    c0, c1 = min(p[1] for p in pts), max(p[1] for p in pts)
    rstep = max(1, (r1 - r0) // max(1, rows))
    cstep = max(1, (c1 - c0) // max(1, cols))
    return r0, r1, rstep, c0, c1, cstep


def fetch_window(stamp, box, get=None):
    """-> parsed sections for reflectivity and the nodata mask, in ONE request.

    Both, always. Asking only for reflectivity would make a blind cell and a
    dry cell arrive as the same number.
    """
    get = get or _get
    r0, r1, rstep, c0, c1, cstep = box
    sl = "[0:1:0][%d:%d:%d][%d:%d:%d]" % (r0, rstep, r1, c0, cstep, c1)
    q = ("equivalent_reflectivity_factor" + sl + ",is_nodata" + sl)
    return parse_ascii(get(url_for(stamp, urllib.parse.quote(q, safe=",:"))))


def newest(get=None, now=None):
    """-> (stamp, parsed) for the newest published frame, or (None, None).

    Walks back from the clock because there is no cheap resolver: `latest.xml`
    500s and `latest/catalog.xml` is 576 entries to learn one name.

    A stamp that is not published yet and a dataset that has moved both answer
    404, so running out of candidates gets its own line in the log and NEVER
    reaches a reader as an empty sky.
    """
    get = get or _get
    probe = ("equivalent_reflectivity_factor[0:1:0][0:1:0][0:1:0],"
             "is_nodata[0:1:0][0:1:0][0:1:0]")
    for stamp in stamps(now):
        try:
            parsed = parse_ascii(get(url_for(stamp, urllib.parse.quote(
                probe, safe=",:"))))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                continue
            sys.stderr.write("METNO-HTTP %s %s\n" % (e.code, stamp))
            return None, None
        except Exception as e:
            sys.stderr.write("METNO-FETCH-FAILED %r\n" % (e,))
            return None, None
        if frame_time(parsed):
            return stamp, parsed
    sys.stderr.write(
        "METNO-NO-FRAME none of the last %d stamps is published -- this is "
        "'I could not find one', not 'the sky is clear'\n" % LOOKBACK)
    return None, None


def level_at(dbz_value, nodata):
    """-> level, or -1 for 'not seen'.

    The floor and the bands come from `scripts/dbz.py`, the fleet's single
    table. Three countries once drew clear-air clutter as light rain because
    each module carried its own copy of it.
    """
    if nodata or dbz_value is None:
        return -1
    if dbz_value >= FILL_MIN:
        # SEEN, and nothing detected -- level 0, not "not seen".
        #
        # Measured, because reading it the other way turns a clear sky into a
        # blind grid and reaches a reader as "no radar here". Oslo: is_nodata
        # 0% while 76% of cells carry _FillValue, scattered as speckle among
        # values like -6.5 dBZ. A blind region is contiguous, not speckled --
        # and the mid-Norwegian Sea, which genuinely is blind, comes back
        # is_nodata 100%. `is_nodata` is the authority on whether the radar
        # can see; the fill value only says nothing was above detection there.
        return 0
    return dbz.level_for(dbz_value)


def window(parsed, box, lng, lat, span_km, cols, rows):
    """-> (levels, nodata_share) for the reader's grid."""
    ref = parsed.get("equivalent_reflectivity_factor") or []
    nod = parsed.get("is_nodata") or []
    if not ref:
        return None, 1.0
    r0, r1, rstep, c0, c1, cstep = box
    nrows, ncols = len(ref), len(ref[0]) if ref else 0
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    out, missing = [], 0
    for r in range(rows):
        cell_lat = lat + half_lat - (2 * half_lat) * (r + 0.5) / rows
        row_out = []
        for c in range(cols):
            cell_lng = lng - half_lng + (2 * half_lng) * (c + 0.5) / cols
            rc = cell_of(cell_lat, cell_lng)
            lv = -1
            if rc:
                jj = int(round((rc[0] - r0) / float(rstep)))
                ii = int(round((rc[1] - c0) / float(cstep)))
                if 0 <= jj < nrows and 0 <= ii < ncols:
                    blind = True
                    if jj < len(nod) and ii < len(nod[jj]):
                        blind = bool(nod[jj][ii])
                    lv = level_at(ref[jj][ii], blind)
            if lv < 0:
                missing += 1
                lv = -1
            row_out.append(lv)
        out.append(row_out)
    return out, missing / float(rows * cols)


def draw(code, lng, lat, small=False, get=None, cached_only=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None."""
    if not covers(lng, lat):
        return None
    cols, rows = (24, 12) if small else (48, 24)
    span = float(os.environ.get("RUNEMAP_SPAN_KM", "280") or 280)
    box = box_for(lng, lat, span, cols, rows)
    if box is None:
        return None
    now = time.time()
    with _LOCK:
        stamp = (_STAMP["stamp"]
                 if now - _STAMP["at"] < STAMP_TTL else None)
    parsed = _cached_window((stamp, box)) if stamp else None
    if parsed is None and cached_only:
        # `cached_only` means "answer from what you already have, and open no
        # socket". Once this window is warm that is a real answer, so refusing
        # outright would keep Norway on the slow path forever -- a guard whose
        # release condition is the very thing it forbids.
        return None
    if stamp is None:
        stamp, _probe = newest(get)
        if not stamp:
            return None
        with _LOCK:
            _STAMP.update(stamp=stamp, at=now)
        parsed = _cached_window((stamp, box))
    if parsed is None:
        try:
            parsed = fetch_window(stamp, box, get)
        except Exception as e:
            sys.stderr.write("METNO-WINDOW-FAILED %r\n" % (e,))
            return None
        _put_window((stamp, box), parsed)
    ts = frame_time(parsed)
    if ts is None:
        sys.stderr.write("METNO-NO-TIME frame carried no time variable\n")
        return None
    age = time.time() - ts
    if age > FRAME_MAX_AGE:
        sys.stderr.write("METNO-FRAME-TOO-OLD age=%.0fs\n" % (age,))
        return None
    levels, share = window(parsed, box, lng, lat, span, cols, rows)
    if levels is None:
        return None
    if share > MAX_NODATA_SHARE:
        sys.stderr.write("METNO-MOSTLY-BLIND %.2f,%.2f %.0f%% > %.0f%%\n"
                         % (lng, lat, share * 100, MAX_NODATA_SHARE * 100))
        return None
    from runemap.render import RAMP, OUTSIDE
    grid = [[(RAMP[v] if v >= 0 else OUTSIDE) for v in row] for row in levels]
    my, mx = rows // 2, cols // 2
    for i, ch in enumerate(code[:2]):
        if mx + i < cols:
            grid[my][mx + i] = ch
    art = "\n".join("".join(r) for r in grid)
    return art, span / cols, float(ts), None, float(ts), NAME
