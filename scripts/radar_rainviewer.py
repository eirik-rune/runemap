"""A second radar source, behind the same shape the renderer already eats.

Why this exists: measured 8/13 06:17 UTC, paired in the same instant by Eirik's
ops/paired_ab.py -- mumbai and saopaulo answer {"status":"failed"} with zero
frames upstream while this source has 1665 and 998 precipitation pixels over the
same coordinates. Zero frames is the only state where the reader truly cannot
see rain (a partial 4-frame list still draws a 24-row map), so those two skies
are the whole point.

This module deliberately stops at bytes + bbox. It does not decide whether we
may USE this source: the free tier is "personal or educational use only" and we
are a company, so nothing here is wired into the serve path. A source we are not
licensed for must not be one import away from shipping by accident.

Three things measured rather than assumed, each of which lies quietly if you
guess instead:

 1. The city is usually near a tile SEAM. At z6, mumbai sits at x=0.96 of its
    tile, london 0.98, paris y=0.02. A single-tile fetch renders a map that
    looks perfectly normal with half the rain missing, and nothing anywhere
    reports it. So the tile rectangle is derived from the span we intend to
    draw, never from "one tile ought to be enough".

 2. Zoom 8 is a silent lie. Tiles (177,113), (178,113) and (177,114) at z8 all
    return HTTP 200, 3269 bytes, and byte-identical sha256 -- one image for
    every coordinate. I only caught it because two different cities produced
    identical ink counts (432 vs 432). Nothing errors. MAX_ZOOM is 7 and there
    is a test that fails if someone raises it.

 3. An empty tile is NOT evidence of no coverage; it is also what a dry sky
    looks like. Presence of pixels proves coverage, absence proves nothing.
    plan()/fetch() therefore return what was fetched, and never a verdict.
"""
import io
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor

INDEX_URL = "https://api.rainviewer.com/public/weather-maps.json"
TILE_PX = 512
MAX_ZOOM = 7          # see docstring note 2; not a preference, a measurement
DEFAULT_ZOOM = 7
COLOR = 4             # a blue->green->yellow->red ramp, which is what
OPTIONS = "1_1"       # runemap.render.classify() already keys on


def _to_xy(lat, lon, z):
    """WGS84 -> fractional web-mercator tile coordinates at zoom z."""
    n = 2.0 ** z
    lat = max(-85.05, min(85.05, float(lat)))
    x = (float(lon) + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(math.radians(lat))
                        + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y, n


def _to_lat(y, n):
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))


def plan(lat, lon, span_km, zoom=DEFAULT_ZOOM, max_zoom=None):
    """-> (xs, ys, n): the smallest tile rectangle covering +-span_km/2.

    Derived from the span the renderer will draw, not from a tile count. The
    difference is invisible in the output, which is exactly why it is a rule.
    """
    # The ceiling belongs to the SERVICE, not to this function. MAX_ZOOM is
    # RainViewer's, measured on RainViewer; JMA publishes usable tiles at 8 and
    # nothing but empty ones at 7, so importing this number into that adapter
    # would have drawn a permanently clear Japan. Same shape as copying
    # RainViewer's freshness ceiling onto REDEMET this morning.
    cap = MAX_ZOOM if max_zoom is None else max_zoom
    if zoom > cap:
        raise ValueError("zoom %d is above this service's ceiling %d; for "
                         "RainViewer that level serves one identical tile for "
                         "every coordinate (see module docstring)" % (zoom, cap))
    half_lat = span_km / 2.0 / 111.0
    # cos(lat) shrinks a degree of longitude; clamp so a polar sky cannot ask
    # for the whole globe.
    half_lon = span_km / 2.0 / (111.0 * max(0.2, math.cos(math.radians(lat))))
    x_w, _, n = _to_xy(lat, lon - half_lon, zoom)
    x_e, _, _ = _to_xy(lat, lon + half_lon, zoom)
    _, y_n, _ = _to_xy(min(85.0, lat + half_lat), lon, zoom)
    _, y_s, _ = _to_xy(max(-85.0, lat - half_lat), lon, zoom)
    xs = list(range(int(math.floor(x_w)), int(math.floor(x_e)) + 1))
    ys = list(range(int(math.floor(y_n)), int(math.floor(y_s)) + 1))
    return xs, ys, n


def bbox_of(xs, ys, n):
    """-> (south, west, north, east), the order runemap.render.ascii_radar wants."""
    return (_to_lat(ys[-1] + 1, n), xs[0] / n * 360.0 - 180.0,
            _to_lat(ys[0], n), (xs[-1] + 1) / n * 360.0 - 180.0)


def tile_url(host, path, x, y, z, n):
    return "%s%s/%d/%d/%d/%d/%d/%s.png" % (host, path, TILE_PX, z,
                                           int(x) % int(n), int(y), COLOR, OPTIONS)


def _http_get(url, timeout=10):
    return urllib.request.urlopen(url, timeout=timeout).read()


def fetch(host, path, lat, lon, span_km=280.0, zoom=DEFAULT_ZOOM,
          get=_http_get, workers=8, url_for=None, max_zoom=None, tile_px=None):
    """-> (PIL.Image RGBA, bbox, got, wanted). Missing tiles stay transparent.

    url_for lets another XYZ service reuse this mosaic instead of copying it:
    the seam handling, the thread pool and the bbox arithmetic have one owner,
    and only the URL shape differs. (JMA is the second caller.)

    got < wanted is reported, not raised: a partial mosaic still draws, and the
    caller is the one who knows whether a hole matters. Serial fetching of a
    3x3 measured 7.4-8.1s against a 3s reader budget; this is why the pool.
    """
    from PIL import Image
    xs, ys, n = plan(lat, lon, span_km, zoom, max_zoom=max_zoom)
    # Tile SIZE is per service too, and getting it wrong does not fail: pasting
    # JMA's 256px tiles into RainViewer's 512px cells produced a mosaic with a
    # blank stripe beside every tile, which renders as regular bands of "no
    # rain" and looks like weather.
    px = TILE_PX if tile_px is None else tile_px
    img = Image.new("RGBA", (px * len(xs), px * len(ys)))
    jobs = [(i, j, x, y) for i, x in enumerate(xs) for j, y in enumerate(ys)]

    def one(job):
        i, j, x, y = job
        if not (0 <= y < n):        # off the top/bottom of the world
            return i, j, None
        try:
            build = url_for or (lambda X, Y, Z, N: tile_url(host, path, X, Y, Z, N))
            return i, j, get(build(x, y, zoom, n))
        except Exception:
            return i, j, None

    got = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, j, raw in ex.map(one, jobs):
            if raw:
                img.paste(Image.open(io.BytesIO(raw)).convert("RGBA"),
                          (i * px, j * px))
                got += 1
    return img, bbox_of(xs, ys, n), got, len(jobs)


def frames(index):
    """-> [(ts, path)] oldest first, from an already-fetched index dict.

    Takes the parsed index rather than fetching it, so a caller can decide the
    freshness policy and a test never needs the network.
    """
    return [(int(f["time"]), f["path"])
            for f in (index.get("radar") or {}).get("past") or []]
