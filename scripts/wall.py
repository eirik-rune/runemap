#!/usr/bin/env python3
"""The wall, and everything derived from it. One number, one place.

Why a module for four constants
-------------------------------
The 3s ceiling was written down in at least fourteen places: two Python
defaults, two environment variables that systemd never set (so the code
defaults were what actually ran, while the config *looked* authoritative),
a shell probe, a status page's `good()`, that same page's prose promise
"under 3 seconds", an SLO window, a demo assertion, and four test literals.
Changing the wall meant finding all of them, and the failure mode when you
miss one is not a crash -- it is a page that says one thing and counts
another. That already happened here once: the page promised under 3 seconds
while its statistics were still scoring an old 20s column.

So: the number lives here, and everything else asks. Shell callers included:

    python3 scripts/wall.py --print wall       -> 10.0
    python3 scripts/wall.py --json             -> {"wall": 10.0, ...}

Changing the wall
-----------------
Set RUNEMAP_SCENE_BUDGET (systemd unit, or the environment of whatever runs
serve.py) and every consumer moves together. The defaults below are what runs
when nothing is set, which is the case in production today -- so they are the
real configuration, not a fallback, and they are edited with that in mind.

2026-07-31: 3.0 -> 10.0. Not a performance regression: the shareholder's
complaint was "I often see no radar at all", and a cold sky needs one list
fetch (~1s) plus one frame (1-3s) before there is anything to draw. Under a 3s
wall that work could not finish inside a request, so the honest answer was
always "fetching". The wall was not costing latency, it was costing content.

The 6.25s that keeps getting rediscovered
-----------------------------------------
6.25 = WALL 10.0 - RESERVE 0.25 - WX_MARGIN 3.5. It appears as no literal
anywhere, which is why I have reported it to the shareholder twice as if it
were a new finding. It is not a cost and not a measurement: it is the reader's
waiting budget, the time radar_resolve is allowed to spend on ev.wait() before
it must answer with whatever is in hand.

What it is not: radar_resolve opens no socket. It waits on the background warm
worker. So "the reader waits 6.25s" never means "we spend 6.25s fetching for
this reader" -- nobody is fetching on their behalf.

Measured 2026-08-07, 400 cold requests per arm:
    W = 2.65  ->  264 images, p90 3.00s
    W = 6.25  ->  326 images, of which 264 inside the 3s promise, p90 6.60s
264 is flat across the whole interval. That number is set by upstream speed,
not by this constant -- widening W buys later images, not more images inside
the promise. Which is why READER_SLO below exists as its own number.

"""
import json
import os
import sys
import time

__all__ = ["WALL", "RESERVE", "WX_MARGIN", "RADAR_WAIT_UNKNOWN",
           "RADAR_WAIT_COOLDOWN", "READER_SLO", "radar_wait",
           "decor_budget", "as_dict"]


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


# The ceiling for one request, end to end. Nothing on the request path may
# wait past it, and every wait must leave RESERVE for rendering and writing.
WALL = _f("RUNEMAP_SCENE_BUDGET", 10.0)

# What the response still needs after the last wait returns. radar_resolve
# has always kept this margin for itself; it is named here because the audit
# test measures every wait against it.
RESERVE = _f("RUNEMAP_WALL_RESERVE", 0.25)

# Room the weather join needs after radar returns: serve.py joins the wx
# thread with left - 0.1 and then renders. Radar must not eat this.
WX_MARGIN = _f("RUNEMAP_WX_MARGIN", 3.5)

# Never wait less than this for an unknown sky, whatever the arithmetic says.
RADAR_WAIT_FLOOR = _f("RUNEMAP_RADAR_WAIT_FLOOR", 1.2)

# How long a reader waits for a sky we know nothing about.
#
# This is a PRODUCT parameter -- how long a person stares at a blank page --
# and until 8/7 it was arithmetic on WALL, which is an OPS knob for how long
# a request may hold a socket. Raising the wall on 8/2 silently moved the
# reader-facing wait from 1.2s to 6.25s. Nobody decided that; subtraction did.
#
# The clamp in radar_wait() is what keeps a wait inside the wall, and it is
# unchanged. That is the safety. The derivation was never the safety, it was
# a coupling that let one number move another behind our back.
#
# The value below is the one the derivation happened to produce, so this
# commit changes no behaviour. What it changes is that moving it is now a
# decision with a number attached. Measured 8/7 over 400 cold requests:
#
#   wait   maps delivered   maps within the 3s SLO   p90 of all readers
#   2.65s       264                  264                   3.00s
#   6.25s       326                  264                   6.60s
#
# The extra 3.6s buys 62 maps, every one of them arriving after the 3s SLO,
# and costs the 18.5% who get no map at all a 6.25s stall. Whether that is a
# good trade depends on whether our readers are humans who leave at 3s or
# agents who do not -- a question about users, which I cannot answer from
# inside. It is filed rather than decided here.
#
# The floor is not decoration. Derived purely as WALL - RESERVE - WX_MARGIN, a
# wall set back to 3.0 yields -0.75 -> 0.0: radar would stop waiting entirely,
# which is worse than the 1.2 it replaced. A default that only makes sense at
# one value of its input is a trap for whoever changes the input next -- and
# the whole point of this module is that someone will.
RADAR_WAIT_UNKNOWN = _f("RUNEMAP_RADAR_WAIT", max(RADAR_WAIT_FLOOR, 6.25))

# How long to wait for a sky that just refused us. The failure counter is
# already in cooldown; waiting the full budget on a peer that said no 30
# seconds ago spends the reader's time on a coin flip we just lost.
RADAR_WAIT_COOLDOWN = _f("RUNEMAP_RADAR_WAIT_COOLDOWN", 1.5)


