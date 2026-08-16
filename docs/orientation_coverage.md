# Which of the twelve countries can prove its map is the right way up?

Written 2026-08-13, after shipping the twelfth country, because "twelve
countries" is a number that flatters us until this question is answered. It was
asked the way the fleet has learned to ask: **count the entities actually
covered, not the modules that exist.** Three `*_orient.py` files exist. That is
not the same as three countries being safe, and it is not the same as nine
being unsafe either.

## The failure this is about

An upside-down or transposed payload is the worst class of bug this service can
have, because **nothing looks wrong**. The picture is scale-correct, the
timestamp is fresh, the legend is right, and the weather is in the wrong place.
No exception, no log line, no probe turns red.

A *projection* check does not catch it. Norway's and the Netherlands' corner
checks compare my arithmetic against coordinates from the same file, so the two
agree whatever the data array does. Catching a transposed payload requires
evidence **the product cannot forge** — something outside the file.

## Not every source carries that risk

The sources split into two structurally different groups, and conflating them
would overstate the problem by four countries.

**Group A — we ask for a window, they return that window.** No national grid is
indexed, so there is no row/column convention of ours to get backwards.

| source | countries | what pins the geometry |
|---|---|---|
| `radar_wms` | US, CA, FI, DE | WMS: we send a bbox, the server renders that bbox. Axis order per WMS version is asserted in code (1.1.1 x-first, 1.3.0 y-first) — the one real trap here, and it is pinned. |
| `radar_redemet` | BR | the bbox comes back **with** the image and is mirrored verbatim; we never invent it |
| `radar_jma` | JP | XYZ tiles; orientation is fixed by the tiling scheme, and `ops/jma_zoom.py` asserts the zoom because a wrong zoom returns 200 with a valid empty PNG |
| `radar_second` | (global fallback) | tiles, bbox derived from the tiling scheme |

These can still be wrong — a server could serve a mirrored image — but the
error would have to be upstream's, in a documented interchange format, rather
than ours. That is a different and much smaller risk than a private grid
convention.

**Group B — we index into a national grid.** Here a row/column convention of
ours is what places the weather, and getting it backwards is silent.

| source | country | independent control | status |
|---|---|---|---|
| `radar_dmi` | DK | `ops/dmi_orient.py` — blind mask vs 5 radar sites; flipped read is ~113 km out | **verified** |
| `radar_chmi` | CZ | `ops/chmi_orient.py` | **verified** |
| `radar_meteoswiss` | CH | `ops/ch_orient.py` — rain gauges, corr +0.934 vs +0.059 flipped | **verified** |
| `radar_metno` | NO | blind mask vs 9 OSCAR-resolved sites | **partial**: up-down flip excluded by 36 points; **180° rotation not excluded** (2.1 points) |
| `radar_smhi` | SE | `ops/se_orient.py` — blind mask vs 10 OSCAR-resolved sites; p10 blind-cell distance 254 km as read vs 88 flipped | **partial**: row order confirmed by 143 km; **180° rotation not excluded** (45 km) |
| `radar_knmi` | NL | corner check only — same file on both sides | **unverified** |

So the honest count is **three verified, two partial, one unverified**, out of
six grid-indexing sources — not "three of twelve". Sweden moved from unverified
to partial on 2026-08-13 without waiting for rain (see below); the Netherlands is
the one that has nothing.

## Sweden was settled with the other instrument, and needed no rain

The gauge route above assumed Sweden had to wait for an archived rainy hour.
It did not. **The blind mask — the instrument that settled Denmark — has power
in Sweden, and that was measured rather than assumed**, which is the whole
lesson from Switzerland: there the composite is centred on MeteoSwiss's own
network, so flipping mapped the mask almost onto itself (140.6 km vs 142.0) and
the control was worthless. Sweden's composite is a tall box with a large blind
margin and disagrees with its own vertical flip on 38% of cells.

**Which statistic matters more than which instrument.** "Cells near a radar are
seen" assumes a complete site list, and Norway showed what that costs — it
*preferred* the wrong orientation there. Sweden's list is incomplete too (10 of
12: Gotland refused by the name guard, Bålsta absent from OSCAR), so the
judgement runs on the direction that survives a missing site: **a blind cell
must be far from every known radar.** A site we failed to resolve can only turn
blind cells into seen ones — it can weaken the evidence, never manufacture it.

