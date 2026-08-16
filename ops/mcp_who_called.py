#!/usr/bin/env python3
"""Listed, or used? Read the MCP call log and refuse to conflate the two.

Within an hour of the official registry entry going live, five distinct outside
clients hit `/mcp`. Every one sent `initialize`, then `tools/list`, then stopped:
directory crawlers and health probes. In an access log that is indistinguishable
from a real client warming up, and reporting it as demand would be the same
error as counting a bought star -- a number that flatters us and measures
nothing.

So the only line that matters here is `tools/call` **from outside our own
machines**. Everything else is printed, because a crawler arriving is real
information about distribution; it is just not information about use.

Exit 0 when the log could be read, 2 when it could not. Never 1: there is no
failing state, only a count that may be zero, and zero is an honest answer.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

DEFAULT = os.path.join(os.environ.get("RUNEMAP_CACHE", "/var/cache/runemap"),
                       "mcp_calls.jsonl")

#: Our own machines. Imported, never copied: the first version of this file
#: declared its own tuple *while its docstring said a second list drifts from
#: the first and both look reasonable alone*. Writing the rule down did not stop
#: me typing the duplicate four lines later, which is the argument for making it
#: structurally impossible rather than remembered.
#:
#: who_is_using.py is the single source because it is the one that reads nginx's
#: logs, where the addresses are written in the form being compared.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from who_is_using import INSIDER_NETS  # noqa: E402

#: nginx zeroes the last octet in its logs ("139.162.58.0"); the MCP ledger
#: records the address as sent. Compare on the network part, which both agree on.
INSIDERS = tuple(k.rsplit(".", 1)[0] + "." for k in INSIDER_NETS) + ("127.0.0.1", "::1")


def ours(ip):
    return any(ip == i or ip.startswith(i) for i in INSIDERS)


def tool_name():
    """The tool this server advertises, read from the server itself.

    Importing serve.py would need its whole environment (it exits without a
    token), so the name is lifted from the source. Raises rather than guessing:
    a default here would silently reclassify every real call as a probe on the
    day the tool is renamed, which is the failure this whole file exists to
    avoid.
    """
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "scripts", "serve.py"), encoding="utf-8").read()
    m = re.search(r'_MCP_TOOL\s*=\s*\{\s*"name":\s*"([^"]+)"', src)
    if not m:
        raise SystemExit("cannot find the advertised tool name in serve.py -- "
                         "refusing to guess, because guessing turns every real "
                         "call into a 'probe' without saying so")
    return m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT)
    a = ap.parse_args()
    try:
        rows = [json.loads(x) for x in open(a.log, encoding="utf-8") if x.strip()]
    except OSError as e:
        # "I cannot read it" must not share an exit code with "nobody called".
        print("NO-LOG %s: %s" % (a.log, e))
        return 2

    outside = [r for r in rows if not ours(r.get("ip", ""))]
    methods = Counter(r.get("method") for r in outside)

    # A tools/call is not automatically use. The first outside call this server
    # ever received asked for `__verifymcp_auth_probe_1f9090822a209ed8__` -- a
    # directory checking whether we demand authentication by calling a name that
    # cannot exist. Counting that as our first user would have been this tool
    # reporting exactly the thing it was written to prevent, on its first day.
    #
    # The advertised name is read out of the server rather than typed here: a
    # second copy would agree today and drift the moment the tool is renamed,
    # and then this report would quietly reclassify every real call as a probe.
    advertised = tool_name()
    calls = [r for r in outside
             if r.get("method") == "tools/call" and r.get("tool") == advertised]
    probes = [r for r in outside
              if r.get("method") == "tools/call" and r.get("tool") != advertised]

    print("%d MCP requests logged, %d from outside our machines\n"
          % (len(rows), len(outside)))
    for m, n in methods.most_common():
        print("  %-28s %d" % (m, n))

    print("\nOutside clients, by user agent")
    for ua, n in Counter(r.get("ua") or "(none)" for r in outside).most_common(10):
        print("  %4d  %s" % (n, ua[:88]))

    if probes:
        print("\ntools/call for a tool we do not advertise -- checkers, not users")
        for r in probes[-6:]:
            print("  tool=%s  ua=%s" % (str(r.get("tool"))[:44],
                                        (r.get("ua") or "")[:40]))
    if calls:
        print("\ntools/call for %r from outside -- this is the only bucket that is use"
              % advertised)
        for r in calls[-10:]:
            print("  %s  ua=%s" % (r.get("at"), (r.get("ua") or "")[:50]))
    print("\nThe honest sentence: %d outside client(s) have introspected this server, "
          "%d made a\ncall to a tool that does not exist (checking us, not using us), and "
          "%d actually\ncalled %r. Being listed, being checked, and being used are three "
          "numbers; only\nthe last one is the product's." %
          (len(set(r.get("ip") for r in outside)), len(probes), len(calls), advertised))
    return 0


if __name__ == "__main__":
    sys.exit(main())
