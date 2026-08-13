"""Latitude/longitude to UTM, because the Swedish composite is a GeoTIFF.

Every WMS we ship asks the server for EPSG:4326 and never has to do this. SMHI's
radar composite is different: it arrives from their open-data file API as a
GeoTIFF whose GeoKeys say Projection 16033 -- UTM zone 33 North -- on the GRS80
ellipsoid, in metres. To find the pixel under a reader we have to do the
projection ourselves.

Hand-rolled geodesy is exactly the kind of code that returns a confident wrong
number, so the point of this module is the checks around it, not the series:

  * `forward` is the standard Kruger series to fourth order in n; over a single
    UTM zone its error is centimetres, and we are choosing 2 km pixels.
  * `inverse` is its counterpart, and `tests/test_utm.py` requires the two to
    round-trip across the whole Swedish extent.
  * The real control is external: the same composite is published as ODIM HDF5
    with FOUR CORNER LATITUDES AND LONGITUDES written by SMHI. Projecting the
    GeoTIFF's own corners and comparing against those corners is a check this
    code can fail, and did fail while it was being written.

Nothing here is specific to Sweden except the default zone.
"""
import math

A = 6378137.0                 # GRS80 semi-major, from the file's own GeoKeys
F = 1.0 / 298.257222101       # GRS80 inverse flattening, likewise
K0 = 0.9996                   # UTM scale factor at the central meridian
FALSE_EASTING = 500000.0
FALSE_NORTHING = 10000000.0   # southern hemisphere only

_N = F / (2.0 - F)
_A_RECT = A / (1.0 + _N) * (1.0 + _N ** 2 / 4.0 + _N ** 4 / 64.0)
_ALPHA = (_N / 2.0 - 2.0 / 3.0 * _N ** 2 + 5.0 / 16.0 * _N ** 3 + 41.0 / 180.0 * _N ** 4,
          13.0 / 48.0 * _N ** 2 - 3.0 / 5.0 * _N ** 3 + 557.0 / 1440.0 * _N ** 4,
          61.0 / 240.0 * _N ** 3 - 103.0 / 140.0 * _N ** 4,
          49561.0 / 161280.0 * _N ** 4)
_BETA = (_N / 2.0 - 2.0 / 3.0 * _N ** 2 + 37.0 / 96.0 * _N ** 3 - 1.0 / 360.0 * _N ** 4,
         1.0 / 48.0 * _N ** 2 + 1.0 / 15.0 * _N ** 3 - 437.0 / 1440.0 * _N ** 4,
         17.0 / 480.0 * _N ** 3 - 37.0 / 840.0 * _N ** 4,
         4397.0 / 161280.0 * _N ** 4)
_DELTA = (2.0 * _N - 2.0 / 3.0 * _N ** 2 - 2.0 * _N ** 3 + 116.0 / 45.0 * _N ** 4,
          7.0 / 3.0 * _N ** 2 - 8.0 / 5.0 * _N ** 3 - 227.0 / 45.0 * _N ** 4,
          56.0 / 15.0 * _N ** 3 - 136.0 / 35.0 * _N ** 4,
          4279.0 / 630.0 * _N ** 4)


def central_meridian(zone):
    if not 1 <= int(zone) <= 60:
        raise ValueError("UTM zone %r does not exist" % (zone,))
    return (int(zone) - 1) * 6.0 - 180.0 + 3.0


def forward(lat, lng, zone=33):
    """(lat, lng) degrees -> (easting, northing) metres in that UTM zone.

    The zone is an argument and never inferred from the longitude: this is used
    to read a raster whose zone is fixed by its own GeoKeys, and a point west of
    the zone simply lands at a small easting rather than silently jumping into
    a different grid.
    """
    lat_r = math.radians(lat)
    dl = math.radians(lng - central_meridian(zone))
    t = math.sinh(math.atanh(math.sin(lat_r))
                  - (2.0 * math.sqrt(_N) / (1.0 + _N))
                  * math.atanh((2.0 * math.sqrt(_N) / (1.0 + _N)) * math.sin(lat_r)))
    xi = math.atan(t / math.cos(dl))
    eta = math.atanh(math.sin(dl) / math.sqrt(1.0 + t * t))
    e = eta
    n = xi
    for j, a in enumerate(_ALPHA, start=1):
        e += a * math.cos(2.0 * j * xi) * math.sinh(2.0 * j * eta)
        n += a * math.sin(2.0 * j * xi) * math.cosh(2.0 * j * eta)
    easting = FALSE_EASTING + K0 * _A_RECT * e
    northing = K0 * _A_RECT * n
    if lat < 0:
        northing += FALSE_NORTHING
    return easting, northing


def inverse(easting, northing, zone=33, southern=False):
    """(easting, northing) metres -> (lat, lng) degrees. The counterpart."""
    n = (northing - (FALSE_NORTHING if southern else 0.0)) / (K0 * _A_RECT)
    e = (easting - FALSE_EASTING) / (K0 * _A_RECT)
    xi, eta = n, e
    for j, b in enumerate(_BETA, start=1):
        xi -= b * math.sin(2.0 * j * n) * math.cosh(2.0 * j * e)
        eta -= b * math.cos(2.0 * j * n) * math.sinh(2.0 * j * e)
    chi = math.asin(math.sin(xi) / math.cosh(eta))
    lat = chi
    for j, d in enumerate(_DELTA, start=1):
        lat += d * math.sin(2.0 * j * chi)
    lng = math.radians(central_meridian(zone)) + math.atan2(math.sinh(eta), math.cos(xi))
    return math.degrees(lat), math.degrees(lng)
