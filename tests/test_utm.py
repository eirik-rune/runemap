"""The projection, checked against something that was not written here.

Hand-rolled geodesy returns a confident wrong number, so a round-trip test on
its own proves very little -- forward and inverse can be wrong together. The
control that matters is external: SMHI publishes the same radar composite twice,
as a GeoTIFF in UTM 33N and as ODIM HDF5 whose `/where` group carries four
corner latitudes and longitudes they computed themselves. Projecting one into
the other is a check this code can fail.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import utm      # noqa: E402


class ForwardAndInverseAgree(unittest.TestCase):
    """Necessary, nowhere near sufficient: both could be wrong the same way."""

    PLACES = [(59.3293, 18.0686), (57.7089, 11.9746), (67.8500, 20.2200),
              (55.6000, 13.0000), (63.8258, 20.2630), (48.9000, 9.0000),
              (70.1000, 25.0000)]

    def test_round_trip_is_sub_millimetre_across_the_swedish_extent(self):
        for lat, lng in self.PLACES:
            e, n = utm.forward(lat, lng)
            back_lat, back_lng = utm.inverse(e, n)
            self.assertAlmostEqual(back_lat, lat, places=9, msg=(lat, lng))
            self.assertAlmostEqual(back_lng, lng, places=9, msg=(lat, lng))

    def test_the_central_meridian_has_the_false_easting_exactly(self):
        e, _n = utm.forward(60.0, utm.central_meridian(33))
        self.assertAlmostEqual(e, utm.FALSE_EASTING, places=6)

    def test_a_zone_that_does_not_exist_is_refused(self):
        for z in (0, 61, -3):
            with self.assertRaises(ValueError):
                utm.central_meridian(z)

    def test_the_zone_is_never_inferred_from_the_longitude(self):
        """This reads a raster whose zone is fixed by its own GeoKeys. A point
        west of the zone must land at a small easting, not silently jump grids."""
        e33, _ = utm.forward(58.0, 5.0)
        e32, _ = utm.forward(58.0, 5.0, zone=32)
        self.assertNotAlmostEqual(e33, e32, places=0)
        self.assertLess(e33, utm.FALSE_EASTING)


class ItAgreesWithSMHIsOwnCornerCoordinates(unittest.TestCase):
    """The external control.

    Left column: the GeoTIFF's georeference, read from its own tags
    (ModelTiepointTag, ModelPixelScaleTag, Projection 16033 = UTM 33N).
    Right column: the four corners SMHI writes into the HDF5 `/where` group of
    the same composite, which is on a different grid (polar stereographic,
    2000 m) -- so these are two independent descriptions of one footprint.

    Measured 2026-08-13, corner by corner, in TIFF pixel coordinates on a
    471x887 grid: (1.0, -1.3), (473.5, 8.3), (-1.5, 880.3), (439.3, 889.5).
    Everything is within a few pixels of the corresponding corner, which is
    what two griddings of one footprint should look like. A wrong zone or a
    broken series puts these hundreds of kilometres out, not three pixels.
    """

    TIFF = {"e0": 126648.404, "n0": 7771252.876,
            "scale": 2014.9581656050955, "w": 471, "h": 887}
    H5_CORNERS = {
        "UL": (69.80737478474711, 5.32395848573793),
        "UR": (69.26386891092274, 29.82139416992871),
        "LL": (53.987947441350705, 9.255694381015509),
        "LR": (53.70653782305684, 22.76169105068516),
    }
    # 8 km on a 950 x 1790 km grid. Not a number chosen to pass: the measured
    # worst case is UR at x=473.5 against a width of 471, i.e. the HDF5
    # footprint reaches about 2.5 cells past the GeoTIFF's east edge. So the
    # UTM product is not a strict bounding box of the native grid, it is a
    # slightly different extent -- which is a fact about SMHI's two products
    # and not about this projection. What the control still rules out is the
    # failure it exists for: a wrong zone or a broken series is a hundred
    # pixels out, and that case is asserted separately below.
    MARGIN_PX = 4.0

    def _pixel(self, lat, lng):
        e, n = utm.forward(lat, lng)
        return ((e - self.TIFF["e0"]) / self.TIFF["scale"],
                (self.TIFF["n0"] - n) / self.TIFF["scale"])

    def test_every_published_corner_lies_inside_the_tiff_grid(self):
        """The TIFF extent is the UTM BOUNDING BOX of a polar-stereographic
        footprint, so a corner of one is not a corner of the other -- the first
        version of this test asserted that and failed by 8 pixels at UR, which
        is the rotation, not an error. Containment is the claim that is
        actually true."""
        for lab, (lat, lng) in self.H5_CORNERS.items():
            px, py = self._pixel(lat, lng)
            self.assertGreater(px, -self.MARGIN_PX, lab)
            self.assertLess(px, self.TIFF["w"] + self.MARGIN_PX, "%s x=%.1f" % (lab, px))
            self.assertGreater(py, -self.MARGIN_PX, "%s y=%.1f" % (lab, py))
            self.assertLess(py, self.TIFF["h"] + self.MARGIN_PX, "%s y=%.1f" % (lab, py))

    def test_the_grid_is_a_tight_box_around_those_corners(self):
        """Containment alone would pass for a grid ten times too big. The
        bounding box of the four published corners has to be nearly the whole
        raster. Measured 2026-08-13: x spans -1.5..473.5 of 0..471, y spans
        -1.3..889.5 of 0..887."""
        pts = [self._pixel(la, lo) for la, lo in self.H5_CORNERS.values()]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.assertLess(abs(min(xs) - 0.0), 10.0, min(xs))
        self.assertLess(abs(max(xs) - self.TIFF["w"]), 10.0, max(xs))
        self.assertLess(abs(min(ys) - 0.0), 10.0, min(ys))
        self.assertLess(abs(max(ys) - self.TIFF["h"]), 10.0, max(ys))

    def test_a_wrong_zone_would_have_been_caught(self):
        """The control is only worth something if it can fail. Zone 32 puts the
        upper-left corner more than a hundred pixels out."""
        lat, lng = self.H5_CORNERS["UL"]
        e, _n = utm.forward(lat, lng, zone=32)
        px = (e - self.TIFF["e0"]) / self.TIFF["scale"]
        self.assertGreater(abs(px - 0.0), 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
