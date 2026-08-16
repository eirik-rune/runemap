#!/usr/bin/env python3
"""Every command the Agent Skill teaches must actually work.

The Skill is a promise made to a stranger's agent: *call this and you will get
weather*. If a URL form changes, nothing in the test suite goes red -- the Skill
just starts teaching something that 404s, an agent tries once, fails, and never
comes back. There is no louder failure available; that is exactly why it needs
its own check.

Commands are extracted from SKILL.md itself rather than listed here. A second
hand-maintained list drifts from the first while both look reasonable alone.

**The all-identical guard is the point of this file.** The first version of this
check wrote each response to `/tmp/x` and reported a confident "8 of 8 work".
`/tmp/x` turned out to be a root-owned file from three weeks earlier: curl could
not write it, `-s` swallowed the permission error, and every measurement read
the same stale 76 KB HTML. Eight different endpoints returning byte-identical
responses is impossible, and that impossibility was printed on screen without me
noticing. So the size spread is now computed and reported: if all responses come
back the same length, the instrument is broken, and the check says so instead of
passing.

Exit 0 all good, 1 a taught command failed, 2 could not be determined.
"""
import os
import re
import subprocess
import sys
import tempfile

SKILL = os.path.join(os.path.dirname(__file__), "..", "skills",
                     "echorune-radar", "SKILL.md")
BASE = os.environ.get("SKILL_CHECK_BASE", "https://echorune.net")

#: What an agent would substitute. Placeholders that stay unsubstituted would be
#: shell redirection, not a URL, so they must all be covered here.
FILL = {"<place>": "osaka", "<lon>,<lat>": "135.50,34.69"}

#: Smaller than this is not a weather answer even with a 200 attached -- an
#: error page can be perfectly well-formed.
MIN_BODY = 200


def taught_commands(text):
    return [c.strip() for c in re.findall(r"^(curl [^\n#]+?)(?:\s+#.*)?$", text, re.M)]


def main():
    try:
        body = open(SKILL, encoding="utf-8").read()
    except OSError as e:
        print("NO-SKILL cannot read %s: %s" % (SKILL, e))
        return 2
    cmds = taught_commands(body)
    if not cmds:
        # "Found nothing" and "there is nothing" must not share an exit code
        # with success.
        print("NO-COMMANDS parsed 0 curl lines from SKILL.md -- parser drift?")
        return 2

    tmpdir = tempfile.mkdtemp()
    out = os.path.join(tmpdir, "resp")
    print("%d commands taught by the Skill, against %s\n" % (len(cmds), BASE))

    sizes, failed = [], []
    for c in cmds:
        real = c
        for k, v in FILL.items():
            real = real.replace(k, v)
        real = real.replace("echorune.net", BASE.replace("https://", ""))
        if not real.startswith("curl https://"):
            real = real.replace("curl ", "curl https://", 1)
        if os.path.exists(out):
            os.remove(out)          # never judge a file left by a previous run
        try:
            p = subprocess.run(real + " -s -o %s -w '%%{http_code}'" % out,
                               shell=True, capture_output=True, text=True, timeout=60)
            code = p.stdout.strip()[-3:]
        except subprocess.TimeoutExpired:
            code = "---"
        size = os.path.getsize(out) if os.path.exists(out) else -1
        sizes.append(size)
        ok = code == "200" and size >= MIN_BODY
        if not ok:
            failed.append(c)
        print("  %-3s %7dB  %s" % (code, size, c))

    spread = len(set(sizes))
    print("\ndistinct response sizes: %d of %d" % (spread, len(sizes)))
    if spread == 1 and len(sizes) > 1:
        print("BROKEN-RULER every response was the same length. Different "
              "endpoints cannot\n  return identical bodies -- this check is "
              "measuring something other than\n  what it thinks. Not reporting "
              "a pass.")
        return 2

    if failed:
        print("FAILED %d of %d taught commands do not work:" % (len(failed), len(cmds)))
        for c in failed:
            print("   ", c)
        return 1
    print("OK all %d taught commands work" % len(cmds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
