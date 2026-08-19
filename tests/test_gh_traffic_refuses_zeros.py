"""The traffic snapshot must refuse rather than report an absence it invented.

GitHub keeps repo traffic for 14 days and then deletes it, which is the whole
reason this snapshot exists. It is also why a broken run is dangerous here in a
way it would not be elsewhere: the true answer is *small* -- 22 unique visitors
in 14 days, measured 2026-08-19 -- so a row of zeros from a run that could not
authenticate looks exactly like a true reading. Small true numbers are where
fail-open hurts most, because there is no implausibility to catch it.

Same shape as who_is_using's NO-LOG, fixed the same morning: "I could not ask"
and "nobody came" must not print the same page.

No network. These exercise the refusal paths and the reader; the success path is
exercised by running it, which is what the cron does daily.
"""
import io
import json
import os
import sys
import contextlib
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))


def run(argv, **env):
    """Import fresh so module-level env reads take effect, and capture stdout."""
    old_env = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    sys.modules.pop("gh_traffic_snapshot", None)
    old_argv = sys.argv
    sys.argv = argv
    out = io.StringIO()
    try:
        import gh_traffic_snapshot as G
        with contextlib.redirect_stdout(out):
            rc = G.main()
    finally:
        sys.argv = old_argv
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sys.modules.pop("gh_traffic_snapshot", None)
    return rc, out.getvalue()


class ItRefusesRatherThanInventsAnAbsence(unittest.TestCase):
    def test_no_token_file_is_no_data_not_zeros(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = run(["gh_traffic_snapshot"],
                          GH_TOKEN_FILE=os.path.join(d, "absent"),
                          GH_TRAFFIC_OUT=os.path.join(d, "t.jsonl"))
        self.assertEqual(rc, 2, out)
        self.assertIn("NO-DATA", out)
        self.assertNotIn("0 unique", out)

    def test_an_empty_token_file_is_also_refused(self):
        """A present-but-empty credential is the case that slips through a
        `[ -r ]`-style check: readable, and useless."""
        with tempfile.TemporaryDirectory() as d:
            tok = os.path.join(d, "tok")
            open(tok, "w").close()
            rc, out = run(["gh_traffic_snapshot"], GH_TOKEN_FILE=tok,
                          GH_TRAFFIC_OUT=os.path.join(d, "t.jsonl"))
        self.assertEqual(rc, 2, out)
        self.assertIn("NO-DATA", out)

    def test_nothing_kept_yet_is_not_reported_as_no_visitors(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = run(["gh_traffic_snapshot", "--show"],
                          GH_TRAFFIC_OUT=os.path.join(d, "t.jsonl"))
        self.assertEqual(rc, 2, out)
        self.assertIn("NO-DATA", out)

    def test_kept_days_are_read_back(self):
        """The control for the test above: with data present it must succeed,
        or 'refuses when empty' would be indistinguishable from 'always
        refuses', which is a guard with one verdict and no jurisdiction."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"day": "2026-08-18", "views": 6,
                                    "views_uniques": 3, "clones": 516,
                                    "clones_uniques": 133}) + "\n")
            rc, out = run(["gh_traffic_snapshot", "--show"], GH_TRAFFIC_OUT=p)
        self.assertEqual(rc, 0, out)
        self.assertIn("2026-08-18", out)
        self.assertIn("1 day(s) kept", out)

    def test_a_corrupt_line_does_not_take_the_file_with_it(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{not json at all\n")
                f.write(json.dumps({"day": "2026-08-18", "views": 6}) + "\n")
            rc, out = run(["gh_traffic_snapshot", "--show"], GH_TRAFFIC_OUT=p)
        self.assertEqual(rc, 0, out)
        self.assertIn("2026-08-18", out)


if __name__ == "__main__":
    unittest.main()
