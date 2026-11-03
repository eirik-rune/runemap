"""The radar picture: same window as the text map, honest about where there is no radar.

Synthetic frames only -- no network, no Caiyun key. Each test names the
failure it exists for.
"""
import io, math, os, sys, time, unittest

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


class Motion(unittest.TestCase):
    """bob 11-03: the first mock put the eastbound arrow over the place name."""
    DIRS = [(1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1)]

    def marks(self, vx, vy, kmh=50.0):
        from PIL import ImageDraw
        n = math.hypot(vx, vy)
        mo = {"kind": "moving", "vx": vx / n * kmh, "vy": vy / n * kmh, "kmh": kmh, "dir_en": "?"}
        im = Image.new("RGB", (RI.SIZE, RI.SIZE)); d = ImageDraw.Draw(im)
        return RI.draw_motion(d, mo, RI.SIZE, 200)

    def test_name_never_sits_on_a_motion_mark(self):
        f = RI._font(18)
        for vx, vy in self.DIRS:
            segs = self.marks(vx, vy)
            box = RI.place_label(f.getbbox("Shanghai", stroke_width=3), RI.SIZE / 2, 10, segs, RI.SIZE)
            self.assertFalse(RI._hits(box, segs), "label on the marks for %r" % ((vx, vy),))

    def test_upwind_dashes_stay_inside_the_map(self):
        # a fixed radius ran a southbound line into the title bar
        for vx, vy in self.DIRS:
            for kmh in (20.0, 60.0, 150.0):
                line = self.marks(vx, vy, kmh)[0]
                (x, y) = line[1]
                self.assertTrue(20 <= x <= RI.SIZE - 20 and 56 <= y <= RI.SIZE - 106,
                                "dashes end at %r for %r %s" % ((x, y), (vx, vy), kmh))

    def test_nothing_drawn_unless_moving(self):
        from PIL import ImageDraw
        d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        for mo in (None, {"kind": None}, {"kind": "stationary", "vx": 1, "vy": 0, "kmh": 1},
                   {"kind": "undetermined", "why": "sparse"}):
            self.assertEqual(RI.draw_motion(d, mo, RI.SIZE, 200), [], mo)

    def test_the_hit_test_can_fail(self):
        # positive control: a box straddling the arrow must count as a hit.
        # Eastbound echo => the arrow comes in from the WEST of the marker.
        segs = self.marks(1, 0)
        c = RI.SIZE / 2
        self.assertTrue(RI._hits((c - 90, c - 8, c - 20, c + 8), segs))
        self.assertFalse(RI._hits((c + 20, c - 8, c + 90, c + 8), segs))

    def test_the_arrow_points_at_the_asker(self):
        # bob 11-03: an arrow leaving the marker reads as "going away". The
        # only arrowhead must sit next to the marker, on the upwind side.
        from PIL import ImageDraw
        for vx, vy in self.DIRS:
            im = Image.new("RGB", (RI.SIZE, RI.SIZE), (255, 255, 255))
            n = math.hypot(vx, vy)
            RI.draw_motion(ImageDraw.Draw(im), {"kind": "moving", "vx": vx / n * 50,
                           "vy": vy / n * 50, "kmh": 50}, RI.SIZE, 200)
            a = np.asarray(im).astype(int)
            c = RI.SIZE // 2
            ux, uy = vx / n, vy / n
            up = a[int(c - uy * 20), int(c - ux * 20)]     # inside the arrowhead
            down = a[int(c + uy * 40), int(c + ux * 40)]   # where the old arrow was
            self.assertTrue((up < 200).all(), "no arrowhead upwind for %r" % ((vx, vy),))
            self.assertTrue((down > 250).all(), "something drawn downwind for %r" % ((vx, vy),))


class Route(unittest.TestCase):
    def test_places_are_pictures(self):
        for p, want in (("/shanghai.png", ("shanghai", "all")),
                        ("/shanghai/radar.png", ("shanghai", "radar")),
                        ("/121.47,31.23.png", ("121.47,31.23", "all")),
                        ("/%E4%B8%8A%E6%B5%B7/radar.png", ("\u4e0a\u6d77", "radar")),
                        ("/st.petersburg.png", ("st.petersburg", "all"))):
            self.assertEqual(S.png_place(p), want, p)

    def test_asset_fetches_are_not_places(self):
        # The .png requests that already arrive are icons. Each one let into the
        # fuzzy matcher would warm Caiyun frames for some town it matched.
        for p in ("/favicon.png", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
                  "/logo.png", "/static/x.png", "/wp-content/uploads/a.png", "/.png",
                  "/og-image.png", "/images/banner.png", "/radar.png", "/a/b/radar.png",
                  "/icon/radar.png"):
            self.assertIsNone(S.png_place(p), p)


