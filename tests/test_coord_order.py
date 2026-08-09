# -*- coding: utf-8 -*-
"""lon,lat is a promise to strangers, so it needs a test that fails when broken.

The whole 92-test suite passed while this convention was being reversed, which
means nothing was holding it. A convention with no test is a sentence in a help
string, and help strings drift away from parsers silently -- that is exactly the
bug this change exists to remove.
"""
import os, sys, unittest
# serve.py exits at import time without a token; copied from
# test_file_probe_checks_every_segment.py rather than invented.
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import serve


class CoordOrder(unittest.TestCase):
    def test_longitude_comes_first(self):
        """Caiyun's order, Dark Sky's order, and the order our own header prints."""
        self.assertEqual(serve._as_coords("100.50,13.75"), (13.75, 100.5))
        self.assertEqual(serve._as_coords("116.39,39.93"), (39.93, 116.39))
        self.assertEqual(serve._as_coords("-74.0,40.7"), (40.7, -74.0))

    def test_no_silent_swap(self):
        """The old rule swapped when abs > 90, which is how '39.93,116.39'
        became Beijing without anyone being told. Refusing is the point: a
        latitude of 116 is not a place, and inventing one hides the mistake."""
        self.assertIsNone(serve._as_coords("39.93,116.39"))
        self.assertIsNone(serve._as_coords("13.75,100.50"))

    def test_a_pair_of_numbers_is_distinguishable_from_a_name(self):
        """The 400 branch needs to know 'numbers in the wrong order' from
        'not coordinates', or the reader gets told their city does not exist."""
        self.assertEqual(serve._numeric_pair("13.75,100.50"), (13.75, 100.5))
        self.assertIsNone(serve._numeric_pair("london"))
        self.assertIsNone(serve._numeric_pair("13.75"))

    def test_help_text_states_the_convention_it_parses(self):
        """A help string that drifts from the parser is worse than no help:
        the reader who obeys it has evidence they did it right."""
        self.assertIn("<lon>,<lat>", serve.HOME)
        self.assertNotIn("<lat>,<lon>", serve.HOME)


if __name__ == "__main__":
    unittest.main()
