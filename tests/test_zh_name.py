"""The Chinese pages say 雨书, the service's Chinese name.

2026-11-14: in a Caiyun users' group someone asked about the text radar and
nobody could type or say "echorune" or "runemap". bob picked 雨书 from
Qianlu's three ("雨书 这个名字很棒 ... 中文版换这个名字"); the name is
Luoshu's to accept and he did. Only the Chinese surfaces change: the English
and Japanese pages, the domain, the repo and every identifier (MCP serverInfo,
skill name) stay as they are.

Asserted on what a reader gets back -- the rendered text page, the fetching
page, and the picture's footer string -- not on the source.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
os.environ.setdefault("CAIYUN_TOKEN", "dummy-for-import-only")
import render_scene as R  # noqa: E402
from runemap import panorama as PN  # noqa: E402

NAME = "雨书"   # 雨书

WX = {"realtime": {"skycon": "CLEAR_DAY", "temperature": 20.0, "humidity": 0.5,
                   "wind": {"speed": 5.0},
                   "precipitation": {"local": {"intensity": 0.0}}},
      "forecast_keypoint": "no rain",
      "minutely": {"precipitation_2h": [0.0] * 120, "description": "no rain"}}


def data_line(page):
    hits = [l for l in page.split("\n")
            if l.startswith(("data:", "数据:", "データ:"))]
    assert len(hits) == 1, hits
    return hits[0]


class ChinesePagesSayTheChineseName(unittest.TestCase):

    def test_the_scene_page(self):
        line = data_line(R.build("zh", "x", "XX", "x", 0.0, 0.0, 0, WX, None))
        self.assertIn(NAME + " 渲染", line)          # 雨书 渲染
        self.assertNotIn("runemap 渲染", line)
        self.assertIn("caiyunapp.com", line)                  # the data credit stays

    def test_the_fetching_page(self):
        line = data_line(R.build_fetching("zh", "x"))
        self.assertIn(NAME + " 渲染", line)
        self.assertNotIn("runemap 渲染", line)

    def test_the_picture_footer(self):
        foot = PN.text("zh", "foot2")
        self.assertIn(NAME, foot)
        self.assertIn("echorune.net", foot)                   # the address people type


class OtherLanguagesAreUntouched(unittest.TestCase):

    def test_scene_and_fetching(self):
        for lang, word in (("en", "| runemap "), ("ja", "| runemap ")):
            for page in (R.build(lang, "x", "XX", "x", 0.0, 0.0, 0, WX, None),
                         R.build_fetching(lang, "x")):
                line = data_line(page)
                self.assertIn(word, line, lang)
                self.assertNotIn(NAME, line, lang)

    def test_picture_footer(self):
        for lang in ("en", "ja"):
            self.assertNotIn(NAME, PN.text(lang, "foot2"), lang)


if __name__ == "__main__":
    unittest.main()
