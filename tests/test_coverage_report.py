"""The fleet must be able to say what it serves, and to say when it cannot.

This exists because I answered "is the US wired?" from memory, counted
`radar_*.py` filenames, and was wrong -- four countries share `radar_wms.py`.
Every verdict the report can print is fired here on purpose, because a
judgement that only ever prints one word has no jurisdiction.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "ops"), os.path.join(_ROOT, "scripts"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import coverage_report as C          # noqa: E402


def run(chain):
    """-> (rc, text). The chain is passed through the environment, the way
    production passes it, rather than through a private argument."""
    old = os.environ.get("RUNEMAP_SECOND_SOURCE")
    os.environ["RUNEMAP_SECOND_SOURCE"] = chain
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = C.main()
    finally:
        if old is None:
            os.environ.pop("RUNEMAP_SECOND_SOURCE", None)
        else:
            os.environ["RUNEMAP_SECOND_SOURCE"] = old
    return rc, buf.getvalue()


class TheMappingIsProductionsMapping(unittest.TestCase):

    def test_the_report_does_not_keep_its_own_copy_of_the_names(self):
        """Four places agreeing by coincidence is not a guard. If this ever
        needs its own dict, this test should be the thing that objects."""
        import render_scene as R
        with open(os.path.join(_ROOT, "ops", "coverage_report.py")) as fh:
            src = fh.read()
        self.assertIn("R.SECOND_MODULES", src)
        self.assertTrue(len(R.SECOND_MODULES) >= 8)

    def test_every_named_module_can_actually_be_imported(self):
        """A name in the table that does not resolve would reach a reader as
        'this source declined', which is what a clear sky looks like."""
        import render_scene as R
        for name, modname in R.SECOND_MODULES.items():
            with self.subTest(source=name):
                __import__(modname)


class CountriesAreCountedNotModules(unittest.TestCase):

    def test_one_module_may_serve_several_countries(self):
        """The whole point: radar_wms is one file and four countries."""
        import radar_wms as W
        self.assertGreater(len(W.SERVES), 1)
        for cc in ("US", "CA", "FI", "DE"):
            self.assertIn(cc, W.SERVES)

    def test_the_wms_country_list_is_derived_from_the_service_table(self):
        """Retyped constants drift apart silently and each looks right alone."""
        import radar_wms as W
        self.assertEqual(W.SERVES,
                         tuple(sorted(x["serves"] for x in W.SERVICES)))

    def test_the_us_is_wired(self):
        """The specific false statement that caused this file."""
        rc, out = run("wms")
        self.assertEqual(rc, 0, out)
        self.assertIn("US", out)

    def test_serves_is_not_coverage(self):
        """COVERAGE says what a mosaic can SEE. Norway's box holds Stockholm,
        so reading it as 'who we serve' hands Sweden to Norway."""
        import radar_metno as M
        self.assertEqual(M.SERVES, ("NO",))
        self.assertTrue(M.COVERAGE[0] < 60.0 < M.COVERAGE[2])
        self.assertTrue(M.COVERAGE[1] < 18.07 < M.COVERAGE[3])   # Stockholm


class EveryVerdictCanFire(unittest.TestCase):

    def test_ok(self):
        rc, out = run("dmi,metno")
        self.assertEqual(rc, 0, out)
        self.assertIn("2 countries", out)

    def test_no_declaration_fails_the_run_rather_than_shrinking_the_count(self):
        """rainviewer is a global composite and declares no SERVES. Dropping it
        quietly would let the country list fall without anyone noticing."""
        rc, out = run("dmi,rainviewer")
        self.assertEqual(rc, 1, out)
        self.assertIn("NO-DECLARATION", out)
        self.assertIn("floor, not a total", out)

    def test_an_unknown_source_name_is_an_error_not_a_silent_skip(self):
        rc, out = run("dmi,bogus")
        self.assertEqual(rc, 1, out)
        self.assertIn("not a known source name", out)

    def test_no_config_is_its_own_verdict_and_its_own_exit_code(self):
        """'I could not ask' must not print or exit like 'there are none'."""
        real = C.chain_from_env
        try:
            C.chain_from_env = lambda: (None, "no unit here")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = C.main()
            self.assertEqual(rc, 2)
            self.assertIn("NO-CONFIG", buf.getvalue())
            self.assertIn("I could not ask", buf.getvalue())
        finally:
            C.chain_from_env = real

    def test_the_ok_path_and_the_no_config_path_do_not_share_an_exit_code(self):
        """The positive control for the test above: if every path returned 0,
        each assertion would still pass on its own."""
        ok, _ = run("dmi")
        self.assertNotEqual(ok, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
