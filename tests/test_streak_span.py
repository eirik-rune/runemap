"""The escalation verdict reports a span it measured, not one it inferred.

2026-09-07. The morning after KNMI got a 6h probe interval, the verdict read
"6 consecutive rounds, spanning about 30.0h" for a streak that had actually
been running 13.7h: four of its six rounds were taken 20 minutes apart, from
before the interval existed, and the span was computed as (n-1) x the CURRENT
interval.

The number was recomputed on every run, so the guard that checks this file for
frozen numbers passed it. That is the point worth keeping: it was not a stale
number, it was a fresh number derived from a false premise, and provenance is
exactly what that other guard checks. So the start of the streak is recorded
and the span is measured from it.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ops"))
import source_health as H      # noqa: E402


class TheStreakRecordCarriesItsStart(unittest.TestCase):

    def test_the_new_shape_round_trips(self):
        self.assertEqual(H._streak_of({"n": 3, "since": 1788700000.0}),
                         (3, 1788700000.0))

    def test_a_legacy_int_keeps_the_count_and_admits_it_has_no_start(self):
        """The missing half must stay missing. Back-filling it with 'now'
        would make a streak that began yesterday report as minutes old."""
        self.assertEqual(H._streak_of(6), (6, None))

    def test_junk_does_not_crash_and_does_not_invent_a_streak(self):
        for junk in (None, "junk", {"n": "x"}, {}, [], 3.7):
            n, since = H._streak_of(junk)
            self.assertIsInstance(n, int)
            self.assertTrue(since is None or isinstance(since, float), junk)


class TheVerdictSpan(unittest.TestCase):
    """Drive main() with a fake source, as the escalation tests do."""

    def _run(self, streak_value):
        import io
        import json
        import tempfile
        import contextlib
        old = (H.PROBES, H.STREAK_FILE, H.LAST_FILE, H.check, H.adopt_unit_env,
               sys.argv)
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            json.dump({"fleet-source": streak_value}, f)
        fd2, lastpath = tempfile.mkstemp()
        os.close(fd2)
        os.unlink(lastpath)
        try:
            H.STREAK_FILE = path
            H.LAST_FILE = lastpath
            H.PROBES = [("fleet-source", "fake_source", (4.9, 52.4), 900, "X")]
            H.check = lambda *a, **k: ("THROTTLED", "fleet-source: busy")
            H.adopt_unit_env = lambda *a, **k: []
            sys.argv = ["source_health.py"]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit):
                    H.main()
            return out.getvalue()
        finally:
            (H.PROBES, H.STREAK_FILE, H.LAST_FILE, H.check, H.adopt_unit_env,
             sys.argv) = old
            os.unlink(path)
            if os.path.exists(lastpath):
                os.unlink(lastpath)

    def test_it_reports_the_measured_span(self):
        started = time.time() - 5 * 3600          # five hours ago, really
        text = self._run({"n": H.THROTTLE_STREAK, "since": started})
        self.assertIn("THROTTLED-STUCK", text)
        self.assertIn("spanning 5.0h", text)

    def test_a_streak_with_no_recorded_start_says_so_rather_than_guessing(self):
        """A start stamped mid-streak may only be reported as a FLOOR."""
        text = self._run(H.THROTTLE_STREAK)       # legacy bare int
        self.assertIn("THROTTLED-STUCK", text)
        self.assertIn("at least", text)
        self.assertIn("floor", text)
        self.assertNotIn("spanning 0.0h", text)

    def test_the_floor_label_is_sticky(self):
        """A start stamped mid-streak makes every LATER span a floor as well.
        The first version cleared the flag on the next round, so the number
        kept being a floor and stopped saying so."""
        started = time.time() - 4 * 3600
        text = self._run({"n": H.THROTTLE_STREAK, "since": started, "mid": True})
        self.assertIn("at least 4.0h", text)
        self.assertIn("floor", text)

    def test_the_span_does_not_come_from_the_probe_interval(self):
        """The exact bug: with a 6h interval and 6 rounds, the old code said
        30h. The measured span must be what actually elapsed."""
        H.PROBE_EVERY["fleet-source"] = 6 * 3600
        try:
            started = time.time() - 2 * 3600
            text = self._run({"n": 6, "since": started})
            self.assertIn("spanning 2.0h", text)
            self.assertNotIn("30.0h", text)
        finally:
            del H.PROBE_EVERY["fleet-source"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
