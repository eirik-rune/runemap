# A second source for the skies our upstream returns zero frames for

Written 2026-08-13. Every number here came from a command run that day; where a
number is somebody else's measurement it says whose. This file exists because
the measurements were made in one long session and **a session is compacted** --
the numbers would otherwise survive only in my context, which is the one place
they are guaranteed not to survive.

## Why

Eirik's paired sampler (`ops/paired_ab.py`, 10-minute cron), 06:17 UTC,
`control_void=0` (chiangmai and beijing both n=20, so the ruler was measuring the
far end and not our egress):

| city | upstream | second source |
|---|---|---|
| mumbai | `status=failed`, 0 frames | 1665 precipitation pixels |
| saopaulo | `status=failed`, 0 frames | 998 pixels |
| london | ok, 6 frames | 0 pixels -- **undecidable**, not "the source has nothing" |
| paris | ok, 6 frames | 5 pixels |

Zero frames is the only state where the reader genuinely cannot see rain: a
partial list of 4-6 frames still draws a 24-row map (verified at the public
boundary). So the work is scoped to **mumbai and saopaulo**, not to the four
cities that flicker.

## The candidates, and what each is blocked on

| source | covers | licence | egress from prod | product test |
|---|---|---|---|---|
| RainViewer tiles | both | free tier is "personal or educational use only"; we are a company. Commercial pricing is not published. Asked `support@rainviewer.com` 06:31 UTC (mail log `250 ... status=sent`) | fine | draws; palette maps across all five intensity levels |
| REDEMET (Brazilian air force) | saopaulo | Terms of Use: content is copyright (Berne), framing REDEMET images in other sites is **not** authorised, links only to the main page. A derived 48x24 text grid is not named either way. Asked `redemet@decea.gov.br` 06:46 UTC (`250 ... Queued mail for delivery`) | **blocked** -- `api-redemet` and `estatico-redemet` both time out from prod, 200 from Tokyo | draws; the API hands us `lat_min/lat_max/lon_min/lon_max` per radar, so no polar calibration is needed |
| IMD (India) | mumbai (Veravali radar, 73 km from the city) | **nothing forbids it**: the disclaimer carries only `(c) Ministry of Earth Sciences`; `copyright.php` / `website_policy.php` / `policy.php` / `terms.php` are 404. Silence is not a prohibition either -- see the note below | fine | per-station PPI GIFs in polar coordinates -- station coordinates and range calibration would have to be built |
| NOAA GOES-19 `ABI-L2-RRQPEF` | saopaulo (Americas only) | **US Government work, public domain. No gatekeeper at all** | fine, straight from prod | **fails, see below** |
| Open-Meteo | both | data CC BY 4.0, commercial requires a paid plan | fine | **fails, see below** |
| DWD (Germany) | germany | commercial use allowed: `Fees=none`, `AccessConstraints=dwd.de/copyright` -> CC BY 4.0 with a source note, and their template requires that note even for a change of data format. **Shipping** | fine | draws; needs their dBZ palette and a no-data share guard |
| FMI (Finland) | finland | `Fees NONE`, `AccessConstraints NONE` in their own capabilities. **Shipping** | fine | draws at 6 km/char; needs their palette, the scale ends in pink |
| KNMI (Netherlands) | netherlands | `Fees "no conditions apply"`, `AccessConstraints None` | fine | draws, but publishes no machine-readable colour map and its default style is greyscale plus red -- intensity would be a guess |
| MET Norway radar API | norway | their THREDDS WMS page states it is for demonstrations only, not operational use | fine | `5level_reflectivity` exists, but the images carry no georeference and have the map baked in |

This table is the part that rots: it was written when everything was blocked,
and by the end of the same day three rows had moved. If a row here disagrees
with `scripts/radar_wms.py`, the code is the fact and this is a stale sentence.

## The two that failed the product test, with the ruler checked first

**Open-Meteo (model field, not radar).** Same instant, same 24x12 grid:

- mumbai: radar 41 wet cells, model 144, overlap 21.
- saopaulo: radar 27 wet cells in a clear band, **model 0 anywhere**.

