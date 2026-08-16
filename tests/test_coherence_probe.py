"""The probe that decides whether our two halves contradict each other.

It had no test. That matters more than usual for this one, because it is
wrapped in `except Exception: pass` -- correct, since instrumentation must not
break serving, but it means a broken probe writes **no rows**, and no rows is
what "the product never contradicts itself" also looks like. An instrument
whose failure mode is indistinguishable from good news is the shape this
repository keeps finding in other people's code.

What is pinned here is only what the probe itself owes: that it samples when
there is something to sample, stays silent when there is not, measures with the
right geometry, and records the fields a later judging pass needs. Whether the
product actually disagrees with itself is not decided here and must not be --
that judgement belongs out of band, on enough samples to mean something.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import render_scene as rs  # noqa: E402

#: Copied from the module, not typed. The first draft of this file used "#"
#: as an echo glyph, which is not on the ramp, so every distance came back
#: None and two tests errored -- a test that names the subject's alphabet
#: from memory is testing my memory.
ECHO = rs.RAMP[1]


def rt_with_rain_at(km, intensity=0.66):
    return {"precipitation": {"nearest": {"distance": km, "intensity": intensity}}}


class CoherenceProbe(unittest.TestCase):
    def setUp(self):
        self.log = tempfile.mktemp(suffix=".jsonl")
        self._real = rs._COHERENCE_LOG
        rs._COHERENCE_LOG = self.log
        self.addCleanup(setattr, rs, "_COHERENCE_LOG", self._real)
        self.addCleanup(lambda: os.path.exists(self.log) and os.unlink(self.log))

    def rows(self):
        if not os.path.exists(self.log):
            return []
        return [json.loads(x) for x in open(self.log, encoding="utf-8") if x.strip()]

    def sample(self, rt, art, kmcol=5.8, marker="><", **kw):
        rs._coherence_sample("testville", rt, art, kmcol, marker, **kw)

    # -- when it must NOT write ------------------------------------------

    def test_no_sample_when_upstream_sees_no_rain(self):
        # 10000.0 is upstream's no-rain sentinel, not a distance. Recording it
        # would put a 10000 km "disagreement" into the data set every clear day.
        self.sample(rt_with_rain_at(rs._NO_RAIN_KM), "..\n.><.\n..")
        self.sample({"precipitation": {"nearest": {}}}, "..\n.><.\n..")
        self.assertEqual(self.rows(), [])

    def test_no_sample_when_the_marker_was_not_drawn(self):
        # Without the marker there is no origin to measure from, so a distance
        # would be measured from wherever index() happened to fail.
        self.sample(rt_with_rain_at(5.0), "....\n....\n....")
        self.assertEqual(self.rows(), [])

    def test_it_never_raises_however_broken_the_input(self):
        for bad in (None, {}, {"precipitation": None},
                    {"precipitation": {"nearest": {"distance": "not a number"}}}):
            self.sample(bad, "..\n.><.\n..")   # must not raise
        self.sample(rt_with_rain_at(5.0), None)

    # -- the geometry, which was wrong once ------------------------------

    def test_a_row_step_is_twice_a_column_step(self):
        """The first version multiplied both axes by km_per_col.

        A terminal cell is about twice as tall as it is wide, so that halved
        every vertical distance -- and would have reported the map and the
        prose as disagreeing when the disagreement was the probe's own.
        """
        kmcol = 5.0
        # An echo one row above the marker, nothing else on the grid.
        art = "\n".join([" %s " % ECHO,
                         " ><",
                         "   "])
        self.sample(rt_with_rain_at(3.0), art, kmcol=kmcol)
        r = self.rows()[-1]
        self.assertAlmostEqual(r["map_km"], kmcol * 2.0, places=1,
                               msg="a vertical cell must count as 2 km_per_col")
        self.assertEqual(r["km_per_row"], kmcol * 2.0)
        self.assertEqual(r["km_per_char"], kmcol)

    def test_rain_overhead_measures_one_cell_not_zero(self):
        """The floor of this measurement is one cell, and it is agreement.

        When rain is directly overhead the marker occupies that cell and
        overwrites the echo glyph, so the nearest ramp character is a
        neighbour. The map has no character left with which to say "0 km". A
        judging pass that scores this as a disagreement is reading the marker
        rather than the weather, and 73 of the first 161 samples were exactly
        this case.
        """
        kmcol = 5.0
        art = "\n".join([ECHO*3,
                         ECHO + "><",
                         ECHO*3])
        self.sample(rt_with_rain_at(0.0), art, kmcol=kmcol)
        r = self.rows()[-1]
        self.assertAlmostEqual(r["map_km"], kmcol, places=1)
        self.assertEqual(r["upstream_km"], 0.0)

    # -- the fields a later judging pass needs ---------------------------

    def test_it_records_what_would_explain_a_disagreement(self):
        """One-sidedness is a mechanism, and these fields choose between two.

        The first 260 pairs put our map farther out than the prose 26 times and
        nearer 3 times. Either the frame is extrapolated or minutes old and the
        echo has moved (honest), or our dBZ floor drops light echo that
        upstream counts (a reader-facing error). Without the frame's age and
        extrapolation flag on the record, that stays an argument.
        """
        art = "\n".join([" %s " % ECHO, " ><", "   "])
        self.sample(rt_with_rain_at(3.0), art,
                    obs_age=25, age_tok="stale", extrapolated=True)
        r = self.rows()[-1]
        self.assertEqual((r["obs_age"], r["age_tok"], r["extrapolated"]),
                         (25, "stale", True))
        for field in ("at", "place", "upstream_km", "map_km",
                      "km_per_char", "km_per_row", "intensity"):
            self.assertIn(field, r)

    def test_a_record_says_which_scale_produced_it(self):
        # Rows written before the geometry fix lack km_per_row, and blending
        # the two metrics would average a corrected measurement with a halved
        # one. The record carries its own scale so a reader need not know when
        # the fix landed.
        self.sample(rt_with_rain_at(3.0), " %s \n ><\n   " % ECHO)
        self.assertIn("km_per_row", self.rows()[-1])


if __name__ == "__main__":
    unittest.main()
