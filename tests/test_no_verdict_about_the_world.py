"""State 3 is deleted: nothing here may claim anything about the world.

bob 14:35: "no radar this means you did not get the radar. Nobody is going to
believe there is no radar just because you say so." That sentence removes the
reason the confirmation machinery existed -- it was there to earn the right to
say "this sky has no coverage", a claim about the world backed only by "I asked
three times and got nothing", which is a claim about me. So the verdict goes,
and with it the counter that had to be tuned, the memo, the .seen history file
and the observer effect my own probe produced on 8/3 12:4x.

What must SURVIVE the deletion is the cooldown. It looks like part of the
verdict but its job is throttling: a sky that just refused us must not be
re-asked once per request. Deleting it would spend upstream quota on exactly
the skies that never answer. Test 4 is that regression guard, and it is the one
test here that also passes against the old code -- on purpose.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, ".."))
import render_scene as R
import time

WX = {"realtime": {"skycon": "CLOUDY", "temperature": 20.0, "humidity": 0.5,
                   "wind": {"speed": 5.0},
                   "precipitation": {"local": {"intensity": 0.0}}},
      "forecast_keypoint": "no rain",
      "minutely": {"precipitation_2h": [0.0] * 120, "description": "no rain"}}

# Claims about the world, in the three languages we serve. None of these may
# ever reach a reader again, whatever the internal state is called.
WORLD_CLAIMS = ("no coverage", "coverage at this location", "\u30ec\u30fc\u30c0\u30fc\u570f\u5916",
                "\u65e0\u96f7\u8fbe\u8986\u76d6")


_CLEAR_NAMES = ("_RA_INFLIGHT", "_RA_FAIL", "_MO_CACHE", "_MO_BUSY")
_RESTORE_NAMES = ("_RA_FAIL_COOLDOWN",)
# The authority for "must not exist" -- deleted by bob 2026-08-03 14:35.
GONE_BY_DECREE = ("STATE_NONE", "_RA_NONE", "_RA_NONE_TTL", "_RA_NONE_CONFIRM",
                  "_RA_NONE_SPAN", "_RA_SEEN", "_sky_remember", "_sky_has_history",
                  "_sky_seen_path")

class Base(unittest.TestCase):
    def setUp(self):
        # getattr-guarded so this file runs both before and after the deletion.
        for n in _CLEAR_NAMES:
            getattr(R, n).clear()
        # Restore, do not just set: leaving a mutated module global is the
        # exact bug this suite was just caught having (see test_radar_states).
        for n in _RESTORE_NAMES:
            self.addCleanup(setattr, R, n, getattr(R, n))
            setattr(R, n, 0.0)
        self.calls = []
        self.pool = {}
        R._peek = lambda url: self.pool.get(url)
        R._get = self._failing_get()

    def _failing_get(self):
        def _get(url, timeout=15):
            self.calls.append(url)
            if "/radar/" in url:
                body = b'{"status": "failed"}'
                self.pool[url] = body
                return body
            self.pool[url] = b"PNG"
            return b"PNG"
        return _get


def _settle(timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and R._RA_INFLIGHT:
        time.sleep(0.02)


class NoVerdictAboutTheWorld(unittest.TestCase):
    def test_the_machinery_is_absent_not_merely_unused(self):
        # A missing capability outranks a guard (Luoshu): with no verdict at all,
        # no probe of mine or anyone else can manufacture one again.
        for gone in GONE_BY_DECREE:
            self.assertFalse(hasattr(R, gone), "%s still exists" % gone)

    def test_setup_does_not_tend_the_dead(self):
        # Luoshu 8/3 23:32: half sentinel, half fallback in one file is two
        # eras of it stacked. The setUp lists are the half that goes quiet --
        # hasattr skips a name that died and nothing reports it, so the guard
        # keeps performing a caution that no longer exists.
        for n in _CLEAR_NAMES + _RESTORE_NAMES:
            self.assertNotIn(n, GONE_BY_DECREE,
                             "%s was deleted by decree; setUp still tends it" % n)
            self.assertTrue(hasattr(R, n),
                            "%s is in setUp but absent from render_scene" % n)


class RepeatedFailuresStayAboutMe(Base):
    def test_ten_refusals_never_earn_a_verdict(self):
        for i in range(10):
            st, payload = R.radar_resolve("><", -140.0, -30.0, "T", wait=0.5)
            _settle()
            self.assertEqual(st, R.STATE_FETCHING, "refusal #%d became %r" % (i + 1, st))
            self.assertIsNone(payload)


class TheLineNeverClaimsCoverage(unittest.TestCase):
    def _line(self, lang):
        out = R.build(lang, "x", "XX", "x", 0.0, 0.0, 0, WX, None,
                      radar_state=R.STATE_FETCHING)
        hits = [l for l in out.split("\n") if l.startswith("radar: ")]
        self.assertEqual(len(hits), 1, hits)
        return hits[0]

    def test_no_world_claim_in_any_language(self):
        for lang in ("en", "zh", "ja"):
            l = self._line(lang)
            for bad in WORLD_CLAIMS:
                self.assertNotIn(bad, l, (lang, l))

    def test_english_says_no_radar(self):
        # bob picked the words: it is a statement about us, so it is always true.
        self.assertIn("no radar", self._line("en"))

    def test_token_is_still_greppable_and_untranslated(self):
        for lang in ("en", "zh", "ja"):
            self.assertTrue(self._line(lang).startswith("radar: fetching"), lang)


class ThrottleMustSurvive(Base):
    """The half that is NOT a verdict: do not re-ask a sky that just refused."""

    def test_a_just_refused_sky_is_not_re_asked_within_cooldown(self):
        R._RA_FAIL_COOLDOWN = 60.0
        R.radar_resolve("><", -140.0, -30.0, "T", wait=0.5)
        _settle()
        n = len(self.calls)
        for _ in range(15):
            st, _p = R.radar_resolve("><", -140.0, -30.0, "T", wait=0)
            self.assertEqual(st, R.STATE_FETCHING)
        self.assertEqual(len(self.calls), n, "cooldown gone: upstream hammered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
