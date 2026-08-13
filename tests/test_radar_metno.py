"""Norway: the projection, the two kinds of nothing, and the words for failure.

Hermetic. The fixture in `fixtures_metno_ascii.txt` is a real OPeNDAP response
captured on 2026-08-13; the coordinates the projection is checked against are
the file's OWN `lat`/`lon` arrays, read from the live grid the same evening and
copied here literally.
"""
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "scripts"), os.path.join(_ROOT, "ops"), _ROOT):
    sys.path.insert(0, _p)

import lcc                       # noqa: E402
import radar_metno as M          # noqa: E402

PROJ4 = "+proj=lcc +lat_0=63 +lon_0=15 +lat_1=63 +lat_2=63 +no_defs +R=6.371e+06"

# (name, lat, lng, row, col, file's own lat, file's own lon at that cell)
CITIES = [
    ("Oslo", 59.9139, 10.7522, 1460, 559, 59.918274, 10.750573),
    ("Bergen", 60.3913, 5.3221, 1375, 266, 60.39335, 5.325492),
    ("Tromso", 69.6492, 18.9553, 379, 950, 69.650345, 18.955868),
    ("Trondheim", 63.4305, 10.3951, 1069, 567, 63.429794, 10.391953),
]


def fixture():
    with open(os.path.join(os.path.dirname(__file__),
                           "fixtures_metno_ascii.txt")) as fh:
        return fh.read()


class TheProjectionIsCheckedAgainstTheFilesOwnCoordinates(unittest.TestCase):
    """The grid could be read upside down and still produce a scale-correct,
    freshly-stamped map of the wrong half of Norway. What settles it is that
    the file ships 2-D lat/lon arrays: the cell is computed first, and only
    then is the file asked what it puts there."""

    def test_each_city_lands_on_the_cell_the_file_agrees_with(self):
        for name, lat, lng, row, col, flat, flon in CITIES:
            self.assertEqual(M.cell_of(lat, lng), (row, col), name)
            blat, blon = lcc.inverse(M.X0 + col * M.CELL, M.Y0 - row * M.CELL)
            self.assertAlmostEqual(blat, flat, places=3, msg=name)
            self.assertAlmostEqual(blon, flon, places=3, msg=name)

    def test_north_is_row_zero(self):
        """Measured off the axis, not assumed: Yc DECREASES with index."""
        north = M.cell_of(69.6492, 18.9553)[0]
        south = M.cell_of(59.9139, 10.7522)[0]
        self.assertLess(north, south)

    def test_a_flipped_read_would_put_tromso_in_the_south(self):
        """The positive control for the check above: if row 0 were the south
        edge, the northernmost city would land in the southern half."""
        row = M.cell_of(69.6492, 18.9553)[0]
        self.assertLess(row, M.NY / 2)
        self.assertGreater(M.NY - 1 - row, M.NY / 2)

    def test_the_grid_it_can_read_is_one_specific_grid(self):
        self.assertTrue(lcc.assert_proj4(PROJ4))
        for broken in ("+proj=lcc +lat_0=60 +lon_0=15 +lat_1=63 +lat_2=63 +R=6.371e+06",
                       "+proj=stere +lat_0=63 +lon_0=15 +lat_1=63 +lat_2=63 +R=6.371e+06",
                       "+proj=lcc +lat_0=63 +lon_0=15 +lat_1=63 +lat_2=63"):
            with self.assertRaises(ValueError):
                lcc.assert_proj4(broken)

    def test_a_point_off_the_grid_says_so(self):
        self.assertIsNone(M.cell_of(0.0, 0.0))


class TwoKindsOfNothing(unittest.TestCase):
    """`_FillValue` and `is_nodata` both mean "no number here" and they mean
    completely different things. Reading the fill as blindness turns a clear
    sky into "no radar here"; reading blindness as dry paints rain-free
    weather over places nobody can see.

    Measured on the live grid, 2026-08-13: over Oslo, `is_nodata` is 0% while
    76% of cells carry the fill, scattered as speckle among values like
    -6.5 dBZ. Over the mid-Norwegian Sea, `is_nodata` is 100%. A blind region
    is contiguous; below-detection cells are speckle.
    """

    def test_not_seen_is_minus_one(self):
        self.assertEqual(M.level_at(20.0, True), -1)
        self.assertEqual(M.level_at(M.FILL_MIN * 10, True), -1)

    def test_seen_with_nothing_detected_is_dry_not_blind(self):
        self.assertEqual(M.level_at(9.96921e36, False), 0)

    def test_below_the_shared_floor_is_dry(self):
        """The floor is the fleet's, from scripts/dbz.py. Three countries once
        drew clear-air clutter as light rain because each module kept its own
        copy of this table."""
        import dbz
        self.assertEqual(M.level_at(-6.5, False), 0)
        self.assertEqual(M.level_at(dbz.FLOOR_DBZ - 0.1, False), 0)
        self.assertGreaterEqual(M.level_at(dbz.FLOOR_DBZ, False), 1)

    def test_real_rain_climbs_the_ramp(self):
        import dbz
        for v in (20.0, 35.0, 50.0):
            self.assertEqual(M.level_at(v, False), dbz.level_for(v))

    def test_the_two_nothings_do_not_give_the_same_answer(self):
        """The positive control for this whole class."""
        self.assertNotEqual(M.level_at(9.96921e36, False),
                            M.level_at(9.96921e36, True))


