# -*- coding: utf-8 -*-
"""A test that MUST fail, on a throwaway branch that MUST NOT be merged.

2026-08-12 11:03: the new unit-tests job came back green on PR #36. That proves
it can say "pass". It does not prove it can say "fail" -- and a gate that never
goes red is decoration, not evidence (I have shipped three of those this month:
a watcher whose pgrep matched itself, a drift check that globbed only *.py, a
counter that counted the legend as rain).

So: deliberate failure, on branch eirik/ci-negative-control, in a shallow clone
that shares no git metadata with the dev arm under soak until 14:10 UTC. The
expected verdict is unit-tests conclusion=failure. Then the PR is closed and the
branch deleted; nothing here is ever merged.

The sentinel string is deliberately dead -- it appears nowhere else in the tree,
so grepping for it cannot match the prose that talks about it.
"""
import unittest


class CIGateNegativeControl(unittest.TestCase):
    def test_this_must_turn_the_gate_red(self):
        self.assertEqual("KUMLGRAV-1103", "gate must be able to say no")
