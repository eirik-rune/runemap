"""An empty sky is a measurement, not an undecided instrument.

8/7 13:15-13:29. Five cities polled every 60s: london printed
"echo motion: fetching (retry in ~60s)" on 38 of 39 samples, singapore 37,
shanghai 36. Knocking twice 20s apart showed the compute was fine -- knock 2
always carried an answer. The answer for london was "n/a (no echo to track)",
which _motion_compute normalises to kind="undetermined", which _mo_fresh gave
_MO_FAIL_TTL = 60. Poll at 60s against a 60s lifetime and every look lands on a
just-expired entry: the vector is computed and thrown away each cycle, forever,
while the page promises that coming back will change something.

Chiangmai was the control. Same rhythm, same code, 2 of 39 -- because its
answers are "stationary", which lives _MO_TTL.

"noecho" cost the same download and the same correlation that produced a
"stationary", and it is exactly as true five minutes later. If 600s is the
house's answer for how long a sky-measurement is good, the two cannot be given
different answers on the grounds that one of them is inconvenient. See #32.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as RS


class NoEchoIsKnowledge(unittest.TestCase):
    def test_noecho_outlives_a_failure_of_the_same_age(self):
        # the whole point: identical age, and only one of them is knowledge
        age = RS._MO_FAIL_TTL + 5
        self.assertTrue(age < RS._MO_TTL, "the two TTLs must differ or this proves nothing")
        knowledge = (time.time() - age, {"kind": "undetermined", "why": "noecho"})
        failure = (time.time() - age, {"kind": "undetermined", "why": "fetch"})
        self.assertTrue(RS._mo_fresh(knowledge),
                        "an empty sky was thrown away with a failure's lifetime")
        self.assertFalse(RS._mo_fresh(failure))

    def test_noecho_lives_exactly_as_long_as_a_vector(self):
        # not "longer than a failure" -- as long as the other thing measured
        # from the same two frames, or the asymmetry just moves somewhere else
        age = RS._MO_TTL - 5
        for mo in ({"kind": "undetermined", "why": "noecho"},
                   {"kind": "stationary", "speed": 2.0}):
            self.assertTrue(RS._mo_fresh((time.time() - age, mo)), mo)

    def test_noecho_still_expires(self):
        hit = (time.time() - RS._MO_TTL - 5, {"kind": "undetermined", "why": "noecho"})
        self.assertFalse(RS._mo_fresh(hit),
                         "a sky measured ten minutes ago is not a sky")

    def test_the_other_five_whys_are_still_short_lived(self):
        # the exemption is for one code, not for the word "undetermined"
        age = RS._MO_FAIL_TTL + 5
        for why in ("fetch", "sparse", "corr", "frames", "error"):
            hit = (time.time() - age, {"kind": "undetermined", "why": why})
            self.assertFalse(RS._mo_fresh(hit), why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
