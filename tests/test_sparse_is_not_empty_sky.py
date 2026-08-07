"""Echo too sparse to correlate is not an empty sky either.

8/7 11:16, found while verifying the fetch fix at the user boundary rather than
in a unit test: echorune.net/tokyo/en served a map with 57 echo characters on it
and the line underneath read "= echo motion: n/a (no echo to track)". Both frames
had loaded fine; the newest one covered 0.33% of the pooled grid, under the 1%
gate, so every pair was skipped and _echo_seen stayed False.

The gate answers "can we track it". The sentence answers "is anything there".
Two different questions -- and a reader looking at a screen full of echo can
tell them apart even when we cannot.
"""
import os, sys, time, unittest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import echo_motion as EM


def _frames(n=26, step=300):
    now = time.time()
    return [("http://example.invalid/f%02d.png" % i, now - n * step + i * step,
             [18.0, 98.0, 19.5, 99.5]) for i in range(n)]


def _sparse_grid(frac):
    """A grid whose pooled coverage is below the 1% gate but not zero."""
    a = np.zeros((160, 160), dtype=np.float32)
    n = max(1, int(a.size * frac))
    flat = a.reshape(-1)
    flat[:n] = 2.0
    return a


class SparseIsNotEmptySky(unittest.TestCase):
    def setUp(self):
        self._lv = EM._load_lv

    def tearDown(self):
        EM._load_lv = self._lv

    def test_sparse_echo_says_sparse_not_noecho(self):
        EM._load_lv = lambda u: _sparse_grid(0.002)
        why = EM.echo_motion(_frames()).get("why")
        self.assertEqual(why, "sparse",
                         "echo was on the screen and we called the sky empty (why=%r)" % why)

    def test_truly_empty_sky_still_says_noecho(self):
        EM._load_lv = lambda u: np.zeros((160, 160), dtype=np.float32)
        self.assertEqual(EM.echo_motion(_frames()).get("why"), "noecho")

    def test_the_two_are_distinguishable(self):
        EM._load_lv = lambda u: _sparse_grid(0.002)
        a = EM.echo_motion(_frames()).get("why")
        EM._load_lv = lambda u: np.zeros((160, 160), dtype=np.float32)
        b = EM.echo_motion(_frames()).get("why")
        self.assertNotEqual(a, b, "sparse and empty collapse into one sentence")


if __name__ == "__main__":
    unittest.main()
