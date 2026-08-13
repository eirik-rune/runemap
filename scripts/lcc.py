"""Tangent Lambert conformal conic on a sphere, for MET Norway's Nordic grid.

The parameters are not chosen here. The file states them itself:

    +proj=lcc +lat_0=63 +lon_0=15 +lat_1=63 +lat_2=63 +no_defs +R=6.371e+06

lat_1 == lat_2, so this is the tangent case (one standard parallel), and R is
given, so there is no ellipsoid to get wrong. `assert_proj4` exists so that a
day when met.no changes the grid fails loudly here instead of drawing a
scale-correct map of somewhere else -- the same reason `stereo_oblique` has one.
"""
import math

R = 6.371e6
LAT_0 = 63.0
LON_0 = 15.0
LAT_1 = 63.0

_n = math.sin(math.radians(LAT_1))
_F = (math.cos(math.radians(LAT_1))
      * math.tan(math.pi / 4 + math.radians(LAT_1) / 2) ** _n / _n)


def _rho(lat_deg):
    return R * _F / math.tan(math.pi / 4 + math.radians(lat_deg) / 2) ** _n


_RHO_0 = _rho(LAT_0)


def forward(lat, lng):
    """-> (x, y) in metres on the projection plane."""
    theta = _n * (math.radians(lng) - math.radians(LON_0))
    r = _rho(lat)
    return r * math.sin(theta), _RHO_0 - r * math.cos(theta)


def inverse(x, y):
    """-> (lat, lng). Only used to check the forward transform against the
    file's own coordinates, which is the whole point of having it."""
    dy = _RHO_0 - y
    r = math.hypot(x, dy) * (1 if _n >= 0 else -1)
    theta = math.atan2(x, dy)
    lat = 2 * math.atan((R * _F / r) ** (1 / _n)) - math.pi / 2
    return math.degrees(lat), LON_0 + math.degrees(theta / _n)


def assert_proj4(s):
    """-> True, or raise. The grid this module can read is one specific grid.

    A projection mismatch does not fail: it draws a fresh-stamped, correctly
    scaled picture of the wrong place. So the string the file carries is
    compared against what these constants assume, term by term.
    """
    want = {"proj": "lcc", "lat_0": LAT_0, "lon_0": LON_0,
            "lat_1": LAT_1, "lat_2": LAT_1, "R": R}
    got = {}
    for tok in s.split():
        if not tok.startswith("+") or "=" not in tok:
            continue
        k, v = tok[1:].split("=", 1)
        got[k] = v
    for k, v in want.items():
        if k not in got:
            raise ValueError("proj4 does not state %s: %r" % (k, s))
        if k == "proj":
            if got[k] != v:
                raise ValueError("projection is %r, not %r" % (got[k], v))
        elif abs(float(got[k]) - v) > 1e-6 * max(1.0, abs(v)):
            raise ValueError("%s is %s, expected %s" % (k, got[k], v))
    return True
