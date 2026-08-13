"""The fallback must be invisible until it is needed, and named when it is used.

Hermetic: no network. What is being pinned here is the wiring and the credit,
not RainViewer -- the geometry has its own tests.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import render_scene as RS      # noqa: E402

WX = {"realtime": {"temperature": 27.0, "skycon": "RAIN", "humidity": 0.9,
                   "wind": {"speed": 10, "direction": 200}, "pressure": 100000,
                   "apparent_temperature": 29.0,
                   "precipitation": {"local": {"intensity": 0.3}},
                   "air_quality": {"aqi": {"chn": 40}}}}
ART = "\n".join(["." * 48] * 24)


def body(rb):
    return RS.build("en", "mumbai", "RAIN", "mumbai", 72.88, 19.08, 6, WX, rb)


class TheCreditFollowsWhoDrewIt(unittest.TestCase):

    def test_a_map_from_the_fallback_names_the_fallback(self):
        rb = (ART, 12.0, 1.0, None, 1.0, "RainViewer")
        b = body(rb)
        self.assertIn("radar-data: RainViewer rainviewer.com", b)

    def test_a_map_from_the_primary_carries_no_second_credit(self):
        """Absence is information here: it says the primary drew this one.

        This is the negative control for the test above -- without it, a build
        that always printed the credit would pass.
        """
        rb = (ART, 12.0, 1.0, None, 1.0)
        self.assertNotIn("radar-data:", body(rb))

    def test_the_credit_does_not_reuse_the_state_token(self):
        """An agent greps ^radar: for the state. A second line starting the
        same way would make the state ambiguous to every parser we have."""
        b = body((ART, 12.0, 1.0, None, 1.0, "RainViewer"))
        starts = [l for l in b.split("\n") if l.startswith("radar:")]
        self.assertEqual(len(starts), 1, starts)

    def test_an_unknown_source_is_still_credited_by_name(self):
        b = body((ART, 12.0, 1.0, None, 1.0, "SomeNewSource"))
        self.assertIn("radar-data: SomeNewSource", b)


class TheFallbackIsOffAndCannotThrowIntoTheReader(unittest.TestCase):

    def setUp(self):
        self._was = RS.SECOND_SOURCE

    def tearDown(self):
        RS.SECOND_SOURCE = self._was

    def test_off_by_default_means_not_consulted(self):
        RS.SECOND_SOURCE = ""
        self.assertIsNone(RS._second_source("><", 72.88, 19.08, False))

    def test_an_unknown_name_is_not_an_exception(self):
        RS.SECOND_SOURCE = "no-such-source"
        self.assertIsNone(RS._second_source("><", 72.88, 19.08, False))

    def test_a_fallback_that_explodes_degrades_to_none(self):
        """A broken fallback must cost the reader the sentence they already
        had, never a 500. Fire-tested by making it explode on purpose."""
        RS.SECOND_SOURCE = "rainviewer"
        import radar_second
        orig = radar_second.draw
        radar_second.draw = lambda *a, **k: (_ for _ in ()).throw(IOError("boom"))
        try:
            self.assertIsNone(RS._second_source("><", 72.88, 19.08, False))
        finally:
            radar_second.draw = orig

    def test_a_fallback_that_works_is_passed_through_unchanged(self):
        RS.SECOND_SOURCE = "rainviewer"
        import radar_second
        orig = radar_second.draw
        want = (ART, 12.0, 1.0, None, 1.0, "RainViewer")
        radar_second.draw = lambda *a, **k: want
        try:
            self.assertEqual(RS._second_source("><", 72.88, 19.08, False), want)
        finally:
            radar_second.draw = orig


class TheSourceRefusesToLieAboutFreshness(unittest.TestCase):

    def test_a_frame_older_than_the_limit_is_refused(self):
        import radar_second as S
        old = {"host": "h", "radar": {"past": [{"time": 1, "path": "/p"}]}}
        was = S._INDEX.copy()
        S._INDEX["at"], S._INDEX["v"] = 9e18, old   # far future: never refresh
        try:
            self.assertEqual(S.newest_frame(), (None, None))
        finally:
            S._INDEX.update(was)



class TheChainTriesInOrderAndFallsThrough(unittest.TestCase):
    """Order encodes a judgement about data: a national radar beats a global
    composite over the country that owns it, and declines everywhere else."""

    def setUp(self):
        self._was = RS.SECOND_SOURCE
        import radar_redemet, radar_second
        self._r, self._s = radar_redemet.draw, radar_second.draw

    def tearDown(self):
        RS.SECOND_SOURCE = self._was
        import radar_redemet, radar_second
        radar_redemet.draw, radar_second.draw = self._r, self._s

    def _stub(self, first, second):
        import radar_redemet, radar_second
        radar_redemet.draw = lambda *a, **k: first
        radar_second.draw = lambda *a, **k: second

    def test_the_first_that_answers_wins(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        a = (ART, 12.0, 1.0, None, 1.0, "REDEMET/DECEA")
        b = (ART, 12.0, 2.0, None, 2.0, "RainViewer")
        self._stub(a, b)
        self.assertEqual(RS._second_source("><", -46.63, -23.55, False)[5],
                         "REDEMET/DECEA")

    def test_a_decline_falls_through_to_the_next(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        b = (ART, 12.0, 2.0, None, 2.0, "RainViewer")
        self._stub(None, b)
        self.assertEqual(RS._second_source("><", 72.88, 19.08, False)[5], "RainViewer")

    def test_one_adapter_exploding_does_not_take_the_chain_with_it(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        b = (ART, 12.0, 2.0, None, 2.0, "RainViewer")
        import radar_redemet, radar_second
        radar_redemet.draw = lambda *a, **k: (_ for _ in ()).throw(IOError("boom"))
        radar_second.draw = lambda *a, **k: b
        self.assertEqual(RS._second_source("><", 72.88, 19.08, False)[5], "RainViewer")

    def test_all_declining_is_none_not_an_empty_map(self):
        RS.SECOND_SOURCE = "redemet,rainviewer"
        self._stub(None, None)
        self.assertIsNone(RS._second_source("><", 0.0, 0.0, False))

if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheCooldownPathAsksToo(unittest.TestCase):
    """A sky whose last ask got nothing spends most of its life in the cooldown
    branch, which returned before the fallback was ever consulted. Measured in
    production: two probes a second apart, one drew and one did not."""

    def test_every_no_map_return_consults_the_second_source(self):
        # Structural, not a byte distance. The first version looked 700
        # characters back for the call, and four lines of budget comment above
        # one return broke it while the code was still correct. A ruler whose
        # unit is "how much prose fits between two statements" measures the
        # prose. So: cut the function at its returns and require the fallback
        # to be consulted somewhere in the stretch leading to each no-map one.
        import re
        src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                                "render_scene.py"), encoding="utf-8").read()
        body = src[src.index("def radar_resolve("):src.index("_WX_LOCK = threading.Lock()")]
        cuts = [m.start() for m in re.finditer(r"\n    return ", body)]
        returns = [m.start() for m in re.finditer(r"return STATE_FETCHING, None", body)]
        self.assertTrue(returns, "no such return: this guard has lost its subject")
        for at in returns:
            # `\n    return ` matches this very return too (five characters
            # earlier), so its own cut has to be excluded or the segment is
            # empty and the guard fails on itself.
            prev = max([c for c in cuts if at - c > 6] or [0])
            self.assertIn("_second_source(", body[prev:at],
                          "a 'no map' return with no fallback consulted on the "
                          "way to it: the reader on this path gets a sentence "
                          "while another path gets rain")


class TheCreditIsDerivedNotRestated(unittest.TestCase):
    """Finland drew correctly and was credited as a bare "FMI", because the
    credit line was a second hand-maintained copy of what each adapter already
    declares. A duplicated table does not fail when it falls behind; it
    under-credits somebody whose data we are using."""

    def test_every_shipped_wms_service_credits_itself(self):
        import radar_wms
        for s in radar_wms.SERVICES:
            self.assertEqual(RS._second_attrib(s["name"]), s["attrib"], s["key"])

    def test_the_file_based_adapters_credit_themselves_too(self):
        import radar_redemet, radar_second
        for m in (radar_redemet, radar_second):
            self.assertEqual(RS._second_attrib(m.NAME), m.ATTRIB, m.NAME)

    def test_an_unknown_source_falls_back_to_its_own_name(self):
        """Never blank, never someone else's: an unnamed source is still named."""
        self.assertEqual(RS._second_attrib("SomeNewSource"), "SomeNewSource")

    def test_the_body_prints_the_full_credit_for_a_wms_source(self):
        import radar_wms
        s = next(x for x in radar_wms.SERVICES if x["key"] == "fi-fmi")
        b = body((ART, 12.0, 1.0, None, 1.0, s["name"]))
        self.assertIn("radar-data: " + s["attrib"], b)


