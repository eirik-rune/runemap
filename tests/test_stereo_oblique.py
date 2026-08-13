"""Oblique stereographic, checked against DMI's own numbers. Hermetic.

The fixtures are the `/where` attributes of a real frame
(`dk.com.202608131320.500_max.h5`, 2026-08-13 13:20 UTC), copied literally.
That matters here more than usual: the control on a projection cannot be more
arithmetic, because arithmetic is the thing being checked. It has to be
coordinates the source computed independently -- and those caught a real error,
in their file rather than in ours.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import stereo_oblique as S     # noqa: E402

# Straight out of /where.
CORNERS = {"LL_lat": 52.29427206432812, "LL_lon": 4.379082700525593,
           "LR_lat": 52.29427206432812, "LR_lon": 18.893280870398133,
           "UL_lat": 60.0, "UL_lon": 3.0,
           "UR_lat": 59.827708427801085, "UR_lon": 20.735140174892805}
COLS, ROWS, SCALE = 1984, 1728, 500.0
PROJ4 = "+proj=stere +ellps=WGS84 +lat_0=56 +lon_0=10.5666 +lat_ts=56"


class ItRoundTrips(unittest.TestCase):

    def test_every_stated_corner_survives_a_round_trip(self):
        for n in ("LL", "LR", "UL", "UR"):
            lat, lng = CORNERS[n + "_lat"], CORNERS[n + "_lon"]
            got = S.inverse(*S.forward(lat, lng))
            self.assertAlmostEqual(got[0], lat, places=7, msg=n)
            self.assertAlmostEqual(got[1], lng, places=7, msg=n)

    def test_the_origin_is_the_projection_centre(self):
        x, y = S.forward(S.LAT_0, S.LON_0)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_the_cos_chi1_term_in_the_inverse_is_not_optional(self):
        """Dropping it still returns a plausible latitude -- the first version
        put a Danish corner at 62.7N instead of 60.0N, which reads like a small
        error and is 300 km. So this pins the corner it got wrong."""
        got = S.inverse(*S.forward(60.0, 3.0))
        self.assertAlmostEqual(got[0], 60.0, places=7)
        # And explicitly NOT the bad value. The first version of this line read
        # `assertLess(abs(got[0] - 62.74), 2.0)`, which asserts the opposite of
        # what it says -- a test that could only pass by being wrong.
        self.assertGreater(abs(got[0] - 62.74), 1.0, "regression to the bad value")


class TheGridIsBuiltFromOneCornerAndCheckedAgainstTheRest(unittest.TestCase):
    """Fitting all four corners would have quietly tilted the grid to
    accommodate a typo in the source's metadata."""

    def test_three_corners_agree_within_a_cell(self):
        errs = dict(S.check_corners(CORNERS, COLS, ROWS, SCALE))
        for n in ("UL", "UR", "LL"):
            self.assertLess(errs[n], SCALE, (n, errs[n]))

    def test_the_fourth_corner_is_theirs_and_is_wrong(self):
        """LR_lat is byte-identical to LL_lat. On an oblique projection the
        bottom edge of a projected rectangle is not a line of constant
        latitude, so the two cannot share one -- and the point they state sits
        about 15 km north of where the grid's corner actually is."""
        self.assertEqual(CORNERS["LR_lat"], CORNERS["LL_lat"])
        errs = dict(S.check_corners(CORNERS, COLS, ROWS, SCALE))
        self.assertGreater(errs["LR"], 10000.0)
        self.assertLess(errs["LR"], 20000.0)

    def test_the_corners_are_cell_centres_not_cell_edges(self):
        """(n-1) * scale matches their span; n * scale would be one cell out,
        and that one cell is how you find out which convention a file uses."""
        ulx, uly = S.forward(CORNERS["UL_lat"], CORNERS["UL_lon"])
        urx, _ = S.forward(CORNERS["UR_lat"], CORNERS["UR_lon"])
        _, lly = S.forward(CORNERS["LL_lat"], CORNERS["LL_lon"])
        self.assertAlmostEqual((urx - ulx) / SCALE, COLS - 1, delta=1.0)
        self.assertAlmostEqual((uly - lly) / SCALE, ROWS - 1, delta=1.0)

    def test_a_wrong_anchor_is_detected_rather_than_absorbed(self):
        """Anchoring on the bad corner must make the other three fail, not
        redistribute the error quietly across all of them."""
        errs = dict(S.check_corners(CORNERS, COLS, ROWS, SCALE, anchor="LR"))
        self.assertGreater(max(errs[n] for n in ("UL", "UR", "LL")), 10000.0)


class ItRefusesAGridItDoesNotDescribe(unittest.TestCase):

    def test_the_danish_projection_passes(self):
        self.assertTrue(S.assert_proj4(PROJ4))

    def test_the_polar_aspect_is_refused(self):
        """ops/stereo.py is lat_0=90. The polar formulas do not degrade into
        the oblique ones -- they draw a plausible map of somewhere else."""
        with self.assertRaises(ValueError):
            S.assert_proj4("+proj=stere +lat_0=90 +lon_0=0 +lat_ts=60")

    def test_a_different_projection_family_is_refused(self):
        with self.assertRaises(ValueError):
            S.assert_proj4("+proj=merc +lat_ts=0 +lon_0=0")

    def test_reordering_the_same_projection_still_passes(self):
        self.assertTrue(S.assert_proj4(
            "+lat_ts=56.0 +lon_0=10.5666 +lat_0=56 +ellps=WGS84 +proj=stere"))


class TheTwoFamiliesAreNotInterchangeable(unittest.TestCase):

    def test_the_polar_module_puts_denmark_somewhere_else(self):
        """The reason this file exists rather than a parameter on the other
        one. Same latitude and longitude, two projections, and the answer
        differs by hundreds of kilometres -- with no error raised anywhere."""
        import stereo as polar
        # polar.forward answers in KILOMETRES (KNMI's grid is stated in km);
        # this module answers in metres. Comparing them without converting was
        # the first version of this test, and it made a 3647 km disagreement
        # look like 3647 of something.
        px, pu = [v * 1000.0 for v in polar.forward(56.0, 10.5666)]
        ox, oy = S.forward(56.0, 10.5666)
        self.assertGreater(math.hypot(px - ox, pu - oy), 1000000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