def fake_weather(now=1762182000):
    hours = [{"datetime": "2026-11-03T%02d:00+08:00" % ((23 + i) % 24), "value": 18 + (i % 5)} for i in range(24)]
    hp = [{"datetime": h["datetime"], "value": 0.3 if i < 6 else 0.0, "probability": 80 if i < 6 else 0}
          for i, h in enumerate(hours)]
    sk = [{"datetime": h["datetime"], "value": "LIGHT_RAIN" if i < 6 else "CLOUDY"} for i, h in enumerate(hours)]
    days = ["2026-11-%02dT00:00+08:00" % (3 + k) for k in range(5)]
    return {"server_time": now, "tzshift": 28800, "result": {
        "realtime": {"temperature": 19, "apparent_temperature": 19, "humidity": .67, "skycon": "LIGHT_RAIN",
                     "wind": {"speed": 3, "direction": 100}, "air_quality": {"aqi": {"chn": 55}}},
        "minutely": {"description": "rain stops in an hour", "precipitation_2h": [0.5] * 60 + [0.0] * 60,
                     "probability": [.98, .9, .4, 0]},
        "hourly": {"temperature": hours, "precipitation": hp, "skycon": sk},
        "daily": {"temperature": [{"date": d, "min": 13 + k, "max": 20 + k} for k, d in enumerate(days)],
                  "precipitation": [{"date": d, "probability": 60} for d in days],
                  "skycon": [{"date": d, "value": "CLOUDY"} for d in days],
                  "astro": [{"date": d, "sunrise": {"time": "06:11"}, "sunset": {"time": "17:04"}} for d in days]}}}


class Panorama(unittest.TestCase):
    def test_is_a_long_phone_width_png(self):
        from runemap import panorama as PN
        bb = station_box(LON, LAT, 3)
        body = PN.render(fake_weather(), dict(png=frame(bb, blob=(LON, LAT, 20)), bbox=bb, ts=time.time(),
                                              obs_ts=time.time(), lon=LON, lat=LAT, key="t"),
                         "Shanghai, CN", {"kind": "moving", "vx": 40, "vy": 0, "kmh": 40, "dir_en": "E"}, "x")
        im = Image.open(io.BytesIO(body))
        self.assertEqual(im.format, "PNG")
        self.assertEqual(im.size[0], PN.W)
        self.assertGreater(im.size[1], 2 * im.size[0])

    def test_planned_height_is_what_gets_drawn(self):
        # the canvas is allocated at height() to avoid an oversized canvas and
        # a crop copy; if a block changes and height() does not, this goes red
        from runemap import panorama as PN
        bb = station_box(LON, LAT, 3)
        rd = dict(png=frame(bb), bbox=bb, ts=time.time(), obs_ts=time.time(), lon=LON, lat=LAT, key="h")
        wx = fake_weather()
        for radar, note in ((rd, None), (None, "not yet"), (None, None)):
            PN.render(wx, radar, "X", radar_note=note)
            self.assertEqual(PN._render.last_y, PN.height(wx, radar, note), (radar is None, note))
        wx["result"]["minutely"]["description"] = ""
        PN.render(wx, rd, "X")
        self.assertEqual(PN._render.last_y, PN.height(wx, rd))

    def test_cards_survive_the_palette(self):
        # the first live render lost every card: page grey and card white
        # were merged into one palette entry
        from runemap import panorama as PN
        body = PN.render(fake_weather(), None, "X", radar_note="not yet")
        cols = {c for _, c in Image.open(io.BytesIO(body)).convert("RGB").getcolors(1 << 20)}
        for c in PN.FIXED:
            self.assertIn(c, cols)

    def test_missing_radar_is_said_not_dropped(self):
        # a picture that silently lacks its radar block reads as "no rain"
        from runemap import panorama as PN
        a = PN.render(fake_weather(), None, "X")
        b = PN.render(fake_weather(), None, "X", radar_note="radar frame not fetched yet")
        self.assertGreater(Image.open(io.BytesIO(b)).size[1], Image.open(io.BytesIO(a)).size[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
