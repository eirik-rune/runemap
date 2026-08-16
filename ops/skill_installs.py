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

A second lesson, learned by this file breaking the thing it checks: the
installer writes into the **current working directory**, not into $HOME. The
first version set HOME to a temp dir and left cwd in the repository, so it
installed the skill on top of our own source tree -- replacing the tracked
SKILL.md, adding .agents/, agent/, .claude/ and skills-lock.json -- and then
reported FAILED, because it went looking for the files under $HOME where
nothing had been written. A check that damages the subject and misreports the
result is worse than no check. It now runs entirely inside the temp directory.

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
    print("as a stranger would run it, in a throwaway directory:\n  %s\n"
          % " ".join(cmd))
    try:
        # cwd matters more than HOME here: this installer writes into the
        # working directory. Getting that wrong once was enough -- it installed
        # over the repository's own SKILL.md.
        p = subprocess.run(cmd, env=env, cwd=home, capture_output=True,
                           text=True, timeout=420)
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
        # Enough context to diagnose a failure on a machine I cannot log into.
        # The first CI run of this check failed in a way that does not reproduce
        # locally, and the output it printed -- six lines of a progress spinner
        # -- was not enough to say why. An instrument that only says "no" from
        # inside someone else's environment sends me guessing.
        print("   rc=%s  cwd=%s" % (p.returncode, home))
        print("   HOME=%s  TMPDIR=%s" % (env.get("HOME"), env.get("TMPDIR", "(unset)")))
        listing = []
        for root, dirs, files in os.walk(home):
            rel = root[len(home):].lstrip("/") or "."
            listing.append("%s/  [%s]" % (rel, ", ".join(sorted(files)[:6])))
            if len(listing) > 25:
                listing.append("... (truncated)")
                break
        print("   what was written:")
        for line in listing:
            print("     ", line[:150])
        print("   installer output, last 25 lines:")
        for line in out.strip().splitlines()[-25:]:
            print("     ", line[:160])
        print("\nThis is the command in the README, in /help, on the hub, and in "
              "every listing\nfiled with a stranger. Nobody who tries it gets a "
              "second attempt.")
        shutil.rmtree(home, ignore_errors=True)
        return 1

    # Installed is not the same as intact: an installer that writes an empty or
    # rewritten file would still satisfy the check above.
    #
    # It writes TWO copies, and they are not identical: the canonical one under
    # .agents/ keeps the full frontmatter, while the agent/ copy drops `name`
    # because its directory already carries it. Judging on whichever copy the
    # walk happened to reach first reported "name: present: False" about a
    # perfectly good install -- so every copy is printed, and the requirement is
    # that at least one carries both fields.
    want = open(LOCAL, encoding="utf-8").read()
    intact = False
    print("OK the advertised command installed %d copy/copies:" % len(installed))
    for f in sorted(installed):
        got = open(f, encoding="utf-8").read()
        has = ("name:" in got, "description:" in got)
        intact = intact or all(has)
        print("   %-52s %5dB  name=%-5s description=%-5s%s"
              % (f[len(home):].lstrip("/"), len(got), has[0], has[1],
                 "  (identical to published)" if got.strip() == want.strip() else ""))
    shutil.rmtree(home, ignore_errors=True)
    if not intact:
        print("\nFAILED no installed copy carries both name and description -- "
              "an agent\nresolving this skill has nothing to match on.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
