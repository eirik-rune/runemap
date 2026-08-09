# -*- coding: utf-8 -*-
"""The remembered-pool race, and the two ways it can go inert in silence.

2026-08-09. DNS hands out eight addresses that always share one /24, so the
eight are one POP, and 4.7% of the day that POP answers nobody: all dials fail
together at TOTAL + hedge = 7.00s. A reader waits 6.25s, so a fallback that
begins AFTER the failure is 0.75s too late for the reader who triggered it.
The only shape that helps them is to put the previously-good addresses into the
SAME race -- which is what these tests hold in place.

Both failure modes here are silent, which is why they are tests and not
comments:

  * racers used to be infos[:MAX_PARALLEL], and DNS returns exactly
    MAX_PARALLEL addresses, so anything appended before the slice is dropped
    without an error and the feature merely looks useless.
  * _bounded returns to the stdlib when getaddrinfo yields one address, which
    would skip the remembered pool entirely -- the exact case it exists for.

Every positive assertion is paired with a negative control, because a test that
cannot fail is decoration: each one first proves the blackhole really does kill
the dial before proving memory survives it.
"""
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import happy_eyeballs as he  # noqa: E402

HOST = "meteorology.caiyuncdn.com"
BLACKHOLE = "203.0.113.7"       # TEST-NET-3 (RFC 5737): guaranteed unroutable
REAL_GAI = socket.getaddrinfo


def _entry(ip, port=80):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))


class PoolMemory(unittest.TestCase):
    def setUp(self):
        self._gai = he.socket.getaddrinfo
        he._MEM.clear()
        # A local listener stands in for "an address that answers", so the test
        # needs no upstream and cannot fail because the CDN is having a bad day.
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.good = self.srv.getsockname()

    def tearDown(self):
        he.socket.getaddrinfo = self._gai
        he._MEM.clear()
        self.srv.close()

    def _dns(self, ips):
        def fake(host, port, *a, **kw):
            if host == HOST:
                return [_entry(ip, port) for ip in ips]
            return REAL_GAI(host, port, *a, **kw)
        he.socket.getaddrinfo = fake

    def _dial(self):
        return he._bounded((HOST, self.good[1]), timeout=3.0)

    def test_extras_survive_the_slice(self):
        """MAX_PARALLEL addresses from DNS must not crowd out the memory."""
        self._dns([BLACKHOLE] * he.MAX_PARALLEL)
        with self.assertRaises(OSError):          # negative control first
            self._dial()
        he._remember(HOST, _entry(self.good[0], self.good[1]))
        s = self._dial()
        self.addCleanup(s.close)
        self.assertEqual(s.getpeername()[0], self.good[0])

    def test_single_address_bypass_does_not_swallow_extras(self):
        """One dead address is still a race when something is remembered."""
        self._dns([BLACKHOLE])
        with self.assertRaises(OSError):          # negative control first
            self._dial()
        he._remember(HOST, _entry(self.good[0], self.good[1]))
        s = self._dial()
        self.addCleanup(s.close)
        self.assertEqual(s.getpeername()[0], self.good[0])

    def test_memory_is_scoped_to_listed_hosts(self):
        """install() is process-wide; the memory must not be.

        The weather fetch on the reader path goes through this same patched
        create_connection, so an unscoped memory would alter it too."""
        he._remember("api.caiyunapp.com", _entry(self.good[0], self.good[1]))
        self.assertEqual(he._MEM.get("api.caiyunapp.com", []), [])
        he._remember(HOST, _entry(self.good[0], self.good[1]))
        self.assertTrue(he._MEM.get(HOST))

    def test_winner_is_remembered_and_bounded(self):
        self._dns([self.good[0]])
        for _ in range(he._MEM_KEEP + 3):
            s = self._dial()
            s.close()
        self.assertLessEqual(len(he._MEM.get(HOST, [])), he._MEM_KEEP)
        self.assertEqual(he._MEM[HOST][0][4][0], self.good[0])

    def test_memory_written_by_a_real_winner_can_be_redialed(self):
        """The round trip: a socket teaches the memory, the memory rebuilds it.

        Every other test hands _remember a hand-built tuple, so none of them
        proves the entry a REAL winner produces can be turned back into a
        socket. dial() calls socket.socket(family, type, proto) on it, and on
        Linux a socket's type can carry flag bits (SOCK_NONBLOCK/SOCK_CLOEXEC);
        if that ever leaks in, the rebuild raises OSError -- which dial()
        catches, so the address just loses the race and the whole mechanism
        goes quiet without a single error line.
        """
        self._dns([self.good[0]])
        s1 = self._dial()                       # real connect writes the memory
        s1.close()
        self.assertTrue(he._MEM.get(HOST), "nothing remembered from a real dial")
        entry = he._MEM[HOST][0]

        self._dns([BLACKHOLE])                  # negative control: the pool died
        he._MEM[HOST] = []
        with self.assertRaises(OSError):
            self._dial()

        he._MEM[HOST] = [entry]                 # only the machine-made entry now
        s2 = self._dial()
        self.addCleanup(s2.close)
        self.assertEqual(s2.getpeername()[0], self.good[0])

    def test_pools_not_machines(self):
        """Two addresses in one /24 are one failure unit, so they get one slot.

        DNS hands out eight addresses that always share a /24 and they go dark
        together, so remembering two of them remembers one building twice."""
        e1 = _entry("198.51.100.1")
        e2 = _entry("198.51.100.2")             # same /24 as e1
        e3 = _entry("203.0.113.5")              # a different pool
        for e in (e1, e2, e3):
            he._remember(HOST, e)
        pools = [he._pool(e) for e in he._MEM[HOST]]
        self.assertEqual(len(set(pools)), len(pools), "two entries from one /24")
        self.assertIn("203.0.113", pools)
        self.assertIn("198.51.100", pools)
        self.assertEqual(he._MEM[HOST][0][4][0], "203.0.113.5")

    def test_the_feature_can_be_switched_off(self):
        """An empty host list must short-circuit both halves, not just one."""
        keep = he._MEM_HOSTS
        try:
            he._MEM_HOSTS = set()
            he._remember(HOST, _entry(self.good[0], self.good[1]))
            self.assertEqual(he._MEM.get(HOST, []), [])
            self.assertEqual(he._extras(HOST, []), [])
        finally:
            he._MEM_HOSTS = keep


if __name__ == "__main__":
    unittest.main()
