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

Both products are `object: PVOL` — **polar volumes**, not a Cartesian composite.
Measured from the 07:10Z frames on 2026-08-14, because the note written earlier
the same day from a previous reading (`~10 scans, 360 rays x ~500 bins`) was
**wrong for Dublin**:

| | Shannon `T_PAGZ40` | Dublin `T_PAGZ41` |
|---|---|---|
| `/what/source` | `WMO:03962,NOD:iesha,PLC:Shannon` | **`WMO:03969` only** |
| site | 52.6928 N, 8.9200 W, 29 m | 53.4299 N, 6.2443 W, 99 m |
| sweeps | 10 (0.5deg..90deg) | 10 (0.5deg..15deg) |
| lowest sweep | 360 rays x **497 bins @ 500 m** = 248.5 km | 360 rays x **250 bins @ 1000 m** = 250 km |
| DBZH | gain 0.5, offset -32, nodata 255, undetect 0 | identical |

**The two sites do not share a geometry.** Same reach, half the range
resolution at Dublin. A compositor that reads `rscale`/`nbins` once and applies
it to both places Dublin's echoes at **twice their true range** -- and it would
still produce a plausible picture.

**Dublin's `source` carries no `NOD` and no `PLC`**, only a WMO id. The identity
assertion planned for the site coordinates -- registry place name against OSCAR
station name, the control that caught Norway -- has nothing to key on at Dublin
but the number. That control is genuinely weaker there and must say so rather
than quietly skipping.

### The filename is not the observation time, and the two radars disagree oppositely

| | filename | `/what` (nominal) | `dataset1` actual sweep |
|---|---|---|---|
| Shannon | 07:10:04 | 07:15:00 | **07:14:14 -> 07:14:28** |
| Dublin | 07:10:00 | 07:10:06 | **07:10:06 -> 07:10:26** |

Shannon sweeps **top-down**, so its 0.5deg sweep -- the one we would render --
happens about four minutes *after* the stamp on its own filename. Dublin sweeps
bottom-up and its lowest sweep comes first. Reading the filename reports Shannon
as **4 minutes older than it is**; reading `/what/time` reports it ~45 s younger
than the sweep really is.

**Take the age from `dataset1/what/starttime`** -- the observation time of the
layer actually drawn. This feeds the frame-age ceiling, and age ceilings are
precisely the constants this fleet has repeatedly derived from one source and
then been wrong about on the next.

### `nodata` is 0 % -- the blind mask is ours to author

Both files: **0.0 % nodata**, everything else split between `undetect` and echo.
Every gate the radar looked at reported something. So the *seen / not-seen*
distinction -- the one Norway proved must never share a word with *seen but dry*
-- **does not arrive in the data at all**. Beyond maximum range and below the
lowest beam there is no cell, and the compositor must synthesise that mask from
range geometry. A mask we author is a mask we can get wrong in the silent
direction, so it needs its own control, not a code comment.

### The 7 dBZ floor is not optional here, and this is the measurement

| | echo coverage | echo dBZ min / median / max | share of echo >= 7 dBZ |
|---|---|---|---|
| Shannon | 1.2 % | -13.0 / **-1.0** / 50.5 | **16.4 %** |
| Dublin | 16.6 % | -23.5 / **5.5** / 66.0 | **46.3 %** |

Shannon's median echo is **-1.0 dBZ**, and five sixths of its echo sits below
the floor DWD themselves draw nothing under. Rendering "anything above
undetect" -- the bug that had three countries painting clear-air clutter as
light rain -- would put most of the west of Ireland under drizzle on a frame
where the large majority of returns are noise, insects and ground.

    5-minute frames, both sites

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
