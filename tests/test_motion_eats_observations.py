"""Motion must be computed from frames that are in the past.

8/7: bob asked "we are not fetching observation images at all any more, are
we?" and he was right. The map draws from forecast_images, a list that begins
at the last observation and runs to +4h. echo_motion called the NEWEST frame
"now", so at chiang mai it correlated +40.7min against +100.7min -- two
predictions drifting apart, sold to the reader as rain that moved.

The fix is one branch in _motion_compute. A branch is deleted by anybody who
tidies the call sites, and nothing else in the suite would notice: the arrow
would still be an arrow and every other test would stay green. That is what
this file is for.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as RS


FORECAST = [["https://f/%d.png" % i, 1000 + i * 300, [1, 2, 3, 4]] for i in range(26)]
OBSERVED = [["https://o/%d.png" % i, 1 + i * 300, [1, 2, 3, 4]] for i in range(20)]


class MotionSource(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self._kind = RS._kind_for
        self._obs = RS._obs_frames
        self._cache = dict(RS._MO_CACHE)
        RS._MO_CACHE.clear()
        RS._MO_BUSY.discard((1.0, 1.0))
        import echo_motion as EM
        self._em = EM.echo_motion
        EM.echo_motion = lambda frames, **kw: (self.seen.append(list(frames))
                                               or {"kind": "stationary", "kmh": 0.0})

    def tearDown(self):
        RS._kind_for = self._kind
        RS._obs_frames = self._obs
        RS._MO_CACHE.clear()
        RS._MO_CACHE.update(self._cache)
        import echo_motion as EM
        EM.echo_motion = self._em

    def test_forecast_sky_swaps_in_the_observation_list(self):
        RS._kind_for = lambda lng, lat: "forecast_images"
        RS._obs_frames = lambda lng, lat: OBSERVED
        RS._motion_compute((1.0, 1.0), FORECAST, 98.9, 18.7)
        self.assertEqual(len(self.seen), 1)
        urls = [f[0] for f in self.seen[0]]
        self.assertTrue(all(u.startswith("https://o/") for u in urls),
                        "motion was handed forecast frames: %r" % urls[:3])

    def test_observation_sky_passes_through_untouched(self):
        # mumbai/sydney: forecast_images 404s, so imgs already IS the obs list
        RS._kind_for = lambda lng, lat: "images"
        RS._obs_frames = lambda lng, lat: self.fail("must not refetch")
        RS._motion_compute((1.0, 1.0), OBSERVED, 72.8, 19.0)
        urls = [f[0] for f in self.seen[0]]
        self.assertTrue(all(u.startswith("https://o/") for u in urls))

    def test_failed_obs_download_reads_as_fetch_not_as_computation(self):
        RS._kind_for = lambda lng, lat: "forecast_images"
        RS._obs_frames = lambda lng, lat: None
        RS._motion_compute((1.0, 1.0), FORECAST, 98.9, 18.7)
        self.assertEqual(self.seen, [], "must not fall back to forecast frames")
        hit = RS._MO_CACHE.get((1.0, 1.0))
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1].get("why"), "fetch")


if __name__ == "__main__":
    unittest.main()
