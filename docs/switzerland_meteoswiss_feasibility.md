# Switzerland (MeteoSwiss) — measured feasibility, 2026-08-13

Measured against the live service, not read off a description of it. Written
before any adapter exists. The expensive part of adding a country is the
georeferencing proof; the projection half of that **is** done and verified here
(`ops/somerc.py`), and the payload-layout half is **not**, for a reason that was
measured rather than assumed.

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

## The orientation control is named by the file, but is not usable yet

    how/nodes = WMO:06661,06699,06768,06726,06776

Five radars, named by the file itself — the forgery-proof control in principle,
since a product cannot fake where it is blind. Denmark's `dmi_orient.py` is the
template: it compares a flipped read against the real one, and there the wrong
orientation is off by ~113 km.

An earlier draft of this file said that made Switzerland's control *better than
Norway's*. **Measurement says otherwise** — see the section below. Naming five
radars is not the same as being able to locate them, and the mask here turns out
to be too symmetric to orient the array on its own. The claim was written before
the check was run, which is the habit this repo exists to break.

One caveat carried forward from today: **do not resolve those WMO numbers
through NOAA's `isd-history.csv`.** Tried for Norway this evening; it returned
3 of 12 and two were wrong by 120 and 180 km, silently. If a WMO join is used,
it must assert the station name against the expected site name and refuse the
row otherwise. The five Swiss sites (Albis, La Dôle, Monte Lema, Plaine Morte,
Weissfluhgipfel) are well documented by swisstopo/MeteoSwiss and should come
from a source that states them, not from a join that guesses.

## The projection — DONE, 2026-08-13 (`ops/somerc.py`)

Written and verified against numbers this repo did not produce.

**swisstopo's own worked example** (Zimmerwald, WGS84 → LV95). Their answer is
2602030.680 / 1191775.030; this module returns **7 cm east, 2 cm north** of it.
The residual is their point's 947 m ellipsoidal height, which `forward()` takes
as zero. The projection origin, fed as CH1903, lands on 2600000 / 1200000
exactly.

**The file's four corners** project to a clean grid:

| corner | easting | northing |
|---|---|---|
| UL | 2255000.2 | 1480003.0 |
| UR | 2964997.7 | 1480003.9 |
| LR | 2964999.2 | 839997.4 |
| LL | 2254999.9 | 839996.8 |

Width 709 998 m against the declared 710 000; height 640 006 against 640 000.
Agreement to ~6 m on a **1000 m** cell. The grid is therefore LV95
`E 2255000 → 2965000`, `N 1480000 → 840000`, 710 × 640 at 1 km, with row 0 at
the north — so `col = (E - 2255000)/1000`, `row = (1480000 - N)/1000`.

The residual is not noise on my side: MeteoSwiss's corner latitudes sit far
outside Switzerland (43.6–49.4 N, 2.7–12.5 E), where swisstopo's *approximate*
formulas — likely what produced them — degrade to metres. Inside the country
the agreement is centimetres, as the Zimmerwald check shows.

**The datum shift is applied and is not decoration.** `towgs84` is worth ~200 m
here, a fifth of a cell: small enough to look right, large enough to put the
weather in the wrong place. A test asserts that doing it and skipping it
*disagree*, so the correction cannot quietly become a no-op.

`assert_proj4()` compares values rather than the string, refuses a projdef that
merely *omits* a parameter rather than defaulting it, and every rejection is
fired on a projdef built to earn it. The tests themselves were fired four ways:
zeroing the datum shift, flipping the northing sign, and disabling either
half of the projdef guard each turn the suite red.

## What is NOT done: proving the payload is laid out as the coordinates claim

The corner check validates my arithmetic against the file's georeference. Both
sides come from the same file, so they agree whatever the payload does. The
control that cannot be forged is the blind mask against the radar sites --
Denmark's `dmi_orient.py`.

**Attempted tonight with the real site positions, and it does not work here.**
This is a measured negative, not a missing ingredient.

The five sites were resolved properly in the end. `how/nodes` gives WMO ids, and
**WMO OSCAR/Surface is keyed by exactly those ids**, so there is no name-guessing
join of the sort that returned confident nonsense for Norway:

