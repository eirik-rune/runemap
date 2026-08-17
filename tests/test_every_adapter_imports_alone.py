"""Every probe must import without help from the probe before it.

2026-08-17. `ops/source_health.py zurich` printed
`ERROR chrzc-zurich: ModuleNotFoundError: No module named 'runemap'` while the
full fleet run printed `OK chrzc-zurich` for the same source in the same
minute. The adapter was importable only because an earlier probe had inserted
the repository root into sys.path as a side effect; a clean pair proved it --
`zurich` alone failed, `jma zurich` passed.

Two things were wrong and only one of them was the crash:

1. The single-source form is the one I reach for **when a source is already
   misbehaving**. The monitor was healthy and the diagnostic was lying, which
   is the worse way round: it sends the next hour of investigation at a source
   that is fine.
2. The fleet's green light for Switzerland was passing for a reason it did not
   state. "This adapter works" and "something that ran before it repaired the
   path" produce the same word.

So the assertion here is not "the fleet is green". It is that each adapter
imports **in isolation**, which is the claim the fleet result silently borrows.
Each import runs in its own interpreter, because an import inside this process
would be satisfied by whatever the test runner already loaded -- the same
borrowed-success that caused the bug.

No network: importing an adapter must not fetch anything, and if that ever
stops being true this test will get slow and say so.
"""
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import source_health as S            # noqa: E402


class EachAdapterStandsOnItsOwn(unittest.TestCase):
    def test_every_probe_module_imports_in_a_fresh_interpreter(self):
        # The first version of this file hand-wrote the two sys.path lines here
        # -- and stayed green with the fix deleted, because it was asserting
        # against its own copy of the setup instead of the subject's. Firing it
        # is what showed that; reading it would not have.
        #
        # So the subprocess now imports source_health FIRST and lets it lay the
        # path, exactly as production does. Only `ops` is placed by hand, since
        # without that there is nothing to import at all.
        setup = (
            "import sys, os\n"
            "sys.path.insert(0, os.path.join(%r, 'ops'))\n"
            "import source_health\n" % (_ROOT,)
        )
        broken = []
        for probe in S.PROBES:
            label, modname = probe[0], probe[1]
            r = subprocess.run(
                [sys.executable, "-c", setup + "__import__(%r)" % modname],
                capture_output=True, text=True, timeout=120, cwd="/")
            if r.returncode != 0:
                broken.append("%s (%s): %s" % (
                    label, modname, r.stderr.strip().splitlines()[-1:]))
        self.assertEqual(broken, [], "adapters that need a neighbour to import: %s"
                         % broken)

    def test_importing_the_probe_is_what_puts_the_root_on_the_path(self):
        """Asked in a fresh interpreter, because this one already has it.

        The first version asserted against *this* process's sys.path, which the
        test runner had already populated with the repo root -- it passed with
        the fix deleted. An assertion satisfied by something other than the
        subject is not testing the subject.
        """
        code = (
            "import sys, os\n"
            "sys.path.insert(0, os.path.join(%r, 'ops'))\n"
            "before = [os.path.abspath(p) for p in sys.path]\n"
            "import source_health\n"
            "after = [os.path.abspath(p) for p in sys.path]\n"
            "root = os.path.abspath(%r)\n"
            "print('BEFORE' if root in before else 'ABSENT',\n"
            "      'AFTER' if root in after else 'MISSING')\n" % (_ROOT, _ROOT)
        )
        # cwd="/" is load-bearing, not tidiness: python puts the working
        # directory on sys.path, so run from the repo root the root is already
        # importable and neither of these tests can see the fix at all. The
        # positive-control assertion below caught exactly that.
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=60, cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.split()
        self.assertEqual(out[0], "ABSENT",
                         "the root was already importable before source_health ran, "
                         "so this test cannot see whether source_health adds it")
        self.assertEqual(out[1], "AFTER",
                         "importing source_health must leave the repo root importable")


if __name__ == "__main__":
    unittest.main()
