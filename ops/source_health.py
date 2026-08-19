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
  PARTIAL-BLIND the frame came back and a fixed part of the network is absent
               from it, past the adapter's own blind-share limit. Exit 1, and
               it rings: unlike THROTTLED nothing refused us, the data itself
               is short. Measured before it got its own name -- the blind share
               holds constant to the digit for hours, which is a set of radars
               missing, not weather.
  THROTTLED    the upstream rate-limited us and the adapter backed off, as it
               is supposed to. Nothing is broken -- not the source, not the
               adapter, not the network -- so this is "I cannot tell right
               now", exit 2, and it must not ring. KNMI's key is shared by
               every unregistered user, so this recurs all day (8 times on
               8/16, 165 times on record) with no cause on our side. An alarm
               that fires on a benign recurring condition is training to
               ignore alarms.
               It escalates: THROTTLED-STUCK after THROTTLE_STREAK consecutive
               rounds, which is exit 1, because "throttled for three hours" is
               no longer a transient and stops being a thing I can wait out.
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

Exit 0 every source OK, 1 a source is down, 2 the only non-OK verdicts were
"I cannot tell" (throttled). That matters more than the text: a report nobody
reads is decoration, and the first version of half the checks in this repo only
printed -- but a report that cries down when it means cannot-tell is worse than
decoration, because it spends the next hour on a network that is fine.

    python3 ops/source_health.py            # all sources
    python3 ops/source_health.py jma wms    # a subset

