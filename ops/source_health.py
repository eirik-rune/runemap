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
  NO-READER    the adapter cannot read this format here (an optional
               dependency is absent). The upstream is not implicated, and
               folding this into NO-MAP would aim the next hour of debugging
               at a network that is fine.
  NO-ACCESS    the credential this source needs exists and THIS USER cannot
               read it -- a fact about who ran the probe, not about the source.
               Production may well be serving it; ask the service.
  WRONG-SOURCE another service answered, so the one this probe names is not
               being exercised at all
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
import contextlib
import io
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))

# (label, module import path, sky, max age in seconds, expected source name)
#
# The age limit is the source's own cycle plus room for one missed beat -- not
# a number picked so the check passes. Where the adapter already declares one,
# it is read from the adapter rather than restated here, because a restated
# constant drifts and the drift is silent.
#
# The fourth field is the source this probe is FOR. Without it the label was
# the only thing saying which service was being exercised, and a label is not a
# judgement: "wms-toronto" was answered by NWS NEXRAD, because the NEXRAD
# rectangle reaches past the border and it is first in the table. So Environment
# Canada had no probe at all -- it could have died and this file would still
# have printed "7 of 7 healthy", which is the exact decoration this file was
# written against. Calgary is far enough north that ECCC is the service that
# answers, and the assertion below makes drift a failure rather than a rename.
PROBES = [
    ("jma-tokyo", "radar_jma", (139.69, 35.69), None, "JMA"),
    ("jma-naha", "radar_jma", (127.68, 26.21), None, "JMA"),
    ("wms-chicago", "radar_wms", (-87.62, 41.88), 900, "NWS NEXRAD"),
    ("wms-calgary", "radar_wms", (-114.07, 51.05), 900, "Environment Canada"),
    ("wms-helsinki", "radar_wms", (24.94, 60.17), 900, "FMI"),
    ("wms-berlin", "radar_wms", (13.40, 52.52), 900, "DWD"),
    ("smhi-stockholm", "radar_smhi", (18.07, 59.33), 1800, "SMHI"),
    ("chmi-prague", "radar_chmi", (14.42, 50.09), None, "CHMI"),
    ("knmi-amsterdam", "radar_knmi", (4.90, 52.37), None, "KNMI"),
    ("dmi-copenhagen", "radar_dmi", (12.57, 55.68), None, "DMI"),
    # Oslo, not a point picked for looking healthy: it is the city this source
    # was added for, and it is inside every Norwegian radar's reach.
    ("metno-oslo", "radar_metno", (10.75, 59.91), None, "MET Norway"),
    ("chrzc-zurich", "radar_meteoswiss", (8.55, 47.3667), None, "MeteoSwiss"),
    ("redemet-saopaulo", "radar_redemet", (-46.63, -23.55), None, "REDEMET/DECEA"),
]


def _max_age(mod, fallback):
    for name in ("FRAME_MAX_AGE", "MAX_AGE"):
        v = getattr(mod, name, None)
        if v:
            return float(v)
    return float(fallback if fallback is not None else 1800)


