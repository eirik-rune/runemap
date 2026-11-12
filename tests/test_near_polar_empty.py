"""Three things a reader was told that were not so (Qianlu, 2026-11-12 09:31).

1. A coordinate came back titled with the nearest settlement as if it were the
   place: Shenzhen town in Gaozhou (111.10,22.17) read "Shenzhen, CN", which a
   reader takes for the city 300 km east. It is now "near" that settlement.
2. Where upstream's frame list for a sky was empty (McMurdo, Suva), the picture
   and the MCP image line said "ask again in ~30s"; asking again 35 s later got
   the same. They now say what upstream answered, and when. Still no claim
   about coverage: that verdict was deleted on 2026-08-03 and stays deleted.
3. In polar day Caiyun prints sunrise 16:52, sunset 16:52. Polar day and polar
   night are now said as such, computed from the date and the latitude.

The handler is driven through do_GET with the two picture routes stubbed, so
the test reads the label the real request path builds. No server, no network,
no gazetteer file.
"""
import datetime
import io
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")
import serve  # noqa: E402
import render_scene as R  # noqa: E402
from runemap import panorama as PN  # noqa: E402
from runemap import words as W  # noqa: E402

NEAREST = {"label": "Shenzhen, Maoming Shi, Guangdong, CN", "lat": 22.18, "lon": 111.09,
           "tz": "Asia/Shanghai", "dist_km": 1.6}
CITY = {"label": "Shenzhen, Guangdong, CN", "lat": 22.54, "lon": 114.06, "tz": "Asia/Shanghai"}


def handler(path, headers=None):
    h = serve.H.__new__(serve.H)
    h.path = path
    h.headers = headers or {"Host": "echorune.net"}
    h.client_address = ("203.0.113.9", 0)
    h.wfile = io.BytesIO()
    h.seen = []
    h._send_png = lambda lon, lat, label, span: h.seen.append(("radar", label))
    h._send_panorama = lambda lon, lat, label, *a, **k: h.seen.append(("all", label))
    h._send = lambda code, body, **k: h.seen.append((code, body))
    return h


class Stubs(unittest.TestCase):
    def setUp(self):
        for name, val in (("rlookup", lambda lat, lon, radius_km=60, lang=None: dict(NEAREST)),
                          ("lookup", lambda q, lang=None: dict(CITY)),
                          ("tz_offset", lambda tz: 8.0)):
            self.addCleanup(setattr, serve.G, name, getattr(serve.G, name))
            setattr(serve.G, name, val)


class ACoordinateIsAnsweredAsNearASettlement(Stubs):

    def label(self, path, headers=None):
        h = handler(path, headers)
        h.do_GET()
        self.assertEqual(len(h.seen), 1, h.seen)
        return h.seen[0][1]

    def test_the_reported_case_in_each_language(self):
        self.assertEqual(self.label("/111.10,22.17/radar.png"),
                         "near Shenzhen, Maoming Shi, Guangdong, CN")
        self.assertEqual(self.label("/111.10,22.17/zh.png"),
                         "Shenzhen附近, Maoming Shi, Guangdong, CN")
        self.assertEqual(self.label("/111.10,22.17/ja.png"),
                         "Shenzhen付近, Maoming Shi, Guangdong, CN")

    def test_a_label_without_commas(self):
        self.assertEqual(serve.near_label("深镇", "zh"), "深镇附近")

    def test_a_named_place_is_still_the_place(self):
        self.assertEqual(self.label("/shenzhen/radar.png"), CITY["label"])

    def test_an_explicit_label_wins(self):
        self.assertEqual(self.label("/111.10,22.17.png?label=Gaozhou"), "Gaozhou")

    def text_label(self, path):
        """The label the text route hands on, with weather stubbed to 'not
        ready': build_fetching is then the first thing to receive it."""
        got = []
        for name, val in (("weather", lambda *a, **k: None),
                          ("weather_start", lambda *a, **k: None),
                          ("radar_resolve", lambda *a, **k: (R.STATE_FETCHING, None)),
                          ("build_fetching", lambda lang, label: got.append(label) or "x")):
            self.addCleanup(setattr, R, name, getattr(R, name))
            setattr(R, name, val)
        h = handler(path)
        h.do_GET()
        self.assertEqual(len(got), 1, h.seen)
        return got[0]

    def test_the_text_route_too(self):
        self.assertEqual(self.text_label("/111.10,22.17/zh"),
                         "Shenzhen\u9644\u8fd1, Maoming Shi, Guangdong, CN")

    def test_the_ip_guess_keeps_its_own_wording(self):
        # "/" with no query: the location is a guess from the IP and the page
        # says so on its own line; "near" is for a point the reader typed
        self.addCleanup(setattr, serve, "GI", serve.GI)
        serve.GI = type("GI", (), {"locate": staticmethod(lambda ip: (22.17, 111.10))})
        self.assertEqual(self.text_label("/"), NEAREST["label"])


