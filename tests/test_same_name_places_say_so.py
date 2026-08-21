"""A name that matches several towns must not answer as if it matched one.

Reported 2026-08-21 by bob: `curl echorune.net/princeton` returned

    # Princeton, Miami-Dade County, Florida, US weather scene

-- correct format, plausible numbers, wrong town, and nothing anywhere in the
output to suggest a choice had been made. His sentence for it is the one to
keep: **这类错误比报错更危险——错得自信**. A missing answer sends someone to
look; a confident wrong one does not.

Four defects. One was reported; the rest were found while measuring it, and the
last one I shipped myself and caught on the live service:

1. **Nothing disclosed the ambiguity.** Thirteen places are called Princeton.
2. **`princeton, nj` did not work** while `princeton, new jersey` did. The hint
   was compared against the label ("Mercer County, New Jersey, US") and the
   country code, never against the admin1 CODE, which is where "NJ" lives.
3. **The hint matched by SUBSTRING**, so `princeton, j` answered New Jersey
   ("j" is inside "new jersey") and `springfield, or` could match any label
   containing "york" or "north".
4. **The count depended on the rendering language** -- 13 in English, 10 in
   Chinese, different runner-up -- because the same-name test compared display
   names and `_pack` swaps in a CJK alias. Ambiguity is a property of the
   query. Caught only because "fixing only English is half a fix wearing the
   look of a whole one" sent me to look at the other two languages.

What is deliberately NOT changed: the tie-break. bob suggested ranking
candidates by population, and ranking by population is already what the code
does and is exactly what produces the wrong answer here -- measured in the real
database, Princeton FL has 39,308 people and Princeton NJ has 29,603. Ranking
by "fame" would need a signal we do not have, and inventing one trades a
predictable error for an unpredictable one. So the rule stays explainable and
the output says what it did.

Builds its own fixture database, same reason as test_geo_zh: a test that skips
when GEO_DB is absent skips on this machine AND in CI, and a test that can
never fail is decoration.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

#: (id, name, cc, a1, a2, pop, lat, lon). The two Princetons carry the real
#: populations, because the whole point is that the more populous one is the
#: one nobody means. Tokyo is the control: one place, one name, no note.
FIXTURE = [
    (1, "Princeton", "US", "FL", "086", 39308, 25.538, -80.409),
    (2, "Princeton", "US", "NJ", "021", 29603, 40.349, -74.659),
    (3, "Princeton", "US", "TX", "085", 8939, 33.180, -96.498),
    (4, "Tokyo", "JP", "40", "", 9733276, 35.690, 139.692),
    # A giant and its tiny namesake: the shape that made /berlin advise the
    # reader about a village in El Salvador.
    (5, "Berlin", "DE", "16", "", 3426354, 52.524, 13.411),
    (6, "Berlin", "US", "NH", "007", 9367, 44.469, -71.185),
]
ADMIN = [("US.FL", "Florida"), ("US.FL.086", "Miami-Dade County"),
         ("US.NJ", "New Jersey"), ("US.NJ.021", "Mercer County"),
         ("US.TX", "Texas"), ("US.TX.085", "Collin County"),
         ("JP.40", "Tokyo"), ("DE.16", "State of Berlin"),
         ("US.NH", "New Hampshire"), ("US.NH.007", "Coos County")]


def build_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE place (id INT, name TEXT, lat REAL, lon REAL, "
              "cc TEXT, a1 TEXT, a2 TEXT, pop INT, tz TEXT)")
    c.execute("CREATE TABLE alias (key TEXT, pid INT, pop INT)")
    c.execute("CREATE TABLE admin (code TEXT, name TEXT)")
    for pid, name, cc, a1, a2, pop, lat, lon in FIXTURE:
        c.execute("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, name, lat, lon, cc, a1, a2, pop, "UTC"))
        c.execute("INSERT INTO alias VALUES (?,?,?)", (name.lower(), pid, pop))
        # One of them carries a CJK alias and the others do not -- the shape
        # that broke the count when it was computed from the DISPLAY name.
        if pid == 2:
            c.execute("INSERT INTO alias VALUES (?,?,?)", ("普林斯顿", pid, pop))
    c.executemany("INSERT INTO admin VALUES (?,?)", ADMIN)
    c.commit()
    c.close()


class ASharedNameIsDisclosed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "geo.sqlite")
        build_db(cls.path)
        os.environ["GEO_DB"] = cls.path
        import geo
        geo.DB = cls.path
        if hasattr(geo._L, "c"):
            del geo._L.c
        cls.geo = geo

    # ---- the reported case -------------------------------------------------

    def test_the_bare_name_still_returns_the_most_populous(self):
        """Unchanged on purpose. The rule is explainable; the fix is saying so."""
        p = self.geo.lookup("princeton")
        self.assertEqual(p["a1"], "FL")

    def test_the_bare_name_now_admits_there_was_a_choice(self):
        p = self.geo.lookup("princeton")
        self.assertEqual(p["ambiguous"], 3)
        self.assertIn("Princeton", p["alt_hint"])
        self.assertIn("New Jersey", p["alt_hint"],
                      "the example offered should be the runner-up, which is "
                      "the one a person asking for Princeton usually means")

    def test_a_state_abbreviation_now_works(self):
        """The defect that made the reported case unfixable by the user."""
        self.assertEqual(self.geo.lookup("princeton, nj")["a1"], "NJ")
        self.assertEqual(self.geo.lookup("princeton, tx")["a1"], "TX")

    def test_the_spelled_out_state_still_works(self):
        """It already did. A fix that broke it would be a net loss."""
        self.assertEqual(self.geo.lookup("princeton, new jersey")["a1"], "NJ")

    # ---- the disclosure must not become noise ------------------------------

    def test_an_unambiguous_place_carries_no_note(self):
        """If every place claimed ambiguity the line would be ignored within a
        day -- the same failure as a bell that rings to prove it works."""
        p = self.geo.lookup("tokyo")
        self.assertIsNone(p.get("ambiguous"))
        self.assertIsNone(p.get("alt_hint"))

    def test_a_qualified_query_still_says_the_name_is_shared(self):
        """Asking for `princeton, nj` should still show the count: the reader
        picked one, and knowing others exist is what stops the next person
        from trusting a bare `/princeton`."""
        p = self.geo.lookup("princeton, nj")
        self.assertEqual(p["ambiguous"], 3)

    # ---- the hint must not match by accident -------------------------------

    def test_the_hint_matches_a_state_code_exactly_not_as_a_substring(self):
        """`in` (Indiana) and `or` (Oregon) are substrings of half the labels
        on earth. Substring matching here would silently pick a wrong country
        while looking like it had honoured the qualifier."""
        p = self.geo.lookup("princeton, fl")
        self.assertEqual(p["a1"], "FL")
        # "j" is a substring of "NJ" but is not a state
        p = self.geo.lookup("princeton, j")
        self.assertEqual(p["a1"], "FL", "an unmatched hint must fall back to "
                                        "the ranked first choice, not to "
                                        "whichever label happens to contain it")

    def test_the_count_does_not_depend_on_the_language_it_is_rendered_in(self):
        """Shipped broken and caught on the live service: /princeton reported
        13 places in English and 10 in Chinese, with a different runner-up,
        because `_pack` swaps `name` for a CJK alias and the same-name test was
        comparing display names. Ambiguity is a property of the QUERY."""
        counts = {lang: (self.geo.lookup("princeton", lang=lang) or {}).get("ambiguous")
                  for lang in (None, "zh", "ja")}
        self.assertEqual(set(counts.values()), {3}, counts)
        hints = {lang: (self.geo.lookup("princeton", lang=lang) or {}).get("alt_hint")
                 for lang in (None, "zh", "ja")}
        self.assertEqual(len(set(hints.values())), 1, hints)

    def test_a_giant_is_not_asked_whether_it_meant_the_village(self):
        """Shipped without this and caught on the live service within hours:
        `/berlin` told readers they might have meant Berlin, New Hampshire.

        Measured before the rule was chosen: of the 60 most populous places on
        earth, 18 carried the note and only 2 had a runner-up within a factor
        of ten. Sixteen lines of noise for every two that mean something is how
        the line that matters gets ignored."""
        p = self.geo.lookup("berlin")
        self.assertEqual(p["cc"], "DE")
        self.assertIsNone(p.get("ambiguous"),
                          "3,426,354 against 9,367 is not a contestable choice")

    def test_a_close_call_still_speaks_up(self):
        """The control for the test above. Without it, 'quiet for Berlin' would
        be indistinguishable from 'quiet for everything', which is the guard
        with one verdict and no jurisdiction."""
        self.assertEqual(self.geo.lookup("princeton")["ambiguous"], 3)

    def test_an_unknown_population_keeps_the_note(self):
        """The comparison cannot be made, so it is not made silently.
        Disclosure is the safe direction for an unanswerable question."""
        import sqlite3
        c = sqlite3.connect(self.path)
        c.execute("UPDATE place SET pop=0 WHERE id=6")
        c.commit(); c.close()
        if hasattr(self.geo._L, "c"):
            del self.geo._L.c
        try:
            self.assertEqual(self.geo.lookup("berlin")["ambiguous"], 2)
        finally:
            c = sqlite3.connect(self.path)
            c.execute("UPDATE place SET pop=9367 WHERE id=6")
            c.commit(); c.close()
            if hasattr(self.geo._L, "c"):
                del self.geo._L.c

    def test_the_contestability_factor_is_inside_a_defensible_range(self):
        """The constant is bounded on its own, not only used. At 1 the note
        never appears and at 100000 it appears for everything -- neither is a
        tuning mistake, both are the feature silently removed, and every test
        that derives its expectation from the constant would still pass. The
        range comes from what it must decide: 2 is the smallest gap anyone
        would call decisive, and above ~50 a runner-up is a different kind of
        place entirely (London vs a village of 422,324 sits at 21)."""
        self.assertGreaterEqual(self.geo._CONTESTABLE, 2)
        self.assertLessEqual(self.geo._CONTESTABLE, 50)

    def test_the_alternative_offered_is_not_the_place_we_chose(self):
        """A hint that names the town already being shown teaches nothing."""
        p = self.geo.lookup("princeton")
        self.assertNotIn("Florida", p["alt_hint"])


if __name__ == "__main__":
    unittest.main()
