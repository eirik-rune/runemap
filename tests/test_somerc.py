"""Swiss oblique Mercator, checked against numbers this repo did not produce.

Hermetic. The reference point is swisstopo's own worked example and the corner
coordinates are copied verbatim from a live MeteoSwiss radar frame
(`rzc262252120vl.001.h5`), so both sides of every comparison come from outside
this codebase. Expected values are never derived from what the code printed --
that is how a bug gets filed as the correct answer.
"""
import math
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "ops"), os.path.join(_ROOT, "scripts"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import somerc as S          # noqa: E402

# MeteoSwiss's radar grid, as the file's `where` group states it.
PROJDEF = ("+proj=somerc +lat_0=46.95240555555556 +lon_0=7.439583333333333 "
           "+k_0=1 +x_0=2600000 +y_0=1200000 +ellps=bessel "
           "+towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs")
CORNERS = {"LL": (43.62900161743164, 3.1687800884246826),
           "LR": (43.61899948120117, 11.955599784851074),
           "UL": (49.3744010925293, 2.689419984817505),
           "UR": (49.36330032418, 12.462300300598145)}


class AgainstSwisstopoOwnNumbers(unittest.TestCase):

    def test_the_published_worked_example(self):
        """swisstopo publish Zimmerwald as WGS84 -> LV95. Their answer, not
        mine: 2602030.680 / 1191775.030."""
        lat = 46 + 52 / 60 + 37.540562 / 3600
        lon = 7 + 27 / 60 + 54.983301 / 3600
        e, n = S.forward(lat, lon)
        self.assertLess(abs(e - 2602030.680), 1.0, e)
        self.assertLess(abs(n - 1191775.030), 1.0, n)

    def test_the_origin_lands_on_the_false_easting_and_northing(self):
        """lat_0/lon_0 are CH1903 values, so the datum shift must be skipped
        here -- passing them as WGS84 would be a plausible wrong answer."""
        e, n = S.forward(S.LAT_0, S.LON_0, wgs84=False)
        self.assertAlmostEqual(e, 2600000.0, places=3)
        self.assertAlmostEqual(n, 1200000.0, places=3)


class TheDatumShiftIsNotDecoration(unittest.TestCase):

    def test_skipping_it_moves_a_point_by_a_visible_distance(self):
        """If wgs84=True and wgs84=False agreed, the shift would be a no-op
        wearing the name of a correction. It is worth ~200 m -- a fifth of a
        cell, which is small enough to look right and wrong enough to matter."""
        a = S.forward(46.95, 7.44, wgs84=True)
        b = S.forward(46.95, 7.44, wgs84=False)
        d = math.hypot(a[0] - b[0], a[1] - b[1])
        self.assertGreater(d, 100.0, d)
        self.assertLess(d, 500.0, d)

    def test_the_shift_returns_something_close_but_not_equal(self):
        lat, lon = S.wgs84_to_ch1903(46.95, 7.44)
        self.assertNotEqual((lat, lon), (46.95, 7.44))
        self.assertLess(abs(lat - 46.95), 0.01)
        self.assertLess(abs(lon - 7.44), 0.01)


class TheGridImpliedByTheFilesCorners(unittest.TestCase):
    """The file states four corners. Projecting them must reproduce the grid
    the same file declares: 710 x 640 cells of 1000 m. Both sides come from
    MeteoSwiss; only the arithmetic between them is mine."""

    def corners(self):
        return {k: S.forward(la, lo) for k, (la, lo) in CORNERS.items()}

    def test_the_width_is_710_km(self):
        p = self.corners()
        self.assertLess(abs((p["UR"][0] - p["UL"][0]) - 710000.0), 50.0)
        self.assertLess(abs((p["LR"][0] - p["LL"][0]) - 710000.0), 50.0)

    def test_the_height_is_640_km(self):
        p = self.corners()
        self.assertLess(abs((p["UL"][1] - p["LL"][1]) - 640000.0), 50.0)
        self.assertLess(abs((p["UR"][1] - p["LR"][1]) - 640000.0), 50.0)

    def test_the_upper_left_corner_is_the_expected_lv95_origin(self):
        p = self.corners()
        self.assertLess(abs(p["UL"][0] - 2255000.0), 50.0, p["UL"])
        self.assertLess(abs(p["UL"][1] - 1480000.0), 50.0, p["UL"])

    def test_north_is_up_and_east_is_right(self):
        """Which way the axes run, stated as a test rather than a comment: an
        adapter that gets this backwards still draws a scale-correct map."""
        p = self.corners()
        self.assertGreater(p["UL"][1], p["LL"][1])
        self.assertGreater(p["UR"][0], p["UL"][0])

    def test_moving_north_raises_northing_and_moving_east_raises_easting(self):
        base = S.forward(46.8, 8.2)
        self.assertGreater(S.forward(46.9, 8.2)[1], base[1])
        self.assertGreater(S.forward(46.8, 8.3)[0], base[0])


class ItRefusesAGridItDoesNotImplement(unittest.TestCase):
    """A silent upstream change of projection would still deliver numbers, and
    they would still be scaled correctly, and they would be in the wrong place.
    Each rejection below is fired on a projdef built to earn it."""

    def test_the_real_projdef_is_accepted(self):
        self.assertTrue(S.assert_proj4(PROJDEF))

    def test_a_different_projection_family_is_refused(self):
        with self.assertRaises(ValueError):
            S.assert_proj4("+proj=stere +ellps=bessel +lat_0=46.95 "
                           "+lon_0=7.44 +x_0=2600000 +y_0=1200000 +k_0=1")

    def test_a_different_ellipsoid_is_refused(self):
        with self.assertRaises(ValueError):
            S.assert_proj4(PROJDEF.replace("+ellps=bessel", "+ellps=WGS84"))

    def test_a_shifted_origin_is_refused(self):
        with self.assertRaises(ValueError):
            S.assert_proj4(PROJDEF.replace("+x_0=2600000", "+x_0=600000"))

    def test_a_moved_centre_is_refused(self):
        with self.assertRaises(ValueError):
            S.assert_proj4(PROJDEF.replace("+lat_0=46.95240555555556",
                                           "+lat_0=47.0"))

    def test_a_projdef_that_omits_a_parameter_is_refused_not_defaulted(self):
        """Absent must not be treated as agreeing. A missing x_0 defaulted to
        the expected one would accept the very frame this guards against."""
        with self.assertRaises(ValueError):
            S.assert_proj4("+proj=somerc +ellps=bessel "
                           "+lat_0=46.95240555555556 +lon_0=7.439583333333333 "
                           "+y_0=1200000 +k_0=1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
