"""/radar.json: numbers for a box (issue #259).

Every test runs against a fake upstream built here: stations, frame lists and
PNGs are made in memory, so nothing needs a token or the network, and the
expected values come from where the test PAINTED echo -- not from running the
module and copying what it said.
"""
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, ".."))
import radar_grid as RG
from runemap.radar_image import CAIYUN_RAMP

ALPHA = 90          # what upstream draws echo with (measured: 99.8% of visible pixels)
T_NOW = 1_800_000_000


def _merc(lat):
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _inv_merc(y):
    return math.degrees(2 * math.atan(math.exp(math.radians(y))) - math.pi / 2)


class Station:
    """A fake upstream station: a Web Mercator box, frames, and echo blobs."""

    def __init__(self, sid, bbox, size=200, times=(T_NOW,), cadence=None):
        self.sid, self.bbox, self.size = sid, bbox, size
        self.times = list(times)
        self.blobs = {}          # frame ts -> [(lon, lat, ramp index)]

    def paint(self, ts, lon, lat, k):
        self.blobs.setdefault(ts, []).append((lon, lat, k))

    def pixel(self, lon, lat):
        la0, lo0, la1, lo1 = self.bbox
        x = (lon - lo0) / (lo1 - lo0) * self.size
        y = (_merc(la1) - _merc(lat)) / (_merc(la1) - _merc(la0)) * self.size
        return int(x), int(y)

    def png(self, ts):
        a = np.zeros((self.size, self.size, 4), dtype=np.uint8)
        for lon, lat, k in self.blobs.get(ts, []):
            x, y = self.pixel(lon, lat)
            a[max(0, y - 3):y + 4, max(0, x - 3):x + 4] = list(CAIYUN_RAMP[k]) + [ALPHA]
        buf = io.BytesIO()
        Image.fromarray(a, "RGBA").save(buf, "PNG")
        return buf.getvalue()

    def centre(self):
        la0, lo0, la1, lo1 = self.bbox
        return (lo0 + lo1) / 2, _inv_merc((_merc(la0) + _merc(la1)) / 2)

    def serves(self, lon, lat):
        la0, lo0, la1, lo1 = self.bbox
        return lo0 <= lon <= lo1 and la0 <= lat <= la1


class Upstream:
    """fetch(url, timeout) and list_url(lon, lat) for answer(); counts calls."""

    def __init__(self, *stations):
        self.stations = stations
        self.calls = []

    def list_url(self, lon, lat):
        return "list:%s,%s" % (lon, lat)

    def nearest(self, lon, lat):
        best = None
        for st in self.stations:
            if st.serves(lon, lat):
                cx, cy = st.centre()
                d = (cx - lon) ** 2 + (cy - lat) ** 2
                if best is None or d < best[0]:
                    best = (d, st)
        return best and best[1]

    def fetch(self, url, timeout):
        self.calls.append(url)
        if url.startswith("list:"):
            lon, lat = (float(v) for v in url[5:].split(","))
            st = self.nearest(lon, lat)
            if st is None:
                return b'{"status":"failed"}'
            return json.dumps({"status": "ok", "station": st.sid, "images": [
                ["png:%s:%d.png" % (st.sid, t), t, st.bbox] for t in st.times]}).encode()
        if url.startswith("png:"):
            sid, ts = url[4:-4].split(":")
            st = [s for s in self.stations if s.sid == sid][0]
            return st.png(int(ts))
        raise AssertionError("unexpected url " + url)


def ask(up, bbox, res=5, frames=1, cache=None, now=lambda: T_NOW):
    qs = {"bbox": [",".join(str(v) for v in bbox)], "res": [str(res)], "frames": [str(frames)]}
    cache = cache or tempfile.mkdtemp(prefix="rg-")
    code, body = RG.answer(qs, up.fetch, up.list_url, cache, now=now)
    return code, json.loads(body)


def cell(d, lon, lat, frame=-1):
    g = d["grid"]
    ix = int(math.floor((lon - (g["lon0"] - g["dlon"] / 2)) / g["dlon"]))
    iy = int(math.floor(((g["lat0"] - g["dlat"] / 2) - lat) / -g["dlat"]))
    return d["frames"][frame]["values"][iy][ix]


# A China station (reach: circle) and the box we ask about around it.
AZ = (30.0, 100.0, 34.0, 104.8)          # lat0, lon0, lat1, lon1 as upstream gives it
ASK = (99.0, 29.0, 106.0, 35.0)          # west, south, east, north


