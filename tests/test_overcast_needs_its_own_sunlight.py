"""The page says the sky that is there: Shenzhen 2026-11-11 is clear.

Caiyun said CLOUDY (cloudrate 0.97, dswrf 790.7 = clear-sky sunlight) under a
cloudless sky. runemap/skyfix.py has the reasoning; these pin:

  * Qianlu's 39 airports at 11-11 04:30Z come out as she checked them against
    the satellite (fixture_skyfix_20261111.json, `expect2`);
  * with the cloud mask, Shenzhen is CLEAR_DAY now, in the current hour's row,
    and today's summary is no longer overcast; without it, the sunlight rule
    still turns its overcast into partly cloudy, and nothing says "clear";
  * dswrf is judged at the top of its hour, never at the current minute;
  * night, twilight, and rain/haze/dust words are never touched;
  * the page prints only the answer (bob: no note about what the source said),
    and credits JMA/NOAA exactly when their mask decided it;
  * the mask reader returns (None, None) for every way it can be wrong, never
    a share that would read as a clear sky.
"""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")

from runemap import cloudmask as CM  # noqa: E402
from runemap import skyfix as SF  # noqa: E402
import render_scene as RS  # noqa: E402

SZ = (114.06, 22.54)
NOON = datetime(2026, 11, 11, 4, 30, tzinfo=timezone.utc)      # 12:30 in Shenzhen
NIGHT = datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc)     # 22:00


def clear(hh, mm=0):
    t = datetime(2026, 11, 11, hh - 8, mm, tzinfo=timezone.utc)
    return SF.clear_sky(SF.cos_zenith(*SZ, t))


def result(rt_sky="CLOUDY", rt_dswrf=790.7, hours=None, today="CLOUDY"):
    """hours: [(local hour, skycon, dswrf)]; the first is hourly[0]."""
    hours = hours or [(12, "CLOUDY", 790.7344), (15, "CLOUDY", 681.6)]
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
        "daily": {"temperature": [{"date": "2026-11-11T00:00+08:00", "min": 17.0, "max": 24.0}],
                  "skycon": [{"date": "2026-11-11T00:00+08:00", "value": today}]},
        "forecast_keypoint": "",
    }


def sky(r):
    return (r["realtime"]["skycon"], [x["value"] for x in r["hourly"]["skycon"]],
            r["daily"]["skycon"][0]["value"])