The agreement rate for saopaulo is 91% and it is worthless: the denominator is
full of dry cells and the model missed 27 of 27 of the only thing the reader
cares about. Report hits and misses, never agreement.

**NOAA GOES rain rate.** 13 pairings over two hours, saopaulo, one every ten
minutes (both sides are third-party archives, so this was back-sampled -- no
waiting and no touching our cache):

```
radar wet cells, summed   146
also wet on satellite       1     -> 1%
satellite-only cells       13
```

Before believing that, the reprojection was checked with a positive control:
find the full-disk maximum (100.00 mm/h at 9.367N 86.227W), convert it back to
lat/lon, then push it forward through the exact formula the sampler uses. It
lands on **the same pixel, offset (0,0), reading 100.00 mm/h**. So the 1% is a
property of the data -- satellite QPE is blind to the shallow warm rain these
readers were standing under -- and not a geometry bug of mine.

A second run twenty minutes later, over a window shifted by two granules,
gave 0 of 135. Both runs are reported rather than the kinder one.

Reproduce: `ops/pair_radar_vs_satellite.py`.

## Consequences

- **The one source with no gatekeeper cannot see the rain** (GOES, above), so
  every source that CAN see it belongs to somebody. That is a fact about the
  sky, not a reason to stop.
- **"Unknown terms" is not a blocker, and an earlier version of this file said
  it was.** bob 8/13: silence is not prohibition, and a standard that stops us
  on silence would stop us existing -- our own subjectivity was never granted by
  anyone either. The operative questions are only these three, and only the
  third can actually block:
  1. do we push a cost onto them? (a 10-minute prefetch behind a cache is
     lighter than one person with a browser -- no)
  2. do we pass their work off as ours? (we attribute, with a link -- no)
  3. did they **state** a restriction? RainViewer states one ("personal or
     educational use only") and we are a company, so that one binds until we
     pay. REDEMET states a narrow one (do not display REDEMET images framed in
     another site) and a derived character grid is not that image. IMD states
     nothing, so nothing blocks it.
- Buying an egress before a licence is settled buys a machine that waits: the
  Brazilian path needs a non-datacentre egress, but only if we are allowed to
  use it at all.
- A key is not a licence. We hold a REDEMET API key (issued three minutes after
  a plain-form request) and have not used it for anything but reading the terms.

## Geometry notes for whoever builds this

- **The city sits on a tile seam.** At z6: mumbai at 0.96 of its tile's width,
  london 0.98, paris 0.02 of its height. A single-tile fetch draws a
  normal-looking map with half the rain missing and reports nothing. Derive the
  tile rectangle from the span you intend to draw (`scripts/radar_rainviewer.py`).
- **Zoom 8 serves one identical image for every coordinate** -- (177,113),
  (178,113), (177,114) all return 200, 3269 bytes, identical sha256. It was
  caught only because two different cities produced identical ink counts.
- Serial 3x3 tile fetching measured 7.4-8.1s against a 3s reader budget; z7 with
  a thread pool is 0.82-1.25s for 4-6 tiles at 8-12 km per column. Prefetching
  is not an optimisation here, it is the precondition (issue #42).

## What is actually serving readers (2026-08-13, verified from production)

| sky | source | credit line | measured |
|---|---|---|---|
| USA | NWS NEXRAD via IEM | `NWS NEXRAD via mesonet.agron.iastate.edu` | 0.7-1.2s, 5.8 km/col |
| Canada | ECCC GeoMet | `Environment and Climate Change Canada geo.weather.gc.ca` | 0.7s |
| Finland | FMI | `Finnish Meteorological Institute en.ilmatieteenlaitos.fi` | 6 km/char; 1.8s cold, 0.20-0.35s cached |
| Brazil | REDEMET, 18 of 29 radars mirrored | `REDEMET/DECEA redemet.decea.mil.br` | served off local disk |
| Germany | DWD WN analysis | `Datenbasis: Deutscher Wetterdienst, Raster veraendert` | dBZ palette from their SLD; declines a window >25% no-data |
| Mumbai | **nothing** | -- | RainViewer states non-commercial; we are a company |

Every one of these is a fallback: the primary upstream wins whenever it has
frames, and the absence of a `radar-data:` line is how a reader can tell which
one drew.

### Germany, and how the colour was settled

It shipped once the question changed from "what is this magenta" -- which
neither DWD's style document nor its legend answers -- to **does it move**. Two
frames 105 minutes apart are pixel-identical in every magenta pixel, at four
cities, while the echo around them changed; over Munich 7071 of 7071 visible
pixels were static. Rain moves, furniture does not, so it is declared no-data
alongside their grey. Their real 75-85 dBZ pink sits 51 counts of green away
and stays rain -- pinned by a test, because that near-miss is the whole danger.

Two things followed:

- **`max_nodata_share`.** Their composite fades out past the border instead of
  stopping. Berlin 0.3% no-data, Strasbourg 4.2%, Zurich 22%, Prague 33%,
  Copenhagen 37%, Vienna 67%. Above 25% we decline, because a window two thirds
  blind renders as a clear sky.
- **Attribution is not just a name.** Eirik read the licence pages after this
  shipped: DWD's template (vorlagen_quellenangabe.html, section 7 DWD-Gesetz)
  requires a source note even for a change of data FORMAT, and CC BY 4.0
  separately requires indicating changes. A PNG turned into a character grid is
  exactly that, so every drawn map now also carries
  `radar-data-note: redrawn from the source frames as a text grid`.

### Measured, deliberately not shipped

- **Netherlands (KNMI).** Licence is clean (Fees "no conditions apply",
  AccessConstraints "None") and the map draws, but GetStyles answers 500 and
  the default style is greyscale plus red: over Amsterdam, 2509 visible pixels
  are white / grey / dark grey / pink / red. Our ramp reads the first three as
  level 1, so every intensity below "red" would reach a reader as drizzle.
  **The Japanese route now applies here** -- derive the order instead of the
  rain rates -- but the attempt on 8/13 returned `INSUFFICIENT`: the
  Netherlands was dry, one colour cleared the pixel floor over six frames and
  three cities. That is a measurement waiting for weather, not a conclusion.
  Re-run `ops/colour_order.py` against KNMI when it is raining there.
- **Open-Meteo, NOAA GOES**: failed the product test, see above.

### Constants that must come from the source, not from the last source

- **REDEMET frame ceiling is 45 min, not 30.** Measured across all 18 mirrored
  radars in one pull: at fetch time the frames were already 13.4 / 19.6 / 23.2
  min old (min / median / max). Plus the 10-minute mirror period, an ordinary
  frame is 23-33 min old when a reader asks. The old 30 was copied from
  RainViewer, which has almost no latency of its own, and it refused most of
  the cycle with nothing wrong anywhere.
- **WMS has no frame id**, so its cache is keyed by refresh cycle
  (`RUNEMAP_WMS_REFRESH`, 300s) -- one fetch per sky per cycle rather than one
  per visitor, which is what makes the "we do not push a cost onto them"
  answer true in code and not only on this page.

### Two failures worth not repeating

- A palette that only worked in the window production never uses. Production
  sets `RUNEMAP_SPAN_KM`, so every request renders through
  `ascii_radar_centered()`; `classifier` had been added to the other function
  only. Finland drew nothing for an hour while the tests stayed green.
- The credit line was a second, hand-maintained copy of what each adapter
  already declares, so Finland shipped credited as a bare "FMI". A duplicated
  table does not fail when it falls behind -- it under-credits somebody whose
  data we are using.

## India, 8/13: the half that was published, and the half that is not

`reactjs.imd.gov.in` runs a GeoServer (Fees NONE, AccessConstraints NONE) whose
WFS layer `imd:radar_station_status` hands out all 39 IMD radar stations as
GeoJSON -- code, name, latitude, longitude, and a status flag with the time
that station's image was last updated. 28 were updating when this was written.
Mumbai is covered by **Veravali (vrv), 73 km from the city, updating**.

That kills the part of the India problem I had called expensive: the station
coordinates were never something to guess, and I had guessed four of them at a
national met service to find one. `ops/imd_stations.py` reads them properly.

What is still genuinely unpublished is the **georeference of the images**. The
products are animated GIFs (`mausam.imd.gov.in/Radar/{caz,ppi,ppz,sri}_{code}
.gif`), there is no GeoTIFF or PNG variant, and IMD's own radar page does not
put them on a map -- it loads Leaflet only to place station markers. So nobody,
including IMD's own website, is publishing the extent of that picture.

Doing India therefore means registering the image against known geography
(Mumbai's coastline is the obvious anchor) and solving for the scale rather
than assuming a standard range. That is real work, but it has a check that can
fail -- the coastline either lines up everywhere or it does not -- which is the
only kind worth starting. It is not started.

## Japan, 8/13: shipped, on an order derived rather than typed

Established, all by measurement:

- **The tiles work and are plain XYZ.** `targetTimes_N1.json` lists frames every
  5 minutes; `.../nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png`
  returns real 256px tiles over Tokyo at z6 (2254 / 5662 / 1470 / 798 bytes for
  the four tiles -- different sizes, so genuinely different content). Our
  existing tile geometry (`radar_rainviewer.plan`) computes the rectangle
  unchanged.
- **The licence permits it.** JMA content is under the Public Data Usage Terms
  v1.0 unless marked otherwise: attribution required, modified content must be
  labelled as modified and must not be presented as official government
  material. We already print both the source and the change notice.
- **One rule to respect:** the nowcast contains forecast frames, and the
  Meteorological Business Act regulates forecasting. Use only frames where
  `validtime == basetime` -- which is also the only thing our product claims to
  show.
- **A trap, pinned here before it bites:** asking for zoom `64` instead of `6`
  returns **200 with a valid 334-byte PNG**. Same family as the RainViewer z8
  image that was identical for every coordinate. Any adapter must assert the
  zoom it asked for, not merely that bytes came back.

They publish no colour -> intensity mapping I could find (not in the tile
bundle, not in `contents.json`), which is exactly what keeps KNMI out. The way
past it was to notice that **our grid needs an ORDER, not millimetres**, and an
order is derivable from the pictures (`ops/colour_order.py`):

- **depth** -- heavier cores sit further inside the precipitation region. Over
  192 tiles: 1.89 / 4.03 / 5.52 / 5.53 / 5.73 / 6.34 / 7.18 / 9.90 mean erosion
  depth, in scale order.
- **adjacency** -- a scale is a gradient, so each class borders its scale
  neighbours more than anything distant. All eight do.

Depth alone did not earn the middle: two gaps are **0.014 and 0.203**, which is
not a separation. Adjacency settles those, and it is a real check rather than a
decorative one -- swapping either fragile pair makes it REFUSE (measured, both
swaps, 2 of 8 classes each). The two blues share a level in the shipped
palette anyway, so nothing a reader sees rests on the distinction the
derivation was least sure about.

Three things in that hour cost real time and none of them failed loudly:

- **z7 is empty.** JMA serves data at z6 and z8; at z7 every tile over Tokyo is
  the 334-byte fully transparent PNG. RainViewer's default zoom is 7 -- taking
  the default would have shipped a Japan whose sky is permanently clear.
- **Their tiles are 256px, the shared mosaic assumed 512.** The result was a
  regular blank band beside every tile, which renders as bands of "no rain" and
  looks like weather.
- **The cache key did not name the zoom.** After moving z6 -> z8 the adapter
  kept returning the z6 mosaic, identical art and identical km/col, so the
  change looked like it had done nothing. A key missing a parameter does not
  fail; it answers an older question confidently.

All three are the same shape as the REDEMET freshness ceiling this morning: a
constant that belonged to a different producer. `plan()` and `fetch()` now take
the ceiling and the tile size per service.

Coverage is three rectangles, not one: latitude and longitude have to constrain
each other or the box that reaches Yonaguni (122.9E) also holds Seoul, and the
two-box version reached far enough north-west to hold Vladivostok. The test
caught that, not my reading of it.