class ValuesAreWhatWasDrawn(unittest.TestCase):

    def setUp(self):
        self.st = Station("AZ0001", AZ)
        self.cx, self.cy = self.st.centre()
        self.st.paint(T_NOW, self.cx, self.cy, 6)        # 7th colour -> step 7
        self.code, self.d = ask(Upstream(self.st), ASK)

    def test_echo_is_its_step_on_the_scale(self):
        self.assertEqual(self.code, 200)
        self.assertEqual(cell(self.d, self.cx, self.cy), 7)

    def test_seen_and_dry_is_zero(self):
        self.assertEqual(cell(self.d, self.cx + 1.0, self.cy), 0)

    def test_beyond_the_station_box_is_null(self):
        self.assertIsNone(cell(self.d, 105.5, 32.0))
        self.assertIsNone(cell(self.d, 101.0, 34.6))

    def test_corner_of_a_china_station_picture_is_null_not_dry(self):
        """Measured: echo stops at the inscribed circle. The corner is out of reach."""
        la0, lo0, la1, lo1 = AZ
        self.assertIsNone(cell(self.d, lo1 - 0.15, la1 - 0.15))
        self.assertIsNone(cell(self.d, lo0 + 0.15, la0 + 0.15))
        self.assertEqual(self.d["stations"][0]["reach"], "circle")

    def test_row_zero_is_north_and_steps_are_stated(self):
        g = self.d["grid"]
        self.assertLess(g["dlat"], 0)
        self.assertGreater(g["dlon"], 0)
        self.assertAlmostEqual(g["lat0"], ASK[3] + g["dlat"] / 2, places=5)
        self.assertAlmostEqual(g["lon0"], ASK[0] + g["dlon"] / 2, places=5)
        v = self.d["frames"][0]["values"]
        self.assertEqual((len(v), len(v[0])), (g["ny"], g["nx"]))

    def test_no_made_up_units(self):
        txt = json.dumps(self.d)
        self.assertNotIn("mm/h\"", txt.replace("no dBZ or mm/h", ""))
        self.assertEqual([e["rgb"] for e in self.d["legend"]], [list(c) for c in CAIYUN_RAMP])
        self.assertEqual(self.d["source"], "caiyunapp.com")
        self.assertIn("not caiyun's own product", self.d["drawn_by"])


class AStationWeHaveNotMeasuredSeesItsWholeBox(unittest.TestCase):

    def test_box_reach_corner_is_dry_not_null(self):
        st = Station("DE-XYZ", AZ)
        code, d = ask(Upstream(st), ASK)
        la0, lo0, la1, lo1 = AZ
        self.assertEqual(cell(d, lo1 - 0.15, la1 - 0.15), 0)
        self.assertEqual(d["stations"][0]["reach"], "box")


class OverlapTakesTheStrongest(unittest.TestCase):

    def test_max_over_stations(self):
        a = Station("AZ0001", (30.0, 100.0, 34.0, 104.8))
        b = Station("AZ0002", (30.5, 101.0, 34.5, 105.8))
        lon, lat = 102.9, 32.4                     # inside both circles
        a.paint(T_NOW, lon, lat, 2)
        b.paint(T_NOW, lon, lat, 9)
        code, d = ask(Upstream(a, b), (99.0, 29.0, 107.0, 35.5))
        self.assertEqual({s["id"] for s in d["stations"]}, {"AZ0001", "AZ0002"})
        self.assertEqual(cell(d, lon, lat), 10)

    def test_max_does_not_depend_on_which_station_is_painted_last(self):
        """Ablation 2026-11-14: with the strong station painted last, "last one
        wins" passed the test above. Swap the strengths so it cannot."""
        a = Station("AZ0001", (30.0, 100.0, 34.0, 104.8))
        b = Station("AZ0002", (30.5, 101.0, 34.5, 105.8))
        lon, lat = 102.9, 32.4
        a.paint(T_NOW, lon, lat, 9)
        b.paint(T_NOW, lon, lat, 2)
        code, d = ask(Upstream(a, b), (99.0, 29.0, 107.0, 35.5))
        self.assertEqual(cell(d, lon, lat), 10)
        a2 = Station("AZ0001", (30.0, 100.0, 34.0, 104.8))
        b2 = Station("AZ0002", (30.5, 101.0, 34.5, 105.8))
        a2.paint(T_NOW, lon, lat, 2)
        b2.paint(T_NOW, lon, lat, 9)
        code, d = ask(Upstream(a2, b2), (99.0, 29.0, 107.0, 35.5))
        self.assertEqual(cell(d, lon, lat), 10)

    def test_one_dry_one_wet_is_wet(self):
        a = Station("AZ0001", (30.0, 100.0, 34.0, 104.8))
        b = Station("AZ0002", (30.5, 101.0, 34.5, 105.8))
        lon, lat = 102.9, 32.4
        b.paint(T_NOW, lon, lat, 4)
        code, d = ask(Upstream(a, b), (99.0, 29.0, 107.0, 35.5))
        self.assertEqual(cell(d, lon, lat), 5)


