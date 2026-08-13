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

Coverage is a declared rectangle per service, not something we probe. A service
outside its own country returns an empty image, and an empty image is also what
a dry sky looks like: we would not be able to tell "not covered" from "not
raining", so we do not ask.
"""
import io
import math
import os
import sys
import time
import urllib.parse
import urllib.request

TIMEOUT = float(os.environ.get("RUNEMAP_WMS_TIMEOUT", "6"))

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
    url = url_for(svc, bbox)
    try:
        raw = (get or (lambda u: urllib.request.urlopen(u, timeout=TIMEOUT).read()))(url)
    except Exception as e:
        sys.stderr.write("WMS-FAILED %s %r\n" % (svc["key"], e))
        return None
    if not raw or not raw.startswith(b"\x89PNG"):
        # A WMS reports its errors as XML with a 200. Bytes that are not a PNG
        # are the only reliable tell, and they must not reach the renderer.
        sys.stderr.write("WMS-NOT-PNG %s %d bytes %r\n"
                         % (svc["key"], len(raw or b""), (raw or b"")[:80]))
        return None
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        fh.write(raw)
        p = fh.name
    try:
        from render_scene import ascii_radar
        art, kmcol = ascii_radar(p, bbox, lng, lat,
                                 cols=(24 if small else 48),
                                 rows=(12 if small else 24), marker=code)
    finally:
        os.unlink(p)
    now = time.time()
    return art, kmcol, now, None, now, svc["name"]
