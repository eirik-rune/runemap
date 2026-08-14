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

    def test_a_credential_this_user_cannot_read_is_not_a_missing_reader(self):
        """The third absence, and the only one that is a fact about WHO RAN THE
        PROBE. On 8/13 this printed NO-READER and "no KNMI key" for the
        Netherlands while production was serving Amsterdam a 13-minute-old
        frame: the key is 0640 root:root and I am not root. NO-READER sends
        you to pip, NO-MAP sends you to the network, and the cure was to ask
        the service."""
        m = fake(lambda *a, **k: None)
        m.unavailable = lambda: "KNMI key at /etc/runemap/knmi_key is not readable by this user"
        state, msg = H.check("probe", "fake_source", (0.0, 0.0), None)
        self.assertEqual(state, "NO-ACCESS")
        self.assertIn("not readable", msg)

    def test_the_three_absences_print_three_different_words(self):
        """The positive control for the distinction itself: a missing library,
        an unreadable credential and a declining adapter must not collapse."""
        got = []
        for why in ("h5py is not installed",
                    "KNMI key at /x is not readable by this user",
                    None):
            m = fake(lambda *a, **k: None)
            m.unavailable = (lambda w: (lambda: w))(why)
            got.append(H.check("probe", "fake_source", (0.0, 0.0), None)[0])
        self.assertEqual(len(set(got)), 3, got)

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


class ANoMapCarriesTheAdapterOwnReason(unittest.TestCase):
    """NO-MAP was one word for several diseases.

    "Upstream has no frame", "the newest frame is too old" and "the window is
    mostly blind" send you to three different places, and every adapter already
    writes which one it was to stderr. The probe used to discard all of it.
    """

    def _msg(self, draw):
        fake(draw)
        return H.check("probe", "fake_source", (139.69, 35.69), None)[1]

    def test_the_reason_the_adapter_printed_is_in_the_line(self):
        def draw(*a, **k):
            sys.stderr.write("WMS-NO-FRAME newest tried 20260813T2350Z\n")
            return None
        self.assertIn("WMS-NO-FRAME", self._msg(draw))

    def test_the_last_reason_wins_when_the_adapter_is_chatty(self):
        def draw(*a, **k):
            sys.stderr.write("trying slot 1\nCHMI-FRAME-TOO-OLD age=2192s\n")
            return None
        self.assertIn("CHMI-FRAME-TOO-OLD", self._msg(draw))

    def test_a_silent_adapter_is_named_as_silent_not_left_blank(self):
        """'It gave no reason' and 'I did not look for one' must not print the
        same thing -- the absence is itself worth reporting."""
        self.assertIn("no reason given", self._msg(lambda *a, **k: None))

    def test_the_adapter_output_is_re_emitted_not_swallowed(self):
        """Capturing the reason must not steal the log line the adapter wrote:
        the operator log is still its to write."""
        import io as _io
        import contextlib as _c

        def draw(*a, **k):
            sys.stderr.write("WMS-NO-FRAME something\n")
            return None
        fake(draw)
        buf = _io.StringIO()
        with _c.redirect_stderr(buf):
            H.check("probe", "fake_source", (139.69, 35.69), None)
        self.assertIn("WMS-NO-FRAME", buf.getvalue())

    def test_an_adapter_that_raises_still_has_its_output_re_emitted(self):
        import io as _io
        import contextlib as _c

        def draw(*a, **k):
            sys.stderr.write("WMS-PARTIAL got 3 of 9 tiles\n")
            raise ValueError("boom")
        fake(draw)
        buf = _io.StringIO()
        with _c.redirect_stderr(buf):
            verdict, _ = H.check("probe", "fake_source", (139.69, 35.69), None)
        self.assertEqual(verdict, "ERROR")
        self.assertIn("WMS-PARTIAL", buf.getvalue())


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


class ItMeasuresTheConfigurationProductionRuns(unittest.TestCase):
    """8/13: this probe reported NO-READER for the Netherlands -- "no KNMI key"
    -- while production held the key. The service is told where the key is by a
    drop-in; cron told the probe nothing, so it looked in a path that does not
    exist. **The probe was measuring a configuration nobody runs, and the alarm
    it raised was about itself.**

    Worse, it had passed for five hours before that only because a cached frame
    let the adapter answer without a key at all: it was passing for a reason
    other than the one it claimed."""

    def setUp(self):
        self.saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def test_it_takes_the_units_settings(self):
        os.environ.pop("RUNEMAP_KNMI_KEY_FILE", None)
        took = H.adopt_unit_env(run=lambda:
                                "Environment=RUNEMAP_KNMI_KEY_FILE=/etc/runemap/knmi_key "
                                "RUNEMAP_SECOND_SOURCE=knmi\n")
        self.assertIn("RUNEMAP_KNMI_KEY_FILE", took)
        self.assertEqual(os.environ["RUNEMAP_KNMI_KEY_FILE"],
                         "/etc/runemap/knmi_key")

    def test_an_answer_already_given_is_not_overruled(self):
        """A person asking a question on the command line outranks the unit."""
        os.environ["RUNEMAP_SECOND_SOURCE"] = "dmi"
        took = H.adopt_unit_env(run=lambda:
                                "Environment=RUNEMAP_SECOND_SOURCE=knmi\n")
        self.assertEqual(os.environ["RUNEMAP_SECOND_SOURCE"], "dmi")
        self.assertNotIn("RUNEMAP_SECOND_SOURCE", took)

    def test_it_says_so_when_it_cannot_ask(self):
        """"I could not find out" and "there was nothing to find" must not
        print the same thing: the first means every verdict below it is about
        settings production may not use."""
        self.assertIsNone(H.adopt_unit_env(run=lambda: ""))

        def boom():
            raise OSError("systemctl: not found")
        self.assertIsNone(H.adopt_unit_env(run=boom))

    def test_no_settings_to_take_is_not_a_failure(self):
        """A unit with no Environment= line is a real, working state, and it
        must be distinguishable from not being able to ask."""
        self.assertEqual(H.adopt_unit_env(run=lambda: "Environment=\n"), [])
