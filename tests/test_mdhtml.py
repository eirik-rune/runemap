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


ZH = """# Tokyo, Tokyo, JP 天气一屏
# 更新于 2026-08-14 02:23 UTC+9  (经度 139.69171, 纬度 35.6895)
当前: 小雨  24C  湿度 84%  风速 9km/h  雨强 0.14mm/h
48分钟后雨渐停，不过一小时后还有雨

雨量曲线(未来2h, 6min/格):
▄▃▄▃▃▅▄▂▁ ▃▃▂▃ ▂▃▅██
├────┼────┼────┼────┤
0   30   60   90 120min

radar: obs            obs age: 8min ok
每字符≈4km, [><]=Tokyo, Tokyo, JP
            ░░░░░░▒▒▒░▒▒▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▓▓▒▒░░░░░
       ░░    ░░░░░░░░░▒▒▒▒▒▒▒▒▓▓▓▓▓▒▒▓▒▒░░░░░░░░

图例: · 毛毛雨  ░ 小雨  ▒ 中雨  ▓ 大雨  █ 暴雨

数据: 彩云天气 caiyunapp.com | runemap 渲染
"""

JA = ZH.replace("天气一屏", "天気一覧").replace("更新于", "更新").replace(
    "当前:", "現在:").replace("雨量曲线(未来2h, 6min/格)", "雨量曲線(今後2h, 6min/枠)").replace(
    "图例:", "凡例:").replace("毛毛雨", "霧雨").replace("数据:", "データ:")


class TheParserReadsShapeNotEnglish(unittest.TestCase):
    """bob saw a title, a timestamp and nothing else -- three times running --
    while every check here passed. His page is the Chinese one. The parser
    keyed on `now:`, `rain curve`, `~4km/char` and `legend:`, so on /zh (当前:,
    雨量曲线, 每字符≈4km, 图例:) and /ja nothing matched and the document fell
    through to "prose".

    **A parser that understands one language does not fail on the others, it
    empties them** -- and the language I tested in was the one I wrote the keys
    in. So these fixtures exist, and every claim below is about structure."""

    def each(self):
        return (("zh", ZH), ("ja", JA), ("en", SCENE))

    def test_the_conditions_line_is_there_in_every_language(self):
        for lang, scene in (("zh", ZH), ("ja", JA)):
            h = MD.render(scene)
            self.assertIn("24C", h, lang)
            self.assertIn("湿度" if lang == "zh" else "湿度", h, lang)

    def test_the_forecast_sentence_is_there_in_every_language(self):
        self.assertIn("48分钟后雨渐停", MD.render(ZH))

    def test_the_map_keeps_all_its_rows_in_every_language(self):
        for lang, scene in self.each():
            h = MD.render(scene)
            rows = h.count('class="row"')
            self.assertGreater(rows, 1, lang)

    def test_the_legend_labels_are_the_documents_own(self):
        h = MD.render(ZH)
        self.assertIn("毛毛雨", h)
        self.assertNotIn("drizzle", h)
        j = MD.render(JA)
        self.assertIn("霧雨", j)
        self.assertNotIn("drizzle", j)

    def test_the_curve_heading_is_the_documents_own(self):
        self.assertIn("雨量曲线(未来2h, 6min/格)", MD.render(ZH))
        self.assertIn("雨量曲線(今後2h, 6min/枠)", MD.render(JA))
        self.assertNotIn("next 2 hours", MD.render(ZH))

    def test_the_curve_is_drawn_not_dropped(self):
        for lang, scene in (("zh", ZH), ("ja", JA)):
            self.assertIn('class="bars"', MD.render(scene), lang)


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
        """As bars now, for the same reason the map is boxes: the eighth-block
        characters are missing from some phone fonts, and where they are
        missing the curve does not degrade -- it disappears, which is what bob
        saw. Its SHAPE is what has to survive, so this checks one bar per
        bucket with heights in the source's proportions."""
        import re as _re
        self.assertIn("peaks in 30 min", self.h)
        heights = [int(x) for x in _re.findall(r"height:(\d+)%", self.h)]
        # two leading spaces in the fixture are two dry buckets, and they are
        # what puts the rest at the right time
        self.assertEqual(len(heights), len("  ▁▂▄█▆▃▁"))
        self.assertEqual(heights, [0, 0, 12, 25, 50, 100, 75, 37, 12])

    def test_a_dry_bucket_is_a_bucket(self):
        """A space in the curve is a bucket with no rain, not a character to
        skip. Dropping them turned a 20-bucket line into 6 bars crowded at the
        left, each at the wrong time -- bob saw it as the resolution dropping.
        The dropped character was not decoration, it was the value zero."""
        import re as _re
        scene = SCENE.replace("  ▁▂▄█▆▃▁", "  ▁▂ █ ▃▁")
        heights = [int(x) for x in
                   _re.findall(r"height:(\d+)%", MD.render(scene))]
        self.assertEqual(len(heights), 9)
        self.assertEqual(heights[4], 0)     # the gap between ▂ and █
        self.assertEqual(heights[6], 0)

    def test_the_curve_keeps_its_scale(self):
        """Bars with no axis look fine until you ask "0 to what?" -- and the
        first version of the axis filter removed the label line before the
        labels were read out of it, so the scale vanished silently."""
        scene = SCENE.replace("  \u2581\u2582\u2584\u2588\u2586\u2583\u2581",
                              "  \u2581\u2582\u2584\u2588\u2586\u2583\u2581\n"
                              "0   30   60   90 120min")
        h = MD.render(scene)
        axis = h.split('class="axis"')[1].split("</div>")[0]
        for t in ("0", "30", "60", "90", "120min"):
            self.assertIn(">%s<" % t, axis)

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
            if s.startswith("\u2581") or set(s) <= set("\u2581\u2582\u2583"
                                                       "\u2584\u2585\u2586"
                                                       "\u2587\u2588 "):
                continue        # bars, checked by shape in test_the_rain_curve
            frag = html.escape(" ".join(words[:3]))
            # Only GRID rows are redrawn cell-by-cell. Translating every needle
            # was wrong the moment the space became a cell glyph too: it turned
            # "CLEAR_DAY 35C" into a needle with blocks in it and the test
            # failed on a line the page renders perfectly.
            if set(s) <= set(MD.RAMP + "?><ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "):
                # Grid rows carry no text at all now -- they are boxes, so
                # their content cannot be matched as a string. What must
                # survive is the CELL COUNT, checked in TheGridIsBoxesNotText.
                continue
            self.assertIn(frag, hay, ln)

    def test_the_sources_own_legend_line_is_replaced_not_duplicated(self):
        """It stays in the document -- it is what an agent reads -- but a page
        that prints a coloured legend and then the text of the same legend is
        arguing with itself. Found by looking at the render, not by reasoning."""
        self.assertIn("legend:", SCENE)
        self.assertEqual(self.h.count("drizzle"), 1)


