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
| `radar_smhi` | SE | none | **unverified** |
| `radar_knmi` | NL | corner check only — same file on both sides | **unverified** |

So the honest count is **three verified, one partial, two unverified**, out of
six grid-indexing sources — not "three of twelve".

## Sweden and the Netherlands are the open risk

Both read a national grid and neither has a control independent of the file
they read. Neither is known to be wrong; the point is that **if either were
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

So Sweden needs an archived rainy hour, exactly as Switzerland did (four hours
out of the 14-day radar archive).

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
