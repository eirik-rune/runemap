#!/usr/bin/env python3
"""Draw echorune.net's favicon from the palette the product already uses.

  python3 scripts/make_favicon.py [outdir]      # default: static/

Why this exists: on 2026-08-22 bob probed the site from a plane and reported
that `/favicon.ico` was one of his targets. It was answering **404 with the
entire 2,893-byte help page** -- so every browser that ever opened the site
paid for that, got no icon, and reached the Python service to be told a town
called "favicon.ico" does not exist.

Two decisions worth stating, because both could reasonably have gone the
other way:

**It is not my avatar.** The Luo Shu dot square in `avatar.py` is 洛书's
identity, not echorune's, and conflating them would put a person's mark on a
company's product. Rendered down it also fails on its own terms -- I looked
at it at 16, 32, 48 and 64 pixels, and below 48 the nine dot groups collapse
into noise.

**The colours are read out of `mdhtml.py`, not retyped.** They are already
decided and already on the page: five rain intensities plus the marker for
where the reader is. A favicon that invents a sixth palette is a second
source of truth for what this product looks like, and the two would drift.
So this file parses them, and fails loudly if the names it expects are gone
rather than falling back to something plausible.

The mark is the product: a radar cell grid with a band of rain crossing it
and the reader's marker underneath. That is literally what `curl
echorune.net/<city>` prints, and unlike a dot diagram it survives 16 pixels.
"""
import os
import re
import sys

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))

#: The classes whose colours make up the intensity ramp, weakest first, plus
#: the reader's own position. Read from the stylesheet rather than copied.
_WANT = ("r1", "r2", "r3", "r4", "r5", "me")


def palette(path=None):
    """{class: '#rrggbb'} pulled out of the served stylesheet.

    Raises if any expected class is missing. A favicon generator that quietly
    substituted a default would produce a perfectly good-looking icon in a
    palette the site no longer uses, and nothing downstream would notice --
    the shape this repository keeps paying for.
    """
    src = open(path or os.path.join(_HERE, "mdhtml.py"), encoding="utf-8").read()
    out = {}
    for name in _WANT:
        m = re.search(r"\.%s\{background:(#[0-9a-fA-F]{6})\}" % name, src)
        if not m:
            raise SystemExit(
                "PALETTE-MISSING: could not find .%s in mdhtml.py. The site's "
                "colours have moved or been renamed; fix this parser rather "
                "than letting the icon drift away from the page." % name)
        out[name] = m.group(1)
    return out


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


#: 8x8 cells. 0 = no echo. 1..5 = the ramp. 9 = the reader's marker.
#: A band sweeping from lower-left to upper-right with the heaviest core in
#: the middle -- the shape a real front makes, and the shape the character
#: map draws most often.
GRID = [
    [0, 0, 0, 0, 1, 2, 2, 1],
    [0, 0, 0, 1, 2, 3, 3, 2],
    [0, 0, 1, 2, 3, 4, 3, 2],
    [0, 1, 2, 3, 4, 5, 3, 1],
    [1, 2, 3, 4, 5, 4, 2, 0],
    [2, 3, 4, 3, 9, 2, 1, 0],
    [1, 2, 3, 2, 1, 1, 0, 0],
    [0, 1, 2, 1, 0, 0, 0, 0],
]


def draw(px=64, pal=None):
    """One square icon, `px` on a side, transparent where there is no echo.

    Transparent rather than white: the browser tab is dark for half the
    readers, and the page itself already ships a dark theme. A white plate
    would be a light-mode assumption baked into an image.
    """
    pal = pal or palette()
    ramp = [None] + [_rgb(pal["r%d" % i]) for i in (1, 2, 3, 4, 5)]
    me = _rgb(pal["me"])
    n = len(GRID)
    # 16px is the size a browser tab actually uses, and there a cell is
    # exactly 2 pixels. Drawing large and resampling smeared them into a
    # coloured blur -- I only saw that because I rendered the sizes and
    # looked at them instead of assuming a downscale would be fine, which is
    # the same check that ruled out reusing the avatar. So: when the size
    # divides evenly, draw at exactly that scale and never resample.
    cell, rest = divmod(px, n)
    if cell >= 1 and rest == 0:
        img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for y, row in enumerate(GRID):
            for x, v in enumerate(row):
                if v == 0:
                    continue
                colour = me if v == 9 else ramp[v]
                d.rectangle([x * cell, y * cell, (x + 1) * cell - 1,
                             (y + 1) * cell - 1], fill=colour + (255,))
        return img
    ss = 32
    img = Image.new("RGBA", (n * ss, n * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y, row in enumerate(GRID):
        for x, v in enumerate(row):
            if v == 0:
                continue
            colour = me if v == 9 else ramp[v]
            d.rectangle([x * ss, y * ss, (x + 1) * ss - 1,
                         (y + 1) * ss - 1], fill=colour + (255,))
    return img.resize((px, px), Image.LANCZOS)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "..", "static")
    os.makedirs(out, exist_ok=True)
    pal = palette()
    # 16 and 32 only. Adding 48 measured +1,394 bytes for a size a browser
    # tab never asks for, on a product whose whole argument is that it is
    # small. 16+32 is 1,024 bytes.
    sizes = (16, 32)
    imgs = [draw(s, pal) for s in sizes]
    ico = os.path.join(out, "favicon.ico")
    imgs[-1].save(ico, format="ICO", sizes=[(s, s) for s in sizes])
    png = os.path.join(out, "favicon-180.png")
    draw(180, pal).save(png, format="PNG", optimize=True)
    print("palette from mdhtml.py: %s" % pal)
    for p in (ico, png):
        print("%-40s %5d bytes" % (p, os.path.getsize(p)))


if __name__ == "__main__":
    main()
