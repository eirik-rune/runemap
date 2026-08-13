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
              "▓": "\u2588", "█": "\u2588", "?": "\u2588",
              # bob again, from his phone: "主要是那个空格没对齐". Replacing only
              # the rain glyphs was half a fix -- the空 cells were still ordinary
              # spaces from the primary monospace face, while U+2588 came from
              # whatever fallback had it, and two fonts do not agree on width.
              # So EVERY cell is the same glyph and an empty one is simply
              # invisible. A grid where one cell in six is a different font is
              # not a grid.
              " ": "\u2588"}
CLASS[" "] = "r0"

# Bytes of HTML per byte of text. 25 KB for 1.8 KB was 14x.
MAX_RATIO = 6.0

_META = re.compile(r"^(radar|data|~|\[|obs|=)")
# The scene's own `legend:` line stays in the document -- it is what an agent
# reads -- but printing it again under a coloured legend that says the same
# thing is the page arguing with itself. Looking at the render is what showed
# it; the parser was happily filing it as provenance.
_NO_COVER = "no radar here"

# U+2581..U+2588, the eighth-blocks the curve is drawn with. Same trap as the
# map: they are not in every phone's fonts, and where they are missing the
# curve does not degrade -- it disappears, which is what bob saw. So the page
# turns them into bars whose heights are fractions of a box, and the tick line
# (which is box-drawing characters, the same risk again) into plain labels.
BARS = {chr(0x2580 + n): n for n in range(1, 9)}
_GRID_CHARS = set(RAMP + "?><ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ")
_TICKS = set("\u2500\u251c\u252c\u2524\u253c ")
_BAR_CHARS = set(BARS) | {" "}


def _title(s):
    """Strip whatever the document calls itself in its own language."""
    for tail in (" weather scene", " \u5929\u6c14\u4e00\u5c4f",
                 " \u5929\u6c17\u4e00\u89a7"):
        if s.endswith(tail):
            return s[:-len(tail)]
    return s


def _next_is_curve(lines, i):
    """True if the next non-empty line is drawn in eighth-blocks."""
    for nxt in lines[i + 1:i + 3]:
        if nxt.strip():
            return set(nxt.rstrip()) <= _BAR_CHARS
    return False

# bob: "界面有点儿扁". It is not taste, it is geometry, and the renderer says so
# itself: "km_per_row is twice that on purpose: a terminal cell is about twice
# as tall as it is wide, so a geographically 1:2 cell renders square". The
# window on the ground is a square. Drawing the cells square instead stretched
# the whole map 2:1 east-west -- so every echo was drawn twice as far from the
# reader as it is. A picture that is pretty and wrong about where the rain is
# would be worse than the text it replaced.
_CELL_TALL = 2
_DROP = re.compile(r"^(legend|\u56fe\u4f8b|\u51e1\u4f8b)\s*:")
# Terminal alignment padding, meaningless once HTML collapses it.
_MULTISPACE = re.compile(r" {2,}")

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
.map{border:1px solid var(--line);border-radius:10px;padding:.5rem;margin:0 0 .5rem}
/* The square is held by the old padding-bottom trick, not by `aspect-ratio`.
   `aspect-ratio` is unsupported on Safari before 15, and where it is
   unsupported the grid does not degrade -- it collapses to zero height and the
   map is simply gone, which is what bob reported seeing. Same shape as the
   missing glyphs: a feature the reader's device lacks does not announce
   itself. padding-bottom on a zero-height box has worked since 2010. */
.ar{position:relative;height:0}
.grid{position:absolute;top:0;left:0;right:0;bottom:0;
display:flex;flex-direction:column;width:100%%}
.grid .row{flex:1;display:flex}
.grid .row i{display:block}

