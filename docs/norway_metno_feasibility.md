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
* ~~**Caching key.**~~ Done: two shared caches (stamp 60 s, window 150 s),
  keyed on (frame stamp, box). First reader 3.6 s, every reader after 0.006 s.
* **Orientation check in ops/** — still open, and worth being precise about why,
  because I nearly recorded it as done.

  The projection test in `tests/test_radar_metno.py` computes four cities into
  (row, col) and checks the file's own `lat`/`lon` arrays agree. That validates
  **my arithmetic against the file's georeference** — a real check, and it
  would catch a wrong proj4, a wrong origin or a flipped Y axis in my code.

  It cannot catch the failure `dmi_orient.py` exists for: the data array being
  laid out differently from what the file's own coordinates claim. Both my
  computed cell and the `lat`/`lon` arrays come from the same file, so they
  agree with each other whatever the payload does. Catching that needs a
  control the product cannot forge — the `is_nodata` mask against the
  Norwegian radar sites, exactly as Denmark's does.

  Not "mostly covered". Two different questions, and only one is answered.

  **Where the forgery-proof control lives.** The file names its own
  contributors, so the site list need not be typed from memory:

      mosaic_info:nodes = "norsg,noand,nober,nobml,nohas,nohgb,nohur,nohfj,
                           norsa,norst,nosmn,fianj,...,sevil"
      mosaic_info:missing_nodes = "nosta,selek"

  `missing_nodes` is the interesting half: two radars did NOT contribute to
  this frame, so their coverage should be a hole in `is_nodata` that the other
  radars do not fill. A product cannot forge where it is blind, and it
  certainly cannot forge a hole that moves when a different radar drops out.

  The gap is coordinates: these are ODIM node codes and the file does not carry
  their lat/lon, so somewhere publishing Nordic radar positions has to be found
  first (DMI shipped per-radar volume files, which is what made Denmark's check
  easy). Until then the check would have to fall back on "the seen area must
  lie in the Nordic latitude band, and the flipped read must not" -- weaker
  than Denmark's, and it should be labelled as weaker rather than counted as
  the same thing.

  **Searched, 2026-08-13.** "Blocked" had only been measured against met.no, so
  it was worth one real look elsewhere before recording it as a limit.

  BALTRAD's `config/odim_source.xml` (the ODIM registry these codes come from)
  resolves every node to a place name and a WMO number, `nosta` included:

      <nosta plc="Stad"  rad="NO38" wmo="01206">
      <nohur plc="Hurum" rad="NO39" wmo="01498">

  So the names are solved. The coordinates are not, and the way that attempt
  failed is worth more than the attempt.

  Joining those WMO numbers to NOAA's `isd-history.csv` returned three hits out
  of twelve -- and **two of the three are wrong**:

  | node | ODIM place | ISD said | ISD position | truth |
  |---|---|---|---|---|
  | nohas | Hasvik | HASVIK-SLUSKFJELLET | 70.600, 22.450 | agrees |
  | nohur | Hurum | MAGNOR | 59.967, 12.217 | ~120 km off, on the Swedish border |
  | norst | Røst | ROTVAER | 68.367, 15.950 | ~180 km off |

  The WMO numbers in the ODIM registry do not index ISD reliably -- reassigned,
  or a different numbering entirely. Nothing errored. The join returned
  well-formed coordinates in the right country at a believable latitude, and had
  they been fed to the orientation check, the check would have run, printed a
  verdict, and been wrong -- while looking exactly like Denmark's, which works.

  The tell was free and I nearly did not use it: the registry carries a place
  name beside the number, and *the names disagree*. So if this route is ever
  taken up again, **the join must assert that the ODIM place name matches the
  station name, and refuse the row when it does not** -- 1 of 12 survives that,
  which is the honest yield, and 1 site cannot orient anything.

  Still blocked, but blocked for a sharper reason than "I could not find a
  list": the list exists, and the coordinate join available for it is a ruler
  that hands back confident wrong answers. The next thing to try is met.no's own
  Frost API station catalogue -- the operator's own numbers rather than a
  third party's -- which needs a client registration.
* **Coverage box** and the dBZ floor: the shared `scripts/dbz.py` table applies,
  including the 7 dBZ floor, and must not be re-derived here.

## Why the PNG endpoint is unusable — measured, after getting it wrong once

The first version of this note said their rendered PNG carries decorations "in
colours a classifier reads as echo". bob doubted it: if the base map were drawn
in echo colours, nobody could read the picture either — would anyone really
design it that way? He was right, and I had asserted a property of the image
without measuring it, having only looked at it. The base map is grey and
grey-green (180,187,180 / 150,150,170 / 124,124,140); the echo is yellow
through red (231,231,38 / 233,151,38 / 202,58,38 / 210,147,203). Those are
plainly separable.

The real reasons, measured on a live frame:

**The legend's colours appear nowhere in the map.** Reading all 18 swatches out
of the legend column and counting map-area pixels exactly equal to one of them:

    map-area pixels: 350330
    exactly a legend colour: 0  (0.0%)
    distinct colours inside the map area: 895

The echo is composited with transparency over the base map, so the same dBZ
over land and over sea produces different pixels. Recovering a value means
solving a blend with an unknown background and an unknown alpha, not a lookup.
The blend shows up directly in the histogram: pure yellow (230,230,40) at 4246
pixels alongside (192,192,85) at 2974, the latter being that yellow at roughly
0.6 alpha over grey.

**The furniture does not impersonate the echo, it erases it.** Of 3191 dark
pixels in the map area (city names, borders, graticule), 11% fall inside an
echo region — the value underneath is gone, not misread.

The conclusion did not change; half of the stated reason was invented. Same
shape as the Czechia PNG a few hours earlier, where I derived "it has borders
and rivers drawn on it" from colour counts and, on finally opening the image,
found neither. **Having looked at a picture is not the same as having measured
it.**

## One end-to-end check against an independent rendering (2026-08-13 20:40Z)

The projection test proves my arithmetic agrees with the file's coordinates. It
does not exercise `window()` or `level_at()`, and it cannot say whether the
picture a reader gets has the weather in the right place. So: MET publish a
rendered PNG for human eyes. It is useless to a program — that is the whole
point of the section above — but it is perfectly readable to me.

Their `central_norway` frame at 20:40Z, beside our Trondheim grid from the same
minute:

| | their image | our grid |
|---|---|---|
| west / south-west (Kristiansund–Molde) | large, intense mass | dense cells, the heaviest of the run |
| north (Namsos, Steinkjer) | scattered echo | activity in the upper left |
| east (toward Östersund) | clear | nearly empty right half |
| at Trondheim itself | light to moderate | light cells around the marker |

Orientation, the wet/dry split and the intensity ordering all agree.

**What this is and is not.** It exercises the whole chain — projection, window,
level mapping, marker placement — which the coordinate test does not. It is
*not* independent of the data: both pictures come from the same mosaic, so it
confirms that I read the grid correctly, not that the grid is correct. And it
is one manual look at one frame by me, not a guard: it will not notice if this
breaks next week. The `is_nodata` check in the section above is still the thing
that is missing, and this does not substitute for it.
