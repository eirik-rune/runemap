"""The SOCKS5 egress path, proven against a real SOCKS5 server.

Contributed by Martob13 in PR #219 against a bounty that had already been
withdrawn — they wrote it, I reviewed it and told them the money was gone, and
they said to merge it only if it earned a merge on its own merits. This file is
how it earns one, because the honest objection to the patch was never its
quality: **we have no proxy to point it at, so nothing here could be exercised,
and merging an unexercised branch into the module every upstream read passes
through is how a weather service acquires a new way to fail.**

So the test brings its own proxy. A minimal CONNECT-only SOCKS5 server runs in
a thread, a plain HTTP server sits behind it, and the fetch has to come back
through both. That turns "inert by default, trust me" into a claim with a
failing case.

**The positive control is the point.** The proxy counts the connections it
accepts, and the success test asserts that count is 1. Without it, a patch that
quietly ignored RUNEMAP_EGRESS_PROXY and dialled the origin directly would pass
every assertion here — the body would be right, the status would be right, and
the one thing under test would not have happened. That is the substitute-
instrument failure this repository keeps meeting, and it is cheap to prevent
here: make the proxy the only road to the answer, then check the odometer.

Not covered, and said rather than left to be assumed: **HTTPS through the
proxy.** It needs a TLS origin with a certificate the client will accept, and a
self-signed one would only prove that I disabled verification. The handshake
itself is scheme-independent and is covered; what is untested is the
`ctx.wrap_socket(raw, ...)` line. That is a real gap, it is written down, and
it is smaller than the gap of testing nothing.
"""
import os
import socket
import struct
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import net_budget as NB      # noqa: E402

BODY = b"through the proxy\n"


class _Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *a):
        pass


class _Socks5(threading.Thread):
    """CONNECT-only SOCKS5, enough to be a real counterparty.

    `fail_at` makes it misbehave on purpose, because a proxy that only ever
    works cannot show that the client checks anything.
    """

    daemon = True

    def __init__(self, fail_at=None, atyp=0x01):
        super().__init__()
        self.fail_at = fail_at
        self.atyp = atyp
        self.connections = 0            # the odometer
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = False

    def addr(self):
        return "127.0.0.1:%d" % self.port

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass

    def run(self):
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        try:
            n = c.recv(2)[1]
            c.recv(n)                                   # methods
            if self.fail_at == "auth":
                c.sendall(b"\x05\xff")                  # no acceptable method
                return
            if self.fail_at == "version":
                c.sendall(b"\x04\x00")
                return
            if self.fail_at == "hangup":
                c.close()
                return
            c.sendall(b"\x05\x00")

            hdr = c.recv(4)                             # ver cmd rsv atyp
            dlen = c.recv(1)[0]
            host = c.recv(dlen).decode()
            port = struct.unpack("!H", c.recv(2))[0]
            if self.fail_at == "refused":
                # Sends a FAILURE status and then tunnels correctly anyway.
                # That combination is what makes the test discriminating: a
                # client which skips the status check gets a working tunnel
                # and a 200, so the test can only pass if the status is
                # actually read. Firing it is what exposed the earlier
                # version -- there the proxy hung up after the failure reply,
                # so the request died of a closed socket and the test passed
                # whether or not anything checked the status. It was green for
                # a reason it did not claim.
                up = socket.create_connection((host, port), timeout=5)
                c.sendall(b"\x05\x05\x00\x01" + b"\x7f\x00\x00\x01" + b"\x00\x00")
                self._pump(c, up)
                return
            if self.fail_at == "atyp":
                c.sendall(b"\x05\x00\x00\x09" + b"\x00" * 4 + b"\x00\x00")
                return
            up = socket.create_connection((host, port), timeout=5)
            if self.atyp == 0x03:
                # A proxy is allowed to answer with a domain bind address; a
                # client that only handles IPv4 breaks against real proxies and
                # not against a convenient one.
                d = b"proxy.local"
                c.sendall(b"\x05\x00\x00\x03" + bytes([len(d)]) + d + b"\x00\x00")
            elif self.atyp == 0x04:
                c.sendall(b"\x05\x00\x00\x04" + b"\x00" * 16 + b"\x00\x00")
            else:
                c.sendall(b"\x05\x00\x00\x01" + b"\x7f\x00\x00\x01" + b"\x00\x00")
            self._pump(c, up)
        except Exception:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    @staticmethod
    def _pump(a, b):
        def one(src, dst):
            try:
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    dst.sendall(d)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.close()
                    except OSError:
                        pass
        threading.Thread(target=one, args=(a, b), daemon=True).start()
        one(b, a)


