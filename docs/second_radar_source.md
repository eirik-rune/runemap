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
| IMD (India) | mumbai | **no reuse terms found**: the disclaimer carries only `(c) Ministry of Earth Sciences`, and `copyright.php` / `website_policy.php` / `policy.php` / `terms.php` are all 404. Unknown is not permission | fine | per-station PPI GIFs in polar coordinates -- station coordinates and range calibration would have to be built |
| NOAA GOES-19 `ABI-L2-RRQPEF` | saopaulo (Americas only) | **US Government work, public domain. No gatekeeper at all** | fine, straight from prod | **fails, see below** |
| Open-Meteo | both | data CC BY 4.0, commercial requires a paid plan | fine | **fails, see below** |

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

- **There is no licence-free path to "is it raining on me" for these two
  cities.** The one source with no gatekeeper cannot see the rain; every source
  that can see it needs somebody's permission. Two requests are out.
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
