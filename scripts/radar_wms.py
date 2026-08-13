"""National radars that answer in the shape we actually want: give a bbox, get
that bbox.

A WMS server renders the rectangle you ask for, so this adapter has no tiles, no
stitching, no seam to fall on, and no zoom level to be lied to about. Every new
country is one row in SERVICES rather than a new file. Measured 8/13 from the
production box: 0.88-1.18s per frame at ~5.8 km per column, which is finer than
the global composite.

The one thing a WMS will do to you quietly:

    WMS 1.1.1  bbox = minlon,minlat,maxlon,maxlat   (x first)
    WMS 1.3.0  bbox = minlat,minlon,maxlat,maxlon   for EPSG:4326 (y first!)

Get that backwards and the server still answers 200 with a perfectly valid PNG
of the wrong place -- somewhere in the ocean, usually transparent, which reads
as "no rain here". So the axis order is a field per service, not a convention,
and there is a test that pins each one.

Rectangles overlap and cannot be made not to: the US box reaches into southern
Ontario, so Toronto is served by NEXRAD rather than by Environment Canada. That
is documented rather than fixed because it is not wrong -- NEXRAD's beams really
do cross the border and the credit line names them correctly -- and because the
alternative rectangle would hand Detroit and Seattle to Canada. The first
matching service wins, so the order of SERVICES is the tie-break, and there is a
test pinning that Toronto lands on NEXRAD on purpose.

Some services PAINT their zeros. DWD's radar layers fill everything they can
see -- and everything they cannot -- with grey (126,126,126); over Paris that is
100% of the image. Our classifier reads any visible pixel as at least drizzle,
so adopting such a layer unchecked would draw a screen full of rain that is not
there, and it would look completely normal. Hence `nodata_rgb` per service, a
required field with no default, and hence a service may carry a `palette`: an exact
colour -> intensity table taken from the server's OWN style document
(`ops/wms_palette.py` reads it via GetStyles), not from looking at a picture and
guessing. DWD needs one because its scale runs cyan-green-yellow-red-magenta-
blue, and our default ramp reads its magenta as a storm and its blue as nothing.

Coverage is a declared rectangle per service, not something we probe. A service
outside its own country returns an empty image, and an empty image is also what
a dry sky looks like: we would not be able to tell "not covered" from "not
raining", so we do not ask.
"""
import hashlib
import io
import math
import os
import sys
import time
import urllib.parse
import urllib.request

TIMEOUT = float(os.environ.get("RUNEMAP_WMS_TIMEOUT", "6"))

# Kept, unused, deliberately: the machinery is right and the service is not
# ready. Over Hamburg, 43% of the visible pixels after stripping their grey are
# a magenta (251,0,255) that appears in neither the server's own
# style document (GetStyles: 17 ColorMapEntry rows, grey through blue) nor its
# own legend image (GetLegendGraphic: the same 16 swatches). Asking with an
# explicit &time= for the latest 5-minute step returns the same colours, so it
# is not a forecast frame either
# -- so we do not know what it means, and a colour we cannot name must not be
# drawn for a reader as rain. When that is explained, this table and the row
# below it are what turns DWD on.
#
# _DWD_SERVICE = '    {\n        "key": "de-dwd",\n        "name": "DWD",\n      '... (see git history for the full row)
#
# DWD's own SLD, fetched with ops/wms_palette.py: colour -> our 0-5 level, by
# the rain rate their legend attaches to each colour. Their scale ENDS in blue
# (>=150 mm/h), so a ramp that assumes blue means drizzle gets the wettest
# pixels on the map exactly backwards.
_DWD_PALETTE = [("#33ffff", 1), ("#1acc9a", 1), ("#019934", 2), ("#4db31b", 2),
                ("#99cc01", 3), ("#cce601", 3), ("#ffff01", 3), ("#ffc401", 4),
                ("#ff8901", 4), ("#ff4501", 4), ("#fe0000", 5), ("#e5004c", 5),
                ("#cc0098", 5), ("#6600cb", 5), ("#0000fe", 5)]


