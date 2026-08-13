"""Polar stereographic, north aspect, for the KNMI radar composite.

Same shape as ops/utm.py and for the same reason: one national grid needs one
projection, and pulling in a projection library to get it would be a large
dependency for two formulas. The formulas are the standard ellipsoidal polar
stereographic ones (EPSG 9810).

Every constant here comes from the proj4 string KNMI writes into each file:

    +proj=stere +lat_0=90 +lon_0=0 +lat_ts=60 +a=6378137 +b=6356752 +units=km

and `assert_proj4` refuses a file whose string is not that one, rather than
reading a moved grid with the old numbers. A projection that has silently
changed does not fail: it draws the same map somewhere else.

The control is not my arithmetic, it is KNMI's own four corner coordinates,
which every file states independently of the projection parameters. Measured
2026-08-13 on the 13:05 frame: all four agree to **16 m on a 1000 m cell**.
That check lives in tests/test_stereo.py and it is the whole reason to trust
this file.

Note the axis convention, which cost me a first version that put the
Netherlands in the Pacific: KNMI's `geo_row_offset` is the distance from the
pole of the TOP row, in km, and that distance GROWS by one cell per row
downward. A proj-style northing (negative going south from the pole) is the
same number with the other sign, and reading one as the other flips the grid
inside out while leaving the latitudes plausible.
"""
import math

A = 6378137.0
B = 6356752.0
LAT_TS = 60.0
LON_0 = 0.0

E = math.sqrt(1.0 - (B * B) / (A * A))


def _t(lat_rad):
    s = E * math.sin(lat_rad)
    return math.tan(math.pi / 4.0 - lat_rad / 2.0) / ((1.0 - s) / (1.0 + s)) ** (E / 2.0)


def _m(lat_rad):
    return math.cos(lat_rad) / math.sqrt(1.0 - E * E * math.sin(lat_rad) ** 2)


# Scale factor, in kilometres, so that rho = K * t(lat).
K = A * _m(math.radians(LAT_TS)) / _t(math.radians(LAT_TS)) / 1000.0


def forward(lat, lng):
    """-> (x, u) in km: x eastward, u the distance from the pole along lon_0.

    `u` is deliberately not called "y". It is the pole-relative coordinate KNMI
    uses (positive away from the pole), not a northing, and naming it y is what
    invites the sign error this module's docstring warns about.
    """
    r = K * _t(math.radians(lat))
    lo = math.radians(lng - LON_0)
    return r * math.sin(lo), r * math.cos(lo)


def inverse(x, u):
    """-> (lat, lng) for a point given in the same (x, u) km coordinates."""
    r = math.hypot(x, u)
    if r == 0.0:
        return 90.0, LON_0
    t = r / K
    lat = math.pi / 2.0 - 2.0 * math.atan(t)
    for _ in range(8):        # Snyder's iteration; converges in three or four
        s = E * math.sin(lat)
        lat = math.pi / 2.0 - 2.0 * math.atan(t * ((1.0 - s) / (1.0 + s)) ** (E / 2.0))
    return math.degrees(lat), math.degrees(math.atan2(x, u)) + LON_0


def assert_proj4(s):
    """Refuse a file whose projection is not the one these constants describe.

    Checked by value, not by string equality: KNMI could reorder or reformat
    the parameters without changing the grid, and a check that fails on
    whitespace would be deleted by the next person in a hurry.
    """
    if isinstance(s, bytes):
        s = s.decode()
    want = {"proj": "stere", "lat_0": "90", "lon_0": "0", "lat_ts": "60",
            "a": "6378137", "b": "6356752", "units": "km"}
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
            same = abs(float(have) - float(v)) < 1e-6
        except ValueError:
            same = have == v
        if not same:
            raise ValueError("projection %s is %r, these constants assume %r"
                             % (k, have, v))
    return True