class TheRule(unittest.TestCase):
    def test_shenzhen_observed_clear_is_clear_now_this_hour_and_not_overcast_today(self):
        r = SF.apply(result(), *SZ, obs=(0.0, NOON))
        self.assertEqual(sky(r), ("CLEAR_DAY", ["CLEAR_DAY", "PARTLY_CLOUDY_DAY"], "PARTLY_CLOUDY_DAY"))
        self.assertEqual(r["realtime"]["cloudmask_at"], "2026-11-11T04:30Z")

    def test_without_the_mask_overcast_becomes_partly_and_never_clear(self):
        r = SF.apply(result(), *SZ)
        self.assertEqual(sky(r), ("PARTLY_CLOUDY_DAY", ["PARTLY_CLOUDY_DAY", "PARTLY_CLOUDY_DAY"], "CLOUDY"))
        self.assertNotIn("cloudmask_at", r["realtime"])

    def test_observed_thick_cloud_is_overcast_even_when_the_source_said_partly(self):
        v = 0.06 * clear(12)                       # Changsha that noon: kt 0.06
        r = SF.apply(result(rt_sky="PARTLY_CLOUDY_DAY", rt_dswrf=v, hours=[(12, "PARTLY_CLOUDY_DAY", v)]),
                     *SZ, obs=(1.0, NOON))
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")

    def test_observed_full_but_sunlit_is_thin_cloud(self):
        v = 0.95 * clear(12)                       # Zhengzhou/Hefei: a thin real layer
        r = SF.apply(result(rt_sky="CLOUDY", rt_dswrf=v, hours=[(12, "CLOUDY", v)]), *SZ, obs=(1.0, NOON))
        self.assertEqual(r["realtime"]["skycon"], "PARTLY_CLOUDY_DAY")

    def test_a_real_overcast_without_the_mask_is_left_alone(self):
        v = 0.54 * clear(12)
        r = SF.apply(result(rt_dswrf=v, hours=[(12, "CLOUDY", v)]), *SZ)
        self.assertEqual(sky(r), ("CLOUDY", ["CLOUDY"], "CLOUDY"))

    def test_judged_at_the_top_of_its_hour_not_now(self):
        v = 0.50 * clear(15)                       # a real overcast, valid at 15:00
        late = datetime(2026, 11, 11, 7, 50, tzinfo=timezone.utc)
        self.assertGreaterEqual(SF.sunlight(v, *SZ, late), SF.KT_MIN)    # the trap is real
        r = SF.apply(result(rt_dswrf=v, hours=[(15, "CLOUDY", v)]), *SZ)
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")

    def test_realtime_whose_moment_is_unknown_gets_no_sunlight_rule_and_says_so(self):
        err = io.StringIO()
        with redirect_stderr(err):
            r = SF.apply(result(rt_dswrf=790.7, hours=[(12, "PARTLY_CLOUDY_DAY", 700.0)]), *SZ)
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")
        self.assertIn("SKYFIX-UNTIMED", err.getvalue())

    def test_night_and_twilight_leave_the_source_word(self):
        err = io.StringIO()
        with redirect_stderr(err):
            r = SF.apply(result(rt_dswrf=0.0, hours=[(22, "CLOUDY", 0.0)]), *SZ, obs=(0.0, NIGHT))
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")
        self.assertNotIn("cloudmask_at", r["realtime"])
        self.assertEqual(err.getvalue(), "")
        dusk = datetime(2026, 11, 11, 9, 20, tzinfo=timezone.utc)          # 17:20, sun ~4 deg
        self.assertLess(SF.cos_zenith(*SZ, dusk), SF.COSZ_OBS)
        r = SF.apply(result(rt_dswrf=50.0, hours=[(17, "CLOUDY", 50.0)]), *SZ, obs=(0.0, dusk))
        self.assertEqual(r["realtime"]["skycon"], "CLOUDY")

    def test_rain_haze_dust_are_never_touched(self):
        for w in ("LIGHT_RAIN", "LIGHT_HAZE", "DUST", "WIND", "FOG"):
            r = SF.apply(result(rt_sky=w, hours=[(12, w, 790.7344)], today=w), *SZ, obs=(0.0, NOON))
            self.assertEqual(sky(r), (w, [w], w))

    def test_future_hours_have_no_observation(self):
        v = 0.3 * clear(15)
        r = SF.apply(result(hours=[(12, "CLOUDY", 790.7344), (15, "CLOUDY", v)]), *SZ, obs=(0.0, NOON))
        self.assertEqual(r["hourly"]["skycon"][1]["value"], "CLOUDY")

    def test_applying_twice_is_applying_once(self):
        for obs in ((0.0, NOON), (None, None)):
            once = SF.apply(result(), *SZ, obs=obs)
            self.assertEqual(SF.apply(copy.deepcopy(once), *SZ, obs=obs), once)

    def test_qianlus_39_airports(self):
        rows = json.load(open(os.path.join(ROOT, "tests", "fixture_skyfix_20261111.json")))
        self.assertEqual(len(rows), 39)
        changed = 0
        for x in rows:
            t = datetime.fromtimestamp(x["t"], timezone.utc)
            slot = t.replace(minute=0, second=0).astimezone(timezone(timedelta(hours=8)))
            r = {"realtime": {"skycon": x["skycon"], "dswrf": x["dswrf"]},
                 "hourly": {"dswrf": [{"datetime": slot.isoformat(), "value": x["dswrf"]}]}}
            SF.apply(r, x["lon"], x["lat"], obs=(x["frac"], NOON))
            self.assertEqual(r["realtime"]["skycon"], x["expect2"], x["id"])
            changed += x["skycon"] != x["expect2"]
        self.assertEqual(changed, 13)


def page(lang, r):
    return RS.build(lang, "深圳" if lang != "en" else "Shenzhen, CN", "CLOUDY", "深圳",
                    SZ[0], SZ[1], 8, r, None)


