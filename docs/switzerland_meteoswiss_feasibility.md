# Switzerland (MeteoSwiss) — measured feasibility, 2026-08-13

Measured against the live service, not read off a description of it. Written
before any adapter exists, because the expensive part of adding a country is
the georeferencing proof and that part is *not* done here — everything else is.

## How it was found

Not by guessing a URL. The rule that worked for Czechia and the Netherlands is
to start from a machine-readable catalogue and its registered licence, and it
worked again: `data.geo.admin.ch`'s STAC catalogue lists
`ch.meteoschweiz.ogd-radar-precip`.

One trap on the way in, the same one that returned a three-day-old "newest"
frame for Denmark: `?limit=500` returns **100** collections and a `next` link.
Taking the first page as the catalogue would have found nothing, and finding
nothing looks exactly like nothing being there. Paginated: **508 collections**,
and the radar ones are on later pages.

Austria was checked first and rejected on measurement, not impression:
GeoSphere's open API publishes only `inca-v1-1h-1km` **historical** grids. No
near-real-time product, so it cannot serve a live map whatever its licence says.

## Licence

The STAC collection registers `"license": "CC-BY"`, and links MeteoSwiss's own
open-data page. That is the registered, machine-readable answer, which is the
standard this fleet already holds itself to — a second-hand summary of terms is
what nearly made me refuse Denmark wrongly.

## The product

`ch.meteoschweiz.ogd-radar-precip` carries three products, ~257 files each per
day. Asset keys are `<prod><YY><DDD><HHMM>vl.001.h5`:

* **`rzc`** — `CHRZC`, the 5-minute precipitation *rate*. **This is the one.**
* `cpc` — CombiPrecip, radar blended with rain gauges, 60-minute accumulation.
  Better science, wrong question: an hour's total does not answer "is it
  raining on me now".
* `tzc` — the side-view variant.

Read from a live frame (`rzc262252120vl.001.h5`, 41 863 bytes):

    Conventions        ODIM_H5/V2_4
    what/object        COMP        (composite)
    what/source        ORG:215, CTY:644, CMT:MeteoSwiss (Switzerland)
    what/date,time     20260813 212000
    where/xsize,ysize  710, 640      xscale,yscale 1000.0 m
    data1/what         quantity=RATE  unit=mm/h  gain=1.0  offset=0.0
                       undetect=0.0   nodata=NaN

**ODIM_H5 v2.4 — the same family as Denmark's**, so `radar_dmi.py`'s reading
approach carries over and `h5py` is already a production dependency.

**The nodata/undetect distinction is explicit and structural**, which is rare
and valuable: `NaN` means the radars cannot see this cell, `0.0` means they can
see it and there is no rain. That is the exact conflation this fleet keeps
meeting — Norway needed a spatial-shape argument to separate the two, and Sweden,
Czechia and the Netherlands each drew clear air as light rain until the 7 dBZ
floor went in. Here the file simply says which is which. Counted on that frame:
345 005 dry cells, 101 993 blind, the rest rain.

## Units: this source is mm/h, and the fleet speaks dBZ

Every other adapter classifies through the shared `scripts/dbz.py` table. Two
choices, and the fleet's own history decides it: a table copied into three
modules is what produced three countries drawing clear air as rain, so there
must not be a second ramp. Converting mm/h to dBZ with Marshall-Palmer
(`Z = 200 R^1.6`) and classifying through the shared table keeps one ramp.

Worth noting what that conversion does to the floor, because the number lands
somewhere suspiciously clean: the shared 7 dBZ floor is **0.0999 mm/h**, i.e.
0.1 mm/h. And the floor will matter here — the most common non-zero values in
the live frame are 0.01 and 0.02 mm/h, far below it, which is what clear-air
clutter looks like.

This conversion is a derivation, and per this repo's rule a derivation must be
able to refuse. MeteoSwiss derive RZC from reflectivity with **their own** Z-R
relation, which is not necessarily Marshall-Palmer, so inverting with MP is an
approximation and must be labelled one. It should be checked against a frame
where an independent source says how hard it is raining, not asserted.

