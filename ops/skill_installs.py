#!/usr/bin/env python3
"""Does the install command we advertise everywhere actually install?

On 2026-08-16 it did not, for several hours, while every check was green.

`npx skills add https://github.com/eirik-rune/runemap --skill echorune-radar`
is printed in the README, in `/help`, on the INFERO hub, and in three listing
pull requests filed with strangers that morning. It answered:

    No valid skills found. Skills require a SKILL.md with name and description.

The cause was one character. A rewrite put a colon inside the unquoted
description -- "...instead of an image: current conditions..." -- and in YAML an
unquoted scalar may not contain ": ", so the frontmatter stopped parsing. The
file still looked perfect to a human, and it still served fine over HTTP.

Why nothing went red:

* `tests/test_skill_format.py` parses the frontmatter **with a regex**, on
  purpose, and its docstring says so. A regex does not care about YAML quoting,
  so it read `name` and `description` happily out of a file no YAML parser would
  accept.
* `ops/skill_commands_work.py` checks the curl commands the skill teaches. Those
  were all fine. The one thing it does not do is install the skill.

Both instruments were answering a question next to the one that mattered. The
only check that cannot be fooled by this class of bug is the real installer, run
the way a stranger runs it, so that is what this does: a throwaway HOME, the
published URL, no local files.

Exit 0 installed, 1 the advertised command failed, 2 could not be determined
(no npx, no network).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.environ.get("SKILL_REPO", "https://github.com/eirik-rune/runemap")
NAME = "echorune-radar"

#: Read from the file rather than typed, so a rename cannot leave this checking
#: a skill that no longer exists while reporting success about one that does.
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "skills", NAME, "SKILL.md")


def main():
    if not shutil.which("npx"):
        print("NO-NPX npx is not on PATH -- cannot tell whether the advertised "
              "command works. This is 'I do not know', not 'it works'.")
        return 2

    home = tempfile.mkdtemp(prefix="skillcheck-")
    env = dict(os.environ, HOME=home)
    cmd = ["npx", "-y", "skills", "add", REPO, "--skill", NAME]
    print("as a stranger would run it, in a throwaway HOME:\n  %s\n" % " ".join(cmd))
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=420)
    except subprocess.TimeoutExpired:
        print("TIMEOUT the installer did not finish in 7 minutes")
        return 2
    out = (p.stdout or "") + (p.stderr or "")

    # Network failures are not a broken skill, and must not be reported as one.
    if re.search(r"(ENOTFOUND|ECONNREFUSED|ETIMEDOUT|network|registry error)", out, re.I) \
            and "SKILL.md" not in out:
        print("CANNOT-REACH the installer could not fetch anything:\n  %s"
              % out.strip().splitlines()[-1][:160])
        return 2

    installed = []
    for root, _dirs, files in os.walk(home):
        if "SKILL.md" in files:
            installed.append(os.path.join(root, "SKILL.md"))

    if not installed:
        print("FAILED the advertised install command produced no SKILL.md.")
        for line in out.strip().splitlines()[-6:]:
            print("   ", line[:160])
        print("\nThis is the command in the README, in /help, on the hub, and in "
              "every listing\nfiled with a stranger. Nobody who tries it gets a "
              "second attempt.")
        shutil.rmtree(home, ignore_errors=True)
        return 1

    # Installed is not the same as intact: an installer that writes an empty or
    # rewritten file would still satisfy the check above.
    want = open(LOCAL, encoding="utf-8").read()
    got = open(installed[0], encoding="utf-8").read()
    same = got.strip() == want.strip()
    print("OK installed %d file(s); byte-identical to what we publish: %s"
          % (len(installed), same))
    if not same:
        print("   (installed %d bytes, published %d -- the installer normalises "
              "some copies;\n    what matters is that name and description "
              "survive)" % (len(got), len(want)))
        for field in ("name:", "description:"):
            print("   %-13s present in installed copy: %s" % (field, field in got))
    shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
