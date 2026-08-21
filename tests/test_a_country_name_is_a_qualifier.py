"""A country name in the query must actually do work.

Issue #200, found on 2026-08-21 while measuring the `/princeton` bug bob
reported -- not reported by anyone, and that is the point:

    curl echorune.net/'san jose, costa rica'   ->  San Jose, California, US

The country was never stored as a NAME anywhere in the database. `place` has
the two-letter code, `admin` has states and counties, `alias` has settlement
names. So "costa rica" matched no component of any label, the qualifier was
discarded, and the lookup fell back to its default rule -- most populous --
which is California. The reader gets a correctly formatted scene for a city
7,000km from the one they named, with nothing to suggest a choice was made.

**`paris, france` worked, and that is what kept this hidden.** It worked
because Paris FR is already the most populous candidate: the word "france" did
nothing at all. A spot-check of famous cities cannot find this class of bug,
because the qualifier and the default agree in exactly the cases anyone thinks
to check. It shows up only where they disagree, which is where the qualifier
was needed in the first place.

The fix folds the country name into the label components rather than giving it
a matcher of its own, so it inherits the two rules already established by the
Princeton work -- whole-component equality, or a prefix of at least four
characters -- and there stays ONE place where a qualifier is decided.

Builds its own fixture DB: a test that skips when GEO_DB is absent skips here
AND in CI, and a test that can never fail is decoration.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

#: (id, name, cc, a1, a2, pop, lat, lon). The populations are the real ones,
#: because the whole bug is that the more populous San Jose is the wrong one.
FIXTURE = [
    (1, "San Jose", "US", "CA", "085", 1026908, 37.339, -121.895),
    (2, "San Jose", "CR", "08", "", 335007, 9.934, -84.088),
    (3, "Paris", "FR", "11", "75", 2138551, 48.853, 2.349),
    (4, "Paris", "US", "TX", "277", 24782, 33.661, -95.556),
    (5, "Tokyo", "JP", "40", "", 9733276, 35.690, 139.692),
]
ADMIN = [("US.CA", "California"), ("US.CA.085", "Santa Clara County"),
         ("CR.08", "San Jose"), ("FR.11", "Ile-de-France"),
         ("FR.11.75", "Paris"), ("US.TX", "Texas"), ("US.TX.277", "Lamar County"),
         ("JP.40", "Tokyo")]
COUNTRY = [("US", "United States", "USA"), ("CR", "Costa Rica", "CRI"),
           ("FR", "France", "FRA"), ("JP", "Japan", "JPN")]


def build_db(path, with_country=True):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE place (id INT, name TEXT, lat REAL, lon REAL, "
              "cc TEXT, a1 TEXT, a2 TEXT, pop INT, tz TEXT)")
    c.execute("CREATE TABLE alias (key TEXT, pid INT, pop INT)")
    c.execute("CREATE TABLE admin (code TEXT, name TEXT)")
    for pid, name, cc, a1, a2, pop, lat, lon in FIXTURE:
        c.execute("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, name, lat, lon, cc, a1, a2, pop, "UTC"))
        c.execute("INSERT INTO alias VALUES (?,?,?)", (name.lower(), pid, pop))
    c.executemany("INSERT INTO admin VALUES (?,?)", ADMIN)
    if with_country:
        c.execute("CREATE TABLE country (cc TEXT, name TEXT, iso3 TEXT)")
        c.executemany("INSERT INTO country VALUES (?,?,?)", COUNTRY)
    c.commit()
    c.close()


def fresh(path):
    """Point geo at `path` and drop every cached thing that would outlive it."""
    import geo
    geo.DB = path
    geo._COUNTRY = None
    if hasattr(geo._L, "c"):
        del geo._L.c
    return geo


class ACountryNameSelectsTheCountry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "geo.sqlite")
        build_db(cls.path)
        os.environ["GEO_DB"] = cls.path
        cls.geo = fresh(cls.path)

    def setUp(self):
        fresh(self.path)

    # ---- the reported case -------------------------------------------------

    def test_the_reported_case(self):
        p = self.geo.lookup("san jose, costa rica")
        self.assertEqual(p["cc"], "CR", "the country named in the query loses "
                                        "to raw population without this fix")

    def test_the_bare_name_is_unchanged(self):
        """No qualifier, so the explainable default still applies. Changing
        this would be inventing a fame signal we do not have."""
        self.assertEqual(self.geo.lookup("san jose")["cc"], "US")

    # ---- the case that hid it ----------------------------------------------

    def test_paris_france_now_works_for_the_stated_reason(self):
        """It already returned France -- by coincidence, because Paris FR is
        the most populous candidate. The control is the inverse query: if the
        qualifier is really doing the work, naming the small one must win."""
        self.assertEqual(self.geo.lookup("paris, france")["cc"], "FR")
        p = self.geo.lookup("paris, united states")
        self.assertEqual(p["cc"], "US")
        self.assertEqual(p["a1"], "TX", "24,782 people beating 2.1M is the "
                                        "only proof the word was read")

    # ---- it inherits the existing rules, it does not add new ones ----------

    def test_a_three_letter_iso_code_works(self):
        self.assertEqual(self.geo.lookup("san jose, cri")["cc"], "CR")

    def test_a_four_character_prefix_works_as_it_does_for_other_components(self):
        self.assertEqual(self.geo.lookup("san jose, costa")["cc"], "CR")

    def test_a_short_prefix_still_does_not_match(self):
        """`cos` is three characters. Short prefixes are where the silent wrong
        answers live, and country names must not reopen that door."""
        self.assertEqual(self.geo.lookup("san jose, cos")["cc"], "US",
                         "an unmatched qualifier falls back to the ranked "
                         "first choice, it does not match loosely")

    def test_an_unrelated_country_does_not_match_anything(self):
        p = self.geo.lookup("san jose, japan")
        self.assertEqual(p["cc"], "US", "no candidate is in Japan, so the "
                                        "qualifier finds nothing and the "
                                        "default stands")

    def test_the_two_letter_code_still_works(self):
        """It did before this change; a fix that broke it would be a net loss."""
        self.assertEqual(self.geo.lookup("san jose, cr")["cc"], "CR")

    def test_a_state_qualifier_still_works(self):
        """The whole Princeton fix must survive this one."""
        self.assertEqual(self.geo.lookup("paris, tx")["a1"], "TX")
        self.assertEqual(self.geo.lookup("paris, texas")["a1"], "TX")

    # ---- the old database must not take the service down -------------------

    def test_an_older_database_still_answers(self):
        """Production runs a 65MB geo.sqlite that is rebuilt separately from
        the code deploy, so for a window the running service has this code and
        a DB with no `country` table. Falling back is correct; falling over is
        not, and a deploy that blanks the site to add a qualifier would be a
        worse bug than the one being fixed."""
        old = os.path.join(self.dir, "old.sqlite")
        build_db(old, with_country=False)
        g = fresh(old)
        try:
            self.assertEqual(g.lookup("san jose")["cc"], "US")
            self.assertEqual(g.lookup("san jose, cr")["cc"], "CR",
                             "the code-based qualifier is unaffected")
            self.assertEqual(g.lookup("san jose, costa rica")["cc"], "US",
                             "degraded, which is the honest outcome for a DB "
                             "that does not carry the data")
            self.assertEqual(g._countries(), {})
        finally:
            fresh(self.path)

    def test_the_old_database_says_so_out_loud(self):
        """Degrading quietly is the failure this codebase keeps paying for, so
        the absence is announced to the log the service already writes."""
        import contextlib
        import io
        old = os.path.join(self.dir, "old2.sqlite")
        build_db(old, with_country=False)
        err = io.StringIO()
        g = fresh(old)
        try:
            with contextlib.redirect_stderr(err):
                g._countries()
        finally:
            fresh(self.path)
        self.assertIn("no country table", err.getvalue())
        self.assertIn("build_geo.py", err.getvalue(),
                      "an operator reading this needs the repair, not just "
                      "the diagnosis")


class TheBuilderRefusesAnEmptyCountryTable(unittest.TestCase):
    """The parser skips ~50 comment lines by looking for a leading '#'. If that
    ever silently kept three rows, the feature would be off while every other
    number the build prints looked normal -- so the builder asserts a floor
    (252 countries exist today) instead of trusting its own parse."""

    def test_the_floor_is_below_the_real_count_and_above_a_broken_parse(self):
        import re
        src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                                "build_geo.py"), encoding="utf-8").read()
        m = re.search(r"if len\(ctry\) < (\d+):", src)
        self.assertIsNotNone(m, "the floor must exist")
        floor = int(m.group(1))
        self.assertGreater(floor, 50, "must be above the comment-line count, "
                                      "or a parse that kept only comments "
                                      "would pass")
        self.assertLess(floor, 252, "must be below the real count, or every "
                                    "build fails")


if __name__ == "__main__":
    unittest.main()
