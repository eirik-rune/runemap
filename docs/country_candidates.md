# Which country is next, and what each candidate is actually blocked on

Written 2026-08-13, after the twelfth country shipped. A sweep like this is
worth writing down mainly so the next one does not repeat it — and so that
"I looked and found nothing" is never mistaken for "there is nothing".

**Every negative below is scoped to what was actually asked.** Where a probe
came back empty, the entry says whether a positive control passed, because an
empty result and a broken ruler return the same silence.

## Belgium — RULED OUT 2026-08-14: GetMap is 403, only the catalogue is open

Full write-up in `belgium_rmi_feasibility.md`. Plain WMS 1.3.0, 5-minute
frames, `Fees: none`, the class `radar_wms` already serves. RMI grant CC BY 4.0
to EU high-value datasets specifically, and whether radar is one could not be
read from here. **Next step: ask RMI.** Nothing else about it is unresolved.

## Ireland — licence settled, but it needs a compositor we do not have

Found the way this file says to find things: **the national catalogue, not
guessed API paths.** `data.gov.ie` returns *Irish radar files*, publisher Met
Éireann, licence **CC-BY-4.0** as a machine-readable field — so unlike Belgium,
the licence question is answered before any engineering. The directory itself
links the CC BY 4.0 deed too.

    https://opendata2.met.ie/radar/latest/     no key, ~24 h retention
    T_PAGZ40_C_EIDB_<stamp>.h5   Shannon   (NOD:iesha, 52.6928 N 8.9200 W)
    T_PAGZ41_C_EIDB_<stamp>.h5   Dublin
    5-minute frames; newest observed was 5 minutes old

**The catch, and it is a real one: both products are `object: PVOL` — polar
volumes.** Ten elevation scans of 360 rays × ~500 range bins, `DBZH` with
`gain 0.5, offset -32, nodata 255, undetect 0`. That is raw radar, not the
Cartesian composite every existing adapter reads. Nobody has done the
compositing for us.

So Ireland is not a `SERVICES` entry; it is the first candidate that needs
**new work rather than new configuration**:

* project each output cell to azimuth/range from each radar site and sample the
  lowest useful elevation, then combine the two sites — the physics is
  well-specified, and `undetect` vs `nodata` is already the distinction this
  fleet is careful about.
* the orientation risk **changes shape**: we would be building the grid rather
  than indexing someone else's, so an error would be ours. It is also more
  checkable — the radar position is in the file and can be asserted against
  OSCAR, and a range-ring geometry that is wrong shows up immediately as
  coverage that is not a circle centred on the site.

Worth doing, and worth doing deliberately rather than at the end of a long
night. Nothing about it is blocked.

## Ruled out for now, with the reason

| country | what was asked | result |
|---|---|---|
| Austria | GeoSphere `/v1/datasets`, 63 datasets | only `inca-v1-1h-1km`, a **historical hourly analysis grid**, not a live composite. Not a radar source. |
| Poland | IMGW `danepubliczne.imgw.pl` API | `synop` returns live station data (positive control passes), so the API works — it simply has **no radar product**. |
| Estonia | `gsavalik.envir.ee` WMS, 2337 layers | the only "radar" layer is `maaamet:geol_gfp_georadari_profiil` — **ground-penetrating radar geology profiles**. Wrong instrument entirely; a keyword match is not a product. |
| Italy | DPC `radar-api.protezionecivile.it`, **from two exits** | root **503**, product endpoint **403** — identical from this datacentre and from the Tokyo host, so it is **not our address**. `dati.protezionecivile.it` also 403s; only the human-facing `radar.protezionecivile.it` page answers. Their API very likely requires a `Referer` asserting we came from their own site, which would be a false statement about where the request came from, so it was not sent. **Closed to us on those terms.** |
| Portugal | IPMA `api.ipma.pt/open-data` | the API works — the forecast endpoint returns 200 as a positive control — but four guessed radar paths 404. **Path naming is unknown, not absent.** Same shape as the KNMI station dataset: the API serves what you can already name, and the name has to come from a catalogue. |
| Slovenia | `podatki.gov.si` CKAN, queries `radar` and `padavine radar` | **0 hits.** The catalogue answers, so this is a real negative for the catalogue — though it does not rule out a product ARSO publish without registering it. |

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

1. **Ireland** — licence already settled, but it needs a polar-to-Cartesian
   compositor. The largest piece of real work available, and unblocked.
2. ~~Belgium~~ — **ruled out.** Not a licence question after all: `GetMap`
   403s on every variant while `GetCapabilities` returns 200. They publish a
   catalogue entry for a layer they do not serve.
3. ~~Italy from Tokyo~~ — **done, and it is not our exit.** The remaining route
   would be a `Referer` we cannot truthfully send, so Italy is closed unless DPC
   publish elsewhere. Not a candidate.
4. **Portugal** via IPMA's published catalogue rather than by guessing API paths.

None of these needs a new adapter shape. Every one of them is either WMS (which
`radar_wms` serves) or a tiled/bbox product, which is the orientation-safe
Group A described in `orientation_coverage.md`.
