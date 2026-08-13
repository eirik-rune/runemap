"""The Netherlands, from KNMI's 5-minute reflectivity composite.

This country was refused once, and the refusal was wrong in an instructive way:
I had gone at it through their WMS, where colour and value are not registered to
the same cell and every colour sampled back as the same sentinel rain rate. The
conclusion I drew was "the Netherlands cannot be done honestly". The true
statement was "**the route I had was wrong, not the service**" -- the same
sentence already written next to Czechia. KNMI publishes the underlying grid as
ODIM-style HDF5 on their Data Platform, in dBZ, with the calibration in the file.

Licence: CC BY 4.0, machine-readable in the Dutch national catalogue
(data.overheid.nl), on the dataset whose own resource link is
`x-dataset=radar_reflectivity_composites&x-dataset-version=2.0` -- which is the
dataset this module fetches. The join between "the entry I read" and "the files
I take" is that link, and it is stated here so it can be checked rather than
believed. Radars: Herwijnen and Den Helder; reflectivity at 1500 m.

Access: KNMI issues an **anonymous** API key, published on their developer
portal, which "provides unregistered access to open data" and is shared among
unregistered users (50 req/min, 3000/hour, shared; the current one expires
2027-08-01). That is a sanctioned path, taken as offered -- no account, no
claiming to be a person. We use one request per five-minute cycle, cached and
shared by every reader, which is nothing against a shared hourly quota.

What the file states about itself, and what this module therefore does not
restate:

    image_geo_parameter   REFLECTIVITY_[DBZ]     asserted, because the same
                          container carries other quantities
    calibration_formulas  "GEO = 0.500000 * PV + -32.000000"   parsed
    calibration_missing_data / _out_of_image     0 / 255, two different facts
    geo_pixel_def         LU        first row is the north edge -- stated,
                          unlike the Czech product where it had to be measured
    geo_product_corners   four lat/lons, used as the control on the projection
"""
import errno
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "ops")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NAME = "KNMI"
# Who this source is added FOR, as opposed to what it can SEE.
# covers() answers the second question and must not be read as the
# first: a box that holds all of the Netherlands holds neighbours too.
SERVES = ("NL",)
ATTRIB = "KNMI dataplatform.knmi.nl, CC BY 4.0"
DATASET = "radar_reflectivity_composites"
VERSION = "2.0"
API = ("https://api.dataplatform.knmi.nl/open-data/v1/datasets/%s/versions/%s/files"
       % (DATASET, VERSION))
PREFIX = "RAD_NL25_PCP_NA_"
UA = "runemap/1.0 (+https://echorune.net)"
TIMEOUT = 12.0

STEP = 300.0
FRAME_MAX_AGE = 1800.0
LOOKBACK = 6

# The composite reaches well past the Netherlands -- its own corners run
# 48.9-56.0N and 0-10.9E, and it really does see Belgium, the German bight and
# part of the North Sea. DWD is asked before this module, so Germany is answered
# by its own service; Belgium has no service of its own that will serve us
# (advertised, then 403), so drawing it here from a composite that genuinely
# observes it is better than the sentence saying we cannot.
COVERAGE = (49.4, 0.0, 55.9, 10.8)
# How stale a cached frame may be before the (three-request, shared-quota)
# discovery path runs instead. Two slots is ten minutes.
CACHE_ACCEPT_SLOTS = 2
MAX_NODATA_SHARE = 0.25

CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(tempfile.gettempdir(),
                                                        "runemap")
KEY_FILE = os.environ.get("RUNEMAP_KNMI_KEY_FILE",
                          os.path.expanduser("~/.config/runemap/knmi_key"))


def covers(lng, lat):
    s, w, n, e = COVERAGE
    return s <= lat <= n and w <= lng <= e


