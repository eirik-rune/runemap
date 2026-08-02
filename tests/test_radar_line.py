"""The emitted `radar:` line, asserted directly.

The suite ran 18 green tests through two rewrites of this exact line today and
never once looked at it: every assertion was on radar_resolve's tuple, none on
the bytes a stranger reads. A check that cannot fail on the thing you are
changing is decoration. These cases are the two axes, held apart on purpose --
what is drawn, and how old the observation under it is.
"""
import os, sys, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, ".."))
import render_scene as R

WX = {"realtime": {"skycon": "CLOUDY", "temperature": 20.0, "humidity": 0.5,
                   "wind": {"speed": 5.0},
                   "precipitation": {"local": {"intensity": 0.0}}},
      "forecast_keypoint": "no rain",
      "minutely": {"precipitation_2h": [0.0] * 120, "description": "no rain"}}


def radar_line(obs_min, extrap_min, lang="en", state=None, rb_none=False):
    now = time.time()
    base = now - obs_min * 60.0
    ts = base + extrap_min * 60.0
    rb = None if rb_none else ("ART", 10.0, ts, None, base)
    out = R.build(lang, "x", "XX", "x", 0.0, 0.0, 0, WX, rb,
                  radar_state=(state if state is not None else R.STATE_OK))
    hits = [l for l in out.split("\n") if l.startswith("radar: ")]
    assert len(hits) == 1, "expected exactly one radar: line, got %r" % hits
    return hits[0]


class TwoAxes(unittest.TestCase):
    def test_observed_frame_says_obs(self):
        l = radar_line(3, 0)
        self.assertIn("radar: obs", l)
        self.assertNotIn("predict", l)

    def test_extrapolated_frame_says_predict(self):
        l = radar_line(3, 10)
        self.assertIn("radar: predict", l)
        self.assertNotIn("radar: obs", l)

    def test_the_worst_cell_is_reachable(self):
        # An extrapolation drawn on top of a 47-minute-old observation. Under
        # the collapsed one-token scheme this printed plain "radar: predict",
        # which read HEALTHIER than "stale" -- the warning had been demoted to
        # a description. This test exists so that cannot come back silently.
        l = radar_line(47, 10)
        self.assertIn("radar: predict", l)
        self.assertIn("stale", l)
        self.assertIn("47min", l)

    def test_age_threshold_is_printed_not_guessed(self):
        # The boundary belongs in the output, not in a comment: >= 20 is stale.
        self.assertIn("stale", radar_line(R.RADAR_STALE_MIN, 10))
        self.assertIn(" ok", radar_line(R.RADAR_STALE_MIN - 1, 10))

    def test_axes_are_independent(self):
        # All four combinations must be expressible; that is what "orthogonal"
        # means, and enumerating them as one token is what broke it.
        self.assertIn("age: 3min ok", radar_line(3, 0))
        self.assertIn("age: 3min ok", radar_line(3, 10))
        self.assertIn("age: 47min stale", radar_line(47, 0))
        self.assertIn("age: 47min stale", radar_line(47, 10))

    def test_fetching_carries_no_age_placeholder(self):
        # Nothing has been observed, so there is no age. A dash would be a
        # value-shaped nothing: a machine parses it, a human asks what it means.
        # Parsers must key on the token, never on the field count.
        l = radar_line(0, 0, state=R.STATE_FETCHING, rb_none=True)
        self.assertIn("radar: fetching", l)
        self.assertNotIn("age:", l)

    def test_tokens_are_not_translated(self):
        # Readers here are agents. A state you must translate before you can
        # grep it is not a state; the prose after it stays localised.
        for lang in ("en", "zh", "ja"):
            l = radar_line(47, 10, lang=lang)
            self.assertTrue(l.startswith("radar: predict"), (lang, l))
            self.assertIn("stale", l)


if __name__ == "__main__":
    unittest.main()
