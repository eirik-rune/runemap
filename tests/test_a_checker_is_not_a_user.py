"""A checker that calls a real tool must not be counted as a user.

2026-08-17. The first two `tools/call` for `get_weather` from outside came from
`SaSame-MCP-Audit/0.1`, and the report announced them under "this is the only
bucket that is use". The split it draws -- listed / checked / used -- is the
whole reason the script exists, and it failed on that split one line after
drawing it, because the only thing separating the two was whether the tool name
was one we advertise. An auditor that calls a real tool looks exactly like a
customer.

So the rows are split rather than filtered. A user agent is something the
caller chose to say, which makes it fine as a reason to *doubt* a row and a bad
reason to *delete* one: a real user who happens to ship "monitor" in their UA
must still appear. Hiding them is the expensive direction, because the number
this feeds is the one that would tell us a stranger needs this -- and that
number is currently 0, which is only useful if it can still become 1.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import mcp_who_called as M            # noqa: E402


class SelfDeclaredCheckersAreSplitOut(unittest.TestCase):
    def _check(self, ua):
        # The predicate is reached through the module rather than re-typed here;
        # a copy in the test would pass while the subject was broken, which is
        # how two other test files went green today with the bug in place.
        fn = getattr(M, "_self_declared_checker", None)
        self.assertIsNotNone(fn, "the split must exist in the subject, not in this file")
        return fn({"ua": ua})

    def test_the_audit_client_that_caused_this_is_recognised(self):
        self.assertTrue(self._check("SaSame-MCP-Audit/0.1"))

    def test_other_shapes_of_the_same_claim(self):
        for ua in ("acme-scanner/2", "MCP Verify Bot", "uptime-monitor",
                   "healthcheck/1.0", "probe-runner"):
            self.assertTrue(self._check(ua), ua)

    def test_an_ordinary_client_is_not_swept_up(self):
        """The other direction, fired on purpose: a verdict that only ever says
        'checker' would report zero users forever and look responsible doing it."""
        for ua in ("python-requests/2.32", "curl/8.5.0", "claude-code/1.2",
                   "Mozilla/5.0", "", None):
            self.assertFalse(self._check(ua), repr(ua))

    def test_the_word_is_matched_case_insensitively(self):
        self.assertTrue(self._check("BIG-AUDIT-TOOL"))


if __name__ == "__main__":
    unittest.main()
