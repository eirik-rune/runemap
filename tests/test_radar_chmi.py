"""Czechia. Hermetic -- no network, no HDF5 reader, every fixture a literal.

The adapter is arranged so that h5py appears in exactly one function, `read`.
Everything a reader's map depends on -- the coverage rectangle, the frame
naming, the scale arithmetic, the projection, the nodata handling -- is
ordinary numbers, so it can all be tested on a machine that cannot open an
HDF5 file at all. That is not a convenience: it is the difference between a
suite that runs everywhere and an optional dependency that quietly excuses the
interesting half from being checked.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import radar_chmi as C          # noqa: E402
import chmi_orient as O         # noqa: E402
import chmi_terms as T          # noqa: E402

SCALE = {"gain": 0.5, "offset": -32.0, "undetect": 0.0, "nodata": 255.0}
CORNERS = {"LL_lat": 48.047275, "LL_lon": 11.266869,
           "UR_lat": 51.458369, "UR_lon": 19.623974}


class CoverageIsTheCompositeNotTheCountry(unittest.TestCase):
    """The rectangle reaches into four neighbours, and it should: the composite
    merges foreign radars and really does see them. What it must not do is
    answer for a sky it cannot see at all."""

    def test_the_czech_cities_are_covered(self):
        for lng, lat in [(14.42, 50.09), (16.61, 49.20), (18.29, 49.84),
                         (13.38, 49.75)]:
            self.assertTrue(C.covers(lng, lat), (lng, lat))

    def test_paris_and_kyiv_are_not(self):
        for lng, lat in [(2.35, 48.86), (30.52, 50.45), (23.73, 37.98)]:
            self.assertFalse(C.covers(lng, lat), (lng, lat))

    def test_berlin_is_inside_the_rectangle_and_dwd_answers_first(self):
        """Berlin at 52.52N is north of the composite, so this is not even a
        contest -- but Dresden at 51.05N is inside both. The chain order is
        what keeps Germany on DWD, and it is asserted where the chain lives,
        not here; this only pins that the rectangle is honest about reaching."""
        self.assertFalse(C.covers(13.40, 52.52))
        self.assertTrue(C.covers(13.74, 51.05))


class FramesAreDerivedFromTheClockNotFromTheListing(unittest.TestCase):
    """The directory listing is 301 KB of HTML. Reading the first 200 KB of it
    returns a newest frame three days old, with nothing marking the cut -- a
    silently truncated answer that looks like a stale service. So the names come
    from the documented pattern and the clock."""

    def test_stamps_are_five_minute_marks_newest_first(self):
        got = C.stamps(now=time.mktime((2026, 8, 13, 12, 42, 17, 0, 0, 0))
                       - time.timezone)
        self.assertEqual(got[0], "20260813124000")
        self.assertEqual(got[1], "20260813123500")
        self.assertEqual(len(got), C.LOOKBACK)

    def test_a_stamp_round_trips_to_its_own_time(self):
        s = "20260813124000"
        self.assertEqual(time.strftime("%Y%m%d%H%M%S",
                                       time.gmtime(C.frame_ts(s))), s)

    def test_the_url_is_the_documented_shape(self):
        self.assertTrue((C.BASE % "20260813124000").endswith(
            "/T_PABV23_C_OKPR_20260813124000.hdf"))

    def test_two_frames_are_two_cache_files(self):
        self.assertNotEqual(C._cache_path("20260813124000"),
                            C._cache_path("20260813123500"))


class UndetectAndNodataAreDifferentFacts(unittest.TestCase):
    """"Looked, saw nothing" and "did not look here" must not share a return
    value. Every failure in this fleet reaches the reader as an empty grid,
    which is what a clear sky looks like."""

    def test_nodata_is_negative_not_zero(self):
        self.assertEqual(C.level_of(255, SCALE), -1)

    def test_undetect_is_zero(self):
        self.assertEqual(C.level_of(0, SCALE), 0)

    def test_the_bands_are_the_fleets_bands(self):
        # dBZ = 0.5*dn - 32
        self.assertEqual(C.level_of(100, SCALE), 1)     # 18.0
        self.assertEqual(C.level_of(110, SCALE), 2)     # 23.0
        self.assertEqual(C.level_of(128, SCALE), 3)     # 32.0
        self.assertEqual(C.level_of(150, SCALE), 4)     # 43.0
        self.assertEqual(C.level_of(200, SCALE), 5)     # 68.0

    def test_the_scale_comes_from_the_file_not_from_here(self):
        """CHMI publishes gain 0.5 / offset -32.0, which is Denmark's pair and
        NOT Sweden's 0.4 / -30.0. A restated constant would draw the right map
        at the wrong intensity and look completely normal, so `level_of` takes
        the scale as an argument and has no default."""
        swedish = {"gain": 0.4, "offset": -30.0, "undetect": 0.0, "nodata": 255.0}
        # dn 140: CHMI reads 38 dBZ (level 4), Sweden's scale reads 26 (level 2)
        self.assertEqual(C.level_of(140, SCALE), 4)
        self.assertEqual(C.level_of(140, swedish), 2)
        with self.assertRaises(TypeError):
            C.level_of(100)


class TheProjectionIsSphericalMercator(unittest.TestCase):

    def test_the_equator_is_zero_and_north_is_positive(self):
        self.assertAlmostEqual(C._merc_y(0.0), 0.0, places=9)
        self.assertGreater(C._merc_y(51.0), C._merc_y(48.0))

    def test_a_known_pair_matches_the_closed_form(self):
        import math
        for lat in (48.047275, 50.09, 51.458369):
            want = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
            self.assertAlmostEqual(C._merc_y(lat), want, places=12)


class TheWindowWalksOutputCellsIntoTheGrid(unittest.TestCase):

    def setUp(self):
        import numpy as np
        self.np = np
        # 598x378 like the real product, all undetect.
        self.arr = np.zeros((378, 598), dtype=np.uint8)

    def _px(self, lat, lng):
        h, w = self.arr.shape
        y1, y0 = C._merc_y(CORNERS["UR_lat"]), C._merc_y(CORNERS["LL_lat"])
        return (int((lng - CORNERS["LL_lon"])
                    / (CORNERS["UR_lon"] - CORNERS["LL_lon"]) * w),
                int((y1 - C._merc_y(lat)) / (y1 - y0) * h))

    def test_a_dry_grid_is_all_zero_and_nothing_is_missing(self):
        lv, share = C.window(self.arr, SCALE, CORNERS, 14.42, 50.09, 280, 24, 12)
        self.assertEqual(int(lv.max()), 0)
        self.assertEqual(share, 0.0)

    def test_an_echo_at_the_readers_position_is_drawn(self):
        """The positive control. Today's real Czech sky topped out at 12.5 dBZ,
        which is below our lightest band, so every live map came back blank --
        honest, and indistinguishable from a classifier that never fires."""
        x, y = self._px(50.09, 14.42)
        self.arr[y - 15:y + 16, x - 15:x + 16] = 160     # 48 dBZ
        lv, _ = C.window(self.arr, SCALE, CORNERS, 14.42, 50.09, 280, 24, 12)
        self.assertEqual(int(lv.max()), 5)

    def test_nodata_counts_as_missing_and_undetect_does_not(self):
        self.arr[:, :] = 255
        _lv, share = C.window(self.arr, SCALE, CORNERS, 14.42, 50.09, 280, 24, 12)
        self.assertEqual(share, 1.0)

    def test_a_sky_off_the_edge_of_the_grid_is_missing_not_dry(self):
        lv, share = C.window(self.arr, SCALE, CORNERS, 19.61, 48.06, 280, 24, 12)
        self.assertGreater(share, 0.3)

    def test_north_is_up_in_the_output(self):
        """A raster read upside down still draws a map with the right scale and
        a fresh timestamp. Here the echo is placed north of the reader and has
        to appear in the upper half."""
        # 30 grid cells wide: the output cell is ~11.7 km and this walks OUTPUT
        # cells, sampling each centre, so a 5 km blob can fall between samples.
        x, y = self._px(51.0, 14.42)
        self.arr[y - 15:y + 16, x - 15:x + 16] = 160
        lv, _ = C.window(self.arr, SCALE, CORNERS, 14.42, 50.09, 280, 24, 12)
        rows = lv.tolist()
        top = sum(sum(1 for v in r if v) for r in rows[:6])
        bottom = sum(sum(1 for v in r if v) for r in rows[6:])
        self.assertGreater(top, 0)
        self.assertEqual(bottom, 0)


class TheMissingReaderSaysSoOutLoud(unittest.TestCase):
    """h5py is an optional extra. A source that declines silently because a
    library is absent hands the reader an empty grid and tells the health probe
    NO-MAP, which points the next hour of debugging at a network that is fine."""

    def test_draw_declines_and_names_the_reason_when_h5py_is_absent(self):
        import io
        old, C.have_h5py = C.have_h5py, lambda: False
        err, sys.stderr = sys.stderr, io.StringIO()
        try:
            self.assertIsNone(C.draw("><", 14.42, 50.09))
            self.assertIn("CHMI-NO-H5PY", sys.stderr.getvalue())
        finally:
            C.have_h5py, sys.stderr = old, err

    def test_outside_coverage_is_declined_before_anything_else(self):
        old, C.have_h5py = C.have_h5py, lambda: self.fail("asked too early")
        try:
            self.assertIsNone(C.draw("><", 2.35, 48.86))
        finally:
            C.have_h5py = old


class TheOrientationCheckCanSayAllFourThings(unittest.TestCase):
    """Fired against real data on 2026-08-13: OK upright, FLIPPED on the
    reversed array, INSUFFICIENT on a frame with no nodata, DISAGREE on a
    scrambled one. A check with only one reachable verdict is decoration."""

    RANGES = {"NE": 296.0, "NW": 269.0, "SE": 263.0, "SW": 259.0}

    def test_upright(self):
        counts = {"NE": 1447, "NW": 94, "SE": 9, "SW": 0}
        self.assertEqual(O.verdict(self.RANGES, counts)[0], "OK")

    def test_flipped(self):
        counts = {"SE": 1447, "SW": 94, "NE": 9, "NW": 0}
        self.assertEqual(O.verdict(self.RANGES, counts)[0], "FLIPPED")

    def test_a_frame_with_no_nodata_is_insufficient_not_ok(self):
        state, why = O.verdict(self.RANGES, {"NE": 0, "NW": 0, "SE": 0, "SW": 0})
        self.assertEqual(state, "INSUFFICIENT")
        self.assertIn("not a pass", why)

    def test_a_pattern_neither_reading_explains_is_disagree(self):
        counts = {"NE": 0, "NW": 900, "SE": 900, "SW": 0}
        self.assertEqual(O.verdict(self.RANGES, counts)[0], "DISAGREE")

    def test_the_range_ranking_is_computed_from_the_files_corners(self):
        r = O.corner_ranges(CORNERS)
        self.assertGreater(r["NE"], r["SW"])
        self.assertAlmostEqual(r["NE"], 296, delta=6)


class TheTermsCheckTreatsSilenceAsFailure(unittest.TestCase):
    """A catalogue that has been moved or taken down answers with zero
    bindings, and zero bindings satisfies any lazily written "nothing
    disagrees" test."""

    def test_an_empty_answer_is_not_a_pass(self):
        ok, lines = T.compare({})
        self.assertFalse(ok)
        self.assertIn("gone or renamed", lines[0])

    def test_the_recorded_answer_passes(self):
        self.assertTrue(T.compare(dict(T.EXPECT))[0])

    def test_a_licence_that_moved_fails(self):
        moved = dict(T.EXPECT)
        moved["autorské-dílo"] = "https://creativecommons.org/licenses/by-nc/4.0/"
        self.assertFalse(T.compare(moved)[0])

    def test_we_expect_cc_by_4_and_no_database_right(self):
        self.assertEqual(T.EXPECT["autorské-dílo"], T.CC_BY_4)
        self.assertIn("není-chráněna",
                      T.EXPECT["databáze-chráněná-zvláštními-právy"])


