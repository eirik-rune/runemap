"""An "overcast" the source's own sunlight contradicts is printed as partly
cloudy -- and the page says that we changed it.

2026-11-11, Shenzhen: Caiyun said CLOUDY / cloudrate 0.97 with dswrf 790.7
W/m2, about clear-sky for that hour, under a cloudless sky (METAR CAVOK, HKO
"fine", Himawari empty). runemap/skyfix.py has the reasoning; these pin:

  * the Shenzhen case is corrected, a real overcast (kt 0.54, the highest
    thick-cloud station that day) is not;
  * dswrf is judged at the moment it describes -- the top of its hour -- never
    at the current minute (the test proves the trap is real before relying on
    it), and realtime is left alone when we cannot tell which moment that is;
  * night, low sun and every word but CLOUDY are never touched;
  * a corrected word always travels with the source's word, and every page
    that prints the corrected word prints the note, in 79 cells or fewer.
"""
import copy
import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")

from runemap import skyfix as SF  # noqa: E402
import render_scene as RS  # noqa: E402

SZ = (114.06, 22.54)


def clear(hh, mm=0):
    t = datetime(2026, 11, 11, hh - 8, mm, tzinfo=timezone.utc)
    return SF.clear_sky(SF.cos_zenith(*SZ, t))


def result(rt_sky="CLOUDY", rt_dswrf=790.7, first_hour=12, hours=None):
    """hours: [(local hour, skycon, dswrf)], first one is hourly[0]."""
    hours = hours or [(first_hour, "CLOUDY", 790.7344)]
    iso = lambda h: "2026-11-11T%02d:00+08:00" % h
    return {
        "realtime": {"skycon": rt_sky, "dswrf": rt_dswrf, "temperature": 24.0,
                     "apparent_temperature": 23.0, "humidity": 0.43,
                     "wind": {"speed": 10.0, "direction": 45},
                     "precipitation": {"local": {"intensity": 0.0}},
                     "air_quality": {"aqi": {"chn": 38}}},
        "minutely": {"precipitation_2h": [0.0] * 120, "probability": [0, 0, 0, 0], "description": ""},
        "hourly": {"temperature": [{"datetime": iso(h), "value": 24.0} for h, _, _ in hours],
                   "skycon": [{"datetime": iso(h), "value": s} for h, s, _ in hours],
                   "dswrf": [{"datetime": iso(h), "value": v} for h, _, v in hours],
                   "precipitation": [{"datetime": iso(h), "value": 0.0, "probability": 0} for h, _, _ in hours]},
        "daily": {},
        "forecast_keypoint": "",
    }


class TheRule(unittest.TestCase):
    def test_shenzhen_is_corrected_and_keeps_the_source_word(self):
        r = SF.apply(result(), *SZ)["realtime"]
        self.assertEqual(r["skycon"], "PARTLY_CLOUDY_DAY")
        self.assertEqual(r["skycon_upstream"], "CLOUDY")
        self.assertAlmostEqual(r["skycon_kt"], 1.01, delta=0.03)

    def test_a_real_overcast_is_left_alone(self):
        v = 0.54 * clear(12)
        r = SF.apply(result(rt_dswrf=v, hours=[(12, "CLOUDY", v)]), *SZ)
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")
        self.assertNotIn("skycon_upstream", r["realtime"])
        self.assertNotIn("upstream", r["hourly"]["skycon"][0])

    def test_judged_at_the_top_of_its_hour_not_now(self):
        v = 0.50 * clear(15)               # a real overcast, valid at 15:00
        # the trap is real: the same number judged at 15:50 would pass
        late = datetime(2026, 11, 11, 7, 50, tzinfo=timezone.utc)
        self.assertIsNotNone(SF.kt_if_contradicted("CLOUDY", v, *SZ, late))
        r = SF.apply(result(rt_dswrf=v, hours=[(15, "CLOUDY", v)]), *SZ)
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")

    def test_realtime_whose_moment_is_unknown_is_left_alone_and_says_so(self):
        err = io.StringIO()
        with redirect_stderr(err):
            r = SF.apply(result(rt_dswrf=790.7, hours=[(12, "PARTLY_CLOUDY_DAY", 700.0)]), *SZ)
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")
        self.assertIn("SKYFIX-UNTIMED", err.getvalue())

    def test_night_and_low_sun_are_never_touched_and_do_not_log(self):
        err = io.StringIO()
        with redirect_stderr(err):
            r = SF.apply(result(rt_dswrf=0.0, hours=[(21, "CLOUDY", 0.0), (17, "CLOUDY", 300.0)]), *SZ)
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")
        self.assertEqual([x["value"] for x in r["hourly"]["skycon"]], ["CLOUDY", "CLOUDY"])
        self.assertEqual(err.getvalue(), "")

    def test_only_overcast_is_ever_weakened(self):
        for sky in ("PARTLY_CLOUDY_DAY", "LIGHT_RAIN", "LIGHT_HAZE", "CLEAR_DAY"):
            r = SF.apply(result(rt_sky=sky, hours=[(12, sky, 790.7344)]), *SZ)
            self.assertEqual(r["realtime"]["skycon"], sky)
            self.assertEqual(r["hourly"]["skycon"][0]["value"], sky)

    def test_each_hour_is_judged_by_its_own_sunlight(self):
        r = SF.apply(result(hours=[(12, "CLOUDY", 790.7344), (13, "CLOUDY", 0.3 * clear(13)),
                                   (14, "CLOUDY", 681.6)]), *SZ)
        self.assertEqual([x["value"] for x in r["hourly"]["skycon"]],
                         ["PARTLY_CLOUDY_DAY", "CLOUDY", "PARTLY_CLOUDY_DAY"])
        self.assertEqual(r["hourly"]["skycon"][0]["upstream"], "CLOUDY")

    def test_applying_twice_is_applying_once(self):
        once = SF.apply(result(), *SZ)
        self.assertEqual(SF.apply(copy.deepcopy(once), *SZ), once)

    def test_no_sunlight_field_no_change(self):
        r = result()
        del r["realtime"]["dswrf"], r["hourly"]["dswrf"]
        self.assertEqual(SF.apply(copy.deepcopy(r), *SZ), r)