Measured on the 23:0x frame of 2026-08-13 (`ops/se_orient_run.py`):

| orientation | blind-cell distance p10 | median | mean | seen within 50 km |
|---|---|---|---|---|
| as read | **253.7 km** | 349.0 | 365.6 | 100.0% |
| vertical flip | 88.3 km | 241.3 | 257.4 | 72.1% |
| horizontal flip | 111.1 km | 241.0 | 265.3 | 81.4% |
| 180° rotation | 209.0 km | 334.0 | 346.5 | 100.0% |

**Row order — the realistic mistake, the one every ODIM reader here can make —
is excluded by 143 km.** A 180° rotation is not: it scores 45 km worse, inside
the margin. It requires both axes reversed at once, which no single convention
error produces, but this instrument cannot rule it out and the verdict says so
in words rather than rounding up to "verified". Norway carries the identical
open corner.

Fired both ways: the runner exits 1 and prints FLIPPED when handed the array
upside down, and every verdict has a test built to earn it.

## The Netherlands is the remaining open risk, and it really does need rain

Asked the same way as Sweden rather than assumed: **measured, 23:01 frame,
2 operational radars (Den Helder, Herwijnen; De Bilt is flagged
`radar_operational=0` in the file and excluded), 19.5% of the grid blind.**

| orientation | blind-cell p10 | median | mean | seen within 50 km |
|---|---|---|---|---|
| as read | 338.9 km | 369.2 | 376.7 | 100.0% |
| vertical flip | 312.4 km | 365.8 | 368.0 | 100.0% |
| horizontal flip | 319.6 km | 368.7 | 370.6 | 100.0% |
| 180° rotation | 327.8 km | 369.4 | 374.0 | 100.0% |

**The mask has no power here — 26 km of spread, and every orientation keeps
100% coverage over both radars.** That is Switzerland's situation, not
Sweden's: KNMI's composite is a range-limited disc centred on a network in the
middle of a small country, so flipping it maps it very nearly onto itself. The
right verdict is INSUFFICIENT, and taking the 26 km as a direction would be the
1% margin mistake with a new coat on.

So the Netherlands is the one country that genuinely needs the gauge method and
therefore an archived rainy hour. Both prerequisites were established on
2026-08-13: the radar archive goes back to 2019 in the same dataset
`radar_knmi` already reads, and the one unknown left is the **station dataset
name, which must come from KNMI's published catalogue** — their open-data API
serves files for a dataset you can already name and answers 404 to
`/datasets`, confirmed against a positive control on the same key.

Whatever walks that archive must budget for strangers: **that API key is shared
by every unregistered user**, and walking timestamps with it earned a 429.



The Netherlands reads a national grid and has no control independent of the
file it reads. Neither is known to be wrong; the point is that **if either were
wrong, nothing here would say so.**

The method that settled Switzerland transfers directly and needs no new idea:
rain gauges are a different instrument, in different files, from equipment that
is not a radar. If the array is read correctly, gauge totals correlate with the
radar rate at each station's own cell; upside down they correlate with rain
that fell somewhere else. Both countries publish station observations openly,
and `ops/ch_orient.py` is already written to take the frame and the gauge
readings from its caller, so the judgement itself is reusable as-is.

**Sweden, started 2026-08-13 and stopped at an honest verdict.** SMHI's gauge
feed is open and needs no key:

    .../metobs/api/version/1.0/parameter/7/station-set/all/period/latest-hour/data.json

It returned **140 stations, of which 2 were wet** — and `ch_orient.judge()`
answers INSUFFICIENT for that sample no matter what the radar column contains.
Checked rather than assumed: feeding it a radar column that agrees perfectly, one
that is perfectly flipped, and one that is pure noise all return INSUFFICIENT,
because the gauge side alone fails the wet-station minimum. **That is the
verdict, not a gap in the tooling** — Sweden was simply dry.

