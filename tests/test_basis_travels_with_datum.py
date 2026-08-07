"""The basis label must follow the number, not the map it was drawn beside.

8/7: minutes after motion was taught to eat observation frames, chiang mai
printed "= 回波准静止 (<5km/h, 上游预报)". The number under that label had just
been measured from two OBSERVED frames. The label was re-derived at render time
from the kind of list the MAP came from -- forecast_images nearly everywhere --
so the sentence attributed the number to a source it did not come from. Same
family as the bug bob reported that morning: a sentence speaking for something
it does not know.

The fix is a stamp (mo['basis']='obs') plus one read at the render site. Both
halves are one line each, and either one is deletable by somebody tidying up,
with every other test staying green. Hence this file. It goes through
R.build(), the function the server actually calls -- an offline re-derivation
of the same expression would only prove the expression equals itself.
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import render_scene as R

WX = {"realtime": {"skycon": "CLOUDY", "temperature": 20.0, "humidity": 0.5,
                   "wind": {"speed": 5.0},
                   "precipitation": {"local": {"intensity": 0.0}}},
      "forecast_keypoint": "no rain",
      "minutely": {"precipitation_2h": [0.0] * 120, "description": "no rain"}}

ART = "\n".join(["." * 48 for _ in range(24)])
FORECAST_WORDS = ("upstream forecast", "\u4e0a\u6e38\u9884\u62a5", "\u4e0a\u6d41\u4e88\u5831")
OBS_WORDS = ("1h obs", "\u8fd11h\u5b9e\u6d4b", "\u76f4\u8fd11h\u5b9f\u6e2c")


class BasisFollowsTheDatum(unittest.TestCase):
    def setUp(self):
        self._kind = R._kind_for
        self.addCleanup(setattr, R, "_kind_for", self._kind)

    def _lines(self, map_kind, mo, lang="zh"):
        R._kind_for = lambda lng, lat, _k=map_kind: _k
        now = time.time()
        rb = (ART, 6.0, now, mo, now)
        out = R.build(lang, "x", "><", "x", 0.0, 0.0, 0, WX, rb,
                      radar_state=R.STATE_OK)
        return [l for l in out.split("\n")
                if any(w in l for w in FORECAST_WORDS + OBS_WORDS)]

    def test_stamped_obs_over_a_forecast_map_says_obs(self):
        mo = {"kind": "stationary", "kmh": 0.0, "basis": "obs"}
        got = self._lines("forecast_images", mo)
        self.assertEqual(len(got), 1, got)
        self.assertTrue(any(w in got[0] for w in OBS_WORDS),
                        "measured from observed frames, labelled: %r" % got[0])
        self.assertFalse(any(w in got[0] for w in FORECAST_WORDS), got[0])

    def test_unstamped_over_a_forecast_map_still_says_forecast(self):
        # older cache entries carry no stamp; they must not be promoted
        mo = {"kind": "stationary", "kmh": 0.0}
        got = self._lines("forecast_images", mo)
        self.assertEqual(len(got), 1, got)
        self.assertTrue(any(w in got[0] for w in FORECAST_WORDS), got[0])

    def test_observation_map_says_obs_without_any_stamp(self):
        mo = {"kind": "stationary", "kmh": 0.0}
        got = self._lines("images", mo)
        self.assertEqual(len(got), 1, got)
        self.assertTrue(any(w in got[0] for w in OBS_WORDS), got[0])

    def test_moving_line_in_english_carries_the_stamp_too(self):
        mo = {"kind": "moving", "kmh": 22.0, "arrow": "\u2192",
              "dir_en": "east", "dir_cn": "\u4e1c", "basis": "obs"}
        got = self._lines("forecast_images", mo, lang="en")
        self.assertEqual(len(got), 1, got)
        self.assertIn("1h obs", got[0])


class TheStampIsActuallyApplied(unittest.TestCase):
    """The reader above is only half the fix; this is the other half.

    Ignition caught this file passing with the stamp deleted, because every
    test up there hands build() a mo dict it wrote itself. A guard that never
    runs the code it guards is decoration.
    """

    def setUp(self):
        self._kind = R._kind_for
        self._obs = R._obs_frames
        self._cache = dict(R._MO_CACHE)
        R._MO_CACHE.clear()
        R._MO_BUSY.discard((2.0, 2.0))
        import echo_motion as EM
        self._em = EM.echo_motion
        EM.echo_motion = lambda frames, **kw: {"kind": "stationary", "kmh": 0.0}

        def restore():
            R._kind_for = self._kind
            R._obs_frames = self._obs
            R._MO_CACHE.clear()
            R._MO_CACHE.update(self._cache)
            EM.echo_motion = self._em
        self.addCleanup(restore)

    def test_motion_compute_stamps_the_basis_it_measured_from(self):
        obs = [["https://o/%d.png" % i, 1 + i * 300, [1, 2, 3, 4]] for i in range(20)]
        R._kind_for = lambda lng, lat: "forecast_images"
        R._obs_frames = lambda lng, lat: obs
        R._motion_compute((2.0, 2.0), obs, 98.9, 18.7)
        hit = R._MO_CACHE.get((2.0, 2.0))
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1].get("basis"), "obs",
                         "measured from observations and did not say so: %r" % (hit[1],))


if __name__ == "__main__":
    unittest.main()
