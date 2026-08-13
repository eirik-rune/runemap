"""Swiss oblique Mercator (somerc) on the Bessel ellipsoid, plus the datum shift.

MeteoSwiss's radar composite states its own projection:

    +proj=somerc +lat_0=46.95240555555556 +lon_0=7.439583333333333 +k_0=1
    +x_0=2600000 +y_0=1200000 +ellps=bessel
    +towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs

pyproj is not installed in production, so this is hand-rolled the way
`stereo_oblique.py` (Denmark) and `scripts/lcc.py` (Norway) are. Two parts,
and the second one is the part that is easy to skip:

1. **The datum shift.** The grid is on CH1903 (Bessel), readers arrive in
   WGS84. `towgs84` is a three-parameter translation, and ignoring it moves a
   point by a couple of hundred metres. That is a fifth of a cell here -- not
   enough to look broken, which is exactly what makes it dangerous: a
   scale-correct, fresh-stamped map with the weather slightly displaced. So it
   is applied, and `forward()` refuses to pretend otherwise.

2. **The projection.** swisstopo's rigorous formulation: the ellipsoid is
   mapped conformally to a sphere (Gauss), the sphere is rotated so Bern lies
   on its equator, and the result is a Mercator projection of that rotated
   sphere.

Sign convention: swisstopo call easting `y` and northing `x`. This module
returns `(easting, northing)` in that order and does not use their names, since
mixing the two conventions is how an axis gets flipped in silence.
"""
import math

# Bessel 1841, as the projdef names it.
A_BESSEL = 6377397.155
F_BESSEL = 1.0 / 299.1528128
E2_BESSEL = 2 * F_BESSEL - F_BESSEL * F_BESSEL
E_BESSEL = math.sqrt(E2_BESSEL)

# WGS84, where readers' coordinates come from.
A_WGS84 = 6378137.0
F_WGS84 = 1.0 / 298.257223563
E2_WGS84 = 2 * F_WGS84 - F_WGS84 * F_WGS84

# towgs84: CH1903 geocentric + these = WGS84 geocentric. Going the other way
# therefore subtracts them.
DX, DY, DZ = 674.374, 15.056, 405.346

LAT_0 = 46.95240555555556      # Bern, old observatory
LON_0 = 7.439583333333333
X_0 = 2600000.0                # LV95 false easting
Y_0 = 1200000.0                # LV95 false northing

_lat0 = math.radians(LAT_0)
_lon0 = math.radians(LON_0)

# Gauss sphere: radius, and the constant that stretches longitude on it.
R_SPHERE = (A_BESSEL * math.sqrt(1 - E2_BESSEL)
            / (1 - E2_BESSEL * math.sin(_lat0) ** 2))
ALPHA = math.sqrt(1 + (E2_BESSEL / (1 - E2_BESSEL)) * math.cos(_lat0) ** 4)
B_0 = math.asin(math.sin(_lat0) / ALPHA)


def _k_const():
    return (math.log(math.tan(math.pi / 4 + B_0 / 2))
            - ALPHA * math.log(math.tan(math.pi / 4 + _lat0 / 2))
            + ALPHA * E_BESSEL / 2
            * math.log((1 + E_BESSEL * math.sin(_lat0))
                       / (1 - E_BESSEL * math.sin(_lat0))))


K_CONST = _k_const()


def wgs84_to_ch1903(lat, lon, h=0.0):
    """WGS84 geodetic -> CH1903 (Bessel) geodetic, via geocentric coordinates.

    Height is taken as 0 unless given. The horizontal error that assumption
    introduces is metres, against a 1000 m cell; the error from skipping this
    function entirely is hundreds of metres, which is why it exists.
    """
    la, lo = math.radians(lat), math.radians(lon)
    n = A_WGS84 / math.sqrt(1 - E2_WGS84 * math.sin(la) ** 2)
    x = (n + h) * math.cos(la) * math.cos(lo)
    y = (n + h) * math.cos(la) * math.sin(lo)
    z = (n * (1 - E2_WGS84) + h) * math.sin(la)
    x, y, z = x - DX, y - DY, z - DZ
    # Geocentric -> geodetic on Bessel, iterated. Converges in a few rounds at
    # these latitudes; the loop is bounded so a bad input cannot hang a reader.
    p = math.hypot(x, y)
    lat_b = math.atan2(z, p * (1 - E2_BESSEL))
    for _ in range(8):
        n_b = A_BESSEL / math.sqrt(1 - E2_BESSEL * math.sin(lat_b) ** 2)
        prev = lat_b
        lat_b = math.atan2(z + E2_BESSEL * n_b * math.sin(lat_b), p)
        if abs(lat_b - prev) < 1e-12:
            break
    return math.degrees(lat_b), math.degrees(math.atan2(y, x))


def forward(lat, lon, wgs84=True):
    """(lat, lon) -> (easting, northing) in LV95 metres.

    `wgs84=False` says the caller already holds CH1903 coordinates. It is an
    explicit argument rather than a guess, because the two datums differ by
    only a couple of hundred metres and a wrong assumption produces a plausible
    answer instead of an error.
    """
    if wgs84:
        lat, lon = wgs84_to_ch1903(lat, lon)
    la, lo = math.radians(lat), math.radians(lon)
    s = (ALPHA * math.log(math.tan(math.pi / 4 + la / 2))
         - ALPHA * E_BESSEL / 2
         * math.log((1 + E_BESSEL * math.sin(la))
                    / (1 - E_BESSEL * math.sin(la)))
         + K_CONST)
    b = 2 * (math.atan(math.exp(s)) - math.pi / 4)
    l = ALPHA * (lo - _lon0)
    # Rotate the sphere so that Bern sits on its equator.
    l_bar = math.atan2(math.sin(l),
                       math.sin(B_0) * math.tan(b) + math.cos(B_0) * math.cos(l))
    b_bar = math.asin(math.cos(B_0) * math.sin(b)
                      - math.sin(B_0) * math.cos(b) * math.cos(l))
    easting = R_SPHERE * l_bar + X_0
    northing = (R_SPHERE / 2
                * math.log((1 + math.sin(b_bar)) / (1 - math.sin(b_bar))) + Y_0)
    return easting, northing


def assert_proj4(projdef):
    """Refuse a frame whose projection is not the one implemented here.

    The failure this guards against is a silent upstream change of grid: the
    numbers would still arrive, still be scaled correctly, and be in the wrong
    place. Values are compared, not the string, because parameter order and
    formatting are not promises.
    """
    want = {"proj": "somerc", "lat_0": LAT_0, "lon_0": LON_0,
            "x_0": X_0, "y_0": Y_0, "k_0": 1.0}
    got = {}
    for tok in projdef.split():
        tok = tok.lstrip("+")
        if "=" in tok:
            k, v = tok.split("=", 1)
            got[k] = v
    if got.get("proj") != "somerc":
        raise ValueError("not somerc: %r" % (got.get("proj"),))
    if got.get("ellps") != "bessel":
        raise ValueError("not the Bessel ellipsoid: %r" % (got.get("ellps"),))
    for key, expect in want.items():
        if key == "proj":
            continue
        if key not in got:
            raise ValueError("projdef does not state %s" % key)
        if abs(float(got[key]) - expect) > 1e-6:
            raise ValueError("%s is %s, expected %s" % (key, got[key], expect))
    return True
