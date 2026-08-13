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


class PaintedZerosMustNotReadAsRain(unittest.TestCase):
    """DWD fills its radar layers with grey where there is no echo -- over
    Paris that is 100% of the image. Every visible pixel is at least drizzle to
    the renderer, so a painted zero draws rain that is not there and looks
    entirely normal."""

    def _png(self, colour):
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGBA", (8, 8), colour).save(b, "PNG")
        return b.getvalue()

    def test_a_declared_nodata_colour_becomes_transparent(self):
        import numpy as np
        from PIL import Image
        import io as _io
        svc = {"key": "t", "nodata_rgb": [(126, 126, 126)]}
        out = W._strip_nodata(self._png((126, 126, 126, 255)), svc)
        a = np.array(Image.open(_io.BytesIO(out)).convert("RGBA"))
        self.assertEqual(int((a[..., 3] > 50).sum()), 0)

    def test_real_echo_is_left_alone(self):
        import numpy as np
        from PIL import Image
        import io as _io
        svc = {"key": "t", "nodata_rgb": [(126, 126, 126)]}
        out = W._strip_nodata(self._png((0, 200, 0, 255)), svc)
        a = np.array(Image.open(_io.BytesIO(out)).convert("RGBA"))
        self.assertEqual(int((a[..., 3] > 50).sum()), 64)

    def test_a_service_that_forgot_to_declare_is_an_error_not_a_default(self):
        with self.assertRaises(KeyError):
            W._strip_nodata(self._png((1, 2, 3, 255)), {"key": "t"})

    def test_every_shipped_service_has_declared(self):
        for s in W.SERVICES:
            self.assertIsNotNone(s.get("nodata_rgb"), s["key"])
