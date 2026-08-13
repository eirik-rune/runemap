"""The value probe, tested by making each verdict happen on purpose.

It exists because two of our services will simply tell us what a pixel means,
and asking beats deriving. What it must never do is answer confidently about a
style that cannot carry an answer.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import value_probe as V      # noqa: E402


class ItReadsTheNumberOutOfEitherShape(unittest.TestCase):

    def test_geoserver_json(self):
        b = b'{"features":[{"properties":{"GRAY_INDEX":97}}]}'
        self.assertEqual(V.parse_value(b, "geoserver"), 97.0)

    def test_adaguc_plain_text_with_units(self):
        b = b"Coordinates - (lon=5.25; lat=52.15)\n    image1.image_data 0.000365 mm/hr\n"
        self.assertAlmostEqual(V.parse_value(b, "adaguc"), 0.000365)

    def test_a_dbz_answer_is_read_too(self):
        self.assertEqual(V.parse_value(b"x 31.5 dBZ", "adaguc"), 31.5)

    def test_an_answer_with_no_number_is_none_not_zero(self):
        """'the server said nothing numeric' and 'the value is zero' are two
        facts, and a calibration built on the second when it was the first is
        built on silence."""
        self.assertIsNone(V.parse_value(b"<html>no data here</html>", "adaguc"))
        self.assertIsNone(V.parse_value(b'{"features":[]}', "geoserver"))

    def test_unparseable_json_is_none_not_a_crash(self):
        self.assertIsNone(V.parse_value(b"<not json>", "geoserver"))


class EveryVerdictHasBeenFired(unittest.TestCase):

    def test_separable_bands_are_ok(self):
        t = {(1, 1, 1): [1.0, 1.1, 1.2], (2, 2, 2): [5.0, 5.1, 5.2],
             (3, 3, 3): [9.0, 9.1, 9.2]}
        self.assertEqual(V.verdict(t)[0], "OK")

    def test_overlapping_bands_are_refused(self):
        """Two colours holding the same values means the picture is not
        carrying the value, and no lookup table exists to be shipped."""
        t = {(1, 1, 1): [1.0, 5.5, 2.0], (2, 2, 2): [5.0, 1.5, 5.2],
             (3, 3, 3): [9.0, 9.1, 9.2]}
        self.assertEqual(V.verdict(t)[0], "REFUSED")

    def test_too_few_colours_is_insufficient_not_refused(self):
        """A dry country returns this. It is a measurement waiting for
        weather, not a statement about the service -- and the two must not
        print the same word."""
        t = {(1, 1, 1): [0.0, 0.0, 0.0]}
        self.assertEqual(V.verdict(t)[0], "INSUFFICIENT")

    def test_a_colour_with_one_sample_does_not_count_as_a_class(self):
        t = {(1, 1, 1): [1.0, 1.1, 1.2], (2, 2, 2): [5.0], (3, 3, 3): [9.0]}
        self.assertEqual(V.verdict(t)[0], "INSUFFICIENT")


class RankAgreementJudgesTheOrderNotTheNumbers(unittest.TestCase):

    KNOWN = [("#000000", 0), ("#404040", 1), ("#808080", 2), ("#c0c0c0", 3)]

    def test_a_matching_order_is_concordant(self):
        t = {(0, 0, 0): [1.0], (64, 64, 64): [2.0], (128, 128, 128): [3.0],
             (192, 192, 192): [4.0]}
        con, dis = V._rank_agreement(t, self.KNOWN)
        self.assertEqual((con, dis), (6, 0))

    def test_a_reversed_order_is_discordant(self):
        t = {(0, 0, 0): [4.0], (64, 64, 64): [3.0], (128, 128, 128): [2.0],
             (192, 192, 192): [1.0]}
        con, dis = V._rank_agreement(t, self.KNOWN)
        self.assertEqual((con, dis), (0, 6))


class AGuardWhoseThresholdGrowsWithTheProblemIsNotAGuard(unittest.TestCase):
    """The first version read `len(by) > max(MAX_CLASSES, len(vis) // 8)`,
    which made the threshold 245 for a window with 1962 visible pixels -- so it
    never fired on the very case it was written for, and the tool spent 60
    requests producing a verdict about my own colour matching."""

    def test_the_ceiling_is_a_constant(self):
        import inspect
        src = inspect.getsource(V.sample)
        self.assertIn("len(by) > MAX_CLASSES", src)
        self.assertNotIn("len(vis) // 8", src)

    def test_the_ceiling_is_smaller_than_any_real_ramp(self):
        """FMI's default style shows 59 distinct colours in one window."""
        self.assertLess(V.MAX_CLASSES, 59)


if __name__ == "__main__":
    unittest.main(verbosity=2)
