"""Denmark: the scale, the geometry, and the words for not knowing. Hermetic.

Fixtures are taken from a real frame (`dk.com.202608131535.500_max.h5`) and
from DMI's own volume files, copied literally. Nothing here touches the
network.
"""
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "scripts"), os.path.join(_ROOT, "ops"), _ROOT):
    sys.path.insert(0, _p)

import radar_dmi as D          # noqa: E402

# /what and /where of a real frame, verbatim.
SCALE = {"gain": 0.5, "offset": -32.0, "undetect": 0.0, "nodata": 255.0}
CORNERS = {"LL_lat": 52.29427206432812, "LL_lon": 4.379082700525593,
           "LR_lat": 52.29427206432812, "LR_lon": 18.893280870398133,
           "UL_lat": 60.0, "UL_lon": 3.0,
           "UR_lat": 59.827708427801085, "UR_lon": 20.735140174892805}
CELL = 500.0
# Site coordinates as DMI's own volume files state them.
SITES = [("dksam", 55.812, 10.585), ("dkbor", 55.11275, 14.887517),
         ("dkste", 55.326, 12.449), ("dkrom", 55.173, 8.552),
         ("dksin", 57.489, 10.136)]


class TheScaleIsTheirsNotOurs(unittest.TestCase):

    def test_nodata_is_not_no_rain(self):
        """Every failure this fleet has had reaches a reader as an empty grid,
        which is what a clear sky looks like. -1 is not 0."""
        self.assertEqual(D.level_of(255, SCALE), -1)
        self.assertEqual(D.level_of(0, SCALE), 0)

    def test_a_value_below_the_shared_floor_is_not_rain(self):
        """DN 78 is 7 dBZ exactly, the floor DWD publishes. Below it, clear-air
        clutter -- insects and ground echo on a hot dry day -- used to draw as
        light rain across three countries."""
        self.assertEqual(D.level_of(77, SCALE), 0)
        self.assertEqual(D.level_of(78, SCALE), 1)

    def test_the_bands_come_from_the_shared_table(self):
        import dbz
        for dn in (100, 130, 160, 190):
            self.assertEqual(D.level_of(dn, SCALE),
                             dbz.level_for(0.5 * dn - 32.0))

    def test_a_swedish_scale_would_draw_the_same_map_at_the_wrong_intensity(self):
        """0.4/-30.0 is SMHI's pair. Restating a constant is how a source gets
        read plausibly and wrongly, so this pins that they differ."""
        smhi = dict(SCALE, gain=0.4, offset=-30.0)
        self.assertNotEqual(D.level_of(120, SCALE), D.level_of(120, smhi))


class TheGridIsBuiltFromOneAnchor(unittest.TestCase):

    def test_a_radar_site_lands_inside_the_grid(self):
        import dmi_orient as O
        rc = O._cell(CORNERS, CELL, (1728, 1984), 55.11275, 14.887517)
        self.assertIsNotNone(rc)
        r, c = rc
        self.assertTrue(0 <= r < 1728 and 0 <= c < 1984, rc)

    def test_the_projection_is_asserted_by_value(self):
        import stereo_oblique as SO
        self.assertTrue(SO.assert_proj4(
            "+proj=stere +ellps=WGS84 +lat_0=56 +lon_0=10.5666 +lat_ts=56"))
        with self.assertRaises(ValueError):
            SO.assert_proj4("+proj=stere +lat_0=90 +lon_0=0 +lat_ts=60")

    def test_coverage_refuses_places_the_radars_cannot_see(self):
        self.assertTrue(D.covers(12.57, 55.68))     # Copenhagen
        self.assertTrue(D.covers(9.92, 57.05))      # Aalborg
        self.assertFalse(D.covers(2.35, 48.86))     # Paris
        self.assertFalse(D.covers(18.07, 59.33))    # Stockholm


class TheOrientationCheckCanReturnEveryVerdictItPrints(unittest.TestCase):
    """A judgement that only ever prints one word has no jurisdiction (快刀手,
    8/12). Each verdict is shown firing on a frame built to earn it."""

    def frame(self, seen_centres, radius_cells=200):
        """A synthetic composite: nodata everywhere except disks around the
        given points, which is what a real composite's blind mask looks like."""
        import numpy as np
        import stereo_oblique as SO
        arr = np.full((1728, 1984), 255, dtype=np.uint8)
        ax, ay = SO.forward(CORNERS["UL_lat"], CORNERS["UL_lon"])
        yy, xx = np.mgrid[0:1728, 0:1984]
        for lat, lng in seen_centres:
            x, y = SO.forward(lat, lng)
            cx, cy = (x - ax) / CELL, (ay - y) / CELL
            arr[((xx - cx) ** 2 + (yy - cy) ** 2) < radius_cells ** 2] = 0
        return arr

    def test_ok(self):
        import dmi_orient as O
        arr = self.frame([(la, lo) for _n, la, lo in SITES])
        v, note = O.judge(arr, SCALE, CORNERS, CELL, SITES)
        self.assertEqual(v, "OK", note)

    def test_flipped(self):
        """The failure this whole file exists for: an upside-down read draws a
        scale-correct, fresh-stamped map of the wrong half of the country."""
        import numpy as np
        import dmi_orient as O
        arr = np.flipud(self.frame([(la, lo) for _n, la, lo in SITES]))
        v, note = O.judge(arr, SCALE, CORNERS, CELL, SITES)
        self.assertEqual(v, "FLIPPED", note)

    def test_disagree_when_the_seen_area_is_nowhere_near_the_radars(self):
        import dmi_orient as O
        arr = self.frame([(58.9, 6.0)])       # a disk over southern Norway
        v, note = O.judge(arr, SCALE, CORNERS, CELL, SITES)
        self.assertEqual(v, "DISAGREE", note)

    def test_insufficient_is_its_own_word(self):
        """"I cannot tell" must not print the same string as "they disagree":
        one sends you to the data, the other to the code."""
        import dmi_orient as O
        arr = self.frame([(la, lo) for _n, la, lo in SITES])
        v, _ = O.judge(arr, SCALE, CORNERS, CELL, SITES[:1])
        self.assertEqual(v, "INSUFFICIENT")

    def test_insufficient_when_the_frame_sees_nothing_at_all(self):
        import numpy as np
        import dmi_orient as O
        arr = np.full((1728, 1984), 255, dtype=np.uint8)
        v, _ = O.judge(arr, SCALE, CORNERS, CELL, SITES)
        self.assertEqual(v, "INSUFFICIENT")


