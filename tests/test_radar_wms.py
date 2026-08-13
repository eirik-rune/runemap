"""A WMS answers 200 with a valid PNG of the wrong place when you get the axis
order wrong, so that is what these pin. No network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import radar_wms as W      # noqa: E402


class TheAxisOrderIsPerServiceNotAConvention(unittest.TestCase):

    def test_wms_111_puts_longitude_first(self):
        svc = [s for s in W.SERVICES if s["version"] == "1.1.1"][0]
        u = W.url_for(svc, (39.0, -75.0, 41.0, -73.0))
        self.assertIn("bbox=-75.000000%2C39.000000%2C-73.000000%2C41.000000", u)
        self.assertIn("srs=EPSG%3A4326", u)

    def test_wms_130_puts_latitude_first(self):
        svc = [s for s in W.SERVICES if s["version"] == "1.3.0"][0]
        u = W.url_for(svc, (39.0, -75.0, 41.0, -73.0))
        self.assertIn("bbox=39.000000%2C-75.000000%2C41.000000%2C-73.000000", u)
        self.assertIn("crs=EPSG%3A4326", u)

    def test_every_service_declares_which_one_it_is(self):
        """The failure this guards is silent, so no service may default."""
        for s in W.SERVICES:
            self.assertIn(s["axis"], ("xy", "yx"), s["key"])
            self.assertIn(s["crs_param"], ("srs", "crs"), s["key"])
            self.assertTrue(s["attrib"], s["key"])


class CoverageIsDeclaredAndOverlapIsDeliberate(unittest.TestCase):

    def test_a_sky_nobody_declares_gets_nobody(self):
        self.assertIsNone(W.service_for(72.88, 19.08))    # mumbai
        self.assertIsNone(W.service_for(-46.63, -23.55))  # saopaulo

    def test_us_cities_go_to_nexrad(self):
        for lng, lat in [(-74.0, 40.71), (-95.37, 29.76), (-122.33, 47.61)]:
            self.assertEqual(W.service_for(lng, lat)["key"], "us-nexrad")

    def test_toronto_goes_to_nexrad_on_purpose(self):
        """Not a bug: the boxes overlap, NEXRAD's beams do cross the border,
        and the credit names NEXRAD correctly. Flipping the order would hand
        Detroit and Seattle to Canada instead."""
        self.assertEqual(W.service_for(-79.38, 43.65)["key"], "us-nexrad")

    def test_canada_beyond_the_overlap_gets_canada(self):
        for lng, lat in [(-113.49, 53.55), (-63.57, 44.65)]:   # edmonton, halifax
            self.assertEqual(W.service_for(lng, lat)["key"], "ca-geomet")


class ErrorsArriveAsTwoHundredsWithXml(unittest.TestCase):

    def test_non_png_bytes_never_reach_the_renderer(self):
        xml = b'<?xml version="1.0"?><ServiceExceptionReport/>'
        self.assertIsNone(W.draw("><", -74.0, 40.71, get=lambda u: xml))

    def test_empty_body_is_refused_too(self):
        self.assertIsNone(W.draw("><", -74.0, 40.71, get=lambda u: b""))

    def test_a_fetch_that_raises_is_not_an_exception_upward(self):
        def boom(u):
            raise IOError("no route")
        self.assertIsNone(W.draw("><", -74.0, 40.71, get=boom))


if __name__ == "__main__":
    unittest.main(verbosity=2)