def page(lang, r):
    return RS.build(lang, "深圳" if lang != "en" else "Shenzhen, CN", "CLOUDY", "深圳",
                    SZ[0], SZ[1], 8, r, None)


class ThePageSaysWeChangedIt(unittest.TestCase):
    def test_every_language_prints_the_note_under_now(self):
        r = SF.apply(result(hours=[(12, "CLOUDY", 790.7344)]), *SZ)
        for lang in ("en", "zh", "ja"):
            L = page(lang, copy.deepcopy(r)).split("\n")
            i = next(k for k, ln in enumerate(L) if ln.startswith(("now:", "当前:", "現在:")))
            self.assertIn("101%", L[i + 1])
            self.assertTrue(L[i + 1].startswith(("sky:", "天空:", "空:")), (lang, L[i + 1]))
            self.assertTrue(any(ln.startswith("* ") for ln in L), (lang, "no hourly footnote"))
        en = page("en", copy.deepcopy(r)).split("\n")
        # the now: line is an interface: same shape, the corrected token in it
        self.assertTrue(any(ln.startswith("now: PARTLY_CLOUDY_DAY  24C") for ln in en))

    def test_the_notes_fit_79_cells_at_their_longest(self):
        for lang in ("en", "zh", "ja"):
            X = RS._TX[lang]
            for ln in (X["sky_fix"].format(kt="999"), X["sky_fix_h"].format(m="100")):
                self.assertLessEqual(RS.cells(ln), 79, (lang, RS.cells(ln), ln))

    def test_nothing_corrected_nothing_added(self):
        r = result(rt_dswrf=0.3 * clear(12), hours=[(12, "CLOUDY", 0.3 * clear(12))])
        SF.apply(r, *SZ)
        for lang in ("en", "zh", "ja"):
            out = page(lang, copy.deepcopy(r))
            self.assertNotIn("\n* ", out)
            self.assertFalse(any(ln.startswith(("sky:", "天空:", "空:")) for ln in out.split("\n")))


class ThePictureSaysItToo(unittest.TestCase):
    """2026-11-11: the first English note ran off the right edge of the card.
    Nothing errors when that happens; only looking at the PNG showed it."""

    def test_the_note_fits_beside_the_longest_corrected_word_at_full_size(self):
        try:
            from runemap import panorama as PN
        except ImportError as e:            # no Pillow/numpy: CI installs them
            self.skipTest(str(e))
        words = {"en": PN.SKY, "zh": RS.SKY_ZH, "ja": RS.SKY_JA}
        X0, X1 = PN.M + PN.P, PN.PT_W - PN.M - PN.P
        for lang, table in words.items():
            if not PN.RI.can_draw(lang):
                continue
            pg = PN._Page(None, PN._Measure(), lang)
            end = X0 + pg.width(table[SF.NEW], 22, True) + 10 + pg.width(PN.T[lang]["skyfix"], 15)
            self.assertLessEqual(end, X1, (lang, end, X1))

    def test_a_corrected_sky_draws_its_note(self):
        try:
            from runemap import panorama as PN
        except ImportError as e:
            self.skipTest(str(e))
        seen = []
        real = PN._Page.text

        def spy(self, x, y, s, *a, **k):
            seen.append(s)
            return real(self, x, y, s, *a, **k)

        r = SF.apply(result(), *SZ)
        r["daily"] = {}
        full = {"result": r, "server_time": 1794369600, "tzshift": 28800}
        PN._Page.text = spy
        try:
            PN.render(full, None, "Shenzhen", lang="en")
        finally:
            PN._Page.text = real
        self.assertIn(PN.T["en"]["skyfix"], seen)


if __name__ == "__main__":
    unittest.main()
