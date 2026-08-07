"""Motion must be measured from the frame the reader is looking at.

8/7 first version of this file encoded the wrong requirement. bob reported a
map full of echo above the line "no echo to track", and I concluded motion had
to be recomputed from a separately fetched observation list. He corrected it:
a forecast pair IS the motion this map predicts -- that is the product. The
real defect was the pivot. echo_motion took frames[-1] as "now", which is the
newest frame of an observation list and the FARTHEST FUTURE frame of a forecast
list. Measured at chiang mai 8/7 15:52: the list spans -19.1..+105.9min, the
renderer draws +0.9, and motion was correlating +45.9 against +105.9. Both
sentences on the page were true; they were about two different skies.

So the invariant is not "observation frames". It is: the pair motion correlates
CONTAINS the frame the renderer draws. Same pixels, same sky, and the two lines
cannot contradict each other no matter what the wording says.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as RS
import echo_motion as EM


NOW = time.time()
# a forecast list as upstream really shapes it: begins at the last observation,
# runs out past +100min (measured spans 8/7: -19.1..+105.9, -1.9..+147.2)
FORECAST = [["https://f/%d.png" % i, NOW - 1200 + i * 300, [1, 2, 3, 4]]
            for i in range(26)]
# an observation list: entirely in the past (mumbai/sydney, forecast_images 404s)
OBSERVED = [["https://o/%d.png" % i, NOW - 6000 + i * 300, [1, 2, 3, 4]]
            for i in range(20)]


def drawn_frame(imgs, kind):
    cands, _base = RS._pick_frames(imgs, kind)
    return cands[0]


class MotionUsesTheMapsOwnFrames(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self._kind = RS._kind_for
        self._cache = dict(RS._MO_CACHE)
        RS._MO_CACHE.clear()
        RS._MO_BUSY.discard((1.0, 1.0))
        self._em = EM.echo_motion
        EM.echo_motion = lambda frames, **kw: (self.seen.append(list(frames))
                                               or {"kind": "stationary", "kmh": 0.0})

    def tearDown(self):
        RS._kind_for = self._kind
        RS._MO_CACHE.clear()
        RS._MO_CACHE.update(self._cache)
        EM.echo_motion = self._em

    def test_forecast_sky_is_not_re_fetched_as_observations(self):
        """The extra list request cost one upstream call per sky and made the
        arrow describe pixels nobody was looking at."""
        RS._kind_for = lambda lng, lat: "forecast_images"
        RS._obs_frames = lambda lng, lat: self.fail("must not fetch a second list")
        RS._motion_compute((1.0, 1.0), FORECAST, 98.9, 18.7)
        self.assertEqual(len(self.seen), 1)
        urls = [f[0] for f in self.seen[0]]
        self.assertTrue(all(u.startswith("https://f/") for u in urls),
                        "motion was handed something other than the map list: %r"
                        % urls[:3])

    def test_observation_sky_passes_through_untouched(self):
        RS._kind_for = lambda lng, lat: "images"
        RS._motion_compute((1.0, 1.0), OBSERVED, 72.8, 19.0)
        urls = [f[0] for f in self.seen[0]]
        self.assertTrue(all(u.startswith("https://o/") for u in urls))


class ThePairContainsTheFrameOnScreen(unittest.TestCase):
    """The one that would have caught the real bug."""

    def setUp(self):
        self.fetched = []
        self._load = EM._load_lv

        def recorder(u):
            self.fetched.append(u)
            raise RuntimeError("no network in tests")
        EM._load_lv = recorder

    def tearDown(self):
        EM._load_lv = self._load

    def _run(self, imgs, kind):
        self.fetched = []
        EM.echo_motion([(f[0], float(f[1]), f[2]) for f in imgs])
        return set(self.fetched), drawn_frame(imgs, kind)[0]

    def test_forecast_list(self):
        got, on_screen = self._run(FORECAST, "forecast_images")
        self.assertIn(on_screen, got,
                      "motion correlated %r, the reader is looking at %s"
                      % (sorted(got), on_screen))

    def test_observation_list(self):
        got, on_screen = self._run(OBSERVED, "images")
        self.assertIn(on_screen, got,
                      "motion correlated %r, the reader is looking at %s"
                      % (sorted(got), on_screen))

    def test_the_two_frames_are_an_hour_apart(self):
        got, _ = self._run(FORECAST, "forecast_images")
        ts = sorted(float(f[1]) for f in FORECAST if f[0] in got)
        self.assertEqual(len(ts), 2, "expected exactly two frames, got %d" % len(ts))
        self.assertGreaterEqual(ts[1] - ts[0], 600)


if __name__ == "__main__":
    unittest.main()