def _rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def classify_palette(arr, palette, max_dist=40):
    """RGBA array -> 0-5 levels by nearest declared colour.

    Nearest rather than exact because PNG quantisation moves a colour by a
    point or two (measured: DWD magenta arrived as both 252,0,255 and
    251,0,255). Anything further than max_dist from every declared colour is
    left at 0: an unrecognised colour is furniture we were not told about, and
    guessing it is how a legend gets read backwards.
    """
    import numpy as np
    # int32, not int16: a squared channel difference reaches 65025 and int16
    # wraps negative, which turns "furthest colour" into "nearest" silently.
    # Measured: DWD magenta, 113 away from the closest declared colour, came
    # back as level 1 for 166 pixels before this cast.
    a = arr[..., :3].astype(np.int32)
    out = np.zeros(a.shape[:2], dtype=np.uint8)
    best = np.full(a.shape[:2], 1e9, dtype=np.float32)
    for h, lvl in palette:
        r, g, b = _rgb(h)
        d = ((a[..., 0] - r) ** 2 + (a[..., 1] - g) ** 2 + (a[..., 2] - b) ** 2)
        take = d < best
        best = np.where(take, d, best)
        out = np.where(take, lvl, out)
    out[best > max_dist ** 2] = 0
    out[arr[..., 3] <= 50] = 0
    return out


SERVICES = [
    {
        "key": "us-nexrad",
        "name": "NWS NEXRAD",
        "attrib": "NWS NEXRAD via mesonet.agron.iastate.edu",
        "url": "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q.cgi",
        "layers": "nexrad-n0q-900913",
        "version": "1.1.1",
        "crs_param": "srs",
        "axis": "xy",
        # continental US plus a margin; Alaska and Hawaii are separate layers
        # and are deliberately not claimed here rather than half-claimed.
        "coverage": (24.0, -125.0, 50.0, -66.0),
        # Colours that mean "we have no echo here", which this server does not
        # paint. Required, never defaulted: see the note above.
        "nodata_rgb": [],
    },
    {
        "key": "ca-geomet",
        "name": "Environment Canada",
        "attrib": "Environment and Climate Change Canada geo.weather.gc.ca",
        "url": "https://geo.weather.gc.ca/geomet",
        "layers": "RADAR_1KM_RRAI",
        "version": "1.3.0",
        "crs_param": "crs",
        "axis": "yx",
        "coverage": (41.0, -141.0, 70.0, -52.0),
        "nodata_rgb": [],
    },
    {
        "key": "fi-fmi",
        "name": "FMI",
        "attrib": "Finnish Meteorological Institute en.ilmatieteenlaitos.fi",
        "url": "https://openwms.fmi.fi/geoserver/Radar/wms",
        "layers": "suomi_dbz_eureffin",
        "version": "1.3.0",
        "crs_param": "crs",
        "axis": "yx",
        # Their own capabilities document says Fees NONE, AccessConstraints
        # NONE. The declared latitude band is 56.75-71.27; the longitude band
        # reads -180..180, which is a projection artefact rather than a claim,
        # so the rectangle here is the one their radars actually stand in.
        "coverage": (59.0, 19.0, 70.5, 32.0),
        "nodata_rgb": [],
        # Their scale ends in pink (#fa51a5), so the default cool-to-warm
        # heuristic would read Finland's heaviest echo as almost nothing --
        # the same trap DWD sets, and the reason a palette is not optional
        # here. Levels come from the quantities and labels in their own SLD
        # (kohtalainen = moderate, sakea = dense, hyvin sakea = very dense),
        # read by ops/wms_palette.py, not from looking at the picture.
        "palette": [("#6cebf3", 1), ("#58c797", 1), ("#409857", 2),
                    ("#f1f35a", 2), ("#dfc40a", 3), ("#eb951a", 3),
                    ("#e85616", 4), ("#ce0202", 4), ("#830a46", 5),
                    ("#fa51a5", 5)],
    },
]


def service_for(lng, lat):
    for s in SERVICES:
        a, b, c, d = s["coverage"]
        if a <= lat <= c and b <= lng <= d:
            return s
    return None


def bbox_for(lat, lng, span_km=280.0):
    """-> (south, west, north, east), the order ascii_radar wants."""
    d_lat = span_km / 2.0 / 111.0
    d_lon = span_km / 2.0 / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return (lat - d_lat, lng - d_lon, lat + d_lat, lng + d_lon)


def url_for(svc, bbox, px=768):
    s, w, n, e = bbox
    order = "%f,%f,%f,%f" % ((w, s, e, n) if svc["axis"] == "xy" else (s, w, n, e))
    q = {"service": "WMS", "version": svc["version"], "request": "GetMap",
         "layers": svc["layers"], "styles": "", "format": "image/png",
         "transparent": "true", svc["crs_param"]: "EPSG:4326",
         "bbox": order, "width": str(px), "height": str(px)}
    return svc["url"] + "?" + urllib.parse.urlencode(q)


