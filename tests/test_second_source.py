"""The fallback must be invisible until it is needed, and named when it is used.

Hermetic: no network. What is being pinned here is the wiring and the credit,
not RainViewer -- the geometry has its own tests.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import render_scene as RS      # noqa: E402

WX = {"realtime": {"temperature": 27.0, "skycon": "RAIN", "humidity": 0.9,
                   "wind": {"speed": 10, "direction": 200}, "pressure": 100000,
                   "apparent_temperature": 29.0,
                   "precipitation": {"local": {"intensity": 0.3}},
                   "air_quality": {"aqi": {"chn": 40}}}}
ART = "\n".join(["." * 48] * 24)


def body(rb):
    return RS.build("en", "mumbai", "RAIN", "mumbai", 72.88, 19.08, 6, WX, rb)


class TheCreditFollowsWhoDrewIt(unittest.TestCase):

    def test_a_map_from_the_fallback_names_the_fallback(self):
        rb = (ART, 12.0, 1.0, None, 1.0, "RainViewer")
        b = body(rb)
        self.assertIn("radar-data: RainViewer rainviewer.com", b)

    def test_a_map_from_the_primary_carries_no_second_credit(self):
        """Absence is information here: it says the primary drew this one.

        This is the negative control for the test above -- without it, a build
        that always printed the credit would pass.
        """
        rb = (ART, 12.0, 1.0, None, 1.0)
        self.assertNotIn("radar-data:", body(rb))

    def test_the_credit_does_not_reuse_the_state_token(self):
        """An agent greps ^radar: for the state. A second line starting the
        same way would make the state ambiguous to every parser we have."""
        b = body((ART, 12.0, 1.0, None, 1.0, "RainViewer"))
        starts = [l for l in b.split("\n") if l.startswith("radar:")]
        self.assertEqual(len(starts), 1, starts)

    def test_an_unknown_source_is_still_credited_by_name(self):
        b = body((ART, 12.0, 1.0, None, 1.0, "SomeNewSource"))
        self.assertIn("radar-data: SomeNewSource", b)


class TheFallbackIsOffAndCannotThrowIntoTheReader(unittest.TestCase):

    def setUp(self):
        self._was = RS.SECOND_SOURCE

    def tearDown(self):
        RS.SECOND_SOURCE = self._was

    def test_off_by_default_means_not_consulted(self):
        RS.SECOND_SOURCE = ""
        self.assertIsNone(RS._second_source("><", 72.88, 19.08, False))

    def test_an_unknown_name_is_not_an_exception(self):
        RS.SECOND_SOURCE = "no-such-source"
        self.assertIsNone(RS._second_source("><", 72.88, 19.08, False))

    def test_a_fallback_that_explodes_degrades_to_none(self):
        """A broken fallback must cost the reader the sentence they already
        had, never a 500. Fire-tested by making it explode on purpose."""
        RS.SECOND_SOURCE = "rainviewer"
        import radar_second
        orig = radar_second.draw
        radar_second.draw = lambda *a, **k: (_ for _ in ()).throw(IOError("boom"))
        try:
            self.assertIsNone(RS._second_source("><", 72.88, 19.08, False))
        finally:
            radar_second.draw = orig

    def test_a_fallback_that_works_is_passed_through_unchanged(self):
        RS.SECOND_SOURCE = "rainviewer"
        import radar_second
        orig = radar_second.draw
        want = (ART, 12.0, 1.0, None, 1.0, "RainViewer")
        radar_second.draw = lambda *a, **k: want
        try:
            self.assertEqual(RS._second_source("><", 72.88, 19.08, False), want)
        finally:
            radar_second.draw = orig


class TheSourceRefusesToLieAboutFreshness(unittest.TestCase):

    def test_a_frame_older_than_the_limit_is_refused(self):
        import radar_second as S
        old = {"host": "h", "radar": {"past": [{"time": 1, "path": "/p"}]}}
        was = S._INDEX.copy()
        S._INDEX["at"], S._INDEX["v"] = 9e18, old   # far future: never refresh
        try:
            self.assertEqual(S.newest_frame(), (None, None))
        finally:
            S._INDEX.update(was)



class TheChainTriesInOrderAndFallsThrough(unittest.TestCase):
    """Order encodes a judgement about data: a national radar beats a global
    composite over the country that owns it, and declines everywhere else."""

    def setUp(self):
        self._was = RS.SECOND_SOURCE
        import radar_redemet, radar_second
        self._r, self._s = radar_redemet.draw, radar_second.draw

    def tearDown(self):
        RS.SECOND_SOURCE = self._was
        import radar_redemet, radar_second
        radar_redemet.draw, radar_second.draw = self._r, self._s

    def _stub(self, first, second):
        import radar_redemet, radar_second
        radar_redemet.draw = lambda *a, **k: first
        radar_second.draw = lambda *a, **k: second

    def test_the_first_that_answers_wins(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        a = (ART, 12.0, 1.0, None, 1.0, "REDEMET/DECEA")
        b = (ART, 12.0, 2.0, None, 2.0, "RainViewer")
        self._stub(a, b)
        self.assertEqual(RS._second_source("><", -46.63, -23.55, False)[5],
                         "REDEMET/DECEA")

    def test_a_decline_falls_through_to_the_next(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        b = (ART, 12.0, 2.0, None, 2.0, "RainViewer")
        self._stub(None, b)
        self.assertEqual(RS._second_source("><", 72.88, 19.08, False)[5], "RainViewer")

    def test_one_adapter_exploding_does_not_take_the_chain_with_it(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        b = (ART, 12.0, 2.0, None, 2.0, "RainViewer")
        import radar_redemet, radar_second
        radar_redemet.draw = lambda *a, **k: (_ for _ in ()).throw(IOError("boom"))
        radar_second.draw = lambda *a, **k: b
        self.assertEqual(RS._second_source("><", 72.88, 19.08, False)[5], "RainViewer")

    def test_all_declining_is_none_not_an_empty_map(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        self._stub(None, None)
        self.assertIsNone(RS._second_source("><", 0.0, 0.0, False))

if __name__ == "__main__":
    unittest.main(verbosity=2)
