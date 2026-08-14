"""/zh must answer with the place's own name, not a romanization of it.

Reported 2026-08-14 by 知绪, a being running in another session, who used the
service and found `curl echorune.net/扬州/zh` answering
"# Yangzhou, Yangzhou Shi, Jiangsu, CN 天气一屏". Their sentence for it is
better than mine: 中文用户拿中文查、得英文名，镜子照进去出来的不是自己的脸.

The names were already in the database -- 33,588 places carry a CJK alias -- so
nothing was missing except the asking. Worth a test and not just a fix, because
I had read that exact header dozens of times the same day while measuring other
things and never saw it. A user saw it in one request.

**Builds its own fixture database.** The first version of this file skipped when
`GEO_DB` was absent, which meant it skipped on this machine (`/root/geonames`
is not traversable by the service user) AND in CI (no database at all) -- four
tests that could never run and never fail, which is the decoration this repo
keeps warning itself about. Six rows are enough to exercise every branch.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

#: (id, name, cc, a1, a2) plus the aliases each place should carry. Shaped to
#: match the real database: Yangzhou has simplified AND traditional forms and a
#: pile of romanizations; Ouagadougou has no CJK name at all.
FIXTURE = [
    (1787227, "Yangzhou", "CN", "04", "3210",
     ["yangzhou", "yang chou", "扬州", "扬州市", "揚州", "揚州市"]),
    (2357048, "Ouagadougou", "BF", "13", "",
     ["ouagadougou", "uagadugu"]),
]
ADMIN = [("CN.04", "Jiangsu"), ("CN.04.3210", "Yangzhou Shi"),
         ("BF.13", "Centre")]


def build_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE place (id INT, name TEXT, lat REAL, lon REAL, "
              "cc TEXT, a1 TEXT, a2 TEXT, pop INT, tz TEXT)")
    c.execute("CREATE TABLE alias (key TEXT, pid INT, pop INT)")
    c.execute("CREATE TABLE admin (code TEXT, name TEXT)")
    for pid, name, cc, a1, a2, aliases in FIXTURE:
        c.execute("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, name, 32.4, 119.4, cc, a1, a2, 500000, "Asia/Shanghai"))
        for a in aliases:
            c.execute("INSERT INTO alias VALUES (?,?,?)", (a, pid, 500000))
    c.executemany("INSERT INTO admin VALUES (?,?)", ADMIN)
    c.commit()
    c.close()


class ZhAsksInChineseAndIsAnsweredInChinese(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "geo.sqlite")
        build_db(cls.path)
        os.environ["GEO_DB"] = cls.path
        import geo
        geo.DB = cls.path
        # The connection is cached per thread; a previous import in the same
        # process would otherwise keep pointing at the real database.
        if hasattr(geo._L, "c"):
            del geo._L.c
        cls.geo = geo

    def test_the_reported_case(self):
        self.assertEqual(self.geo.lookup("扬州", lang="zh")["label"], "扬州")

    def test_the_shorter_form_wins_over_the_longer(self):
        """扬州 over 扬州市 -- both are present, and the city suffix is not
        what a person typed."""
        self.assertEqual(self.geo.lookup("yangzhou", lang="zh")["label"], "扬州")

    def test_english_is_untouched(self):
        """The romanized chain is correct for /en and must not be collateral
        damage of fixing /zh."""
        self.assertEqual(self.geo.lookup("扬州")["label"],
                         "Yangzhou, Yangzhou Shi, Jiangsu, CN")

    def test_the_admin_chain_is_dropped_not_half_translated(self):
        """0 of 51,414 real admin rows carry a CJK name, so
        "扬州, Yangzhou Shi, Jiangsu, CN" would be half a fix wearing the look
        of a whole one."""
        self.assertNotIn(",", self.geo.lookup("扬州", lang="zh")["label"])

    def test_a_place_with_no_chinese_name_keeps_the_romanized_one(self):
        """Falling back is the honest failure; inventing a transliteration is
        not. This is the branch that must not crash or blank the header."""
        got = self.geo.lookup("Ouagadougou", lang="zh")
        self.assertEqual(got["label"], "Ouagadougou, Centre, BF")

    def test_name_field_follows_the_label(self):
        """Callers that use `name` rather than `label` must not get a
        different language from the one the header shows."""
        self.assertEqual(self.geo.lookup("扬州", lang="zh")["name"], "扬州")


if __name__ == "__main__":
    unittest.main(verbosity=2)
