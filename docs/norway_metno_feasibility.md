# Norway (MET Norway) — measured feasibility, 2026-08-13

Everything here was measured against the live service tonight, not read off a
description of it. Written down because the expensive part of adding a country
is the georeferencing proof, and that part is now done.

## What is published

`https://thredds.met.no/thredds/catalog/remotesensing/reflectivity-nordic/latest/catalog.xml`

    yrwms-nordic.mos.pcappi-0-dbz.noclass-clfilter-novpr-clcorr-block.nordiclcc-1000.<YYYYMMDD>T<HHMM>00Z.nc

* **PCAPPI reflectivity in dBZ** — `equivalent_reflectivity_factor`, units
  stated by the file as `dBZ`, `_FillValue 9.96921E36`.
* 1694 × 2134 cells at **1000 m**, 5-minute cadence, 576 frames listed (48 h).
* Newest frame at the time of measurement: `20260813T193000Z`, about **25
  minutes old**. Current, not an archive lag.
* Ships a real **`is_nodata`** mask, plus `is_blocked`, `is_seaclutter`,
  `is_groundclutter`, `clutter_probability`, `is_convective`. The nodata mask
  is what makes the orientation check possible: it is the one thing the product
  cannot forge, because it says where the radars are blind.
* Nordic mosaic — so it covers Sweden, Denmark and Finland as well as Norway.
  Norway is the new country; the overlap is a possible second opinion on three
  we already serve, which is a different job and not assumed here.

## Licence

met.no's own THREDDS page links **Norwegian License for Open Government Data
(NLOD)** and **CC BY 4.0**. Attribution belongs in `radar-data:` the way DMI's
does. Their guidance also asks for an identifying User-Agent with a contact
address, which every request here carries.

## Georeferencing — proved, not assumed

The file states its own projection:

    +proj=lcc +lat_0=63 +lon_0=15 +lat_1=63 +lat_2=63 +no_defs +R=6.371e+06

Tangent Lambert conformal conic on a **sphere** (R given, so no ellipsoid
maths). Axes, read from the file:

    Xc[0] = -796000    Xc[1693] =  897000     (increasing east, 1000 m)
    Yc[0] =  1125000   Yc[2133] = -1008000    (DECREASING, so row 0 is NORTH)

Row 0 being north is the usual convention and is therefore exactly the kind of
assumption that draws a scale-correct, fresh-stamped map of the wrong half of
the country. Here it was measured off the axis values.

**The check that matters.** I computed the LCC forward transform myself, turned
four cities into (row, col), and only then asked the file what latitude and
longitude it puts at those cells. The file's own 2-D `lat`/`lon` arrays
answered:

| city | computed cell | file says | actual | error |
|---|---|---|---|---|
| Oslo | 1460, 559 | 59.9183, 10.7506 | 59.9139, 10.7522 | < 0.6 km |
| Bergen | 1375, 266 | 60.3934, 5.3255 | 60.3913, 5.3221 | < 0.4 km |
| Tromsø | 379, 950 | 69.6503, 18.9559 | 69.6492, 18.9553 | < 0.2 km |
| Trondheim | 1069, 567 | 63.4298, 10.3920 | 63.4305, 10.3951 | < 0.3 km |

All four inside a single 1 km cell. The direction matters: the indices were
computed **before** asking, so the file confirmed my projection rather than
supplying it. Two independent rulers agreeing beats one ruler consulted four
times.

## Why this does not need an 11 MB download

Each frame is ~11.6 MB, which would be a rude and slow thing to fetch per
reader. THREDDS serves OPeNDAP, which subsets server-side:

    <base>.ascii?equivalent_reflectivity_factor[0][j0:stride:j1][i0:stride:i1]

A reader's window is 48 × 24 cells over ~280 km, i.e. one sample every ~11.7
cells — so a strided request returns about 1150 numbers instead of 3.6 million.
Point-sampling at the cell centre is what `window()` already does in every
other adapter, so this is the existing behaviour expressed as a server-side
subset rather than a local one.

`is_nodata` must be fetched over the same box, or "the radar sees nothing here"
and "there is no rain here" collapse into one answer — the failure this fleet
keeps meeting.

## Still open

* **Discovery — settled, with one caveat.** There is no `latest.xml` resolver
  (it 500s). `latest/catalog.xml` lists 576 frames (~200 KB) to learn one
  filename, so discovery goes by the clock, as DMI's does. Measured that
  "exists" actually discriminates:

      20260813T193000Z -> 200      (published)
      20260813T194500Z -> 404      (not yet; ~25 min publication latency)
      20260814T120000Z -> 404      (future)

  The caveat is the usual one: a name that is not published yet and a dataset
  that has been moved or withdrawn both answer 404. Walking back a bounded
  number of stamps and finding nothing must therefore print its own verdict
  and must not be reported as a clear sky.
* **Caching key.** Per-reader subsets must be shared between readers in the
  same place, or every request spends met.no's bandwidth: cache on (frame
  stamp, rounded centre, span, shape).
* **Orientation check in ops/**, on the pattern of `dmi_orient.py`, using
  `is_nodata` against the Norwegian radar sites.
* **Coverage box** and the dBZ floor: the shared `scripts/dbz.py` table applies,
  including the 7 dBZ floor, and must not be re-derived here.
