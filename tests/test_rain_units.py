"""The rain intensity we print must be the one we asked for.

2026-08-14, found by bob on the first screen: we printed
`precip 0.33mm/h` while asking Caiyun for its DEFAULT units, under which
`precipitation.local.intensity` is a radar precipitation INDEX on a 0~1 scale,
not mm/h. 0.33 of full scale is substantial rain; "0.33 mm/h" reads as a trace.
**The error inverted the meaning** -- the reader forms a false belief and has no
way to detect it, which is the severe class.

mm/h only arrives with `unit=metric:v2`, so the label was not wrong, the request
was. This pins the request rather than the label, because the label is what a
future edit would "fix" first.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

SRC = os.path.join(os.path.dirname(__file__), "..", "scripts", "render_scene.py")


class TheRequestAsksForTheUnitsWePrint(unittest.TestCase):

    def setUp(self):
        with open(SRC, encoding="utf8") as fh:
            self.src = fh.read()

    def test_the_weather_call_asks_for_metric_v2(self):
        call = [l for l in self.src.splitlines()
                if "api.caiyunapp.com/v2.6" in l and "weather?" in l]
        self.assertTrue(call, "the weather request line moved or vanished")
        for l in call:
            self.assertIn("unit=metric:v2", l,
                          "without this the intensity is a 0~1 index, and every "
                          "line below labels it mm/h")

    def test_nothing_branches_on_the_intensity_value(self):
        """The switch is only safe because the value is displayed, never
        compared. If a threshold appears later it must be re-derived for mm/h,
        so make that impossible to add silently."""
        for m in re.finditer(r'^.*intensity.*$', self.src, re.M):
            line = m.group(0)
            if "precipitation" not in line and "intensity\"]" not in line:
                continue
            self.assertNotRegex(
                line, r'(?<![<>=!])[<>]=?\s*[0-9]|[<>]=?\s*[0-9]',
                "a comparison against the intensity appeared: %s" % line.strip())

    def test_the_label_says_mm_per_hour(self):
        """Kept so that request and label cannot drift apart in either
        direction -- the pair is the contract, not either half."""
        self.assertIn("mm/h", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
