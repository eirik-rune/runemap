"""The fleet check, tested by making it fail on purpose.

Every failure this fleet has had arrives at the reader as an empty grid, which
is what a clear sky looks like. So the only thing that makes this file worth
anything is that each verdict has been fired at least once.
"""
import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import source_health as H      # noqa: E402


def fake(draw, max_age=1800.0):
    m = types.ModuleType("fake_source")
    m.draw = draw
    m.FRAME_MAX_AGE = max_age
    sys.modules["fake_source"] = m
    return m


class EveryVerdictHasBeenFired(unittest.TestCase):

    def _check(self, draw, max_age=1800.0):
        fake(draw, max_age)
        return H.check("probe", "fake_source", (139.69, 35.69), None)[0]

    def test_a_working_source_is_ok(self):
        self.assertEqual(self._check(
            lambda *a, **k: ("art", 12.0, 1.0, None, time.time(), "X")), "OK")

    def test_declining_inside_its_own_coverage_is_no_map(self):
        """The interesting one: from the reader's side this is identical to a
        quiet sky, and only a probe aimed where the source claims coverage can
        tell them apart."""
        self.assertEqual(self._check(lambda *a, **k: None), "NO-MAP")

    def test_an_old_frame_is_stale_not_ok(self):
        self.assertEqual(self._check(
            lambda *a, **k: ("art", 12.0, 1.0, None, time.time() - 9999, "X")),
            "STALE")

    def test_a_raise_is_error_not_a_crash_of_the_run(self):
        def boom(*a, **k):
            raise IOError("upstream gone")
        self.assertEqual(self._check(boom), "ERROR")

    def test_an_impossible_scale_is_error(self):
        """A map can come back fresh and still be wrong: 900 km per column
        means the geometry, not the weather, broke."""
        self.assertEqual(self._check(
            lambda *a, **k: ("art", 900.0, 1.0, None, time.time(), "X")), "ERROR")

    def test_a_missing_module_is_error_not_an_exception(self):
        self.assertEqual(H.check("p", "no_such_module", (0.0, 0.0), None)[0],
                         "ERROR")

    def test_another_service_answering_is_wrong_source_not_ok(self):
        """The dangerous shape: the probe is green about SOMETHING. The
        Toronto probe was answered by NEXRAD -- its rectangle reaches past the
        border and it sorts first -- so Environment Canada had no probe at all
        while this file printed '7 of 7 healthy'."""
        fake(lambda *a, **k: ("art", 12.0, 1.0, None, time.time(), "NWS NEXRAD"))
        self.assertEqual(H.check("probe", "fake_source", (0.0, 0.0), None,
                                 "Environment Canada")[0], "WRONG-SOURCE")

    def test_a_missing_reader_is_not_reported_as_a_missing_map(self):
        """Czechia needs h5py, an optional extra. Without it the adapter
        declines -- and if that printed NO-MAP, the line would accuse an
        upstream that is answering perfectly. Two different failures, two
        different repairs, so two different words."""
        m = fake(lambda *a, **k: None)
        m.unavailable = lambda: "h5py is not installed"
        state, msg = H.check("probe", "fake_source", (0.0, 0.0), None)
        self.assertEqual(state, "NO-READER")
        self.assertIn("h5py", msg)

    def test_an_available_reader_that_declines_is_still_no_map(self):
        """The guard must not swallow the real failure it sits in front of."""
        m = fake(lambda *a, **k: None)
        m.unavailable = lambda: None
        self.assertEqual(H.check("probe", "fake_source", (0.0, 0.0), None)[0],
                         "NO-MAP")

    def test_an_adapter_without_the_hook_is_unchanged(self):
        self.assertEqual(self._check(lambda *a, **k: None), "NO-MAP")

    def test_the_expected_source_matching_is_still_ok(self):
        fake(lambda *a, **k: ("art", 12.0, 1.0, None, time.time(), "FMI"))
        self.assertEqual(H.check("probe", "fake_source", (0.0, 0.0), None,
                                 "FMI")[0], "OK")


class TheLimitComesFromTheSourceNotFromHere(unittest.TestCase):
    """A restated constant drifts, and the drift is silent -- this morning's
    REDEMET ceiling was exactly that."""

    def test_the_adapters_own_limit_wins_over_the_fallback(self):
        m = fake(lambda *a, **k: None, max_age=60.0)
        self.assertEqual(H._max_age(m, 99999), 60.0)

    def test_the_fallback_is_used_only_when_it_declares_none(self):
        m = types.ModuleType("bare")
        self.assertEqual(H._max_age(m, 900), 900.0)


class ItShipsProbesForEveryShippedSource(unittest.TestCase):

    def test_no_source_in_the_chain_is_unwatched(self):
        """A source added without a probe here is a source whose death is
        invisible, which is how all of today's failures behaved."""
        watched = {p[1] for p in H.PROBES}
        for mod in ("radar_jma", "radar_wms", "radar_redemet", "radar_chmi",
                    "radar_knmi"):
            self.assertIn(mod, watched, mod)

    def test_every_wms_service_has_its_own_probe_not_just_the_module(self):
        """Counting modules was the coarse version of this check, and it is
        what let Environment Canada go unwatched: radar_wms was 'covered' four
        times over by probes that all reached the same two services."""
        import radar_wms as W
        named = {p[4] for p in H.PROBES}
        for svc in W.SERVICES:
            self.assertIn(svc["name"], named, svc["key"])
