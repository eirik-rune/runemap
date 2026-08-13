"""One reflectivity scale, shared by every source that hands us values.

This file exists because the change that created it was invisible to 369
passing tests: adding a 7 dBZ floor moved roughly 82% of the echo pixels in a
real Dutch frame from "light rain" to "nothing", and not one test noticed,
because no test had ever passed a sub-floor value to a classifier. A branch
with no coverage is exactly the branch that needs reading.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import dbz                     # noqa: E402
import radar_chmi as C         # noqa: E402
import radar_knmi as K         # noqa: E402
import radar_smhi as S         # noqa: E402


class TheFloorIsDwdsNotOurs(unittest.TestCase):
    """DWD's published style declares its first entry transparent below 7 dBZ,
    so a German sky at 3 dBZ draws nothing. Before this floor existed a Dutch
    or Czech sky at 3 dBZ drew light rain, because the value sources treated
    everything above "no echo" as rain -- the same character meaning two
    different things depending on which country the reader stood in."""

    def test_the_floor_is_seven(self):
        self.assertEqual(dbz.FLOOR_DBZ, 7.0)

    def test_below_the_floor_is_nothing_not_light_rain(self):
        for q in (-31.5, -10.0, 0.0, 6.9):
            self.assertEqual(dbz.level_for(q), 0, q)

    def test_at_and_above_the_floor_is_light_rain(self):
        for q in (7.0, 12.0, 18.9):
            self.assertEqual(dbz.level_for(q), 1, q)

    def test_the_bands_above_it_are_unchanged(self):
        self.assertEqual(dbz.level_for(19.0), 2)
        self.assertEqual(dbz.level_for(28.0), 3)
        self.assertEqual(dbz.level_for(37.0), 4)
        self.assertEqual(dbz.level_for(46.0), 5)
        self.assertEqual(dbz.level_for(77.5), 5)


class EverySourceReadsTheSameTable(unittest.TestCase):
    """Four copies that agree are a coincidence, not a construction. They
    agreed until one was edited, and then each map stayed self-consistent while
    disagreeing with the others -- which no reader can see."""

    KNMI = {"gain": 0.5, "offset": -32.0, "missing": 0.0, "outside": 255.0}
    CHMI = {"gain": 0.5, "offset": -32.0, "undetect": 0.0, "nodata": 255.0}

    def test_smhi_exposes_the_shared_bands(self):
        self.assertIs(S.DBZ_LEVELS, dbz.LEVELS)

    def test_the_same_dbz_draws_the_same_level_in_every_country(self):
        # dn 100 is 18 dBZ under the Czech/Dutch calibration and 10 dBZ under
        # Sweden's -- different dBZ, but each must be classified by one table.
        for q, want in ((3.0, 0), (10.0, 1), (30.0, 3), (50.0, 5)):
            self.assertEqual(dbz.level_for(q), want)

    def test_a_sub_floor_pixel_is_zero_in_all_three_adapters(self):
        # pv 60 -> 0.5*60-32 = -2 dBZ, which is not weather.
        self.assertEqual(K.level_of(60, self.KNMI), 0)
        self.assertEqual(C.level_of(60, self.CHMI), 0)
        self.assertEqual(S.level_of(60), 0)          # 0.4*60-30 = -6 dBZ

    def test_zero_from_the_floor_is_still_distinct_from_not_looking(self):
        """The whole point of the -1 sentinel survives the change: "looked and
        saw nothing" and "did not look here" must not collapse together, or a
        blind window renders as fair weather."""
        self.assertEqual(K.level_of(255, self.KNMI), -1)
        self.assertEqual(C.level_of(255, self.CHMI), -1)
        self.assertEqual(S.level_of(255), -1)
        self.assertNotEqual(K.level_of(60, self.KNMI), K.level_of(255, self.KNMI))

    def test_a_real_echo_still_draws(self):
        """Fire the other way too: a floor that swallowed everything would also
        pass every test above."""
        self.assertEqual(K.level_of(160, self.KNMI), 5)     # 48 dBZ
        self.assertEqual(C.level_of(128, self.CHMI), 3)     # 32 dBZ
        self.assertEqual(S.level_of(160), 3)                # 34 dBZ
        self.assertEqual(S.level_of(185), 4)                # 44 dBZ


if __name__ == "__main__":
    unittest.main(verbosity=2)
