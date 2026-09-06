"""A skipped probe is not a verdict about the source.

The change under test slows one probe down (KNMI, whose key is the shared
anonymous key, 216 rounds a day for zero measured Dutch readers). Slowing a
monitor is exactly the kind of change that buys silence by accident, so each
way it could go wrong gets its own case:

  * a skip must not zero the throttle streak -- that would reset the
    escalation of the one source the interval applies to, i.e. the interval
    would silently disable the alarm it was supposed to leave alone
  * a skip must be out of both sides of the healthy ratio -- counted healthy
    is a monitor reporting on a source it never contacted
  * naming the source must always ask, because this file is also the
    single-source diagnostic and that is what I reach for when it misbehaves
  * unknown or unreadable state must ask, not skip: a rate limit that a broken
    file can turn into permanent silence is not a rate limit
"""
import io
import json
import os
import sys
import time
import unittest
import contextlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ops import source_health as sh  # noqa: E402

LABEL = "knmi-amsterdam"
EVERY = sh.PROBE_EVERY[LABEL]


class TestDue(unittest.TestCase):
    def test_never_asked_asks(self):
        self.assertEqual(sh.due(LABEL, {}, now=1000.0)[0], True)

    def test_inside_the_interval_skips(self):
        ask, since = sh.due(LABEL, {LABEL: 1000.0}, now=1000.0 + EVERY - 60)
        self.assertFalse(ask)
        self.assertAlmostEqual(since, EVERY - 60)

    def test_past_the_interval_asks(self):
        ask, _ = sh.due(LABEL, {LABEL: 1000.0}, now=1000.0 + EVERY + 1)
        self.assertTrue(ask)

    def test_named_always_asks(self):
        ask, _ = sh.due(LABEL, {LABEL: 1000.0}, now=1001.0, named=True)
        self.assertTrue(ask, "the diagnostic must not be rate-limited")

    def test_source_without_an_interval_always_asks(self):
        self.assertTrue(sh.due("jma-tokyo", {"jma-tokyo": time.time()})[0])

    def test_unreadable_record_asks(self):
        for junk in (None, {LABEL: "not a number"}, {LABEL: None}):
            self.assertTrue(sh.due(LABEL, junk or {}, now=1000.0)[0], junk)

    def test_clock_going_backwards_asks(self):
        ask, _ = sh.due(LABEL, {LABEL: 9999.0}, now=1000.0)
        self.assertTrue(ask, "a backwards clock must not grant an endless skip")


class TestRun(unittest.TestCase):
    """The loop, with check() replaced -- no network, no shared quota spent."""

    def setUp(self):
        self.tmp = "/tmp/health_iv_%d" % os.getpid()
        os.makedirs(self.tmp, exist_ok=True)
        sh.LAST_FILE = os.path.join(self.tmp, "last.json")
        sh.STREAK_FILE = os.path.join(self.tmp, "streaks.json")
        # Cleared per case, not just per run. Caught by the tests themselves:
        # one case left a fresh timestamp behind and the next one's FIRST run
        # already skipped, so an assertion about a first run was silently
        # measuring a second. Shared state between checks is the same shape as
        # a warmed cache between probes.
        for f in (sh.LAST_FILE, sh.STREAK_FILE):
            if os.path.exists(f):
                os.unlink(f)
        self.asked = []
        self.real_check = sh.check
        self.real_adopt = sh.adopt_unit_env
        sh.adopt_unit_env = lambda *a, **k: []
        sh.check = self.fake_check
        self.addCleanup(self.restore)

    def restore(self):
        sh.check = self.real_check
        sh.adopt_unit_env = self.real_adopt

    def fake_check(self, label, *a, **k):
        self.asked.append(label)
        return "OK", "%s: pretend" % label

    def run_main(self, argv):
        sys.argv = ["source_health.py"] + argv
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                sh.main()
        except SystemExit as e:
            return out.getvalue(), e.code
        raise AssertionError("main() must exit")

    def test_second_run_skips_and_says_so(self):
        text, _ = self.run_main([])
        self.assertIn(LABEL, self.asked)
        self.asked = []
        text, code = self.run_main([])
        self.assertNotIn(LABEL, self.asked, "asked again inside the interval")
        self.assertIn("SKIPPED", text)
        self.assertIn("name it on the command line", text)
        self.assertIn("not asked this round", text)

    def test_skip_is_out_of_the_denominator(self):
        self.run_main([])
        text, _ = self.run_main([])
        n = len(sh.PROBES)
        self.assertIn("-- %d of %d healthy" % (n - 1, n - 1), text)
        self.assertNotIn("of %d healthy" % n, text)

    def test_skip_does_not_zero_the_streak(self):
        sh._streaks({LABEL: 7})
        self.run_main([])          # asks, OK -> streak cleared legitimately
        sh._streaks({LABEL: 7})    # put it back, now inside the interval
        self.run_main([])
        self.assertEqual(sh._streaks().get(LABEL), 7,
                         "a skipped round erased the escalation count")

    def test_naming_it_asks_even_inside_the_interval(self):
        self.run_main([])
        self.asked = []
        self.run_main(["knmi"])
        self.assertEqual(self.asked, [LABEL])

    def test_an_unwritable_record_still_runs_and_complains(self):
        sh.LAST_FILE = "/proc/nonexistent/last.json"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            text, _ = self.run_main([])
        self.assertIn("HEALTH-LAST-UNWRITABLE", err.getvalue())
        self.assertIn(LABEL, self.asked)


if __name__ == "__main__":
    unittest.main(verbosity=2)
