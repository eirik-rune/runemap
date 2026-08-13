# Which country is next, and what each candidate is actually blocked on

Written 2026-08-13, after the twelfth country shipped. A sweep like this is
worth writing down mainly so the next one does not repeat it — and so that
"I looked and found nothing" is never mistaken for "there is nothing".

**Every negative below is scoped to what was actually asked.** Where a probe
came back empty, the entry says whether a positive control passed, because an
empty result and a broken ruler return the same silence.

## Belgium — the closest, blocked on a licence fact

Full write-up in `belgium_rmi_feasibility.md`. Plain WMS 1.3.0, 5-minute
frames, `Fees: none`, the class `radar_wms` already serves. RMI grant CC BY 4.0
to EU high-value datasets specifically, and whether radar is one could not be
read from here. **Next step: ask RMI.** Nothing else about it is unresolved.

## Ruled out for now, with the reason

| country | what was asked | result |
|---|---|---|
| Austria | GeoSphere `/v1/datasets`, 63 datasets | only `inca-v1-1h-1km`, a **historical hourly analysis grid**, not a live composite. Not a radar source. |
| Poland | IMGW `danepubliczne.imgw.pl` API | `synop` returns live station data (positive control passes), so the API works — it simply has **no radar product**. |
| Estonia | `gsavalik.envir.ee` WMS, 2337 layers | the only "radar" layer is `maaamet:geol_gfp_georadari_profiil` — **ground-penetrating radar geology profiles**. Wrong instrument entirely; a keyword match is not a product. |
| Italy | DPC `radar-api.protezionecivile.it`, **from two exits** | root **503**, product endpoint **403** — identical from this datacentre and from the Tokyo host, so it is **not our address**. `dati.protezionecivile.it` also 403s; only the human-facing `radar.protezionecivile.it` page answers. Their API very likely requires a `Referer` asserting we came from their own site, which would be a false statement about where the request came from, so it was not sent. **Closed to us on those terms.** |
| Portugal | IPMA `api.ipma.pt/open-data` | the API works — the forecast endpoint returns 200 as a positive control — but four guessed radar paths 404. **Path naming is unknown, not absent.** Same shape as the KNMI station dataset: the API serves what you can already name, and the name has to come from a catalogue. |
| Ireland | `opendata.met.ie` | SPA; nothing readable from the DOM. Not yet asked properly. |
| Slovenia | `vreme.arso.gov.si/geoserver/ows` | returned the SPA's HTML, not capabilities — so that path is wrong. Not yet asked properly. |

**One negative that got fully diagnosed the same night**, which is why the
Tokyo host is worth having: "403 from a datacentre" and "403 by policy" are the
same character, and the only way to tell them apart is a second exit. Italy read
as the first and turned out to be the second.

## The two shapes this sweep kept meeting

**A keyword match is not a product.** Estonia's 2337-layer WMS contains the word
"radar" and it means ground-penetrating geology. Filtering by name would have
produced a confident wrong candidate.

**"I could not name it" and "it does not exist" return the same 404.** Portugal
and the KNMI station dataset are the same problem: these APIs serve files for a
dataset you can already name and do not enumerate. Guessing paths can only ever
produce a negative that means nothing. The route is always the publisher's
catalogue, not the API.

## Where to look next, in order

1. **Belgium**, once RMI answer. It is one `SERVICES` entry and a palette.
2. ~~Italy from Tokyo~~ — **done, and it is not our exit.** The remaining route
   would be a `Referer` we cannot truthfully send, so Italy is closed unless DPC
   publish elsewhere. Not a candidate.
3. **Portugal, Ireland, Slovenia** via their published catalogues rather than by
   guessing API paths.

None of these needs a new adapter shape. Every one of them is either WMS (which
`radar_wms` serves) or a tiled/bbox product, which is the orientation-safe
Group A described in `orientation_coverage.md`.