class AnEmptyFrameListIsNotAskAgainSoon(unittest.TestCase):
    KEY = R._sky_key(166.67, -77.85)

    def setUp(self):
        self.addCleanup(R._RA_FAIL.pop, self.KEY, None)
        self.h = handler("/x")
        self.h._caiyun_frame = lambda lon, lat, wait=0: None

    def png(self):
        serve.H._send_png(self.h, 166.67, -77.85, "166.6700,-77.8500", 200)
        (code, body), = self.h.seen
        return code, body

    def test_upstream_answered_empty(self):
        asked = time.time() - 4
        R._RA_FAIL[self.KEY] = asked
        code, body = self.png()
        first = body.splitlines()[0]
        self.assertEqual(code, 503)
        self.assertIn("empty when we asked at %s" % time.strftime("%H:%MZ", time.gmtime(asked)), first)
        self.assertNotIn("ask again", body)
        for claim in ("no coverage", "not covered", "no radar here"):
            self.assertNotIn(claim, body)

    def test_not_fetched_yet_is_still_said_as_before(self):
        R._RA_FAIL.pop(self.KEY, None)
        code, body = self.png()
        self.assertEqual(code, 503)
        self.assertIn("not fetched yet", body)

    def test_the_long_picture_says_it_in_the_place_s_local_time(self):
        asked = 1794446400.0                      # 2026-11-12 01:20Z, 14:20 at UTC+13
        R._RA_FAIL[self.KEY] = asked
        wx = {"tzshift": 46800, "result": {}}
        notes = {}
        self.addCleanup(setattr, R, "weather_full", R.weather_full)
        R.weather_full = lambda *a, **k: wx
        self.addCleanup(setattr, PN, "render", PN.render)
        PN.render = lambda *a, **k: notes.setdefault("note", k.get("radar_note")) and b"\x89PNG"
        self.h._picture_url = lambda *a, **k: "https://echorune.net/x.png"
        for lang, word in (("en", "14:20"), ("zh", "14:20"), ("ja", "14:20")):
            notes.clear(); self.h.seen = []
            serve.H._send_panorama(self.h, 166.67, -77.85, "x", 200, lang)
            self.assertEqual(notes["note"], PN.text(lang, "radar_empty").format(t=word), lang)
            self.assertNotIn("30", notes["note"])

    def test_every_language_has_the_sentence(self):
        for lang in ("en", "zh", "ja"):
            s = PN.text(lang, "radar_empty")
            self.assertIn("{t}", s, lang)
            self.assertNotIn("30", s, lang)


MCMURDO = {"date": "2026-11-12T00:00+13:00", "sunrise": {"time": "16:52"}, "sunset": {"time": "16:52"}}


class PolarDayAndNightAreSaid(unittest.TestCase):

    def test_known_cases(self):
        d = datetime.date
        for lat, day, want in ((-77.85, d(2026, 11, 12), "day"),     # McMurdo, the report
                               (69.65, d(2026, 12, 21), "night"),    # Tromso
                               (69.65, d(2026, 6, 21), "day"),
                               (68.97, d(2026, 12, 10), "night"),    # Murmansk, inside
                               (68.97, d(2026, 1, 15), None),        # Murmansk, after it ends
                               (69.65, d(2026, 3, 21), None),
                               (39.9, d(2026, 6, 21), None),
                               (-90.0, d(2026, 6, 21), "night")):
            self.assertEqual(W.polar(lat, day), want, (lat, day))

    def test_only_when_the_source_gives_one_time_for_both(self):
        self.assertEqual(W.polar_of(MCMURDO, -77.85), "day")
        self.assertIsNone(W.polar_of(dict(MCMURDO, sunset={"time": "16:53"}), -77.85))
        self.assertIsNone(W.polar_of(MCMURDO, None))
        self.assertIsNone(W.polar_of(dict(MCMURDO, date="not a date"), -77.85))

    def test_the_text_line(self):
        wx = {"realtime": {}, "daily": {"astro": [MCMURDO]}}
        for lang in ("en", "zh", "ja"):
            line = R.detail_lines(lang, wx, -77.85)[-1]
            self.assertEqual(line, W.POLAR[lang]["day"][1])
            self.assertNotIn("16:52", line)
        # without a latitude it prints what the source said, as before
        self.assertIn("16:52", R.detail_lines("en", wx)[-1])

    def test_the_picture_cell(self):
        self.assertEqual(PN.sun_cell(MCMURDO, -77.85, "zh"), W.POLAR["zh"]["day"][0])
        self.assertEqual(PN.sun_cell(dict(MCMURDO, sunset={"time": "17:10"}), -77.85, "en"),
                         "16:52–17:10")
        self.assertIsNone(PN.sun_cell(None, -77.85, "en"))

    def test_the_text_lines_still_fit(self):
        for lang in ("en", "zh", "ja"):
            for kind in ("day", "night"):
                self.assertLessEqual(R.cells(W.POLAR[lang][kind][1]), 40, (lang, kind))


if __name__ == "__main__":
    unittest.main()