## Discovery: by the clock, and it is fast

The STAC item for a day carries ~770 assets (~all three products); fetching that
to learn one filename would be rude and slow. Clock-derived names work, and the
ruler was checked in both directions rather than assumed:

    21:15 -> 206      21:30 -> 403
    21:20 -> 206      21:35 -> 403
    21:25 -> 206

at 21:26:53 UTC. **Publication latency is under two minutes** — the freshest
source in the fleet by a wide margin (MET Norway runs ~25 minutes).

**`403` here means "no such key", not "you are blocked".** The bucket denies
listing, so a missing object answers 403 where every other source in this fleet
answers 404. Writing that down because I have read a 403 as a ban before and
built a whole self-consistent story on it. A first attempt here produced six
403s that were entirely my own doing — a mistyped filename with one digit too
many — and the tell was that **a frame I had already downloaded also answered
403**. Positive control before alarm, every time.

## The orientation control exists, and it is better than Norway's

    how/nodes = WMO:06661,06699,06768,06726,06776

Five radars, named by the file itself. This is the forgery-proof control that
Norway's adapter still lacks: a product cannot fake where it is blind. Denmark's
`dmi_orient.py` is the template — its check compares a flipped read against the
real one and the wrong orientation is off by ~113 km.

One caveat carried forward from today: **do not resolve those WMO numbers
through NOAA's `isd-history.csv`.** Tried for Norway this evening; it returned
3 of 12 and two were wrong by 120 and 180 km, silently. If a WMO join is used,
it must assert the station name against the expected site name and refuse the
row otherwise. The five Swiss sites (Albis, La Dôle, Monte Lema, Plaine Morte,
Weissfluhgipfel) are well documented by swisstopo/MeteoSwiss and should come
from a source that states them, not from a join that guesses.

## What is NOT done: the projection

    +proj=somerc +lat_0=46.95240555555556 +lon_0=7.439583333333333 +k_0=1
    +x_0=2600000 +y_0=1200000 +ellps=bessel
    +towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs

Swiss oblique Mercator on the **Bessel** ellipsoid, with a three-parameter
datum shift to WGS84. This is a genuinely new projection for this repo —
`ops/stereo_oblique.py` (Denmark), `ops/utm.py` and `scripts/lcc.py` (Norway)
do not cover it — and `pyproj` is not installed in production, so it has to be
written and verified the way the others were.

Two things make that tractable:

* The file states its four corners, so the projection can be checked against
  the file's own numbers rather than against my arithmetic:

      LL 43.6290, 3.16878     LR 43.6190, 11.95560
      UL 49.3744, 2.68942     UR 49.3633, 12.46230

  Projecting those four corners must produce a 710 × 640 km rectangle on a
  1 km grid. That is a real check and it would catch a wrong ellipsoid, a wrong
  origin or a flipped axis.

* The datum shift must not be skipped silently. Ignoring `towgs84` on CH1903
  displaces positions by enough to matter relative to a 1 km cell, and the
  failure mode is the dangerous one: a scale-correct, fresh-stamped map with
  the weather in slightly the wrong place. If the shift is approximated, the
  approximation belongs in a comment with its measured error, not in silence.

The corner check validates my arithmetic against the file's georeference. As
with Norway, it **cannot** catch the data array being laid out differently from
what the coordinates claim — both sides come from the same file. That is what
`how/nodes` is for, and unlike Norway, here it is available on day one.

## Summary

| | status |
|---|---|
| licence | CC-BY, registered in the catalogue |
| format | ODIM_H5 v2.4, h5py already a dependency |
| blind vs dry | explicit (`NaN` vs `0.0`) — no inference needed |
| cadence / latency | 5 min / under 2 min |
| discovery | clock-derived names, both directions checked |
| units | mm/h; needs MP inversion to reach the shared dBZ table |
| projection | **not started** — somerc on Bessel, plus datum shift |
| orientation control | available (`how/nodes`, 5 radars) |