class ItReadsTheServersOwnAnswer(unittest.TestCase):

    def test_it_parses_both_variables_out_of_one_response(self):
        p = M.parse_ascii(fixture())
        self.assertIn("equivalent_reflectivity_factor", p)
        self.assertIn("is_nodata", p)
        self.assertEqual(len(p["equivalent_reflectivity_factor"]), 3)
        self.assertEqual(len(p["equivalent_reflectivity_factor"][0]), 3)

    def test_the_frame_time_comes_from_the_data_not_the_filename(self):
        """The response carries `time` in epoch seconds, so the age a reader
        is shown does not rest on my having parsed a filename correctly."""
        ts = M.frame_time(M.parse_ascii(fixture()))
        self.assertIsNotNone(ts)
        import time as _t
        self.assertEqual(_t.strftime("%Y%m%dT%H%M", _t.gmtime(ts)),
                         "20260813T1920")

    def test_a_response_with_no_time_is_not_given_an_invented_one(self):
        self.assertIsNone(M.frame_time({"equivalent_reflectivity_factor": [[1.0]]}))

    def test_an_error_page_parses_to_nothing_rather_than_to_numbers(self):
        self.assertIsNone(M.frame_time(M.parse_ascii("<html>503</html>")))


class DiscoveryCanFailOutLoud(unittest.TestCase):

    def test_stamps_are_newest_first_and_on_the_five_minute_grid(self):
        s = M.stamps(now=1786648805.0)
        self.assertEqual(s[0], "20260813T192000Z")
        self.assertEqual(s[1], "20260813T191500Z")
        self.assertEqual(len(s), M.LOOKBACK)

    def test_it_walks_back_past_frames_that_are_not_published_yet(self):
        """~25 minutes of publication latency, so the newest stamps 404."""
        import urllib.error
        seen = []

        def get(url):
            seen.append(url)
            if len(seen) < 4:
                raise urllib.error.HTTPError(url, 404, "no", None, None)
            return fixture()
        stamp, parsed = M.newest(get, now=1786648805.0)
        self.assertEqual(stamp, "20260813T190500Z")
        self.assertIsNotNone(M.frame_time(parsed))

    def test_running_out_of_candidates_is_not_a_clear_sky(self):
        """Every failure this fleet has reaches a reader as an empty grid,
        which is what fine weather looks like. This one returns None so the
        caller declines, and says so on stderr."""
        import urllib.error

        def gone(url):
            raise urllib.error.HTTPError(url, 404, "no", None, None)
        self.assertEqual(M.newest(gone, now=1786648805.0), (None, None))

    def test_a_server_error_stops_rather_than_hammering_the_service(self):
        """404 means "try an older one". 500 means the service is unwell, and
        walking twelve more stamps would spend its trouble on more requests."""
        import urllib.error
        calls = []

        def broken(url):
            calls.append(url)
            raise urllib.error.HTTPError(url, 500, "boom", None, None)
        self.assertEqual(M.newest(broken, now=1786648805.0), (None, None))
        self.assertEqual(len(calls), 1)


class ItDeclinesWhereItCannotSee(unittest.TestCase):

    def test_coverage_is_norway(self):
        self.assertTrue(M.covers(10.7522, 59.9139))     # Oslo
        self.assertTrue(M.covers(18.9553, 69.6492))     # Tromso
        self.assertFalse(M.covers(2.35, 48.86))         # Paris
        self.assertFalse(M.covers(139.69, 35.69))       # Tokyo

    def test_covers_answers_what_it_can_see_not_who_it_should_serve(self):
        """Two different questions, and a lat/lon box cannot answer the second:
        Norway is not a rectangle, and any box holding both Finnmark and the
        south coast also holds Stockholm. So `covers()` is honest about the
        mosaic -- it really does see Sweden -- and the decision about who gets
        served belongs to the chain, which must order this source after the
        national ones. A guard here could only lie about the real extent."""
        self.assertTrue(M.covers(18.07, 59.33))         # Stockholm, truly seen
        self.assertEqual(M.SERVES, ("NO",))

    def test_outside_coverage_nothing_is_fetched_at_all(self):
        def fail(url):
            self.fail("asked the network about a place it cannot see")
        self.assertIsNone(M.draw("><", 2.35, 48.86, get=fail))

    def test_a_readers_wait_is_never_spent_on_the_network(self):
        """Nothing is held on disk for this source, so `cached_only` has no
        cheap answer to give and must decline instead of fetching."""
        def fail(url):
            self.fail("spent a reader's wait")
        self.assertIsNone(
            M.draw("><", 10.7522, 59.9139, get=fail, cached_only=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
