"""What we answer when a client asks for a protocol version we do not speak.

2026-09-09. This endpoint had no test for version negotiation at all, which is
why it was wrong for as long as it was. The measurement that found it: 24h of
real initialize calls, 492 of them, of which **110 asked for 2025-11-25 and
were refused** across 14 distinct clients -- including glama/1.0.0, which
publicly lists this connector as Unhealthy, and which sends exactly one
request, gets a 200, and never comes back.

The old fallback answered with our NEWEST version. That is the wrong end of the
list: a client that sends `initialize` is a legacy-era client, and 2026-07-28
is a modern revision that has no initialize handshake at all. The spec says
such clients "have no fall-forward mechanism", so the only thing they can do
with that answer is leave.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))


class TheFallbackIsUsable(unittest.TestCase):

    def setUp(self):
        import serve
        self.serve = serve

    def test_a_version_we_speak_is_honoured_unchanged(self):
        for v in self.serve._MCP_VERSIONS:
            spoken, honoured = self.serve._negotiate(v)
            self.assertEqual(spoken, v)
            self.assertTrue(honoured)

    def test_the_version_the_ecosystem_actually_asks_for_gets_a_legacy_answer(self):
        """2025-11-25 is what 110 of 492 real calls asked for."""
        spoken, honoured = self.serve._negotiate("2025-11-25")
        self.assertFalse(honoured)
        self.assertEqual(spoken, "2025-06-18")

    def test_we_never_answer_a_handshake_with_a_handshakeless_version(self):
        """The regression itself. Answering `initialize` with 2026-07-28 hands
        a legacy client a revision whose premise is that initialize does not
        exist -- which is why they disconnect."""
        for asked in ("2025-11-25", "2025-03-26", "2024-11-05", "1999-01-01",
                      None, "", "not-a-date"):
            spoken, honoured = self.serve._negotiate(asked)
            if not honoured:
                self.assertLessEqual(
                    spoken, self.serve._MCP_LAST_LEGACY,
                    "asked %r -> answered %r, which is a modern revision with "
                    "no initialize handshake" % (asked, spoken))

    def test_an_unknown_version_is_not_silently_accepted(self):
        _, honoured = self.serve._negotiate("2030-01-01")
        self.assertFalse(honoured)

    def test_the_allowlist_does_not_claim_a_spec_we_have_not_run(self):
        """The list means 'exercised against'. Adding 2025-11-25 because
        clients ask for it would be claiming a spec nothing here has been run
        against -- the health check that always returns 200."""
        self.assertNotIn("2025-11-25", self.serve._MCP_VERSIONS)

    def test_the_legacy_subset_is_derived_not_hand_listed(self):
        self.assertEqual(
            self.serve._MCP_LEGACY_VERSIONS,
            tuple(v for v in self.serve._MCP_VERSIONS
                  if v <= self.serve._MCP_LAST_LEGACY))
        self.assertTrue(self.serve._MCP_LEGACY_VERSIONS,
                        "if we ever speak only modern versions, initialize "
                        "needs an error listing them, not a downgrade")


class TheLogAndTheReplyCannotDisagree(unittest.TestCase):
    """They used to be two separate copies of the rule. The log is the thing I
    would have used to check the reply, so a drift between them would have hid
    itself."""

    def test_both_come_from_the_one_function(self):
        import inspect
        import serve
        src = inspect.getsource(serve)
        # Mentions minus the definition itself. Counting raw mentions is off by
        # one and would pass for the wrong reason.
        calls = src.count("_negotiate(") - src.count("def _negotiate(")
        self.assertEqual(
            calls, 2,
            "the reply and the log line must each call _negotiate exactly "
            "once; found %d call sites" % calls)

    def test_only_the_one_function_reads_the_version_list(self):
        """Nobody else may re-derive the rule from _MCP_VERSIONS.

        The first version of this test grepped the source for the old
        expression -- and failed, because it matched the sentence in
        _negotiate's own docstring explaining why that expression was wrong.
        Source carries both what the code does and why it no longer does it,
        and a string search cannot separate them. So: parse it.
        """
        import ast
        import inspect
        import serve
        tree = ast.parse(inspect.getsource(serve))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name == "_negotiate":
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in (
                        "_MCP_VERSIONS", "_MCP_LEGACY_VERSIONS"):
                    offenders.append(node.name)
        self.assertEqual(sorted(set(offenders)), [], "these re-derive the "
                         "negotiation rule instead of calling _negotiate")


if __name__ == "__main__":
    unittest.main()
