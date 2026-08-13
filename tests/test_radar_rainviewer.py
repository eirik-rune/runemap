"""The three ways this source lies quietly, each pinned by a test.

None of these touch the network: the failures they guard against are geometry
and configuration, not connectivity, and a test that needs the internet is a
test that gets skipped on the day it matters.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import radar_rainviewer as RV      # noqa: E402
from PIL import Image              # noqa: E402

# lat, lon. The four skies this source exists for, plus two positive controls
# whose upstream frames are healthy (they must behave identically here -- a
# guard that only ever sees broken input has never been shown to pass).
CITIES = [("mumbai", 19.08, 72.88), ("saopaulo", -23.55, -46.63),
          ("london", 51.5, -0.12), ("paris", 48.86, 2.35),
          ("chiangmai", 18.79, 98.98), ("beijing", 39.9, 116.4)]


def _png(color):
    b = io.BytesIO()
    Image.new("RGBA", (RV.TILE_PX, RV.TILE_PX), color).save(b, "PNG")
    return b.getvalue()


class TheBoxActuallyContainsTheSpan(unittest.TestCase):
    """The bug this file was written for: the city sits on a tile seam.

    At z6 mumbai is at 0.96 of its tile's width, london 0.98, paris 0.02 of its
    height. A single-tile fetch draws a normal-looking map with half the rain
    outside it and reports nothing at all.
    """

    @staticmethod
    def covers(bbox, lat, lon, span):
        import math
        s, w, north, e = bbox
        d_lat = span / 2.0 / 111.0
        d_lon = span / 2.0 / (111.0 * max(0.2, math.cos(math.radians(lat))))
        return (s <= lat - d_lat and north >= lat + d_lat
                and w <= lon - d_lon and e >= lon + d_lon)

    def test_requested_span_is_inside_the_returned_bbox(self):
        for name, lat, lon in CITIES:
            xs, ys, n = RV.plan(lat, lon, 280.0)
            self.assertTrue(self.covers(RV.bbox_of(xs, ys, n), lat, lon, 280.0),
                            "%s: the plan cuts the span it was asked for" % name)

    def test_the_ruler_can_fail(self):
        """Positive control, both directions, on the same predicate.

        Without this the test above would also pass against a planner that
        returned the whole world, and I could not tell which one I had. The
        shrunk box is the shape of the bug: a single tile with the city on its
        seam still looks like a perfectly normal map.
        """
        lat, lon = 51.5, -0.12
        xs, ys, n = RV.plan(lat, lon, 280.0)
        real = RV.bbox_of(xs, ys, n)
        self.assertTrue(self.covers(real, lat, lon, 280.0))
        s, w, north, e = real
        shrunk = (lat - 0.01, lon - 0.01, lat + 0.01, lon + 0.01)
        self.assertFalse(self.covers(shrunk, lat, lon, 280.0),
                         "the predicate accepts a box 2km wide: it is vacuous")

    def test_bbox_is_south_west_north_east(self):
        xs, ys, n = RV.plan(19.08, 72.88, 280.0)
        s, w, north, e = RV.bbox_of(xs, ys, n)
        self.assertLess(s, north)
        self.assertLess(w, e)


class ZoomEightServesOneImageForEveryCoordinate(unittest.TestCase):
    """Measured: (177,113), (178,113), (177,114) at z8 all return 200, 3269
    bytes, identical sha256. Nothing errors; two different cities produced
    identical ink counts and that is the only reason I looked."""

    def test_above_max_zoom_is_refused(self):
        with self.assertRaises(ValueError):
            RV.plan(19.08, 72.88, 280.0, zoom=RV.MAX_ZOOM + 1)

    def test_max_zoom_itself_still_works(self):
        xs, ys, n = RV.plan(19.08, 72.88, 280.0, zoom=RV.MAX_ZOOM)
        self.assertTrue(xs and ys)


class AMissingTileIsReportedNotHidden(unittest.TestCase):

    def test_all_present(self):
        xs, ys, _n = RV.plan(19.08, 72.88, 280.0)
        img, bbox, got, want = RV.fetch("h", "/p", 19.08, 72.88,
                                        get=lambda u, timeout=10: _png((0, 0, 255, 255)))
        self.assertEqual(got, want)
        self.assertEqual(want, len(xs) * len(ys))
        self.assertGreater(want, 1, "a single tile means the seam bug is back")
        self.assertEqual(img.size, (RV.TILE_PX * len(xs), RV.TILE_PX * len(ys)))

    def test_one_tile_failing_leaves_a_hole_and_says_so(self):
        seen = {"n": 0}

        def flaky(url, timeout=10):
            seen["n"] += 1
            if seen["n"] == 1:
                raise IOError("upstream said no")
            return _png((0, 0, 255, 255))

        img, bbox, got, want = RV.fetch("h", "/p", 19.08, 72.88, get=flaky)
        self.assertEqual(got, want - 1, "a hole must be counted, not swallowed")
        self.assertEqual(img.getpixel((0, 0))[3], 0, "the hole must stay transparent")

    def test_url_carries_the_zoom_it_was_planned_at(self):
        u = RV.tile_url("https://h", "/v2/radar/abc", 88, 56, 7, 128)
        self.assertIn("/512/7/88/56/", u)
        self.assertTrue(u.endswith(".png"))


class FramesComeFromTheIndexNotFromGuessing(unittest.TestCase):

    def test_empty_index_is_empty_not_an_error(self):
        self.assertEqual(RV.frames({}), [])
        self.assertEqual(RV.frames({"radar": {}}), [])

    def test_frames_are_oldest_first_with_epoch_seconds(self):
        idx = {"radar": {"past": [{"time": 10, "path": "/a"},
                                  {"time": 20, "path": "/b"}]}}
        self.assertEqual(RV.frames(idx), [(10, "/a"), (20, "/b")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
