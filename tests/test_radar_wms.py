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


class ANearestColourTableMustNotWrapAround(unittest.TestCase):
    """The squared distance between two channels reaches 65025. In int16 that
    wraps negative and the furthest colour silently becomes the nearest --
    measured on DWD magenta, 113 away from anything declared, which came back
    as level 1 for 166 pixels."""

    def _arr(self, rgb):
        import numpy as np
        a = np.zeros((4, 4, 4), dtype=np.uint8)
        a[..., 0], a[..., 1], a[..., 2], a[..., 3] = rgb[0], rgb[1], rgb[2], 255
        return a

    def test_a_far_colour_is_left_unclaimed(self):
        pal = [("#33ffff", 1), ("#019934", 2)]
        lv = W.classify_palette(self._arr((251, 0, 255)), pal)
        self.assertEqual(int(lv.max()), 0, "a colour nobody declared became rain")

    def test_a_declared_colour_lands_on_its_level(self):
        pal = [("#33ffff", 1), ("#019934", 2), ("#fe0000", 5)]
        self.assertEqual(int(W.classify_palette(self._arr((254, 0, 0)), pal).max()), 5)

    def test_quantisation_within_the_cap_still_matches(self):
        pal = [("#cc0098", 5)]
        near = W.classify_palette(self._arr((203, 2, 150)), pal)
        self.assertEqual(int(near.max()), 5)

    def test_transparent_pixels_are_never_rain(self):
        import numpy as np
        a = self._arr((254, 0, 0)); a[..., 3] = 0
        self.assertEqual(int(W.classify_palette(a, [("#fe0000", 5)]).max()), 0)


class FinlandNeedsItsOwnScaleOrItIsOverstated(unittest.TestCase):
    """FMI's colour map ends in pink (#fa51a5 at the top), so the default
    cool-to-warm heuristic reads its scale wrongly in both directions.
    Measured over Oulu on one real frame: default = {2:1182, 3:97, 4:28, 5:27},
    their own scale = {1:576, 2:217, 3:69, 4:24} -- a level too wet everywhere
    and a top class that does not exist. The palette is load-bearing."""

    def _svc(self):
        return next(s for s in W.SERVICES if s["key"] == "fi-fmi")

    def test_finland_is_covered_and_the_neighbours_are_not(self):
        self.assertEqual(W.service_for(24.94, 60.17)["key"], "fi-fmi")   # helsinki
        self.assertEqual(W.service_for(25.47, 65.01)["key"], "fi-fmi")   # oulu
        self.assertIsNone(W.service_for(18.07, 59.33))                   # stockholm
        self.assertIsNone(W.service_for(37.62, 55.75))                   # moscow

    def test_it_ships_a_palette_rather_than_trusting_the_heuristic(self):
        self.assertTrue(self._svc().get("palette"), "no palette: Finland's "
                        "heaviest echo would be drawn as almost nothing")

    def test_its_top_class_is_the_pink_not_the_red(self):
        """The specific inversion this palette exists to prevent."""
        import numpy as np
        pal = self._svc()["palette"]
        a = np.zeros((2, 2, 4), dtype=np.uint8)
        a[..., 0], a[..., 1], a[..., 2], a[..., 3] = 0xFA, 0x51, 0xA5, 255
        self.assertEqual(int(W.classify_palette(a, pal).max()), 5)

    def test_the_declared_levels_only_climb(self):
        levels = [lv for _c, lv in self._svc()["palette"]]
        self.assertEqual(levels, sorted(levels), "a scale that goes back down "
                         "is a transcription error, not a scale")


class TheRampCheckMustBeAbleToSayBothWords(unittest.TestCase):
    """A verdict machine that can only refuse is not judging. This one told me
    Finland was 78% undeclared, when every one of those colours was a point on
    an interpolated ramp between two of their own stops."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
        import wms_palette
        self.P = wms_palette

    def test_a_colour_between_two_stops_is_on_the_ramp(self):
        stops = [W._rgb(h) for h, _ in W._DWD_PALETTE]
        self.assertTrue(self.P.on_ramp((200, 0, 150), stops))

    def test_the_colour_that_stopped_germany_is_still_refused(self):
        stops = [W._rgb(h) for h, _ in W._DWD_PALETTE]
        self.assertFalse(self.P.on_ramp((251, 0, 255), stops),
                         "the ramp check must not become a way to explain "
                         "away a colour nobody declared")


class BothWindowsMustAcceptTheCallersScale(unittest.TestCase):
    """Production sets RUNEMAP_SPAN_KM, so every real request renders through
    ascii_radar_centered() and never through ascii_radar(). The classifier
    argument was missing from that one signature only, which no test could see
    and every Finnish reader could: SECOND-FAILED wms TypeError, and the
    sentence instead of rain."""

    def _png(self, rgb):
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGBA", (64, 64), rgb + (255,)).save(b, "PNG")
        return b.getvalue()

    def _draw_finland(self):
        raw = self._png((250, 81, 165))          # their top class, pink
        return W.draw("><", 24.94, 60.17, small=True, get=lambda u: raw)

    def test_the_centred_window_draws_with_a_palette(self):
        import render_scene as RS
        RS.set_span(200.0)
        try:
            got = self._draw_finland()
        finally:
            RS.set_span(None)
        self.assertIsNotNone(got, "the window production actually uses refused "
                                  "the service's own colour scale")
        self.assertEqual(got[5], "FMI")
        self.assertIn("█", got[0])          # top class, drawn as full block

    def test_the_box_window_draws_with_a_palette_too(self):
        got = self._draw_finland()
        self.assertIsNotNone(got)
        self.assertIn("█", got[0])
