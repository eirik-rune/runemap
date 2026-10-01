"""A directory probe must not report a delisting it did not measure.

2026-10-01 05:24 the watcher printed

    mcpservers.org   ABSENT   both 404 (TimeoutError) -- control agrees

and rang. Measured afterwards: we were still listed; that run had simply timed
out. The negative control "agreed" because fetch() returns the same None for a
real 404, for a 403 and for a timeout -- so the one thing the control cannot
rule out is the ruler being blind, which is exactly what had happened.

The SITES path already guards this (smithery prints BLIND because a word that
must be there also returns zero). These tests hold that guard on the DIRECT
path too, and they fire every branch -- including the one that must still say
ABSENT, because a guard's real cost is in what it wrongly refuses.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
MINE = "https://example-directory.test/servers/eirik-rune/runemap"
CTRL = MINE + "-control-does-not-exist"
ROOT = "https://example-directory.test/"


def verdict_for(pages, default=(None, "TimeoutError")):
    """Run the DIRECT loop against a stubbed web and return its verdict word."""
    with tempfile.TemporaryDirectory() as d:
        os.environ["RUNEMAP_LISTED_STATE"] = os.path.join(d, "state.json")
        spec = importlib.util.spec_from_file_location(
            "lw_under_test", HERE / "ops" / "listed_where.py")
        lw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lw)
        lw.fetch = lambda url: pages.get(url, default)
        lw.DIRECT = [("probe", MINE, CTRL)]
        lw.SITES = []
        lw.SCORE_URL = None
        buf = io.StringIO()
        # main() calls parse_args() with no argument list, so it reads sys.argv
        # -- which under `python -m unittest -v` holds the runner's own flags and
        # makes argparse SystemExit(2) before printing a thing. The first version
        # of this test swallowed that in `except SystemExit` and reported "the
        # probe printed nothing", i.e. it was measuring the test runner.
        argv = sys.argv
        sys.argv = ["listed_where.py"]
        try:
            with contextlib.redirect_stdout(buf):
                lw.main()
        except SystemExit:
            pass
        finally:
            sys.argv = argv
        for line in buf.getvalue().splitlines():
            if line.startswith("probe"):
                return line.split()[1]
        raise AssertionError("the probe printed nothing:\n" + buf.getvalue())


class DirectProbeDistinguishesBlindFromAbsent(unittest.TestCase):
    def test_front_page_unreachable_is_blind_not_absent(self):
        """Today's actual shape: nothing on that host answers."""
        self.assertEqual(verdict_for({}), "BLIND")

    def test_real_404_with_reachable_front_page_is_absent(self):
        """The guard must still be able to say we are not listed."""
        self.assertEqual(
            verdict_for({ROOT: ("<html>front page</html>", None)},
                        default=(None, "HTTP 404")),
            "ABSENT")

    def test_our_page_blocked_is_not_absence(self):
        """403 on our page is a refusal, not evidence that we are gone."""
        self.assertEqual(
            verdict_for({ROOT: ("<html>front page</html>", None),
                         MINE: (None, "HTTP 403")}),
            "NO-SIGNAL")

    def test_our_page_exists_and_control_404s_is_listed(self):
        self.assertEqual(
            verdict_for({ROOT: ("<html>front page</html>", None),
                         MINE: ("<html>runemap</html>", None)},
                        default=(None, "HTTP 404")),
            "LISTED")

    def test_positive_control_is_derived_not_listed_separately(self):
        """A second hand-kept table of "pages that should be up" would drift."""
        spec = importlib.util.spec_from_file_location(
            "lw_pc", HERE / "ops" / "listed_where.py")
        lw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lw)
        self.assertEqual(lw.positive_control(MINE), ROOT)
        self.assertEqual(
            lw.positive_control("https://h.test/a/b?q=1#f"), "https://h.test/")


if __name__ == "__main__":
    unittest.main()
