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
import urllib.parse
from collections import Counter, defaultdict

#: Words a caller uses to say, in its own user agent, that it is checking us.
#: It lives here rather than in mcp_who_called because the dependency already
#: runs that way (that module imports INSIDER_NETS from this one), and because
#: this file is where "how we classify a caller" belongs. One list, two readers:
#: two lists of words-meaning-checker would each look reasonable and drift.
#:
#: 2026-08-19 additions -- "liveness", "uptime", "heartbeat" -- came from the
#: site log, where `SentinelOracle/0.1 (+https://glimind.com/opt-out;
#: liveness-check)` at 1196 requests and `mcpbeat/0.1 (+https://mcpbeat.com/bot/;
#: liveness check)` at 438 were the two loudest entries in the bucket named
#: "could be users". They said what they were and this list lacked the word.
#: `scan` rather than `scanner`: Palo Alto's Xpanse announces itself as "find
#: out more about our scans", and one missing letter put a self-identifying
#: internet-wide scanner into the bucket named "could be users" for two weeks.
#: A word that is one inflection short is a namelist pretending to be a rule.
_AUDITY = ("audit", "scan", "probe", "verify", "monitor", "healthcheck",
           "liveness", "uptime", "heartbeat")


def self_declared_checker(ua):
    """Does this caller say, in its own user agent, that it is checking us?

    A claim, never proof. Callers must SPLIT on it and print both sides, never
    filter: a real user whose agent string happens to contain "monitor" would
    otherwise vanish from the only number that could ever become evidence that
    a stranger needs this.
    """
    return any(w in (ua or "").lower() for w in _AUDITY)


#: Words a crawler uses about itself. `CRAWLER_UA` below is a list of NAMES and
#: will always be one name behind; this is the shape they share.
_CRAWLERY = ("bot", "crawler", "spider", "webindex", "indexer")


def self_declared_crawler(ua):
    """Does this caller say, in its own user agent, that it indexes rather
    than uses?

    Added 2026-08-20 after measuring which callers came back on more than one
    day -- the intuition being that returning costs a crawler nothing but is
    the cheapest thing a person can spend that an indexer will not. The top
    returners were `MJ12bot`, `agent-tools.cloud-crawler`, `PubkyWebIndex` and
    a Palo Alto Networks scanner: every one of them says what it is, and
    `CRAWLER_UA` simply did not contain those four names. A namelist is always
    one name behind, and every name it lacks lands in the bucket that flatters
    us.

    The `+http` clause is the load-bearing one: putting a contact URL in the
    user agent is a convention indexers follow and people's browsers do not,
    so it catches the ones whose names nobody has heard of yet.

    Same contract as `self_declared_checker`: a claim, not proof, and callers
    must SPLIT on it and print both sides rather than filter. `Bun/1.1.45` and
    `node` do not match here and must not -- an agent built on a runtime is the
    reader we are trying to find.
    """
    low = (ua or "").lower()
    return "+http" in low or any(w in low for w in _CRAWLERY)

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