So Sweden needed an archived rainy hour — **and then didn't**, because the
blind mask turned out to have power there and needs no rain at all. Kept above
rather than deleted: the gauge attempt is what made me measure the mask instead
of assuming Switzerland's outcome generalised. **Reaching for the instrument
that worked last time is how a whole night gets spent waiting for weather.**
SMHI's archive route stays recorded here in case the 180° corner is ever worth
closing, which needs a rain-based instrument.

**Both archives exist and are deep — checked, so tomorrow does not start by
re-deriving this.** The Netherlands was dry too tonight (24-25 C, humidity
31-42%, precip 0.00 in all four cities), so it needs the same treatment.

| | radar archive | gauges |
|---|---|---|
| SE | `opendata-download-radar.smhi.se`, area `sweden`, product `comp` — **years 2008 → 2026**, newest file `radar_2608132230` | metobs parameter 7; `latest-hour` works keyless, history under `latest-months` / `corrected-archive` |
| NL | KNMI dataplatform, same dataset `radar_knmi` already reads — oldest file kept is `RAD_NL25_PCP_NA_201910281110.h5`, i.e. **back to 2019** | KNMI station observations (dataset name still unidentified — see note) |

**Finding the KNMI station dataset needs their catalogue, not their API.**
`/open-data/v1/datasets` answers 404. That is not "forbidden" and not "absent":
a positive control in the same breath — the file listing for the dataset
`radar_knmi` already reads — returned 200 with the same key and base URL, so the
key works and the path is simply wrong. The open-data API serves files for a
dataset you can already name; it does not appear to enumerate datasets. The name
has to come from KNMI's published catalogue.

One caution carried forward for the KNMI side: that API key is **shared by every
unregistered user**, and walking timestamps with it earned a 429 earlier tonight.
The listing above cost exactly one request (`maxKeys=1&sorting=asc`). Whatever
does the archive walk must budget for strangers, not just for itself.

`radar_smhi` and `radar_knmi` both fetch only the current frame today, so the
archive reader is new code either way — but it is a fetch, not a new idea, and
`ops/ch_orient.py` is the judgement already.

Two things learned tonight apply when that is done:

* **The control must have margin, not just direction.** Switzerland's blind
  mask pointed the right way by 1% and was useless; MeteoSwiss centre the
  composite on their own radars, so flipping maps it onto itself.
* **Pick a statistic whose assumption you satisfy.** For Norway, "mean distance
  from a seen cell to the nearest radar" *preferred the 180° rotation*, because
  it assumes "seen ⇒ near a known radar" and the Nordic mosaic includes Swedish
  and Finnish radars I cannot locate. Only "near a known radar ⇒ seen" survives
  an incomplete site list.

  The numbers, since a margin claim is worthless without them. The statistic
  that *fails* Norway: mean distance from a seen cell to its nearest known
  radar — 318.6 km for the 180° rotation against 387.8 km read straight, i.e.
  it ranks the wrong answer first. The statistic that *holds*, "near a known
  radar ⇒ seen": **94.9% straight / 58.4% flipped vertically / 92.8% rotated
  180°.** So the vertical flip is excluded by 36 points and the 180° rotation
  is **not** excluded by 2.1 — Norway's honest status is "vertical flip ruled
  out, 180° open", never "verified". Report the margin per orientation, not one
  verdict for the check as a whole: an average over orientations would hide
  exactly the one that is undecided.

## How to resolve radar sites, since two routes were tried and one lies

Do **not** join WMO ids to NOAA's `isd-history.csv`: for Norway it returned 3 of
12 and two were wrong by 120 and 180 km, with no error — well-formed
coordinates, right country, believable latitude.

Do use **WMO OSCAR/Surface**, keyed by the ids BALTRAD's `odim_source.xml`
gives for each ODIM node, and **assert the registry's place name against
OSCAR's station name, refusing the row when they disagree.** That gave 5 of 5
for Switzerland and 9 of 13 for Norway, every one labelled `RADAR <place>`. The
guard is deliberately conservative: Norway's `noosl` ("Oslo") resolves to
`RADAR Asker`, which really is the Oslo radar, and is refused anyway. Losing a
true site costs less than accepting a wrong one.