class FramesLineUp(unittest.TestCase):

    def test_newest_frame_is_where_most_stations_have_published(self):
        """16:15Z 2026-11-14: taking the single newest frame anywhere left seven
        Gansu stations out of it. The newest returned frame is the latest time
        the most stations cover."""
        a = Station("AZ0001", AZ, times=[T_NOW - 1440, T_NOW - 1080, T_NOW - 720, T_NOW - 360, T_NOW])
        b = Station("AZ0002", (30.5, 101.0, 34.5, 105.8),
                    times=[T_NOW - 1460, T_NOW - 1100, T_NOW - 740, T_NOW - 380])   # one frame behind
        lists = [[(None, float(t), None) for t in a.times], [(None, float(t), None) for t in b.times]]
        self.assertEqual(RG.align(lists), T_NOW - 360)

    def test_oldest_first_six_minutes_apart_and_gaps_named(self):
        a = Station("AZ0001", AZ, times=[T_NOW - 360 * k for k in range(6)][::-1])
        b = Station("AZ0002", (30.5, 101.0, 34.5, 105.8), times=[T_NOW - 30, T_NOW - 1830])
        code, d = ask(Upstream(a, b), (99.0, 29.0, 107.0, 35.5), frames=4)
        ts = [f["t"] for f in d["frames"]]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(len(ts), 4)
        self.assertEqual(d["frames"][-1]["gaps"], [])
        self.assertEqual(d["frames"][0]["gaps"], ["AZ0002"])
        for f in d["frames"]:
            self.assertEqual(f["kind"], "obs")
            self.assertLessEqual(f["spread_s"], RG.MATCH_S)


class NoRadarIsSaidNotGuessed(unittest.TestCase):

    def test_box_with_no_station(self):
        code, d = ask(Upstream(), (80.0, 38.0, 84.0, 41.0))
        self.assertEqual(code, 200)
        self.assertEqual(d["frames"], [])
        self.assertEqual(d["stations"], [])
        self.assertIn("no radar station", d["note"])


class ProbesAreRememberedAndBounded(unittest.TestCase):

    def test_second_ask_does_not_probe_again(self):
        up = Upstream(Station("AZ0001", AZ))
        cache = tempfile.mkdtemp(prefix="rg-")
        ask(up, ASK, cache=cache)
        lists_first = len([u for u in up.calls if u.startswith("list:")])
        up.calls.clear()
        ask(up, ASK, cache=cache)
        lists_second = len([u for u in up.calls if u.startswith("list:")])
        self.assertGreater(lists_first, 5)
        self.assertEqual(lists_second, 1)          # the station's frame list only

    def test_failed_probe_is_forgotten_after_three_hours_ok_after_a_day(self):
        path = os.path.join(tempfile.mkdtemp(prefix="rg-"), "p.json")
        t = [T_NOW]
        book = RG.ProbeBook(path, now=lambda: t[0])
        book.put("1.0,1.0", {"s": None, "at": T_NOW})
        book.put("2.0,2.0", {"s": "AZ1", "bbox": [0, 0, 1, 1], "at": T_NOW})
        t[0] = T_NOW + 3 * 3600 + 1
        self.assertIsNone(book.get("1.0,1.0"))
        self.assertIsNotNone(book.get("2.0,2.0"))
        t[0] = T_NOW + 86400 + 1
        self.assertIsNone(book.get("2.0,2.0"))

    def test_probe_limit_is_said_not_hidden(self):
        old = RG.MAX_NEW_PROBES
        RG.MAX_NEW_PROBES = 3
        try:
            code, d = ask(Upstream(Station("AZ0001", AZ)), ASK)
        finally:
            RG.MAX_NEW_PROBES = old
        self.assertFalse(d["coverage"]["complete"])
        self.assertGreater(d["coverage"]["unprobed"], 0)
        self.assertIn("Ask again", d["note"])
        self.assertNotIn("no radar station reaches", d["note"])


class TheTokenNeverLeaks(unittest.TestCase):

    def test_errors_carrying_the_url_stay_inside(self):
        def fetch(url, timeout):
            raise RuntimeError("HTTP 500: https://api.example/v1/radar/images?token=SECRET123")
        qs = {"bbox": ["99,29,106,35"]}
        code, body = RG.answer(qs, fetch, lambda lo, la: "x?token=SECRET123", tempfile.mkdtemp())
        self.assertNotIn("SECRET123", body)


