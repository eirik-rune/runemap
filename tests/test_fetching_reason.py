# -*- coding: utf-8 -*-
"""Each `fetching` must name WHICH of its meanings it has -- and success must stay silent.

The instrument itself only proves the code can write a line. What has to be
proven is that the line names the RIGHT branch, and that a reader who got a map
produces no line at all: a diagnostic that fires on the healthy path would
retrain me to ignore it. Five positive controls, one negative, no sockets --
_peek is stubbed, so nothing here touches the upstream or the disk pool.
"""
import io
import sys
import threading
import time
import unittest

sys.path.insert(0, "scripts")
import render_scene as RS


class FetchingReason(unittest.TestCase):
    def setUp(self):
        self._save = {k: getattr(RS, k) for k in
                      ("_peek", "_radar_render", "_radar_start", "_mark")}
        RS._mark = lambda c: c
        RS._radar_start = lambda *a, **k: threading.Event()
        RS._radar_render = lambda *a, **k: "MAP"
        with RS._RA_LOCK:
            RS._RA_FAIL.clear()

    def tearDown(self):
        for k, v in self._save.items():
            setattr(RS, k, v)
        with RS._RA_LOCK:
            RS._RA_FAIL.clear()

    def _run(self, lat=1.5, lng=2.5):
        err = io.StringIO()
        keep, sys.stderr = sys.stderr, err
        try:
            state, payload = RS.radar_resolve("x", lng, lat, "tok", wait=0.0)
        finally:
            sys.stderr = keep
        lines = [l for l in err.getvalue().splitlines() if "FETCHING-REASON" in l]
        return state, payload, lines

    def _reason(self, lines):
        self.assertEqual(len(lines), 1, "expected exactly one line, got %r" % lines)
        return dict(t.split("=", 1) for t in lines[0].split()[1:])["reason"]

    def test_list_read_with_no_carrier_word_says_nopeek(self):
        # A bare stub never calls _cached_peek, so no carrier word is left behind and
        # the reason must name THAT, not a cache miss. render_scene.py:829 names this
        # path in advance. Was "list-miss" until 81006e02 split the word; the rename
        # never reached this file, so the assert nailed a word the code cannot emit.
        RS._peek = lambda url: None
        st, _, lines = self._run()
        self.assertEqual(st, RS.STATE_FETCHING)
        self.assertEqual(self._reason(lines), "list-nopeek")

    def test_a_carrier_word_survives_to_the_reason(self):
        # The point of 81006e02 was that four empty reads are four different facts.
        # If anyone re-collapses them, this goes red: the carrier word must arrive.
        RS._peek = lambda url: (RS.note_peek_miss("nofile"), None)[1]
        st, _, lines = self._run()
        self.assertEqual(st, RS.STATE_FETCHING)
        self.assertEqual(self._reason(lines), "list-nofile")

    def test_list_unparseable(self):
        RS._peek = lambda url: "{"
        st, _, lines = self._run()
        self.assertEqual(st, RS.STATE_FETCHING)
        self.assertEqual(self._reason(lines), "list-unparseable")

    def test_sky_empty(self):
        RS._peek = lambda url: '{"images": []}'
        st, _, lines = self._run()
        self.assertEqual(st, RS.STATE_FETCHING)
        self.assertEqual(self._reason(lines), "sky-empty")

    def test_render_failed(self):
        RS._peek = lambda url: '{"images": ["a", "b"]}'
        RS._radar_render = lambda *a, **k: None
        st, _, lines = self._run()
        self.assertEqual(st, RS.STATE_FETCHING)
        self.assertEqual(self._reason(lines), "render-failed")

    def test_cooldown(self):
        RS._peek = lambda url: None
        with RS._RA_LOCK:
            RS._RA_FAIL[(1.5, 2.5)] = time.time()
        st, _, lines = self._run()
        self.assertEqual(st, RS.STATE_FETCHING)
        self.assertEqual(self._reason(lines), "cooldown")

    def test_success_is_silent(self):
        RS._peek = lambda url: '{"images": ["a"]}'
        st, payload, lines = self._run()
        self.assertEqual(st, RS.STATE_OK)
        self.assertEqual(payload, "MAP")
        self.assertEqual(lines, [], "a diagnostic that fires on the healthy path is noise")

    def test_reasons_are_distinct(self):
        """Five branches must not collapse into fewer strings -- that is the bug being fixed."""
        seen = set()
        for peek, render in (("N", "MAP"), ("{", "MAP"), ('{"images": []}', "MAP"),
                             ('{"images": ["a"]}', None)):
            RS._peek = (lambda url: None) if peek == "N" else (lambda url, p=peek: p)
            RS._radar_render = (lambda *a, **k: None) if render is None else (lambda *a, **k: "MAP")
            seen.add(self._reason(self._run()[2]))
        self.assertEqual(len(seen), 4, "reasons collapsed: %r" % sorted(seen))


if __name__ == "__main__":
    unittest.main(verbosity=2)
