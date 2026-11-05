"""Three phone pictures side by side, for the top of the README.

    python3 tools/readme_hero.py OUT.png a.png:"English · São Paulo" b.png:"中文 · 武汉" ...

Each input is a picture exactly as the service returns it (/<place>.png). The
top of each is kept -- the title, the "now" card, the one-line forecast and the
radar card -- cut at the same height for all of them, so the row reads as
phones showing the first screen. Nothing on the screens is redrawn; the frame,
shadow and caption are the only things added.

Background is transparent and the caption is a mid grey, so the same file reads
on GitHub's light and dark themes.
"""
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"   # face 2: Simplified Chinese
CAPTION = (139, 148, 158, 255)      # GitHub's muted grey; legible on #fff and #0d1117
BEZEL = (24, 26, 31, 255)
RIM = (84, 92, 104, 255)            # 2 px edge so the dark frame still shows on a dark page
OUT_W = 1800


def radar_card_bottom(im):
    """Row where the third card (the radar card) ends: cards are the runs of rows
    whose pixel at x=60 differs from the page background."""
    a = np.asarray(im.convert("RGB")).astype(int)
    bg = a[8, 8]
    col = np.abs(a[:, 60] - bg).sum(axis=1) > 6
    runs, start = [], None
    for y, on in enumerate(col):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start > 40:
                runs.append((start, y))
            start = None
    if len(runs) < 3:
        raise SystemExit("could not find the radar card (%d card runs)" % len(runs))
    return runs[2][1]


def phone(screen, radius=64, bezel=26):
    w, h = screen.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    W, H = w + 2 * bezel, h + 2 * bezel
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=radius + bezel, fill=RIM)
    d.rounded_rectangle((2, 2, W - 3, H - 3), radius=radius + bezel - 2, fill=BEZEL)
    body.paste(screen.convert("RGBA"), (bezel, bezel), mask)
    return body


def main(out, items):
    shots = []
    for it in items:
        path, cap = it.split(":", 1)
        shots.append((Image.open(path).convert("RGB"), cap))
    cut = max(radar_card_bottom(im) for im, _ in shots) + 48
    phones = [(phone(im.crop((0, 0, im.size[0], min(cut, im.size[1])))), cap) for im, cap in shots]
    pw, ph = phones[0][0].size
    gap, pad, cap_h = 110, 90, 150
    W = pad * 2 + pw * len(phones) + gap * (len(phones) - 1)
    H = pad + ph + cap_h
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shadow)
    for i in range(len(phones)):
        x = pad + i * (pw + gap)
        sd.rounded_rectangle((x + 10, pad + 34, x + pw - 10, pad + ph + 20), radius=90, fill=70)
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))
    canvas.putalpha(shadow)                          # black, at the shadow's alpha
    f = ImageFont.truetype(CJK, 54, index=2)
    # captions on their own layer: drawn straight onto a transparent canvas,
    # the antialiased edges keep the canvas's alpha and come out as a dark fringe
    text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    for i, (p, cap) in enumerate(phones):
        x = pad + i * (pw + gap)
        canvas.alpha_composite(p, (x, pad))
        tw = d.textlength(cap, font=f)
        d.text((x + (pw - tw) / 2, pad + ph + 48), cap, font=f, fill=CAPTION)
    canvas.alpha_composite(text)
    small = canvas.resize((OUT_W, round(H * OUT_W / W)), Image.LANCZOS)
    small.save(out, optimize=True)
    print("%s %dx%d, cut at %d px of each picture" % (out, small.size[0], small.size[1], cut))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2:])
