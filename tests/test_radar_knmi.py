"""The Netherlands. Hermetic -- no network, no HDF5 reader, no API key.

Same arrangement as Czechia: h5py appears in one function, so everything a
reader's map depends on can be tested on a machine that cannot open an HDF5
file. The projection is checked against KNMI's own four corner coordinates,
which they publish in every file independently of the projection parameters --
that is the control, not my arithmetic.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import radar_knmi as K         # noqa: E402
import stereo                  # noqa: E402

SCALE = {"gain": 0.5, "offset": -32.0, "missing": 0.0, "outside": 255.0}
# Straight out of the 2026-08-13 13:05 frame.
GEO = {"cols": 700, "rows": 765, "px": 1.0000026226043701,
       "py": 1.0000044107437134, "col0": 0.0, "row0": 3649.9794921875,
       "corners": [0.0, 49.362064361572266, 0.0, 55.973602294921875,
                   10.856453895568848, 55.388973236083984,
                   9.009300231933594, 48.895301818847656]}
PROJ4 = ("+proj=stere +lat_0=90 +lon_0=0 +lat_ts=60 +a=6378137 +b=6356752"
         " +x_0=0 +y_0=0 +units=km")


class TheProjectionIsCheckedAgainstTheirCorners(unittest.TestCase):
    """A projection that has silently changed does not fail -- it draws the
    same map somewhere else. KNMI states four corner lat/lons in every file,
    derived independently of the projection parameters, so they are a real
    control rather than a restatement."""

    def _cell(self, col, row):
        return (GEO["col0"] + col) * GEO["px"], GEO["row0"] + row * GEO["py"]

    def test_all_four_corners_land_within_a_fifth_of_a_cell(self):
        import math
        c = GEO["corners"]
        cases = [((0, GEO["rows"]), (c[0], c[1])),
                 ((0, 0), (c[2], c[3])),
                 ((GEO["cols"], 0), (c[4], c[5])),
                 ((GEO["cols"], GEO["rows"]), (c[6], c[7]))]
        for (col, row), (wlon, wlat) in cases:
            x, u = self._cell(col, row)
            lat, lng = stereo.inverse(x, u)
            off = math.hypot((lat - wlat) * 111320,
                            (lng - wlon) * 111320 * math.cos(math.radians(lat)))
            self.assertLess(off, 200.0, (col, row, off))     # measured: 16 m

    def test_forward_and_inverse_round_trip(self):
        for lat, lng in [(52.37, 4.90), (51.92, 4.48), (53.22, 6.57)]:
            got = stereo.inverse(*stereo.forward(lat, lng))
            self.assertAlmostEqual(got[0], lat, places=6)
            self.assertAlmostEqual(got[1], lng, places=6)

    def test_the_axis_is_pole_relative_not_a_northing(self):
        """The sign error that put the Netherlands in the Pacific: u grows
        away from the pole, so a southern point has the LARGER u."""
        self.assertGreater(stereo.forward(49.0, 0.0)[1],
                           stereo.forward(56.0, 0.0)[1])

    def test_a_moved_projection_is_refused_not_reinterpreted(self):
        self.assertTrue(stereo.assert_proj4(PROJ4))
        with self.assertRaises(ValueError):
            stereo.assert_proj4(PROJ4.replace("lat_ts=60", "lat_ts=90"))
        with self.assertRaises(ValueError):
            stereo.assert_proj4("+proj=merc +lat_ts=0 +lon_0=0")

    def test_reformatting_the_same_projection_still_passes(self):
        """A check that fails on whitespace gets deleted by the next person in
        a hurry, and a real check dies with it."""
        self.assertTrue(stereo.assert_proj4(
            "+units=km +b=6356752 +a=6378137.0 +lat_ts=60.0 +lon_0=0"
            " +lat_0=90 +proj=stere"))


class TheCalibrationIsParsedNotRestated(unittest.TestCase):

    def test_their_formula_is_read(self):
        self.assertEqual(K.parse_calibration("GEO = 0.500000 * PV + -32.000000"),
                         (0.5, -32.0))

    def test_a_moved_scale_is_followed(self):
        self.assertEqual(K.parse_calibration("GEO = 0.400000 * PV + -30.000000"),
                         (0.4, -30.0))

    def test_an_unreadable_formula_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            K.parse_calibration("GEO = something else entirely")


class MissingAndOutsideAreDifferentFacts(unittest.TestCase):

    def test_out_of_image_is_negative(self):
        self.assertEqual(K.level_of(255, SCALE), -1)

    def test_missing_is_zero(self):
        self.assertEqual(K.level_of(0, SCALE), 0)

    def test_clear_air_clutter_is_below_the_floor(self):
        """Measured against reality on 2026-08-13: Amsterdam was 31C, 17%
        humidity and 0.00 mm/h, while 82% of the frame's echo pixels sat below
        7 dBZ and drew as light rain across the whole window."""
        self.assertEqual(K.level_of(60, SCALE), 0)          # -2 dBZ
        self.assertEqual(K.level_of(77, SCALE), 0)          # 6.5 dBZ
        self.assertEqual(K.level_of(78, SCALE), 1)          # 7.0 dBZ

    def test_real_rain_still_draws(self):
        self.assertEqual(K.level_of(128, SCALE), 3)         # 32 dBZ
        self.assertEqual(K.level_of(160, SCALE), 5)         # 48 dBZ


class TheFilenameIsTheContract(unittest.TestCase):

    def test_a_published_name_yields_its_stamp(self):
        self.assertEqual(K.stamp_of("RAD_NL25_PCP_NA_202608131305.h5"),
                         "202608131305")

    def test_another_products_name_is_not_accepted(self):
        self.assertIsNone(K.stamp_of("RAD_NL25_ETH_NA_202608131305.h5"))
        self.assertIsNone(K.stamp_of(""))
        self.assertIsNone(K.stamp_of(None))

    def test_a_stamp_round_trips_to_its_own_time(self):
        s = "202608131305"
        self.assertEqual(time.strftime("%Y%m%d%H%M",
                                       time.gmtime(K.frame_ts(s))), s)


class ItAsksOnceAndBacksOffOnTheirLimit(unittest.TestCase):
    """The anonymous key's quota is SHARED with every other unregistered user
    of the platform, so a burst here is not our own budget being spent. The
    first version walked six candidate timestamps asking for each in turn and
    ran the shared quota into a 429 -- which I caused, for everyone."""

    def test_the_listing_is_one_request(self):
        calls = []

        def get(u, k=None):
            calls.append(u)
            return b'{"files": [{"filename": "RAD_NL25_PCP_NA_202608131305.h5"}]}'
        self.assertEqual(K.newest_frame("key", get),
                         "RAD_NL25_PCP_NA_202608131305.h5")
        self.assertEqual(len(calls), 1)
        self.assertIn("maxKeys=1", calls[0])

    def test_a_429_stops_rather_than_walking_the_list(self):
        import urllib.error
        calls = []

        def get(u, k=None):
            calls.append(u)
            raise urllib.error.HTTPError(u, 429, "Too Many Requests", {}, None)
        with self.assertRaises(K.RateLimited):
            K.newest_frame("key", get)
        self.assertEqual(len(calls), 1)

    def test_the_signed_url_is_fetched_without_the_key(self):
        """Sending credentials to a pre-signed URL is unnecessary and a way to
        leave them in somebody else's logs."""
        seen = []

        def get(u, k=None):
            seen.append((u, k))
            if u.endswith("/url"):
                return b'{"temporaryDownloadUrl": "https://example.invalid/x"}'
            return b"\\x89HDF\\r\\n\\x1a\\n" + b"0" * 40
        K.download("202608131305", "SECRET", get)
        self.assertEqual(seen[0][1], "SECRET")
        self.assertIsNone(seen[1][1])

    def test_an_empty_listing_is_not_a_frame(self):
        self.assertIsNone(K.newest_frame("key", lambda u, k=None: b'{"files": []}'))


