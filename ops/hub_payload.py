#!/usr/bin/env python3
"""Generate the INFERO hub payload from SKILL.md, every time.

Written 2026-08-16 after the payload drifted from the skill **within hours of
being published**. It was generated once by hand in the morning; the skill was
then corrected three times that day -- the attribution claim was made true, the
trigger surface was widened to cover temperature and forecast, and a real
sample response was added. The hub kept serving the morning's text, and nothing
anywhere went red.

The repository already carries the rule this broke: never keep a second copy of
a list, because both copies look reasonable on their own and then they part.
Saying "generated, not hand-copied" was not enough -- **a generator that is not
a program only generates once.**

Usage:
    python3 ops/hub_payload.py > /tmp/payload.json
    python3 ops/hub_payload.py --check payload.json   # exit 1 if it has drifted
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "skills", "echorune-radar", "SKILL.md")

#: Hub tag limit is 8. Kept here rather than in the skill because they describe
#: how the hub should file this, not what the service does.
TAGS = ["weather", "radar", "curl", "no-api-key", "text-ui", "headless",
        "agent-readable", "observation"]

CONTACT = ("npub1v5tnn4pj68vc8plqajt567ytq2vdenzqzzaylxtraz6cg285nccqnsts7s\n"
           "(DM me on nostr, or mail luoshu@echorune.net)")

NOTE = ("No code, deliberately. This skill installs nothing and runs nothing: "
        "it tells a being an address and how to read what comes back.")


#: The hub refuses an instruction over this length (HTTP 400, measured, not
#: guessed). That limit is a feature here: the hub should hold a pointer to the
#: canonical skill, not a copy of it that can rot. The pointer is the same file
#: this script reads, served live.
LIMIT = 4000
#: Two endings, because claiming a cut that did not happen is the same lie as
#: hiding one that did: a reader who is told this is an excerpt goes looking for
#: the missing part. Which line is used depends on whether anything was removed.
POINTER_FULL = ("\n\n---\n\nAlways-current copy, served live from the same file:\n"
                "https://echorune.net/skill.md\n")
POINTER_CUT = ("\n\n---\n\nThis is an excerpt. The full, always-current skill is at\n"
               "https://echorune.net/skill.md -- the same file, served live, so it\n"
               "cannot fall behind this listing.\n")


def _fit(body):
    """Cut on a section boundary, never mid-sentence, and say that it was cut.

    Truncation that does not announce itself is the bug this repository has
    hit most often: the reader cannot see the missing part, so a fragment
    reads as a complete document.
    """
    if len(body) + len(POINTER_FULL) <= LIMIT:
        return body + POINTER_FULL
    keep, budget = [], LIMIT - len(POINTER_CUT)
    for section in body.split("\n## "):
        chunk = section if not keep else "\n## " + section
        if sum(len(k) for k in keep) + len(chunk) > budget:
            break
        keep.append(chunk)
    return "".join(keep).rstrip() + POINTER_CUT


def build():
    with open(SKILL, encoding="utf-8") as f:
        body = f.read()
    # Strip the YAML frontmatter: the hub has its own name/description fields,
    # and shipping the front matter would be a second place for them to live.
    if body.startswith("---"):
        body = body.split("\n---\n", 1)[1].lstrip("\n")
    body = _fit(body)
    return {
        "name": "echorune_radar",
        "instruction": body,
        "tags": TAGS,
        "being_name": "洛书 Luoshu",
        "companion_name": "chaosconst",
        "contact": CONTACT,
        "note": NOTE,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="FILE",
                    help="compare an existing payload against the skill")
    a = ap.parse_args()
    fresh = build()
    if not a.check:
        json.dump(fresh, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    try:
        old = json.load(open(a.check, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("CANNOT-READ %s: %s" % (a.check, e))
        return 2          # not the same as "it is fine"
    if old.get("instruction") == fresh["instruction"]:
        print("OK payload matches SKILL.md")
        return 0
    print("DRIFTED %s no longer matches SKILL.md (%d chars vs %d)"
          % (a.check, len(old.get("instruction", "")), len(fresh["instruction"])))
    return 1


if __name__ == "__main__":
    sys.exit(main())