class AStaleFrameLosesToAFresherRadar(unittest.TestCase):
    """The hour Germany shipped, Berlin was served a 46-minute-old frame,
    correctly labelled stale, while a 0-minute German radar frame sat one call
    away. "Has a frame" and "has a frame worth showing" are different
    questions, and answering the first served the older sky on purpose."""

    def setUp(self):
        self._was = RS._second_source

    def tearDown(self):
        RS._second_source = self._was

    def _hit(self, age_min):
        import time
        ts = time.time() - age_min * 60
        return (RS.STATE_OK, (ART, 12.0, ts, None, ts))

    def _second(self, age_min, name="DWD"):
        import time
        ts = time.time() - age_min * 60
        RS._second_source = lambda *a, **k: (ART, 12.0, ts, None, ts, name)

    def test_a_fresh_primary_never_asks(self):
        asked = []
        RS._second_source = lambda *a, **k: asked.append(1)
        got = RS._fresher_of(self._hit(3), "><", 13.4, 52.5, False)
        self.assertEqual(asked, [], "the fast path must not pay for this")
        self.assertEqual(len(got[1]), 5)

    def test_a_stale_primary_yields_to_a_fresher_source(self):
        self._second(0)
        got = RS._fresher_of(self._hit(46), "><", 13.4, 52.5, False)
        self.assertEqual(got[1][5], "DWD")

    def test_a_stale_primary_keeps_its_map_if_the_second_is_older(self):
        """The control that stops this from becoming 'the fallback always
        wins': older is older, whoever it belongs to."""
        self._second(90)
        got = RS._fresher_of(self._hit(46), "><", 13.4, 52.5, False)
        self.assertEqual(len(got[1]), 5, "we took an older frame")

    def test_no_second_source_leaves_the_reader_their_map(self):
        RS._second_source = lambda *a, **k: None
        got = RS._fresher_of(self._hit(46), "><", 13.4, 52.5, False)
        self.assertEqual(len(got[1]), 5)

    def test_a_comparison_that_throws_costs_the_reader_nothing(self):
        RS._second_source = lambda *a, **k: (_ for _ in ()).throw(IOError("boom"))
        got = RS._fresher_of(self._hit(46), "><", 13.4, 52.5, False)
        self.assertEqual(len(got[1]), 5)


