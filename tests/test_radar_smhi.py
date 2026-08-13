"""Sweden. Hermetic -- the GeoTIFF fixtures are built here, no network.

This is the first source that hands us values instead of colours, so most of
these pin the two places that can quietly turn a number into the wrong picture:
the scale, and the difference between "saw nothing" and "did not look".
"""
import io
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import radar_smhi as S      # noqa: E402


def geotiff(values, e0=126648.404, n0=7771252.876, scale=2014.958,
            proj=16033, units=9001, sy=None):
    """A single-band GeoTIFF with the GeoKeys this adapter insists on."""
    import numpy as np
    from PIL import Image
    a = np.array(values, dtype=np.uint8)
    im = Image.fromarray(a, mode="L")
    gk = [1, 1, 0, 2,
          3074, 0, 1, proj,
          3076, 0, 1, units]
    b = io.BytesIO()
    im.save(b, format="TIFF", tiffinfo={
        33922: (0.0, 0.0, 0.0, e0, n0, 0.0),
        33550: (scale, sy if sy is not None else scale, 0.0),
        34735: tuple(gk)})
    return b.getvalue()


def write(tmpdir, raw, name="f.tif"):
    p = os.path.join(tmpdir, name)
    with open(p, "wb") as fh:
        fh.write(raw)
    return p


class NoDataAndNoRainAreDifferentFacts(unittest.TestCase):
    """The whole fleet's failures reach a reader as an empty grid, which is what
    a clear sky looks like. SMHI states both separately -- undetect=0 is
    "looked, saw nothing", nodata=255 is "did not look here" -- so they must not
    share a return value here either."""

    def test_nodata_is_negative_not_zero(self):
        self.assertEqual(S.level_of(255), -1)

    def test_undetect_is_zero(self):
        self.assertEqual(S.level_of(0), 0)

    def test_a_nodata_cell_counts_as_missing_not_as_clear(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="smhi-")
        raw = geotiff([[255] * 8 for _ in range(8)])
        p = write(d, raw)
        lv, share = S.window(p, 18.07, 59.33, 40.0, 4, 4)
        self.assertEqual(share, 1.0)
        self.assertEqual(int(lv.max()), 0, "nodata must not draw as an intensity")


class TheScaleIsTheirsAndTheBandsAreSharedWithDWD(unittest.TestCase):

    def test_dbz_comes_from_their_gain_and_offset(self):
        for dn, dbz in ((0, -30.0), (100, 10.0), (140, 26.0), (222, 58.8)):
            self.assertAlmostEqual(S.GAIN * dn + S.OFFSET, dbz, places=6)

    def test_the_bands_are_the_same_ones_the_german_row_uses(self):
        """dBZ is physical. One intensity has to draw one character whether the
        radar is German or Swedish; per-source thresholds would make the map's
        scale depend on which country the reader stands in."""
        self.assertEqual([e for e, _ in S.DBZ_LEVELS], [19.0, 28.0, 37.0, 46.0])

    def test_levels_rise_with_reflectivity(self):
        seen = [S.level_of(dn) for dn in range(1, 255)]
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(S.level_of(254), 5)


class TheGeoreferenceIsAssertedNotAssumed(unittest.TestCase):
    """A product that quietly moved to another grid would otherwise be read
    with the old one and answer confidently about the wrong place."""

    def _open(self, **kw):
        from PIL import Image
        return Image.open(io.BytesIO(geotiff([[0, 0], [0, 0]], **kw)))

    def test_the_expected_grid_is_accepted(self):
        e0, n0, scale, w, h = S.georeference(self._open())
        self.assertAlmostEqual(e0, 126648.404, places=3)
        self.assertAlmostEqual(scale, 2014.958, places=3)
        self.assertEqual((w, h), (2, 2))

    def test_another_utm_zone_is_refused(self):
        with self.assertRaises(ValueError):
            S.georeference(self._open(proj=16032))

    def test_units_other_than_metres_are_refused(self):
        with self.assertRaises(ValueError):
            S.georeference(self._open(units=9002))

    def test_non_square_pixels_are_refused(self):
        with self.assertRaises(ValueError):
            S.georeference(self._open(sy=1000.0))

    def test_a_plain_tiff_without_georeference_is_refused(self):
        import numpy as np
        from PIL import Image
        b = io.BytesIO()
        Image.fromarray(np.zeros((2, 2), dtype=np.uint8), mode="L").save(b, format="TIFF")
        with self.assertRaises(ValueError):
            S.georeference(Image.open(io.BytesIO(b.getvalue())))


class CoverageIsTheFootprintAndThePixelsAreTheBoundary(unittest.TestCase):

    def test_sweden_is_covered(self):
        for lng, lat in [(18.07, 59.33), (11.97, 57.71), (20.22, 67.85), (13.0, 55.6)]:
            self.assertTrue(S.covers(lng, lat), (lng, lat))

    def test_finland_is_left_to_fmi(self):
        self.assertFalse(S.covers(24.94, 60.17))

    def test_southern_norway_is_inside_on_purpose(self):
        """Not an oversight: the composite genuinely sees it, the credit says
        SMHI, and the nodata share is what actually decides -- measured over
        Oslo, 48% blind, declined. The first version of this file claimed
        'deliberately only Sweden' while the rectangle contained Oslo."""
        self.assertTrue(S.covers(10.75, 59.91))

    def test_a_mostly_blind_window_is_declined_rather_than_drawn(self):
        self.assertLess(S.MAX_NODATA_SHARE, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
