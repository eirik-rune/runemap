"""The radar picture: same window as the text map, honest about where there is no radar.

Synthetic frames only -- no network, no Caiyun key. Each test names the
failure it exists for.
"""
import io, os, sys, time, unittest

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")
from runemap import radar_image as RI
import serve as S

LON, LAT = 121.47, 31.23          # Shanghai: land, sea and a lake in 200 km


def frame(bbox, size=400, blob=None):
    """Transparent Mercator overlay; optional opaque blob at (lon, lat, radius px)."""
    a = np.zeros((size, size, 4), np.uint8)
    if blob:
        blon, blat, r = blob
        x = (blon - bbox[1]) / (bbox[3] - bbox[1]) * size
        y0, y1 = float(RI.merc_y(bbox[0])), float(RI.merc_y(bbox[2]))
        y = (y1 - float(RI.merc_y(blat))) / (y1 - y0) * size
        yy, xx = np.mgrid[:size, :size]
        m = (xx - x) ** 2 + (yy - y) ** 2 < r * r
        a[m] = (0, 200, 255, 255)
    b = io.BytesIO(); Image.fromarray(a, "RGBA").save(b, "PNG")
    return b.getvalue()


def station_box(lon, lat, half_deg):
    return [lat - half_deg, lon - half_deg, lat + half_deg, lon + half_deg]


class Picture(unittest.TestCase):
    def draw(self, bbox, blob=None, span=200):
        body, frac = RI.render(frame(bbox, blob=blob), bbox, LON, LAT, "Shanghai",
                               time.time(), time.time(), span)
        im = Image.open(io.BytesIO(body)).convert("RGB")
        return np.asarray(im).astype(int), frac

    def test_is_a_png_of_the_promised_size(self):
        px, _ = self.draw(station_box(LON, LAT, 3))
        self.assertEqual(px.shape, (RI.SIZE, RI.SIZE, 3))

    def test_rain_on_the_asker_lands_on_the_marker(self):
        # The window is centred on the asker, not the station: put the station
        # off to one side and the rain on the asker, and it must be drawn at
        # the centre of the picture.
        bb = station_box(LON + 1.0, LAT - 0.8, 3)
        px, _ = self.draw(bb, blob=(LON, LAT - 0.2, 12))
        # South of the marker, clear of its label (which sits to the east).
        # Pixel row from the window's own projection, not an estimate.
        wb = RI.window(LON, LAT, 200)
        y0, y1 = float(RI.merc_y(wb[0])), float(RI.merc_y(wb[2]))
        row = int((y1 - float(RI.merc_y(LAT - 0.2))) / (y1 - y0) * RI.SIZE)
        r, g, b = px[row, RI.SIZE // 2]
        self.assertTrue(b > 200 and r < 120, "no rain where it was put: %r" % ((r, g, b),))

    def test_station_covering_the_window_means_no_hatch(self):
        _, frac = self.draw(station_box(LON, LAT, 3))
        self.assertEqual(frac, 0.0)

    def test_window_past_the_station_is_marked_and_blended(self):
        # The station image ends 0.5 deg east of the asker: everything east of
        # that has no radar. First version pasted the hatch's own alpha into
        # the picture and drew that area as a solid grey slab -- so the check
        # is that the basemap still shows through the hatch, not only that a
        # fraction was reported.
        bb = [LAT - 3, LON - 3, LAT + 3, LON + 0.5]
        px, frac = self.draw(bb)
        self.assertGreater(frac, 0.2)
        east = px[200:600, 760:790].reshape(-1, 3)
        solid = np.all(np.abs(east - (120, 126, 136)) < 6, axis=1).mean()
        self.assertLess(solid, 0.5, "no-radar area is an opaque slab")
        west = px[200:600, 10:40].reshape(-1, 3)
        self.assertFalse(np.array_equal(east.mean(0).round(), west.mean(0).round()))

    def test_no_tile_seam_drawn_as_coast(self):
        # The basemap is cut into 10-degree tiles offline. Drawn naively, the
        # cut at lon 120 / lat 30 shows up as a straight coastline across
        # land. A window straddling both cuts must not have a coast-coloured
        # vertical line at lon 120 on land.
        lon, lat = 120.0, 30.6           # inland, west of Shanghai
        img = RI.basemap(lon, lat, 200)
        a = np.asarray(img).astype(int)
        col = a[100:700, RI.SIZE // 2]
        coast = np.all(np.abs(col - RI.PAL["coast"]) < 8, axis=1).mean()
        self.assertLess(coast, 0.2, "tile edge drawn as coast: %.0f%%" % (coast * 100))

    def test_extrapolated_frame_is_not_called_observed(self):
        t = 1762180000.0
        self.assertIn("observed", RI.when_text(t, t))
        w = RI.when_text(t, t - 1800)
        self.assertNotIn("observed", w)
        self.assertIn("predicted", w)


class Route(unittest.TestCase):
    def test_places_are_images(self):
        for p, want in (("/shanghai.png", "shanghai"), ("/121.47,31.23.png", "121.47,31.23"),
                        ("/%E4%B8%8A%E6%B5%B7.png", "上海"), ("/st.petersburg.png", "st.petersburg")):
            self.assertEqual(S.png_place(p), want, p)

    def test_asset_fetches_are_not_places(self):
        # The .png requests that already arrive are icons. Each one let into the
        # fuzzy matcher would warm Caiyun frames for some town it matched.
        for p in ("/favicon.png", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
                  "/logo.png", "/static/x.png", "/wp-content/uploads/a.png", "/.png",
                  "/og-image.png", "/images/banner.png"):
            self.assertIsNone(S.png_place(p), p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
