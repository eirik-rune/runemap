"""/ja must answer with the place's Japanese name, and only one we can vouch for.

`curl echorune.net/tokyo/ja` answered "# Tokyo, Tokyo, JP 天気一覧" until
2026-11-04 -- the zh fix (test_geo_zh.py) never asked for Japanese, and the
alias table could not have answered if it had: it holds 東京, 东京 and 東京都
for the same id with no language attached, and the rule that picks 扬州 for a
Chinese reader picks 东京 (lower code point) for everybody.

The Japanese name comes from Natural Earth's NAME_JA in the places the
basemap ships, matched by name AND distance. This file uses that shipped file
as it is -- the point is that the real data answers, not a fixture of it --
and builds its own tiny gazetteer, as test_geo_zh.py does, so it runs in CI.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

NE = json.load(open(os.path.join(ROOT, "runemap", "data", "ne", "places.json"), encoding="utf-8"))
TOKYO_NE = next(r for r in NE if r[2] == "Tokyo")

FIXTURE = [
    # the real Tokyo, a little off Natural Earth's point (GeoNames vs NE)
    (1850147, "Tokyo", 35.6895, 139.69171, "JP", "40", "",
     ["tokyo", "东京", "東京", "東京都"]),
    # the same name nowhere near it: must not borrow the name
    (9999001, "Tokyo", -6.0, 141.0, "PG", "01", "", ["tokyo"]),
    # a place Natural Earth does not carry
    (9999002, "Hamlet Nowhere", 36.2, 140.1, "JP", "08", "", ["hamlet nowhere"]),
]
ADMIN = [("JP.40", "Tokyo"), ("PG.01", "Central"), ("JP.08", "Ibaraki")]


def build_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE place (id INT, name TEXT, lat REAL, lon REAL, "
              "cc TEXT, a1 TEXT, a2 TEXT, pop INT, tz TEXT)")
    c.execute("CREATE TABLE alias (key TEXT, pid INT, pop INT)")
    c.execute("CREATE TABLE admin (code TEXT, name TEXT)")
    for k, (pid, name, lat, lon, cc, a1, a2, aliases) in enumerate(FIXTURE):
        pop = 9000000 - k
        c.execute("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, name, lat, lon, cc, a1, a2, pop, "Asia/Tokyo"))
        for a in aliases:
            c.execute("INSERT INTO alias VALUES (?,?,?)", (a, pid, pop))
    c.executemany("INSERT INTO admin VALUES (?,?)", ADMIN)
    c.commit()
    c.close()


class JaAsksInJapaneseAndIsAnsweredInJapanese(unittest.TestCase):

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

    def test_the_reported_case(self):
        got = self.geo.lookup("tokyo", lang="ja")
        self.assertEqual(got["label"], TOKYO_NE[5])
        self.assertEqual(got["name"], TOKYO_NE[5])

    def test_it_is_not_the_chinese_pick(self):
        """The bug that would come back first: reusing cjk_name for ja."""
        self.assertNotEqual(self.geo.lookup("tokyo", lang="ja")["label"],
                            self.geo.lookup("tokyo", lang="zh")["label"])

    def test_a_coordinate_gets_it_too(self):
        got = self.geo.rlookup(35.6895, 139.69171, lang="ja")
        self.assertEqual(got["label"], TOKYO_NE[5])

    def test_the_same_name_far_away_keeps_its_own(self):
        got = self.geo.rlookup(-6.0, 141.0, lang="ja")
        self.assertEqual(got["label"], "Tokyo, Central, PG")

    def test_a_place_natural_earth_lacks_stays_romanized(self):
        self.assertEqual(self.geo.lookup("hamlet nowhere", lang="ja")["label"],
                         "Hamlet Nowhere, Ibaraki, JP")

    def test_english_and_chinese_are_untouched(self):
        self.assertEqual(self.geo.lookup("tokyo")["label"], "Tokyo, Tokyo, JP")
        self.assertEqual(self.geo.lookup("tokyo", lang="zh")["label"], "东京")


if __name__ == "__main__":
    unittest.main()