.curve .bars{display:flex;align-items:flex-end;gap:1px;height:2.6rem;
border-bottom:1px solid var(--line)}
.curve .bars i{flex:1;background:#4aa3df;border-radius:1px 1px 0 0;min-height:1px}
.curve .axis{display:flex;justify-content:space-between;color:var(--dim);
font-size:.7rem;margin-top:.15rem}
.curve .flat{margin:0;color:var(--dim);font-size:.85rem}
.curve h2{font-size:.8rem;font-weight:600;color:var(--dim);margin:0 0 .3rem}
.curve{margin:0 0 1.1rem}
/* The marker used to be dark text on a yellow chip. Once every cell became a
   solid block, the dark colour painted the whole cell and "you are here" read
   as a hole punched in the map. It is now a colour no rain level uses. */
.me{background:#7b3fe4}
.r0{background:transparent}
.r1{background:#b9dcf2}.r2{background:#3fb56b}.r3{background:#e0c341}
.r4{background:#e08b3f}.r5{background:#d64545}
.rq{background:var(--line)}
.sep{color:var(--dim)}
.legend i{width:.85rem;height:.85rem;border-radius:2px;display:inline-block;
vertical-align:-.12rem}
.legend{display:flex;gap:.7rem;flex-wrap:wrap;color:var(--dim);font-size:.75rem;margin:0 0 1rem}
.meta{color:var(--dim);font-size:.75rem;border-top:1px solid var(--line);padding-top:.6rem}
.meta div{margin:.15rem 0}
</style>
<main>
<h1>%(place)s</h1>
<p class="sub">%(when)s</p>
%(head)s
%(body)s<div class="meta">%(meta)s</div>
</main>
"""


def paint(lines, marker="><"):
    """The grid as boxes, not text. One box per RUN of identical cells.

    8/13, bob's third round: "还是只能看到左半边的雷达图，能不能强制半角?" Even with
    every cell drawn as U+2588, his phone renders that glyph from a CJK
    fallback where it is FULL width, so 48 columns are twice as wide as the
    arithmetic assumed and half the map is off-screen. Sizing text by
    calculation only works if you know which font will draw it, and from here
    I never do -- that is the third font surprise in one hour.

    So no glyphs at all. Each row is a flex line, each run a box with
    `flex: <n>`, and the whole grid carries the aspect ratio. Widths are then
    fractions of the container, which no font can argue with, and the page
    gets smaller because the cells have no content.
    """
    out = []
    for ln in lines:
        buf, i = [], 0
        while i < len(ln):
            if ln[i:i + len(marker)] == marker:
                buf.append('<i class="me" style="flex:%d"></i>' % len(marker))
                i += len(marker)
                continue
            ch = ln[i]
            j = i
            while j < len(ln) and ln[j] == ch and ln[j:j + len(marker)] != marker:
                j += 1
            buf.append('<i class="%s" style="flex:%d"></i>'
                       % (CLASS.get(ch, "r0"), j - i))
            i = j
        out.append('<div class="row">%s</div>' % "".join(buf))
    return "".join(out)


def _is_axis(w):
    """"0   30   60   90 120min" is the axis, not a sentence about the rain.
    It was being printed twice: once as prose above the bars and once as the
    axis below them."""
    toks = w.split()
    return len(toks) >= 3 and sum(1 for t in toks if t[0].isdigit()) >= 3


def _curve_html(lines, heading=""):
    """The 2h rain curve as bars, for the same reason the map is boxes.

    The heading is the document's own ("rain curve (next 2h, 6min/bucket)",
    "雨量曲线(未来2h, 6min/格)", "雨量曲線(今後2h, 6min/枠)"), not a phrase of mine:
    an English caption over a Chinese page is the same defect as an English
    legend, one line up.
    """
    bars, labels, words, width = [], [], [], 0
    for ln in lines:
        if ln.strip() and set(ln.rstrip("\n")) <= _BAR_CHARS:
            # EVERY position is a bucket. Taking only the characters that are
            # bars dropped the gaps -- and in this chart a space is a bucket
            # with no rain, so a 20-bucket line came out as 6 bars crowded at
            # the left and every one of them at the wrong time. bob: "本来应该
            # 是20个就变成六格了". The dropped character was not decoration, it
            # was the value zero.
            # NOT rstripped: this function was undoing what the parser had
            # just taken care to preserve. Two rstrips on the same value, one
            # in each half, and removing either alone changes nothing -- which
            # is how the first fix here measured as working.
            row = [BARS.get(c, 0) for c in ln.rstrip("\n")]
            if len(row) > len(bars):
                bars = row
            continue
        if ln.strip() and set(ln.strip()) <= _TICKS:
            # The tick line states the chart's FULL width, which the bar line
            # cannot when its last buckets are dry: trailing spaces do not
            # survive being written down. 8/13: this assignment was in a patch
            # whose target string did not match, so it silently did not land
            # and `width` stayed 0 -- the padding below was dead code, and I
            # "verified" the fix on Tokyo, whose curve happened to have no dry
            # tail. **A check run on a case that cannot exhibit the bug is not
            # a check.**
            # MINUS ONE. The ruler marks bucket BOUNDARIES, not buckets:
            # `runemap/sparkline.py` says so in its own docstring -- "ruler
            # marks bucket boundaries 0..20 -> 21 chars". 20 intervals need 21
            # fenceposts. Taking its length as a bucket count therefore always
            # invented one extra empty bucket at the end, which is not a
            # cosmetic extra: the chart answers "when does the rain arrive",
            # so a 21st bucket squeezes every real one leftward and puts each
            # bar at a time it does not mean. Measured live on Trondheim,
            # 2026-08-13 19:20 -- source 20 buckets, page drew 21.
            width = max(width, len(ln.rstrip()) - 1)
            continue
        if ln.strip():
            words.append(ln.strip())
    # The axis line becomes the axis; everything else on those lines is prose.
    # Splitting them the other way round (filter first, then look for labels in
    # what is left) is how the scale silently vanished from the chart -- the
    # bars stayed, so it looked fine until you asked "0 to what?".
    for w in words:
        if _is_axis(w):
            labels = w.split()
    words = [w for w in words if not _is_axis(w)]
    if not bars:
        # No bars at all is a real answer -- "no precipitation expected" -- and
        # it must be shown, not silently dropped.
        return ('<div class="curve"><h2>%s</h2><p class="flat">%s</p>'
                '</div>\n' % (html.escape(heading or "next 2 hours"),
                              html.escape(" ".join(words)))) if words else ""
    if width > len(bars):
        bars = bars + [0] * (width - len(bars))
    cells = "".join('<i style="height:%d%%"></i>' % (100 * b // 8)
                    for b in bars)
    axis = ("".join('<span>%s</span>' % html.escape(t) for t in labels)
            if labels else "")
    # Any prose on the curve line ("peaks in 30 min") is the most useful part
    # of it and must not be dropped for the sake of the picture.
    note = ('<p class="flat">%s</p>' % html.escape(" ".join(words))) if words else ""
    return ('<div class="curve"><h2>%s</h2>%s'
            '<div class="bars">%s</div><div class="axis">%s</div></div>\n'
            % (html.escape(heading or "next 2 hours"), note, cells, axis))


def render(text, marker="><"):
    """Parse by SHAPE, not by English words.

    bob opened the page on his phone and saw a title, a timestamp and nothing
    else -- and he was right three times running while every check I ran here
    passed. His page is the Chinese one. The first parser keyed on `now:`,
    `rain curve`, `~4km/char` and `legend:`, so on /zh (当前:, 雨量曲线,
    每字符≈4km, 图例:) and on /ja nothing matched and the whole document fell
    through to "prose". **A parser that only understands one language does not
    fail on the others, it empties them** -- and the language I tested in was
    of course the one I wrote the keys in.

    The document has the same SHAPE in all three: two `#` header lines, a
    conditions line, a forecast sentence, a curve drawn in eighth-blocks, a
    grid drawn in ramp characters, a legend that pairs ramp characters with
    words, and provenance lines. Every one of those is recognisable without
    reading a word of it.
    """
    place = when = now = say = ""
    meta, grid, curve, pairs = [], [], [], []
    order, in_grid, head_seen, curve_head = [], False, 0, ""
    lines = text.split("\n")
    for i, raw in enumerate(lines):
        s = raw.rstrip()
        # -- the grid: rows of ramp characters, and a row of clear sky is a row
        # of spaces (rstrip made those "" and London lost most of its map).
        if in_grid:
            if not s or set(s) <= _GRID_CHARS:
                # UNSTRIPPED. A cell with no rain on the eastern edge is a
                # space, and dropping it does not merely shorten the picture:
                # the window is centred on the reader, so the marker sits at
                # column cols/2 BY CONSTRUCTION. Narrow the grid from the right
                # and the marker is no longer in the middle of it -- every echo
                # is then drawn at the wrong bearing and the wrong distance
                # from the person reading. bob: "不然紫色块儿就不在中心了".
                grid.append(raw.rstrip("\n"))
                if "map" not in order:
                    order.append("map")
                continue
            in_grid = False
        if s.startswith("# "):
            head_seen += 1
            if head_seen == 1:
                place = _title(s[2:])
            elif not when:
                when = s[2:]
            continue
        if not s:
            continue
        # -- the legend FIRST: it ends in \u2588, which is also the tallest bar,
        # so testing for bars first read the legend as a chart -- and the page
        # then fell back to labels I had generated in English, which is exactly
        # the failure this rewrite is about.
        toks = s.split()
        if sum(1 for t in toks if t in CLASS) >= 3:
            pairs.extend((toks[k], toks[k + 1])
                         for k in range(0, len(toks) - 1)
                         if toks[k] in CLASS and toks[k + 1] not in CLASS)
            continue
        # -- the curve: a line that is NOTHING BUT eighth-blocks and spaces.
        # Appended UNSTRIPPED: a trailing space is a bucket with no rain, and
        # the loop's `s` has already lost them. Exactly the bug that deleted
        # most of London's map this morning, in the other block -- I fixed the
        # grid and did not sweep the family.
        if s.strip() and set(s) <= _BAR_CHARS:
            curve.append(raw.rstrip("\n"))
            if "curve" not in order:
                order.append("curve")
            continue
        if set(s) <= _TICKS:
            curve.append(s)
            continue
        if curve and not grid and _is_axis(s):
            curve.append(s)
            continue
        # -- a grid row met without a scale line before it
        if len(s) >= 8 and set(s) <= _GRID_CHARS and any(
                c in RAMP[1:] or c in "?><" for c in s):
            in_grid = True
            # raw, not s: same reason as the branch above. This is the path a
            # document takes when it has no [><]= scale line, and it had the
            # trailing-space bug all along -- I fixed the two paths I had a
            # failing page for and left the third, which is how this family
            # got to three instances in one day.
            grid.append(raw.rstrip("\n"))
            continue
        # -- provenance and scale lines
        if _META.match(s) or "]=" in s:
            # A looser test here ("km" anywhere in the first field) swallowed
            # the Chinese conditions line -- 当前: 小雨 24C 湿度 84% 风速 9km/h --
            # and the page lost the one fact a reader opens it for. The scale
            # line is recognised by the marker it names, which every language
            # writes the same way: [><]=Tokyo.
            meta.append(s.strip())
            if "]=" in s:
                # The grid begins on the next line, blank rows included.
                in_grid = True
            continue
        # -- the label that introduces the curve: "雨量曲线(未来2h, 6min/格):" or
        # "rain curve (next 2h): no precipitation expected". Whatever follows
        # the colon is content and is kept; the label itself is a heading.
        # ...and only once the conditions and the forecast are in hand, so
        # that "= echo motion: NE 21km/h" cannot be mistaken for it. It was:
        # the lookahead found the legend line, which ends in \u2588, and the
        # motion line was split into a heading and a stray "NE 21km/h".
        if now and say and (s.endswith(":") or (":" in s and _next_is_curve(lines, i))):
            head, rest = s.split(":", 1)[0].strip(), s.split(":", 1)[1].strip()
            if head:
                curve_head = head
            if rest:
                curve.append(rest)
            if "curve" not in order:
                order.append("curve")
            continue
        # -- the first two prose-ish lines after the headers are the conditions
        # and the forecast. Position, not vocabulary: 当前:/現在:/now: differ,
        # their place in the document does not.
        if not now:
            now = s.split(":", 1)[1].strip() if ":" in s[:12] else s
            continue
        if not say:
            say = s
            continue
        meta.append(s.strip())
    if not pairs:
        pairs = list(zip(RAMP, ("drizzle", "light", "moderate",
                                "heavy", "storm")))
    # The marker and "no coverage" are cells on the map too, and an unexplained
    # colour is worse than none: a reader who cannot place it will read it as
    # weather. The marker's label is the document's own ([><]=Tokyo, Tokyo, JP),
    # so it stays in the reader's language, and the unknown entry appears only
    # when the grid actually contains unknown cells.
    extra = []
    here = next((m.split("]=", 1)[1] for m in meta if "]=" in m), "")
    if grid and here:
        extra.append('<span><i class="me"></i> %s</span>'
                     % html.escape(here.split(",")[0]))
    if any("?" in r for r in grid):
        extra.append('<span><i class="rq"></i> %s</span>'
                     % html.escape(_NO_COVER))
    legend = " ".join(
        ['<span><i class="%s"></i> %s</span>'
         % (CLASS[c], html.escape(n)) for c, n in pairs]
        + extra)
    # A scene that is still fetching has no conditions line, no forecast
    # sentence, no curve and no grid -- and my first page rendered that as two
    # empty paragraphs and a footnote in grey, which reads as "the site is
    # broken" rather than "we are looking". bob hit exactly this. Empty blocks
    # are not emitted, and when there is nothing at all, the reason moves up to
    # where the reader is looking.
    head = ""
    if now:
        head += '<p class="now">%s</p>\n' % html.escape(now)
    if say:
        head += '<p class="say">%s</p>\n' % html.escape(say)
    if not (now or say or grid or curve):
        why = next((m for m in meta if m.startswith("radar")), "")
        head += ('<p class="say">%s</p>\n'
                 % html.escape(why or "no reading yet"))
    # Rows arrive rstripped of nothing but the newline, yet a source row may
    # still be short; pad so every row has the same number of cells, or the
    # flex weights describe a ragged grid.
    _w = max((len(r) for r in grid), default=48)
    grid = [r.ljust(_w) for r in grid]
    blocks = {
        "map": ('<div class="map"><div class="ar" style="padding-bottom:%.1f%%">'
                '<div class="grid">%s</div></div></div>\n'
                '<p class="legend">%s</p>\n'
                % (100.0 * len(grid) * _CELL_TALL / max(1, _w),
                   paint(grid, marker), legend)) if grid else "",
        "curve": _curve_html(curve, curve_head) if curve else "",
    }
    return PAGE % {
        "title": html.escape(place.split(",")[0] or "runemap"),
        "place": html.escape(place or "runemap"),
        "when": html.escape(when),
        "head": head,
        "body": "".join(blocks[k] for k in order),
        # The padding on these lines SEPARATES FIELDS, so it is data, not
        # layout. "radar: obs            obs age: 8min ok" collapses in HTML to
        # "radar: obs obs age: 8min ok" -- a stutter, where the first "obs" is
        # what was drawn and the second belongs to "obs age". Keeping the
        # spaces with white-space:pre would push the line off a phone sideways
        # instead. So the run becomes a visible separator: the boundary
        # survives, and it survives at any width.
        "meta": "".join("<div>%s</div>" % _MULTISPACE.sub(
            '<span class="sep"> · </span>', html.escape(m)) for m in meta),
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