class TheGridIsBoxesNotText(unittest.TestCase):
    """Three font surprises in one hour ended this argument. `░ ▒ ▓` are absent
    from phone monospace faces; then U+2588 came from a CJK fallback where it is
    FULL width, so 48 columns were twice as wide as the arithmetic assumed and
    bob could see only the left half. Sizing text by calculation only works if
    you know which font will draw it, and from here you never do.

    So the grid has no glyphs: each row is a flex line and each run a box with
    `flex: n`. Widths are fractions of the container, which no font can argue
    with."""

    def test_the_grid_contains_no_text(self):
        h = MD.render(SCENE)
        # from the end of the opening tag, so the tag's own attributes are
        # not mistaken for content
        grid = h.split('class="grid"')[1].split(">", 1)[1].split("</div></div>")[0]
        import re as _re
        self.assertEqual(_re.sub(r"<[^>]*>", "", grid).strip(), "")

    def test_every_cell_is_accounted_for(self):
        """The count is the thing that must survive, since the characters no
        longer do: flex weights across a row must sum to its cell count."""
        import re as _re
        row = "??      ··░░▒▒"
        html_row = MD.paint([row])
        weights = [int(x) for x in _re.findall(r"flex:(\d+)", html_row)]
        self.assertEqual(sum(weights), len(row))

    def test_a_run_is_one_box_not_many(self):
        self.assertEqual(MD.paint(["········"]).count("<i "), 1)

    def test_the_marker_is_a_cell_of_its_own(self):
        painted = MD.paint(["··><··"])
        self.assertIn('class="me" style="flex:2"', painted)

    def test_a_row_of_clear_sky_is_still_a_row(self):
        """The bug this catches deleted most of London's map and only in calm
        weather: a row with no rain is 48 spaces, and dropping "blank" lines
        turned a 48x24 grid into 26x12. The failure was invisible on any city
        that happened to be wet -- which is every city I had looked at."""
        rows = ["·" * 8] + [" " * 8] * 3 + ["·" * 8]
        scene = ("# X weather scene\n~6km/char, [><]=X\n"
                 + "\n".join(rows) + "\n= echo motion: n/a\n")
        h = MD.render(scene)
        self.assertIn("padding-bottom:125.0%", h)   # 5 rows of 8, cells 1:2
        self.assertEqual(h.count('class="row"'), 5)

    def test_the_square_does_not_depend_on_aspect_ratio_support(self):
        """`aspect-ratio` is unsupported on Safari before 15, and where it is
        unsupported the grid collapses to zero height -- the map is not
        distorted, it is gone. Same shape as the missing glyphs: a feature the
        reader's device lacks does not announce itself."""
        import re as _re
        css = _re.sub(r"/\*.*?\*/", "", MD.render(SCENE), flags=_re.S)
        self.assertNotIn("aspect-ratio:", css)   # the property, not the comment

    def test_the_grid_states_its_aspect_ratio(self):
        """Without it the boxes have no height and the map is invisible -- and
        with the wrong one the map is stretched, which is a lie about where the
        rain is. The ratio is not cols:rows: the renderer makes km_per_row
        twice km_per_col so that a 1:2 cell renders square in a terminal, so
        the window on the ground is a SQUARE and the page must draw it as one.
        bob saw this as "界面有点儿扁"."""
        h = MD.render(SCENE)
        rows = [l for l in SCENE.split("\n")
                if l and set(l) <= set(MD.RAMP + "?><ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ")]
        cols = max(len(r) for r in rows)
        self.assertIn("padding-bottom:%.1f%%" % (100.0 * len(rows) * 2 / cols), h)


