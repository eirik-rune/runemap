"""Every source that can draw a map must be able to name its licence.

This exists because MeteoSwiss was added to the chain and served Swiss readers
crediting nobody: the attribution resolver kept its own hand-written tuple of
module names, and the new module was not in it. The fallback returns the bare
NAME, which *looks* like an attribution and is not the licence line CC BY asks
for -- so nothing failed, nothing logged, and the obligation was quietly
dropped.

The generalisation is the same one that put the US in the wrong place earlier
today: a second hand-kept list of modules will drift from the first.
"""
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "scripts"), os.path.join(_ROOT, "ops"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import render_scene as R          # noqa: E402


class EverySourceCanNameItself(unittest.TestCase):

    def test_every_module_in_the_chain_table_resolves_its_own_attribution(self):
        """The whole point: iterate what production resolves, not a list
        written here, or this test acquires the very drift it guards."""
        import importlib
        for key, modname in R.SECOND_MODULES.items():
            with self.subTest(source=key):
                m = importlib.import_module(modname)
                name = getattr(m, "NAME", None)
                if name is None:
                    # radar_wms is four countries in one module and holds a
                    # name per service instead. Asserted below rather than
                    # skipped, so "no NAME" cannot become a way to opt out.
                    self.assertTrue(getattr(m, "SERVICES", None),
                                    "%s has neither NAME nor SERVICES" % modname)
                    continue
                got = R._second_attrib(name)
                self.assertNotEqual(
                    got, name,
                    "%s resolves to its bare NAME -- that is the silent "
                    "fallback, not an attribution" % modname)

    def test_the_wms_services_each_carry_their_own_credit(self):
        import radar_wms as W
        for svc in W.SERVICES:
            with self.subTest(service=svc["key"]):
                self.assertEqual(R._second_attrib(svc["name"]), svc["attrib"])

    def test_a_licence_bearing_source_states_its_licence(self):
        """CC BY is a condition of use, not a courtesy."""
        for name in ("MeteoSwiss", "MET Norway", "DMI"):
            self.assertIn("CC BY", R._second_attrib(name), name)

    def test_the_resolver_does_not_keep_its_own_list_of_modules(self):
        with open(os.path.join(_ROOT, "scripts", "render_scene.py")) as fh:
            src = fh.read()
        i = src.index("def _second_attrib")
        body = src[i:i + 1400]
        self.assertIn("SECOND_MODULES", body)
        self.assertNotIn('"radar_dmi"', body)

    def test_an_unclaimed_name_still_returns_something_printable(self):
        """Degrading to the bare name is right for a reader; it just must not
        be how a real source is treated."""
        self.assertEqual(R._second_attrib("Not A Source"), "Not A Source")


if __name__ == "__main__":
    unittest.main(verbosity=2)
