"""The ghost cell: the mark for the sky that reaches the reader in ~60 min.

Two harnesses have to get a real verdict out of this file, and an earlier
version served neither well:

  - it pinned an absolute path into one machine's tree, so run from a throwaway
    clone it silently imported a different copy than the one under review -- and
    that path happened to be readable, so it did not even fail;
  - it only printed its verdict, so every quadrant could be reversed and the
    process still exited 0;
  - the sys.exit() that fixed the second point broke `unittest discover`, which
    turns a module-level SystemExit into ImportError -- compressing pass and
    fail into the same line of output.

So: relative import, real TestCase assertions (discover gets a true verdict),
and unittest.main() at the bottom (direct execution still exits non-zero).
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))   # last insert wins

from render_scene import _ghost, GHOST, GHOST_MIN        # noqa: E402

COLS, ROWS = 48, 24


def blank(fill=" "):
    g = [[fill] * COLS for _ in range(ROWS)]
    g[ROWS // 2][COLS // 2] = ">"
    g[ROWS // 2][COLS // 2 + 1] = "<"
    return "\n".join("".join(r) for r in g)


def where(art):
    for j, r in enumerate(art.split("\n")):
        i = r.find(GHOST)
        if i >= 0:
            return (j - ROWS // 2, i - COLS // 2)
    return None


def mv(bearing_deg, kmh):
    """Math-convention bearing: 0 = east, 90 = north. vy is south-positive,
    anchored on echo_motion's pre-existing atan2(-vy, vx)."""
    return {"kind": "moving", "kmh": kmh,
            "vx": kmh * math.cos(math.radians(bearing_deg)),
            "vy": -kmh * math.sin(math.radians(bearing_deg))}


def cells(mo, kmcol):
    """True displacement in cells, before any rounding."""
    t = GHOST_MIN / 60.0
    return math.hypot(-mo["vx"] * t / kmcol, -mo["vy"] * t / (2.0 * kmcol))


class Direction(unittest.TestCase):
    """The mark goes where the arriving sky is, i.e. UPWIND of the reader."""

    def test_quadrants(self):
        for bearing, name, check in (
                (45, "northeast", lambda d: d[0] > 0 and d[1] < 0),
                (0, "east", lambda d: d[0] == 0 and d[1] < 0),
                (90, "north", lambda d: d[0] > 0 and d[1] == 0),
                (225, "southwest", lambda d: d[0] < 0 and d[1] > 0)):
            art, drawn = _ghost(blank(), mv(bearing, 35), 5.0, "><")
            self.assertTrue(drawn, "echo heading %s drew nothing" % name)
            d = where(art)
            self.assertTrue(check(d),
                            "echo heading %s put the arriving sky at %r" % (name, d))

    def test_row_scale_is_half_the_column_scale(self):
        """km per ROW is twice km per COLUMN (see ascii_radar_centered).

        Dropping that factor does not move a single mark into the wrong
        quadrant, so test_quadrants cannot catch it -- it only doubles every
        north-south displacement. Hence a ratio, not a direction.
        """
        n, _ = _ghost(blank(), mv(90, 35), 5.0, "><")
        e, _ = _ghost(blank(), mv(0, 35), 5.0, "><")
        ratio = abs(where(n)[0]) / abs(where(e)[1])
        self.assertTrue(0.42 < ratio < 0.60,
                        "north:east displacement ratio %.2f, expected ~0.5" % ratio)


class Refusals(unittest.TestCase):
    """Each of these is a way the mark could have lied."""

    def test_under_one_cell_is_never_rounded_up(self):
        """The refusal must be tested BEFORE rounding.

        Testing the rounded result instead lets every component in [0.5, 1.0)
        through, inventing a full cell of motion that did not happen. Found in
        review by Eirik, who swept this space and got 169 false marks in 1680.
        """
        drawn_but_short = []
        for kmcol in (5.0, 12.0):
            for bearing in range(0, 360, 15):
                for kmh in range(5, 41):
                    mo = mv(bearing, kmh)
                    _, drawn = _ghost(blank(), mo, kmcol, "><")
                    if drawn and cells(mo, kmcol) < 1.0:
                        drawn_but_short.append(
                            (kmcol, bearing, kmh, round(cells(mo, kmcol), 2)))
        self.assertEqual(drawn_but_short, [],
                         "%d marks drawn for a displacement under one cell"
                         % len(drawn_but_short))

    def test_known_sub_cell_cases(self):
        """Eirik's four worst cases. Two of them are diagonals, where both
        components are under half a cell and the magnitude still is not."""
        for kmcol, bearing, kmh in ((12.0, 330, 7), (12.0, 63, 15),
                                    (12.0, 45, 12), (5.0, 63, 6)):
            _, drawn = _ghost(blank(), mv(bearing, kmh), kmcol, "><")
            self.assertFalse(drawn, "%.0fkm/char %ddeg %dkm/h is %.2f cells"
                             % (kmcol, bearing, kmh, cells(mv(bearing, kmh), kmcol)))

    def test_off_grid_is_not_clamped(self):
        """Clamping to the edge quietly restates the claim as 'arrives from
        the edge', which is a different and false one."""
        _, drawn = _ghost(blank(), mv(45, 900), 5.0, "><")
        self.assertFalse(drawn)

    def test_no_mark_where_nobody_looked(self):
        """'?' means no radar behind the cell. A confident + on top of it
        claims knowledge we do not have."""
        _, drawn = _ghost(blank("?"), mv(45, 35), 5.0, "><")
        self.assertFalse(drawn)

    def test_undetermined_motion_draws_nothing(self):
        """And no placeholder either: '-' is a value-shaped hole."""
        _, drawn = _ghost(blank(), {"kind": "undetermined"}, 5.0, "><")
        self.assertFalse(drawn)


if __name__ == "__main__":
    unittest.main()
