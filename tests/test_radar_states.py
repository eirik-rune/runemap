"""Three radar states: proven, not inferred; and one fetch per sky.

Everything here is offline. The one thing these tests must not do is what my
Connection: close bug did on 7/30 -- pass 9/9 against a world I invented. So
the fakes below reproduce the two upstream behaviours that actually bit us:
a list call that raises, and a list call that succeeds with zero images.
"""
import json, os, sys, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, ".."))
import render_scene as R


class Base(unittest.TestCase):
    def setUp(self):
        R._RA_INFLIGHT.clear()
        R._RA_NONE.clear()
        R._RA_FAIL.clear()
        R._RA_NONE_SPAN = 0.0        # the real one is 120s; shrink, do not skip
        R._RA_FAIL_COOLDOWN = 0.0
        R._MO_CACHE.clear()
        R._MO_BUSY.clear()
        self.calls = []
        self.pool = {}
        R._peek = lambda url: self.pool.get(url)

    def _get_factory(self, list_body=None, raises=None, delay=0.0):
        def _get(url, timeout=15):
            self.calls.append(url)
            if delay:
                time.sleep(delay)
            if raises is not None and "/radar/" in url:
                raise raises
            if "/radar/" in url:
                self.pool[url] = list_body
                return list_body
            self.pool[url] = b"PNG"
            return b"PNG"
        return _get