def key_status():
    """-> (key or None, reason or None). Env first, then a file.

    "There is no key here" and "the key is right there and I am not allowed to
    read it" used to return the same None, and the probe printed the same
    sentence for both -- which sends the next hour to the wrong place. That is
    exactly what happened on 8/13: the fleet was healthy, production was
    serving Amsterdam, and running the probe as a user who cannot read a
    root-owned 0640 file reported it as a missing key.

    The reason NEVER carries the file's contents, only errno's word for why.
    """
    k = os.environ.get("RUNEMAP_KNMI_KEY")
    if k and k.strip():
        return k.strip(), None
    try:
        with open(KEY_FILE) as fh:
            k = fh.read().strip()
        return (k, None) if k else (None, "empty")
    except FileNotFoundError:
        return None, "absent"
    except PermissionError:
        return None, "unreadable"
    except OSError as exc:
        return None, "unreadable(%s)" % (errno.errorcode.get(exc.errno, "?"),)


def api_key():
    """-> the key, or None. Never passed as a command argument."""
    return key_status()[0]


def have_h5py():
    try:
        import h5py           # noqa: F401
        return True
    except Exception:
        return False


def unavailable():
    """-> a sentence if this source cannot work here at all, else None.

    Two different absences, both of which would otherwise reach the reader as
    an empty grid and the health probe as NO-MAP -- pointing an investigation at
    an upstream that is answering perfectly.
    """
    if not have_h5py():
        return "h5py is not installed (pip install 'runemap[hdf5]')"
    key, why = key_status()
    if key:
        return None
    if why in ("unreadable", "empty") or (why or "").startswith("unreadable("):
        # Not a configuration gap -- a permissions one, and the cure is to run
        # as whoever production runs as, not to go looking for a key.
        return ("KNMI key at %s is %s by this user (production reads it as its "
                "own user; check with the service, not the source)"
                % (KEY_FILE, "empty" if why == "empty" else "not readable"))
    return ("no KNMI key: set RUNEMAP_KNMI_KEY or put their published"
            " anonymous key in %s" % (KEY_FILE,))


def stamps(now=None):
    t = time.time() if now is None else now
    base = math.floor(t / STEP) * STEP
    return [time.strftime("%Y%m%d%H%M", time.gmtime(base - i * STEP))
            for i in range(LOOKBACK)]


def frame_ts(stamp):
    return time.mktime(time.strptime(stamp, "%Y%m%d%H%M")) - time.timezone


def _cache_path(stamp):
    key = "knmi-%s|%s" % (DATASET, stamp)
    return os.path.join(CACHE, "knmi-" + hashlib.sha1(key.encode()).hexdigest() + ".h5")


def _get(url, key=None, timeout=TIMEOUT):
    h = {"User-Agent": UA}
    if key:
        h["Authorization"] = key
    return urllib.request.urlopen(urllib.request.Request(url, headers=h),
                                  timeout=timeout).read()


class RateLimited(Exception):
    """Their 429 means what it says, unlike some other services' 429.

    Worth naming, because the hub's 429 is an authentication failure wearing a
    rate limit's clothes, and treating this one the same way -- retry, it will
    pass -- is how a client turns a queue into a stampede.
    """


def newest_frame(key, get=None):
    """-> the newest published filename, in ONE request.

    The first version of this walked candidate timestamps and asked for each in
    turn, which is six requests to discover one file, and it ran straight into
    the shared quota. The listing endpoint will name the newest file directly;
    asking the question once is both the correct client and the polite one.
    """
    g = get or (lambda u, k=None: _get(u, k))
    url = API + "?maxKeys=1&sorting=desc&orderBy=created"
    try:
        d = json.loads(g(url, key))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited("listing")
        sys.stderr.write("KNMI-LIST-FAILED %r\n" % (e,))
        return None
    except Exception as e:
        sys.stderr.write("KNMI-LIST-FAILED %r\n" % (e,))
        return None
    files = d.get("files") or []
    if not files:
        sys.stderr.write("KNMI-LIST-EMPTY\n")
        return None
    return files[0].get("filename")


def stamp_of(filename):
    """-> the 'YYYYMMDDhhmm' in a published filename, or None."""
    m = re.search(re.escape(PREFIX) + r"(\d{12})\.h5$", filename or "")
    return m.group(1) if m else None