| WMO | OSCAR name | lat | lon | elev |
|---|---|---|---|---|
| 06661 | ALBIS | 47.28417 | 8.51194 | 928 m |
| 06699 | LA DOLE | 46.42500 | 6.09917 | 1680 m |
| 06768 | MONTE LEMA | 46.04083 | 8.83333 | 1625 m |
| 06726 | PLAINE MORTE | 46.37056 | 7.48667 | 2937 m |
| 06776 | WEISSFLUHGIPFEL | 46.83500 | 9.79444 | 2840 m |

All five report territory Switzerland, all sit at plausible mountain-top
elevations, and the three the BALTRAD registry knows **agree by name** — the
free cross-check the Norway join failed.

And with those positions in hand the check still has no power:

    mean distance from a seen cell to the nearest radar
      as read          140.6 km        left-right flip  146.5 km
      up-down flip     142.0 km        180 rotate       146.0 km

As-read is the minimum in all four orientations, which is the right direction,
but by **1%** on the axis that matters. **A judgement whose two branches differ
by one percent has no more jurisdiction than one that only ever prints a single
word.** It would fire on noise.

The reason is structural and worth stating, because it will recur: the radar
cluster's centre is **E 2653919, N 1161002** and the grid's centre is
**E 2610000, N 1160000** — one kilometre apart on the north-south axis.
MeteoSwiss build the composite centred on their own network, so an upside-down
read maps the blind mask almost exactly onto itself. **The symmetry that makes
it a good product makes it useless as an orientation control.** Denmark's works
precisely because its radars sit asymmetrically in its domain.

Having a forgery-proof control's ingredients is not the same as the control
having power, and that has to be measured rather than assumed. It was assumed
in an earlier draft of this very file.

Two coordinate-free versions were tried first and are recorded for completeness;
both are weaker still:

* Centroid of the seen mask vs the centre of Switzerland: **35 km** as read,
  **38 km** flipped. A ratio of 1.1 is not a judgement, it is a coin landing on
  its edge.
* Blind fraction by row band, which is nearly symmetric:

      rows   0- 79  seen 39.1%      rows 560-639  seen 31.8%
      rows  80-159  seen 78.2%      rows 480-559  seen 80.9%
      rows 160-239  seen 94.5%      rows 400-479  seen 96.7%
      rows 240-319  seen 99.4%      rows 320-399  seen 99.9%

  An upside-down read produces almost the same profile.

So the mask alone cannot orient this array, and a check built on it would print
a verdict it had not earned -- the failure mode this repo keeps naming. It
cannot be rescued by better site data, because the site data is now correct and
complete. What would settle it is a comparison against an **independent
rendering** during rain — MeteoSwiss publish radar images for human eyes, which
is how Norway's chain was finally checked end to end (#108). That needs weather,
and tonight the whole domain was dry. Until then the payload layout is
**unverified**, and an adapter must say so rather than let the corner check
imply otherwise.

**A second thing that could not be checked tonight:** every Swiss city read
`0.000 mm/h` on the live frame, and so did Milan, Munich and Lyon. It was dry
across the whole domain. That is consistent with our own service calling Zürich
`CLEAR_NIGHT`, but it discriminates nothing -- when nothing is raining, the map
looks the same however it is drawn. The end-to-end look has to wait for weather.

## Summary

| | status |
|---|---|
| licence | CC-BY, registered in the catalogue |
| format | ODIM_H5 v2.4, h5py already a dependency |
| blind vs dry | explicit (`NaN` vs `0.0`) — no inference needed |
| cadence / latency | 5 min / under 2 min |
| discovery | clock-derived names, both directions checked |
| units | mm/h; needs MP inversion to reach the shared dBZ table |
| projection | **done** — `ops/somerc.py`, 7 cm vs swisstopo, corners to 6 m |
| datum shift | applied, and tested to be worth ~200 m rather than a no-op |
| grid geometry | LV95 E 2255000→2965000, N 1480000→840000, row 0 north |
| radar site positions | **resolved** — WMO OSCAR, keyed by the file's own ids, names cross-checked |
| payload orientation | **open, and the mask cannot fix it** — composite is centred on its own radars |
| end-to-end look | **not possible yet** — the whole domain was dry tonight |
| adapter | not written |