class NamingTheSourceIsNotTheWholeObligation(unittest.TestCase):
    """Eirik read DWD's licence pages after Germany shipped: their template
    (vorlagen_quellenangabe.html, section 7 DWD-Gesetz) requires a source note
    even for a change of data format, and CC BY 4.0 separately requires that
    changes be indicated. We had the mention and not the change notice."""

    def test_dwd_is_credited_in_the_form_its_licence_asks_for(self):
        import radar_wms
        s = next(x for x in radar_wms.SERVICES if x["key"] == "de-dwd-wn")
        self.assertIn("Deutscher Wetterdienst", s["attrib"])
        self.assertIn("veraendert", s["attrib"])

    def test_every_drawn_map_says_it_was_redrawn(self):
        for name in ("DWD", "FMI", "RainViewer", "REDEMET/DECEA"):
            b = body((ART, 12.0, 1.0, None, 1.0, name))
            self.assertIn("radar-data-note: redrawn", b, name)

    def test_a_primary_map_carries_no_note(self):
        """Absence stays informative: the primary drew this one, and we make no
        claim about somebody else's licence on it."""
        self.assertNotIn("radar-data-note", body((ART, 12.0, 1.0, None, 1.0)))

    def test_the_note_has_its_own_token(self):
        b = body((ART, 12.0, 1.0, None, 1.0, "DWD"))
        self.assertEqual(len([l for l in b.split("\n") if l.startswith("radar:")]), 1)
        self.assertEqual(len([l for l in b.split("\n")
                              if l.startswith("radar-data:")]), 1)

    def test_both_lines_fit_the_width_budget(self):
        import unicodedata
        cells = lambda s: sum(2 if unicodedata.east_asian_width(c) in ("W", "F")
                              else 1 for c in s)
        import radar_wms
        for s in radar_wms.SERVICES:
            b = body((ART, 12.0, 1.0, None, 1.0, s["name"]))
            for line in b.split("\n"):
                if line.startswith("radar-data"):
                    self.assertLessEqual(cells(line), 79, line)


