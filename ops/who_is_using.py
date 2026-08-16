#!/usr/bin/env python3
"""Who is actually calling this service — and who we cannot classify.

Written 2026-08-16, before distributing the Agent Skill rather than after.
The reason is on my stone in blunter words: if I ship to four channels first,
the only thing I can report afterwards is "I published in four places", which
is activity, not result. A promoted service with no idea whether anyone arrived
is the same object as a bought star or a health check that always returns 200 —
a number that flatters us and measures nothing.

**This measurement is entirely ours.** Whether strangers can *see* our posts on
someone else's platform, I cannot measure: from a datacentre exit Reddit answers
403 to our posts and to a control alike, and v2ex shows a sign-in page for our
thread and for other people's threads alike. Both are "I cannot tell", not
"we are hidden". But who calls *us* is in our own access log, needs nobody's
permission, and cannot be faked by a platform being moody.

Five buckets, because four of them are things I would otherwise have reported
as demand for the product:

    OURS               an explicitly listed machine of ours
    CRAWLER            a known indexer, by user agent
    SCANNER            probing for software we do not run (/wp-admin, /.env)
    ASKED-FOR-WEATHER  asked for something we serve, and got it
    UNCLASSIFIED       could not place

**ASKED-FOR-WEATHER is not a synonym for "users", and neither is UNCLASSIFIED.**
The reason these are separate buckets at all is that on 2026-08-06 I counted a GitHub star as an external signal
when it was bob's own account, and on 2026-08-14 I nearly announced a fellow
being as our first external user when we share a human. Both errors pointed the
flattering way. So an unclassified hit is printed as exactly that, and any
report that turns it into a customer has to do so out loud.

Insiders are listed explicitly, never inferred, because "external" is not a
field in the data — it is a judgement, and judgements that live in a heuristic
drift silently.
"""
import argparse
import glob
import gzip
import os
import re
import sys
from collections import Counter

#: Our own machines. First octets-with-zeroed-last, matching how nginx logs them.
#: Add here, not to a regex somewhere else: a second list drifts from the first
#: and both look reasonable on their own.
INSIDER_NETS = {
    "139.162.58.0": "echorune-1 (this server: status checks, health probes, my curls)",
    "3.114.3.0": "tokyo aws (my only eye outside this machine)",
    "127.0.0.0": "localhost -- nginx health probes and my own curls on the box",
}

#: Substrings identifying indexers. Not users, not nothing — a third thing.
CRAWLER_UA = ("googlebot", "bingbot", "yandex", "baiduspider", "ahrefs",
              "semrush", "petalbot", "duckduckbot", "applebot", "facebookexternalhit",
              "bytespider", "gptbot", "claudebot", "ccbot", "perplexitybot",
              "amazonbot", "dataforseo", "censys", "expanse", "internet-measurement")

#: Substrings that suggest a program rather than a person at a browser. Weak
#: evidence and labelled as such: a real browser can send any string it likes,
#: and an agent behind a proxy may look like Chrome.
AGENTISH_UA = ("curl", "wget", "python", "httpie", "go-http", "node-fetch",
               "axios", "okhttp", "java/", "ruby", "libwww", "aiohttp", "requests")

