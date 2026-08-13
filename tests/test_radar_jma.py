"""Japan. Hermetic -- every fixture is a literal, no network.

Most of these exist because the thing they pin already went wrong once during
the hour this adapter was written.
"""
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import radar_jma as J          # noqa: E402
import radar_rainviewer as RV  # noqa: E402


def stamp(offset_s=0):
    return time.strftime("%Y%m%d%H%M%S", time.gmtime(time.time() - offset_s))


class CoverageMustNotAnnexTheNeighbours(unittest.TestCase):
    """One rectangle cannot hold Japan without holding Korea: Yonaguni is at
    122.9E and Seoul at 127.0E. A sky JMA does not cover would render as an
    empty grid, and an empty grid reads as 'no rain', not 'not looking'."""

    def test_japan_is_covered(self):
        for lng, lat in [(139.69, 35.69), (135.50, 34.69), (141.35, 43.06),
                         (127.68, 26.21), (130.40, 33.59)]:
            self.assertTrue(J.covers(lng, lat), (lng, lat))

    def test_korea_is_not(self):
        for lng, lat in [(126.98, 37.57), (129.03, 35.18)]:   # seoul, busan
            self.assertFalse(J.covers(lng, lat), (lng, lat))

    def test_shanghai_and_vladivostok_are_not(self):
        self.assertFalse(J.covers(121.47, 31.23))
        self.assertFalse(J.covers(131.89, 43.12))


class OnlyTheObservedFrame(unittest.TestCase):
    """The file is a nowcast: most of what it lists is forecast. Using those
    would be both a different promise than 'what the radar sees now' and a
    regulated one under the Meteorological Business Act."""

    def test_a_forecast_step_is_never_chosen(self):
        now, later = stamp(0), stamp(-3600)
        times = [{"basetime": now, "validtime": later},     # forecast
                 {"basetime": now, "validtime": now}]       # observation
        ts, bt = J.observed_frame(times)
        self.assertEqual(bt, now)

    def test_all_forecast_is_no_frame_not_the_nearest_one(self):
        now = stamp(0)
        times = [{"basetime": now, "validtime": stamp(-600)}]
        self.assertEqual(J.observed_frame(times), (None, None))

    def test_an_old_frame_is_refused(self):
        old = stamp(J.FRAME_MAX_AGE + 600)
        self.assertEqual(J.observed_frame([{"basetime": old, "validtime": old}]),
                         (None, None))

    def test_an_unparseable_stamp_is_none_not_a_crash(self):
        self.assertEqual(J.observed_frame([{"basetime": "soon", "validtime": "soon"}]),
                         (None, None))


class TheZoomIsTheirsNotRainViewers(unittest.TestCase):
    """Measured over Tokyo: z6 carries data, **z7 returns the 334-byte fully
    transparent tile everywhere**, z8 carries data again. RainViewer's default
    is 7, and taking it would have shipped a Japan whose sky is always clear --
    200, a valid PNG, and nothing in it."""

    def test_we_do_not_use_the_empty_level(self):
        self.assertNotEqual(J.ZOOM, 7)

    def test_the_url_carries_the_level_we_asked_for(self):
        u = J.tile_url("20260813094000", 227, 100, 8, 256)
        self.assertIn("/hrpns/8/227/100.png", u)

    def test_a_nonsense_zoom_is_refused_here_not_upstream(self):
        with self.assertRaises(ValueError):
            J.tile_url("20260813094000", 227, 100, 64, 256)

    def test_the_shared_planner_takes_a_per_service_ceiling(self):
        """RainViewer's ceiling is RainViewer's. Importing it into another
        service is the same mistake as copying its freshness window onto the
        Brazilian mirror."""
        RV.plan(35.69, 139.69, 280.0, zoom=8, max_zoom=10)
        with self.assertRaises(ValueError):
            RV.plan(35.69, 139.69, 280.0, zoom=8)