def download(stamp, key, get=None):
    """-> raw bytes for one frame, or None. Raises RateLimited on a 429.

    Their download is two steps: ask for a temporary URL, then fetch it. The
    second request must NOT carry the key -- it is a signed URL, and sending
    credentials to it is both unnecessary and a way to leak them into somebody
    else's logs.
    """
    fn = PREFIX + stamp + ".h5"
    g = get or (lambda u, k=None: _get(u, k))
    try:
        meta = json.loads(g(API + "/" + fn + "/url", key))
        url = meta["temporaryDownloadUrl"]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(stamp)
        sys.stderr.write("KNMI-NO-URL %s %r\n" % (stamp, e))
        return None
    except Exception as e:
        sys.stderr.write("KNMI-NO-URL %s %r\n" % (stamp, e))
        return None
    try:
        raw = g(url, None)
    except Exception as e:
        sys.stderr.write("KNMI-FETCH-FAILED %s %r\n" % (stamp, e))
        return None
    if not raw or raw[:8] != b"\x89HDF\r\n\x1a\n":
        sys.stderr.write("KNMI-NOT-HDF5 %s %d bytes\n" % (stamp, len(raw or b"")))
        return None
    return raw


def _store(stamp, raw):
    p = _cache_path(stamp)
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = p + ".%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, p)
        return p
    except Exception as e:
        sys.stderr.write("KNMI-CACHE-FAILED %r\n" % (e,))
        tmp = os.path.join(tempfile.gettempdir(), "knmi-%d.h5" % os.getpid())
        with open(tmp, "wb") as fh:
            fh.write(raw)
        return tmp


def parse_calibration(formula):
    """'GEO = 0.500000 * PV + -32.000000' -> (gain, offset).

    Parsed rather than restated. It happens to be 0.5 / -32.0 today, the same
    pair Czechia and Denmark use and NOT Sweden's 0.4 / -30.0 -- and a copied
    constant that later disagrees with the file draws the right map at the wrong
    intensity, which looks entirely normal.
    """
    if isinstance(formula, bytes):
        formula = formula.decode()
    m = re.search(r"GEO\s*=\s*([-\d.eE+]+)\s*\*\s*PV\s*\+\s*([-\d.eE+]+)", formula)
    if not m:
        raise ValueError("cannot read calibration %r" % (formula,))
    return float(m.group(1)), float(m.group(2))


def read(path):
    """-> (array, scale, geo) from the file's own attributes."""
    import h5py
    import stereo
    with h5py.File(path, "r") as f:
        img = f["/image1"]
        param = img.attrs.get("image_geo_parameter")
        if isinstance(param, bytes):
            param = param.decode()
        if param != "REFLECTIVITY_[DBZ]":
            raise ValueError("expected REFLECTIVITY_[DBZ], got %r" % (param,))
        cal = f["/image1/calibration"].attrs
        gain, offset = parse_calibration(cal["calibration_formulas"])
        missing = float(cal["calibration_missing_data"][0])
        outside = float(cal["calibration_out_of_image"][0])
        g = f["/geographic"].attrs
        proj = f["/geographic/map_projection"].attrs["projection_proj4_params"]
        stereo.assert_proj4(proj)
        pd = g["geo_pixel_def"]
        if (pd.decode() if isinstance(pd, bytes) else pd) != "LU":
            raise ValueError("pixel origin is %r, not the left-upper this reads" % (pd,))
        geo = {"cols": int(g["geo_number_columns"][0]),
               "rows": int(g["geo_number_rows"][0]),
               "px": abs(float(g["geo_pixel_size_x"][0])),
               "py": abs(float(g["geo_pixel_size_y"][0])),
               "col0": float(g["geo_column_offset"][0]),
               "row0": float(g["geo_row_offset"][0]),
               "corners": [float(v) for v in g["geo_product_corners"]]}
        arr = f["/image1/image_data"][:]
        end = f["/overview"].attrs.get("product_datetime_end")
    scale = {"gain": gain, "offset": offset,
             "missing": missing, "outside": outside}
    return arr, scale, geo, (end.decode() if isinstance(end, bytes) else end)


def level_of(pv, scale):
    """Pixel value -> our 0-5 scale, or -1 for "not looked at".

    KNMI names the two absences separately and so does this: `missing` is no
    echo, `out_of_image` is outside the composite. Only the first one means no
    rain, and a sentinel that can be mistaken for zero is how this whole fleet
    fails invisibly.
    """
    if pv == scale["outside"]:
        return -1
    if pv == scale["missing"]:
        return 0
    import dbz as _dbz
    return _dbz.level_for(scale["gain"] * pv + scale["offset"])


