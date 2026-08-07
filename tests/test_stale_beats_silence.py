"""A burst of upstream failure must not evict knowledge we already have.

On 8/7 the radar CDN rotated the hostname onto 45.253.17.x at 11:54 and
103.239.45.x at 11:55; all eight addresses of each timed out on a bare TCP
connect, and recovered by 11:56. Without this rule, one such blink throws away
a motion vector computed four minutes earlier and hands the reader
"undetermined" instead -- strictly less than what we already knew, and shaped
exactly like a sky we never managed to read.

The bound must not move: a surviving entry keeps its ORIGINAL timestamp, so it
still dies at _MO_TTL. This buys freshness for nobody; it only refuses to trade
knowledge for ignorance.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as RS

ANSWER = {"kind": "moving", "arrow": "\u2197", "dir_en": "NE",
          "dir_cn": "\u5411\u4e1c\u5317", "kmh": 9.5, "vx": 8.4, "vy": -4.4}


class StaleBeatsSilence(unittest.TestCase):
    def setUp(self):
        self.key = (99.9, 99.9)
        RS._MO_CACHE.pop(self.key, None)
        RS._MO_BUSY.discard(self.key)

    tearDown = setUp

    def _compute_failure(self):
        # imgs=[] makes echo_motion produce no answer; that is the failure path
        RS._motion_compute(self.key, [])

    def test_a_live_answer_survives_a_failure(self):
        born = time.time() - 240
        RS._MO_CACHE[self.key] = (born, dict(ANSWER))
        self._compute_failure()
        ts, mo = RS._MO_CACHE[self.key]
        self.assertEqual(mo.get("kind"), "moving", "the failure erased what we knew")
        self.assertAlmostEqual(ts, born, delta=1.0,
                               msg="the answer was refreshed; staleness must not be laundered")

    def test_the_bound_does_not_move(self):
        # an answer already past _MO_TTL must not be resurrected by a failure
        born = time.time() - RS._MO_TTL - 30
        RS._MO_CACHE[self.key] = (born, dict(ANSWER))
        self._compute_failure()
        ts, mo = RS._MO_CACHE[self.key]
        self.assertEqual(mo.get("kind"), "undetermined")
        self.assertFalse(RS._mo_fresh((ts, mo)) and mo.get("kind") == "moving")

    def test_a_failure_still_replaces_a_failure(self):
        RS._MO_CACHE[self.key] = (time.time() - 5,
                                  {"kind": "undetermined", "why": "corr"})
        self._compute_failure()
        ts, mo = RS._MO_CACHE[self.key]
        self.assertEqual(mo.get("kind"), "undetermined")
        self.assertLess(time.time() - ts, 2.0, "the new failure must own the entry")

    def test_an_empty_cache_takes_the_failure(self):
        self._compute_failure()
        self.assertEqual(RS._MO_CACHE[self.key][1].get("kind"), "undetermined")

    def test_busy_is_always_cleared(self):
        RS._MO_CACHE[self.key] = (time.time() - 10, dict(ANSWER))
        RS._MO_BUSY.add(self.key)
        self._compute_failure()
        self.assertNotIn(self.key, RS._MO_BUSY,
                         "keeping the previous answer must not leak the busy flag")


if __name__ == "__main__":
    unittest.main(verbosity=2)
