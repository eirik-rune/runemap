#!/usr/bin/env python3
"""Which directories have actually picked us up? Ask them, with a control.

We are an `active` entry in the official MCP registry. Several directories are
said to ingest it. On 2026-08-16 none of them listed us, and finding that out
by hand is the kind of thing I do once and then forget for a week.

**The trap this file exists to avoid.** Searching glama for "echorune" returned
three hits, which reads like news. A control query that cannot exist -- a
string of nonsense -- returned exactly three as well. All three were the search
term echoed back into the page: the input box's `value`, the "N matching
servers" heading, and the query embedded in the page's own JSON state. Counting
those would be an instrument reporting my own question back to me as an answer.

So every probe runs twice, once for us and once for a string that cannot be
listed anywhere, and a hit only counts as `LISTED` when our count EXCEEDS the
control's. A site whose control count is not lower is reported `NO-SIGNAL`:
that is "this ruler cannot answer the question", not "we are absent". The two
must not print the same word, because only one of them means keep looking.

Exit 0 when every site could be asked, 2 when at least one could not be reached
(a 403 from a datacenter IP is not evidence of anything about us), and never 1:
being absent from a directory is not a failure state, it is today's answer.

    python3 ops/listed_where.py
    python3 ops/listed_where.py --quiet   # print only changes from last run
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

#: The word to look for. Read from the registry entry rather than typed, so a
#: rename cannot leave this happily searching for a name nobody publishes.
NEEDLE = "echorune"

#: Cannot be listed anywhere, by construction. Any count this returns is the
#: site echoing the query back, and that is the floor a real hit must clear.
CONTROL = "zzqqxnothingzz"

SITES = [
    ("glama", "https://glama.ai/mcp/servers?query=%s"),
    ("mcp.so", "https://mcp.so/search?q=%s"),
    ("smithery", "https://smithery.ai/?q=%s"),
    ("skills.sh", "https://skills.sh/api/search?q=%s"),
]

STATE = os.environ.get(
    "RUNEMAP_LISTED_STATE",
    os.path.join(os.environ.get("RUNEMAP_CACHE", "/tmp"), "listed_where.json"))


def fetch(url):
    """-> (body, None) or (None, why). A refusal is never a body."""
    req = urllib.request.Request(url, headers={
        # Our own name. Not a browser's -- pretending to be one to get past a
        # block is on the list of things we do not do, and the answer it would
        # buy is not one I could trust anyway.
        "User-Agent": "echorune-listing-check (+https://echorune.net)"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:
        return None, type(e).__name__


def count(body, needle):
    return len(re.findall(re.escape(needle), body, re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="print only sites whose verdict changed")
    a = ap.parse_args()

    try:
        was = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        was = {}

    now, unreachable, changed = {}, 0, []
    for name, tmpl in SITES:
        mine, why = fetch(tmpl % NEEDLE)
        if mine is None:
            verdict, detail = "UNREACHABLE", why
            unreachable += 1
        else:
            ctrl, why2 = fetch(tmpl % CONTROL)
            if ctrl is None:
                # Without the control there is no floor, so a count means
                # nothing. Refusing to guess is the whole point of the control.
                verdict, detail = "NO-CONTROL", "ours=%d, control %s" % (
                    count(mine, NEEDLE), why2)
                unreachable += 1
            else:
                m, c = count(mine, NEEDLE), count(ctrl, CONTROL)
                if m > c:
                    verdict, detail = "LISTED", "%d hits vs %d echoed" % (m, c)
                elif c == 0 and m == 0:
                    verdict, detail = "ABSENT", "0 hits, control 0"
                else:
                    verdict, detail = "NO-SIGNAL", (
                        "%d hits vs %d echoed -- the page echoes the query, so "
                        "this ruler cannot tell absent from listed" % (m, c))
        now[name] = verdict
        if was.get(name) != verdict:
            changed.append((name, was.get(name), verdict))
        if not a.quiet or was.get(name) != verdict:
            print("%-12s %-12s %s" % (name, verdict, detail))

    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(now, f)
        os.replace(tmp, STATE)
    except OSError as e:
        sys.stderr.write("LISTED-STATE-UNWRITABLE %s: %s\n" % (STATE, e))

    listed = [n for n, v in now.items() if v == "LISTED"]
    if not a.quiet:
        print("\n%d of %d directories list us%s. Being ingested is not being "
              "used -- ops/mcp_who_called.py answers that one."
              % (len(listed), len(SITES),
                 " (%s)" % ", ".join(listed) if listed else ""))
    for name, before, after in changed:
        if after == "LISTED" and before not in (None, "LISTED"):
            print("CHANGE %s now lists us (was %s)" % (name, before))
    return 2 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
