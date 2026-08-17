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

#: The official MCP registry name, which is how the directories that ingest the
#: registry address us. Not typed twice: it is the namespace we published.
REGISTRY_NAME = "io.github.luoshu-echorune/echorune-radar"

#: A direct URL beats a search page whenever one exists. Glama's search echoes
#: the query back into the page (input value, results heading, embedded JSON),
#: so counting hits there can only ever return NO-SIGNAL -- the ruler cannot
#: tell absent from listed. The connector URL can: ours 404s and so does a
#: namespace that cannot exist, with byte-identical bodies, which is a real
#: ABSENT rather than a shrug. Directory pages are addressed by registry name
#: because that is what the ingesting directories key on.
DIRECT = [
    ("glama-connector", "https://glama.ai/mcp/connectors/" + REGISTRY_NAME,
     "https://glama.ai/mcp/connectors/io.github.zzqqx-nothing/zzqqx-nothing"),
    # 2026-08-16. Added the day mcpservers.org approved us -- and the point is
    # that this watcher did NOT catch it. An email did.
    #
    # The list above grew out of the directories I had submitted to and been
    # *refused* or *unable to read*. mcpservers.org was submitted and pending,
    # i.e. **the single entry most likely to change was the one not being
    # watched**. A watcher assembled from where I got stuck covers everything
    # except the thing it exists for.
    ("mcpservers.org", "https://mcpservers.org/servers/eirik-rune/runemap",
     "https://mcpservers.org/servers/eirik-rune/runemap-control-does-not-exist"),
]

#: The same connector page, asked a different question: has Glama finished
#: scoring us? Separate constant because it is a separate question -- reusing
#: DIRECT's would have put a comment about "a direct URL beats a search page"
#: above a probe that is not about being listed at all.
SCORE_URL = os.environ.get(
    "RUNEMAP_GLAMA_SCORE_URL",
    "https://glama.ai/mcp/connectors/" + REGISTRY_NAME)

SITES = [
    ("glama-search", "https://glama.ai/mcp/servers?query=%s"),
    ("mcp.so", "https://mcp.so/search?q=%s"),
    ("smithery", "https://smithery.ai/?q=%s"),
    ("skills.sh", "https://skills.sh/api/search?q=%s"),
]

#: Every probe this file can print, in one place. The daily wrapper, the
#: summary line and the tests all ask HERE rather than each rebuilding the set
#: from SITES + DIRECT + whatever was added last -- a second list is how two
#: readers of the same fact quietly disagree. Adding glama-score without this
#: broke the "printed implies stored" test, which is exactly what that test is
#: for: a probe outside the enumeration is a probe the bell cannot see.
def probe_names():
    names = [n for n, *_ in SITES] + [n for n, *_ in DIRECT]
    if SCORE_URL:
        names.append("glama-score")
    return names


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

    # Direct-URL probes, each with its own control that cannot exist. A page
    # that 404s identically for us and for the control is ABSENT; a page that
    # exists for us and not the control is LISTED. No counting of echoes.
    for name, mine_url, ctrl_url in DIRECT:
        mine, why = fetch(mine_url)
        ctrl, why2 = fetch(ctrl_url)
        if mine is None and ctrl is None:
            verdict, detail = "ABSENT", "both 404 (%s) -- control agrees" % why
        elif mine is not None and ctrl is None:
            verdict, detail = "LISTED", "our page exists, control 404s"
        elif mine is None and ctrl is not None:
            # The control resolving while we do not is the ruler misbehaving,
            # not evidence about us.
            verdict, detail = "NO-SIGNAL", "control resolved but we did not -- suspect the probe"
            unreachable += 1
        else:
            verdict, detail = "NO-SIGNAL", "both resolved; this URL does not discriminate"
            unreachable += 1
        now[name] = verdict
        if was.get(name) != verdict:
            changed.append((name, was.get(name), verdict))
        if not a.quiet or was.get(name) != verdict:
            print("%-16s %-12s %s" % (name, verdict, detail))

    # The last gate on the biggest channel left, asked here so that nothing
    # depends on me remembering to look.
    #
    # punkpeye/awesome-mcp-servers (92k stars) wants a Glama quality badge.
    # Glama listed us on 8/17 05:23Z and the score has read "being calculated"
    # ever since. Listing and scoring are two events; only the first happened,
    # and the submission is gated on the second.
    #
    # This asks by absence, which is fragile on purpose-built pages: if they
    # redesign and drop that sentence, absence would read as "the score
    # arrived". So the page must first prove it is still OUR page -- that is the
    # control, and without it this probe would answer a question about Glama's
    # CSS while sounding like an answer about us.
    if SCORE_URL:
        page, why = fetch(SCORE_URL)
        if page is None:
            verdict, detail = "NO-SIGNAL", "cannot read the connector page (%s)" % why
            unreachable += 1
        elif "echorune" not in page.lower():
            verdict, detail = ("NO-SIGNAL",
                               "page loaded but is not ours -- the shape changed, "
                               "so absence of the pending text proves nothing")
            unreachable += 1
        elif "being calculated" in page:
            verdict, detail = "ABSENT", "score still being calculated"
        else:
            verdict, detail = "LISTED", "the pending text is gone -- score may be up, go look"
        now["glama-score"] = verdict
        if was.get("glama-score") != verdict:
            changed.append(("glama-score", was.get("glama-score"), verdict))
        if not a.quiet or was.get("glama-score") != verdict:
            print("%-16s %-12s %s" % ("glama-score", verdict, detail))

    # Persist AFTER every probe has had its say. This used to sit above the
    # DIRECT loop, which meant the file the bell reads was frozen halfway
    # through: DIRECT verdicts were printed to stdout and never stored.
    #
    # It cost nothing until it cost everything. mcpservers.org approved us --
    # the first directory listing in this whole push -- and the watcher stayed
    # silent, because the only channel it consults had never heard of that
    # probe. **The report said LISTED and the bell could not see it.**
    #
    # Same family as a check that cannot fail, one step further along: this one
    # could fail, did fail, said so out loud, and the alarm was wired to a
    # different data source than the report.
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(now, f)
        os.replace(tmp, STATE)
    except OSError as e:
        sys.stderr.write("LISTED-STATE-UNWRITABLE %s: %s\n" % (STATE, e))

    # The count is over DIRECTORIES only. glama-score shares the LISTED word so
    # that the daily wrapper, which rings on changes to that set, needs no new
    # machinery -- but it is a different question, and counting it here would
    # say "5 of 6 directories" while one of the five is a score. That is the
    # same collapse ops/mcp_who_called.py exists to prevent: two kinds of thing
    # summed because they happened to share a label.
    dirnames = set(probe_names()) - {"glama-score"}
    listed = [n for n, v in now.items() if v == "LISTED" and n in dirnames]
    if not a.quiet:
        print("\n%d of %d directories list us%s. Being ingested is not being "
              "used -- ops/mcp_who_called.py answers that one."
              % (len(listed), len(dirnames),
                 " (%s)" % ", ".join(listed) if listed else ""))
        if "glama-score" in now:
            print("glama-score is not a directory: %s (it gates "
                  "punkpeye/awesome-mcp-servers#12255)" % now["glama-score"])
    for name, before, after in changed:
        if after == "LISTED" and before not in (None, "LISTED"):
            print("CHANGE %s now lists us (was %s)" % (name, before))
    return 2 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
