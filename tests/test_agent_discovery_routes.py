"""The two files a machine reads before it reads anything else.

`/llms.txt` and `/robots.txt` exist so that an agent arriving at echorune.net
can find out what is here without a human in the loop. They went in on
2026-08-16; before that `/robots.txt` was a 404, which is not neutral -- some
agent frameworks fetch it first and a 404 is one more thing they have to guess
about.

Why a test at all: these routes have no reader inside the service. Nothing else
breaks if they start 404ing, no page looks wrong, and the failure lands on a
stranger's agent rather than on us. That is the shape this repo keeps warning
itself about, so the promise is asserted here rather than remembered.

The assertions are deliberately about *pointers*, not prose. `/llms.txt` must
point at the skill and must not grow into a second copy of it: a duplicated
description drifts from the real one and both read as reasonable on their own.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def _route(path):
    """Read the literal body the server would send for `path`.

    Parsed out of the source rather than served, because standing a server up
    needs production credentials; what is being checked here is the promise in
    the code, and a drift in that promise is exactly what this catches.
    """
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "serve.py"), encoding="utf-8").read()
    m = re.search(r'if u\.path == "%s":\n(.*?)\n        if ' % re.escape(path),
                  src, re.S)
    if not m:
        raise AssertionError("no route serving %s" % path)
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))


class AgentFacingFilesExist(unittest.TestCase):

    def test_llms_txt_points_at_the_skill_and_the_docs(self):
        body = _route("/llms.txt")
        self.assertIn("echorune.net/skill.md", body)
        self.assertIn("echorune.net/help", body)
        self.assertIn("github.com/eirik-rune/runemap", body)

    def test_llms_txt_is_a_pointer_not_a_second_copy_of_the_skill(self):
        """A summary is fine; a duplicated interface is not. If this file ever
        starts teaching the API itself, there are two descriptions to keep in
        step and no way to notice when they part."""
        body = _route("/llms.txt")
        self.assertLess(len(body), 1200,
                        "llms.txt is growing into a second skill document")
        self.assertNotIn("curl ", body)

    def test_llms_txt_carries_the_one_distinction_that_changes_answers(self):
        """'?' is not clear sky. Anything that summarises this service and
        drops that line is summarising it wrongly."""
        self.assertRegex(_route("/llms.txt"), r"(?i)outside radar coverage")

    def test_robots_allows_crawling_and_names_the_summary(self):
        body = _route("/robots.txt")
        self.assertIn("User-agent: *", body)
        self.assertIn("Allow: /", body)
        self.assertNotIn("Disallow: /\\n", body)
        self.assertIn("echorune.net/llms.txt", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
