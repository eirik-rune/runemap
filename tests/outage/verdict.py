# -*- coding: utf-8 -*-
"""Compute the verdict from the raw samples. The words are printed here, never
typed next to the numbers by me.

The gate is transcribed verbatim from paired.py, fixed before any data existed:

    Scored: does the reader see a grid. PASS needs on-arm maps > 0 and
    off-arm maps == 0 across >= 8 samples.

Run 1 ended FAIL (on 8/8, off 1/8). The off-arm row that drew a map answered in
1.34s, which is what an unblocked pool looks like -- DNS rotates the pool about
every minute, so the rule can end up naming a /24 nobody is talking to and the
"outage" label on that row is simply false. Dropping it after seeing it would
have been widening the gate to fit the data. So the sampler now re-resolves
after the asks and records stable=yes/no, and this rule -- declared here before
run 2 exists -- excludes rows where the pool rotated mid-sample. Excluded rows
are counted and printed, never hidden.

Scoring reads the grid column, not the state word: predict/obs are labels about
provenance, while g24 is the thing a reader looks at.
"""
import io, os, sys

MIN_N = 8
# The samples file is an argument, not a constant. The first copy of this script
# lived in /tmp with the path baked in, so the version committed here would have
# scored a file that does not exist on any fresh checkout -- present in the
# repository and unrunnable, which is a document pretending to be a tool.
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "run2_PASS.txt")

rows, skipped = [], []
for ln in io.open(PATH, encoding="utf-8"):
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    d = {}
    for tok in ln.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    if "on" not in d or "off" not in d:
        continue
    if d.get("stable") != "yes":
        skipped.append(d.get("blocked", "?"))
        continue
    on, off = d["on"].split(","), d["off"].split(",")
    rows.append({
        "blocked": d.get("blocked", "?"),
        "on_t": float(on[1][:-1]), "on_g": int(on[2][1:]),
        "off_t": float(off[1][:-1]), "off_g": int(off[2][1:]),
    })

n = len(rows)
on_maps = sum(1 for r in rows if r["on_g"] >= 24)
off_maps = sum(1 for r in rows if r["off_g"] >= 24)
pools = sorted({r["blocked"] for r in rows})
print("  scored n=%d, distinct pools blocked=%d" % (n, len(pools)))
print("  excluded, DNS rotated mid-sample so the outage label was false: %d" % len(skipped))
if n:
    print("  ON  (fallback enabled) : maps %d/%d   median wait %.2fs"
          % (on_maps, n, sorted(r["on_t"] for r in rows)[n // 2]))
    print("  OFF (fallback disabled): maps %d/%d   median wait %.2fs"
          % (off_maps, n, sorted(r["off_t"] for r in rows)[n // 2]))

if n < MIN_N:
    print("  VERDICT: INSUFFICIENT (n=%d < %d) -- the gate is not widened to fit" % (n, MIN_N))
    sys.exit(2)
if on_maps > 0 and off_maps == 0:
    print("  VERDICT: PASS -- during an outage the reader sees a map only with the fallback")
    sys.exit(0)
print("  VERDICT: FAIL (on=%d off=%d)" % (on_maps, off_maps))
sys.exit(1)
