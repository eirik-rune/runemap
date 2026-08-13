# The HTML rendering, 2026-08-13: what it cost to make one document readable twice

bob's design: one canonical document. Agents get the plain bytes they already
get; a person opening the same URL in a browser gets it lightly rendered; a
machine that lands there by accident must not be handed a giant page. This
records what that took, because the summary on the stone keeps only the
conclusions and the mistakes are the useful part.

## Three rounds of arguing with a font, and losing each one

Every cell of the radar map is a character in the document: `· ░ ▒ ▓ █`.

1. **Put them in the HTML as they are.** They are absent from the monospace
   faces phones ship with, so the browser takes each from whichever fallback
   has it, at that font's advance width. The grid goes ragged row by row. I had
   screenshotted the page twice through headless chromium and seen nothing:
   *my* box has fonts with those glyphs. bob saw it immediately on his phone.
2. **Draw every rain cell with one glyph (U+2588).** Still ragged. The EMPTY
   cells were ordinary spaces, from the primary face, while the block came from
   a fallback — two fonts, two widths. A half-fix that looks like a fix.
3. **Size the text by calculation** (`(100vw - 3.6rem) / cols / 0.6em`). bob:
   "还是只能看到左半边的雷达图". His phone renders U+2588 from a CJK fallback where
   it is FULL width, so 48 columns came out twice as wide as the arithmetic
   assumed.

The pattern only became visible after the third round: **sizing text by
calculation requires knowing which font will draw it, and from here I never
do.** The fix that ended it stopped using text at all — each row is a flex
line, each run of identical cells a box with `flex: n`, the grid carries its
aspect ratio. Widths are fractions of the container, which no font can argue
with. The page also got smaller, because the cells have no content.

The same trap one layer down: the 2h rain curve is drawn with U+2581..U+2588
and its tick line with box-drawing characters. Where a phone lacks them the
curve does not degrade, **it disappears** — bob: "我看不到降水曲线了". Now bars
whose heights are fractions of a box.

## The geometry was wrong, and our own renderer said so

bob: "界面有点儿扁". Not taste. `ascii_radar_centered`'s docstring:

> km_per_row is twice that on purpose: a terminal cell is about twice as tall
> as it is wide, so a geographically 1:2 cell renders square.

So the 48x24 grid covers a **square** of sky. Drawing the cells square
stretched the map 2:1 east-west, which drew every echo twice as far from the
reader as it is. A picture that is pretty and wrong about where the rain is is
worse than the text it replaced.

## The bug none of that was about

A grid row with no rain is 48 spaces. The parser rstripped rows, which turned
those into empty strings, and skipped them. London rendered as 26x12 instead of
48x24: most of the map was not wrong, it was **deleted** — and only in calm
weather. Every city I had looked at that day happened to be raining.

No test would have caught it. I checked by re-breaking it and watching nothing
go red, then wrote one that does.

The grid is now delimited by the document's own scale line (`~4km/char,
[><]=London`) and runs until something that is not grid-shaped.

## Smaller things, each found only by looking at the rendered page

* The page put the rain curve BELOW the map; the document has it above. The
  template hard-coded the order — a rendering that reorders is editing. Order
  now comes from the source.
* The marker was dark text on a yellow chip. Once cells became solid blocks the
  dark colour filled the cell, so the one cell the reader cares most about read
  as a hole punched in the map.
* The legend explained five colours out of seven (not the marker, not "no radar
  here"). An unexplained colour is worse than none: a reader who cannot place it
  reads it as weather.
* The legend text was English I generated, so `/tokyo/zh` — whose own legend
  line reads `图例: · 毛毛雨 ...` — would have been captioned in a language the
  reader never asked for. Labels now come from the document's legend line,
  which is why that line is parsed rather than merely dropped.
* A still-fetching scene has no conditions line, no sentence, no curve and no
  grid. Rendered as empty paragraphs plus a grey footnote it reads as a broken
  site rather than "we are looking".
* The axis filter removed the label line before the labels had been read out of
  it, so the chart silently lost its scale. Bars with no axis look fine until
  you ask "0 to what?".

## What is measured, not asserted

* Agents unchanged: negotiation is on `Accept` and `*/*` does not count, so
  everything that did not explicitly ask for HTML gets the same bytes as before.
* `Vary: Accept`, because the responses carry `public, max-age=300` and a cache
  would otherwise be free to hand a browser's HTML to the next agent — the exact
  failure bob asked me to avoid, arriving through the cache rather than the code.
* `X-Radar-Grid` / `X-Radar-Why` are still computed from the PLAIN body. From
  the markup, every HTML row would read `nogrid` and that log column would have
  started lying the day this shipped.
* Size: Tokyo (a busy grid) ~3.2x the text, London ~1.9x, against 14x for the
  first prototype. The ceiling is asserted, and measured on a production-size
  scene rather than on a toy fixture where the fixed stylesheet dominates.
* Cost: warm city, plain 0.061s vs html 0.058s. One request, no external
  resources of any kind.

## The instrument problem, stated plainly

Three of the seven defects above were found by bob on a phone and could not
have been found from here: whether a character exists in a reader's font, how
wide it is, and what a CJK fallback does with it are properties of the reader's
device. "I looked at the image" covers my box's fonts and nothing else.

His screenshots, incidentally, I could not open at all: 0xchat encrypts
attachments, so the URL yields ciphertext. Every one of these was located from
his sentences.

## 2026-08-13, fourth catch: the grid narrowed to its own weather

bob, on Chiang Mai: "右侧本来不下雨，不下雨的内容你也得保留，不然紫色块儿就不在
中心了" — then the general form: "横向的格你不能都删了，然后纵向的格没数据，你也
不能删了，他没数据也得表示点什么。"

Measured on the live page before the fix:

    source grid rows: 24  widths: [48]   marker at row 12, col 24
    rendered: padding-bottom 114.3% => implied cols 47.2

Two mechanisms stacked. The parser appended each grid row `raw.rstrip()`, so
cells with no rain on the eastern edge disappeared; the width was then taken as
`max(len(r) for r in grid)` — the widest **surviving** row. When no row happened
to have weather in the last column, the whole grid narrowed.

Why that is not "a slightly smaller picture": the window is centred on the
reader by construction, so the marker sits at column `cols/2` and every echo is
read as a bearing and a distance **from it**. Narrow the grid and the marker is
no longer in the middle — every echo silently moves to a wrong direction and a
wrong distance.

**Third instance of the family in one day** (London 26×12; the curve's 20
buckets rendered as 6), and the reason there was a third is the shape of the
first two fixes: I fixed the paths I had a visibly broken page for and did not
sweep the rest. The missed one was the branch a document takes when it has no
`[><]=` scale line — same `grid.append(s)`, same bug.

Two tests that nearly passed for the wrong reason:

* `left == 24` for the marker passes on the **broken** renderer. The truncation
  trims to the *right* of the marker, so the count before it never moves. The
  assertion now compares both halves against the grid's own width.
* The first fixture drew rain as a row of `█` and spaces — which is a legal
  **rain curve**, because `█` is also the tallest eighth-block. It was parsed as
  a chart, so the test measured a different block entirely and said nothing.
  The fixture now uses a mixed ramp.

All three assertions fire: put the strip back and width, height and centring go
red together.
