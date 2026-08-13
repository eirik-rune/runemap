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
| RainViewer tiles | both | **closed, permanently.** Their support answered 2026-08-13: "RainViewer no longer offers paid API plans or commercial licenses. That ended with the 2025 API transition... the free API... is limited to personal and educational use only - not company or commercial projects, even at low volume with attribution." There is no price to pay, so this is not "until we pay" -- it is a no. Enforced in `scripts/radar_second.py`: `draw()` returns None and says why | fine | draws, but may not be shipped |
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
     educational use only") and we are a company. I wrote "until we pay" here,
     and their answer removed that escape: there is no commercial tier to buy
     any more, so it is simply a no. REDEMET states a narrow one (do not display REDEMET images framed in
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
| Sweden | SMHI national composite (GeoTIFF, values not colours) | `SMHI opendata.smhi.se, CC BY 4.0` | dBZ from their own HDF5 gain/offset; UTM 33N projected here |
| Germany | DWD WN analysis | `Datenbasis: Deutscher Wetterdienst, Raster veraendert` | dBZ palette from their SLD; declines a window >25% no-data |
| Mumbai | **nothing** | -- | RainViewer is non-commercial and has no paid tier to buy (their support, 2026-08-13); IMD's images have no published geographic extent |

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

### Sweden (SMHI) -- the first source that hands us values instead of colours

Every other row makes us work out what a picture's colours mean. SMHI's
open-data file API publishes the national composite as a single-band GeoTIFF
whose pixels *are* reflectivity, and the companion ODIM HDF5 of the same frame
states the scale in its own attributes:

    /dataset1/data1/what: quantity=DBZH, gain=0.4, offset=-30.0,
                          undetect=0.0, nodata=255.0

so `dBZ = 0.4 * DN - 30`. `ops/smhi_scale.py` re-reads those attributes and
exits non-zero if any of them move -- fired by pretending our gain had drifted
to 0.5. A constant copied out of a file is a constant that can rot, and a wrong
gain does not break anything: the map still draws, in the wrong intensity,
looking entirely normal.

`undetect` and `nodata` are kept apart all the way to the character grid:
"looked, saw nothing" renders blank, "did not look here" renders `?`, and a
window more than 25% nodata is declined outright. Measured over Oslo: 48%
blind, declined -- which is what actually bounds the coverage, not the
rectangle.

The dBZ bands are **the same ones the German row uses** (19 / 28 / 37 / 46).
dBZ is physical, so one intensity has to draw one character whether the radar
is German or Swedish; per-source thresholds would make the scale depend on
which country the reader is standing in.

Licence: Creative Commons Attribution 4.0 SE, from SMHI's own terms page --
commercial use permitted, source must be named and modification indicated. Both
are printed, the second through the shared `radar-data-note` line.

The awkward part is the projection: the GeoTIFF is UTM zone 33 North, stated by
its own GeoKeys (3074 = 16033, 3076 = 9001 metres) and asserted rather than
assumed. `ops/utm.py` projects the reader, and its control is external -- SMHI
publishes four corner latitudes and longitudes in the HDF5, computed on an
entirely different grid (polar stereographic, 2 km). Every published corner
lands inside the GeoTIFF within a few cells, and the box they bound is the
raster to within 10 cells. A wrong zone is a hundred cells out, asserted
separately so the control is known to be able to fail.

Two things stated rather than smoothed over: the first version of the
containment test claimed one grid was a strict bounding box of the other and
failed by 8 cells at the north-east corner -- that is the rotation, not an
error, and the claim was rewritten rather than the tolerance widened to fit.
And the health probe caught `ModuleNotFoundError: runemap` on its first run, a
packaging fault 331 green tests could not see because they all ran with the
repo root importable, which is not a path a reader stands on.

One file serves the whole country, so this fetches once per refresh cycle for
every Swedish reader rather than once per sky. Measured: 0.84s cold for the
22 KB GeoTIFF, 0.01-0.15s to window it, 13 minutes old at the probe.

**Not used**: `wts.smhi.se` is also a WMS and carries the same composite, but
its layer list mixes openly-licensed layers with ones whose names literally
contain `officialuseonly`, while the service-level `AccessConstraints` says
nothing at all. A service-level silence does not grant what a layer name
refuses, so the file API -- which is unambiguously the documented open-data
product -- is what ships.

### Denmark (DMI): technically solved, blocked on terms I cannot read

Everything the adapter would need is published and costs 42 KB:

    GET /v1/radardata/collections/composite/items?datetime=<from>/<to>
    -> dk.com.202608131205.500_max.h5   (ODIM HDF5, 13 min old, 42 KB)

    /what   quantity=DBZH, gain=0.5, offset=-32.0, undetect=0.0, nodata=255
    /where  projdef=+proj=stere +ellps=WGS84 +lat_0=56 +lon_0=10.5666
            +lat_ts=56, xscale=500, yscale=500, and four corner lat/lons

so `dBZ = 0.5 * DN - 32` -- **different from Sweden's 0.4 / -30**, which is the
whole argument for taking every constant from the source that serves it.

It is **not shipped**, and the reason is the terms, not the technique:

  * `opendatadocs.dmi.govcloud.dk` answers 404 on every page, and
    `opendataapi.dmi.dk` points at `dmi.dk/frie-data`, which does not state
    them.
  * Secondary material quoting DMI says users "may not make changes to the
    actual data". If that is the wording it is aimed straight at what we do.
    We do not redistribute or alter their files, but we do redraw the values,
    and the permissive reading is not ours to pick.
  * The API answers **without an API key** -- and that is not permission. The
    same material says a key is required. An endpoint that does not enforce a
    rule has not waived it.

Asking them failed too, loudly: mail to `opendata@dmi.dk` **bounced**, `554 ...
rejected due to poor reputation of a domain used in message transfer` from
`mx04.statens-it.dk`. Our own authentication is fine -- SPF `v=spf1 mx -all`
passes from the MX itself, DMARC is published, and outbound is DKIM-signed
(`d=echorune.net; s=ls2607`, verified on a probe). The Danish state mail system
is scoring a young domain from a datacenter address, which is the same shape as
every other reputation wall this year.

**A near miss worth keeping**: I first concluded we were not signing at all,
because `grep "d=echorune.net" /var/log/mail.log` returned 0 -- and was about
to "fix" a working config. opendkim logs `s=/d=` for messages it **verifies**,
not for ones it **signs**. The log answers *what did I check*; I asked it *what
did I send*. Testing before changing is what caught it.

### Norway (met.no): a different quantity, and a size problem

`thredds.met.no/thredds/catalog/remotesensingradaraccr/` carries a live daily
file, updated within the last ten minutes, on **UTM 33 North at 1 km** -- so
`ops/utm.py` would work unchanged. Two reasons it is not next:

  * the product is `sri-acrr-1h`, **one-hour accumulated rainfall**, not
    instantaneous reflectivity. Drawing it under a line that says `radar: obs`
    would be the JMA-forecast mistake in another costume: an honest number
    answering a different question than the one the reader asked.
  * the file is 15 MB per day and grows; a reader's window would have to come
    through the THREDDS subset service or its ncWMS rather than the file.

The earlier refusal of `public-wms.met.no` (their own page says demonstration
only) is a statement about that server, not about THREDDS, and should not be
carried across without checking.

### Measured, deliberately not shipped

- **Netherlands (KNMI): three claims corrected, one route left open.**
  The original refusal was "no published mapping from colour to rain rate".
  That is true of their legend and false of their service: the layer is
  `queryable="1"` and GetFeatureInfo answers `image1.image_data ... mm/hr`,
  unit declared by the server. So the value is published even though the
  mapping is not.

  Three things I wrote down on 8/13 and then measured out of existence:

  1. *"`/nearest` means the picture is drawn without interpolation, so a colour
     table can be exact."* No. In ADAGUC the suffix is the resampling method,
     not the colour scale: `precip-blue/nearest` and `precip-blue/bilinear`
     return **the identical 73 shades**. What is discrete is the *style* --
     `radar/nearest` renders 6 colours (white / grey / dark grey / pink / red)
     and is also what the server falls back to for a style name we invent.
  2. *"A style name we invented returns 200 with an empty PNG."* That was
     measured over a dry country, so it answered "what does a bogus style do
     when there is nothing to draw". With weather under it, a bogus style
     returns a **different, non-empty image** -- the default style's rendering.
  3. *"GetFeatureInfo tells us what a pixel means."* It tells us what a *cell*
     means, at the resolution of the request. Asked in a 384px window over
     10.85 degrees, a red pixel came back 3.6 mm/hr; the same point in a window
     of 0.02 degrees came back **27.3 mm/hr**. Colour and value are only
     measurements of the same thing when one image pixel is one grid cell, and
     even at ~0.9 km/px (the RAD_NL25 grid is 1 km) the bands still overlap:
     the sentinel `0.000365 mm/hr` -- their "no echo" value -- turns up under
     **every** colour, which means a share of the queries land on a cell that
     is not the one that was drawn. Pinning `time=` on both requests sharpened
     the means into the right order (white < grey < dark grey < pink < red,
     red reaching 27 mm/hr) but did not remove the overlap.

  So `ops/value_probe.py` returns REFUSED for KNMI and that verdict stands.
  Dropping the sentinel would make the bands look better and would be exactly
  the "loosen it until it agrees" step this file exists to refuse.

  **The route that is still open is the Japanese one.** `radar/nearest` gives
  six discrete classes, which is `ops/colour_order.py`'s home ground -- depth
  and adjacency, a derivation that can fail. Run it against
  `styles=radar/nearest` when it is raining over the Netherlands. The value
  probe's contribution is that it found the discrete style and produced an
  independent expectation of the order to check the derivation against.
- **Open-Meteo, NOAA GOES**: failed the product test, see above.

### Open: the REDEMET ceiling measures two different things at once

`radar_redemet.MAX_AGE = 2700` (45 min) was derived this morning from **one
pull** across 18 radars: 13.4 / 19.6 / 23.2 minutes old, min/median/max. Six
hours later a single pull read **13.3 / 23.9 / 52.7** -- the median barely
moved, the maximum more than doubled, and Sao Paulo's own radar (`sr`) sat at
52.7 with `be` at 40.9 while everything else was under 31. The mirror was
running and succeeding the whole time; the lag is upstream, on individual
radars.

The probe correctly reported NO-MAP. What it exposed is that the constant is
answering two questions with one number:

  * **is the mirror alive?** -- an ops question, and the reason the ceiling was
    written ("a dead timer's ages climb past it within one period")
  * **is this frame worth drawing?** -- a product question, which we already
    answer honestly a different way, by printing `obs age` and warning past
    `RADAR_STALE_MIN`

Those are the two orthogonal axes this repo already refused to compress once,
for `predict` and `stale`. Raising the number would blunt the first question;
keeping it silences a working radar during upstream lag.

**Not changed yet, on purpose.** Two snapshots are not a distribution, and
setting the number from a snapshot is exactly how it got here. `ops/redemet_pull.py`
now records min/median/p90/max on every ten-minute pull, so the next version of
this constant can come from data. Nothing reads that field yet.

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

## Swept and what each one turned into (2026-08-13)

`ops/wms_sweep.py` asks a list of candidate national services three questions
in the order that fails fastest: is it a WMS, does it declare a radar layer,
and what does it say about fees and access. It decides nothing -- everything
below still needed the colour mapping, the coverage rectangle, and a GetMap
that answers.

| candidate | capabilities | verdict |
|---|---|---|
| Belgium, RMI `opendata.meteo.be/service/radar/wms` | **200**, one layer `belgian_rainfall_composite`, `Fees=none`, `AccessConstraints=none`, a 5-minute `time` dimension (so a real observation stamp, unlike NEXRAD and ECCC where we can only honestly report our own fetch time) | **advertised but not served**: GetMap, GetLegendGraphic and GetStyles all answer 403 while GetCapabilities answers 200 from the same address, the same user agent, the same second. Positive control in the same run: the identical code path got a PNG from FMI. So this is not our egress and not our client -- they publish a layer they will not hand us. Next step is their portal's terms, not another request shape |
| Switzerland, swisstopo | 200, 2029 layers | **no live radar**. The 24 "radar-ish" names are geology and climate normals; the only MeteoSwiss precipitation layers are `klimanormwerte-niederschlag_1961_1990` and `_aktuelle_periode`. The first run of the sweep reported "GetMap ok" here -- for `ch.swisstopo.geologie-reflexionsseismik`, matched on "refl". The tool names the layer it probed now |
| Estonia, Maa-amet | 200, 108 layers, `Fees=tasuta / none` | no radar layer; that server is base mapping |
| Norway, met.no | 503 | separately refused already: their own page says the WMS is for demonstration, not operational use |
| Poland IMGW, Czech CHMI, Slovenia ARSO | 404 / DNS / 499 | the endpoint I had was wrong, not the service. Unfinished, not refused |
| UK Met Office, Australia BOM | 403 on capabilities | both front their open data with a registered API key. Not refused on principle -- unasked |