class BadQuestionsGetA400ThatSaysWhy(unittest.TestCase):

    def _bad(self, **q):
        code, body = RG.answer({k: [v] for k, v in q.items()}, None, None, tempfile.mkdtemp())
        self.assertEqual(code, 400, body)
        d = json.loads(body)
        self.assertIn("usage", d)
        return d["error"]

    def test_bbox_shape(self):
        self.assertIn("four numbers", self._bad(bbox="1,2,3"))
        self.assertIn("four numbers", self._bad(bbox="a,b,c,d"))
        self.assertIn("west of", self._bad(bbox="105,30,100,35"))
        self.assertIn("south of", self._bad(bbox="100,35,105,30"))

    def test_too_big(self):
        self.assertIn("2000 km", self._bad(bbox="80,20,110,45"))

    def test_res_and_frames_range(self):
        self.assertIn("outside", self._bad(bbox="100,30,105,35", res="1"))
        self.assertIn("outside", self._bad(bbox="100,30,105,35", frames="0"))
        self.assertIn("outside", self._bad(bbox="100,30,105,35", frames="99"))

    def test_value_cap_names_what_would_fit(self):
        msg = self._bad(bbox="95,30,112,42", res="4", frames="20")
        m = re.search(r"frames<=(\d+)", msg)
        self.assertIsNotNone(m, msg)
        RG.parse({"bbox": ["95,30,112,42"], "res": ["4"], "frames": [m.group(1)]})

    def test_gansu_as_asked_fits(self):
        RG.parse({"bbox": ["92.3,32.5,108.7,42.8"], "res": ["6"], "frames": ["10"]})


def _t(ts):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(ts))


class SinceReturnsOnlyNewFrames(unittest.TestCase):
    """Qianlu's poller re-fetched 3 MB to learn one new frame (#259)."""

    def setUp(self):
        self.st = Station("AZ0001", AZ, times=[T_NOW - 360 * k for k in range(10)][::-1])

    def _ask(self, **q):
        qs = {"bbox": [",".join(str(v) for v in ASK)]}
        qs.update({k: [v] for k, v in q.items()})
        code, body = RG.answer(qs, Upstream(self.st).fetch, Upstream(self.st).list_url,
                               tempfile.mkdtemp(prefix="rg-"), now=lambda: T_NOW)
        return code, json.loads(body)

    def test_only_frames_after_since(self):
        code, d = self._ask(frames="10", since=_t(T_NOW - 3 * 360))
        self.assertEqual([f["t"] for f in d["frames"]],
                         [_t(T_NOW - 720), _t(T_NOW - 360), _t(T_NOW)])
        self.assertEqual(d["newest"], _t(T_NOW))

    def test_passing_back_the_newest_returns_nothing_and_says_so(self):
        code, d = self._ask(since=_t(T_NOW))
        self.assertEqual(code, 200)
        self.assertEqual(d["frames"], [])
        self.assertEqual(d["newest"], _t(T_NOW))
        self.assertIn("nothing newer", d["note"])

    def test_a_frame_off_the_minute_is_not_returned_twice(self):
        """t is printed to the minute; upstream frames are not on the minute.
        Passing back the newest t must not hand the same frame back again."""
        self.st = Station("AZ0001", AZ, times=[T_NOW + 25 - 360 * k for k in range(10)][::-1])
        code, d = self._ask(frames="3")
        newest = d["frames"][-1]["t"]
        code, d2 = self._ask(since=newest)
        self.assertEqual(d2["frames"], [])

    def test_since_without_frames_returns_every_new_frame(self):
        code, d = self._ask(since=_t(T_NOW - 5 * 360))
        self.assertEqual(len(d["frames"]), 5)

    def test_epoch_seconds_work_too(self):
        code, d = self._ask(frames="10", since=str(T_NOW - 2 * 360))
        self.assertEqual(len(d["frames"]), 2)

    def test_without_since_nothing_changes(self):
        code, d = self._ask(frames="3")
        self.assertEqual(len(d["frames"]), 3)
        self.assertEqual(d["newest"], _t(T_NOW))

    def test_bad_since_is_a_400_that_shows_the_format(self):
        code, d = self._ask(since="yesterday")
        self.assertEqual(code, 400)
        self.assertIn("2026-11-14T16:17Z", d["error"])


class RoutedBeforeThePlaceMatcher(unittest.TestCase):
    """'mcp' once fuzzy-matched Macapa and answered 200 with its weather."""

    def test_route_precedes_place_lookup(self):
        with open(os.path.join(HERE, "..", "scripts", "serve.py"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("    def do_GET(self):"):]
        self.assertLess(body.index('"/radar.json"'), body.index("G.lookup("))
        self.assertLess(body.index('"/radar.json"'), body.index("G.rlookup("))


if __name__ == "__main__":
    unittest.main()