class Socks5Egress(unittest.TestCase):

    def setUp(self):
        self.origin = HTTPServer(("127.0.0.1", 0), _Origin)
        threading.Thread(target=self.origin.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/x" % self.origin.server_port
        self._was = NB._EGRESS_PROXY

    def tearDown(self):
        NB._EGRESS_PROXY = self._was
        self.origin.shutdown()
        self.origin.server_close()

    def _proxy(self, **kw):
        p = _Socks5(**kw)
        p.start()
        self.addCleanup(p.close)
        NB._EGRESS_PROXY = p.addr()
        return p

    def test_the_body_arrives_and_the_proxy_is_the_road_it_came_by(self):
        p = self._proxy()
        got = NB.get(self.url, budget=10)
        self.assertIn(BODY, got if isinstance(got, bytes) else got[1])
        # The whole test rests on this line: without it, a build that ignored
        # the proxy entirely would be indistinguishable from one that used it.
        self.assertEqual(p.connections, 1,
                         "the fetch succeeded without going through the proxy")

    def test_it_is_off_when_no_proxy_is_configured(self):
        """The negative control, and the property the merge actually depends
        on: with the variable unset, nothing about the existing path changes
        and no proxy is contacted."""
        p = _Socks5()
        p.start()
        self.addCleanup(p.close)
        NB._EGRESS_PROXY = ""
        got = NB.get(self.url, budget=10)
        self.assertIn(BODY, got if isinstance(got, bytes) else got[1])
        self.assertEqual(p.connections, 0)

    def test_a_domain_bind_address_is_handled(self):
        p = self._proxy(atyp=0x03)
        NB.get(self.url, budget=10)
        self.assertEqual(p.connections, 1)

    def test_an_ipv6_bind_address_is_handled(self):
        p = self._proxy(atyp=0x04)
        NB.get(self.url, budget=10)
        self.assertEqual(p.connections, 1)

    def _must_fail(self, **kw):
        self._proxy(**kw)
        with self.assertRaises(OSError):
            NB.get(self.url, budget=5)

    def test_a_proxy_refusing_every_auth_method_is_an_error(self):
        self._must_fail(fail_at="auth")

    def test_a_proxy_answering_the_wrong_version_is_an_error(self):
        self._must_fail(fail_at="version")

    def test_a_failed_connect_is_an_error_not_an_empty_body(self):
        """0x05 = connection refused by the proxy. The failure that would
        matter is this arriving as a successful empty response."""
        self._must_fail(fail_at="refused")

    def test_an_unknown_address_type_is_an_error(self):
        """NOT discriminating, and saying so rather than letting the green
        tick imply otherwise. Removing the atyp validation still fails this
        test -- but from the socket closing, not from the check. Making it
        discriminating means tunnelling after an unknown atyp, and then a
        client that skipped the check misparses the stream and errors anyway;
        every version I could construct passes for a reason it does not claim.

        It is kept because it pins the behaviour, and it is labelled because
        an unfired test counted as a fired one is how a suite starts
        overstating what it protects."""
        self._must_fail(fail_at="atyp")

    def test_a_proxy_that_hangs_up_mid_handshake_is_an_error(self):
        self._must_fail(fail_at="hangup")

    def test_an_unreachable_proxy_does_not_fall_back_to_a_direct_dial(self):
        """The one that would be worst in production and silent in testing:
        if egress is configured and the proxy is down, the request must FAIL,
        never quietly leave from our own address. The whole point of the
        setting is which IP the packet leaves from.

        The first version of this test accused the patch of exactly that bug
        and was wrong. It built a proxy, called close() on it, and assumed the
        port was dead -- but close() from another thread does not wake the
        accept() blocked on that fd, and the kernel goes on completing
        handshakes from the listen backlog. The "unreachable" proxy was
        answering. Five runs in six failed, and the accusation was against
        somebody else's code.

        So the premise is now MEASURED rather than assumed: find a port that
        actually refuses, and prove it refuses, before asking the client to
        fail against it. Checking that the ruler works before reporting what
        it measured -- the same rule that catches a shadow-ban that is really
        an unsigned request."""
        port = None
        for cand in range(9101, 9140):
            probe = socket.socket()
            probe.settimeout(0.3)
            try:
                probe.connect(("127.0.0.1", cand))
            except OSError:
                port = cand            # refused: this one is genuinely dead
                break
            finally:
                probe.close()
        if port is None:
            self.skipTest("no refusing port available to test against")
        NB._EGRESS_PROXY = "127.0.0.1:%d" % port
        with self.assertRaises(OSError):
            NB.get(self.url, budget=5)


if __name__ == "__main__":
    unittest.main()
