"""Render the plain-text scene as a small HTML page, for browsers only.

bob's design, 8/13: there is ONE canonical document -- the markdown-ish plain
text every agent already gets. A person opening the same URL in Chrome should
not see raw text, and a machine that lands here by accident must not be handed
a giant HTML blob. So this is a *rendering* of the bytes, never a second
source: `render()` takes the finished scene text and adds nothing to it.

Two rules it must not break, because they are the product:

  * ONE request. No external CSS, fonts, images or JS -- everything inline.
  * It stays small. The first prototype wrapped every map character in an
    inline-styled <span> and weighed 25 KB for a 1.8 KB scene, which is exactly
    the "giant HTML" bob asked me to avoid. Runs of identical characters share
    one span and the colours live in classes, so the page is a small multiple
    of the text. `MAX_RATIO` below is asserted in the tests, because a size
    promise nobody measures is a promise that quietly stops being true.

Negotiation is the caller's job (serve.py) and is done on `Accept`, not on
User-Agent: a header a client sends about what it wants is evidence; a name it
sends about what it is, is a guess.
"""
import html
import re

# The glyphs render.py draws with, weakest to strongest, plus '?' for sky we
# have no radar for. '?' is deliberately NOT coloured as weather: "not looked
# at" and "looked, no rain" must not share a shape (8/12).
RAMP = "·░▒▓█"
CLASS = {"·": "r1", "░": "r2", "▒": "r3",
         "▓": "r4", "█": "r5", "?": "rq"}

# 8/13, bob: "怎么格子没有对齐呢?" -- because `░ ▒ ▓` are not in the monospace
# faces phones ship with, so the browser pulls each from whatever fallback has
# them, at that font's advance width. The grid then goes ragged row by row and
# the map stops being a map. The document keeps its five characters -- they are
# what an agent reads -- but the PAGE draws every cell with the SAME glyph and
# says which level it is in colour, which is what bob proposed in the first
# place ("把那个雷达图用block搞一下"). One glyph cannot disagree with itself
# about width.
CELL_GLYPH = {"·": "\u2588", "░": "\u2588", "▒": "\u2588",
              "▓": "\u2588", "█": "\u2588", "?": "\u2588"}

# Bytes of HTML per byte of text. 25 KB for 1.8 KB was 14x.
MAX_RATIO = 6.0

