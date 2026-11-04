"""The text map says the rest of the forecast, and only adds lines to say it.

bob 2026-11-04: "让文字版也丰富一些". The long picture had grown feels-like,
today's range, wind direction, air quality, sunrise/sunset, the half-hour
chances, 24 hours and five days -- all from the /weather call the text map
already makes -- and the text printed none of it.

What must hold, each as a property and not as a sentence:
  * the new blocks only insert lines (most readers are agents, and a line
    they grep is an interface) -- see TheNewBlocksArriveWhole for exactly
    how far that check reaches;
  * every new line fits 79 terminal cells in en / zh / ja with the longest
    values the fields can take, measured in cells (CJK is two), not len();
  * AQI 0 is "no data" (runemap.words.aqi_value), as in the picture;
  * no data, no line -- nothing is invented for a response without hourly or
    daily, and a block that cannot be read says so instead of vanishing.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")

import render_scene as RS  # noqa: E402

LANGS = ("en", "zh", "ja")


def wx_full(worst=False, aqi=None, day_aqi=None, now_aqi=None):
    """A /weather result. worst=True gives every field its longest value."""
    hours = ["2026-11-04T%02d:00+08:00" % h for h in range(24)]
    days = ["2026-11-%02dT00:00+08:00" % (4 + k) for k in range(5)]
    sky = "PARTLY_CLOUDY_NIGHT" if worst else "LIGHT_RAIN"
    t, p, v = (-12.0, 100, 12.5) if worst else (18.0, 60, 0.4)
    a = 175 if worst else 60
    return {
        "realtime": {"skycon": sky, "temperature": t, "apparent_temperature": t - 8,
                     "humidity": 0.93, "wind": {"speed": 108.0 if worst else 7.0, "direction": 315},
                     "precipitation": {"local": {"intensity": v}},
                     "air_quality": {"aqi": {"chn": a if now_aqi is None else now_aqi}}},
        "minutely": {"precipitation_2h": [0.0] * 119 + [v], "probability": [1, 1, 1, 1] if worst else [.6, .4, .2, 0],
                     "description": ""},
        "hourly": {"temperature": [{"datetime": h, "value": t} for h in hours],
                   "skycon": [{"datetime": h, "value": sky} for h in hours],
                   "precipitation": [{"datetime": h, "value": v, "probability": p} for h in hours],
                   "air_quality": {"aqi": [{"datetime": h, "value": {"chn": a if aqi is None else aqi[i]}}
                                           for i, h in enumerate(hours)]}},
        "daily": {"temperature": [{"date": d, "min": t, "max": t + 9} for d in days],
                  "skycon": [{"date": d, "value": "PARTLY_CLOUDY_DAY" if worst else sky} for d in days],
                  "precipitation": [{"date": d, "probability": p} for d in days],
                  "air_quality": {"aqi": [{"date": d, "max": {"chn": a if day_aqi is None else day_aqi[k]}}
                                          for k, d in enumerate(days)]},
                  "astro": [{"date": d, "sunrise": {"time": "06:11"}, "sunset": {"time": "17:04"}} for d in days]},
        "forecast_keypoint": "",
    }


def new_lines(lang, wx):
    out = list(RS.detail_lines(lang, wx))
    c = RS.chance_line(lang, wx)
    if c:
        out.append(c)
    return out + RS.forecast_lines(lang, wx)


def build(lang, wx, rb=None):
    return RS.build(lang, "上海" if lang != "en" else "Shanghai, CN", "MODERATE_RAIN", "上海",
                    121.458, 31.222, 8, wx, rb)


class EveryNewLineFitsEightyColumns(unittest.TestCase):
    def test_the_ruler_counts_cells_not_characters(self):
        """Negative control: 40 CJK glyphs are 40 characters and 80 cells."""
        self.assertEqual(len("东" * 40), 40)
        self.assertEqual(RS.cells("东" * 40), 80)

    def test_longest_values_in_every_language(self):
        wx = wx_full(worst=True)
        for lang in LANGS:
            lines = new_lines(lang, wx)
            self.assertGreater(len(lines), 12, lang)      # the fixture reached every block
            for ln in lines:
                self.assertLessEqual(RS.cells(ln), 79, "%s %d cells: %r" % (lang, RS.cells(ln), ln))


class TheNewBlocksArriveWhole(unittest.TestCase):
    """What this CAN see: every line the three helpers produce is inserted,
    none dropped, none merged into a neighbour -- switching them off leaves
    the rest of the page as a subsequence, one blank line shorter.

    What it CANNOT see, and is not to be read as guarding: an edit inside
    build() itself to an existing line. Both sides of this comparison run
    the same build(), so such an edit lands on both and the subsequence
    still holds (fired 2026-11-04: it stayed green). That the existing lines
    were left byte-identical by the commit that added these blocks was
    checked once against the previous render_scene.py, outside this suite."""

    def test_off_is_a_subsequence_of_on_and_the_rest_is_new(self):
        wx = wx_full()
        saved = RS.detail_lines, RS.chance_line, RS.forecast_lines
        for lang in LANGS:
            on = build(lang, wx).split("\n")
            added = new_lines(lang, wx)
            try:
                RS.detail_lines = lambda *a: []
                RS.chance_line = lambda *a: None
                RS.forecast_lines = lambda *a: []
                off = build(lang, wx).split("\n")
            finally:
                RS.detail_lines, RS.chance_line, RS.forecast_lines = saved
            it = iter(on)
            self.assertTrue(all(any(x == y for y in it) for x in off), lang)
            # one blank line separates the forecast from the map
            self.assertEqual(len(on) - len(off), len(added) + 1, lang)


class AnAqiOfZeroIsNoData(unittest.TestCase):
    """Tokyo 2026-11-04: the air now at 11, every later hour and day 0."""

    def test_holes_are_said_not_printed_as_zero(self):
        wx = wx_full(aqi=[11] + [0] * 23, day_aqi=[11, 0, 0, 0, 0], now_aqi=0)
        for lang in LANGS:
            out = build(lang, wx)
            self.assertNotIn("AQI 0", out, lang)
            self.assertNotIn("AQI(CN) 0", out, lang)
            self.assertIn(RS._TX[lang]["aqi_none"], out, lang)
            self.assertIn("AQI 11", out, lang)            # the one real day stays

    def test_no_daily_value_drops_the_note_about_it(self):
        wx = wx_full(day_aqi=[0] * 5)
        for lang in LANGS:
            out = build(lang, wx)
            self.assertIn(RS._TX[lang]["days"].format(n=5), out, lang)
            self.assertNotIn(RS._TX[lang]["days_aqi"].format(n=5), out, lang)

    def test_a_present_series_is_printed_whole(self):
        out = build("en", wx_full())
        self.assertNotIn(RS._TX["en"]["aqi_none"], out)
        self.assertEqual(out.count("  AQI 60"), 8 + 5)    # 8 hourly rows, 5 days


class ThePeakIsNeverPrintedAsZero(unittest.TestCase):
    def test_a_trace_of_rain_keeps_its_digits(self):
        # Reykjavik 2026-11-04: "peak 0.0mm/h in 16min" under a curve that
        # was not empty -- a value above zero printed as zero
        wx = wx_full()
        wx["minutely"]["precipitation_2h"] = [0.0] * 16 + [0.03] * 20 + [0.0] * 84
        for lang in LANGS:
            line = RS.chance_line(lang, wx)
            self.assertIn("0.03mm/h", line, lang)


class NoDataNoLine(unittest.TestCase):
    MIN = {"realtime": {"skycon": "CLOUDY", "temperature": 20.0, "humidity": 0.5,
                        "wind": {"speed": 5.0}, "precipitation": {"local": {"intensity": 0.0}}},
           "minutely": {"precipitation_2h": [0.0] * 120, "description": ""},
           "forecast_keypoint": ""}

    def test_a_bare_response_gets_no_invented_blocks(self):
        for lang in LANGS:
            self.assertEqual(new_lines(lang, self.MIN), [], lang)
            build(lang, self.MIN)                          # and does not raise

    def test_an_unreadable_block_says_so(self):
        wx = wx_full()
        del wx["hourly"]["temperature"][3]["value"]     # 3: a row that is printed (every 3 h)
        for lang in LANGS:
            out = build(lang, wx)
            self.assertIn(RS._TX[lang]["broken"], out, lang)
            self.assertIn(RS._TX[lang]["feel"].format(v="10"), out, lang)   # what could be read stays


if __name__ == "__main__":
    unittest.main()