class TheScaleIsAnOrderNotAGuessAboutMillimetres(unittest.TestCase):

    def test_the_levels_never_go_backwards(self):
        levels = [lv for _c, lv in J.PALETTE]
        self.assertEqual(levels, sorted(levels))

    def test_the_pair_the_derivation_could_not_separate_shares_a_level(self):
        """Their mean depths differ by 0.014 over 192 tiles, which is not a
        separation. Nothing a reader sees may depend on it."""
        by = dict(J.PALETTE)
        self.assertEqual(by[(33, 140, 255)], by[(0, 65, 255)])

    def test_the_extremes_are_the_extremes(self):
        by = dict(J.PALETTE)
        self.assertEqual(by[(242, 242, 255)], 1)
        self.assertEqual(by[(180, 0, 104)], 5)

    def test_a_colour_they_never_declared_is_not_rain(self):
        import numpy as np
        a = np.zeros((3, 3, 4), dtype=np.uint8)
        a[..., 0], a[..., 1], a[..., 2], a[..., 3] = 7, 200, 7, 255
        self.assertEqual(int(J.classify(a).max()), 0)

    def test_transparent_is_never_rain(self):
        import numpy as np
        a = np.zeros((3, 3, 4), dtype=np.uint8)
        a[..., 0], a[..., 1], a[..., 2], a[..., 3] = 180, 0, 104, 0
        self.assertEqual(int(J.classify(a).max()), 0)


class TheCacheKeyNamesEverythingThatChangesThePicture(unittest.TestCase):
    """It did not name the zoom, and the first thing that cost was a lie to me:
    after moving from z6 to z8 it kept serving the z6 mosaic, identical art and
    identical km/col, so the change looked like it had done nothing."""

    def test_two_zooms_are_two_files(self):
        self.assertNotEqual(J._cache_path(139.69, 35.69, "20260813094000", zoom=6),
                            J._cache_path(139.69, 35.69, "20260813094000", zoom=8))

    def test_two_frames_are_two_files(self):
        self.assertNotEqual(J._cache_path(139.69, 35.69, "20260813094000"),
                            J._cache_path(139.69, 35.69, "20260813094500"))

    def test_two_skies_are_two_files(self):
        self.assertNotEqual(J._cache_path(139.69, 35.69, "20260813094000"),
                            J._cache_path(135.50, 34.69, "20260813094000"))


class CachedOnlyMeansNoThirdPartyAtAll(unittest.TestCase):
    """The tile cache is not the whole third party. The frame index is a second
    request to jma.go.jp (0.57s measured), and gating only the tiles left every
    reader arriving on a cold scene paying it -- for an upgrade to a map they
    already held. It showed up as a median cold render of 1.4s against
    yesterday's 0.9s, which the tile gate could not explain."""

    def setUp(self):
        self._saved = dict(J._INDEX)
        J._INDEX["at"], J._INDEX["v"] = 0.0, None

    def tearDown(self):
        J._INDEX.update(self._saved)

    def _count_calls(self):
        """Count the reaches, do not raise on them.

        The first version of these two raised from the fake urlopen, and one of
        them stayed green against the unfixed code: `_times` catches Exception
        so the network failure path can degrade to the last index, and it
        swallowed the assertion along with it. A fire test the subject can catch
        is not a fire test -- so the probe records instead of throwing.
        """
        calls = []
        def fake(*a, **k):
            calls.append(a[0] if a else None)
            raise OSError("no network in tests")
        self._old = urllib.request.urlopen
        urllib.request.urlopen = fake
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", self._old))
        return calls

    def test_an_empty_index_is_not_fetched_on_a_readers_thread(self):
        calls = self._count_calls()
        self.assertIsNone(J._times(cached_only=True))
        self.assertEqual(J.observed_frame(cached_only=True), (None, None))
        self.assertIsNone(J.draw("><", 139.69, 35.69, cached_only=True))
        self.assertEqual(calls, [])

    def test_a_stale_index_is_not_refreshed_on_a_readers_thread(self):
        now = stamp(0)
        J._INDEX["at"] = time.time() - J.INDEX_TTL - 1
        J._INDEX["v"] = [{"basetime": now, "validtime": now}]
        calls = self._count_calls()
        self.assertIsNone(J._times(cached_only=True))
        self.assertEqual(calls, [])

    def test_a_fresh_index_is_still_served_without_the_network(self):
        now = stamp(0)
        J._INDEX["at"] = time.time()
        J._INDEX["v"] = [{"basetime": now, "validtime": now}]
        self.assertEqual(J.observed_frame(cached_only=True)[1], now)

    def test_the_warm_path_may_still_fetch(self):
        """Otherwise nobody ever fetches it and Japan goes dark quietly --
        the guard would be a permanently closed gate rather than a gate."""
        calls = []
        class R:
            def read(self_):
                calls.append(1)
                now = stamp(0)
                return ('[{"basetime":"%s","validtime":"%s"}]' % (now, now)).encode()
        old, urllib.request.urlopen = urllib.request.urlopen, lambda *a, **k: R()
        try:
            self.assertTrue(J._times())
            self.assertEqual(len(calls), 1)
        finally:
            urllib.request.urlopen = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