class ItNamesWhyItCannotWork(unittest.TestCase):

    def test_a_missing_reader_is_named_not_silently_declined(self):
        """Missing h5py and a dead upstream both reach a reader as an empty
        grid. One word for both sends the next hour to the wrong place."""
        real = D.have_h5py
        try:
            D.have_h5py = lambda: False
            msg = D.unavailable()
            self.assertIn("h5py", msg or "")
            self.assertIsNone(D.draw("><", 12.57, 55.68))
        finally:
            D.have_h5py = real

    def test_a_working_install_reports_nothing_to_report(self):
        """The positive control: if unavailable() could only ever return a
        sentence, it would be decoration."""
        if not D.have_h5py():
            self.skipTest("h5py absent here; the other direction is pinned above")
        self.assertIsNone(D.unavailable())


class TheFrameNameIsTheClock(unittest.TestCase):

    def test_the_stamp_comes_from_the_filename_we_asked_for(self):
        ts = D.stamp_of("dk.com.202608131535.500_max.h5")
        self.assertIsNotNone(ts)
        import time
        self.assertEqual(time.strftime("%Y%m%d%H%M", time.gmtime(ts)),
                         "202608131535")

    def test_an_unparseable_name_says_so_rather_than_guessing(self):
        self.assertIsNone(D.stamp_of("dk.com.someday.500_max.h5"))


class TheListingIsAskedOnceAndCanBeEmpty(unittest.TestCase):

    def test_one_request_per_discovery(self):
        """Walking candidate timestamps is what burned 18 requests of a quota
        shared with strangers at KNMI. This asks once."""
        calls = []

        def get(u):
            calls.append(u)
            return b'{"features":[{"id":"dk.com.202608131535.500_max.h5"}]}'
        self.assertEqual(D.newest_frame(get), "dk.com.202608131535.500_max.h5")
        self.assertEqual(len(calls), 1)

    def test_an_empty_list_is_not_a_clear_sky(self):
        self.assertIsNone(D.newest_frame(lambda u: b'{"features":[]}'))

    def test_a_broken_listing_is_not_a_clear_sky(self):
        self.assertIsNone(D.newest_frame(lambda u: b"<html>503</html>"))


class AStaleCachedFrameMustNotPinTheSource(unittest.TestCase):
    """Found by fixing the same bug in MeteoSwiss and then scanning the family.

    draw() used to answer from ANY cached slot in its whole window before
    asking upstream what was newest, so one old entry served readers a frame up
    to 25 minutes old with a fresh one available, and the cache only refreshed
    once that entry aged out. Reproduced deliberately before the fix: seeding
    only an old slot made draw() return with zero network calls.
    """

    def setUp(self):
        import tempfile
        self.old_cache = D.CACHE
        D.CACHE = tempfile.mkdtemp()
        # draw() returns before the cache logic when h5py is absent, so without
        # this the test passes here and fails on CI, which does not install the
        # optional extra. Pinned rather than skipped: which slot is consulted
        # has nothing to do with HDF5, and skipping would hide it on the one
        # machine that runs this suite on every push. Third time tonight -- the
        # difference is that this one was caught before pushing.
        self.old_have = D.have_h5py
        D.have_h5py = lambda: True

    def tearDown(self):
        D.CACHE = self.old_cache
        D.have_h5py = self.old_have

    def seed(self, slots_back):
        import math
        import time
        now = time.time()
        old = math.floor((now - slots_back * D.STEP) / D.STEP) * D.STEP
        name = "dk.com.%s.500_max.h5" % time.strftime("%Y%m%d%H%M",
                                                      time.gmtime(old))
        with open(D._cache_path(name), "wb") as fh:
            fh.write(b"\x89HDF\r\n\x1a\n" + b"0" * 64)

    def calls_for(self, slots_back, cached_only=False):
        self.seed(slots_back)
        asked = []

        def get(u):
            asked.append(u)
            return b'{"features":[]}'
        D.draw("><", 12.57, 55.68, get=get, cached_only=cached_only)
        return asked

    def test_a_fresh_cached_frame_is_served_without_asking_upstream(self):
        """The cache must still do its job -- otherwise this 'fix' is just a
        way to make every reader pay for a round trip."""
        self.assertEqual(self.calls_for(1), [])

    def test_a_stale_cached_frame_does_not_prevent_asking_what_is_newest(self):
        self.assertEqual(len(self.calls_for(5)), 1)

    def test_cached_only_opens_no_socket_even_when_the_cache_is_stale(self):
        """The other half of the contract: a reader already holding a map does
        not pay for a round trip, however old our cache is."""
        self.assertEqual(self.calls_for(5, cached_only=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