def insider(ip):
    """Which insider /24 this address belongs to, or None.

    This replaced an exact string match (`ip in INSIDER_NETS`) on 2026-08-20,
    and **the exact match was not broken** -- nginx here anonymises the client
    address to its /24 before writing it, so every address in the log already
    ends in `.0` and matched the keys by construction. Measured rather than
    assumed: 6486 lines of access.log.3.gz, zero addresses not ending in `.0`.

    I claimed the opposite first, and the way I got there is worth keeping.
    I fired the check with hand-typed addresses (`3.114.3.152`) that do not
    occur in any log, watched them fall through to ASKED-FOR-WEATHER, and
    concluded the insider list had never matched. **Names must be taken from
    the source text, never typed from memory** -- a rule already on the stone,
    broken here while writing a positive control, which is the one place a
    fabricated input turns straight into a fabricated finding.

    What survives is a narrower reason to keep this version: the exact match is
    correct *only because* something upstream of us anonymises. That is a
    property of an nginx config, not of this program, and if it is ever turned
    off our own traffic re-enters the acceptance bucket silently and in our
    favour. Deriving the network here makes the check depend on nothing but the
    address. Deliberately /24 and no wider: a /16 would swallow strangers who
    share a datacentre range with us, and calling a real user "ours" shrinks
    the only number that matters.
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return None                      # IPv6 or a malformed line: not ours
    return INSIDER_NETS.get(".".join(parts[:3]) + ".0")


def classify(ip, ua, path, status):
    """Five buckets, because four of them are things I would otherwise have
    reported as demand for the product."""
    if insider(ip):
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


#: Paths that are ours rather than a place: asking for these says nothing about
#: whether anyone wanted to know the weather anywhere.
NOT_A_PLACE = ("", "/", "/mcp", "/status", "/help", "/robots.txt",
               "/favicon.ico", "/index.html", "/sitemap.xml", "/en", "/old")


def repeat_city(paths):
    """How many callers asked for the SAME named place on two separate days?

    Everything else this file counts answers "was there traffic". This is the
    narrowest thing in the logs that could mean somebody wanted an answer:
    returning costs an indexer nothing, but coming back for *one particular
    place* is what a person does who has a reason to care about that place.
    It was suggested by a stranger replying to a public note on 2026-08-20,
    who put it as: requests/day measures indexing, settled calls measure
    demand. I would not put a price on the endpoint -- one request with no key
    and no account is the product -- so this is the version of that idea which
    costs the caller nothing but repetition.

    First run, 15 days of retained logs: **114 (caller, place) pairs, 5 of them
    repeated across days, and four of the five did not survive being looked at**
    -- a lead-scraper sweeping /contact /kontakt /impressum in a dozen
    languages, two GCP addresses running curl, and a junk path. One browser
    asking for the same city on two days is left, and it is not confirmed to be
    a person either.

    So the number this prints is an UPPER BOUND with a very small ceiling, and
    printing the pairs matters more than printing the count: every time today
    that a number here looked like people, reading the rows showed machines.
    """
    seen = defaultdict(set)
    agents = defaultdict(set)
    hits = defaultdict(int)
    #: "I could not ask" and "everyone who asked was a machine" are different
    #: answers and must not print the same page. Caught by a test whose
    #: expectation looked wrong and was not: excluding every caller produced
    #: the sentence meaning "check your log glob", which would send the next
    #: reader to fix a path when the finding was that nobody human came.
    excluded = 0
    for line in read_lines(paths):
        m = LOG_RE.match(line)
        if not m:
            continue
        ip, ua, path = m.group("ip"), m.group("ua"), m.group("path")
        if classify(ip, ua, path, m.group("status")) != "ASKED-FOR-WEATHER":
            excluded += 1
            continue
        if self_declared_checker(ua) or self_declared_crawler(ua):
            excluded += 1
            continue
        p = urllib.parse.unquote(path.split("?")[0]).rstrip("/").lower()
        if p in NOT_A_PLACE or p.startswith("/mcp"):
            continue
        place = p.split("/")[1] if p.startswith("/") and len(p) > 1 else p
        key = (ip, place)
        seen[key].add(m.group("t")[:11])          # dd/Mon/YYYY
        agents[key].add(ua[:46])
        hits[key] += 1

    if not seen:
        if excluded:
            print("0 distinct (caller, place) pairs asked for a named place, "
                  "out of %d requests that were all either ours, machines by "
                  "their own description, or not about a place.\n"
                  "0 of them came back for the SAME place on 2+ separate days.\n"
                  "This is an answer, not a failure to ask." % excluded)
            return 0
        print("NO-PLACES: these logs contain no requests at all that reached "
              "the point of being classified. That is 'I could not tell', not "
              "'nobody wanted one' -- check the log glob before reading it as "
              "an answer.")
        return 2

    repeat = sorted(((len(d), hits[k], k, sorted(agents[k])) for k, d in seen.items()
                     if len(d) >= 2), reverse=True)
    print("%d distinct (caller, place) pairs asked for a named place." % len(seen))
    print("%d of them came back for the SAME place on 2+ separate days:\n"
          % len(repeat))
    for days, n, (ip, place), ua in repeat:
        print("  %-16s %-20s %d days %4d reqs  %s"
              % (ip, place, days, n, "; ".join(ua)[:76]))
    print("\nUPPER BOUND, and a small one. A user agent is a claim, callers are "
          "/24 networks rather than people, and on 2026-08-20 four of five rows "
          "here turned out to be machines once the rows themselves were read. "
          "Read the rows; do not report the count on its own.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="/var/log/nginx/access.log*")
    ap.add_argument("--path-filter", default=None,
                    help="only count requests whose path contains this")
    ap.add_argument("--repeat-city", action="store_true",
                    help="the narrowest demand signal we have: one caller "
                         "asking for the SAME named place on separate days")
    a = ap.parse_args()

    paths = sorted(glob.glob(a.logs))
    if not paths:
        print("NO-LOGS %s matched nothing -- this is 'I cannot tell', "
              "not 'nobody came'" % a.logs)
        return 2

    if a.repeat_city:
        return repeat_city(paths)

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
            # Three-way, not two-way. `program-like` is the column the weekly
            # report and the acceptance criterion both name, and on 2026-08-19
            # its top two entries were `SentinelOracle/0.1 (... liveness-check)`
            # and `mcpbeat/0.1 (... liveness check)` -- 1634 requests from two
            # machines that say in their own user agent that they are checking
            # whether we are up. Counting those toward "could be a user" makes
            # the number move without anyone needing us.
            #
            # SPLIT, never filter, and the predicate is imported rather than
            # rewritten here: a UA is a claim, so a real user whose agent string
            # happens to contain "monitor" must still appear in the output --
            # just under a name that says what it claimed.
            # Checker first, and across the WHOLE bucket rather than inside the
            # program-like branch. 2026-08-19: the two loudest agents here are
            # `SentinelOracle/0.1 (... liveness-check)` and `mcpbeat/0.1 (...
            # liveness check)`, 1634 requests between them -- and AGENTISH_UA
            # does not match either, so they were landing in
            # `browser-like-or-unknown`. That label reads "might be a person",
            # which is the worst place for a machine that says it is a machine.
            #
            # SPLIT, never filter: a real user whose agent string happens to
            # contain "monitor" still appears, under a name that says what it
            # claimed rather than what it is.
            if self_declared_checker(ua):
                agentish["says it is a checker (not a user)"] += 1
            elif any(x in low for x in AGENTISH_UA):
                agentish["program-like"] += 1
            else:
                agentish["browser-like-or-unknown"] += 1

    # 2026-08-19: run as `cc` rather than with sudo, every count printed 0 and
    # the honest sentence read "0 requests came from outside our own machines".
    # The nginx logs are 0640 www-data:adm; nothing was readable and nothing
    # said so. **"nobody came" and "I could not look" printed the same page**,
    # which is the failure this whole file is supposed to guard against, on the
    # instrument that reports the acceptance criterion. `window: ? -> ?` was the
    # only tell and it is easy to read past.
    #
    # So: refuse. Exit 2 is "could not determine", never 0.
    if not paths or total == 0:
        print("NO-LOG: read %d file(s) and parsed %d requests -- refusing to "
              "report zeros" % (len(paths), total))
        print("  A zero here would be indistinguishable from 'nobody came'.")
        print("  Most likely the log is not readable by this user "
              "(nginx writes 0640 www-data:adm); try sudo.")
        return 2
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

    checkers = agentish.get("says it is a checker (not a user)", 0)
    print("\nThe honest sentence: %d requests came from outside our own machines,\n"
          "asked for something we actually serve, and got it. That is an UPPER BOUND on\n"
          "real users -- it still contains anyone we failed to list as an insider, and\n"
          "bob's own phone. Of those, %d say in their own user agent that they are\n"
          "checking whether we are up, so the bound that could ever become evidence a\n"
          "stranger needs this is nearer %d. A user agent is a claim either way."
          % (buckets["ASKED-FOR-WEATHER"], checkers,
             buckets["ASKED-FOR-WEATHER"] - checkers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