class TheLegendSpeaksTheDocumentsLanguage(unittest.TestCase):
    """A generated English legend would have captioned /tokyo/zh -- whose own
    legend line reads 图例: · 毛毛雨 ... -- in a language nobody asked for."""

    def test_the_labels_come_from_the_document(self):
        zh = SCENE.replace(
            "legend: · drizzle  ░ light  ▒ moderate  ▓ heavy  █ storm",
            "图例: · 毛毛雨  ░ 小雨  ▒ 中雨  ▓ 大雨  █ 暴雨")
        h = MD.render(zh)
        self.assertIn("毛毛雨", h)
        self.assertNotIn("drizzle", h)

    def test_a_scene_without_one_still_gets_a_legend(self):
        h = MD.render("\n".join(l for l in SCENE.split("\n")
                                if not l.startswith("legend:")))
        self.assertIn("drizzle", h)


class ASceneWithNothingInItSaysWhy(unittest.TestCase):
    """A page that is still fetching has no conditions line, no sentence, no
    curve and no grid. Rendered as empty paragraphs plus a grey footnote it
    reads as a broken site rather than as "we are looking" -- which is what bob
    saw."""

    FETCH = ("# Chiang Mai, TH weather scene\n"
             "# updated 2026-08-13 16:20 UTC+7\n"
             "radar: fetching -- first look at this sky; try again in ~30s\n"
             "data: Caiyun Weather caiyunapp.com | runemap\n")

    def test_the_reason_is_where_the_reader_is_looking(self):
        h = MD.render(self.FETCH)
        top = h.split("<main>")[1].split('class="meta"')[0]
        self.assertIn("fetching", top)

    def test_no_empty_paragraphs(self):
        h = MD.render(self.FETCH)
        self.assertNotIn('class="now"></p>', h)
        self.assertNotIn('class="say"></p>', h)


class EveryColourOnTheMapIsExplained(unittest.TestCase):
    """An unexplained colour is worse than none: a reader who cannot place it
    reads it as weather. The marker was also dark-on-yellow, which once cells
    became solid blocks painted the whole cell and looked like a hole in the
    map -- visible only by looking at the render."""

    def test_the_marker_is_named_in_the_readers_own_words(self):
        h = MD.render(SCENE)
        legend = h.split('<p class="legend">')[1].split("</p>")[0]
        self.assertIn("London", legend)
        self.assertIn('class="me"', legend)

    def test_the_marker_colour_is_not_a_rain_colour(self):
        css = MD.PAGE.split("<style>")[1]
        me = css.split(".me{background:")[1].split("}")[0]
        for cls in ("r1", "r2", "r3", "r4", "r5"):
            self.assertNotIn(me, css.split(".%s{background:" % cls)[1].split(";")[0])

    def test_unknown_cells_are_explained_only_when_present(self):
        self.assertIn("no radar here", MD.render(SCENE))
        self.assertNotIn("no radar here", MD.render(SCENE.replace("?", " ")))


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

    def test_a_run_of_identical_cells_is_one_box_not_many(self):
        """The mechanism the ratio depends on, measured directly -- a ratio
        test alone would pass on a small scene and fail in production."""
        self.assertEqual(MD.paint(["········"]).count("<i "), 1)

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
