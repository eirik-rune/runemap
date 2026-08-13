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

Where a service paints its no-data, though, that distinction becomes visible,
and then we do have to look: DWD's German composite fades out past the border
rather than stopping, so a window can be two thirds their own no-data grey and
still render as a clear sky. `max_nodata_share` declines those, and the reader
gets the sentence they would otherwise be lied to instead of.
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

# The palette of DWD's OTHER radar layer (Niederschlagsradar / the RV product,
# analysis AND forecast in one image). Kept unused and named, because it is the
# table a reader of this file will otherwise rebuild: it is a rain-rate scale,
# it ENDS IN BLUE at >=150 mm/h, and a ramp assuming blue means drizzle gets
# its wettest pixels exactly backwards. The layer we actually ship is the WN
# analysis, whose scale is dBZ -- a different quantity with a different table.
_RV_PALETTE = [("#33ffff", 1), ("#1acc9a", 1), ("#019934", 2), ("#4db31b", 2),
               ("#99cc01", 3), ("#cce601", 3), ("#ffff01", 3), ("#ffc401", 4),
               ("#ff8901", 4), ("#ff4501", 4), ("#fe0000", 5), ("#e5004c", 5),
               ("#cc0098", 5), ("#6600cb", 5), ("#0000fe", 5)]
_DWD_PALETTE = _RV_PALETTE      # the name the DWD tests were written against


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
    {
        "key": "de-dwd-wn",
        "name": "DWD",
        # Their form, not ours. DWD's own template page (vorlagen_
        # quellenangabe.html, under section 7 of the DWD-Gesetz) is explicit
        # that a source note is required even for extracts or a change of data
        # format, and that further modification calls for at least a mention of
        # DWD -- and CC BY 4.0 separately requires indicating changes. A PNG
        # turned into a 48x24 character grid is exactly that modification, so
        # naming them is necessary and not sufficient. Found by Eirik reading
        # the licence pages after this shipped.
        "attrib": "Datenbasis: Deutscher Wetterdienst, Raster veraendert",
        "url": "https://maps.dwd.de/geoserver/dwd/wms",
        # The WN composite is analysis only. The RV layer next to it carries
        # analysis AND forecast in one product, which is a different promise
        # than "what the radar sees now".
        "layers": "dwd:Radar_wn-analysis_1x1km_ger",
        "version": "1.3.0",
        "crs_param": "crs",
        "axis": "yx",
        "coverage": (47.0, 5.8, 55.1, 15.1),
        # Germany was blocked for a day by a magenta (251,0,255) that appears
        # in neither their style document nor their legend. Settled by asking
        # whether it MOVES: two frames 105 minutes apart are pixel-identical in
        # every magenta pixel, at four cities, while the echo around them
        # changed. Rain moves; furniture does not. Over Munich 7071 of 7071
        # visible pixels were static (grey plus this magenta) -- an empty sky
        # painted full -- and over Hamburg the only pixels that moved were the
        # light-rain cyan. It sits 51 counts of green away from their declared
        # 75-85 dBZ pink, which is exactly the near-miss that makes this family
        # dangerous: two almost-equal colours meaning opposite things.
        "nodata_rgb": [(126, 126, 126), (125, 125, 125),
                       (250, 0, 255), (251, 0, 255), (252, 0, 255)],
        # Levels from the dBZ band each colour carries in their SLD, not from
        # the colour itself: <19 dBZ is 1, then 19-28, 28-37, 37-46, and >=46
        # is the top class. Their scale ends in blue-violet-black at the
        # extreme, so reading it by warmth would put a hail core at level 0.
        "palette": [("#99ffff", 1), ("#33ffff", 1), ("#00caca", 1),
                    ("#009934", 1), ("#4dbf1a", 2), ("#99cc00", 2),
                    ("#cce600", 3), ("#ffff00", 3), ("#ffc400", 4),
                    ("#ff8900", 4), ("#ff0000", 5), ("#b40000", 5),
                    ("#4848ff", 5), ("#0000ca", 5), ("#990099", 5),
                    ("#ff33ff", 5), ("#000000", 5)],
        # Their composite fades out past the border rather than stopping, so a
        # window can be mostly their own no-data and still look like a clear
        # sky. Measured: Berlin 0.3%, Strasbourg 4.2%, Zurich 22%, Prague 33%,
        # Copenhagen 37%, Vienna 67%. The line is drawn where a map still has
        # most of its window behind a radar.
        "max_nodata_share": 0.25,
    },
]


# The Netherlands is measured and NOT shipped, for a different reason than
# Germany. KNMI's endpoint is fine (Fees "no conditions apply",
# AccessConstraints "None", and it selects its dataset in the URL, which is why
# _join() exists), but it answers GetStyles with a 500 and its default style is
# greyscale plus red: measured over Amsterdam, 2509 visible pixels are
# white/grey/dark-grey/pink/red. Our default ramp reads white, light grey and
# dark grey all as level 1, so every intensity below "red" would arrive at a
# reader flattened into drizzle. The colours are nameable; what is missing is
# any published mapping from colour to rain rate, and inventing that ordering
# from the look of a legend is the guess this file exists to refuse. The named
# styles they do offer (radar/nearest, precip-rainbow, precip-with-range) are
# the place to start if someone wants to finish this.


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
    return _join(svc["url"], q)


def _join(base, q):
    """Append a query, respecting one the base URL already carries.

    KNMI's endpoint selects its dataset in the URL (?dataset=RADAR), and a
    blind "?" + urlencode produced a second question mark -- a request the
    server answers 422 to. Not hypothetical: it is how the Netherlands failed
    the first time it was asked anything.
    """
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(q)


def nodata_share(raw, svc):
    """How much of this window the service itself says it cannot see.

    Only meaningful for a service that PAINTS its no-data, which is why it is
    computed from the same declared list. Measured on DWD, whose German
    composite reaches past the border and fades out: Berlin 0.3%, Strasbourg
    4.2%, Zurich 22%, Prague 33%, Copenhagen 37%, Vienna 67%. A Viennese
    reader would get a map that is two thirds blind and looks exactly like a
    clear sky -- "not covered" and "not raining" arriving as the same picture,
    which is the failure this whole file keeps circling.
    """
    colours = svc.get("nodata_rgb") or []
    if not colours:
        return 0.0
    import numpy as np
    from PIL import Image
    a = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    hit = np.zeros(a.shape[:2], dtype=bool)
    for r, g, b in colours:
        hit |= (a[..., 0] == r) & (a[..., 1] == g) & (a[..., 2] == b)
    return float(hit.sum()) / float(a.shape[0] * a.shape[1])


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
        cap = svc.get("max_nodata_share")
        if cap is not None:
            share = nodata_share(raw, svc)
            if share > cap:
                # Declining is the honest answer: the chain moves on, and the
                # reader gets the sentence rather than a map that is mostly
                # blind and reads as clear sky.
                sys.stderr.write("WMS-MOSTLY-BLIND %s %.0f%% > %.0f%%\n"
                                 % (svc["key"], share * 100, cap * 100))
                return None
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
