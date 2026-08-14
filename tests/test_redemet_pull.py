"""The publish gate: an empty mirror round must not replace a good index.

2026-08-14. Every radar fetch missed on the Tokyo side, the mirror wrote a
well-formed index with `radars: []` and exited 0, the tar had bytes -- so both
existing guards passed and the empty index went live. Brazil served nothing for
hours while 18 usable frames sat in the destination directory.

The shape is one this repo keeps meeting: a *successful* run that got nothing,
and an empty result overwriting a good one.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import redemet_pull as P      # noqa: E402


class AnEmptyRoundIsRefused(unittest.TestCase):

    def test_the_round_that_blanked_brazil_is_refused(self):
        why = P.why_not_publishable({"listed": 29, "mirrored": 0, "radars": []})
        self.assertIn("REDEMET-MIRROR-EMPTY", why)
        self.assertIn("29", why)

    def test_a_good_round_publishes(self):
        self.assertIsNone(
            P.why_not_publishable({"listed": 29, "mirrored": 18, "radars": [1]}))

    def test_a_partial_round_still_publishes(self):
        """Partial is not empty: 3 of 29 is worse weather cover, not a fault
        this gate should block. Blocking it would freeze the mirror on the
        first bad night."""
        self.assertIsNone(
            P.why_not_publishable({"listed": 29, "mirrored": 3, "radars": [1]}))

    def test_upstream_listing_nothing_gets_its_own_words(self):
        """A different fact from our fetches failing, and it must not print the
        same refusal -- one sends you to REDEMET, the other to our mirror."""
        why = P.why_not_publishable({"listed": 0, "mirrored": 0, "radars": []})
        self.assertIn("NOTHING-LISTED", why)
        self.assertNotIn("MIRROR-EMPTY", why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
