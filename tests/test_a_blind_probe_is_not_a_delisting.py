"""A directory I cannot read is not a directory that dropped us.

listing_watch.sh has promised since 2026-08-16 that a move into NO-SIGNAL or
UNREACHABLE is logged and never rung -- "ringing for those trains me to ignore
the bell". The code never implemented it: the bell compared the set of
directories whose verdict was LISTED, so sliding from LISTED into any
can't-tell verdict left that set and read as a delisting.

Measured before the change, over the whole log: 12 rings, 11 of them six
drop/return pairs one day apart. One drop said, in the probe's own words,
`NO-CONTROL ours=38, control HTTP 503` -- it had found us thirty-eight times.

Every verdict this module can return is fired here, including the two that
decide nothing, because a judgement that only ever prints one word has no
jurisdiction.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "ops"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import listing_decide as L          # noqa: E402


class WhatRings(unittest.TestCase):

    def test_a_real_delisting_rings(self):
        ring, held, unk = L.decide({"d": "LISTED"}, {"d": "ABSENT"})
        self.assertEqual([("d", "LISTED", "ABSENT")], ring)
        self.assertEqual([], held)

    def test_a_real_listing_rings(self):
        ring, _, _ = L.decide({"d": "ABSENT"}, {"d": "LISTED"})
        self.assertEqual([("d", "ABSENT", "LISTED")], ring)

    def test_nothing_moving_is_silent(self):
        ring, held, _ = L.decide({"d": "LISTED"}, {"d": "LISTED"})
        self.assertEqual(([], []), (ring, held))


class WhatMustNotRing(unittest.TestCase):
    """The eleven. Each of these rang before 2026-11-03."""

    def test_losing_the_positive_control_is_not_a_delisting(self):
        """`NO-CONTROL ours=38, control HTTP 503`: it found us thirty-eight
        times and the old criterion called it a delisting."""
        ring, held, _ = L.decide({"d": "LISTED"}, {"d": "NO-CONTROL"})
        self.assertEqual([], ring)
        self.assertEqual([("d", "LISTED", "NO-CONTROL")], held)

    def test_a_page_that_echoes_the_query_is_not_a_delisting(self):
        ring, held, _ = L.decide({"d": "LISTED"}, {"d": "NO-SIGNAL"})
        self.assertEqual([], ring)
        self.assertTrue(held)

    def test_a_blind_page_is_not_a_delisting(self):
        ring, _, _ = L.decide({"d": "LISTED"}, {"d": "BLIND"})
        self.assertEqual([], ring)

    def test_unreachable_is_not_a_delisting(self):
        ring, _, _ = L.decide({"d": "LISTED"}, {"d": "UNREACHABLE"})
        self.assertEqual([], ring)

    def test_recovering_from_blindness_is_not_a_new_listing(self):
        """The hopeful direction, and the one that cost a false claim on
        2026-10-02: I cannot tell "they added us" from "yesterday I was
        blind", so this is logged and not rung either."""
        ring, held, _ = L.decide({"d": "NO-SIGNAL"}, {"d": "LISTED"})
        self.assertEqual([], ring)
        self.assertEqual([("d", "NO-SIGNAL", "LISTED")], held)

    def test_a_directory_added_to_the_list_does_not_ring(self):
        ring, held, _ = L.decide({}, {"d": "LISTED"})
        self.assertEqual([], ring)
        self.assertTrue(held)

    def test_a_directory_no_longer_asked_does_not_ring(self):
        ring, held, _ = L.decide({"d": "LISTED"}, {})
        self.assertEqual([], ring)
        self.assertTrue(held)


class AWordIHaveNeverSeen(unittest.TestCase):

    def test_it_counts_as_cannot_tell_but_is_named_out_loud(self):
        """Silence is acceptable; silence nobody can explain is not."""
        ring, held, unk = L.decide({"d": "LISTED"}, {"d": "PARTIAL-NEW"})
        self.assertEqual([], ring)
        self.assertTrue(held)
        self.assertEqual(["PARTIAL-NEW"], unk)

    def test_a_known_cannot_tell_word_is_not_reported_as_unknown(self):
        _, _, unk = L.decide({"d": "LISTED"}, {"d": "BLIND"})
        self.assertEqual([], unk)


class TheExitCode(unittest.TestCase):
    """The shell keys on it, so it is part of the interface."""

    def rc(self, *argv):
        """main() prints the lines the shell logs; swallow them so a passing
        suite stays readable, but still run the real entry point."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            return L.main(["x"] + list(argv))

    def test_one_means_go_and_look(self):
        self.assertEqual(1, self.rc("d=LISTED", "d=ABSENT"))

    def test_zero_means_nothing_i_can_act_on(self):
        self.assertEqual(0, self.rc("d=LISTED", "d=NO-CONTROL"))

    def test_an_empty_baseline_cannot_ring(self):
        """The first run has nothing to compare; the shell guards this too,
        and a self-announcing baseline would ring on every new machine."""
        self.assertEqual(0, self.rc("", "d=LISTED"))


class TheParser(unittest.TestCase):

    def test_it_reads_the_shape_the_shell_hands_it(self):
        self.assertEqual({"a": "LISTED", "b": "NO-SIGNAL"},
                         L.parse("a=LISTED b=NO-SIGNAL"))

    def test_rubbish_tokens_are_dropped_not_guessed(self):
        self.assertEqual({"a": "LISTED"}, L.parse("a=LISTED nonsense ="))


if __name__ == "__main__":
    unittest.main()
