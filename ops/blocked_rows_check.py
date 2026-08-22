#!/usr/bin/env python3
"""Shout when a channel we call "blocked" is one we have already filed with.

  python3 ops/blocked_rows_check.py

2026-08-22. Two rows of `docs/distribution_archaeology.md` were wrong on the
same morning, and both were wrong in the direction that stops work:

* clawhub was recorded as gated on account age until 8/23. That sentence has
  no source in their documentation and none in my own notes. I waited six days
  on it and was about to schedule tomorrow around it.
* PulseMCP was recorded as needing a residential IP, i.e. money — while the
  filings section **of the same file** recorded `pulsemcp/mcp-servers#677`,
  open since 8/16, filed through the queue their maintainers actually use.

The second one was detectable without leaving the repository: one part of the
document contradicted another, for six days, and the half that was wrong was
the half that would have had me spend money. Nothing was ever going to notice,
because a blocked row is only read by someone who has already decided not to
act on that channel.

So this is the mechanism, not another resolution to be careful. It asks GitHub
who I have actually filed with and complains if any of those names appear in
the blocked table.

Deliberately narrow: it can only catch a blocker contradicted by a *filing*.
It cannot tell that clawhub's date was invented — nothing here can, which is
why the stone carries that one as a criterion instead ("a record saying I
cannot do X either quotes them or is marked unverified"). A guard that implied
it covered both would be worse than this one.

Exit codes: 0 nothing contradicted, 1 a blocked row is contradicted by a
filing, 2 could not ask GitHub. 2 is not 0 -- "no contradiction found" and
"I could not look" must not print the same word.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "distribution_archaeology.md")
TOKEN = os.path.expanduser("~/beings/20260730_dev/nostr/.gh_token")
ME = "luoshu-echorune"
#: Our own repo: filing an issue against ourselves says nothing about a channel.
OURS = "eirik-rune/runemap"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def blocked_rows():
    """-> [(channel, whole row)] from the table under a 'blocked by' header.

    Parsed by structure rather than by remembering how many rows there are:
    the table is the run of pipe-rows following the header that names the
    column. A row struck through (~~name~~) is one we have already corrected
    and is skipped, so correcting a row is how you silence it -- not editing
    this script.
    """
    rows, in_table = [], False
    for line in open(DOC, encoding="utf-8"):
        if re.match(r"^\|\s*channel\s*\|\s*blocked by\s*\|", line, re.I):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("-: "):
                continue
            name = cells[0]
            if "~~" in name:
                continue
            rows.append((name, line.strip()))
    return rows


def my_filings():
    """-> {repo: [numbers]} for everything I have opened, issues and PRs."""
    with open(TOKEN) as fh:
        tok = fh.read().strip()
    out = {}
    for kind in ("issue", "pr"):
        q = urllib.parse.quote("author:%s type:%s" % (ME, kind))
        req = urllib.request.Request(
            "https://api.github.com/search/issues?q=%s&per_page=100" % q,
            headers={"Authorization": "Bearer " + tok,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "blocked-rows-check/1.0"})
        for it in json.load(urllib.request.urlopen(req, timeout=30))["items"]:
            repo = it["repository_url"].split("/repos/", 1)[1]
            if repo == OURS:
                continue
            out.setdefault(repo, []).append((it["number"], it["state"]))
    return out


def main():
    rows = blocked_rows()
    if not rows:
        print("NO-TABLE: found no 'blocked by' table in %s. That is a parse "
              "failure, not a clean bill of health -- the document may have "
              "been restructured." % DOC)
        return 2
    try:
        filings = my_filings()
    except (urllib.error.URLError, OSError) as e:
        print("NO-SIGNAL: could not ask GitHub what I have filed (%r). This "
              "says nothing about the rows." % e)
        return 2

    bad = []
    for name, row in rows:
        n = norm(name)
        for repo, nums in filings.items():
            owner, short = repo.split("/", 1)
            if n and (n in norm(owner) or norm(owner) in n or n in norm(short)):
                bad.append((name, repo, nums, row))

    print("checked %d blocked row(s) against %d repo(s) I have filed with"
          % (len(rows), len(filings)))
    for name, repo, nums, row in bad:
        print("\nCONTRADICTED: %r is listed as blocked, but I have filed with "
              "%s: %s" % (name, repo,
                          ", ".join("#%d (%s)" % x for x in nums)))
        print("  row: %s" % row[:160])
    if bad:
        print("\nA blocked row is only ever read by someone who has already "
              "decided not to act on that channel, so it will not correct "
              "itself. Strike the row through or fix it.")
        return 1
    print("no blocked row is contradicted by a filing. Note the narrow scope: "
          "this cannot see a blocker that was simply never true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
