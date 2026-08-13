"""The Brazilian adapter: geometry from their numbers, freshness from their cycle.

Hermetic -- it reads a temp directory, never Brazil. The one thing worth pinning
hardest is the age ceiling, because getting it wrong is silent in both
directions: too tight and the reader gets a sentence while a perfectly good
frame sits on disk, too loose and we draw yesterday's rain and call it now.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import radar_redemet as R      # noqa: E402

SP = (-46.63, -23.55)


def _rec(name, ts, bbox, png="x.png"):
    return {"name": name, "png": png, "raio": 400, "bbox": list(bbox),
            "data": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))}


class TheIndexIsTheirNumbers(unittest.TestCase):

    def test_a_time_string_round_trips_through_utc(self):
        now = int(time.time())
        self.assertAlmostEqual(R._ts(_rec("sr", now, (0, 0, 1, 1))), now, delta=1)

    def test_a_broken_time_is_none_not_a_guess(self):
        self.assertIsNone(R._ts({"data": "yesterday"}))

    def test_the_nearest_centre_wins_when_discs_overlap(self):
        idx = {"radars": [_rec("far", 0, (-30.0, -50.0, -10.0, -30.0)),
                          _rec("near", 0, (-24.5, -47.5, -22.5, -45.5))]}
        self.assertEqual(R.pick(SP[0], SP[1], idx)["name"], "near")

    def test_a_sky_no_disc_covers_is_none(self):
        """Declining is the whole point: this returns None so the chain moves
        on, and it must never mean 'no radar exists in Brazil'."""
        idx = {"radars": [_rec("sr", 0, (-24.5, -47.5, -22.5, -45.5))]}
        self.assertIsNone(R.pick(2.35, 48.85, idx))   # paris

    def test_a_missing_mirror_is_none_not_a_crash(self):
        was, R.DIR = R.DIR, tempfile.mkdtemp(prefix="redemet-empty-")
        try:
            self.assertIsNone(R._index())
            self.assertIsNone(R.draw("><", SP[0], SP[1]))
        finally:
            shutil.rmtree(R.DIR, ignore_errors=True)
            R.DIR = was


class TheCeilingCoversOneWholeCycle(unittest.TestCase):
    """Measured 8/13: REDEMET's own latency is 13-23 min, and the mirror runs
    every 10. So the ordinary worst case a reader meets is about 33 min old and
    is not a fault; two dead periods is."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="redemet-test-")
        self._was = R.DIR
        R.DIR = self.dir

    def tearDown(self):
        R.DIR = self._was
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, age_s, with_png=True):
        rec = _rec("sr", time.time() - age_s, (-24.5, -47.5, -22.5, -45.5))
        with open(os.path.join(self.dir, "index.json"), "w") as fh:
            json.dump({"at": time.time(), "radars": [rec]}, fh)
        if with_png:
            from PIL import Image
            Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(
                os.path.join(self.dir, rec["png"]))
        return rec

    def _draw(self):
        return R.draw("><", SP[0], SP[1])

    def test_the_ordinary_worst_case_of_the_cycle_still_draws(self):
        """The positive control. Without it, a ceiling of zero would pass every
        other test in this class -- refusing everything looks exactly like
        refusing correctly."""
        self._write(33 * 60)
        got = self._draw()
        self.assertIsNotNone(got, "a 33-minute frame is an ordinary one here")
        self.assertEqual(got[5], "REDEMET/DECEA")

    def test_a_frame_past_the_ceiling_is_refused(self):
        self._write(50 * 60)
        self.assertIsNone(self._draw())

    def test_two_dead_mirror_periods_are_refused(self):
        self._write(60 * 60)
        self.assertIsNone(self._draw())

    def test_a_missing_png_is_refused_separately_from_age(self):
        """Both refusals return None; only the reasons differ, and they go to
        stderr under distinct names so a quiet map can be told apart from a
        stale one."""
        self._write(5 * 60, with_png=False)
        self.assertIsNone(self._draw())


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheMirrorRecordsTheAgeDistributionNotJustACount(unittest.TestCase):
    """The 45-minute ceiling in radar_redemet.py was derived from ONE pull
    (13.4 / 19.6 / 23.2 min, min/median/max) and set to clear it. Six hours
    later a single pull read 13.3 / 23.9 / 52.7 -- the median barely moved and
    the maximum more than doubled. A constant set from a sample that cannot
    show its own tail is a constant that will be wrong later, quietly, in the
    direction of refusing a working radar."""

    def setUp(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
        import redemet_pull
        self.R = redemet_pull

    def _idx(self, minutes):
        import time
        now = time.time()
        return {"radars": [
            {"data": time.strftime("%Y-%m-%d %H:%M:%S",
                                   time.gmtime(now - m * 60))} for m in minutes]}

    def test_it_reports_the_tail_not_only_the_middle(self):
        got = self.R._age_quantiles(self._idx([10, 20, 20, 20, 60]))
        self.assertEqual(got.split("/")[0], "10")
        self.assertEqual(got.split("/")[-1], "60")

    def test_an_index_with_no_times_says_so_rather_than_reporting_zero(self):
        """'no ages' and 'every radar is current' must not print the same
        thing; only one of them is good news."""
        self.assertEqual(self.R._age_quantiles({"radars": []}), "unparseable")
        self.assertEqual(self.R._age_quantiles({"radars": [{"data": "soon"}]}),
                         "unparseable")

    def test_one_bad_row_does_not_discard_the_others(self):
        idx = self._idx([10, 30])
        idx["radars"].append({"data": "soon"})
        self.assertEqual(self.R._age_quantiles(idx).split("/")[0], "10")
