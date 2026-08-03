"""No blocking call on the request thread may outlive the request deadline.

Why this exists
---------------
_MO_BUDGET = 3.0 was correct code. Under the 18s budget it shipped with, a 3s
wait for motion was a small slice. Narrowing the request budget to 3s is what
turned it into a violation -- and nobody told it, because it never asked. The
whole file consulted net_budget.current_deadline() exactly once, in the wait
that was written after the narrowing.

So the defect class is not "someone wrote a slow wait". It is:

    a guard exists, but not on the path the work actually takes.

A grep for `_MO_BUDGET` would have found this one instance and nothing else.
This test instead instruments the blocking primitives themselves, so the next
wait -- one nobody has written yet, in a function this file does not name --
is caught the same way.

Scoping is free: net_budget's deadline is thread-local, so background warm
threads (which are supposed to outlive the response, that is their job) have
no deadline and are never flagged. Only a thread that promised a wall is held
to it.

Calibration -- the part that makes this a ruler and not a decoration
--------------------------------------------------------------------
Ran against ede4d59^ (motion still joined on the request thread), this test
MUST fail. Ran against ede4d59 and later, it must pass. A test that has never
been seen red is a test whose failure mode is untested; today alone I watched a
`journalctl` query print 0 rows and mean nothing, a probe measure `sed`'s exit
code instead of the program's, and 9/9 green against a mock upstream that did
not echo the one header production sends. Green is only evidence if red was
reachable.

    tests/calibrate_deadline_audit.sh   runs both commits and checks both colours.
"""
import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, ".."))
import net_budget
import render_scene as R
import wall as W

TOL = 0.15          # scheduler slop; a real violation here is seconds, not ms
WALL = W.WALL       # never a literal: a ruler that measures a wall the service
                    # no longer has is the decoration this file exists to catch
RESERVE = W.RESERVE # time the response still needs after the last wait returns
                    # -- the same margin radar_resolve already keeps for itself
                    # (min(wait, left - 0.25)). A wait that asks for the entire
                    # remainder has not left the wall anything to be met with:
                    # the bytes still have to be rendered and written.


class Recorder:
    """Wraps Event.wait / Thread.join / time.sleep and remembers who blocked.

    A call is a violation when, at the moment it was made, a request deadline
    existed and the call blocked past it. Not "blocked longer than we like" --
    blocked past the wall its own thread had already promised.
    """

    def __init__(self):
        self.calls = []          # (name, requested, elapsed, left_at_call)
        self._patches = []

    def _wrap(self, obj, name):
        orig = getattr(obj, name)

        def wrapper(*a, **kw):
            dl = net_budget.current_deadline()
            left = dl.left() if dl is not None else None
            t0 = time.time()
            try:
                return orig(*a, **kw)
            finally:
                el = time.time() - t0
                if left is not None:
                    # a[0] is self: these are class attributes, so the wrapper
                    # receives the instance. Reading a[0] as the timeout logged
                    # a Thread object as "the requested wait" and the rule below
                    # silently compared None.
                    req = (a[1] if len(a) > 1 else kw.get("timeout"))
                    self.calls.append((
                        "%s.%s" % (obj.__name__ if isinstance(obj, type)
                                   else type(obj).__name__, name),
                        req, el, left))
        setattr(obj, name, wrapper)
        self._patches.append((obj, name, orig))

    def __enter__(self):
        self._wrap(threading.Event, "wait")
        self._wrap(threading.Thread, "join")
        # time.sleep is a module attribute; patch it where render_scene looks it
        # up, not just in the time module, or a `from time import sleep` escapes.
        self._orig_sleep = time.sleep
        time.sleep = self._sleep
        return self

    def _sleep(self, secs=0):
        dl = net_budget.current_deadline()
        left = dl.left() if dl is not None else None
        t0 = time.time()
        try:
            return self._orig_sleep(secs)
        finally:
            if left is not None:
                self.calls.append(("time.sleep", secs, time.time() - t0, left))

    def __exit__(self, *exc):
        for obj, name, orig in self._patches:
            setattr(obj, name, orig)
        time.sleep = self._orig_sleep
        return False

    def violations(self):
        """Two rules, and the first one is the one that matters.

        (a) asked for a cap that does not fit inside what is left, minus the
            reserve the response still needs. This is the invariant: a wait
            that names such a cap did not consult the wall, whether or not the
            peer happened to answer in time.

            Two earlier versions of this rule were green against the commit I
            know is sick. "Blocked past the deadline" missed it because the
            3.0s join with 3.0s left returned at exactly the wall. "Asked for
            more than was left" missed it too, for the same arithmetic: asking
            for precisely all of it is not asking for more. Both readings were
            defensible and both were decorations. What is actually wrong with
            that join is that it leaves nothing for rendering and writing --
            so that is what the rule now says.

        (b) blocked past the deadline anyway. Catches waits with no explicit
            cap at all, which rule (a) cannot see.
        """
        out = []
        for c in self.calls:
            name, req, elapsed, left = c
            if req is not None and req > left - RESERVE + TOL:
                out.append(c)
            elif elapsed > left + TOL:
                out.append(c)
        return out


