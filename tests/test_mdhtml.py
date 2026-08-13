"""The HTML rendering: one document, small page, agents untouched.

The point of these is not that the markup is pretty. It is that the three
promises made to bob on 8/13 are measured rather than asserted: the bytes an
agent gets are unchanged, the page a browser gets is a small multiple of them,
and nothing is added that the text did not already say.
"""
import html
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import mdhtml as MD    # noqa: E402

SCENE = """# London, Greater London, England, GB weather scene
# updated 2026-08-13 16:30 UTC+1  (lon -0.12574, lat 51.50853)
now: CLEAR_DAY  35C  humidity 15%  wind 9km/h  precip 0.00mm/h
After one hour the rain stops. Take an umbrella if you leave before then

rain curve (next 2h): peaks in 30 min
  ▁▂▄█▆▃▁

radar: predict 16:30  obs age: 15min ok
~6km/char, [><]=London
????????????????????????
??      ····░░▒▒
??      ··░░▒▓█  ><
= echo motion: NE 21km/h
legend: · drizzle  ░ light  ▒ moderate  ▓ heavy  █ storm

data: Caiyun Weather caiyunapp.com | runemap
"""


class ItCarriesTheWholeDocument(unittest.TestCase):
    """The first prototype silently dropped the forecast sentence and the rain
    curve: it matched on 'Over the next', and the wording that day was 'After
    one hour'. The filter decided the shape of the blind spot, and what fell in
    it was the product. So every part is pinned by name."""

    def setUp(self):
        self.h = MD.render(SCENE)

    def test_the_forecast_sentence_survives_a_change_of_wording(self):
        self.assertIn("After one hour the rain stops", self.h)

    def test_the_rain_curve_survives(self):
        self.assertIn("▁▂▄█▆▃▁", self.h)
        self.assertIn("peaks in 30 min", self.h)

    def test_the_conditions_line_survives(self):
        self.assertIn("CLEAR_DAY", self.h)

    def test_the_provenance_lines_survive(self):
        for frag in ("Caiyun Weather", "obs age: 15min", "echo motion: NE 21km/h"):
            self.assertIn(frag, self.h)

    def test_the_marker_is_still_findable(self):
        self.assertIn('class="me"', self.h)

    def test_no_line_of_the_source_is_dropped_without_being_named(self):
        """A line that matches nothing at all would vanish in silence.

        The first version of this test matched each line's first word, and
        passed on the legend line for the wrong reason: `legend` also occurs in
        this page's own CSS class name. A check that can be satisfied by
        markup it is not looking at is not a check. So it matches on content
        that only the source line carries, and the one line deliberately
        dropped is named here rather than allowed to fall through."""
        drop = ("legend:",)     # rendered as a coloured legend instead
        # Compare against the page's TEXT, not its markup: grid rows are cut
        # into coloured spans, so a raw fragment would never match there and
        # the map -- the part most worth protecting -- would be exempt from
        # this check for a reason that has nothing to do with the map.
        hay = " ".join(re.sub(r"<[^>]+>", "", self.h).split())
        for ln in SCENE.split("\n"):
            s = ln.strip()
            if not s or s.startswith("#") or s.startswith(drop):
                continue
            # `now:` and `rain curve (next 2h):` are labels the page turns into
            # styling and a heading. What they label still has to be there.
            if s.startswith("rain curve"):
                s = s.split(":", 1)[1].strip()
            words = s.split()
            if words[0] == "now:":
                words = words[1:]
            frag = html.escape(" ".join(words[:3]))
            self.assertIn(frag, hay, ln)

    def test_the_sources_own_legend_line_is_replaced_not_duplicated(self):
        """It stays in the document -- it is what an agent reads -- but a page
        that prints a coloured legend and then the text of the same legend is
        arguing with itself. Found by looking at the render, not by reasoning."""
        self.assertIn("legend:", SCENE)
        self.assertEqual(self.h.count("drizzle"), 1)


class ItStaysSmall(unittest.TestCase):
    """25 KB for a 1.8 KB scene is the 'giant HTML' this is meant not to be."""

    def test_the_page_is_a_small_multiple_of_the_text(self):
        ratio = len(MD.render(SCENE).encode()) / float(len(SCENE.encode()))
        self.assertLess(ratio, MD.MAX_RATIO, "ratio %.1fx" % ratio)

    def test_a_run_of_identical_cells_is_one_span_not_many(self):
        """The mechanism the ratio depends on, measured directly -- a ratio
        test alone would pass on a small scene and fail in production."""
        self.assertEqual(MD.paint(["········"]).count("<span"), 1)

    def test_nothing_is_fetched_from_anywhere(self):
        """ONE request is the product. An external font or stylesheet would
        also be a third party learning who read the page."""
        h = MD.render(SCENE)
        for bad in ("http://", "https://cdn", "<script", "<img", "@import", "url("):
            self.assertNotIn(bad, h.replace("caiyunapp.com", ""))


class ItRendersOnlyForClientsThatAskedForIt(unittest.TestCase):
    """curl and every agent library send `*/*` or nothing. If the wildcard
    counted, shipping this would have changed what every existing caller
    receives -- which is the one thing it must not do."""

    def test_a_browser_gets_html(self):
        self.assertTrue(MD.wants_html(
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"))

    def test_curl_does_not(self):
        self.assertFalse(MD.wants_html("*/*"))

    def test_a_client_that_said_nothing_does_not(self):
        self.assertFalse(MD.wants_html(None))
        self.assertFalse(MD.wants_html(""))

    def test_an_explicit_preference_for_plain_text_wins(self):
        self.assertFalse(MD.wants_html("text/plain,text/html;q=0.5"))

    def test_html_refused_outright_is_not_served(self):
        self.assertFalse(MD.wants_html("text/html;q=0,*/*"))


class UnknownSkyIsNotDrawnAsWeather(unittest.TestCase):
    def test_the_question_mark_has_its_own_class(self):
        """'not looked at' and 'looked, no rain' must not share a shape, and
        '?' must not borrow a rain colour on the way through."""
        self.assertEqual(MD.CLASS["?"], "rq")
        self.assertNotIn(MD.CLASS["?"], [MD.CLASS[c] for c in MD.RAMP])


if __name__ == "__main__":
    unittest.main(verbosity=2)
