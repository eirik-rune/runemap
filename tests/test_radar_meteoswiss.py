"""Switzerland: the naming, the units, and the two kinds of nothing. Hermetic.

The frame name is pinned against a key observed on the live service, not
against what this module printed -- deriving an expectation from the code's own
output is how a bug gets filed as the correct answer.

Anything needing h5py builds its own file and skips when h5py is absent. CI
does not install it, and a test that is green only where the optional
dependency happens to exist is green for a reason it does not state.
"""
import math
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "scripts"), os.path.join(_ROOT, "ops"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import radar_meteoswiss as M          # noqa: E402


def have_h5py():
    try:
        import h5py          # noqa: F401
        return True
    except Exception:
        return False


class TheFrameNameIsTheirs(unittest.TestCase):

    def test_a_key_observed_on_the_live_service(self):
        """`rzc262252120vl.001.h5` was listed by their STAC item for
        2026-08-13. Year-of-century 26, day-of-year 225, 21:20 UTC."""
        import calendar
        ts = calendar.timegm((2026, 8, 13, 21, 20, 0, 0, 0, 0))
        self.assertEqual(M.frame_name(ts), "rzc262252120vl.001.h5")

    def test_the_day_of_year_is_not_the_day_of_month(self):
        """The two agree for the first twelve days of January and never again;
        a lazy format would pass any test written in early January."""
        import calendar
        ts = calendar.timegm((2026, 3, 1, 0, 0, 0, 0, 0, 0))
        self.assertIn("26060", M.frame_name(ts))     # 2026 is not a leap year

    def test_the_url_carries_the_calendar_date_directory(self):
        import calendar
        ts = calendar.timegm((2026, 8, 13, 21, 20, 0, 0, 0, 0))
        u = M.frame_url(ts)
        self.assertIn("/20260813-ch/", u)
        self.assertTrue(u.endswith("rzc262252120vl.001.h5"), u)

    def test_candidate_stamps_walk_backwards_on_the_five_minute_grid(self):
        st = M.stamps(now=1786742430.0)
        self.assertEqual(len(st), M.LOOKBACK)
        self.assertEqual(st[0] % 300, 0)
        self.assertTrue(all(a - b == 300 for a, b in zip(st, st[1:])))


class ServesIsNotCovers(unittest.TestCase):

    def test_it_declines_places_its_radars_cannot_reach(self):
        self.assertTrue(M.covers(8.55, 47.3667))     # Zurich
        self.assertTrue(M.covers(6.143, 46.204))     # Geneva
        self.assertFalse(M.covers(9.19, 45.46))      # Milan
        self.assertFalse(M.covers(18.07, 59.33))     # Stockholm

    def test_the_declared_country_is_switzerland(self):
        self.assertEqual(M.SERVES, ("CH",))


class TwoKindsOfNothing(unittest.TestCase):
    """Every failure this fleet has had reaches a reader as an empty grid,
    which is what a clear sky looks like. Here the file distinguishes them and
    so must we."""

    def test_nan_is_blind_and_zero_is_dry(self):
        self.assertEqual(M.level_at(float("nan")), -1)
        self.assertEqual(M.level_at(0.0), 0)

    def test_none_is_blind_too_and_does_not_crash(self):
        self.assertEqual(M.level_at(None), -1)

    def test_rain_classifies_above_zero(self):
        self.assertGreaterEqual(M.level_at(5.0), 1)


class TheSharedFloorApplies(unittest.TestCase):
    """The 7 dBZ floor DWD publishes, reached through the one shared table.
    Below it, clear-air clutter -- insects and ground echo on a hot dry
    afternoon -- used to draw as light rain across three countries."""

    def test_the_floor_lands_where_marshall_palmer_puts_it(self):
        r = (10 ** 0.7 / 200.0) ** (1 / 1.6)
        self.assertAlmostEqual(r, 0.0999, places=3)
        self.assertAlmostEqual(M.dbz_of(r), 7.0, places=6)

    def test_just_below_the_floor_is_not_rain_and_just_above_is(self):
        self.assertEqual(M.level_at(0.09), 0)
        self.assertGreaterEqual(M.level_at(0.11), 1)

    def test_it_uses_the_shared_table_rather_than_a_second_ramp(self):
        import dbz
        for rate in (0.5, 2.0, 8.0, 40.0):
            self.assertEqual(M.level_at(rate), dbz.level_for(M.dbz_of(rate)))

    def test_the_conversion_is_monotonic(self):
        vals = [M.dbz_of(r) for r in (0.2, 1.0, 5.0, 25.0)]
        self.assertEqual(vals, sorted(vals))


class TheGridIsAnchoredWhereTheFileSaysItIs(unittest.TestCase):

    def test_a_radar_site_lands_inside_the_grid(self):
        """Albis, at the position WMO OSCAR states for the id the frame's own
        how/nodes carries."""
        rc = M.cell_of(47.28417, 8.51194)
        self.assertIsNotNone(rc)
        r, c = rc
        self.assertTrue(0 <= r < M.NY and 0 <= c < M.NX, rc)

    def test_north_is_a_smaller_row_and_east_is_a_larger_column(self):
        r0, c0 = M.cell_of(46.8, 8.2)
        r_n, _ = M.cell_of(47.3, 8.2)
        _, c_e = M.cell_of(46.8, 9.2)
        self.assertLess(r_n, r0)
        self.assertGreater(c_e, c0)

    def test_a_point_off_the_grid_returns_none_rather_than_a_wrapped_cell(self):
        self.assertIsNone(M.cell_of(59.33, 18.07))     # Stockholm
        self.assertIsNone(M.cell_of(41.9, 12.5))       # Rome


class ItNamesWhyItCannotWork(unittest.TestCase):

    def test_a_missing_reader_is_named_not_silently_declined(self):
        real = M.have_h5py
        try:
            M.have_h5py = lambda: False
            self.assertIn("h5py", M.unavailable() or "")
        finally:
            M.have_h5py = real

    def test_a_working_install_reports_nothing_to_report(self):
        """The positive control: without this, unavailable() could only ever
        return a sentence and would be decoration."""
        if not have_h5py():
            self.skipTest("h5py absent here; the other direction is pinned above")
        self.assertIsNone(M.unavailable())


class ItRefusesAFrameThatIsNotTheProductItExpects(unittest.TestCase):
    """A silent upstream change would still deliver numbers and still scale
    them correctly. Each rejection is fired on a file built to earn it."""

    def setUp(self):
        if not have_h5py():
            self.skipTest("h5py not installed")
        import tempfile
        self.dir = tempfile.mkdtemp()

    def frame(self, quantity="RATE", unit="mm/h", nx=None, ny=None,
              projdef=None, cell=1000.0):
        import h5py
        import numpy as np
        nx = M.NX if nx is None else nx
        ny = M.NY if ny is None else ny
        p = os.path.join(self.dir, "f%s.h5" % len(os.listdir(self.dir)))
        with h5py.File(p, "w") as f:
            g = f.create_group("dataset1/data1")
            g.create_dataset("data", data=np.zeros((ny, nx), dtype="f8"))
            w = f.create_group("where")
            w.attrs["projdef"] = (projdef if projdef is not None else
                                  "+proj=somerc +lat_0=46.95240555555556 "
                                  "+lon_0=7.439583333333333 +k_0=1 "
                                  "+x_0=2600000 +y_0=1200000 +ellps=bessel "
                                  "+units=m +no_defs")
            w.attrs["xsize"], w.attrs["ysize"] = nx, ny
            w.attrs["xscale"] = w.attrs["yscale"] = cell
            wh = f["dataset1/data1"].create_group("what")
            wh.attrs["quantity"] = quantity
            wh.attrs["unit"] = unit
        return p

    def test_a_correct_frame_is_accepted(self):
        arr, _ = M.read(self.frame())
        self.assertEqual(arr.shape, (M.NY, M.NX))

    def test_a_reflectivity_product_is_refused_not_read_as_a_rain_rate(self):
        with self.assertRaises(ValueError):
            M.read(self.frame(quantity="DBZH", unit="dBZ"))

    def test_a_resized_grid_is_refused(self):
        with self.assertRaises(ValueError):
            M.read(self.frame(nx=700, ny=600))

    def test_a_changed_cell_size_is_refused(self):
        with self.assertRaises(ValueError):
            M.read(self.frame(cell=500.0))

    def test_a_changed_projection_is_refused(self):
        with self.assertRaises(ValueError):
            M.read(self.frame(projdef="+proj=stere +ellps=WGS84 +lat_0=90 "
                                      "+lon_0=0 +x_0=0 +y_0=0 +k_0=1"))


class AStaleCachedFrameMustNotBeatAFresherOne(unittest.TestCase):
    """The bug this file did not catch when it shipped.

    Production held one cached frame from 36 minutes earlier while MeteoSwiss
    had published up to 6 minutes ago. draw() scanned the whole cache before
    trying any download, took the stale one, then correctly refused it as too
    old -- so the country declined entirely with fresh data sitting there.
    "Prefer the cache" is right; "prefer ANY cached frame over a newer one" is
    not, and they look identical until the cache holds exactly one old entry.
    """

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.old_cache = M.CACHE
        M.CACHE = self.dir

    def tearDown(self):
        M.CACHE = self.old_cache

    def test_the_newest_slot_is_tried_before_older_cached_ones(self):
        st = M.stamps()
        # Only the OLDEST candidate is on disk, as it was in production.
        with open(M._cache_path(st[-1]), "wb") as fh:
            fh.write(b"\x89HDF\r\n\x1a\n" + b"0" * 32)
        asked = []

        def get(url):
            asked.append(url)
            return b"\x89HDF\r\n\x1a\n" + b"1" * 32

        # Call draw() itself. The first version of this test re-implemented
        # draw()'s loop inline and therefore tested a replica of the code --
        # it stayed green with the bug put back. Ask the subject about itself.
        M.draw("><", 8.55, 47.3667, get=get)
        self.assertTrue(asked,
                        "no download attempted: a stale cached frame won "
                        "outright, which is the bug")
        self.assertIn(M.frame_name(st[0]), asked[0],
                      "the NEWEST slot must be asked for first, not an older one")

    def test_cached_only_never_opens_a_socket_even_when_the_cache_is_stale(self):
        """The other half: the flag must still hold. A reader already holding a
        map does not pay for a round trip."""
        calls = []
        r = M.draw("><", 8.55, 47.3667,
                   get=lambda u: calls.append(u) or b"", cached_only=True)
        self.assertEqual(calls, [], "cached_only opened a socket")
        self.assertIsNone(r)


class BlindCellsRenderAsBlindNotAsClearSky(unittest.TestCase):

    def setUp(self):
        if not have_h5py():
            self.skipTest("h5py not installed")

    def test_nan_reaches_the_reader_as_outside_not_as_blank(self):
        """`render.py` says it in one line: OUTSIDE is "?" and not " ", because
        empty means "no rain" and this means "no radar here"."""
        import numpy as np
        from runemap.render import OUTSIDE
        arr = np.full((M.NY, M.NX), np.nan, dtype="f8")
        levels, share = M.window(arr, 8.55, 47.3667, 280.0, 48, 24)
        self.assertEqual(share, 1.0)
        self.assertTrue((levels == -1).all())
        self.assertEqual(OUTSIDE, "?")

    def test_a_dry_frame_is_not_reported_as_blind(self):
        import numpy as np
        arr = np.zeros((M.NY, M.NX), dtype="f8")
        levels, share = M.window(arr, 8.55, 47.3667, 280.0, 48, 24)
        self.assertEqual(share, 0.0)
        self.assertTrue((levels == 0).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
