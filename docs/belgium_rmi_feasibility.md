# Belgium (RMI/KMI) — technically the cheapest country left, blocked on one fact

Written 2026-08-13. **Not adopted.** The engineering is nearly free; the licence
is not established, and this stops there rather than guessing in either
direction.

## What is established

RMI publish a radar composite as a plain WMS, which is the class `radar_wms`
already serves (US, Canada, Finland, Germany):

    https://opendata.meteo.be/service/radar/wms?service=WMS&request=GetCapabilities&version=1.3.0

| | |
|---|---|
| layer | `belgian_rainfall_composite` (style `rainfall`) |
| version | WMS 1.3.0 — the y-first axis order `radar_wms` already asserts |
| CRS | EPSG:4326, 3857, 31370, 3812, CRS:84 |
| bbox | 47.42–53.80 N, −0.93–9.66 E (Belgium plus a wide margin) |
| time | `2026-08-13T10:40Z/2026-08-13T23:35Z/PT5M` — 5-minute frames, ~13 h deep |
| freshness | newest frame stamped 6 minutes before the request |
| `<Fees>` | `none` |
| `<AccessConstraints>` | `none` |

So this would be a `SERVICES` entry and a palette, not a new adapter.

## What is not established, and why that blocks it

`Fees: none` and `AccessConstraints: none` are not a licence. The portal's own
terms text (found in the site's JS bundle — the page is a SPA and its DOM
carries none of this) says:

> All content published on the open data platform of the Royal Meteorological
> Institute of Belgium (RMI) … may be re-used, distributed or presented
> publicly, midst the user explicitly refers to the RMI as the official source
> of the raw data. **All open data of the RMI that are defined as high-value
> datasets (HVD) may be re-used under the Creative Commons licence conditions
> CC BY 4.0** provided that the source is acknowledged.

**The CC BY 4.0 grant is conditioned on the dataset being an HVD** under EU
Implementing Regulation 2023/138. The only exclusion RMI name explicitly is
climate gridded data, which the radar composite is not. But naming what is
excluded is not the same as confirming what is included, and this is a
redistribution question, so the difference matters.

**Three routes to that fact were tried and none answered:**

* EUR-Lex returns a **zero-length body** for the regulation over HTML and a
  2 KB error page for the PDF from this exit. That is "I could not read it",
  **not** "radar is not listed" — the two return the same silence, and one of
  them would be a licence to proceed.
* The EU open data portal has the regulation's datasets but a publisher-facet
  query for RMI returned **0 hits**, which is equally uninformative: a facet I
  may have malformed and an absent registration look identical.
* RMI's portal text mentions HVD twice, neither time about radar.

A near miss worth recording: a plain search of the EU portal for "High
Resolution Composite Rainfall Radar" returns a dataset of that name whose
publisher is the **UK Met Office**. Reading its licence as Belgium's would have
been the NOAA `isd-history` failure again — a well-formed, believable, wrong
join. The publisher field is what caught it.

## The decisive next step

**Ask RMI.** That is this repo's own rule — before recording that terms forbid
something, ask the service where its terms are — and it is the one route not
yet tried. `opendata@meteo.be` is the contact on the portal. The question is
one sentence: is `belgian_rainfall_composite` among the high-value datasets, and
therefore CC BY 4.0?

Until there is an answer, Belgium is not wired. Nothing about the engineering
gets easier or harder by waiting, and the alternative is redistributing another
institute's data on an assumption.

## If the answer is yes

* one entry in `radar_wms.SERVICES` with `attrib` naming RMI, plus the
  "material has been changed" note CC BY needs — a 48×24 character grid is a
  change, and the shared `radar-data-note` line already carries that for SMHI.
* a palette for style `rainfall`, derived the way `ops/wms_palette.py` does it
  for the existing four, **with the 7 dBZ floor** — three countries were drawing
  clear-air clutter as light rain until that floor went in.
* orientation needs no new control: WMS is Group A. We send a bbox and are
  served that bbox, so there is no private grid convention of ours to reverse.
  See `orientation_coverage.md`.
