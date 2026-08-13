"""Oblique stereographic, for DMI's Danish composite. Third projection family.

`ops/stereo.py` is the POLAR aspect (lat_0=90), which is what KNMI uses. DMI's
grid is oblique -- `+proj=stere +ellps=WGS84 +lat_0=56 +lon_0=10.5666
+lat_ts=56` -- and the polar formulas do not degrade gracefully into it. They
just draw a plausible map of somewhere else, which is the failure mode this
whole directory keeps meeting: no exception, no empty grid, a picture that
looks like weather over the wrong country.

Formulas are Snyder (1987) for the ellipsoidal oblique stereographic, via the
conformal latitude chi (eq 3-1), forward 21-27..21-30, inverse 21-36..21-38.

    forward(lat, lng) -> (x, y) metres from the projection origin
    inverse(x, y)     -> (lat, lng)

## The control, and what it found

The control is not my arithmetic. DMI states four corner lat/lons in every
file, computed independently of the projection parameters, and the grid states
its own size and cell scale. Measured on `dk.com.202608131320.500_max.h5`:

    UL  (60.0000,  3.0000)  ->  x=-422114.8  y= 469381.0
    UR  (59.8277, 20.7351)  ->  x= 569385.2  y= 469381.0     same y as UL
    LL  (52.2943,  4.3791)  ->  x=-422114.8  y=-394119.0     same x as UL
    LR  (52.2943, 18.8933)  ->  x= 567616.4  y=-379148.4     <-- does not fit

Three of them describe an axis-aligned rectangle 991.5 km x 863.5 km, and the
file says 1984 x 1728 cells at 500 m = 992.0 x 864.0 km. The difference is
exactly one cell in each direction, so **the stated corners are cell CENTRES**,
spanning n-1 cells. That agreement across two independent quantities is what
makes the projection trustworthy here.

**The fourth corner is wrong, and it is wrong in their file, not in this code.**
`LR_lat` is byte-identical to `LL_lat` (52.29427206432812). On an oblique
projection the bottom edge of a projected rectangle is not a line of constant
latitude, so LL and LR cannot share one. Inverting the rectangle-implied corner
gives (52.1592, 18.8933): their longitude is right, their latitude is copied
from the corner next door, and the point they state sits about 15 km north of
the grid's actual corner.

So: build the grid from the projection, the scale and ONE anchor corner, and
use the corners as a check -- `check_corners` below, which returns per-corner
error and is the thing to run when the product changes. Fitting all four would
have quietly tilted the whole grid to accommodate a typo.
"""
import math

A = 6378137.0
F = 1.0 / 298.257223563
B = A * (1.0 - F)
E = math.sqrt(1.0 - (B * B) / (A * A))

LAT_0 = 56.0
LON_0 = 10.5666


def conformal(lat_rad):
    """Snyder eq 3-1: geodetic latitude -> conformal latitude."""
    s = E * math.sin(lat_rad)
    return 2.0 * math.atan(math.tan(math.pi / 4.0 + lat_rad / 2.0)
                           * ((1.0 - s) / (1.0 + s)) ** (E / 2.0)) - math.pi / 2.0


def _m(lat_rad):
    return math.cos(lat_rad) / math.sqrt(1.0 - E * E * math.sin(lat_rad) ** 2)


_CHI0 = conformal(math.radians(LAT_0))
_M0 = _m(math.radians(LAT_0))


def forward(lat, lng):
    """-> (x, y) in metres. Scale is true at lat_ts = lat_0, so k0 = 1."""
    p = math.radians(lat)
    l = math.radians(lng) - math.radians(LON_0)
    c = conformal(p)
    den = math.cos(_CHI0) * (1.0 + math.sin(_CHI0) * math.sin(c)
                             + math.cos(_CHI0) * math.cos(c) * math.cos(l))
    k = 2.0 * A * _M0 / den
    return (k * math.cos(c) * math.sin(l),
            k * (math.cos(_CHI0) * math.sin(c)
                 - math.sin(_CHI0) * math.cos(c) * math.cos(l)))


def inverse(x, y):
    """-> (lat, lng).

    The `cos(chi1)` in `ce` is not optional: leaving it out still round-trips
    nothing and still returns a perfectly plausible latitude -- the first
    version put a Danish corner at 62.7N instead of 60.0N, which reads like a
    small error and is 300 km.
    """
    rho = math.hypot(x, y)
    if rho == 0.0:
        return LAT_0, LON_0
    ce = 2.0 * math.atan(rho * math.cos(_CHI0) / (2.0 * A * _M0))
    c = math.asin(math.cos(ce) * math.sin(_CHI0)
                  + y * math.sin(ce) * math.cos(_CHI0) / rho)
    lng = math.radians(LON_0) + math.atan2(
        x * math.sin(ce),
        rho * math.cos(_CHI0) * math.cos(ce) - y * math.sin(_CHI0) * math.sin(ce))
    p = c
    for _ in range(12):        # conformal -> geodetic, Snyder 3-4
        s = E * math.sin(p)
        p = 2.0 * math.atan(math.tan(math.pi / 4.0 + c / 2.0)
                            * ((1.0 + s) / (1.0 - s)) ** (E / 2.0)) - math.pi / 2.0
    return math.degrees(p), math.degrees(lng)


def assert_proj4(s):
    """Refuse a grid whose projection is not the one these constants describe."""
    if isinstance(s, bytes):
        s = s.decode()
    want = {"proj": "stere", "lat_0": "56", "lon_0": "10.5666", "lat_ts": "56"}
    got = {}
    for tok in s.replace("+", " ").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            got[k] = v
    for k, v in want.items():
        have = got.get(k)
        if have is None:
            raise ValueError("projection has no %s: %r" % (k, s))
        try:
            same = abs(float(have) - float(v)) < 1e-4
        except ValueError:
            same = have == v
        if not same:
            raise ValueError("projection %s is %r, these constants assume %r"
                             % (k, have, v))
    return True


def check_corners(corners, cols, rows, scale, anchor="UL"):
    """-> list of (name, metres off) for each stated corner.

    Builds the grid from the projection, the cell scale and ONE anchor corner,
    then measures every stated corner against it. Fitting all four instead
    would silently tilt the grid to accommodate a bad one -- and DMI ships a
    bad one: LR_lat is a copy of LL_lat, about 15 km out.

    `corners` is the ODIM `/where` mapping (LL_lat, LL_lon, UL_lat, ...).
    Corners are treated as cell CENTRES, which is what makes (n-1)*scale match
    their span.
    """
    ax, ay = forward(corners[anchor + "_lat"], corners[anchor + "_lon"])
    w = (cols - 1) * scale
    h = (rows - 1) * scale
    at = {"UL": (ax, ay), "UR": (ax + w, ay),
          "LL": (ax, ay - h), "LR": (ax + w, ay - h)}
    out = []
    for name in ("UL", "UR", "LL", "LR"):
        sx, sy = forward(corners[name + "_lat"], corners[name + "_lon"])
        ex, ey = at[name]
        out.append((name, math.hypot(sx - ex, sy - ey)))
    return out
