"""A qualifier we could not honour is not a qualifier the reader did not type.

Found 2026-08-22 by reading the rows of my own demand report, not by anyone
using the service. The top "returning reader" was a lead scraper walking
/contact, /kontakt, /impressum, /en/contact in a dozen languages -- and eleven
of its requests came back **200 with a full weather scene**:

    GET /en/contact  ->  # Hardeeville, Jasper County, South Carolina, US

Two defects stacked, and each one alone would have been invisible:

1. **`en` is an alias of a real town** (Hardeeville, SC, 5,301 people), so the
   bare language suffix in our own URL grammar resolved to a place. `/ko`
   likewise answers Kyiv -- left alone deliberately, because we do not serve
   Korean and inventing a rule about languages we do not offer would be
   guessing rather than fixing.

2. **An unmatched qualifier was silently discarded.** `/en/contact` parses as
   place "en", qualifier "contact"; nothing matched "contact", so the default
   rule answered as though the word had never been typed. That is the general
   form of issue #200 -- there the qualifier could not match because country
   names were not stored at all; fixing the table removed one reason a hint can
   fail, and this makes every remaining reason audible instead of leaving them
   to be discovered one at a time.

The reader-facing case is the one that matters more than the scraper:
`princeton, new jersy` confidently answered Florida over a typo. bob's
sentence for this class still applies -- 这类错误比报错更危险，错得自信.

Deliberately NOT changed: the qualifier is still ignored and an answer is
still returned. Refusing would be defensible, but "shown, with the reason it
could not be honoured" is the smaller error by the ranking bob set out --
missing but honestly declared beats confidently wrong -- and it keeps every
query that works today working.

Builds its own fixture database, same reason as its neighbours: a test that
skips when GEO_DB is absent skips in CI too, and a test that cannot fail is
decoration.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

FIXTURE = [
    (1, "Princeton", "US", "FL", "086", 39308, 25.538, -80.409),
    (2, "Princeton", "US", "NJ", "021", 29603, 40.349, -74.659),
    (3, "Hardeeville", "US", "SC", "053", 5301, 32.287, -81.080),
    (4, "Tokyo", "JP", "40", "", 9733276, 35.690, 139.692),
]
ADMIN = [("US.FL", "Florida"), ("US.FL.086", "Miami-Dade County"),
         ("US.NJ", "New Jersey"), ("US.NJ.021", "Mercer County"),
         ("US.SC", "South Carolina"), ("US.SC.053", "Jasper County"),
         ("JP.40", "Tokyo")]
COUNTRY = [("US", "United States", "USA"), ("JP", "Japan", "JPN")]


def build_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE place (id INT, name TEXT, lat REAL, lon REAL, "
              "cc TEXT, a1 TEXT, a2 TEXT, pop INT, tz TEXT)")
    c.execute("CREATE TABLE alias (key TEXT, pid INT, pop INT)")
    c.execute("CREATE TABLE admin (code TEXT, name TEXT)")
    c.execute("CREATE TABLE country (cc TEXT, name TEXT, iso3 TEXT)")
    for pid, name, cc, a1, a2, pop, lat, lon in FIXTURE:
        c.execute("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, name, lat, lon, cc, a1, a2, pop, "UTC"))
        c.execute("INSERT INTO alias VALUES (?,?,?)", (name.lower(), pid, pop))
    # The alias that made this bug: the real database has "en" pointing at
    # Hardeeville, and no test could reproduce the report without it.
    c.execute("INSERT INTO alias VALUES (?,?,?)", ("en", 3, 5301))
    c.executemany("INSERT INTO admin VALUES (?,?)", ADMIN)
    c.executemany("INSERT INTO country VALUES (?,?,?)", COUNTRY)
    c.commit()
    c.close()


class AnUnmatchedQualifierIsAnnounced(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "geo.sqlite")
        build_db(cls.path)
        os.environ["GEO_DB"] = cls.path
        import geo
        geo.DB = cls.path
        geo._COUNTRY = None
        if hasattr(geo._L, "c"):
            del geo._L.c
        cls.geo = geo

    def test_a_typo_in_a_state_is_reported_not_swallowed(self):
        """The reader-facing case. Before this, a mistyped state answered
        Florida with nothing to suggest the word had been read and dropped."""
        p = self.geo.lookup("princeton, new jersy")
        self.assertEqual(p["a1"], "FL", "the answer itself is unchanged")
        self.assertEqual(p["unmatched_hint"], "new jersy")

    def test_the_qualifier_is_echoed_exactly_as_typed(self):
        """Echoing the normalised form would tidy the typo up and hide the one
        thing the reader needs to see."""
        p = self.geo.lookup("princeton,   New Jersy  ")
        self.assertEqual(p["unmatched_hint"], "New Jersy")

    def test_the_scraper_case(self):
        p = self.geo.lookup("en/contact")
        self.assertEqual(p["name_raw"], "Hardeeville")
        self.assertEqual(p["unmatched_hint"], "contact")

    # ---- it must stay quiet whenever the qualifier did its job -------------

    def test_a_qualifier_that_matched_says_nothing(self):
        """If this fired on success it would appear on nearly every qualified
        query and be ignored inside a day -- the bell that rings to prove it
        works."""
        self.assertIsNone(self.geo.lookup("princeton, nj").get("unmatched_hint"))
        self.assertIsNone(self.geo.lookup("princeton, new jersey")
                          .get("unmatched_hint"))
        self.assertIsNone(self.geo.lookup("princeton, united states")
                          .get("unmatched_hint"))

    def test_no_qualifier_means_no_note(self):
        self.assertIsNone(self.geo.lookup("princeton").get("unmatched_hint"))
        self.assertIsNone(self.geo.lookup("tokyo").get("unmatched_hint"))

    def test_an_unknown_place_still_returns_nothing(self):
        """The note must not turn a 404 into an answer."""
        self.assertIsNone(self.geo.lookup("asdfqwerzxcv, narnia"))

    def test_both_notes_can_appear_together(self):
        """13 Princetons AND a qualifier that matched none of them. They are
        two independent facts and neither may suppress the other."""
        p = self.geo.lookup("princeton, narnia")
        self.assertEqual(p["ambiguous"], 2)
        self.assertEqual(p["unmatched_hint"], "narnia")


class TheRenderedSceneCarriesTheNote(unittest.TestCase):
    """The value is useless if it never reaches the reader, and 'passed to the
    renderer' and 'printed' have been two different things here before."""

    def _scene(self, lang, **kw):
        import render_scene
        wx = {"realtime": {"skycon": "CLEAR_DAY", "temperature": 20.0,
                           "humidity": 0.5, "wind": {"speed": 3.0},
                           "precipitation": {"local": {"intensity": 0.0}}},
              "forecast_keypoint": "", "minutely": {"precipitation_2h": []}}
        # build() returns the finished text. Joining it again split every
        # character onto its own line, and the assertions failed against a
        # scene that was correct -- the harness, not the code.
        return render_scene.build(
            lang, "Princeton, Florida, US", "", "普林斯顿", 1.0, 2.0, 0.0,
            wx, None, **kw)

    def test_english(self):
        s = self._scene("en", unmatched_hint="new jersy")
        self.assertIn("new jersy", s)
        self.assertIn("ignored", s)

    def test_chinese_and_japanese_are_not_left_behind(self):
        """Fixing only English is half a fix wearing the look of a whole one --
        the exact way the ambiguity count shipped broken a day earlier."""
        for lang in ("zh", "ja"):
            s = self._scene(lang, unmatched_hint="new jersy")
            self.assertIn("new jersy", s, lang)
            self.assertNotIn("ignored", s, "%s must not fall back to the "
                                           "English wording" % lang)

    def test_nothing_is_printed_when_there_is_nothing_to_say(self):
        for lang in ("en", "zh", "ja"):
            self.assertNotIn("new jersy", self._scene(lang), lang)


