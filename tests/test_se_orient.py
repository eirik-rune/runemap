"""Every verdict the Swedish orientation check prints, fired on data built to
earn it.

Hermetic: `se_orient` is the judgement, not the download, so none of this
touches the network. The masks are synthetic on purpose -- a fixture cut from
the real 471x887 frame would be unreadable, and the property under test is
geometric, not Swedish.

Two failures met on this exact question tonight are pinned here: a control
whose branches differ by a percent (Switzerland's mask) must say INSUFFICIENT
rather than pick a winner, and a verdict of OK must not quietly claim more than
the instrument can see -- the 180 degree rotation stays in the note.
"""
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "ops"), os.path.join(_ROOT, "scripts"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import se_orient as O          # noqa: E402

# Real scale, so the module's real thresholds apply: 10 km cells over a
# 1000x2000 km box, radars ranging 250 km -- Sweden's shape and physics.
CELL_KM = 10.0
W, H = 100, 200


def mask(sites, radius_cells=25):
    """Seen = within `radius_cells` of a site. That is what a composite is."""
    grid = [[False] * W for _ in range(H)]
    for cx, cy in sites:
        for y in range(H):
            for x in range(W):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius_cells ** 2:
                    grid[y][x] = True
    return grid


# Upper half and left of centre, so a vertical AND a horizontal flip both
# move the coverage off the radars. Sweden is asymmetric in both axes too.
TOP = [(20, 30), (45, 40), (18, 60), (50, 70), (32, 25), (28, 80), (40, 55)]


class TheRealMeasurement(unittest.TestCase):
    """Numbers from the frame of 2026-08-13 23:0x, 10 OSCAR-resolved sites.

    Kept as an assertion about the *judgement*, not a re-measurement: these are
    the p10 blind-cell distances that were actually observed, so if judge()
    ever stops calling that pattern OK, this says so.
    """

    OBSERVED = {"as-read": 253.7, "vertical-flip": 88.3,
                "horizontal-flip": 111.1, "180-rotation": 209.0}

    def test_the_observed_scores_are_judged_ok_with_the_rotation_flagged(self):
        got = dict(self.OBSERVED)
        margin = min(got["as-read"] - got[k]
                     for k in ("vertical-flip", "horizontal-flip"))
        self.assertGreaterEqual(margin, O.MIN_MARGIN_KM,
                                "the real margin no longer clears the "
                                "threshold this module ships with")
        self.assertLess(got["as-read"] - got["180-rotation"], O.MIN_MARGIN_KM,
                        "180 rotation would now be excluded -- the docstring "
                        "and the doc both say it is not, so one is wrong")


class EveryVerdictCanFire(unittest.TestCase):

    def test_ok(self):
        v, note = O.judge(mask(TOP), TOP, CELL_KM)
        self.assertEqual(v, "OK", note)

    def test_the_ok_note_does_not_claim_the_rotation_is_excluded(self):
        """A verdict must not be read as more than it measured."""
        _v, note = O.judge(mask(TOP), TOP, CELL_KM)
        self.assertIn("180-rotation NOT excluded", note)

    def test_flipped(self):
        """A mask read upside down: the failure in the form it would take."""
        m = mask(TOP)
        v, note = O.judge(m[::-1], TOP, CELL_KM)
        self.assertEqual(v, "FLIPPED", note)

    def test_insufficient_when_too_few_sites_resolved(self):
        v, note = O.judge(mask(TOP), TOP[:3], CELL_KM)
        self.assertEqual(v, "INSUFFICIENT")
        self.assertIn("radar sites", note)

    def test_insufficient_when_the_mask_has_no_blind_margin(self):
        """Switzerland in miniature: a composite that sees everywhere cannot
        be oriented by where it is blind."""
        v, note = O.judge([[True] * W for _ in range(H)], TOP, CELL_KM)
        self.assertEqual(v, "INSUFFICIENT")
        self.assertIn("blind", note)

    def test_insufficient_when_the_margin_is_too_thin(self):
        """Sites spread symmetrically: flipping maps the mask nearly onto
        itself, which is exactly why the Swiss mask was discarded."""
        sym = [(50, 30), (50, 170), (25, 100), (75, 100), (50, 100),
               (30, 60), (70, 140)]
        v, note = O.judge(mask(sym), sym, CELL_KM)
        self.assertEqual(v, "INSUFFICIENT", note)
        self.assertIn("margin", note)


class TheStatisticsThemselves(unittest.TestCase):

    def test_blind_distance_returns_none_rather_than_a_number_when_blind_is_empty(self):
        """'Nothing to measure' and 'measured, and it is zero' must not print
        the same thing."""
        full = [[True] * W for _ in range(H)]
        self.assertIsNone(
            O.blind_distance(full, TOP, CELL_KM, lambda y, x: full[y][x]))

    def test_every_cell_near_a_radar_is_seen_when_the_mask_is_read_correctly(self):
        m = mask(TOP)
        share = O.seen_near_radars(m, TOP, CELL_KM, lambda y, x: m[y][x])
        self.assertEqual(share, 1.0)

    def test_the_flipped_read_loses_coverage_near_the_radars(self):
        m = mask(TOP)
        h = len(m)
        share = O.seen_near_radars(m, TOP, CELL_KM,
                                   lambda y, x: m[h - 1 - y][x])
        self.assertLess(share, 0.9)

    def test_sites_off_the_grid_are_skipped_not_invented(self):
        out = O.sites_to_cells([(1.0, 1.0), (2.0, 2.0)],
                               lambda lat, lng: (10, 10) if lat < 1.5 else None)
        self.assertEqual(out, [(10, 10)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
