"""Upstream being too slow must not be reported as upstream refusing.

2026-08-17. MeteoSwiss went 2.4s -> 30s -> 48s -> 98s, and the fleet check
printed `declined inside its own coverage (48.22s) -- no reason given, which is
itself the bug`. Both states arrive at that line as the same `None`, so the
probe named the wrong mechanism, and the name is what decides where the next
hour goes: a refusal is a question about coverage or licensing, a run of
timeouts is a question about whether upstream is alive and whether our limit is
right. 48.22s was 4 x the adapter's own 12s timeout -- arithmetic no refusal
would ever produce.

The threshold is read off the adapter (`TIMEOUT`) instead of written here, so
retuning the adapter cannot leave this judgement quietly stale. An adapter with
no TIMEOUT keeps the old verdict rather than getting a made-up one.

The clock is replaced rather than waited on: a test that sleeps 48 seconds to
observe a timeout would be dropped from the suite within a week, and a check
nobody runs is a check that does not exist.
"""
import os
import sys
import types
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import source_health as S            # noqa: E402


class _Clock:
    """time.time() that jumps by `step` on its second call, so `took` is
    whatever the test wants without anyone waiting for it."""

    def __init__(self, step):
        self.step, self.n = step, 0

    def __call__(self):
        self.n += 1
        return 1000.0 + (self.step if self.n > 1 else 0.0)


def fake_adapter(timeout=12.0):
    m = types.ModuleType("fake_adapter")
    if timeout is not None:
        m.TIMEOUT = timeout
    m.covers = lambda lng, lat: True
    m.draw = lambda *a, **k: None          # inside coverage, no frame, silent
    return m


def verdict(step, timeout=12.0):
    mod = fake_adapter(timeout)
    real_import, real_time = S.__import__ if hasattr(S, "__import__") else None, S.time.time
    sys.modules["fake_adapter"] = mod
    S.time.time = _Clock(step)
    try:
        return S.check("fake-city", "fake_adapter", (0.0, 0.0), None)
    finally:
        S.time.time = real_time
        del sys.modules["fake_adapter"]


class SlowIsItsOwnVerdict(unittest.TestCase):
    def test_four_timeouts_worth_of_waiting_is_not_a_refusal(self):
        state, msg = verdict(48.22)
        self.assertEqual(state, "SLOW-NO-MAP", msg)
        self.assertIn("not a refusal", msg)
        self.assertIn("4.0x", msg)

    def test_a_quick_empty_answer_is_still_a_refusal(self):
        """The other branch, fired on purpose: a verdict that can only say one
        thing has no jurisdiction, and 'slow' must not swallow 'declined'."""
        state, msg = verdict(0.30)
        self.assertEqual(state, "NO-MAP", msg)
        self.assertIn("declined", msg)

    def test_the_boundary_belongs_to_the_adapter_not_to_this_file(self):
        """Retuning the adapter moves the line, because the line is read off it."""
        slow, _ = verdict(9.0, timeout=4.0)      # 2.25x of 4s
        fast, _ = verdict(9.0, timeout=30.0)     # 0.3x of 30s
        self.assertEqual((slow, fast), ("SLOW-NO-MAP", "NO-MAP"))

    def test_an_adapter_without_a_timeout_gets_the_old_verdict_not_a_guess(self):
        state, msg = verdict(48.22, timeout=None)
        self.assertEqual(state, "NO-MAP", msg)


class TheWordsBeatTheArithmetic(unittest.TestCase):
    """2026-08-19. DWD answered `NO-MAP wms-berlin: declined inside its own
    coverage (7.36s) -- WMS-FAILED de-dwd-wn TimeoutError('The read operation
    timed out')`: a verdict saying "it refused" sitting on evidence saying "we
    stopped waiting". 7.36s is 1.23x the adapter's 6s timeout, not 2x, because
    one inner request hit its own limit and the adapter gave up promptly -- a
    fast failure, not a slow one.

    Counted before changing anything: 15 rounds said `declined` while their own
    reason line said timeout, against 4 that this file's rule caught. Inferring
    the mechanism from elapsed time was wrong three times more often than right,
    and the adapter had said so in words every time.
    """

    def _spoke(self, text, step, timeout=6.0):
        mod = types.ModuleType("fake_adapter")
        if timeout is not None:
            mod.TIMEOUT = timeout
        mod.covers = lambda lng, lat: True

        def draw(*a, **k):
            sys.stderr.write(text + "\n")
            return None

        mod.draw = draw
        sys.modules["fake_adapter"] = mod
        real = S.time.time
        S.time.time = _Clock(step)
        try:
            return S.check("fake-city", "fake_adapter", (0.0, 0.0), None)
        finally:
            S.time.time = real
            del sys.modules["fake_adapter"]

    def test_a_stated_timeout_wins_even_when_it_was_quick(self):
        state, msg = self._spoke(
            "WMS-FAILED de-dwd-wn TimeoutError('The read operation timed out')",
            7.36)
        self.assertEqual(state, "SLOW-NO-MAP", msg)
        self.assertIn("the adapter said so", msg)

    def test_the_arithmetic_still_covers_a_silent_giving_up(self):
        """The control for the branch above: an adapter that times out without
        saying anything is the case the elapsed-time rule was built for, and it
        must still be caught -- otherwise this change trades one blind spot for
        another."""
        state, msg = self._spoke("SOME-OTHER-PROBLEM nothing about waiting", 48.0)
        self.assertEqual(state, "SLOW-NO-MAP", msg)
        self.assertIn("8.0x", msg)

    def test_a_quick_refusal_that_mentions_nothing_is_still_a_refusal(self):
        state, msg = self._spoke("DE-DWD-OUTSIDE-COVERAGE", 0.4)
        self.assertEqual(state, "NO-MAP", msg)


if __name__ == "__main__":
    unittest.main()
