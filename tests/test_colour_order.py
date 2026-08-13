"""The derivation that now decides a shipped palette, so it gets its own tests.

Synthetic rain, not fixtures from the wire: the point is whether the method
recovers an order that IS there and refuses one that is not, and only a
constructed scene lets me know the truth in advance.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import colour_order as CO      # noqa: E402

LIGHT, MID, CORE = (200, 200, 255), (0, 100, 255), (255, 0, 0)


def storm(size=120, radii=(50, 32, 14)):
    """Concentric rings: light outside, core inside -- rain's actual shape."""
    a = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    d = np.hypot(yy - size / 2, xx - size / 2)
    for r, c in zip(radii, (LIGHT, MID, CORE)):
        m = d <= r
        a[m, 0], a[m, 1], a[m, 2], a[m, 3] = c[0], c[1], c[2], 255
    return a


class ItRecoversAnOrderThatIsReallyThere(unittest.TestCase):

    def setUp(self):
        self.imgs = [storm(), storm(radii=(56, 30, 10)), storm(radii=(48, 36, 18))]
        self.stats = CO.sample(self.imgs, min_px=50)

    def test_depth_puts_the_core_last(self):
        self.assertEqual(CO.order(self.stats), [LIGHT, MID, CORE])

    # These scenes are three small rings, so the sample-size floor is stated
    # explicitly rather than inherited from the one tuned for 192 map tiles.
    # Lowering it here is about scene size; it is never lowered to make a real
    # service pass.
    FLOOR = 500

    def test_adjacency_agrees_with_the_true_order(self):
        by = CO.order(self.stats)
        ok, msg = CO.verdict(by, CO.adjacency(self.imgs, by), min_pairs=self.FLOOR)
        self.assertTrue(ok, msg)

    def test_adjacency_refuses_a_shuffled_order(self):
        """The fire test. A check that cannot refuse is not a check."""
        wrong = [MID, LIGHT, CORE]
        ok, msg = CO.verdict(wrong, CO.adjacency(self.imgs, wrong),
                             min_pairs=self.FLOOR)
        self.assertFalse(ok, msg)


class ItSaysICannotTellRatherThanTheyDisagree(unittest.TestCase):
    """Two different failures that must not print the same word: too little
    data, and data that contradicts itself. Measured for real -- the tool
    refused an order it had just confirmed, on a smaller sample."""

    def test_a_tiny_sample_is_insufficient_not_refused(self):
        small = [storm(size=24, radii=(9, 6, 3))]
        by = CO.order(CO.sample(small, min_px=5))
        ok, msg = CO.verdict(by, CO.adjacency(small, by))
        self.assertIsNone(ok)
        self.assertIn("INSUFFICIENT", msg)

    def test_one_class_cannot_be_called_stable(self):
        """Over a dry Netherlands exactly one colour survived the pixel floor,
        and the stability check called that order stable."""
        flat = np.zeros((60, 60, 4), dtype=np.uint8)
        flat[..., 0], flat[..., 3] = 255, 255
        _orders, stable = CO.stability([flat, flat])
        self.assertIsNone(stable)


class DepthIsMeasuredNotAssumed(unittest.TestCase):

    def test_an_edge_pixel_is_shallower_than_a_centre_pixel(self):
        m = np.zeros((40, 40), dtype=bool)
        m[10:30, 10:30] = True
        d = CO.depth_map(m)
        self.assertEqual(int(d[10, 10]), 1)
        self.assertGreater(int(d[20, 20]), int(d[12, 12]))

    def test_outside_the_mask_is_zero(self):
        m = np.zeros((20, 20), dtype=bool)
        m[5:15, 5:15] = True
        self.assertEqual(int(CO.depth_map(m)[0, 0]), 0)


class FragilePairsAreNamedNotHidden(unittest.TestCase):

    def test_two_classes_at_the_same_depth_are_reported(self):
        stats = {LIGHT: (1.0, 900), MID: (5.00, 500), CORE: (5.01, 400)}
        frag = CO.fragile_pairs([LIGHT, MID, CORE], stats)
        self.assertEqual([(f[0], f[1]) for f in frag], [(MID, CORE)])

    def test_a_real_separation_is_not_reported(self):
        stats = {LIGHT: (1.0, 900), MID: (5.0, 500), CORE: (9.0, 400)}
        self.assertEqual(CO.fragile_pairs([LIGHT, MID, CORE], stats), [])
