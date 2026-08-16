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
import sys
from collections import Counter

DEFAULT = os.path.join(os.environ.get("RUNEMAP_CACHE", "/var/cache/runemap"),
                       "mcp_calls.jsonl")

#: Our own machines, by the address the server sees. Kept here rather than
#: inferred: "external" is a judgement, and judgements inside a heuristic drift
#: silently. Same list, same reason, as ops/who_is_using.py.
INSIDERS = ("127.0.0.1", "::1", "139.162.58.", "3.114.3.")


def ours(ip):
    return any(ip == i or ip.startswith(i) for i in INSIDERS)


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
    calls = [r for r in outside if r.get("method") == "tools/call"]

    print("%d MCP requests logged, %d from outside our machines\n"
          % (len(rows), len(outside)))
    for m, n in methods.most_common():
        print("  %-28s %d" % (m, n))

    print("\nOutside clients, by user agent")
    for ua, n in Counter(r.get("ua") or "(none)" for r in outside).most_common(10):
        print("  %4d  %s" % (n, ua[:88]))

    if calls:
        print("\ntools/call from outside -- this is the only bucket that is use")
        for r in calls[-10:]:
            print("  %s  tool=%s  ua=%s" % (r.get("at"), r.get("tool"),
                                            (r.get("ua") or "")[:50]))
    print("\nThe honest sentence: %d outside clients have introspected this server; "
          "%d have\nactually called the tool. Being listed and being used are "
          "different numbers, and\nthe second one is the product's." %
          (len(set(r.get("ip") for r in outside)), len(calls)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
