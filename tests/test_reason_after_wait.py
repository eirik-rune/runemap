# -*- coding: utf-8 -*-
"""A refusal that arrived DURING this request is newer than the file we peeked at.

Why this test exists: on 8/13 05:19-05:25 london/mumbai/saopaulo (all *-ICUWN-*)
went dark together on a UTC-locked schedule, and upstream itself answered
{"status": "failed"} for london at 05:23:17 while chiangmai answered ok with 20
frames. The reader was told "our copy of this sky was too old; fetching a new
one" -- true about our housekeeping, misleading about the world, because
refetching cannot help while upstream is listing no frames.

_RA_FAIL[key] was the only place that fact lived, and it was read at exactly one
place behind a 30s throttle, so the honest sentence was only sayable for 30
seconds. _reason_after_wait() gives it a second reader.

The negative controls matter more than the positive one: this helper must never
invent a reason (why stays None when nothing was observed), and must not let an
OLD refusal speak, or one 30-second-stale memory would silence a sky that has
since come back.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import render_scene as RS


class ReasonAfterWait(unittest.TestCase):
    def test_refusal_during_this_request_wins(self):
        # started at 100, upstream refused at 100.5 -> newer than the peeked file
        self.assertEqual(RS._reason_after_wait("list-toostale", 100.5, 100.0), "sky-empty")

    def test_refusal_exactly_at_start_counts(self):
        self.assertEqual(RS._reason_after_wait("list-toostale", 100.0, 100.0), "sky-empty")

    def test_older_refusal_does_not_speak(self):
        # negative control: the throttle already had its say; a stale refusal must
        # not outrank what we just peeked at
        self.assertEqual(RS._reason_after_wait("list-toostale", 99.0, 100.0), "list-toostale")

    def test_no_refusal_leaves_the_reason_alone(self):
        # negative control: the helper may not invent a reason
        self.assertIsNone(RS._reason_after_wait(None, None, 100.0))
        self.assertEqual(RS._reason_after_wait("list-nofile", None, 100.0), "list-nofile")

    def test_missing_clock_is_not_an_excuse_to_guess(self):
        self.assertEqual(RS._reason_after_wait("list-toostale", 100.5, None), "list-toostale")

    def test_the_word_it_returns_can_reach_a_reader(self):
        # a reason with no sentence is a reason the person never sees: the whole
        # point of PR #40. sky-empty must be in the clause table, in every language.
        for lang in ("en", "zh", "ja"):
            s = RS.fetching_clause("sky-empty", lang)
            self.assertTrue(s, "sky-empty has no %s sentence" % lang)
        # positive control for the ruler: a word nobody defined stays silent
        self.assertEqual(RS.fetching_clause("no-such-reason-xyz", "en"), "")


if __name__ == "__main__":
    unittest.main()
