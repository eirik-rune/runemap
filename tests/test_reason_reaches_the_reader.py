# -*- coding: utf-8 -*-
"""The reason a map is missing must reach the PERSON, not only an operator.

`X-Radar-Why` shipped 2026-08-12 and answers "why is there no map" -- in a
response header. Measured the same day: of 105 first-visit product requests
from strangers, 9 got no map, and all 9 landed on the zero-parameter entry with
a real browser UA. A header is read by whoever runs the service; those 9 people
read the body, and the body said only that we were "looking".

What is asserted here:
  1. the clause appears in the body for a reason we chose to explain;
  2. it is a sentence about US, never a verdict about the world (bob 8/3 14:35:
     "nobody is going to believe there is no radar just because you say so");
  3. NEGATIVE CONTROL -- a reason we have never seen produces no clause at all,
     and a request that got a map produces none either. A line that appears on
     the healthy path would train its reader to skip it (bob 8/2 08:56: hedging
     every line "is not honesty, it is stupid");
  4. reading the reason from the body does not consume it, so serve.py can
     still pop it for the header. Two readers, one owner of the clearing.

No sockets, no disk: the radar entry points are stubbed, as in
test_fetching_reason.py.
"""
import os
import sys
import threading
import time
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
NAME = "Almaty, Almaty, KZ"


class ReasonReachesTheReader(unittest.TestCase):
    def setUp(self):
        self._save = {k: getattr(RS, k) for k in ("_radar_render", "_radar_start", "_mark")}
        RS._mark = lambda c: c
        RS._radar_start = lambda *a, **k: threading.Event()
        RS._radar_render = lambda *a, **k: None
        RS.note_reason(None)

    def tearDown(self):
        for k, v in self._save.items():
            setattr(RS, k, v)
        RS.note_reason(None)

    def body(self, lang="en"):
        return RS.build(lang, NAME, "PARTLY_CLOUDY_NIGHT", NAME,
                        76.9, 43.2, 6, WX, None,
                        radar_state=RS.STATE_FETCHING)

    def radar_line(self, lang="en"):
        for l in self.body(lang).split("\n"):
            if l.startswith("radar: "):
                return l
        self.fail("no radar line in body")

    def why_line(self, lang="en"):
        """The reason lives on its OWN line (see WhyLineFitsEightyColumns)."""
        for l in self.body(lang).split("\n"):
            if l.startswith("radar-why: "):
                return l
        return ""

    def test_named_reason_reaches_the_body(self):
        RS.note_reason("sky-empty")
        self.assertIn("upstream listed no frames", self.why_line())

    def test_sentence_is_about_us_not_about_the_world(self):
        RS.note_reason("sky-empty")
        line = self.why_line().lower()
        # the forbidden shape is a claim that the world lacks radar
        for verdict in ("no radar here", "there is no radar",
                        "this sky has no radar", "not covered by radar"):
            self.assertNotIn(verdict, line)

    def test_unknown_reason_says_nothing(self):
        RS.note_reason("some-word-nobody-has-defined")
        self.assertEqual(self.radar_line(), self.plain_line())
        self.assertEqual(self.why_line(), "", "an unexplained word must stay silent")

    def test_no_reason_says_nothing(self):
        RS.note_reason(None)
        self.assertEqual(self.radar_line(), self.plain_line())
        self.assertEqual(self.why_line(), "")

    def plain_line(self):
        return ("radar: fetching -- no radar frames for this sky yet; "
                "weather above is live")

    def test_a_drawn_map_carries_no_clause(self):
        # `rb` (not radar_state) is what decides whether a map was drawn --
        # my first version of this test passed rb=None with STATE_OK and went
        # red, correctly: the code took the not-drawn branch because there was
        # nothing to draw. The fixture was lying, not the product.
        RS.note_reason("sky-empty")
        rb = ("MAP", 6.0, time.time(), None, None)   # rb[2] is an epoch, not a label
        body = RS.build("en", NAME, "PARTLY_CLOUDY_NIGHT", NAME,
                        76.9, 43.2, 6, WX, rb, radar_state=RS.STATE_OK)
        self.assertNotIn("upstream listed no frames", body)
        self.assertIn("MAP", body)

    def test_body_peeks_so_the_header_can_still_pop(self):
        RS.note_reason("sky-empty")
        self.why_line()
        self.assertEqual(RS.last_reason(), "sky-empty",
                         "body consumed the reason; X-Radar-Why would go blank")
        self.assertIsNone(RS.last_reason())

    def test_every_explained_reason_has_all_three_languages(self):
        for why, langs in RS._FETCH_CLAUSE.items():
            for lang in ("en", "zh", "ja"):
                self.assertTrue(langs.get(lang), "%s missing %s" % (why, lang))


if __name__ == "__main__":
    unittest.main()


class WhyLineFitsEightyColumns(unittest.TestCase):
    """Every reason line must fit an 80-column terminal.

    Eirik measured the first version of this change: appending the clause to the
    radar line pushed all 9 real (reason, language) combinations past 80 cells --
    the ja base is 79 by itself, so anything appended had to wrap. A wrapped line
    is not a line an agent can grep, and this text exists for the reader who got
    no map. So the reason lives on its own line, and this guard holds it there.

    The combinations are DERIVED from _FETCH_CLAUSE and the language branches,
    never hand-enumerated: a hand-written list silently omits the fourth reason
    on the day someone adds one. The ruler is east_asian_width, not len() --
    len() under-counts every CJK cell by half (runemap paid for that lesson in
    9d68324).
    """
    LIMIT = 79

    @staticmethod
    def cells(s):
        import unicodedata
        return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
                   for c in s)

    def test_every_reason_line_fits(self):
        wide = []
        for why in RS._FETCH_CLAUSE:
            for lang in ("en", "zh", "ja"):
                line = "radar-why: " + RS.fetching_clause(why, lang)
                n = self.cells(line)
                if n > self.LIMIT:
                    wide.append("%s/%s=%d" % (why, lang, n))
        self.assertEqual(wide, [], "over %d cells: %s" % (self.LIMIT, wide))

    def test_the_ruler_is_not_len(self):
        # negative control: if cells() ever collapses to len(), this catches it
        self.assertEqual(self.cells("上游"), 4)

    def test_the_guard_can_go_red(self):
        # a clause that WOULD overflow must be rejected by the same predicate
        self.assertGreater(self.cells("radar-why: " + "x" * 80), self.LIMIT)