class AStaleCachedFrameMustNotPinTheSource(unittest.TestCase):
    """The fourth adapter with this shape, and the one that proves the point
    about scanning a family by shape rather than by symptom.

    MeteoSwiss declined the country outright and was loud about it. Here the
    lookback window (25 min) sits under the staleness limit (30 min), so the
    same bug just quietly served an older frame than necessary and refreshed
    only once the stale entry aged out. Nothing logged, no probe went red.
    """

    def setUp(self):
        import tempfile
        self.old_cache = C.CACHE
        C.CACHE = tempfile.mkdtemp()
        # draw() returns before the cache logic when h5py is absent, so pin the
        # reader: which slot is consulted has nothing to do with HDF5, and
        # skipping would hide it on the machine that runs this on every push.
        self.old_have = C.have_h5py
        C.have_h5py = lambda: True

    def tearDown(self):
        C.CACHE = self.old_cache
        C.have_h5py = self.old_have

    def calls_for(self, slots_back, cached_only=False):
        cand = C.stamps()
        with open(C._cache_path(cand[slots_back]), "wb") as fh:
            fh.write(b"\x89HDF\r\n\x1a\n" + b"0" * 64)
        asked = []

        def get(u):
            asked.append(u)
            return b""
        C.draw("><", 14.42, 50.09, get=get, cached_only=cached_only)
        return asked

    def test_a_fresh_cached_frame_is_served_without_asking_upstream(self):
        self.assertEqual(self.calls_for(0), [])

    def test_a_stale_cached_frame_does_not_prevent_asking_for_a_newer_one(self):
        self.assertTrue(self.calls_for(5),
                        "a 25-minute-old cached frame won outright and "
                        "upstream was never asked -- the silent symptom")

    def test_cached_only_opens_no_socket_even_when_the_cache_is_stale(self):
        self.assertEqual(self.calls_for(5, cached_only=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
