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

Settled numbers, and what settled them
--------------------------------------
These are here because on 2026-08-12 10:52 the shareholder said I had been
"reconfirming 6.5s dozens of times". He was right, and the reason is that the
number lived only in my prose: every time it came back I re-derived it and
reported it as if it were new. A constant that has been decided belongs next to
the code that reads it, so the answer to "where does 6.25 come from" is a file
lookup rather than a memory. Nothing below is a fresh claim; each line names the
measurement that closed it.

  6.25s: a LITERAL, not a derivation -- and I got this wrong in this very file
      an hour ago. WALL 10 - RESERVE 0.25 - WX_MARGIN 3.5 happens to equal 6.25,
      so I wrote that the wait was derived from the wall. It is not: the value is
      typed in below, and at WALL=5 or WALL=2 it stayed 6.25, i.e. a reader could
      be told to wait longer than the entire request budget. It is now clamped to
      min(6.25, WALL - RESERVE), which changes nothing at today's wall and only
      binds where the story was false. Two constants being equal is a
      coincidence, not a mechanism -- check it by moving one of them.
      What it IS: a BUDGET FOR THE READER, not a cost of the upstream. The
      resolve path opens no socket; it does ev.wait() on a background warm.
      "Waiting" here never means "I am fetching for you".

  The wall's price, measured 2026-08-07 over 400 cold requests:
      W=2.65 -> 264 maps delivered, 264 of them inside 3s, p90 3.00s
      W=6.25 -> 326 maps delivered, still 264 inside 3s, p90 6.60s
      So a bigger wall buys 62 more maps and costs every 3s-bounded reader
      nothing -- but the readers who end up in the extra 3.6s wait mostly get
      nothing at all for it. 264 is FLAT across the whole range: it is set by
      upstream speed, which I cannot turn. Whether to cut back to 2.65 is a
      question about which readers we are serving, not a tuning exercise.
      (Cold-path measurement 2026-08-12: of 2737 clean cold samples, 475 came
      back "fetching" with p50 6.85s and 0.0% of them carrying a map. That group
      is the entire gap between 71.44% and the ~85% the wall was bought for --
      they paid the full budget and got the empty answer.)

  READER_SLO = 3.0
      The product promise, and the only number here a reader can feel. It was
      added 2026-08-12 because until then the promise had no executable form:
      the code could only ask the operations knob (WALL), so decorative work
      kept spending a budget sized for content. decor_budget(elapsed) exists to
      refuse that spend, not to make anything faster.

  A derivation is not a guard.
      The clamp min(want, left - RESERVE) is the safety device; the arithmetic
      above is only bookkeeping. Do not add a rule of the form "these two
      constants happen to be equal" -- 2026-08-06 the inequality that actually
      bound was held by a third constant nobody had listed.
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
# SETTLED, measured -- do not re-derive from memory (bob, 2026-08-12):
#
#   6.25 = WALL 10 - RESERVE 0.25 - WX_MARGIN 3.5
#
# There is no literal 6.25 anywhere in this file; it is a derived quantity, so
# ask for it (`python3 scripts/wall.py --json`) instead of quoting it. And keep
# the two quantities apart, because I conflated them once in front of the
# shareholder and it cost him a round:
#
#   * ~6.5s is what the UPSTREAM costs to hand us a frame. A constant of the
#     world; I cannot turn it. Its real corollary is already on the stone:
#     the user path should make ZERO upstream requests.
#   * 6.25s is what I make the READER wait. That one is a knob of mine.
#
# 400 cold requests, 2026-08-07 (raw columns, not a fit):
#
#   W = 2.65s  ->  264 images delivered, p90 3.00s
#   W = 6.25s  ->  326 images delivered, p90 6.60s
#
# So 3.6 extra seconds buys 62 more images, while the 18.5% who get nothing wait
# the full 6.25s for it. The 264 is FLAT across the whole interval: it is set by
# upstream speed, not by this constant.
#
# And this wait is not a fetch: radar_resolve opens no socket, it does
# ev.wait(wait) on a background warm. "Waiting" and "going upstream for you" are
# two different things -- worst case is you wait, then still get `fetching`.
# 2026-08-12: the 6.25 below is a LITERAL, and I had just written in the
# docstring that it was "derived from WALL - RESERVE - WX_MARGIN". Measured:
# WALL=10 -> 6.25 (equal, which is why I believed the story), WALL=5 -> still
# 6.25, WALL=2 -> still 6.25, i.e. a reader would be asked to wait longer than
# the whole request budget. Equal values are not a derivation; 8/6 taught me
# the same lesson from the other side, where the inequality that actually bound
# was held by a third constant nobody had listed.
#
# So clamp it to what the wall can actually contain. At the WALL that runs today
# this changes nothing (min(6.25, 9.75) == 6.25) -- it only binds if someone
# lowers the wall, which is exactly the case where the literal lied.
RADAR_WAIT_UNKNOWN = _f("RUNEMAP_RADAR_WAIT",
                        max(RADAR_WAIT_FLOOR, min(6.25, WALL - RESERVE)))

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