class ThePageGivesOnlyTheAnswer(unittest.TestCase):
    def test_clear_now_no_note_and_the_credit(self):
        r = SF.apply(result(), *SZ, obs=(0.0, NOON))
        for lang in ("en", "zh", "ja"):
            out = page(lang, copy.deepcopy(r))
            L = out.split("\n")
            now = next(ln for ln in L if ln.startswith(("now:", "当前:", "現在:")))
            self.assertTrue(now.split()[1] in ("CLEAR_DAY", "晴", "晴れ"), (lang, now))
            for leak in ("CLOUDY upstream", "彩云报阴", "上流は曇り", "upstream"):
                self.assertNotIn(leak, out)
            self.assertIn(CM.ATTRIB[lang], L)
            for ln in L:
                self.assertLessEqual(RS.cells(ln), 79, (lang, ln))
        en = page("en", copy.deepcopy(r)).split("\n")
        self.assertTrue(any(ln.startswith("now: CLEAR_DAY  24C") for ln in en))

    def test_no_mask_no_credit(self):
        r = SF.apply(result(), *SZ)
        for lang in ("en", "zh", "ja"):
            self.assertNotIn(CM.ATTRIB[lang], page(lang, copy.deepcopy(r)))


class ThePictureToo(unittest.TestCase):
    def _drawn(self, r, lang):
        try:
            from runemap import panorama as PN
        except ImportError as e:            # no Pillow/numpy here: CI has them
            self.skipTest(str(e))
        seen, real = [], PN._Page.text

        def spy(self, x, y, s, *a, **k):
            seen.append(s)
            return real(self, x, y, s, *a, **k)

        PN._Page.text = spy
        try:
            PN.render({"result": r, "server_time": 1794369600, "tzshift": 28800}, None, "Shenzhen", lang=lang)
        finally:
            PN._Page.text = real
        return seen

    def test_credit_drawn_exactly_when_the_mask_decided(self):
        self.assertIn(CM.ATTRIB["en"], self._drawn(SF.apply(result(), *SZ, obs=(0.0, NOON)), "en"))
        self.assertNotIn(CM.ATTRIB["en"], self._drawn(SF.apply(result(), *SZ), "en"))


class TheMaskReader(unittest.TestCase):
    """A synthetic full-disk frame: sparse zeros (clear), with what each test needs."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "cmsk_20261111T0430Z.u8")
        with open(self.path, "wb") as f:
            f.truncate(CM.N * CM.N)
        self.c, self.r = (int(round(v - .5)) for v in CM._px(*SZ))
        self._reset()

    def _reset(self):
        for f, mm, _ in CM._open.values():
            mm.close(); f.close()
        CM._open.clear()

    def tearDown(self):
        self._reset()
        for n in os.listdir(self.d):
            os.remove(os.path.join(self.d, n))
        os.rmdir(self.d)

    def paint(self, v, half=CM.HALF):
        with open(self.path, "r+b") as f:
            for rr in range(self.r - half, self.r + half + 1):
                f.seek(rr * CM.N + self.c - half)
                f.write(bytes([v]) * (2 * half + 1))
        self._reset()

    def frac(self, now=NOON):
        return CM.cloud_fraction(*SZ, now=now, d=self.d)

    def test_clear_cloudy_and_the_frame_time(self):
        self.assertEqual(self.frac(), (0.0, NOON))
        self.paint(3)
        self.assertEqual(self.frac()[0], 1.0)

    def test_a_frame_lasts_through_the_daily_gap(self):
        """In use up to 10 (spacing) + 28 (NOAA's lag) + 5 (the feed's look) + 10
        (no scan at 02:40/14:40 UTC) = 53 min; at 45 the sky flipped at noon.
        And not much past an hour: older than that it is not "now"."""
        self.assertEqual(self.frac(now=NOON + timedelta(minutes=53)), (0.0, NOON))
        self.assertLessEqual(CM.MAX_AGE, timedelta(minutes=90))

    def test_every_way_to_be_wrong_is_none(self):
        self.assertEqual(self.frac(now=NOON + CM.MAX_AGE + timedelta(minutes=1)), (None, None))  # stale
        self.assertEqual(CM.cloud_fraction(-40.0, 22.5, now=NOON, d=self.d), (None, None))  # off the disk
        self.assertEqual(CM.cloud_fraction(*SZ, now=NOON, d=self.d + "/nope"), (None, None))
        self.paint(255)                                                                     # invalid pixels
        self.assertEqual(self.frac(), (None, None))
        with open(self.path, "r+b") as f:                                                   # truncated frame
            f.truncate(1000)
        self._reset()
        self.assertEqual(self.frac(), (None, None))


if __name__ == "__main__":
    unittest.main()