_META = re.compile(r"^(radar|data|~|\[|obs|=)")
# The scene's own `legend:` line stays in the document -- it is what an agent
# reads -- but printing it again under a coloured legend that says the same
# thing is the page arguing with itself. Looking at the render is what showed
# it; the parser was happily filing it as provenance.
_DROP = re.compile(r"^(legend|\u56fe\u4f8b|\u51e1\u4f8b)\s*:")

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
<style>
:root{color-scheme:light dark;--ink:#171a1f;--dim:#6b7280;--bg:#fff;--line:#e5e7eb}
@media (prefers-color-scheme:dark){:root{--ink:#e6e8ec;--dim:#98a0ab;--bg:#0f1115;--line:#232833}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-text-size-adjust:100%%}
main{max-width:40rem;margin:0 auto;padding:1rem 1rem 2rem}
h1{font-size:1.15rem;line-height:1.3;margin:0 0 .1rem;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:.8rem;margin:0 0 1rem}
.now{font-size:1.05rem;margin:0 0 .3rem}
.say{margin:0 0 1.1rem}
.map{overflow-x:auto;border:1px solid var(--line);border-radius:10px;padding:.6rem .7rem;margin:0 0 .5rem}
.map pre{margin:0;white-space:pre;
font:12px/1.05 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.06em}
.curve pre{margin:0;white-space:pre;overflow-x:auto;color:#4aa3df;
font:15px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.curve .axis{color:var(--dim);font-size:12px}
.curve h2{font-size:.8rem;font-weight:600;color:var(--dim);margin:0 0 .3rem}
.curve{margin:0 0 1.1rem}
.me{color:#111;background:#ffd54a;border-radius:2px;font-weight:700}
.r1{color:#4aa3df;opacity:.45}.r2{color:#3fb56b}.r3{color:#e0c341}.r4{color:#e08b3f}.r5{color:#d64545}
.rq{color:var(--line);opacity:.5}
.legend{display:flex;gap:.7rem;flex-wrap:wrap;color:var(--dim);font-size:.75rem;margin:0 0 1rem}
.legend i{font-style:normal;font-family:ui-monospace,monospace}
.meta{color:var(--dim);font-size:.75rem;border-top:1px solid var(--line);padding-top:.6rem}
.meta div{margin:.15rem 0}
</style>
<main>
<h1>%(place)s</h1>
<p class="sub">%(when)s</p>
<p class="now">%(now)s</p>
<p class="say">%(say)s</p>
%(body)s<div class="meta">%(meta)s</div>
</main>
"""


def paint(lines, marker="><"):
    """Colour the grid, one span per RUN of identical characters."""
    out = []
    for ln in lines:
        buf, i = [], 0
        while i < len(ln):
            if ln[i:i + len(marker)] == marker:
                buf.append('<span class="me">%s</span>' % html.escape(marker))
                i += len(marker)
                continue
            ch = ln[i]
            j = i
            while j < len(ln) and ln[j] == ch and ln[j:j + len(marker)] != marker:
                j += 1
            cls = CLASS.get(ch)
            run = html.escape(CELL_GLYPH.get(ch, ch) * (j - i))
            buf.append('<span class="%s">%s</span>' % (cls, run) if cls else run)
            i = j
        out.append("".join(buf))
    return "\n".join(out)


def render(text, marker="><"):
    place = when = now = say = ""
    meta, grid, curve = [], [], []
    # 8/13, bob: the text puts the rain curve ABOVE the map and my first page
    # put it below, because the template hard-coded the order. That is the page
    # editing the document, which is the one thing it must not do. Which block
    # was met first is recorded here and the page follows it.
    order = []
    in_curve = False
    for s in text.split("\n"):
        s = s.rstrip()
        if s.startswith("# ") and not place:
            place = s[2:].replace(" weather scene", "")
            continue
        if s.startswith("# updated"):
            when = s[2:]
            continue
        if s.startswith("now:"):
            now = s[4:].strip()
            continue
        if s.startswith("rain curve"):
            # The curve answers "when does it stop", which is the question a
            # person actually has. The first parser dropped it because its
            # block characters were not in RAMP -- the filter decided the shape
            # of the blind spot, and what fell in it was the product.
            in_curve = True
            if "curve" not in order:
                order.append("curve")
            rest = s.split(":", 1)[1].strip() if ":" in s else ""
            if rest:
                curve.append(rest)
            continue
        if in_curve:
            if s.strip():
                curve.append(s)
                continue
            in_curve = False
            continue
        if _DROP.match(s):
            continue
        if _META.match(s):
            meta.append(s.strip())
            continue
        if s and set(s) <= set(RAMP + "?><ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "):
            grid.append(s)
            if "map" not in order:
                order.append("map")
            continue
        if s.strip() and not say:
            # Any remaining prose is the forecast sentence. Matching on "Over
            # the next" lost it the moment the wording became "After one hour",
            # and that sentence is the most useful line on the page.
            say = s.strip()
    legend = " ".join(
        '<span><i class="%s">%s</i> %s</span>' % (CLASS[c], CELL_GLYPH[c], n)
        for c, n in zip(RAMP, ("drizzle", "light", "moderate", "heavy", "storm")))
    blocks = {
        "map": ('<div class="map"><pre>%s</pre></div>\n<p class="legend">%s</p>\n'
                % (paint(grid, marker), legend)) if grid else "",
        "curve": ('<div class="curve"><h2>next 2 hours</h2><pre>%s</pre></div>\n'
                  % html.escape("\n".join(curve))) if curve else "",
    }
    return PAGE % {
        "title": html.escape(place.split(",")[0] or "runemap"),
        "place": html.escape(place or "runemap"),
        "when": html.escape(when),
        "now": html.escape(now),
        "say": html.escape(say),
        "body": "".join(blocks[k] for k in order),
        "meta": "".join("<div>%s</div>" % html.escape(m) for m in meta),
    }


def wants_html(accept):
    """True only when the client ASKED for HTML above plain text.

    curl sends `*/*`, every agent library sends `*/*` or nothing, and browsers
    send an explicit `text/html` first. So the wildcard must never count: the
    default -- for anything that did not say -- stays the plain bytes that are
    already the contract.
    """
    if not accept:
        return False
    best_html = best_text = -1.0
    for part in accept.split(",")[:20]:
        bits = part.strip().split(";")
        mime = bits[0].strip().lower()
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if mime in ("text/html", "application/xhtml+xml"):
            best_html = max(best_html, q)
        elif mime == "text/plain":
            best_text = max(best_text, q)
    return best_html > 0 and best_html > best_text
