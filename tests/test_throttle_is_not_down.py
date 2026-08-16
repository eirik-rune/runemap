"""Being rate-limited is not being down, and the check must not say so.

KNMI's radar key is shared by every unregistered user, so the adapter backs off
on a 429 several times a day -- 8 times on 2026-08-16, 165 times on record. Each
one arrived at source_health as `NO-MAP`, indistinguishable from a dead Dutch
radar network, exit 1, doorbell. A benign condition that recurs all day and
rings every time does not warn me about anything; it teaches me that the source
alarm is noise, and then the one round that matters rings into a habit of
ignoring it.

So there are three verdicts where there were two:

  THROTTLED        upstream said 429 and we backed off -> exit 2, no bell
  THROTTLED-STUCK  it has said so for THROTTLE_STREAK consecutive rounds
                   (~3 hours) -> exit 1, because a quota that has not refilled
                   in three hours is not a quota problem
  NO-MAP           the adapter declined for any other reason -> exit 1

The escalation is the part worth testing hardest. A quiet verdict with no way
back to loud is not a verdict, it is a mute button, and I would rather find that
out here than by discovering a source has been silently unanswerable for a day.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ops"))


class FakeSource:
    """An adapter that declines, saying why in the adapters' own idiom."""

    def __init__(self, complaint):
        self.complaint = complaint

    def draw(self, *a, **k):
        sys.stderr.write(self.complaint + "\n")
        return None


class ThrottleIsNotDown(unittest.TestCase):
    def setUp(self):
        import builtins
        import source_health
        self.sh = source_health
        self.streaks = tempfile.mktemp(suffix=".json")
        self.sh.STREAK_FILE = self.streaks
        self.mods = {}
        self.real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name in self.mods:
                return self.mods[name]
            return self.real_import(name, *a, **k)

        builtins.__import__ = fake_import
        self.addCleanup(setattr, builtins, "__import__", self.real_import)
        self.addCleanup(lambda: os.path.exists(self.streaks)
                        and os.unlink(self.streaks))

    def verdict(self, complaint):
        self.mods["fake_adapter"] = FakeSource(complaint)
        return self.sh.check("fake-city", "fake_adapter", (4.9, 52.4), None, None)

    def test_a_429_is_throttled_not_no_map(self):
        state, msg = self.verdict("KNMI-RATE-LIMITED listing -- the anonymous "
                                  "key is shared; backing off rather than retrying")
        self.assertEqual(state, "THROTTLED", msg)

    def test_any_other_decline_is_still_no_map(self):
        # The negative half. Without it, a rule broad enough to catch every
        # spelling of "429" could quietly swallow real outages, and the test
        # above would still pass -- a check that can only return one verdict
        # has no jurisdiction.
        for complaint in ("WMS-NO-FRAME upstream returned nothing",
                          "CHMI-FRAME-TOO-OLD 71 min",
                          "nodata share 0.83 over the limit"):
            state, msg = self.verdict(complaint)
            self.assertEqual(state, "NO-MAP", msg)

    def _run_fleet(self, complaint):
        self.mods["fake_adapter"] = FakeSource(complaint)
        self.sh.PROBES[:] = [("fake-city", "fake_adapter", (4.9, 52.4), None, None)]
        self.sh.adopt_unit_env = lambda *a, **k: []
        argv, sys.argv = sys.argv, ["source_health"]
        try:
            with self.assertRaises(SystemExit) as e:
                self.sh.main()
        finally:
            sys.argv = argv
        return e.exception.code

    def test_the_streak_is_a_duration_a_person_would_wait(self):
        """The escalation tests below cannot catch an absurd streak length.

        Found by firing: setting THROTTLE_STREAK to 99999 left every test in
        this file green, because they all derive their expectation from the
        constant -- correct for a retune, blind to a value that means "never
        escalate". It also ran for two minutes doing it, so the runtime of the
        suite scaled with the very number nothing was checking.

        The bound comes from what the number is FOR: cron asks every 20 minutes,
        and a shared quota that has not refilled within a few hours is not a
        quota. One hour is too twitchy to be worth a bell; six hours is long
        enough that a source could be unanswerable most of a working day while
        this file reports 'could not tell' and rings nothing.
        """
        ROUND_MINUTES = 20
        hours = self.sh.THROTTLE_STREAK * ROUND_MINUTES / 60.0
        self.assertGreaterEqual(hours, 1.0, "escalates too eagerly to mean anything")
        self.assertLessEqual(hours, 6.0,
                             "at %.1f hours this is a mute button, not a "
                             "delay -- a source could be unanswerable all day "
                             "and never ring" % hours)

    def test_throttling_exits_2_then_escalates_to_1(self):
        rc = [self._run_fleet("KNMI-RATE-LIMITED listing") for _ in
              range(self.sh.THROTTLE_STREAK)]
        self.assertEqual(rc[:-1], [2] * (self.sh.THROTTLE_STREAK - 1),
                         "a transient throttle must be 'cannot tell', not 'down'")
        self.assertEqual(rc[-1], 1,
                         "after %d consecutive rounds it must escalate; a quiet "
                         "verdict with no way back to loud is a mute button"
                         % self.sh.THROTTLE_STREAK)

    def test_the_streak_resets_so_escalation_means_consecutive(self):
        for _ in range(self.sh.THROTTLE_STREAK - 1):
            self._run_fleet("KNMI-RATE-LIMITED listing")
        self.assertEqual(self._run_fleet("WMS-NO-FRAME nothing"), 1)
        self.assertEqual(json.load(open(self.streaks)), {},
                         "a non-throttled round must clear the count, or "
                         "'9 consecutive' silently means 'the 9th ever'")
        self.assertEqual(self._run_fleet("KNMI-RATE-LIMITED listing"), 2)

    def test_a_subset_run_does_not_reset_other_sources_streaks(self):
        # Debugging one source by name must not quietly disarm the escalation
        # on all the others.
        for _ in range(3):
            self._run_fleet("KNMI-RATE-LIMITED listing")
        before = json.load(open(self.streaks))
        self.mods["fake_adapter"] = FakeSource("WMS-NO-FRAME nothing")
        self.sh.PROBES[:] = [("other-city", "fake_adapter", (0.0, 0.0), None, None)]
        argv, sys.argv = sys.argv, ["source_health", "other"]
        try:
            with self.assertRaises(SystemExit):
                self.sh.main()
        finally:
            sys.argv = argv
        self.assertEqual(json.load(open(self.streaks)), before)


if __name__ == "__main__":
    unittest.main()
