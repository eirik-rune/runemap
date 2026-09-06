"""The escalation threshold is three hours, not nine of anything.

THROTTLE_STREAK = 9 was arithmetic on a 20-minute round. On 2026-09-06 I gave
KNMI a 6-hour probe interval and did not notice that the same 9 rounds had
become two and a quarter days -- for the one source the threshold was written
for. Nothing would have failed; the constant would just have quietly meant
something else. So the judgement (STUCK_AFTER) is stored, and the number of
rounds is derived per source.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ops"))
import source_health as H      # noqa: E402


class TheLineIsHoursNotRounds(unittest.TestCase):

    def test_every_source_escalates_after_at_least_the_judged_span(self):
        for label in [p[0] for p in H.PROBES]:
            every = H.PROBE_EVERY.get(label) or H.BASE_ROUND
            n = H.streak_line(label)
            self.assertGreaterEqual(
                n * every, H.STUCK_AFTER,
                "%s escalates before the span that was judged" % label)

    def test_it_is_not_later_than_it_needs_to_be(self):
        """The failure my change would have caused: not too eager, too late.
        A source probed every 6h would have waited 54 hours to say a word."""
        for label in [p[0] for p in H.PROBES]:
            every = H.PROBE_EVERY.get(label) or H.BASE_ROUND
            n = H.streak_line(label)
            if n > 2:
                self.assertLess((n - 1) * every, H.STUCK_AFTER,
                                "%s waits longer than the judgement" % label)

    def test_one_round_can_never_establish_a_streak(self):
        self.assertGreaterEqual(H.streak_line("knmi-amsterdam"), 2)
        H.PROBE_EVERY["fake-slow"] = 30 * 24 * 3600
        try:
            self.assertEqual(H.streak_line("fake-slow"), 2)
        finally:
            del H.PROBE_EVERY["fake-slow"]

    def test_the_default_cadence_is_unchanged(self):
        """The published constant still holds for every source without an
        interval -- this change was not licence to retune the fleet."""
        self.assertEqual(H.streak_line("jma-tokyo"), H.THROTTLE_STREAK)
        self.assertEqual(H.streak_line("a-source-added-tomorrow"),
                         H.THROTTLE_STREAK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