class JapanIsInTheChainAndCreditsItself(unittest.TestCase):

    def setUp(self):
        self._was = RS.SECOND_SOURCE

    def tearDown(self):
        RS.SECOND_SOURCE = self._was

    def test_the_chain_knows_the_name_jma(self):
        RS.SECOND_SOURCE = "jma"
        import radar_jma
        orig = radar_jma.draw
        want = (ART, 8.0, 1.0, None, 1.0, "JMA")
        radar_jma.draw = lambda *a, **k: want
        try:
            self.assertEqual(RS._second_source("><", 139.69, 35.69, False), want)
        finally:
            radar_jma.draw = orig

    def test_its_credit_comes_from_the_adapter_not_a_second_table(self):
        import radar_jma
        self.assertEqual(RS._second_attrib(radar_jma.NAME), radar_jma.ATTRIB)

    def test_the_body_prints_source_and_change_notice(self):
        b = body((ART, 8.0, 1.0, None, 1.0, "JMA"))
        self.assertIn("radar-data: Japan Meteorological Agency jma.go.jp", b)
        self.assertIn("radar-data-note: redrawn", b)


class TheUpgradeMustNotCostTheReaderTheirTime(unittest.TestCase):
    """Shipped without this and measured it on production: mean probe latency
    0.96s -> 1.66s, p99 6.7s, 9.3% of probes over the 3s product line against
    4.1% the day before. The reader already holds a map; buying them a fresher
    one with an upstream round trip is a trade nobody asked for -- and
    radar_resolve's own docstring says this thread opens no socket."""

    def setUp(self):
        self._was = RS._second_source
        self._warm = RS._warm_second
        RS._WARMING.clear()

    def tearDown(self):
        RS._second_source = self._was
        RS._warm_second = self._warm

    def _hit(self, age_min):
        import time
        ts = time.time() - age_min * 60
        return (RS.STATE_OK, (ART, 12.0, ts, None, ts))

    def test_the_upgrade_asks_for_cache_only(self):
        seen = {}

        def spy(c, x, y, s, cached_only=False):
            seen["flag"] = cached_only
            return None          # None, not the flag: a stub that returns a
            # bool makes the caller log a TypeError, and a fake error line in
            # the logs is how real ones get ignored.
        RS._second_source = spy
        RS._warm_second = lambda *a, **k: None
        RS._fresher_of(self._hit(46), "><", 13.4, 52.5, False)
        self.assertIs(seen.get("flag"), True)

    def test_a_cache_miss_warms_for_the_next_reader(self):
        warmed = []
        RS._second_source = lambda *a, **k: None
        RS._warm_second = lambda *a, **k: warmed.append(1)
        got = RS._fresher_of(self._hit(46), "><", 13.4, 52.5, False)
        self.assertEqual(len(got[1]), 5, "the reader kept their own map")
        self.assertEqual(warmed, [1])

    def test_a_fresh_primary_neither_asks_nor_warms(self):
        warmed = []
        RS._second_source = lambda *a, **k: self.fail("asked on the fast path")
        RS._warm_second = lambda *a, **k: warmed.append(1)
        RS._fresher_of(self._hit(3), "><", 13.4, 52.5, False)
        self.assertEqual(warmed, [])

    def test_the_warm_does_not_stampede(self):
        calls = []
        RS._second_source = lambda *a, **k: calls.append(1)
        RS._warm_second(">< ", 13.4, 52.5, False)
        RS._warm_second(">< ", 13.4, 52.5, False)
        RS._warm_second(">< ", 13.4, 52.5, False)
        for t in __import__("threading").enumerate():
            if t.name == "second-warm":
                t.join(5)
        self.assertEqual(len(calls), 1, "every reader of a stale sky started "
                                        "their own fetch")


