"""A cached failure must expire faster than a cached answer.

8/7 11:46 bob sent a screen full of echo captioned "could not be fetched".
Two minutes later every observation frame for that same sky answered 200. He
was not seeing a live failure; he was seeing the ten-minute corpse of one,
because _motion_compute writes every outcome into _MO_CACHE and both read
sites honoured the same _MO_TTL.

Upstream fails in bursts of seconds. Serving that verdict for ten minutes
turns a blink into an outage, and the reader cannot tell the two apart.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as RS


class FailureIsNotAConclusion(unittest.TestCase):
    def test_a_fresh_failure_is_still_served(self):
        # inside one refresh cycle there is nothing better to say
        hit = (time.time() - 5, {"kind": "undetermined", "why": "fetch"})
        self.assertTrue(RS._mo_fresh(hit))

    def test_a_stale_failure_is_not_served(self):
        # 8/7 14:33. This list used to be typed out here, and it had "sparse" and
        # "corr" in it -- codes that cost the same download and the same
        # correlation as a vector. Shanghai printed "fetching (retry in ~60s)" on
        # 21 of 22 samples with twenty good frames in hand, and this test was one
        # of the two places holding that wrong axis in place. A hand-written list
        # is a second definition; it agrees with the real one only until someone
        # edits one of them. Derive it.
        age = RS._MO_FAIL_TTL + 5
        self.assertTrue(RS._MO_BLIND, "empty set would make this vacuously true")
        for why in sorted(RS._MO_BLIND):
            hit = (time.time() - age, {"kind": "undetermined", "why": why})
            self.assertFalse(RS._mo_fresh(hit), why)

    def test_an_answer_outlives_a_failure(self):
        # the whole point: same age, different lifetimes
        age = RS._MO_FAIL_TTL + 5
        self.assertTrue(age < RS._MO_TTL, "the two TTLs must differ or this proves nothing")
        answer = (time.time() - age, {"kind": "moving", "bearing": 90, "speed": 21})
        failure = (time.time() - age, {"kind": "undetermined", "why": "fetch"})
        self.assertTrue(RS._mo_fresh(answer))
        self.assertFalse(RS._mo_fresh(failure))

    def test_an_answer_still_expires(self):
        hit = (time.time() - RS._MO_TTL - 5, {"kind": "moving", "bearing": 90, "speed": 21})
        self.assertFalse(RS._mo_fresh(hit))

    def test_kind_none_counts_as_a_failure(self):
        # _motion_compute normalises to "undetermined", but a None must never
        # be cached for the full ten minutes if one ever slips through
        hit = (time.time() - RS._MO_FAIL_TTL - 5, {"kind": None})
        self.assertFalse(RS._mo_fresh(hit))

    def test_no_read_site_compares_against_MO_TTL_directly(self):
        # the guard is only real if every reader goes through it
        src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                                "render_scene.py"), encoding="utf-8").read()
        body = src.split("def _mo_fresh(", 1)[1].split("\ndef ", 1)[1]
        # Comments are prose, not comparisons. A guard that cannot tell the two
        # apart pushes the next reader to delete the explanation instead of the
        # bypass -- and the explanation is the only reason this rule survives.
        code = "\n".join(l.split("#", 1)[0] for l in body.split("\n"))
        self.assertNotIn("_MO_TTL", code,
                         "a read site still compares against _MO_TTL instead of _mo_fresh()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
