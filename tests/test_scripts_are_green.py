"""The two script-style checks, run the way they were written.

They call sys.exit() at import, so unittest's loader recorded a SystemExit as
an ERROR for each -- the suite had two permanent red marks that meant nothing,
and worse, discover never actually exercised their assertions. A red that means
nothing is the same disease as a check that can never fail: nobody reads it.
So they are renamed out of discover's way and run here as what they are --
subprocesses whose exit code is the verdict.
"""
import os, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class Scripts(unittest.TestCase):
    def _run(self, name):
        p = subprocess.run([sys.executable, os.path.join(HERE, name)],
                           cwd=os.path.dirname(HERE), capture_output=True, timeout=90)
        out = (p.stdout + p.stderr).decode(errors="replace")
        self.assertEqual(p.returncode, 0, out)
        self.assertNotIn("FAIL", out, out)

    def test_close_header(self):
        self._run("check_close_header.py")

    def test_hedged(self):
        self._run("check_hedged.py")
