"""A frame that arrived missing part of the network is not a refusal.

2026-08-18 the fleet check said `dmi-copenhagen: declined inside its own
coverage (2.09s) -- DMI-MOSTLY-BLIND 12.57,55.68 31% > 25%`. "Declined inside
its own coverage" points the next hour at licensing or a coverage rectangle.
The truth is the opposite: DMI answered, and a fixed piece of its radar network
was absent from the answer.

I had written this down as possibly the same shape as KNMI's shared quota --
benign, recurring, therefore a bell to silence -- and planned to either give it
THROTTLED's exemption or add a streak threshold. Measuring first killed both
options. Over ~5200 rounds there are two episodes, twelve rounds, and inside
each episode the blind share is constant to the digit: 43% for four rounds,
31% for eight. Weather and noise wander. A value pinned for two and a half
hours is a set of radars missing. And the log shows the bell already rings once
per episode and reports the recovery, which is the shape I wanted -- so the
thing to fix was the word, not the ringing.

Hence: its own verdict, still exit 1. The three empty-handed outcomes now say
which one they are, because that is what decides where the next hour goes:

    THROTTLED       they refused us          (exit 2, no bell)
    SLOW-NO-MAP     we gave up waiting       (exit 1)
    PARTIAL-BLIND   they answered short      (exit 1)
    NO-MAP          they declined, no reason (exit 1)
"""
import os
import sys
import types
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import source_health as S            # noqa: E402


class _Clock:
    """Replaces the clock so `took` is whatever the test wants. A test that
    slept to observe a timeout would be dropped from the suite in a week."""

    def __init__(self, step):
        self.step, self.n = step, 0

    def __call__(self):
        self.n += 1
        return 1000.0 + (self.step if self.n > 1 else 0.0)


def verdict(reason, step=2.09, timeout=12.0):
    """Run one probe against an adapter that declines and says `reason`."""
    mod = types.ModuleType("fake_adapter")
    if timeout is not None:
        mod.TIMEOUT = timeout
    mod.covers = lambda lng, lat: True

    def draw(*a, **k):
        if reason:
            sys.stderr.write(reason + "\n")
        return None

    mod.draw = draw
    sys.modules["fake_adapter"] = mod
    real_time = S.time.time
    S.time.time = _Clock(step)
    try:
        return S.check("fake-city", "fake_adapter", (0.0, 0.0), None)
    finally:
        S.time.time = real_time
        del sys.modules["fake_adapter"]


_BLIND = "DMI-MOSTLY-BLIND 12.57,55.68 31% > 25%"


class ShortDataIsNotARefusal(unittest.TestCase):
    def test_a_blind_window_gets_its_own_verdict(self):
        state, msg = verdict(_BLIND)
        self.assertEqual(state, "PARTIAL-BLIND", msg)
        self.assertIn("part of the network is missing", msg)
        self.assertIn("not refusing us", msg)
        self.assertIn("31%", msg)     # the number that showed it was constant

    def test_without_the_marker_it_is_still_a_plain_refusal(self):
        """The control. If this also came back PARTIAL-BLIND, the verdict would
        be answering to something other than the adapter's own words."""
        state, msg = verdict("")
        self.assertEqual(state, "NO-MAP", msg)
        self.assertIn("declined", msg)

    def test_being_refused_still_wins_over_being_short(self):
        """A rate-limited adapter never got far enough to see the data. If
        blindness swallowed that, KNMI's shared quota would start ringing all
        day -- the exact bell this check refuses to become."""
        state, _ = verdict("KNMI-RATE-LIMITED listing")
        self.assertEqual(state, "THROTTLED")

    def test_a_slow_blind_answer_is_reported_as_blind_not_as_slow(self):
        """Ordering, fired on purpose: an answer that arrived short IS an
        answer, so 'we gave up waiting' would be a false statement about it."""
        state, msg = verdict(_BLIND, step=48.0)
        self.assertEqual(state, "PARTIAL-BLIND", msg)
        self.assertIn("not slow", msg)

    def test_it_counts_as_down_and_not_as_cannot_tell(self):
        """The verdict's whole point is the exit code it drives. Only THROTTLED
        is exempt from the bell; anything else non-OK is counted down, so this
        asserts against the classification main() actually performs."""
        state, _ = verdict(_BLIND)
        self.assertNotEqual(state, "OK")
        self.assertNotEqual(state, "THROTTLED")


if __name__ == "__main__":
    unittest.main()
