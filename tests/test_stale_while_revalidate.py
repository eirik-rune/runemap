"""Serving a stale entry must also schedule its refresh.

Before this test, _cached_peek did only the first half: a list past its TTL was
served over and over for up to _STALE_MAX x TTL while nothing asked upstream.
The observation timestamp we print comes from that list, so it froze while the
wall clock ran on -- measured 8/2: 19 of 24 servable lists were past TTL, and
re-fetching moved the observation forward by 5-18 minutes.

Every patch below gets its addCleanup on the very next line: a leaked
monkeypatch does not fail in its own file, it fails in whichever test discover
happens to run next.
"""
import json, os, sys, tempfile, threading, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import scene_at as SA


def _list_body(n=3):
    now = time.time()
    return json.dumps({"status": "ok",
                       "images": [["http://x/%d.png" % i, now - 300 * i, [0, 0, 1, 1]]
                                  for i in range(n)]}).encode()


class StaleWhileRevalidate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="swr_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.old_cache = SA.CACHE
        self.addCleanup(setattr, SA, "CACHE", self.old_cache)
        SA.CACHE = self.dir
        self.calls = []
        self.fetched = threading.Event()
        self.old_get = SA._orig_get
        self.addCleanup(setattr, SA, "_orig_get", self.old_get)

        def fake(url, timeout):
            self.calls.append(url)
            self.fetched.set()
            return _list_body()
        SA._orig_get = fake
        with SA._SWR_LOCK:
            SA._SWR_INFLIGHT.clear()
        self.addCleanup(SA._SWR_INFLIGHT.clear)

    def _plant(self, url, kind, age):
        import hashlib
        p = os.path.join(self.dir, hashlib.sha1(SA._ckey(url).encode()).hexdigest() + "." + kind)
        open(p, "wb").write(_list_body())
        os.utime(p, (time.time() - age, time.time() - age))
        return p

    def test_past_ttl_entry_is_served_and_refreshed(self):
        url = "https://api.example/v1/radar/forecast_images?token=t&lon=1&lat=2"
        self._plant(url, "radar_json", SA._TTL["radar_json"] * 2)   # stale, still servable
        got = SA._cached_peek(url)
        self.assertIsNotNone(got, "a stale-but-servable entry must still be served")
        self.assertTrue(self.fetched.wait(5), "serving a stale entry must schedule a refresh")
        self.assertEqual(self.calls, [url])

    def test_fresh_entry_is_not_refreshed(self):
        url = "https://api.example/v1/radar/forecast_images?token=t&lon=3&lat=4"
        self._plant(url, "radar_json", 1)
        self.assertIsNotNone(SA._cached_peek(url))
        self.assertFalse(self.fetched.wait(0.5), "a fresh entry must not hit upstream")

    def test_png_is_never_refreshed(self):
        url = "http://cdn.example/frames/2026/0802/1230.png"
        import hashlib
        p = os.path.join(self.dir, hashlib.sha1(SA._ckey(url).encode()).hexdigest() + ".png")
        open(p, "wb").write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IEND\xae\x42\x60\x82")
        old = time.time() - SA._TTL["png"] * 2
        os.utime(p, (old, old))
        self.assertIsNotNone(SA._cached_peek(url), "stale png still servable")
        self.assertFalse(self.fetched.wait(0.5),
                         "a timestamped png is immutable: refetching buys nothing")


if __name__ == "__main__":
    unittest.main()
