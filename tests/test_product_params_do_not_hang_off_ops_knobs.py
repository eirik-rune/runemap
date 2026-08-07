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


class ProductParamsAreIndependentOfTheWall(unittest.TestCase):

    def test_reader_waits_do_not_move_when_the_wall_moves(self):
        budgets = [3.0, 10.0, 30.0]
        seen = {}
        for b in budgets:
            vals, wall_val = _wall_at(b)
            self.assertEqual(wall_val, b, "the knob itself must move, or this "
                                          "test is measuring nothing")
            for k, v in vals.items():
                seen.setdefault(k, []).append((b, v))
        for k, pairs in sorted(seen.items()):
            vals = set(v for _, v in pairs)
            self.assertEqual(
                len(vals), 1,
                "%s moved when %s moved: %s -- a reader-facing wait was derived "
                "from an ops knob, which is how 1.2s silently became 6.25s"
                % (k, OPS_KNOB, pairs))

    def test_the_deadline_clamp_is_still_in_force(self):
        """The ban above must not be read as 'waits ignore the deadline'."""
        import wall
        importlib.reload(wall)
        self.assertLessEqual(wall.radar_wait(left=3.0), 3.0 - wall.RESERVE + 1e-9)
        self.assertEqual(wall.radar_wait(left=0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
