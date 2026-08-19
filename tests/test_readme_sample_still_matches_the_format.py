"""The frozen README sample must still name fields the renderer still prints.

The sample in README.md is deliberately not live -- a pasted "live" reading
starts lying six minutes after it is pasted, so it is frozen on purpose. That
decision is sound and this test does not argue with it.

What freezing protects is the **weather**. It does not protect the **format**,
and nothing did: the sample sat unchanged from 2026-07-29 to 2026-08-19 while
the header line, the radar line and the legend all changed. A visitor following
the README would have run the advertised curl and compared their answer against
fields we had stopped printing -- old presented as current, which is worse than
absent-and-said-so.

Twenty-two people looked at this repository in the fortnight when that was true.
When arrivals are that scarce, the first screen is most of the product.

The check is deliberately weak and cheap: every field label in the sample must
still appear somewhere in the renderer's source. It cannot tell whether the
layout still looks the same, and it is a proxy rather than a measurement -- but
it is offline, it needs no weather, and it is exactly the drift that happened.
A field that gets renamed or deleted trips it.

**One direction only, and that is deliberate.** It catches "the README shows a
field we no longer print". It does NOT catch "the README omits a field we now
print" -- guarding that would need a list of fields that are always present, and
there is no such list: no rain means no curve, no radar means no map. Firing it
both ways is how that ceiling got measured rather than assumed.
"""
import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(_ROOT, "README.md")
RENDERER = os.path.join(_ROOT, "scripts", "render_scene.py")

#: Labels are pulled out of the sample rather than listed here, so a field added
#: to the sample later is covered without anyone remembering this file. These
#: are the shapes a label takes in the output.
#: Anywhere in the sample, not just at line start. The first version anchored
#: with ^ and so was blind to exactly the drift it was written for: the fields
#: that moved were INSIDE the radar line (`obs age:` -> something else), while
#: the line still began with `radar:`, which still exists. It passed on the real
#: regression until it was fired against it.
_LABEL = re.compile(r"(?P<k>[a-z][a-z ]{1,18}):")
_EXTRA = ("weather scene", "km/char", "echo motion", "blank=no echo")


def frozen_sample():
    r = open(README, encoding="utf-8").read()
    blocks = re.findall(r"```\n(.*?)```", r, re.S)
    for b in blocks:
        if "weather scene" in b:
            return b
    raise AssertionError("no frozen weather-scene sample found in README.md")


class TheSampleNamesFieldsWeStillPrint(unittest.TestCase):
    def setUp(self):
        self.sample = frozen_sample()
        self.src = open(RENDERER, encoding="utf-8").read()

    def test_the_sample_is_findable_at_all(self):
        """If the sample stops being findable this whole file goes quiet while
        passing, which is the failure mode it exists to prevent elsewhere."""
        self.assertIn("weather scene", self.sample)
        self.assertGreater(len(self.sample.splitlines()), 10)

    def test_every_label_in_the_sample_still_exists_in_the_renderer(self):
        labels = set()
        for m in _LABEL.finditer(self.sample):
            labels.add(m.group("k").strip() + ":")
        for token in _EXTRA:
            if token in self.sample:
                labels.add(token)
        self.assertTrue(labels, "found no labels to check -- the extractor is "
                                "broken, and would pass forever")
        missing = sorted(l for l in labels if l not in self.src)
        self.assertEqual(missing, [], "README's frozen sample prints %r, which "
                                      "the renderer no longer does. Re-freeze "
                                      "it from a live response." % (missing,))

    def test_the_check_can_fail(self):
        """Positive control. Without this, 'no missing labels' would be
        indistinguishable from 'the extractor found nothing to look for'."""
        self.assertNotIn("obs vintage:", self.src)

    def test_the_curl_command_is_above_the_sample(self):
        """Conversion, not tidiness: the first curl used to sit at line 54,
        below fifty lines of prose, on a product whose entire claim is that one
        request is enough."""
        r = open(README, encoding="utf-8").read()
        curl = r.find("curl echorune.net")
        fence = r.find("```")
        self.assertNotEqual(curl, -1, "README has no curl command at all")
        self.assertLess(curl, fence,
                        "the first curl command must come before the sample")


if __name__ == "__main__":
    unittest.main()
