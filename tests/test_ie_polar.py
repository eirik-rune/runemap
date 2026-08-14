"""The Irish compositor's geometry, which is the half we author ourselves.

No h5py: CI deliberately lacks it, and the geometry is exactly the part that can
be wrong without anyone seeing. Reading the files is the adapter's problem.

Every test here was written to be able to fail, and each was fired against the
unfixed code before being trusted.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import numpy as np           # noqa: E402

import ie_polar as P         # noqa: E402

SHANNON = (52.6928, -8.9200)
DUBLIN = (53.4299, -6.2443)

# Ray i starts at azimuth i, as Met Eireann's files do to within 0.03 degrees.
STARTAZ = np.arange(360, dtype=float)


def sweep(nbins, rscale, fill):
    """A sweep where every gate holds `fill`."""
    return np.full((360, nbins), fill, dtype=float)


class RangeAndAzimuth(unittest.TestCase):

    def test_north_of_the_site_is_azimuth_zero(self):
        rng, az = P.ground_range_and_azimuth(
            SHANNON[0], SHANNON[1], [SHANNON[0] + 0.5], [SHANNON[1]])
        self.assertAlmostEqual(az[0], 0.0, places=3)
        self.assertAlmostEqual(rng[0] / 1000.0, 55.6, delta=0.5)

    def test_east_of_the_site_is_azimuth_ninety(self):
        _rng, az = P.ground_range_and_azimuth(
            SHANNON[0], SHANNON[1], [SHANNON[0]], [SHANNON[1] + 0.5])
        self.assertAlmostEqual(az[0], 90.0, delta=0.3)

    def test_azimuth_is_clockwise_from_north_not_anticlockwise(self):
        """The one that catches a mirrored map. A cell to the north-east must
        be 45, not 315 -- and a flipped composite is still a picture of
        Ireland, so nothing downstream would object."""
        _r, az = P.ground_range_and_azimuth(
            DUBLIN[0], DUBLIN[1], [DUBLIN[0] + 0.3], [DUBLIN[1] + 0.5])
        self.assertLess(az[0], 90.0)
        self.assertGreater(az[0], 0.0)


class TheBlindMaskIsAuthoredSoItIsTested(unittest.TestCase):
    """`nodata` is 0.0% in the real files: nothing states "not seen". If this
    module gets the range mask wrong, unseen cells become dry ones and we paint
    fair weather where no beam reached."""

    def test_beyond_the_last_bin_is_unseen_not_dry(self):
        data = sweep(250, 1000.0, 0.0)          # all undetect
        far_lat = DUBLIN[0] + 4.0               # ~445 km north
        dbz, seen = P.sample_sweep(
            data, STARTAZ, 1000.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [far_lat], [DUBLIN[1]])
        self.assertFalse(bool(seen[0]))
        self.assertTrue(math.isnan(dbz[0]))

    def test_inside_range_with_undetect_is_seen_and_dry(self):
        data = sweep(250, 1000.0, 0.0)
        dbz, seen = P.sample_sweep(
            data, STARTAZ, 1000.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [DUBLIN[0] + 0.3], [DUBLIN[1]])
        self.assertTrue(bool(seen[0]), "a cell the radar looked at is seen")
        self.assertTrue(math.isnan(dbz[0]), "and it is dry, which is not unseen")

    def test_nodata_inside_range_is_unseen(self):
        data = sweep(250, 1000.0, 255.0)
        _dbz, seen = P.sample_sweep(
            data, STARTAZ, 1000.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [DUBLIN[0] + 0.3], [DUBLIN[1]])
        self.assertFalse(bool(seen[0]))

    def test_seen_is_not_recoverable_from_dbz(self):
        """The whole design in one assertion: dry and unseen have the same dbz,
        so any caller collapsing to a single array loses the distinction."""
        dry = sweep(250, 1000.0, 0.0)
        d1, s1 = P.sample_sweep(
            dry, STARTAZ, 1000.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [DUBLIN[0] + 0.3], [DUBLIN[1]])
        d2, s2 = P.sample_sweep(
            dry, STARTAZ, 1000.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [DUBLIN[0] + 4.0], [DUBLIN[1]])
        self.assertTrue(math.isnan(d1[0]) and math.isnan(d2[0]))
        self.assertNotEqual(bool(s1[0]), bool(s2[0]))


class TheTwoSitesDoNotShareAGeometry(unittest.TestCase):
    """Shannon is 497 bins at 500 m, Dublin 250 at 1000 m. Reusing one site's
    rscale for the other doubles or halves every range."""

    def test_rscale_places_the_echo_and_a_wrong_one_moves_it(self):
        # One ring of echo at bin 100. At 1000 m that is 100 km out; read with
        # 500 m it would be 50 km.
        data = sweep(250, 1000.0, 0.0)
        data[:, 100] = 80.0                     # 80*0.5-32 = 8 dBZ
        # Aim at the CENTRE of bin 100 (100.0-101.0 km), not its edge: at the
        # edge, floating point decides whether we land in bin 99 or 100 and the
        # test would be asserting on rounding rather than on geometry.
        lat = DUBLIN[0] + (100500.0 / P.EARTH_R_M) * 180.0 / math.pi
        dbz, seen = P.sample_sweep(
            data, STARTAZ, 1000.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [lat], [DUBLIN[1]])
        self.assertTrue(bool(seen[0]))
        self.assertAlmostEqual(dbz[0], 8.0, places=6)

        wrong, _ = P.sample_sweep(
            data, STARTAZ, 500.0, 250, 0.0, 0.5, -32.0, 255.0, 0.0,
            DUBLIN[0], DUBLIN[1], [lat], [DUBLIN[1]])
        self.assertTrue(math.isnan(wrong[0]),
                        "the wrong rscale must not find the ring here")


class A1gateIsNotARotation(unittest.TestCase):
    """a1gate is 95 at Shannon and 142 at Dublin. It is the first ray acquired
    in time, not a storage offset; startazA[0] ~ 0 in both files. Applying it
    would rotate the two sites by different amounts."""

    def test_ray_zero_serves_azimuth_zero(self):
        self.assertEqual(int(P.ray_of_azimuth(STARTAZ, [0.5])[0]), 0)

    def test_ray_index_follows_published_start_angles(self):
        self.assertEqual(int(P.ray_of_azimuth(STARTAZ, [95.5])[0]), 95)
        self.assertEqual(int(P.ray_of_azimuth(STARTAZ, [359.9])[0]), 359)

    def test_a_shifted_startaz_array_shifts_the_rays(self):
        """If Met Eireann ever do publish an offset sweep, we follow the file
        rather than the convention -- which is why this reads startazA at all."""
        # Ray 0 starts at 10 deg, ray 349 at 359, ray 350 at 0. This array
        # ascends and then wraps, so it is NOT sorted -- feeding it straight to
        # searchsorted returns wrong rays without complaining.
        shifted = np.mod(np.arange(360, dtype=float) + 10.0, 360.0)
        self.assertEqual(int(P.ray_of_azimuth(shifted, [10.5])[0]), 0)
        self.assertEqual(int(P.ray_of_azimuth(shifted, [0.5])[0]), 350)
        self.assertEqual(int(P.ray_of_azimuth(shifted, [359.5])[0]), 349)


class Compositing(unittest.TestCase):

    def test_one_radar_looking_is_enough_to_be_seen(self):
        a = (np.array([np.nan]), np.array([False]))
        b = (np.array([np.nan]), np.array([True]))
        _dbz, seen = P.composite([a, b])
        self.assertTrue(bool(seen[0]))

    def test_the_stronger_echo_wins_and_a_blind_site_does_not_dilute_it(self):
        a = (np.array([30.0]), np.array([True]))
        b = (np.array([np.nan]), np.array([False]))
        dbz, _seen = P.composite([a, b])
        self.assertAlmostEqual(dbz[0], 30.0)

    def test_below_the_floor_is_dropped_but_the_cell_stays_seen(self):
        """Shannon's echo median is -1.0 dBZ. Dropping it must not also drop
        the fact that we looked -- that would turn clutter into a blind spot."""
        a = (np.array([-1.0]), np.array([True]))
        dbz, seen = P.composite([a], floor_dbz=7.0)
        self.assertTrue(math.isnan(dbz[0]))
        self.assertTrue(bool(seen[0]))

    def test_at_the_floor_exactly_is_kept(self):
        dbz, _ = P.composite([(np.array([7.0]), np.array([True]))], floor_dbz=7.0)
        self.assertAlmostEqual(dbz[0], 7.0)

    def test_no_sweeps_raises_rather_than_returning_an_empty_grid(self):
        with self.assertRaises(ValueError):
            P.composite([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
