"""The window is an interval in time, not in alphabetical order.

`ops/who_is_using.py` printed `window: 01/Sep/2026 -> 31/Aug/2026` for weeks:
an interval that ends before it begins. The timestamps were being compared as
strings, so "01/Sep" sorts before "31/Aug". Nothing failed -- every count below
that header was correct, and the period they covered was nonsense. That is the
worse failure, because the header is the denominator and the header is what I
would quote to somebody.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ops"))
import who_is_using as W      # noqa: E402


class TheWindowIsOrderedByTime(unittest.TestCase):

    def test_the_case_that_was_wrong_for_weeks(self):
        aug31 = W._when("31/Aug/2026:23:59:01 +0000")
        sep01 = W._when("01/Sep/2026:00:00:05 +0000")
        self.assertIsNotNone(aug31)
        self.assertLess(aug31, sep01,
                        "31 August sorted after 1 September -- string order")

    def test_years_months_days_and_clock_all_order(self):
        pairs = [("31/Dec/2025:23:59:59 +0000", "01/Jan/2026:00:00:00 +0000"),
                 ("01/Feb/2026:00:00:00 +0000", "01/Mar/2026:00:00:00 +0000"),
                 ("09/Sep/2026:00:00:00 +0000", "10/Sep/2026:00:00:00 +0000"),
                 ("06/Sep/2026:09:00:00 +0000", "06/Sep/2026:10:00:00 +0000")]
        for earlier, later in pairs:
            self.assertLess(W._when(earlier), W._when(later), (earlier, later))

    def test_an_unreadable_timestamp_is_none_not_a_guess(self):
        """None so the caller can COUNT it. Anything else makes a broken line
        the earliest or latest moment in the window and moves the header."""
        for junk in ("", "not a date", "31/Xxx/2026:00:00:00 +0000",
                     "31/Aug/2026", "//::"):
            self.assertIsNone(W._when(junk), junk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
