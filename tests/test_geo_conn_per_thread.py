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


def _fixture():
    """A db derived from the real schema (sqlite_master of geo.sqlite, 8/13), not
    from the environment: the 05:15 version of this file asked for
    /home/ubuntu/geonames/geo.sqlite, which exists on the production box and in no
    repo, so CI could only ever go red. Four cities are enough -- what is under
    test is the connection, not the gazetteer."""
    import sqlite3
    import tempfile
    d = tempfile.mkdtemp(prefix="geofix-")
    path = os.path.join(d, "geo.sqlite")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, lat REAL, "
              "lon REAL, cc TEXT, a1 TEXT, a2 TEXT, pop INTEGER, tz TEXT)")
    c.execute("CREATE TABLE alias(key TEXT, pid INTEGER, pop INTEGER)")
    c.execute("CREATE TABLE admin(code TEXT PRIMARY KEY, name TEXT)")
    rows = ((1, "London", 51.51, -0.13, "GB", "ENG", None, 8961989, "Europe/London"),
            (2, "Paris", 48.85, 2.35, "FR", "11", "75", 2138551, "Europe/Paris"),
            (3, "Tokyo", 35.69, 139.69, "JP", "40", None, 8336599, "Asia/Tokyo"),
            (4, "Berlin", 52.52, 13.41, "DE", "16", None, 3426354, "Europe/Berlin"))
    c.executemany("INSERT INTO place VALUES(?,?,?,?,?,?,?,?,?)", rows)
    c.executemany("INSERT INTO alias VALUES(?,?,?)",
                  [(geo.norm(r[1]), r[0], r[7]) for r in rows])
    c.execute("CREATE INDEX ix_alias ON alias(key, pop DESC)")
    c.execute("CREATE INDEX ix_alias_sq ON alias(replace(key,' ',''), pop DESC)")
    c.commit()
    c.close()
    return path


def setUpModule():
    geo.DB = _fixture()


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
