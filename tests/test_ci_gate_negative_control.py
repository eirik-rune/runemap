# -*- coding: utf-8 -*-
"""A test that MUST fail, on a throwaway branch that MUST NOT be merged.

2026-08-12 11:03: the unit-tests job came back green on PR #36. That proves it
can say "pass". It does not prove it can say "fail" -- and a gate that never
goes red is decoration, not evidence.

11:05, first attempt: I branched the failing test off main, in a deliberately
clean shallow clone. The check-runs came back with unit_tests=ABSENT -- the job
lives on eirik/pool-instrument, not on main, so my clean room was clean of the
thing under test. A negative control has to run on the tree that CONTAINS the
guard; otherwise "no red" and "no guard" share one answer, which is the same
shape as the two-ended zero I keep being fooled by.

The sentinel is deliberately dead: it appears nowhere else in the tree, so
grepping for it cannot match the prose that discusses it.
"""
import unittest


class CIGateNegativeControl(unittest.TestCase):
    def test_this_must_turn_the_gate_red(self):
        self.assertEqual("KUMLGRAV-1103", "gate must be able to say no")


# 11:08, take 3. Retargeting the PR to main returned http=200 and the base did
# change, yet check-runs stayed at total=0. Reason: `pull_request` fires on
# opened/synchronize/reopened by default -- a base change is the `edited`
# activity, which nobody subscribed to. So take 1 had the base but not the
# guard, take 2 had the guard but not the base, and take 3 had both but no
# dispatch. Three attempts, three different unmet preconditions, each of which
# looked like "the gate is fine" from the outside.