def _strip_nodata(raw, svc):
    """Make a service's painted zeros transparent again.

    A no-data fill and light rain are the same thing to the renderer: both are
    visible pixels. Whoever adds a service is the one who knows which colours
    are furniture, so the list is theirs to declare and empty means "this
    server paints nothing", not "nobody looked".
    """
    colours = svc.get("nodata_rgb")
    if colours is None:
        raise KeyError("%s must declare nodata_rgb (empty list is an answer)"
                       % svc["key"])
    if not colours:
        return raw
    import numpy as np
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    a = np.array(im)
    for r, g, b in colours:
        hit = (a[..., 0] == r) & (a[..., 1] == g) & (a[..., 2] == b)
        a[hit, 3] = 0
    out = io.BytesIO()
    Image.fromarray(a).save(out, format="PNG")
    return out.getvalue()


REFRESH = float(os.environ.get("RUNEMAP_WMS_REFRESH", "300"))
CACHE = os.environ.get("RUNEMAP_CACHE") or os.path.join(
    __import__("tempfile").gettempdir(), "runemap")


def _bucket(now=None):
    """Which of their refresh cycles we are in.

    A WMS GetMap carries no timestamp, so there is no frame id to key a cache
    on. Both shipped services refresh about every five minutes, so the cycle
    number is the closest thing to a frame identity that exists -- and it is
    honest in the direction that matters: within one bucket every reader sees
    the same picture, and the age we print is already an underestimate.
    """
    return int((time.time() if now is None else now) // REFRESH)


def _cache_path(svc, lat, lng, bucket):
    key = "%s|%.1f,%.1f|%d" % (svc["key"], round(lat, 1), round(lng, 1), bucket)
    return os.path.join(CACHE, "wms-" + hashlib.sha1(key.encode()).hexdigest() + ".png")


def draw(code, lng, lat, small=False, get=None):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None.

    ts is our fetch time, not the radar's scan time: a WMS GetMap carries no
    timestamp, and inventing one would be the sharper lie. It is honest to
    within the service's own refresh (~5 min for both of these) and the age we
    print is therefore an underestimate of staleness, never an overestimate.
    """
    svc = service_for(lng, lat)
    if svc is None:
        return None
    bbox = bbox_for(lat, lng)
    # One fetch per sky per refresh cycle, not one per visitor. Measured before
    # this cache: every Helsinki reader paid 1.3-1.9s and a fresh GetMap to
    # FMI, while the answer I gave for "do we push a cost onto them" was "a
    # prefetch behind a cache is lighter than one person with a browser". That
    # answer has to be true in the code, not in the document.
    cached = _cache_path(svc, lat, lng, _bucket())
    p, keep = None, False
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        p, keep = cached, True
    if p is None:
        url = url_for(svc, bbox)
        try:
            raw = (get or (lambda u: urllib.request.urlopen(u, timeout=TIMEOUT).read()))(url)
        except Exception as e:
            sys.stderr.write("WMS-FAILED %s %r\n" % (svc["key"], e))
            return None
        if not raw or not raw.startswith(b"\x89PNG"):
            # A WMS reports its errors as XML with a 200. Bytes that are not a
            # PNG are the only reliable tell, and they must not reach the
            # renderer -- nor the cache, or one bad minute would be served for
            # the rest of the cycle.
            sys.stderr.write("WMS-NOT-PNG %s %d bytes %r\n"
                             % (svc["key"], len(raw or b""), (raw or b"")[:80]))
            return None
        import tempfile
        raw = _strip_nodata(raw, svc)
        try:
            os.makedirs(CACHE, exist_ok=True)
            tmp = cached + ".%d" % os.getpid()
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, cached)     # never let a half-written frame be read
            p, keep = cached, True
        except Exception as e:
            sys.stderr.write("WMS-CACHE-FAILED %r\n" % (e,))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                fh.write(raw)
                p = fh.name
    try:
        from render_scene import ascii_radar
        pal = svc.get("palette")
        art, kmcol = ascii_radar(
            p, bbox, lng, lat, cols=(24 if small else 48),
            rows=(12 if small else 24), marker=code,
            classifier=((lambda a: classify_palette(a, pal)) if pal else None))
    finally:
        if not keep:
            os.unlink(p)
    now = time.time()
    return art, kmcol, now, None, now, svc["name"]