class AdaptersHonourTheNoNetworkFlag(unittest.TestCase):

    def test_every_adapter_accepts_it(self):
        import inspect
        import radar_jma, radar_redemet, radar_second, radar_wms
        for m in (radar_jma, radar_redemet, radar_second, radar_wms):
            sig = inspect.signature(m.draw)
            self.assertIn("cached_only", sig.parameters, m.__name__)

    def test_a_cold_wms_declines_instead_of_fetching(self):
        import shutil
        import tempfile
        import radar_wms
        d = tempfile.mkdtemp(prefix="cold-")
        was, radar_wms.CACHE = radar_wms.CACHE, d
        try:
            def boom(u):
                raise AssertionError("touched the network on a reader thread")
            self.assertIsNone(radar_wms.draw("><", -87.62, 41.88,
                                             get=boom, cached_only=True))
        finally:
            radar_wms.CACHE = was
            shutil.rmtree(d, ignore_errors=True)


class AColdFetchNeedsRoomInTheReadersBudget(unittest.TestCase):
    """Helsinki cold measured 3.65s end to end -- over the 3s product line --
    because the primary had nothing and the fallback fetched on the reader's
    thread. Spending that when the budget is nearly gone turns "no map, here is
    why" into "no map, and you waited"."""

    def test_the_threshold_is_the_measured_cost_not_a_round_number(self):
        self.assertGreaterEqual(RS.SECOND_FETCH_NEEDS, 3.0)

    def test_with_no_deadline_at_all_we_still_fetch(self):
        """A caller outside a request budget (a test, a warm, an ops script)
        must not be silently downgraded to cache-only."""
        import net_budget
        self.assertIsNone(net_budget.current_deadline())
        seen = {}

        def spy(c, x, y, s, cached_only=False):
            seen["flag"] = cached_only
            return None
        was = RS._second_source
        RS._second_source = spy
        try:
            RS.radar_resolve("><", 0.0, 0.0, "tok", wait=0)
        except Exception:
            pass
        finally:
            RS._second_source = was
        self.assertIs(seen.get("flag"), False)


class RainViewerIsRefusedInCodeNotOnlyInADocument(unittest.TestCase):
    """Their support, 2026-08-13, in reply to an enquiry from this address: no
    paid plans or commercial licences exist any more, and the free API is
    "personal and educational use only - not company or commercial projects,
    even at low volume with attribution". echorune is a company.

    docs/second_radar_source.md already said we would not use it. A refusal
    that lives only in a document is the same shape as a check that only
    prints: RUNEMAP_SECOND_SOURCE=rainviewer would have shipped it and nothing
    would have said a word."""

    def test_draw_returns_nothing_whatever_it_is_asked(self):
        import radar_second
        for sky in [(72.88, 19.08), (-46.63, -23.55), (0.0, 51.5)]:
            self.assertIsNone(radar_second.draw("><", sky[0], sky[1]))
            self.assertIsNone(radar_second.draw("><", sky[0], sky[1],
                                                cached_only=True))

    def test_the_reason_is_carried_in_the_module_not_in_my_memory(self):
        import radar_second
        r = radar_second.LICENCE_REFUSED.lower()
        self.assertIn("personal and educational", r)
        self.assertIn("company", r)
        self.assertIn("2026-08-13", r)

    def test_the_chain_still_moves_on_rather_than_erroring(self):
        import render_scene as RS
        old = RS.SECOND_SOURCE
        RS.SECOND_SOURCE = "rainviewer"
        try:
            self.assertIsNone(RS._second_source("><", 72.88, 19.08, True))
        finally:
            RS.SECOND_SOURCE = old