def cell_of(geo, lat, lng):
    """-> (col, row) for a sky, or None if it falls outside the grid."""
    import stereo
    x, u = stereo.forward(lat, lng)
    col = int(x / geo["px"] - geo["col0"])
    row = int((u - geo["row0"]) / geo["py"])
    if 0 <= col < geo["cols"] and 0 <= row < geo["rows"]:
        return col, row
    return None


def window(arr, scale, geo, lng, lat, span_km, cols, rows):
    """-> (levels, nodata_share), walking OUTPUT cells into the grid."""
    import numpy as np
    half_lat = (span_km / 2.0) / 111.32
    half_lng = half_lat / max(0.2, math.cos(math.radians(lat)))
    out = np.zeros((rows, cols), dtype=np.int16)
    missing = 0
    for r in range(rows):
        cell_lat = lat + half_lat - (2 * half_lat) * (r + 0.5) / rows
        for c in range(cols):
            cell_lng = lng - half_lng + (2 * half_lng) * (c + 0.5) / cols
            at = cell_of(geo, cell_lat, cell_lng)
            if at is None:
                missing += 1
                continue
            lv = level_of(int(arr[at[1], at[0]]), scale)
            if lv < 0:
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
        sys.stderr.write("KNMI-UNAVAILABLE %s\n" % (why,))
        return None
    cand = stamps()
    # Same ceiling as DMI, and for the same reason -- but NOT the same fix as
    # MeteoSwiss: this key's quota is shared with every unregistered user, so
    # the discovery path below stays exactly three requests and must never
    # become a loop over candidates. Bounding what the cache may answer costs
    # nothing extra upstream.
    if not cached_only:
        cand = cand[:CACHE_ACCEPT_SLOTS]
    path = ts = None
    for stamp in cand:
        p = _cache_path(stamp)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            path, ts = p, frame_ts(stamp)
            break
    if path is None:
        if cached_only:
            return None      # see radar_wms.draw: never spend a reader's time
        key = api_key()
        # Three requests per cycle, shared by every reader: ask which file is
        # newest, ask for its URL, fetch it. Never a loop over candidates --
        # the anonymous key's quota is SHARED with every other unregistered
        # user of this platform, so a burst here is not our own budget being
        # spent, it is everyone's. On 429 we stop immediately rather than
        # walking down the list making it worse.
        try:
            fn = newest_frame(key, get)
            stamp = stamp_of(fn)
            if stamp is None:
                sys.stderr.write("KNMI-NO-FRAME listing gave %r\n" % (fn,))
                return None
            raw = download(stamp, key, get)
        except RateLimited as e:
            sys.stderr.write("KNMI-RATE-LIMITED %s -- the anonymous key is"
                             " shared; backing off rather than retrying\n" % (e,))
            return None
        if raw is None:
            return None
        path, ts = _store(stamp, raw), frame_ts(stamp)
    if path is None:
        sys.stderr.write("KNMI-NO-FRAME newest tried %s\n" % (cand[0],))
        return None
    age = time.time() - ts
    if age > FRAME_MAX_AGE:
        sys.stderr.write("KNMI-FRAME-TOO-OLD age=%.0fs\n" % (age,))
        return None
    try:
        arr, scale, geo, _end = read(path)
    except Exception as e:
        sys.stderr.write("KNMI-READ-FAILED %r\n" % (e,))
        return None
    cols, rows = (24, 12) if small else (48, 24)
    span = float(os.environ.get("RUNEMAP_SPAN_KM", "280") or 280)
    try:
        levels, share = window(arr, scale, geo, lng, lat, span, cols, rows)
    except Exception as e:
        sys.stderr.write("KNMI-WINDOW-FAILED %r\n" % (e,))
        return None
    if share > MAX_NODATA_SHARE:
        sys.stderr.write("KNMI-MOSTLY-BLIND %.2f,%.2f %.0f%% > %.0f%%\n"
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
