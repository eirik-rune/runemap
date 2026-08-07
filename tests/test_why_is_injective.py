"""Every unavailable exit must carry its own why, and every why its own words.

The wording table is read as `_MO_UNDET.get(why) or _MO_UNDET["corr"]`. That
fallback is silent: add a new exit tomorrow and its reason collapses into
"frames not correlated" with nothing going red. 8/7's bug was this same shape
one layer down -- a fetch failure wearing the words for an empty sky -- so the
mapping is welded here instead of trusted.
"""
import io, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EM_SRC = io.open(os.path.join(ROOT, "scripts", "echo_motion.py"), encoding="utf-8").read()
RS_SRC = io.open(os.path.join(ROOT, "scripts", "render_scene.py"), encoding="utf-8").read()


def whys_produced():
    return set(re.findall(r'why["\']?\s*[:=]\s*["\'](\w+)["\']', EM_SRC)) | \
           set(re.findall(r'why\s*=\s*["\'](\w+)["\']', EM_SRC))


def table_keys():
    i = RS_SRC.find("_MO_UNDET = {")
    assert i != -1, "_MO_UNDET not found -- this test is measuring the wrong file"
    seg = RS_SRC[i:RS_SRC.find("\n}", i)]
    return set(re.findall(r'^\s{4}"(\w+)":', seg, re.M))


class WhyIsInjective(unittest.TestCase):
    def test_every_produced_why_has_wording(self):
        produced, keys = whys_produced(), table_keys()
        self.assertTrue(produced, "found no why values -- the regex, not the code, is what failed")
        missing = produced - keys
        self.assertEqual(missing, set(),
                         "these reasons would silently fall back to the corr wording: %s" % sorted(missing))

    def test_wordings_are_distinct(self):
        i = RS_SRC.find("_MO_UNDET = {")
        seg = RS_SRC[i:RS_SRC.find("\n}", i)]
        en = re.findall(r'"en":\s*"([^"]+)"', seg)
        self.assertEqual(len(en), len(set(en)),
                         "two reasons share one sentence, so the reader cannot tell them apart: %s" % en)
        self.assertGreaterEqual(len(en), 4)

    def test_fetch_wording_does_not_claim_an_empty_sky(self):
        i = RS_SRC.find('"fetch":')
        self.assertNotEqual(i, -1, "no fetch wording")
        seg = RS_SRC[i:i + 400]
        for forbidden in ("no echo", "nothing to track"):
            self.assertNotIn(forbidden, seg.lower(),
                             "the fetch wording makes a claim about the sky: %r" % forbidden)


if __name__ == "__main__":
    unittest.main()
