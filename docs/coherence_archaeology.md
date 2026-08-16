# Does the prose contradict the map? — the investigation, 2026-08-16

Moved out of `CLAUDE.md`. The stone keeps the answer and the two judgements
that transfer; this file keeps the evidence, so "the disagreement is caused by
extrapolation" can be checked rather than believed.

## The question

A weather scene has two halves that come from different places: a sentence from
upstream ("light rain 18 km to the northeast") and a character radar map we
render ourselves. **Do they ever disagree, and how often?**

It started as one case in Chiang Mai — prose said rain 18 km NE, our nearest
echo was 30 km SW — which I mistook for a newly discovered contradiction. It
was not: that frame was labelled `predict, obs age 25min stale`, and the
mechanism had been settled on 8/02 (the prose is passed through from upstream
verbatim; bob rejected a separate attribution line, and the fix was those two
tokens). **I nearly "fixed" a disclosure that was working as designed.**

Scanning twelve cities to measure the rate returned a sample of **zero** — the
prose only carries a distance when upstream sees rain nearby, which is a sparse
event a one-off sweep will not catch. So the pairs are recorded as they happen
(`_coherence_sample` in `scripts/render_scene.py`) and judged out of band.

## The floor is one cell, and it is agreement

Median gap came back at **exactly 5.8 km**, mean identical to median. A constant
that precise is a property of the instrument. It is: when rain is overhead the
marker `[><]` occupies the centre cell and overwrites the echo glyph, so the
nearest ramp character is a neighbour. **128 of the first 161 corrected samples
measured exactly one cell, 73 of those with upstream reporting 0.0 km.** The map
has no character left with which to say "0 km".

Any judging pass that scores a one-cell gap as disagreement is reading the
marker, not the weather.

## The disagreements are one-sided

Of 260 corrected pairs across 44 places: **231 agree within one cell, 26 put the
rain farther than the prose does, 3 put it nearer.** One-sidedness is a
mechanism, not noise.

Two candidates, with very different consequences:

- the frame is extrapolated or minutes old and the echo has moved — an **honest**
  disagreement between a current sentence and an older picture;
- our 7 dBZ floor drops light echo that upstream counts, so the nearest glyph we
  draw is the next band out — a **reader-facing error**, and in the direction
  that matters: telling someone rain is 66 km away when upstream says 13.

## Three wrong turns, in order

**1. A constant that looked like a bug.** Every large-gap row carried
`intensity = 0.6596`, identical to four decimals. That reads like a constant
masquerading as a measurement. It takes **four** distinct values across the set,
spaced like discrete radar levels — coarsely quantised, not broken. Weak
evidence, but not a defect.

**2. The comparison had no power, and saying so was the right answer.** To test
the floor hypothesis I split by upstream intensity — and **251 of 260 samples
share one value**. That comparison cannot discriminate anything. `INSUFFICIENT`,
not "ruled out". The response was to record what *would* discriminate (frame
age, age token, extrapolation flag — all three already computed one line above
the call site) rather than to pick the story that read better.

**3. A third hypothesis I invented and half-refuted myself.** Places with no
national radar showed a far-side rate of **58% against 23%** where we have one.
That looks like "our global fallback is coarser" — but it cannot be separated
from "upstream's own estimate is worse in those regions", because both degrade
in the same places. No conclusion drawn.

## The answer

With frame provenance recorded, the first cut said **observed frames: 0 far-side
of 38; extrapolated: 87 of 172**. That looked decisive and was nearly worthless:
those 38 observed rows were **all Japan, only 2 places, 14 distinct minutes**.
Measuring the place, not the frame.

Stratified by place, holding country and source fixed:

| Tokyo (JMA) | far-side | agrees |
|---|---|---|
| observed frames | **0** | 38 |
| extrapolated frames | **78** | 74 |

Same location, same radar network, same renderer. The only difference is
whether the frame was an extrapolation. At the extrapolated rate of 51%, the
chance of seeing 0 of 38 is about 3×10⁻¹².

**The 7 dBZ floor is refuted**: it applies to observed frames identically and it
does not touch them at all. **The cause is extrapolation.**

## What this means for the reader

It is an **honest** disagreement, and it is already disclosed: the scene prints
`radar: predict HH:MM` and `obs age: N min`. The product says the picture is
extrapolated; the sentence is current; they can differ. That is the disclosure
bob and I settled on 8/02, working.

The real open question is that the extrapolation errs **one way** — outward —
in half of extrapolated frames. Random error would be symmetric. That is a
quality question about the extrapolation, not a lie to the reader, and it rests
on one city over roughly two hours. **No code changed. Keep collecting.**

## Transferable, and kept on the stone

- **Before calling something a contradiction, check whether it is a disclosure
  we already decided on and already print.** An unfamiliar label is more likely
  something someone installed to answer this exact question than evidence that
  nobody thought of it.
- **Stratify by place before believing a difference between groups.** "0 of 38"
  was really "these two places agreed".
- **A comparison with no power gets its own verdict.** `INSUFFICIENT` must not
  print the same word as "ruled out".
