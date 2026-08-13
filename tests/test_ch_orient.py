"""Every verdict the Swiss orientation check prints, fired on data built to
earn it -- plus the real measurement it was derived from.

Hermetic. A judgement that only ever prints one word has no jurisdiction, and
neither has one whose branches differ by a percent; both failures were met
tonight on this exact question.
"""
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "ops"), os.path.join(_ROOT, "scripts"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ch_orient as O          # noqa: E402

# Gauge readings and the radar rate at each station's own cell, hour ending
# 2026-08-04 18:00 UTC, copied from the measurement in the module docstring.
# Real numbers, so this test fails if the arithmetic ever stops reproducing it.
REAL = [(15.5, 14.714, 0.005), (9.5, 13.300, 0.000), (7.1, 7.867, 1.437),
        (5.7, 9.167, 7.931), (1.4, 3.733, 1.966), (0.8, 2.563, 1.248),
        (0.7, 1.314, 4.418), (0.6, 1.829, 0.000), (0.4, 1.570, 0.006),
        (0.0, 0.05, 0.10), (0.0, 0.00, 0.02), (0.0, 0.12, 0.00),
        (0.0, 0.00, 0.31), (0.0, 0.20, 0.00), (0.0, 0.00, 0.00),
        (0.0, 0.04, 0.09), (0.0, 0.00, 0.00), (0.0, 0.11, 0.02)]


class TheRealHour(unittest.TestCase):

    def test_the_measured_hour_says_the_array_is_read_correctly(self):
        v, note = O.judge(REAL)
        self.assertEqual(v, "OK", note)

    def test_the_same_hour_read_upside_down_is_caught(self):
        """Swapping the two radar columns is exactly what an upside-down read
        would have produced, so this is the failure case in its real form."""
        v, note = O.judge([(g, b, a) for g, a, b in REAL])
        self.assertEqual(v, "FLIPPED", note)


class EveryVerdictCanFire(unittest.TestCase):

    # The wrong column must VARY without tracking the gauge. A constant column
    # is refused by the no-spread guard, so building the fixture that way tests
    # the guard rather than the verdict -- which is how these two first failed.
    NOISE = [2.0, 0.0, 1.0, 3.0, 0.5, 2.5, 0.2, 1.5, 0.8, 2.2]

    def test_ok(self):
        s = [(float(i), float(i), self.NOISE[i]) for i in range(10)]
        v, note = O.judge(s)
        self.assertEqual(v, "OK", note)

    def test_flipped(self):
        s = [(float(i), self.NOISE[i], float(i)) for i in range(10)]
        v, note = O.judge(s)
        self.assertEqual(v, "FLIPPED", note)

    def test_insufficient_when_too_few_stations(self):
        v, note = O.judge([(1.0, 1.0, 0.0)] * 3)
        self.assertEqual(v, "INSUFFICIENT")
        self.assertIn("stations", note)

    def test_insufficient_on_a_dry_hour(self):
        """The trap that hid this all evening: when nothing is raining, the map
        looks the same however it is drawn. It must say so, not guess."""
        v, note = O.judge([(0.0, 0.0, 0.0)] * 12)
        self.assertEqual(v, "INSUFFICIENT")
        self.assertIn("dry hour", note)

    def test_insufficient_when_neither_orientation_wins(self):
        """Ambiguous must not be reported as agreement -- this is the 1% margin
        the blind-mask control offered, in miniature."""
        s = [(float(i), float(i), float(i) * 0.98) for i in range(12)]
        v, note = O.judge(s)
        self.assertEqual(v, "INSUFFICIENT")
        self.assertIn("margin", note)

    def test_a_verdict_of_ok_is_not_reachable_by_a_constant_column(self):
        """A radar column that never varies has no correlation. Returning 0.0
        would read as 'measured, and it disagrees'."""
        v, _ = O.judge([(float(i), 1.0, 1.0) for i in range(12)])
        self.assertEqual(v, "INSUFFICIENT")


class ItIgnoresUnusableRows(unittest.TestCase):

    def test_nan_and_none_rows_are_dropped_not_counted(self):
        nan = float("nan")
        s = REAL + [(nan, 1.0, 0.0), (1.0, None, 0.0), (1.0, 1.0, nan)]
        self.assertEqual(O.judge(s)[0], "OK")

    def test_dropping_them_can_still_reach_insufficient(self):
        nan = float("nan")
        self.assertEqual(O.judge([(nan, nan, nan)] * 20)[0], "INSUFFICIENT")


class TheSampleBuilderSkipsPointsOffTheGrid(unittest.TestCase):

    def test_a_station_outside_the_grid_is_not_invented(self):
        frame = [[1.0, 2.0], [3.0, 4.0]]
        def cell_of(lat, lng):
            return (0, 0) if lat > 0 else None
        s = O.sample_from(frame, lambda rc: frame[1][rc[1]],
                          [(1.0, 1.0, 5.0), (-1.0, 1.0, 5.0)], cell_of)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0], (5.0, 1.0, 3.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
