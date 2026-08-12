# -*- coding: utf-8 -*-
"""The header is two lines: the place on one, the metadata on the next.

Asked for by bob 2026-08-12 12:00 ("第一行有点儿太长了"). Measured before the
change: the single header line was 130 cells wide for Chiang Mai, against a body
whose width mode is 48 -- 2.7x the widest thing under it. A rule that lives only
in a commit message is a comment, so this is the guard.

The predicate is deliberately about SHAPE, not about a width number: the place
name has no bound (a Thai tambon plus province plus country is long and that is
the truth), so asserting "<= N cells" would encode a wrong requirement and go
red on some future long name. What must hold is that the timestamp/coordinates
live on their own line.

Negative control: the pre-patch one-line form is reassembled here and the same
predicate must reject it. Without that, the test could never be red.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import render_scene as RS  # noqa: E402

WX = {"realtime": {"skycon": "PARTLY_CLOUDY_NIGHT", "temperature": 28.0,
                   "humidity": 0.93, "wind": {"speed": 5.0},
                   "precipitation": {"local": {"intensity": 0.0}}},
      "minutely": {"precipitation_2h": [0.0] * 120, "description": ""},
      "forecast_keypoint": ""}
NAME = "Chiang Mai, Amphoe Mueang Chiang Mai, Chiang Mai, TH"
ZH = "Jingshan, Beijing, Beijing, CN"


def header(lang):
    out = RS.build(lang, NAME, "PARTLY_CLOUDY_NIGHT", ZH,
                   98.98468, 18.79038, 7, WX, None)
    lines = out.split("\n") if isinstance(out, str) else list(out)
    return lines


def split_ok(lines):
    """True iff the place line carries no coordinates and line 2 does."""
    return ("(" not in lines[0]
            and lines[0].startswith("#")
            and lines[1].startswith("#")
            and "(" in lines[1])


class TitleIsTwoLines(unittest.TestCase):

    def test_every_language_splits(self):
        for lang in ("en", "ja", "zh"):
            lines = header(lang)
            self.assertTrue(split_ok(lines),
                            "%s: %r / %r" % (lang, lines[0], lines[1]))

    def test_negative_control_one_line_form_is_rejected(self):
        for lang in ("en", "ja", "zh"):
            lines = header(lang)
            merged = [lines[0] + "  " + lines[1][2:]] + lines[2:]
            self.assertFalse(split_ok(merged),
                             "%s: the predicate accepts the old one-line form, "
                             "so it can never go red: %r" % (lang, merged[0]))

    def test_fetching_state_has_the_same_shape(self):
        # build_fetching already put the place alone on line 1; the two states
        # must not have different header shapes.
        for lang in ("en", "ja", "zh"):
            first = RS.build_fetching(lang, NAME).split("\n")[0]
            self.assertTrue(first.startswith("#"))
            self.assertNotIn("(", first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
