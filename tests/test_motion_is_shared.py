"""One answer, one expiry -- and the guard must span two processes.

Measured 8/8: the two workers never computed different vectors. What differed
was WHEN each answer expired. 8788, warmed 06:24:44, fell back to "fetching" at
06:34:57 (613s = _MO_TTL); 8789, warmed 330s later, flipped at 06:40:21 --
predicted to the second before the data existed. Two 600s windows offset by
however far apart the workers were warmed, and nginx hands consecutive readers
to alternating workers: one shows a vector, the other "fetching", forever.

Every other test in this suite runs inside ONE interpreter, where the in-memory
mirror answers every read. Delete the disk write entirely and they all stay
green. So this file writes from a SUBPROCESS and reads here: the only shape that
can tell a shared entry from a private one.
"""
import json
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import render_scene as RS

KEY = (88.8, 88.8)
ANSWER = {"kind": "moving", "kmh": 12.5, "vx": 12.5, "vy": 0.0, "basis": "obs"}


class MotionIsShared(unittest.TestCase):
    def setUp(self):
        RS._MO_CACHE.pop(KEY, None)
        try:
            os.remove(RS._mo_path(KEY))
        except OSError:
            pass

    tearDown = setUp

    def _write_in_another_process(self, ts):
        code = (
            "import sys, time; sys.path.insert(0, %r); import render_scene as RS; "
            "RS._mo_put(%r, %r, ts=%r)" % (SCRIPTS, KEY, ANSWER, ts)
        )
        p = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, "writer process failed: %s" % p.stderr)

    def test_another_process_answer_is_visible_here(self):
        born = time.time() - 60
        self._write_in_another_process(born)
        # nothing in this interpreter's memory has ever heard of KEY
        self.assertNotIn(KEY, RS._MO_CACHE, "the mirror would mask the disk read")
        hit = RS._mo_get(KEY)
        self.assertIsNotNone(hit, "the other worker's answer did not cross over")
        self.assertEqual(hit[1].get("kind"), "moving")

    def test_the_expiry_crosses_over_too(self):
        """Sharing the answer but not its age would keep the alternation alive."""
        born = time.time() - RS._MO_TTL - 30
        self._write_in_another_process(born)
        hit = RS._mo_get(KEY)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[0], born, delta=2.0,
                               msg="the age was reset on read; each worker would expire on its own clock")
        self.assertFalse(RS._mo_fresh(hit), "an answer older than _MO_TTL was served")

    def test_a_corrupt_entry_is_absent_not_an_answer(self):
        os.makedirs(RS._MO_DIR, exist_ok=True)
        with open(RS._mo_path(KEY), "wb") as f:
            f.write(b"{half-written")
        self.assertIsNone(RS._mo_get(KEY), "a truncated file was read as an answer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
