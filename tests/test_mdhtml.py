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
            # Grid rows are drawn with one glyph per cell (see CELL_GLYPH):
            # the substitution is deliberate and stated, so the needle is
            # translated the same way rather than the map being exempted.
            frag = html.escape(" ".join(words[:3]))
            frag = "".join(MD.CELL_GLYPH.get(c, c) for c in frag)
            self.assertIn(frag, hay, ln)

    def test_the_sources_own_legend_line_is_replaced_not_duplicated(self):
        """It stays in the document -- it is what an agent reads -- but a page
        that prints a coloured legend and then the text of the same legend is
        arguing with itself. Found by looking at the render, not by reasoning."""
        self.assertIn("legend:", SCENE)
        self.assertEqual(self.h.count("drizzle"), 1)


class ItDrawsTheGridWithOneGlyph(unittest.TestCase):
    """`░ ▒ ▓` are absent from the monospace faces phones ship with, so each is
    pulled from a different fallback at that font's advance width and the grid
    goes ragged -- bob saw it before I did. One glyph cannot disagree with
    itself about width; the level is carried by colour instead."""

    def test_every_rain_cell_uses_the_same_character(self):
        h = MD.render(SCENE)
        body = h.split('class="map"')[1].split("</pre>")[0]
        for ch in "·░▒▓":
            self.assertNotIn(ch, body, ch)
        self.assertIn("\u2588", body)

    def test_the_five_levels_are_still_distinguishable(self):
        painted = MD.paint(["·░▒▓█"])
        for cls in ("r1", "r2", "r3", "r4", "r5"):
            self.assertIn('class="%s"' % cls, painted)

    def test_the_legend_shows_the_shape_the_map_draws(self):
        """A legend teaching a character the map no longer uses is worse than
        no legend: it tells the reader to look for something absent."""
        h = MD.render(SCENE)
        legend = h.split('class="legend"')[1].split("</p>")[0]
        for ch in "·░▒▓":
            self.assertNotIn(ch, legend, ch)


class ItKeepsTheDocumentsOrder(unittest.TestCase):
    """bob, 8/13: the text has the rain curve above the map and the first page
    had it below, because the template hard-coded the order. A rendering that
    reorders is editing."""

    def test_the_curve_comes_before_the_map_when_the_text_does(self):
        h = MD.render(SCENE)
        self.assertLess(h.index('class="curve"'), h.index('class="map"'))

    def test_and_after_it_when_the_text_does(self):
        lines = SCENE.split("\n")
        cut = lines.index("rain curve (next 2h): peaks in 30 min")
        moved = lines[:cut] + lines[cut + 3:] + lines[cut:cut + 3]
        h = MD.render("\n".join(moved))
        self.assertGreater(h.index('class="curve"'), h.index('class="map"'))


def full_scene():
    """A scene the size production actually serves: a full 48x24 grid.

    The小 fixture above is a few hundred bytes, where the fixed stylesheet
    dominates and the ratio says more about the CSS than about the rendering.
    Measuring the promise on it would have been measuring the wrong thing --
    and the first version of this file did exactly that, then failed when the
    stylesheet grew by twenty lines. The threshold is not the part to loosen.
    """
    import math
    # Weather is spatially correlated -- rain arrives in bands, so a row is
    # runs, not noise. A uniformly random grid gives every cell its own span
    # and measures an input production never serves (7.6x when I tried it);
    # this is a band crossing the window, which is what the runs are for.
    ramp = " ·░▒▓█"
    rows = []
    for r in range(24):
        row = ""
        for c in range(48):
            d = abs(c - (12 + 1.2 * r)) / 6.0
            row += ramp[max(0, min(5, 5 - int(d)))]
        rows.append(row)
    head = SCENE.split("????")[0]
    tail = "\n".join(SCENE.split("\n")[-4:])
    return head + "\n".join(rows) + "\n" + tail


class ItStaysSmall(unittest.TestCase):
    """25 KB for a 1.8 KB scene is the 'giant HTML' this is meant not to be."""

    def test_the_page_is_a_small_multiple_of_the_text(self):
        text = full_scene()
        ratio = len(MD.render(text).encode()) / float(len(text.encode()))
        self.assertLess(ratio, MD.MAX_RATIO, "ratio %.1fx" % ratio)

    def test_even_an_unrealistically_noisy_grid_has_a_ceiling(self):
        """The runs are what keep the page small, so a grid with no runs at all
        is the worst case. It is not an input we serve, but it must not be
        unbounded -- a promise that only holds on friendly data is not one."""
        import random
        rnd = random.Random(7)
        noise = SCENE.replace("????????????????????????",
                              "".join(rnd.choice(" ·░▒▓█") for _ in range(48)))
        ratio = len(MD.render(noise).encode()) / float(len(noise.encode()))
        self.assertLess(ratio, 12.0, "ratio %.1fx" % ratio)

    def test_the_stylesheet_is_a_fixed_cost_and_a_small_one(self):
        """The part that does not scale with the scene, stated outright: it is
        why a tiny scene has a large ratio and a real one does not."""
        h = MD.render(SCENE)
        css = h.split("<style>")[1].split("</style>")[0]
        self.assertLess(len(css.encode()), 3000, len(css.encode()))

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
