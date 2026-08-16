"""Everything the report says out loud must reach the file the bell reads.

2026-08-16. mcpservers.org approved us -- the first directory listing of this
whole promotion push, the first genuinely external event. The daily watcher
said nothing. An email told me.

The cause was pure ordering: the state file was written between the two probe
loops, so DIRECT verdicts were printed to stdout and never stored. The report
said LISTED; the only channel the alarm consults had never heard of that probe.

That is worse than a check that cannot fail. This one could fail, did fail, and
announced it correctly -- while the alarm was wired to a different data source
than the announcement. So the invariant under test is not "the verdict is
right", it is **every probe that can speak also gets recorded**, which is what
no amount of reading the output would have revealed.

Network is stubbed. These tests must not ask the internet whether we are listed
-- that would make them a monitor, and a monitor that fails when a third party
has a bad afternoon teaches me to ignore red.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (os.path.join(_ROOT, "ops"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import listed_where as L             # noqa: E402


def run_with(fetch, state_path):
    """Run main() against a stubbed network and a throwaway state file."""
    real_fetch, real_state, real_argv = L.fetch, L.STATE, sys.argv
    L.fetch, L.STATE = fetch, state_path
    # main() parses sys.argv, which under unittest holds the test selector and
    # would abort with SystemExit(2) -- an exit code this tool also uses for
    # "could not tell". Two different meanings on one number is exactly what
    # the rest of this file is about, so the argv is pinned rather than tolerated.
    sys.argv = ["listed_where.py"]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = L.main()
    finally:
        L.fetch, L.STATE, sys.argv = real_fetch, real_state, real_argv
    return rc, buf.getvalue()


def listed_everywhere(url):
    """Every page resolves except a control namespace, which cannot exist."""
    if "zzqqx-nothing" in url or "does-not-exist" in url:
        return None, "HTTP 404"
    return "runemap runemap runemap runemap", None


class EveryProbeReachesTheFileTheBellReads(unittest.TestCase):
    def test_no_probe_is_printed_without_being_stored(self):
        """The exact bug: DIRECT spoke and was not recorded."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            rc, out = run_with(listed_everywhere, p)
            stored = json.load(open(p, encoding="utf-8"))
        expected = {n for n, *_ in L.SITES} | {n for n, *_ in L.DIRECT}
        self.assertEqual(set(stored), expected,
                         "printed but unstored: %s" % (expected - set(stored)))
        self.assertIn("mcpservers.org", stored,
                      "the directory that actually approved us must be watched")

    def test_a_direct_probe_can_reach_the_file_as_LISTED(self):
        """Storing the name is not enough -- the verdict has to survive too.

        A version that stored every key but froze DIRECT at its pre-loop value
        would pass the test above and still never ring.
        """
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            run_with(listed_everywhere, p)
            stored = json.load(open(p, encoding="utf-8"))
        direct_names = [n for n, *_ in L.DIRECT]
        self.assertIn("LISTED", [stored[n] for n in direct_names],
                      "no DIRECT probe reached the state file as LISTED, so a "
                      "listing on one of them could never ring")


class TheProbeCanStillSayAbsent(unittest.TestCase):
    """A ruler that only ever reads LISTED has no jurisdiction, so the other
    direction is fired here rather than assumed."""

    def test_absent_when_our_page_404s_like_the_control(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            run_with(lambda url: (None, "HTTP 404"), p)
            stored = json.load(open(p, encoding="utf-8"))
        for name, *_ in L.DIRECT:
            self.assertEqual(stored[name], "ABSENT", name)

    def test_control_resolving_while_we_do_not_is_no_signal_not_absent(self):
        """"The ruler is misbehaving" must not print as "we are not listed"."""
        def only_control(url):
            if "zzqqx-nothing" in url or "does-not-exist" in url:
                return "a page", None
            return None, "HTTP 404"
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            rc, out = run_with(only_control, p)
            stored = json.load(open(p, encoding="utf-8"))
        for name, *_ in L.DIRECT:
            self.assertEqual(stored[name], "NO-SIGNAL", name)
        self.assertEqual(rc, 2, "could-not-tell must not exit like all-clear")


if __name__ == "__main__":
    unittest.main()
