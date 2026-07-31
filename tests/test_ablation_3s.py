"""Ablation for the wall (scripts/wall.py): same stalling upstream, old vs new path.

Acceptance 5 asks for reproduce -> fix -> ablate. The honest problem is that
the failure cannot be summoned on demand against the live upstream: sampled 10
cold coordinates while writing this and none exceeded 3s, because p95=4.01s is
an intermittent tail, not a steady state. Waiting for luck is not a proof.

So the ablation runs against a local upstream that reproduces what the real one
does when it misbehaves -- and specifically the part my own 7/30 outage proved I
must not omit: it echoes `Connection: close`, so http.client hands the socket to
the response and conn.sock becomes None. A mock that does not do that is a world
I invented, and 9/9 green against it is worth nothing.
"""
import http.server, json, os, socket, sys, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, ".."))
import render_scene as R
import net_budget
import wall as W

FRAMES = [["/f1.png", "1000", [0, 0, 1, 1]], ["/f2.png", "1600", [0, 0, 1, 1]]]


class Stalling(http.server.BaseHTTPRequestHandler):
    """Radar list answers instantly; the frames trickle forever."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if "/radar/" in self.path:
            body = json.dumps({"status": "ok", "images": FRAMES}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")   # the header that bit me
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", "100000")
        self.send_header("Connection", "close")
        self.end_headers()
        for _ in range(400):                          # 1 byte per 0.2s, forever
            try:
                self.wfile.write(b"\x00"); self.wfile.flush()
            except Exception:
                return
            time.sleep(0.2)


class Ablation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stalling)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        R._RA_INFLIGHT.clear(); R._RA_NONE.clear(); R._RA_FAIL.clear()
        R._MO_CACHE.clear(); R._MO_BUSY.clear()
        base = "http://127.0.0.1:%d" % self.port
        R._radar_list_url = lambda token, lng, lat: base + "/radar/images"
        self._orig_get = R._get

        def _local(url, timeout=15):
            # Hijack EVERY upstream, including the caiyun URL that radar_art
            # builds inline rather than through _radar_list_url. An earlier
            # version of this test only redirected the latter, so the "before"
            # case quietly hit the real API with a bogus token, got
            # {"status":"failed"} in 0.2s, and reported that the old path was
            # fast. A test that escapes to the real world proves nothing about
            # either world.
            if "caiyunapp.com" in url:
                url = base + "/radar/images"
            elif not url.startswith("http"):
                url = base + url
            return net_budget.get(url, budget=timeout)

        R._get = _local
        R._peek = lambda url: None          # nothing warm: this is the cold case
        self.addCleanup(setattr, R, "_get", self._orig_get)

    def test_old_path_blows_the_wall(self):
        """radar_art is the pre-patch shape: it fetches on the caller's thread."""
        t0 = time.time()
        with net_budget.request_budget(30):
            try:
                R.radar_art("><", 1.0, 1.0, "T")
            except Exception:
                pass          # the old path may raise or hang; both are failures
        el = time.time() - t0
        self.assertGreater(el, W.WALL,
                           "expected the old path to exceed the %.1fs wall, took %.2fs"
                           % (W.WALL, el))
        print("\n  old path (radar_art, fetches inline): %.2fs -- over the wall" % el)

    def test_new_path_holds_the_wall(self):
        t0 = time.time()
        with net_budget.request_budget(W.WALL):
            state, payload = R.radar_resolve("><", 2.0, 2.0, "T")
        el = time.time() - t0
        self.assertLess(el, W.WALL, "new path took %.2fs" % el)
        self.assertEqual(state, R.STATE_FETCHING)
        self.assertIsNone(payload)
        print("  new path (radar_resolve, warms off-thread): %.2fs, state=%s"
              % (el, state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
