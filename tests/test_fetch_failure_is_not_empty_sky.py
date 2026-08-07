"""A frame we could not download says nothing about the sky.

bob, 2026-08-07 10:50 UTC, replying to the launch thread with a screenshot of
echorune.net/清迈: the map was full of echo and the line under it read
"回波移动: 无(视野内无回波可追踪)". He was right. Both radar frames had 403'd,
every pair was skipped by `except Exception: continue`, and _echo_seen stayed
False -- so "we could not look" came out wearing the words for "there is
nothing there". render_scene.py's own comment forbids exactly this, one file
away from where it happened.

The test the comment never had.
"""
import os, sys, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import echo_motion as EM


def _frames(n=26, step=300):
    now = time.time()
    return [("http://example.invalid/f%02d.png" % i, now - n * step + i * step,
             [18.0, 98.0, 19.5, 99.5]) for i in range(n)]


class FetchFailureIsNotEmptySky(unittest.TestCase):
    def setUp(self):
        self._lv, self._get = EM._load_lv, getattr(EM, "_get", None)

    def tearDown(self):
        EM._load_lv = self._lv
        if self._get is not None:
            EM._get = self._get

    def test_download_failure_says_fetch_not_noecho(self):
        def boom(u):
            raise IOError("simulated CDN 403")
        EM._load_lv = boom
        EM._get = lambda u, timeout=15: boom(u)
        why = EM.echo_motion(_frames()).get("why")
        self.assertEqual(why, "fetch",
                         "a frame that never arrived was reported as an empty sky (why=%r)" % why)

    def test_genuinely_empty_sky_still_says_noecho(self):
        import numpy as np
        EM._load_lv = lambda u: np.zeros((160, 160), dtype=np.float32)
        self.assertEqual(EM.echo_motion(_frames()).get("why"), "noecho")

    def test_the_two_are_distinguishable(self):
        import numpy as np
        def boom(u):
            raise IOError("simulated CDN 403")
        EM._load_lv = boom
        EM._get = lambda u, timeout=15: boom(u)
        a = EM.echo_motion(_frames()).get("why")
        EM._load_lv = lambda u: np.zeros((160, 160), dtype=np.float32)
        b = EM.echo_motion(_frames()).get("why")
        self.assertNotEqual(a, b, "the reader cannot tell blindness from a clear sky")


if __name__ == "__main__":
    unittest.main()
