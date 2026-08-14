# Ireland (Met Éireann) — licence settled, and `latest/` is a trap

Written 2026-08-14. Ireland is the best remaining candidate: the licence
question is answered before any engineering, unlike Belgium. It needs real work
(a polar-to-Cartesian compositor) rather than a `SERVICES` entry.

## Licence — settled, and settled the way this repo says to settle one

Found through the **national catalogue, not a guessed API path**. `data.gov.ie`
registers *Irish radar files*, publisher Met Éireann, licence **CC-BY-4.0** as a
machine-readable field. The directory index itself also links the CC BY 4.0
deed. Both directions agree, so this is not a second-hand paraphrase — the
mistake made with DMI, where a paraphrase was treated as terms while the service
was handing over the real licence URL.

## `latest/` is stale, and it is stale in the silent direction

**Measured 2026-08-14 ~07:30Z:**

| path | frame range | age of newest |
|---|---|---|
| `/radar/latest/` | `20260812234504` .. `20260813235004` | **7.5 hours** |
| `/radar/2026/08/14/` | `20260813234504` .. `20260814071004` | **~20 min** |
| `/radar/2026/08/13/` | `20260812234504` .. `20260813235004` | (same as `latest/`) |

`latest/` is not a view onto the newest frames. Its range is **identical to the
previous day's dated directory** — it lags by a day rather than tracking. The
dated path is a rolling 24-hour window and is current.

**Use `/radar/YYYY/MM/DD/`. Never `latest/`.**

Two things make this worth a section rather than a footnote:

* **The name is a claim, not a measurement.** On 2026-08-13 this directory was
  recorded here as "newest observed was 5 minutes old", which was true when
  measured. A door that is correct when you test it and wrong later is the
  hardest kind, because the test passed honestly.
* **The failure mode is the expensive one.** `latest/` does not error, does not
  thin out, and does not mark the cut. It serves well-formed HDF5 files with
  plausible timestamps. An adapter built on it would have drawn 7.5-hour-old
  rain and labelled it current — *stale presented as fresh*, which is the class
  ranked **large** (the reader forms a false belief and cannot detect it), not
  the *disclosed absence* class that an empty grid falls into.

The check that caught it was not cleverness: it was refusing to accept a listing
whose newest entry disagreed with yesterday's note, and then asking a **second
door** the same question. One door cannot tell you it is the stale one.

Confirmed not a truncation artefact — the document closes with `</html>` and the
579 stamps span exactly 24 h, so the window is real rather than a cut-off read.
That check exists because a 301 KB listing read to 200 KB once yielded a
"newest frame" three days old with no marker at the cut.

## The actual engineering, still ahead

Both products are `object: PVOL` — **polar volumes**, not a Cartesian composite:

    T_PAGZ40_C_EIDB_<stamp>.h5   Shannon   (NOD:iesha, 52.6928 N, 8.9200 W)
    T_PAGZ41_C_EIDB_<stamp>.h5   Dublin
    ~10 elevation scans, 360 rays x ~500 bins
    DBZH: gain 0.5, offset -32, nodata 255, undetect 0
    5-minute frames

So the compositing nobody has done for us:

* project each output cell to azimuth/range from each site, sample the lowest
  useful elevation, combine the two sites.
* `undetect` vs `nodata` is already the distinction this fleet is careful about
  — and Norway proved they must not share a word: fill means *seen, no echo*,
  nodata means *not seen at all*, and reading one as the other turned a clear
  sky over Oslo into 74 % blind.
* apply the **7 dBZ floor**, like every other source. Three countries drew
  clear-air clutter as light rain before that floor went in.

**Orientation risk changes shape here.** We would be *building* the grid rather
than indexing someone else's, so an error would be ours — but it is also more
checkable than any composite so far: the radar position is in the file and can
be asserted against OSCAR, and wrong range-ring geometry shows up immediately as
coverage that is not a circle centred on the site. That is a control with real
margin, unlike Switzerland's, where the composite is built around its own radar
network and a vertical flip nearly maps onto itself (140.6 vs 142.0 km).