class ItSaysWhyItCannotWork(unittest.TestCase):

    def test_a_missing_key_is_named_not_silently_declined(self):
        """Both absences are pinned, and both are forced.

        The first version only forced the key away and asserted on the
        sentence -- which passed here, where h5py is installed, and failed in
        CI, where it is not and the other reason answers first. A test that
        reads whatever the machine happens to have is not testing the code."""
        oldk, oldh = K.api_key, K.have_h5py
        K.api_key, K.have_h5py = (lambda: None), (lambda: True)
        try:
            self.assertIn("no KNMI key", K.unavailable() or "")
        finally:
            K.api_key, K.have_h5py = oldk, oldh

    def test_a_missing_reader_is_named_too(self):
        oldk, oldh = K.api_key, K.have_h5py
        K.api_key, K.have_h5py = (lambda: "k"), (lambda: False)
        try:
            self.assertIn("h5py", K.unavailable() or "")
        finally:
            K.api_key, K.have_h5py = oldk, oldh

    def test_with_both_present_it_is_available(self):
        oldk, oldh = K.api_key, K.have_h5py
        K.api_key, K.have_h5py = (lambda: "k"), (lambda: True)
        try:
            self.assertIsNone(K.unavailable())
        finally:
            K.api_key, K.have_h5py = oldk, oldh

    def test_outside_coverage_is_declined_before_anything_else(self):
        old = K.unavailable
        K.unavailable = lambda: self.fail("asked too early")
        try:
            self.assertIsNone(K.draw("><", -3.70, 40.42))     # Madrid
        finally:
            K.unavailable = old

    def test_the_dutch_cities_are_covered(self):
        for lng, lat in [(4.90, 52.37), (4.48, 51.92), (6.57, 53.22)]:
            self.assertTrue(K.covers(lng, lat), (lng, lat))


class TheWindowLandsWhereItShould(unittest.TestCase):

    def setUp(self):
        import numpy as np
        self.arr = np.zeros((GEO["rows"], GEO["cols"]), dtype=np.uint8)

    def test_a_sky_inside_the_grid_finds_a_cell(self):
        self.assertIsNotNone(K.cell_of(GEO, 52.37, 4.90))

    def test_a_sky_outside_the_grid_finds_none(self):
        self.assertIsNone(K.cell_of(GEO, 40.42, -3.70))

    def test_an_echo_north_of_the_reader_draws_in_the_upper_half(self):
        col, row = K.cell_of(GEO, 53.3, 4.90)
        self.arr[row - 15:row + 16, col - 15:col + 16] = 160
        lv, _ = K.window(self.arr, SCALE, GEO, 4.90, 52.37, 280, 24, 12)
        rows = lv.tolist()
        self.assertGreater(sum(sum(1 for v in r if v) for r in rows[:6]), 0)
        self.assertEqual(sum(sum(1 for v in r if v) for r in rows[6:]), 0)

    def test_out_of_image_counts_as_missing(self):
        self.arr[:, :] = 255
        _lv, share = K.window(self.arr, SCALE, GEO, 4.90, 52.37, 280, 24, 12)
        self.assertEqual(share, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
