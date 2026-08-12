"""A wait a reader experiences must not move when an ops knob moves.

On 8/2 the wall went from 3.0 to 10.0 to buy content: a cold sky needs a list
fetch plus a frame before there is anything to draw. That was the right call.
What nobody decided was that the same edit moved the reader-facing wait from
1.2s to 6.25s, because RADAR_WAIT_UNKNOWN was defined as WALL - RESERVE -
WX_MARGIN. It took five days and a latency histogram to notice.

"A product parameter must not hang off an ops knob" was already written in my
core memory when that happened. A rule with no guard behind it is worth exactly
what a rule in a comment is worth, which is why this file exists.

What is deliberately NOT asserted: radar_wait(left=...) depends on the deadline,
and must. That clamp is the safety -- it is what keeps any wait inside the wall.
The ban is on the DEFAULT moving by itself, not on a wait being cut short when
the request is already running out of time.
"""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Every constant here is a duration a person spends looking at an unfinished
# page. Add to this list, not to the assertion below.
READER_FACING = ["RADAR_WAIT_UNKNOWN", "RADAR_WAIT_COOLDOWN", "RADAR_WAIT_FLOOR"]

OPS_KNOB = "RUNEMAP_SCENE_BUDGET"


def _wall_at(budget):
    """Import wall.py fresh with the ops knob set to `budget`."""
    saved = {k: os.environ.get(k) for k in list(os.environ) if k.startswith("RUNEMAP_")}
    # Overrides for the product params themselves would mask the coupling, so
    # this measures the defaults, which is what production actually runs.
    for k in list(os.environ):
        if k.startswith("RUNEMAP_"):
            del os.environ[k]
    os.environ[OPS_KNOB] = str(budget)
    try:
        import wall
        importlib.reload(wall)
        return dict((k, getattr(wall, k)) for k in READER_FACING), wall.WALL
    finally:
        for k in list(os.environ):
            if k.startswith("RUNEMAP_"):
                del os.environ[k]
        os.environ.update(dict((k, v) for k, v in saved.items() if v is not None))
        import wall
        importlib.reload(wall)


# A wall is ROOMY when it can hold the whole default wait; then the default is
# not allowed to move at all. It is TIGHT when it cannot; then the default is
# required to move, downwards, to stay inside the request. 6.5 = 6.25 + 0.25.
ROOMY_WALLS = [10.0, 30.0, 100.0]
TIGHT_WALLS = [2.0, 3.0]


def _walls_measured(roomy, tight):
    a, b = {}, {}
    for dst, budgets in ((a, roomy), (b, tight)):
        for w in budgets:
            vals, wall_val = _wall_at(w)
            assert wall_val == w, "the knob itself must move, or this measures nothing"
            for k, v in vals.items():
                dst.setdefault(k, []).append((w, v))
    return a, b


def _violation(measured):
    """Pure. Returns a message naming the offender, or None."""
    roomy, tight = measured
    import wall as _w
    reserve = _w.RESERVE
    floor = _w.RADAR_WAIT_FLOOR
    for k, pairs in sorted(roomy.items()):
        seen = set(v for _, v in pairs)
        if len(seen) != 1:
            return ("%s moved while the wall was roomy: %s -- a reader-facing "
                    "wait was derived from an ops knob, which is how 1.2s "
                    "silently became 6.25s" % (k, pairs))
    for k, pairs in sorted(tight.items()):
        for w, v in pairs:
            ceiling = max(floor, w - reserve)
            if v > ceiling + 1e-9:
                return ("%s is %.2f at wall %.1f, i.e. longer than the whole "
                        "request budget (%.2f) -- a reader would be asked to "
                        "wait past the deadline" % (k, v, w, ceiling))
    return None


class ProductParamsAreIndependentOfTheWall(unittest.TestCase):

    def test_reader_waits_do_not_move_when_the_wall_moves(self):
        """Constant where the wall is roomy; clamped where it is not.

        The first version of this asserted one value across all walls, which
        made it reject the fix for its own bug: at WALL=2 a reader was told to
        wait 6.25s inside a 2s request budget, and clamping the default to
        WALL - RESERVE necessarily makes the value move with the wall. A guard
        that cannot tell "proportional to the knob" from "bounded by the
        request" encodes the wrong requirement, so both halves are asserted
        separately below.
        """
        v = _violation(_walls_measured(ROOMY_WALLS, TIGHT_WALLS))
        self.assertIsNone(v, v)

    def test_the_guard_rejects_a_genuinely_proportional_wait(self):
        """Negative control: without this, the split above could pass anything."""
        proportional = {"RADAR_WAIT_UNKNOWN": [(10.0, 6.25), (30.0, 18.75),
                                               (100.0, 62.5)]}
        v = _violation((proportional, {}))
        self.assertIsNotNone(v, "a wait scaling with the knob must be rejected")
        self.assertIn("RADAR_WAIT_UNKNOWN", v)

    def test_the_guard_rejects_a_wait_longer_than_the_request(self):
        """Negative control for the other half: unclamped at a tiny wall."""
        unclamped = {"RADAR_WAIT_UNKNOWN": [(2.0, 6.25)]}
        v = _violation(({}, unclamped))
        self.assertIsNotNone(v, "a wait exceeding the whole budget must be rejected")
        self.assertIn("2.0", v)

    def test_the_deadline_clamp_is_still_in_force(self):
        """The ban above must not be read as 'waits ignore the deadline'."""
        import wall
        importlib.reload(wall)
        self.assertLessEqual(wall.radar_wait(left=3.0), 3.0 - wall.RESERVE + 1e-9)
        self.assertEqual(wall.radar_wait(left=0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
