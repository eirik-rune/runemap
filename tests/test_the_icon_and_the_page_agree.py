"""The favicon must stay the same product as the page.

2026-08-22. bob probed the site from a plane and `/favicon.ico` was one of his
eleven targets. It was answering **404 with the entire 2,893-byte help page**:
the request reached the Python service, which looked for a town called
"favicon.ico", failed, and served usage instructions to a browser's automatic
icon fetch. No icon, every visit, for three weeks.

The icon is drawn from the palette in `mdhtml.py` rather than a copy of it,
so this test guards the one failure that would otherwise be silent: somebody
changes the rain colours on the page, the committed icon keeps the old ones,
and both look completely reasonable on their own. Nothing renders wrong,
nothing errors, and the tab quietly shows last month's product.

It also pins the two decisions that a later reader might undo by tidying:

* **16 and 32 only.** Adding 48 measured +1,394 bytes for a size a browser tab
  never requests, on a product whose entire argument is that it is small.
* **Transparent background.** Half the readers have a dark tab strip, and the
  page itself ships a dark theme; a white plate would bake a light-mode
  assumption into an image that cannot adapt.

What is deliberately NOT asserted: the exact bytes of the committed .ico.
Pillow's encoder output can change between versions, so a byte comparison
would fail for a reason that has nothing to do with this product, and a test
that cries wolf gets deleted. The palette is the thing that carries meaning.
"""
import os
import struct
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

ICO = os.path.join(_ROOT, "static", "favicon.ico")


def _skip_if_no_pillow():
    try:
        import PIL  # noqa: F401
        return None
    except ImportError:
        return "Pillow is not installed"


class TheIconIsShipped(unittest.TestCase):

    def test_the_file_exists_and_is_small(self):
        """It is committed rather than generated at deploy time, because the
        deploy copies a tree and does not run build steps -- a generated file
        missing from the tree is a 404 that only appears in production."""
        self.assertTrue(os.path.exists(ICO), "static/favicon.ico is missing")
        self.assertLess(os.path.getsize(ICO), 2048,
                        "the icon has grown past the point where it is "
                        "cheaper than the 404 it replaced")

    def test_it_holds_the_two_sizes_a_tab_asks_for(self):
        """Parsed from the ICO directory header, which is six bytes of count
        followed by 16-byte entries whose first two bytes are width and
        height (0 meaning 256). No Pillow needed to read it."""
        with open(ICO, "rb") as f:
            head = f.read(6)
            reserved, kind, count = struct.unpack("<HHH", head)
            self.assertEqual((reserved, kind), (0, 1), "not an ICO file")
            sizes = set()
            for _ in range(count):
                e = f.read(16)
                w, h = e[0] or 256, e[1] or 256
                sizes.add((w, h))
        self.assertEqual(sizes, {(16, 16), (32, 32)}, sizes)


class TheIconMatchesThePage(unittest.TestCase):

    @unittest.skipIf(_skip_if_no_pillow(), "Pillow is not installed")
    def test_every_colour_in_the_icon_is_a_colour_on_the_page(self):
        """The drift guard. If the rain palette moves in mdhtml.py and the
        committed icon is not rebuilt, this is the only thing that notices --
        both artefacts stay individually plausible."""
        from PIL import Image
        import make_favicon as M
        allowed = {M._rgb(v) for v in M.palette().values()}
        img = Image.open(ICO)
        img.size = (32, 32)
        img = img.convert("RGBA")
        seen = set()
        for r, g, b, a in img.getdata():
            if a > 0:
                seen.add((r, g, b))
        self.assertTrue(seen, "the icon is entirely transparent")
        stray = seen - allowed
        self.assertFalse(stray, "colours in the icon that are not on the "
                                "page: %s -- rerun scripts/make_favicon.py"
                                % sorted(stray))

    @unittest.skipIf(_skip_if_no_pillow(), "Pillow is not installed")
    def test_the_generator_refuses_a_stylesheet_it_cannot_read(self):
        """Fired: a generator that fell back to a default palette would draw a
        perfectly good icon in colours the site no longer uses."""
        import tempfile
        import make_favicon as M
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("nothing here resembles a palette\n")
            path = f.name
        try:
            with self.assertRaises(SystemExit) as cm:
                M.palette(path)
            self.assertIn("PALETTE-MISSING", str(cm.exception))
        finally:
            os.unlink(path)

    @unittest.skipIf(_skip_if_no_pillow(), "Pillow is not installed")
    def test_it_is_transparent_where_there_is_no_rain(self):
        """A white plate would be invisible against a light tab strip and a
        bright block against a dark one."""
        from PIL import Image
        img = Image.open(ICO)
        img.size = (32, 32)
        img = img.convert("RGBA")
        self.assertEqual(img.getpixel((0, 31))[3], 0,
                         "the empty corner should be transparent")

    @unittest.skipIf(_skip_if_no_pillow(), "Pillow is not installed")
    def test_small_sizes_are_drawn_not_resampled(self):
        """At 16px a cell is exactly two pixels, and resampling smeared the
        cells into a coloured blur -- caught by rendering the sizes and
        looking at them. Every visible pixel must be exactly a palette
        colour; an interpolated one would not be."""
        import make_favicon as M
        allowed = {M._rgb(v) for v in M.palette().values()}
        img = M.draw(16).convert("RGBA")
        blended = [(r, g, b) for r, g, b, a in img.getdata()
                   if a > 0 and (r, g, b) not in allowed]
        self.assertFalse(blended[:5], "%d interpolated pixels at 16px"
                         % len(blended))


class ThePagePointsAtIt(unittest.TestCase):

    def _head(self):
        return open(os.path.join(_ROOT, "scripts", "mdhtml.py"),
                    encoding="utf-8").read()

    def test_the_html_declares_the_icon(self):
        """Browsers guess /favicon.ico, but nothing guesses the touch icon,
        and a declared link is what lets the path move later without every
        cached tab breaking."""
        src = self._head()
        self.assertIn('rel="icon"', src)
        self.assertIn("/favicon.ico", src)
        self.assertIn("/favicon-180.png", src)


if __name__ == "__main__":
    unittest.main()
