"""#19: the gate reads the LAST segment, the place-name matcher reads the WHOLE spec.

serve.py:200 is the only consumer of _is_file_probe and it hands over the entire
joined spec, so a probe for `.git/config` has tail `config` -- no dot, not a
probe -- and gets fuzzy-matched to a place. bob reproduced it from outside the
host and saw a weather map; Luoshu saw Geita/TZ, I saw Congo. Same bug, the
match drifts with the query string, which is exactly why the assertion below
must be about the ROUTING DECISION and not about which place came back.

Scope, deliberately narrow: a segment that is a known static-file extension, or
a segment that begins with a dot -- place names never begin with a dot. Probes
like `actuator/env` carry no dot and no extension; this test does NOT claim to
catch them, because a claim wider than its evidence is the thing I keep being
caught doing.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")
import serve as S

# Real strings from access.log-shaped traffic, not invented ones.
PROBES = [
    ".git/config", ".git/HEAD", ".env", ".well-known/security.txt",
    "robots.txt", "favicon.ico", "wp-admin/setup-config.php",
    "vendor/phpunit/phpunit.php", "backup.sql", ".aws/credentials",
    ".vscode/sftp.json", "static/js/app.js",
]
PLACES = [
    "london", "st.petersburg", "new.york", "chiang mai", "xi an",
    "united states/new york", "config", "sao paulo",
]


class FileProbeReadsEverySegment(unittest.TestCase):
    def test_probes_are_refused(self):
        missed = [p for p in PROBES if not S._is_file_probe(p)]
        self.assertEqual(missed, [], "these reach the place matcher: %r" % missed)

    def test_place_names_still_pass(self):
        wrong = [p for p in PLACES if S._is_file_probe(p)]
        self.assertEqual(wrong, [], "these would 404 for real users: %r" % wrong)

    def test_a_dot_alone_is_not_evidence(self):
        # The original lesson this guard was born from: st.petersburg has a dot.
        self.assertFalse(S._is_file_probe("st.petersburg"))
        self.assertTrue(S._is_file_probe("st.petersburg/wp-login.php"))

    def test_leading_dot_segment_needs_no_extension_table(self):
        # .git/config has no known extension anywhere -- only the leading dot
        # can catch it, which is why the extension table alone is not enough.
        self.assertTrue(all(seg.rsplit(".", 1)[-1] not in S._PROBE_EXT
                            for seg in "x/config".split("/")))
        self.assertTrue(S._is_file_probe(".git/config"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
