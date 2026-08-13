# -*- coding: utf-8 -*-
"""Every fixed attribution line fits an 80-column terminal.

Measured at the user boundary 2026-08-13 03:08: the with-figure screen for -80.7,36.0 was 38
lines with width mode 48, and the ONLY line over 79 cells was the attribution at 88 -- 1.8x
the widest thing under it. ja was already 79 and zh 75; only English overflowed.

A cell NUMBER is legitimate here, unlike the header (tests/test_title_is_two_lines.py:9
refuses one on purpose because a place name has no bound). These lines are fixed literals
with no user data in them, so a number cannot go wrongly red on a future long name.

The ruler is east_asian_width, not len(): CJK glyphs occupy two terminal columns, so len()
under-reports the Japanese and Chinese variants by 4 and 8 cells.

The literals are read out of the source with ast, NOT grep: the English line is built by
implicit string concatenation, and grepping a fragment reported 57 cells for a line that is
really 88 -- a fragment has no jurisdiction over wrapping.

Negative control: the pre-patch English wording is reassembled here and the same predicate
must reject it. Without that this test could never be red.
"""
import ast
import io
import os
import unicodedata
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = [os.path.join(HERE, "..", "scripts", n)
       for n in ("render_scene.py", "render_live.py", "render_radar.py")]
LIMIT = 79
PRE_PATCH = ("data: Caiyun Weather caiyunapp.com | rendered by runemap "
             "(github.com/eirik-rune/runemap)")


def cells(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def attribution_lines():
    out = []
    for path in SRC:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for line in node.value.split("\n"):
                    if "caiyunapp.com |" in line:
                        out.append((os.path.basename(path), node.lineno, line))
    return out


class AttributionFits80(unittest.TestCase):
    def test_the_lines_were_found_at_all(self):
        found = attribution_lines()
        self.assertGreaterEqual(len(found), 6, "an empty search is not a green: %r" % found)

    def test_every_attribution_line_fits(self):
        for name, lineno, line in attribution_lines():
            self.assertLessEqual(
                cells(line), LIMIT,
                "%s:%d is %d cells, wraps on an 80-column terminal: %r"
                % (name, lineno, cells(line), line))

    def test_the_pre_patch_wording_is_rejected(self):
        self.assertGreater(cells(PRE_PATCH), LIMIT,
                           "negative control failed: the 88-cell line now passes")

    def test_the_ruler_is_not_len(self):
        zh = "\u6570\u636e: \u5f69\u4e91\u5929\u6c14 caiyunapp.com | runemap \u6e32\u67d3"
        self.assertGreater(cells(zh), len(zh),
                           "east_asian_width ruler collapsed to len(): CJK would be undercounted")


if __name__ == "__main__":
    unittest.main()