def check(label, modname, sky, fallback, want_source=None):
    try:
        mod = __import__(modname)
    except Exception as e:
        return "ERROR", "%s: import failed: %r" % (label, e)
    lng, lat = sky
    t0 = time.time()
    # Every adapter already writes its reason to stderr -- WMS-NO-FRAME,
    # CHMI-FRAME-TOO-OLD, a nodata share over the limit -- and this probe used
    # to throw all of it away and print one word. "Upstream has no frame",
    # "the frame is too old" and "the window is mostly blind" send you to three
    # different places, so they must not print the same thing. Captured and
    # re-emitted, never swallowed: the log line the adapter wrote is still the
    # adapter's to write.
    said = io.StringIO()
    try:
        with contextlib.redirect_stderr(said):
            got = mod.draw("><", lng, lat, small=True)
    except Exception:
        sys.stderr.write(said.getvalue())
        return "ERROR", "%s: %s" % (label, traceback.format_exc().strip().splitlines()[-1])
    finally:
        pass
    sys.stderr.write(said.getvalue())
    took = time.time() - t0
    if got is None:
        why = None
        try:
            why = mod.unavailable()
        except AttributeError:
            pass
        except Exception as e:
            why = "unavailable() raised %r" % (e,)
        if why:
            # A third absence, and it is not the adapter's: the credential is
            # present and this user may not read it. NO-READER sends you to
            # pip and NO-MAP sends you to the network; the cure here is to ask
            # the service, which is reading the same file as its own user and
            # answering fine. 8/13: the fleet was 11 of 11 while this printed
            # 10 of 11 and named a missing KNMI key.
            if "not readable" in why or "is empty" in why:
                return "NO-ACCESS", "%s: %s" % (label, why)
            return "NO-READER", "%s: %s" % (label, why)
        # Declining inside declared coverage is the interesting failure: it is
        # exactly what a dead upstream and a quiet sky both look like from the
        # reader's side, and only this probe can tell them apart, because it
        # asked somewhere the source SAYS it can see.
        lines = [x for x in said.getvalue().splitlines() if x.strip()]
        because = (" -- %s" % lines[-1].strip()) if lines else (
            " -- no reason given, which is itself the bug")
        return "NO-MAP", ("%s: declined inside its own coverage (%.2fs)%s"
                          % (label, took, because))
    age = time.time() - float(got[4])
    limit = _max_age(mod, fallback)
    if age > limit:
        return "STALE", ("%s: frame %.0f min old, over its own %.0f min limit"
                         % (label, age / 60.0, limit / 60.0))
    kmcol = float(got[1])
    if not (1.0 <= kmcol <= 60.0):
        return "ERROR", "%s: %.1f km/col is not a plausible scale" % (label, kmcol)
    src = got[5] if len(got) > 5 else None
    if want_source is not None and src != want_source:
        # The probe is still green about SOMETHING -- that is the danger. A
        # sky can move from one service to another (a coverage rectangle that
        # reaches past a border, a reordered table) and the service this probe
        # exists for stops being exercised, silently, while the line still
        # reads OK.
        return "WRONG-SOURCE", ("%s: answered by %r, but this probe exists to"
                                " exercise %r -- %s now has no probe"
                                % (label, src, want_source, want_source))
    return "OK", ("%s: %s, %.0f min old, %.1f km/col, %.2fs"
                  % (label, got[5] if len(got) > 5 else "?", age / 60.0, kmcol, took))


UNIT = os.environ.get("RUNEMAP_HEALTH_UNIT", "runemap")


def adopt_unit_env(unit=UNIT, run=None):
    """Take the running service's own settings, rather than restating them.

    8/13: this probe reported NO-READER for the Netherlands -- "no KNMI key" --
    while production held the key perfectly well. The service is told where the
    key is by a drop-in (RUNEMAP_KNMI_KEY_FILE=/etc/runemap/knmi_key); cron
    told this probe nothing, so it looked in a default path that does not
    exist. **The probe was measuring a configuration nobody runs**, and the
    alarm it raised was about itself.

    It passed for five hours before that only because a cached frame let the
    adapter answer without a key at all -- so it was passing for a reason other
    than the one it claimed, which is how a ruler starts lying.

    Variables already set win: a person asking a question on the command line
    is not overruled by the unit.

    -> list of names adopted, so the log says what was taken. If systemd cannot
    be asked, that is said out loud rather than silently falling back to
    defaults -- "I could not find out" and "there was nothing to find" must not
    print the same thing.
    """
    import subprocess
    try:
        out = (run or (lambda: subprocess.run(
            ["systemctl", "show", unit, "-p", "Environment"],
            capture_output=True, text=True, timeout=10).stdout))()
    except Exception as e:
        sys.stderr.write("HEALTH-ENV-UNREADABLE %s: %r\n" % (unit, e))
        return None
    if not out.startswith("Environment="):
        sys.stderr.write("HEALTH-ENV-UNREADABLE %s: %r\n" % (unit, out[:80]))
        return None
    took = []
    for tok in out[len("Environment="):].strip().split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        if k in os.environ:
            continue
        os.environ[k] = v
        took.append(k)
    return took


def main():
    wanted = sys.argv[1:]
    took = adopt_unit_env()
    if took is None:
        print("NO-CONFIG could not read %s's environment; "
              "the probe would be testing settings production does not use"
              % UNIT)
        sys.exit(1)
    if took:
        print("-- adopted from %s: %s" % (UNIT, " ".join(sorted(took))))
    rows = [p for p in PROBES if not wanted or any(w in p[0] for w in wanted)]
    if not wanted:
        pass
    elif not rows:
        sys.exit("no probe matches %r; have: %s"
                 % (wanted, ", ".join(p[0] for p in PROBES)))
    bad = 0
    for label, modname, sky, fallback, want in rows:
        state, msg = check(label, modname, sky, fallback, want)
        print("%-6s %s" % (state, msg))
        if state != "OK":
            bad += 1
    print("-- %d of %d healthy" % (len(rows) - bad, len(rows)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