def _settle(timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and R._RA_INFLIGHT:
        time.sleep(0.02)


class TestStateThreeIsEarned(Base):
    def test_one_empty_answer_is_not_yet_none(self):
        """Measured: the upstream says {"status":"failed"} for open ocean AND,
        per scene_at._usable's incident note, transiently for covered cities.
        One ambiguous refusal must never become "never come back"."""
        R._get = self._get_factory(list_body=b'{"status": "failed"}')
        st, payload = R.radar_resolve("><", -140.0, -30.0, "T", wait=2.0)
        self.assertEqual(st, R.STATE_FETCHING)
        self.assertIsNone(payload)
        self.assertEqual(R._RA_NONE, {})

    def test_repeated_refusal_earns_none(self):
        R._get = self._get_factory(list_body=b'{"status": "failed"}')
        for _ in range(R._RA_NONE_CONFIRM):
            R.radar_resolve("><", -140.0, -30.0, "T", wait=0.5)
            _settle()
        st, _ = R.radar_resolve("><", -140.0, -30.0, "T", wait=0)
        self.assertEqual(st, R.STATE_NONE)

    def test_a_refusal_then_frames_forgets_the_doubt(self):
        """A covered city that blipped must not accumulate toward "never"."""
        R._get = self._get_factory(list_body=b'{"status": "failed"}')
        R.radar_resolve("><", 1.0, 1.0, "T", wait=0.5); _settle()
        self.assertIn((1.0, 1.0), R._RA_FAIL)
        R._get = self._get_factory(
            list_body=b'{"status": "ok", "images": [["u", "1", [0,0,1,1]]]}')
        R.radar_resolve("><", 1.0, 1.0, "T", wait=0.5); _settle()
        self.assertNotIn((1.0, 1.0), R._RA_FAIL, "doubt survived a good answer")

    def test_list_failure_is_never_none(self):
        """The bug this whole job exists for: a stall used to print
        'no coverage here', telling a caller 'never' when the truth was
        'not yet'. It must be state 2 no matter how the fetch failed."""
        for exc in (OSError("stall"), ValueError("garbage"), TimeoutError()):
            with self.subTest(exc=type(exc).__name__):
                self.setUp()
                R._get = self._get_factory(raises=exc)
                st, _ = R.radar_resolve("><", 116.39, 39.93, "T", wait=0.6)
                self.assertEqual(st, R.STATE_FETCHING)
                self.assertNotIn((round(39.93, 1), round(116.39, 1)), R._RA_NONE)

    def test_none_is_memoised_without_refetch(self):
        R._get = self._get_factory(list_body=b'{"status": "failed"}')
        for _ in range(R._RA_NONE_CONFIRM):
            R.radar_resolve("><", -140.0, -30.0, "T", wait=0.5)
            _settle()
        self.assertEqual(R.radar_resolve("><", -140.0, -30.0, "T", wait=0)[0],
                         R.STATE_NONE)
        n = len(self.calls)
        for _ in range(20):
            st, _ = R.radar_resolve("><", -140.0, -30.0, "T", wait=0)
            self.assertEqual(st, R.STATE_NONE)
        self.assertEqual(len(self.calls), n, "no-coverage must not re-query")


class TestSingleFlight(Base):
    def test_sixty_requests_one_fetch(self):
        """Acceptance 6. The old motion pattern checked a set without a lock,
        so N concurrent callers each spawned a fetch."""
        R._get = self._get_factory(list_body=b'{"status": "failed"}', delay=0.25)
        out = []
        def hit():
            out.append(R.radar_resolve("><", 10.0, 10.0, "T", wait=0)[0])
        ts = [threading.Thread(target=hit) for _ in range(60)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        radar_calls = [c for c in self.calls if "/radar/" in c]
        self.assertEqual(len(radar_calls), 1,
                         "60 callers produced %d upstream fetches" % len(radar_calls))
        self.assertEqual(len(out), 60)


class TestUserPathNeverFetches(Base):
    def test_resolve_makes_no_call_on_this_thread(self):
        """The 3s wall is structural only if the caller has no socket at all."""
        me = threading.current_thread()
        seen = []
        def _get(url, timeout=15):
            seen.append(threading.current_thread() is me)
            self.pool[url] = b'{"status": "failed"}' if "/radar/" in url else b"PNG"
            return self.pool[url]
        R._get = _get
        R.radar_resolve("><", 20.0, 20.0, "T", wait=1.0)
        self.assertTrue(seen, "expected the background warm to fetch")
        self.assertNotIn(True, seen, "an upstream fetch ran on the request thread")

    def test_returns_fast_when_upstream_hangs(self):
        R._get = self._get_factory(list_body=b'{"status": "failed"}', delay=5.0)
        t0 = time.time()
        st, _ = R.radar_resolve("><", 30.0, 30.0, "T", wait=0.4)
        el = time.time() - t0
        self.assertEqual(st, R.STATE_FETCHING)
        self.assertLess(el, 1.0, "waited %.2fs on a hung upstream" % el)


class TestFetchingBecomesOk(Base):
    def test_background_fills_and_next_caller_gets_it(self):
        """State 2 promises 'ask again in ~60s'. That is only true if something
        keeps fetching after the response goes out."""
        imgs = [["https://cdn/f1.png", "1000", [0, 0, 1, 1]],
                ["https://cdn/f2.png", "1600", [0, 0, 1, 1]]]
        body = json.dumps({"images": imgs}).encode()
        R._get = self._get_factory(list_body=body, delay=0.2)
        # Mirror the real contract: the first candidate frame that is on disk
        # wins. An earlier version of this fake demanded both frames, which is
        # stricter than the code -- a test that fails for a reason the product
        # does not have is just a slower way to be wrong.
        R._radar_render = lambda code, lng, lat, i, small: (
            ("ART", 10.0, 1600.0, {"kind": None})
            if any(f[0] in self.pool for f in i[-2:] if f) else None)
        st, _ = R.radar_resolve("><", 40.0, 40.0, "T", wait=0)
        self.assertEqual(st, R.STATE_FETCHING)
        deadline = time.time() + 5
        while time.time() < deadline and R._RA_INFLIGHT:
            time.sleep(0.05)   # wait for the background warm to finish
        st2, payload = R.radar_resolve("><", 40.0, 40.0, "T", wait=0)
        self.assertEqual(st2, R.STATE_OK)
        self.assertEqual(payload[0], "ART")


class TestInflightAlwaysReleased(Base):
    def test_crash_in_warm_does_not_wedge_the_key(self):
        """A key left marked in-flight is a sky that silently never leaves
        state 2 again -- and nothing in the output would say so."""
        R._get = self._get_factory(raises=OSError("boom"))
        R.radar_resolve("><", 50.0, 50.0, "T", wait=0.5)
        deadline = time.time() + 3
        while time.time() < deadline and R._RA_INFLIGHT:
            time.sleep(0.05)
        self.assertEqual(R._RA_INFLIGHT, {}, "in-flight entry leaked after a failure")


class CooldownShortensTheWait(unittest.TestCase):
    """A sky that just refused us is not worth the full budget.

    Raising the wall to 10s bought one thing: a cold sky can now finish its
    list+frame fetch while the reader is still here. Against a *broken*
    upstream that same budget buys nothing -- the ablation measures 6.25s and
    still answers "fetching", six seconds spent to say what we knew at once.

    So the fail counter is load-bearing beyond state 3: the first reader pays
    full price to find out the sky is refusing, and for the next 30s everyone
    else pays 1.5s. Without this the wall change would make a broken upstream
    six times more expensive for readers than it was under the 3s wall.
    """

    def setUp(self):
        for d in (R._RA_INFLIGHT, R._RA_NONE, R._RA_FAIL):
            d.clear()

    def test_cooling_sky_waits_the_short_budget(self):
        import wall as W
        key = (1.0, 1.0)
        with R._RA_LOCK:
            R._RA_FAIL[key] = [1, time.time(), time.time()]
        self.assertEqual(W.radar_wait(cooling=True, left=None),
                         W.RADAR_WAIT_COOLDOWN)
        self.assertGreater(W.radar_wait(cooling=False, left=None),
                           W.radar_wait(cooling=True, left=None),
                           "an unknown sky must be worth more waiting than a "
                           "refusing one, or the cooldown does nothing")

    def test_no_wait_may_outlast_the_wall(self):
        import wall as W
        for left in (W.WALL, 1.0, 0.3, 0.0):
            for cooling in (False, True):
                w = W.radar_wait(cooling=cooling, left=left)
                self.assertLessEqual(w, max(0.0, left - W.RESERVE) + 1e-9,
                                     "wait %.2f with %.2f left leaves nothing "
                                     "for rendering" % (w, left))


if __name__ == "__main__":
    unittest.main(verbosity=2)


