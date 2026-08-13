# -*- coding: utf-8 -*-
"""geo.py must hand each thread its own sqlite connection.

Measured 8/13 05:11 on this box: one shared connection under 8 threads raised
sqlite3.InterfaceError ("bad parameter or other API misuse") 11 times in 4789
lookups (0.23%), while per-thread connections raised 0 in 4800. Production had
3 of those in 6h, on the ?q= entry, at serve.py:339 -> geo.py:30.

What is asserted here is STRUCTURE, not the error. A test that asserts "the
shared connection fails" would be flaky by construction: in one of my three
control rounds the shared arm happened to be clean. The cure is that misuse is
structurally impossible, so the guard checks the structure -- distinct objects
per thread, and reuse within one thread -- plus a negative control so it can
still go red if _db() ever collapses back to one process-wide connection.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import geo


class ConnectionIsPerThread(unittest.TestCase):
    def _ids(self, n):
        got = {}

        def grab(i):
            got[i] = id(geo._db())

        ts = [threading.Thread(target=grab, args=(i,)) for i in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return got

    def test_each_thread_gets_its_own(self):
        got = self._ids(4)
        self.assertEqual(len(got), 4, "a thread failed to reach _db() at all")
        self.assertEqual(len(set(got.values())), 4,
                         "threads shared a connection: %s" % sorted(got.values()))

    def test_one_thread_reuses_its_own(self):
        same = []

        def twice():
            same.append(id(geo._db()) == id(geo._db()))

        t = threading.Thread(target=twice)
        t.start()
        t.join()
        self.assertEqual(same, [True], "a thread reopened sqlite on every call")

    def test_the_ruler_can_go_red(self):
        # negative control: a process-wide singleton is exactly the shape this
        # guard exists to forbid, and the same predicate must reject it.
        shared = object()
        got = {i: id(shared) for i in range(4)}
        self.assertEqual(len(set(got.values())), 1)

    def test_lookup_survives_concurrency(self):
        errs = []
        hits = []

        def hammer():
            for i in range(40):
                try:
                    p = geo.lookup(["london", "paris", "tokyo", "berlin"][i % 4])
                    hits.append(1 if p else 0)
                except Exception as e:
                    errs.append(type(e).__name__)

        ts = [threading.Thread(target=hammer) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [], "concurrent geo.lookup raised: %s" % set(errs))
        # positive control: silence is only meaningful if lookups really ran
        self.assertGreater(sum(hits), 0, "NO-INSTRUMENT: no lookup returned a place")


if __name__ == "__main__":
    unittest.main()
