"""The SLOW-GET log line must never carry the upstream token.

2026-11-14: render_scene._get logged url[-46:]. On a radar list url
(...token=<16 chars>&lon=96.0&lat=32.0) those 46 characters include the whole
token: 125 journal lines in 7.5 days. The new /radar.json probes whole-degree
lattice points, whose short coordinates made it more likely, and one of those
lines was printed into a terminal before anyone noticed.
"""
import io
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import render_scene as R

TOKEN = "TOKENabc12345678"
LIST = "https://api.caiyunapp.com/v1/radar/images?token=%s&lon=96.0&lat=32.0" % TOKEN
WEATHER = ("https://api.caiyunapp.com/v2.6/%s/103.8,36.1/weather?hourlysteps=24"
           "&lang=zh_CN&unit=metric:v2" % TOKEN)


class LogUrlHasNoCredentials(unittest.TestCase):

    def test_query_token(self):
        out = R._log_url(LIST)
        self.assertNotIn(TOKEN, out)
        self.assertIn("token=<redacted>", out)
        self.assertTrue(out.endswith("&lon=96.0&lat=32.0"), out)

    def test_path_token(self):
        out = R._log_url(WEATHER)
        self.assertNotIn(TOKEN, out)
        self.assertIn("/v2.6/<redacted>/103.8,36.1/weather", out)

    def test_a_url_without_credentials_is_unchanged(self):
        u = "https://meteorology.caiyuncdn.com/radar/abc/def.png"
        self.assertEqual(R._log_url(u), u)


class TheSlowGetLineItself(unittest.TestCase):
    """Through the fetch function itself, so a future edit of the log line is
    held to it too. Not R._get: once any test imports scene_at that name is the
    cache layer, which logs nothing -- found when these passed alone and failed
    in the suite, caught by the "SLOW-GET was written" check."""

    def _slow(self, url):
        clock = iter([1000.0, 1002.5])
        err = io.StringIO()
        with mock.patch.object(R.net_budget, "get_hedged", return_value=b"{}"), \
             mock.patch.object(R.time, "time", side_effect=lambda: next(clock)), \
             mock.patch.object(sys, "stderr", err):
            R._get_uncached(url)
        return err.getvalue()

    def test_slow_list_fetch_logs_without_the_token(self):
        out = self._slow(LIST)
        self.assertIn("SLOW-GET", out)          # the line was really written
        self.assertNotIn(TOKEN, out)

    def test_slow_weather_fetch_logs_without_the_token(self):
        out = self._slow(WEATHER)
        self.assertIn("SLOW-GET", out)
        self.assertNotIn(TOKEN, out)


if __name__ == "__main__":
    unittest.main()