class Deadlines(unittest.TestCase):
    def setUp(self):
        for d in (R._RA_INFLIGHT, R._RA_FAIL, R._MO_CACHE):
            d.clear()
        R._MO_BUSY.clear()
        self._peek, self._get = R._peek, R._get
        self.addCleanup(setattr, R, "_peek", self._peek)
        self.addCleanup(setattr, R, "_get", self._get)
        # These two were replaced inside a test body with no cleanup, so this
        # file left a stubbed render_scene behind for everything that ran after
        # it: test_radar_states passed alone (12/12 OK) and failed 5 in the full
        # suite. A suite that is red for reasons nobody owns stops being a gate --
        # this morning it could not tell me whether my own change broke anything.
        self.addCleanup(setattr, R, "ascii_radar", R.ascii_radar)
        self.addCleanup(setattr, R, "_radar_list_url", R._radar_list_url)

    def _stall(self, *a, **kw):
        """An upstream that never answers, bounded only by whoever is waiting.

        The point of the audit is what the *caller* does about a slow peer, so
        the peer is made maximally slow and given no way to be the hero.
        """
        self._orig_sleep_ref(30)
        raise net_budget.BudgetExceeded("http://stalled/", 30, "test", 0)

    def test_render_path_respects_the_wall(self):
        """Walk the request path under a 3s budget with every upstream stalled.

        Frames are 'in cache' so the path proceeds to render and, on the old
        code, into the motion join. ascii_radar is stubbed because this test
        measures waiting, not pixels -- rendering was measured separately at
        43ms/frame and is not the subject.
        """
        self._orig_sleep_ref = time.sleep
        R._peek = lambda url: b"\x89PNG-not-real"
        R._get = self._stall
        R.ascii_radar = lambda *a, **kw: ("art", "km")
        # Six frames an hour apart, because echo_motion returns instantly on
        # fewer than four -- my first fixture had two, the compute thread
        # exited before the join could block, and this test came back GREEN
        # against the commit I know is sick. The ruler was the decoration it
        # is written to prevent, for about ten minutes.
        imgs = [["/%d.png" % i, str(1000 + i * 1200), [0.0, 0.0, 1.0, 1.0]]
                for i in range(6)]
        R._radar_list_url = lambda token, lng, lat: "http://stalled/radar"
        import json as _json
        R._peek = lambda url: (
            _json.dumps({"status": "ok", "images": imgs}).encode()
            if "radar" in url else b"\x89PNG-not-real")

        with Recorder() as rec:
            t0 = time.time()
            with net_budget.request_budget(WALL):
                try:
                    R.radar_resolve("><", 1.0, 1.0, "T")
                except Exception:
                    pass          # a raise is not what we are measuring here
            el = time.time() - t0

        bad = rec.violations()
        for name, req, elapsed, left in bad:
            print("\n  VIOLATION %s(timeout=%s) blocked %.2fs with %.2fs left"
                  % (name, ("%.2f" % req) if req is not None else "none",
                     elapsed, left))
        self.assertFalse(
            bad,
            "%d blocking call(s) on the request thread outlived the deadline; "
            "the wall is enforced on some waits and not others" % len(bad))
        self.assertLess(el, WALL + TOL,
                        "request path took %.2fs under a %.1fs budget" % (el, WALL))

    def test_the_recorder_can_see_a_violation(self):
        """The ruler must be able to read a known-bad value.

        Without this, a recorder that silently records nothing would report a
        clean bill of health for any code at all -- which is the exact failure
        (an instrument that cannot fail) this whole test exists to prevent.
        """
        with Recorder() as rec:
            with net_budget.request_budget(0.3):
                threading.Event().wait(1.0)          # asks 1.0s, has 0.3s
        self.assertEqual(len(rec.violations()), 1,
                         "recorder failed to flag a deliberate 1.0s wait "
                         "against a 0.3s budget: %r" % (rec.calls,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
