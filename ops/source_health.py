"""Ask every radar source, at a sky it claims to cover, whether it still works.

The reason this exists is that every failure this fleet has had reaches the
reader as the same picture: an empty grid, which is what a clear sky looks
like. In one day: a palette wired into the window production never uses (Japan
drew nothing for an hour, tests green), a systemd drop-in on one of two
instances (half the readers, alternating), a zoom level that answers 200 with a
transparent tile, and a tile size that left blank bands looking like weather.
None of those announced themselves.

So the check is per source and it has to be able to fail:

  OK           a map came back, its frame is fresh, and its scale is sane
  STALE        a map came back but the observation is older than the source's
               own cycle allows
  NO-MAP       the adapter declined where it says it has coverage
  ERROR        it raised

Exit code is 0 only if every source is OK. That matters more than the text: a
report nobody reads is decoration, and the first version of half the checks in
this repo only printed.

    python3 ops/source_health.py            # all sources
    python3 ops/source_health.py jma wms    # a subset

Probe skies are inside each source's declared coverage and deliberately spread
out, so a single dead radar does not read as a dead service.
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))

# (label, module, import path, sky, max age in seconds)
#
# The age limit is the source's own cycle plus room for one missed beat -- not
# a number picked so the check passes. Where the adapter already declares one,
# it is read from the adapter rather than restated here, because a restated
# constant drifts and the drift is silent.
PROBES = [
    ("jma-tokyo", "radar_jma", (139.69, 35.69), None),
    ("jma-naha", "radar_jma", (127.68, 26.21), None),
    ("wms-chicago", "radar_wms", (-87.62, 41.88), 900),
    ("wms-toronto", "radar_wms", (-79.38, 43.65), 900),
    ("wms-helsinki", "radar_wms", (24.94, 60.17), 900),
    ("wms-berlin", "radar_wms", (13.40, 52.52), 900),
    ("redemet-saopaulo", "radar_redemet", (-46.63, -23.55), None),
]


def _max_age(mod, fallback):
    for name in ("FRAME_MAX_AGE", "MAX_AGE"):
        v = getattr(mod, name, None)
        if v:
            return float(v)
    return float(fallback if fallback is not None else 1800)


def check(label, modname, sky, fallback):
    try:
        mod = __import__(modname)
    except Exception as e:
        return "ERROR", "%s: import failed: %r" % (label, e)
    lng, lat = sky
    t0 = time.time()
    try:
        got = mod.draw("><", lng, lat, small=True)
    except Exception:
        return "ERROR", "%s: %s" % (label, traceback.format_exc().strip().splitlines()[-1])
    took = time.time() - t0
    if got is None:
        # Declining inside declared coverage is the interesting failure: it is
        # exactly what a dead upstream and a quiet sky both look like from the
        # reader's side, and only this probe can tell them apart, because it
        # asked somewhere the source SAYS it can see.
        return "NO-MAP", "%s: declined inside its own coverage (%.2fs)" % (label, took)
    age = time.time() - float(got[4])
    limit = _max_age(mod, fallback)
    if age > limit:
        return "STALE", ("%s: frame %.0f min old, over its own %.0f min limit"
                         % (label, age / 60.0, limit / 60.0))
    kmcol = float(got[1])
    if not (1.0 <= kmcol <= 60.0):
        return "ERROR", "%s: %.1f km/col is not a plausible scale" % (label, kmcol)
    return "OK", ("%s: %s, %.0f min old, %.1f km/col, %.2fs"
                  % (label, got[5] if len(got) > 5 else "?", age / 60.0, kmcol, took))


def main():
    wanted = sys.argv[1:]
    rows = [p for p in PROBES if not wanted or any(w in p[0] for w in wanted)]
    if not wanted:
        pass
    elif not rows:
        sys.exit("no probe matches %r; have: %s"
                 % (wanted, ", ".join(p[0] for p in PROBES)))
    bad = 0
    for label, modname, sky, fallback in rows:
        state, msg = check(label, modname, sky, fallback)
        print("%-6s %s" % (state, msg))
        if state != "OK":
            bad += 1
    print("-- %d of %d healthy" % (len(rows) - bad, len(rows)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