Probe skies are inside each source's declared coverage and deliberately spread
out, so a single dead radar does not read as a dead service.
"""
import json
import os
import sys
import time
import contextlib
import io
import traceback

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
# The repo root too, because some adapters reach `import runemap`.
#
# 2026-08-17. Without this, `source_health.py zurich` printed
# ModuleNotFoundError while the full fleet run printed OK for the same source
# in the same minute. The adapter was only ever importable because an earlier
# probe -- echo_motion, pulled in by JMA -- had inserted the root as a side
# effect. Proof was a clean pair: `zurich` alone ERRORs, `jma zurich` passes.
#
# So the fleet's green light for Switzerland **was passing for a reason it did
# not state**: not "this adapter works" but "something before it fixed the
# path". And the broken half was the single-source form, which is the one I
# reach for precisely when a source is misbehaving -- the monitor was fine and
# the diagnostic lied, which is the worse way round.
sys.path.insert(0, os.path.abspath(_ROOT))

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


#: How many consecutive throttled rounds before it stops being transient. At
#: one round per 20 minutes this is three hours. Derived from the condition it
#: judges, not picked round: KNMI's shared quota refills continuously, so a
#: source still throttled after three hours is not waiting for a refill -- it is
#: something else wearing a 429, and I want to be told.
THROTTLE_STREAK = 9

#: Beside the cache, so both pool members and cron share one count. A streak
#: kept in memory would reset every run, i.e. never escalate -- a guard whose
#: release condition can only be met by the thing it forbids.
STREAK_FILE = os.environ.get(
    "RUNEMAP_HEALTH_STREAKS",
    os.path.join(os.environ.get("RUNEMAP_CACHE", "/tmp"), "health_streaks.json"))

#: The adapters announce a backoff in their own words. Matched on the shape
#: they all share rather than on one service's spelling, because the next
#: source to hit a shared quota will not say "KNMI".
_THROTTLE_MARKS = ("RATE-LIMITED", "RATE-LIMIT", " 429", "429 ")


def _throttled(stderr_text):
    return any(m in stderr_text for m in _THROTTLE_MARKS)


#: A source can answer and still arrive missing a piece of itself. DMI declines
#: when more than its own MAX_NODATA_SHARE of the window has no data, and that
#: reached here as NO-MAP -- "declined inside its own coverage" -- which aims
#: the next hour at licensing or a coverage rectangle. The truth is the
#: opposite: the frame came back, and a fixed part of the radar network is
#: absent from it.
#:
#: 2026-08-19, measured before naming it. Over ~5200 rounds there are two
#: episodes, twelve rounds total, and inside each episode the blind share is
#: CONSTANT to the digit -- 43% for four rounds, 31% for eight. Weather and
#: noise wander; a value pinned for two and a half hours is a fixed set of
#: radars or sectors missing. So this stays exit 1: upstream really is degraded.
#:
#: What was wrong was the word, not the bell. I had written this down as
#: possibly the same shape as KNMI's shared quota and planned to either silence
#: it or add a streak threshold -- and the log says the bell already rings once
#: per episode and reports the recovery, which is exactly the shape I want.
#: THROTTLED must not ring because nothing on either side is broken and it
#: recurs all day; this must, because part of a national radar network is gone
#: for hours. Buying silence here with a threshold would have hidden the one
#: verdict in this family that is about the data itself.
_BLIND_MARK = "MOSTLY-BLIND"


def _streaks(update=None):
    """Read, and optionally rewrite, the consecutive-throttle count per label.

    Failure to read is not failure to run: a missing or corrupt file means no
    streak is known, which reports as transient. That errs toward the quiet
    verdict on purpose -- the loud one is available the moment the file works
    again, and an unreadable state file must not manufacture an alarm.
    """
    try:
        with open(STREAK_FILE, encoding="utf-8") as f:
            cur = json.load(f)
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    if update is None:
        return cur
    try:
        tmp = STREAK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(update, f)
        os.replace(tmp, STREAK_FILE)
    except OSError as e:
        sys.stderr.write("HEALTH-STREAK-UNWRITABLE %s: %s\n" % (STREAK_FILE, e))
    return update


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
        # Backing off from a shared quota is the adapter doing its job. It
        # arrives here looking exactly like a dead upstream -- draw() returned
        # None inside declared coverage -- and only the reason it wrote tells
        # the two apart. Reported as NO-MAP it says "the Dutch radar network is
        # down", which it is not, once every couple of hours, forever.
        if _throttled(said.getvalue()):
            return "THROTTLED", ("%s: upstream rate-limited us and the adapter"
                                 " backed off (%.2fs)%s" % (label, took, because))
        # "It answered but is missing a piece of itself" also arrives as that
        # same None, and it is the only member of this family that is about the
        # data rather than about the exchange. See _BLIND_MARK.
        if _BLIND_MARK in said.getvalue():
            return "PARTIAL-BLIND", (
                "%s: the frame arrived and part of the network is missing from"
                " it, past the adapter's own blind-share limit -- upstream is"
                " degraded, not refusing us, and not slow (%.2fs)%s"
                % (label, took, because))
        # "It refused" and "we gave up waiting" reach this line as the same
        # None. 2026-08-17: MeteoSwiss went from 2.4s to 48s to 98s, and the
        # probe called it `declined inside its own coverage -- no reason given`.
        # That sentence sends the next hour at the wrong thing: a refusal is a
        # question about coverage or licensing, a timeout is a question about
        # whether upstream is alive and whether our own limit is right.
        #
        # The elapsed time already distinguishes them and was already being
        # printed. The threshold is the adapter's OWN timeout rather than a
        # number of mine, so it stays true when someone retunes the adapter --
        # 48s was exactly 4 x its 12s, which is what a run of timeouts looks
        # like and is nothing a refusal would ever produce.
        # Ask the words before the arithmetic. 2026-08-19: DWD came back
        # `NO-MAP wms-berlin: declined inside its own coverage (7.36s) --
        # WMS-FAILED de-dwd-wn TimeoutError('The read operation timed out')` --
        # a verdict that says "it refused" sitting directly on top of evidence
        # that says "we stopped waiting". The elapsed-time rule below missed it
        # because 7.36s is 1.23x the adapter's 6s timeout, not 2x: one inner
        # request timed out at its own limit and the adapter gave up promptly,
        # which is a fast failure, not a slow one.
        #
        # Counted over the whole log before changing anything: **15 rounds said
        # `declined` while their own reason line said timeout, against 4 that
        # SLOW-NO-MAP caught.** Inferring the mechanism from elapsed time was
        # wrong more often than right, and the adapter had said so in words each
        # time. Same correction as PARTIAL-BLIND made this morning: when the
        # thing being measured states what happened, read that, and keep the
        # inference only for the case where it says nothing.
        to = getattr(mod, "TIMEOUT", None)
        said_timeout = any(m in said.getvalue().lower()
                           for m in ("timeout", "timed out"))
        if said_timeout or (isinstance(to, (int, float)) and to > 0
                            and took >= 2 * to):
            if said_timeout:
                how = "the adapter said so"
            else:
                how = "%.1fx its own %.0fs timeout" % (took / to, to)
            return "SLOW-NO-MAP", (
                "%s: no frame after %.2fs -- upstream too slow to answer, not a"
                " refusal (%s)%s" % (label, took, how, because))
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
    # Streaks are only kept honest when the whole fleet is asked. A subset run
    # ("source_health knmi") would otherwise zero every label it did not look
    # at, and a person debugging one source would silently reset the escalation
    # on all the others.
    whole_fleet = not wanted
    streaks = _streaks()
    bad = 0        # something is broken -> exit 1
    unknown = 0    # cannot tell right now -> exit 2, and no bell
    for label, modname, sky, fallback, want in rows:
        state, msg = check(label, modname, sky, fallback, want)
        if state == "THROTTLED":
            n = int(streaks.get(label, 0)) + 1
            streaks[label] = n
            if n >= THROTTLE_STREAK:
                state = "THROTTLED-STUCK"
                msg += (" -- %d consecutive rounds, past the %d that count as"
                        " transient; this is no longer a quota refilling"
                        % (n, THROTTLE_STREAK))
        elif label in streaks:
            del streaks[label]
        print("%-15s %s" % (state, msg))
        if state == "THROTTLED":
            unknown += 1
        elif state != "OK":
            bad += 1
    if whole_fleet:
        _streaks(streaks)
    # Three counts, printed separately, because collapsing them is the bug this
    # change exists to fix: "12 of 13 healthy" said the same thing whether the
    # Dutch radar was dead or merely busy.
    print("-- %d of %d healthy%s%s"
          % (len(rows) - bad - unknown, len(rows),
             ", %d down" % bad if bad else "",
             ", %d could not be determined" % unknown if unknown else ""))
    sys.exit(1 if bad else (2 if unknown else 0))


if __name__ == "__main__":
    main()