# How long a reader is willing to stare at nothing. THIS IS THE PRODUCT
# PARAMETER, and until today it had no executable existence anywhere on the
# request path -- the docstring above lists where 3s actually lived: an SLO
# window, a demo assertion, and four test literals. Not one of them is reachable
# from serving code. So any wait that wanted to be polite to the reader had
# nothing to ask, and asked WALL instead, which is an ops knob for how long a
# request may hold a socket. That is how raising the wall on 8/2 moved the
# reader-facing radar wait from 1.2s to 6.25s with nobody deciding it, and how
# the motion join ended up capped by "how long the computation takes" -- the
# producer's question -- instead of "what is a decorative line worth to someone
# who is waiting" (Luoshu, 8/12: evidence only answers the question it was
# designed to answer).
#
# The value is unchanged from what the prose always promised. What changes is
# that moving it is now a decision with a number attached, in one place, that
# code can read.
READER_SLO = _f("RUNEMAP_READER_SLO", 3.0)


def decor_budget(elapsed, cap=None, left=None):
    """Seconds a DECORATIVE wait may still spend, given time already spent.

    Derived from what has been consumed, not from a constant: a map that took
    0.3s can afford a little more, a map that took 2.5s can afford none. A
    decorative wait is one whose absence costs a line of text, never the map.

    `elapsed` -- seconds since the request started.
    `cap`     -- the mechanism's own ceiling, if it has one.
    `left`    -- remaining request deadline; the hard wall still binds, because
                 READER_SLO is a promise about people and WALL is a promise
                 about sockets, and violating the second one drops the map.
    """
    want = READER_SLO - float(elapsed) - RESERVE
    if cap is not None:
        want = min(want, float(cap))
    if left is not None:
        want = min(want, float(left) - RESERVE)
    return max(0.0, want)


def radar_wait(cooling=False, left=None):
    """Seconds the request thread may wait for radar frames.

    `cooling` -- the sky failed recently (state 2 with a fail counter).
    `left`    -- remaining request deadline, if there is one.

    The clamp is the invariant the audit test enforces: a wait may never ask
    for more than `left - RESERVE`. Two budgets that are each reasonable on
    their own is exactly how 1.2 + 3.0 walked through a 3s wall.
    """
    want = RADAR_WAIT_COOLDOWN if cooling else RADAR_WAIT_UNKNOWN
    if left is None:
        return max(0.0, want)
    return max(0.0, min(want, left - RESERVE))


HISTORY = os.environ.get("RUNEMAP_WALL_HISTORY", "/var/lib/runemap/wall_history.csv")


def record(path=None):
    """Append (ts, wall) when the wall differs from the last recorded value.

    The status page must judge every sample against the wall that was in force
    when the sample was taken -- rescoring history under today's ruler turns a
    config change into retroactive success, which is the same lie as a page
    that promises one number while counting another.

    That means someone has to know when the wall moved. Not someone: something.
    A switch date maintained by hand is a fact kept in a memory, and today
    alone I watched a 24h window silently span a restart nobody recorded, a
    gate installed after the restart it was meant to guard, and a marker script
    wired to a code path that had been replaced. So the process that runs with
    the wall writes the wall down, every time it starts.

    Returns the row appended, or None when the wall has not moved.
    """
    path = path or HISTORY
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        last = None
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) == 2 and parts[0].isdigit():
                        last = float(parts[1])
        if last is not None and abs(last - WALL) < 1e-9:
            return None
        row = "%d,%g\n" % (int(time.time()), WALL)
        with open(path, "a") as f:
            f.write(row)
        return row.strip()
    except OSError:
        # Never let bookkeeping stop the service from starting. A missing
        # history file degrades the status page's honesty, not the product.
        return None


def history(path=None):
    """[(ts, wall)] oldest first. Empty when nothing was ever recorded."""
    path = path or HISTORY
    out = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 2 and parts[0].isdigit():
                    out.append((int(parts[0]), float(parts[1])))
    except OSError:
        return []
    return sorted(out)


def wall_at(ts, path=None):
    """The wall in force at `ts`.

    Before the first recorded row the honest answer is "the wall we had before
    we started writing them down" -- 3.0, the value this file replaced. It is
    named here rather than assumed so that reading the page tells you which
    ruler scored which era.
    """
    prev = PRE_HISTORY_WALL
    for t, w in history(path):
        if t <= ts:
            prev = w
        else:
            break
    return prev


PRE_HISTORY_WALL = _f("RUNEMAP_PRE_HISTORY_WALL", 3.0)


def as_dict():
    return {"wall": WALL, "reserve": RESERVE, "wx_margin": WX_MARGIN,
            "radar_wait_unknown": RADAR_WAIT_UNKNOWN,
            "radar_wait_cooldown": RADAR_WAIT_COOLDOWN,
            "reader_slo": READER_SLO}


def main(argv):
    if "--json" in argv:
        print(json.dumps(as_dict()))
        return 0
    if "--print" in argv:
        key = argv[argv.index("--print") + 1] if len(argv) > argv.index("--print") + 1 else "wall"
        d = as_dict()
        if key not in d:
            sys.stderr.write("unknown key %r; have %s\n" % (key, ", ".join(sorted(d))))
            return 2
        # Print it the way a shell wants it: bare, no newline games, no label.
        # A probe that has to parse a sentence will one day parse it wrong.
        print(("%g" % d[key]))
        return 0
    sys.stderr.write(__doc__.split("\n\n")[0] + "\n\n"
                     "usage: wall.py --print <wall|reserve|radar_wait_unknown|"
                     "radar_wait_cooldown>\n       wall.py --json\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