LOG_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \[(?P<t>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) [^"]*" '
    r'(?P<status>\d+) (?P<size>\S+) "(?P<ua>[^"]*)"')


def read_lines(paths):
    for p in paths:
        opener = gzip.open if p.endswith(".gz") else open
        try:
            with opener(p, "rt", errors="replace") as f:
                for line in f:
                    yield line
        except OSError as e:
            # Report and continue: a log we cannot read must not be silently
            # equivalent to a log with no traffic in it.
            print("  !! could not read %s: %s" % (p, e), file=sys.stderr)


#: Paths nobody asks for by accident. Scanning for somebody else's software is
#: not a visit; counting it as one inflated the first run of this tool by about
#: tenfold, and the evidence was sitting in its own output -- 2441 requests for
#: /wp-admin/install.php on a service that has never run WordPress.
SCANNER_PATH = ("/wp-", "/wordpress", "/.env", "/.git", "/vendor/", "/phpmyadmin",
                "/admin", "/xmlrpc.php", "/shell", "/cgi-bin", "/.aws",
                "/config.json", "/.ssh", "/actuator", "/solr", "/boaform",
                "/hudson", "/jenkins", "/console", "/.vscode", "/telescope",
                "/mobile/promotion", "/api/", "/v2/_catalog", "/login", "/owa/")
SCANNER_UA = ("apachebench", "libredtail", "zgrab", "masscan", "nmap", "nuclei",
              "sqlmap", "wpscan", "httrack", "l9explore", "netsystemsresearch")


def classify(ip, ua, path, status):
    """Five buckets, because four of them are things I would otherwise have
    reported as demand for the product."""
    if ip in INSIDER_NETS:
        return "OURS"
    low, lp = ua.lower(), path.lower()
    if any(c in low for c in CRAWLER_UA):
        return "CRAWLER"
    if any(c in low for c in SCANNER_UA) or any(c in lp for c in SCANNER_PATH):
        return "SCANNER"
    # Asked for something this service actually serves, and got it. This is the
    # only bucket that could ever be a user -- and it still is not proof of one,
    # which is why it is not called "users".
    if status == "200" and not lp.startswith(("/favicon", "/robots", "/apple-touch")):
        return "ASKED-FOR-WEATHER"
    return "UNCLASSIFIED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="/var/log/nginx/access.log*")
    ap.add_argument("--path-filter", default=None,
                    help="only count requests whose path contains this")
    a = ap.parse_args()

    paths = sorted(glob.glob(a.logs))
    if not paths:
        print("NO-LOGS %s matched nothing -- this is 'I cannot tell', "
              "not 'nobody came'" % a.logs)
        return 2

    buckets = Counter()
    cand_ips = Counter()
    cand_ua = Counter()
    agentish = Counter()
    paths_seen = Counter()
    total = unparsed = 0
    first_t = last_t = None

    for line in read_lines(paths):
        m = LOG_RE.match(line)
        if not m:
            unparsed += 1
            continue
        if a.path_filter and a.path_filter not in m.group("path"):
            continue
        total += 1
        t = m.group("t")
        if first_t is None or t < first_t: first_t = t
        if last_t is None or t > last_t: last_t = t
        ip, ua = m.group("ip"), m.group("ua")
        b = classify(ip, ua, m.group("path"), m.group("status"))
        buckets[b] += 1
        if b == "ASKED-FOR-WEATHER":
            cand_ips[ip] += 1
            cand_ua[ua[:60]] += 1
            paths_seen[m.group("path")[:44]] += 1
            low = ua.lower()
            agentish["program-like" if any(x in low for x in AGENTISH_UA)
                     else "browser-like-or-unknown"] += 1

    print("logs read      : %d file(s), %d requests parsed" % (len(paths), total))
    # n without a denominator is a number that sounds like whatever you want it
    # to. Print the window the count covers, from the data, not from assumption.
    print("window         : %s  ->  %s" % (first_t or "?", last_t or "?"))
    if unparsed:
        # Never silent: an unparsed line is a request we did not judge.
        print("unparsed lines : %d  (not counted anywhere -- format drift?)"
              % unparsed)
    if a.path_filter:
        print("path filter    : contains %r" % a.path_filter)
    print()
    for name, why in (("OURS", "explicitly listed insiders"),
                      ("CRAWLER", "known indexers, by user agent"),
                      ("SCANNER", "probing for other people's software"),
                      ("ASKED-FOR-WEATHER", "asked for something we serve, got 200"),
                      ("UNCLASSIFIED", "could not place -- NOT 'users'")):
        print("  %-13s %6d   %s" % (name, buckets[name], why))

    print("\nASKED-FOR-WEATHER, split by how program-like the agent string is")
    print("  (weak evidence: a browser can send any string, an agent can hide)")
    for k, v in agentish.most_common():
        print("    %-26s %d" % (k, v))

    print("\nASKED-FOR-WEATHER sources (top 10, last octet zeroed by nginx)")
    for ip, n in cand_ips.most_common(10):
        print("    %-18s %d" % (ip, n))

    print("\nASKED-FOR-WEATHER user agents (top 8)")
    for ua, n in cand_ua.most_common(8):
        print("    %4d  %s" % (n, ua or "(empty)"))

    print("\nwhat they asked for (top 8)")
    for p, n in paths_seen.most_common(8):
        print("    %4d  %s" % (n, p))

    print("\nThe honest sentence: %d requests came from outside our own machines,\nasked for something we actually serve, and got it. That is an UPPER BOUND on\nreal users -- it still contains anyone we failed to list as an insider, and\nbob's own phone. It is the only number here that could ever become evidence\nthat a stranger needs this." % buckets["ASKED-FOR-WEATHER"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
