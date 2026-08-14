"""HTML must present the blocks in the order the text document does.

bob, 2026-08-14: "为什么现在dev的HTML和txt还是不一致，雷达图的位置还是不一致".

The map itself was never wrong -- same 24x48 grid, marker at the same cell, 0 of
1150 cells differing across twelve cities. What was wrong was WHERE it sat: the
parser recorded document order and used it for map-vs-curve, but every line
classified `meta` was appended at the end regardless. So `radar: obs / obs age`
and `每字符≈4km, [><]=你的位置` -- the map's CAPTION -- crossed to the far side
of the picture, and a reader had to scroll past the map to learn what a cell was
worth.

Two buckets (before/after the map) was the first attempt and was not enough: it
hoisted `radar:` above the rain curve, which the text prints first. Only a
sequence expresses document order, so meta lines are collected into runs, each
taking its own slot.

Deliberate residual: the coloured legend stays welded under the map, while the
text prints 图例 one line further down, after the motion line. The coloured
legend REPLACES the dropped `图例:` line and belongs against the picture it
explains. Recorded here so the difference is a decision and not a leak.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import mdhtml as M      # noqa: E402

DOC = """# Somewhere weather scene
# updated 2026-08-14 12:00 UTC+0  (lon 1.00, lat 2.00)
now: CLOUDY  20C  humidity 50%  wind 5km/h  precip 0.00mm/h
rain starts in an hour
rain curve(next 2h, 6min/cell):
  ▁▁▁▄█
  0   30   60   90 120min
radar: predict 12:05  obs age: 5min ok
~4km/char, [><]=Somewhere
   ░░░  ▒▒
   ░><░  ░
← west ~9 km/h   echo motion, upstream forecast
legend: · drizzle  ░ light
data: Caiyun Weather caiyunapp.com | runemap
"""


def positions(html_text, needles):
    return {n: html_text.find(n) for n in needles}


class TheCaptionStaysOnTheSameSideOfTheMap(unittest.TestCase):

    def setUp(self):
        self.html = M.render(DOC)

    def test_the_scale_and_radar_lines_come_before_the_map(self):
        """They describe the picture. Below it, the reader meets the map with
        no idea what a cell is worth."""
        p = positions(self.html, ['class="map"', "obs age", "4km/char"])
        self.assertLess(p["obs age"], p['class="map"'],
                        "radar/obs-age caption fell below the map")
        self.assertLess(p["4km/char"], p['class="map"'],
                        "the scale line fell below the map")

    def test_the_curve_still_comes_before_the_radar_line(self):
        """The regression the two-bucket fix introduced: hoisting all meta
        above the map put `radar:` in front of the curve, which the text
        prints first."""
        p = positions(self.html, ['class="curve"', "obs age"])
        self.assertLess(p['class="curve"'], p["obs age"])

    def test_the_provenance_stays_after_the_map(self):
        """Order is not 'everything moves up' -- lines below the map in the
        document stay below it."""
        p = positions(self.html, ['class="map"', "echo motion", "Caiyun"])
        self.assertGreater(p["echo motion"], p['class="map"'])
        self.assertGreater(p["Caiyun"], p['class="map"'])

    def test_every_meta_line_survives_somewhere(self):
        """Reordering must not be a way of losing lines."""
        for needle in ("obs age", "4km/char", "echo motion", "Caiyun"):
            self.assertIn(needle, self.html, "%s vanished" % needle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
