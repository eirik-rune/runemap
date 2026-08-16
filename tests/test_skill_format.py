"""The Agent Skill must stay valid against the published format.

This is a check on a file that no other test touches and that fails
*somewhere else* -- a skill marketplace rejecting an upload, or worse, Claude
silently never triggering the Skill because the description drifted. Nothing
locally would go red. That is the shape this repository keeps warning itself
about, so the rules live here as assertions rather than in my memory.

Rules encoded below come from the published spec, not from recollection:
name is <=64 chars of [a-z0-9-] with no reserved words; description is non-empty,
<=1024 chars, no XML tags, and must say both what it does and when to use it;
SKILL.md body under 500 lines.

Two rules here are not in the spec's validator but are in its guidance, and both
were violated by my first draft:

* **Third person in the description.** It is injected into the system prompt,
  and mixed point-of-view degrades skill selection.
* **No time-sensitive facts.** The first draft froze an uptime figure and a
  country count into a file that cannot update itself. A number in a document
  is a number that will be wrong later; it belongs at an endpoint.

The frontmatter is parsed with a deliberately small regex rather than a YAML
library, because the file is also read by other tools and the point is to catch
the file drifting, not to prove a parser works.
"""
import os
import re
import unittest

SKILL = os.path.join(os.path.dirname(__file__), "..", "skills",
                     "echorune-radar", "SKILL.md")

#: Substrings that would mean a measurement got frozen into the document.
#: Deliberately concrete: these are the exact things the first draft contained.
TIME_SENSITIVE = ("99.9", "n=10077", "median 0.7", "12 national", "BR CA")


def read():
    with open(SKILL, encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise AssertionError("SKILL.md must open with a YAML frontmatter block")
    fields = dict(re.findall(r"^([a-z][a-z-]*):\s*(.*)$", m.group(1), re.M))
    return fields, text[m.end():]


class SkillFileIsValid(unittest.TestCase):

    def setUp(self):
        self.fm, self.body = frontmatter(read())

    def test_the_file_is_named_and_placed_as_the_spec_requires(self):
        """SKILL.md uppercase, inside a directory named for the skill."""
        self.assertTrue(os.path.exists(SKILL))
        self.assertEqual(os.path.basename(SKILL), "SKILL.md")
        self.assertEqual(os.path.basename(os.path.dirname(SKILL)),
                         self.fm["name"])

    def test_name_charset_and_length(self):
        self.assertRegex(self.fm["name"], r"^[a-z0-9-]{1,64}$")

    def test_name_avoids_reserved_words(self):
        for word in ("anthropic", "claude"):
            self.assertNotIn(word, self.fm["name"].lower())

    def test_description_length_and_markup(self):
        d = self.fm["description"]
        self.assertTrue(d)
        self.assertLessEqual(len(d), 1024)
        self.assertNotIn("<", d)
        self.assertNotIn(">", d)

    def test_description_says_when_to_use_it(self):
        """Discovery runs entirely off this field; 'what' without 'when' means
        the Skill exists but never triggers."""
        self.assertIn("use when", self.fm["description"].lower())

    def test_description_is_third_person(self):
        """'Reads ...', not 'Read ...' and not 'I can ...'."""
        first = self.fm["description"].split()[0]
        self.assertTrue(first.endswith("s"),
                        "description should open in third person, got %r" % first)
        for bad in ("i can", "you can", "this skill lets you"):
            self.assertNotIn(bad, self.fm["description"].lower())

    def test_no_unknown_frontmatter_fields(self):
        """Extra keys are the likeliest way an upload gets rejected, and the
        rejection happens on someone else's server, not here."""
        self.assertEqual(set(self.fm), {"name", "description"})

    def test_body_is_within_the_token_budget(self):
        self.assertLess(self.body.count("\n"), 500)

    def test_no_frozen_measurements(self):
        found = [t for t in TIME_SENSITIVE if t in self.body]
        self.assertEqual(found, [], "time-sensitive facts belong at an "
                                    "endpoint, not in the Skill: %r" % found)

    def test_it_still_teaches_the_distinction_that_changes_answers(self):
        """The single most valuable line in the file: '?' is not 'clear'.
        If a rewrite drops this, the Skill still validates and still installs,
        and agents start reporting blind cells as good weather."""
        self.assertIn("?", self.body)
        self.assertIn("outside radar coverage", self.body)
        # Compare against what a reader sees, not the source. The first version
        # of this matched raw markdown and failed on `**not** "clear"`, because
        # the emphasis markers and quotes sit between the two words -- the
        # document was right and the assertion was wrong. Strip the markup that
        # a renderer would consume before asserting about wording.
        plain = re.sub(r'[*_"“”]', "", self.body)
        self.assertRegex(plain, r"(?i)not\s+clear")

    def test_paths_are_posix(self):
        self.assertNotIn("\\", self.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