class ABareLanguageSuffixIsNotAPlace(unittest.TestCase):
    """`/en` answered Hardeeville, South Carolina. The rule has a name now so
    that it can be checked; before this it was three lines inside a request
    handler that no test could reach."""

    def _f(self):
        # serve.py exits at import without a Caiyun token (serve.py:46). The
        # token is used for HTTP calls, and nothing at import time makes one,
        # so an obviously fake value is enough to reach the routing rule --
        # and is why this rule was lifted out of the request handler at all.
        os.environ.setdefault("CAIYUN_TOKEN", "fake-token-for-import-only")
        import serve
        return serve.bare_language_suffix

    def test_the_three_we_serve_are_recognised(self):
        for lang in ("en", "zh", "ja", "EN", "Zh"):
            self.assertEqual(self._f()([lang]), lang.lower(), lang)

    def test_a_language_we_do_not_serve_is_left_alone(self):
        """/ko answers Kyiv, which has that alias. Deliberate: we do not offer
        Korean, and a rule about languages we do not offer would be a guess."""
        for lang in ("ko", "de", "fr", "pt"):
            self.assertIsNone(self._f()([lang]), lang)

    def test_a_real_place_is_never_caught(self):
        for place in ("tokyo", "princeton", "en-route", "endelave"):
            self.assertIsNone(self._f()([place]), place)

    def test_the_suffix_after_a_place_is_not_this_case(self):
        """`/tokyo/en` is the documented form and must reach the lookup."""
        self.assertIsNone(self._f()(["tokyo", "en"]))

    def test_the_scraper_path_is_not_caught_here(self):
        """/en/contact is two segments, so this guard does not fire -- it is
        the unmatched-qualifier note that covers it. Two defects, two fixes;
        asserting that keeps a later reader from deleting one as redundant."""
        self.assertIsNone(self._f()(["en", "contact"]))


if __name__ == "__main__":
    unittest.main()
