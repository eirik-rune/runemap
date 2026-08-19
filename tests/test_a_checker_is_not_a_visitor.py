"""A machine that says it is checking us must not sit in the bucket named
"could be a user" -- and must not be deleted from it either.

2026-08-19. The site log's ASKED-FOR-WEATHER bucket had 4260 requests, and its
two loudest agents were `SentinelOracle/0.1 (+https://glimind.com/opt-out;
liveness-check)` at 1196 and `mcpbeat/0.1 (+https://mcpbeat.com/bot/; liveness
check)` at 438. Neither matched AGENTISH_UA, so both were being counted under
`browser-like-or-unknown` -- the label that reads "might be a person", which is
the worst available place for a machine that announces it is a machine. 1808 of
4260 turned out to say it.

This matters more than the tidiness: `program-like` is the column the weekly
report and the acceptance criterion name, so a number that moves when nobody
needs us is a number that lies in the flattering direction.

Two rules the tests hold down:

- **Split, never filter.** A user agent is a claim. A real person whose string
  happens to contain "monitor" must still appear in the output, under a name
  that says what it claimed rather than what it is. The same mistake in
  mcp_who_called on 8/17 was fixed the same way.
- **One predicate.** `self_declared_checker` lives in who_is_using next to
  INSIDER_NETS, and mcp_who_called imports it. Two lists of words-meaning-
  checker would each look reasonable and then quietly disagree.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ops"))

import who_is_using as W            # noqa: E402


class TheClaimIsRecordedNotObeyed(unittest.TestCase):
    def test_the_agents_that_prompted_this_are_caught(self):
        for ua in ("SentinelOracle/0.1 (+https://glimind.com/opt-out; liveness-check)",
                   "mcpbeat/0.1 (+https://mcpbeat.com/bot/; liveness check)"):
            self.assertTrue(W.self_declared_checker(ua), ua)

    def test_an_ordinary_client_is_not_caught(self):
        """The control. A predicate that says yes to everything would 'fix' the
        number by emptying it, which is the same lie facing the other way."""
        for ua in ("curl/8.7.1", "python-requests/2.32", "Bun/1.1.45", "node",
                   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"):
            self.assertFalse(W.self_declared_checker(ua), ua)

    def test_an_empty_or_missing_agent_is_not_a_claim(self):
        self.assertFalse(W.self_declared_checker(""))
        self.assertFalse(W.self_declared_checker(None))

    def test_there_is_exactly_one_predicate(self):
        """mcp_who_called must ask this module, not keep its own word list."""
        import mcp_who_called as M
        self.assertIs(M.self_declared_checker, W.self_declared_checker)
        self.assertTrue(M._self_declared_checker({"ua": "SaSame-MCP-Audit/0.1"}))
        self.assertFalse(M._self_declared_checker({"ua": "curl/8.7.1"}))

    def test_a_checker_is_reported_not_removed(self):
        """Split, never filter: the three labels must add up to the bucket, so
        nothing can be quietly dropped on its way to the summary."""
        uas = ["SentinelOracle/0.1 (liveness-check)", "curl/8.7.1",
               "Mozilla/5.0 (Windows NT 10.0)", "mcpbeat/0.1 (liveness check)",
               "python-requests/2.32"]
        seen = {"says it is a checker (not a user)": 0, "program-like": 0,
                "browser-like-or-unknown": 0}
        for ua in uas:
            low = ua.lower()
            if W.self_declared_checker(ua):
                seen["says it is a checker (not a user)"] += 1
            elif any(x in low for x in W.AGENTISH_UA):
                seen["program-like"] += 1
            else:
                seen["browser-like-or-unknown"] += 1
        self.assertEqual(sum(seen.values()), len(uas))
        self.assertEqual(seen["says it is a checker (not a user)"], 2)
        self.assertEqual(seen["program-like"], 2)
        self.assertEqual(seen["browser-like-or-unknown"], 1)


class ZerosMustNotStandInForSilence(unittest.TestCase):
    def test_unreadable_logs_are_refused_rather_than_reported_as_zero(self):
        """Run as a user who cannot read nginx's logs, every count printed 0 and
        the summary read "0 requests came from outside our own machines". That
        is indistinguishable from nobody coming -- on the instrument that
        reports the acceptance criterion. It must exit 2 and say NO-LOG."""
        import io
        import contextlib
        import tempfile
        # The file must EXIST and yield nothing. My first version pointed at a
        # path that does not exist, which is caught by an earlier guard -- so
        # the test passed with this branch deleted, i.e. it was satisfied by
        # something other than the thing it names. Firing it is what showed
        # that; reading it would not have.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "access.log")
            open(p, "w").close()          # readable, present, and empty
            out = io.StringIO()
            argv = sys.argv
            sys.argv = ["who_is_using", "--log", p]
            try:
                with contextlib.redirect_stdout(out):
                    rc = W.main()
            finally:
                sys.argv = argv
        self.assertEqual(rc, 2, out.getvalue())
        self.assertIn("NO-LOG", out.getvalue())


if __name__ == "__main__":
    unittest.main()
