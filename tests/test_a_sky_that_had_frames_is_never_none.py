"""A sky that has produced frames must never be memoised as "no coverage".

Measured in production 2026-08-03 09:19-09:42 (ops/evidence/): upstream went
regionally sick -- london, cairo and mumbai all answered
forecast_images=404 + images=200/status=failed/frames=0, byte-identically, for
12 straight minutes, while bangkok stayed ok/26. London had 26 frames on disk
at 09:23 and was still printing a map at 09:29. At 09:34 it began telling users
"none -- no coverage at this location", and kept saying it.

The confirmation window (3 failures over >=120s) is not the bug: it is what
made "never" cost something. The bug is that the counter has no memory of the
sky ever having worked, so a covered city that goes dark for four minutes gets
told it does not exist. The stale-cache window (TTL 300 x _STALE_MAX 6) delayed
it by 1800s -- luck, not design.

Coordinates here are 1.0/1.0 with bbox [0,0,1,1], the pair the existing suite
already renders, so a failure means the state machine, not my fake png.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import render_scene as R
from test_radar_states import Base, _settle
from test_empty_sky_is_cacheable import _png

GOOD = b'{"status": "ok", "images": [["u", "1", [0,0,1,1]]]}'
SICK = b'{"status": "failed"}'


class TestHistoryBeatsAnOutage(Base):
    KEY = (1.0, 1.0)

    def _serve(self, list_body):
        def _get(url, timeout=15):
            self.calls.append(url)
            if "/radar/" in url:
                self.pool[url] = list_body
                return list_body
            b = _png(223, 217, 200)     # real frame size, so PIL and numpy are not the failure
            self.pool[url] = b
            return b
        R._get = _get

    def test_frames_then_repeated_failure_is_never_none(self):
        self._serve(GOOD)                                  # 1. the sky works
        R.radar_resolve("><", 1.0, 1.0, "T", wait=0.6); _settle()
        self.assertNotIn(self.KEY, R._RA_FAIL, "a good answer left doubt behind")

        self._serve(SICK)                                  # 2. regional outage
        self.pool.clear()                                  # stale window closed
        for _ in range(R._RA_NONE_CONFIRM + 2):
            R.radar_resolve("><", 1.0, 1.0, "T", wait=0.6); _settle()

        self.assertNotIn(self.KEY, R._RA_NONE,
                         "a sky that produced frames was declared coverage-less")
        st, _ = R.radar_resolve("><", 1.0, 1.0, "T", wait=0)
        self.assertEqual(st, R.STATE_FETCHING,
                         "for a sky known to work, the answer is 'not yet'")

    def test_a_sky_with_no_history_can_still_earn_none(self):
        """The fix must not disarm the mechanism for genuinely uncovered skies."""
        self._serve(SICK)
        for _ in range(R._RA_NONE_CONFIRM):
            R.radar_resolve("><", -140.0, -30.0, "T", wait=0.6); _settle()
        st, _ = R.radar_resolve("><", -140.0, -30.0, "T", wait=0)
        self.assertEqual(st, R.STATE_NONE)


if __name__ == "__main__":
    unittest.main()
