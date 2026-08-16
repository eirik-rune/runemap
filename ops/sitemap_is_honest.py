#!/usr/bin/env python3
"""Every URL the sitemap advertises must actually answer 200.

A sitemap is a promise made to a crawler: *these URLs exist*. Advertising one
that 404s is worse than publishing no sitemap at all -- the crawler spends its
budget and learns the site is unreliable. Written 2026-08-16, the day the
sitemap went in, because the access log showed /sitemap.xml had been asked for
79 times and refused 74 of them, by Googlebot and ChatGPT-User among others.

**Why this is not a unit test.** The obvious version asserts each advertised
path has a route in serve.py. That was written first and went red on /status --
correctly, because **nginx serves /status, serve.py does not**. The promise
spans two systems, and nothing readable from this repo can verify it. So it is
checked the only way it can be: by fetching each URL from the running service.

Exit 0 all honest, 1 an advertised page does not answer, 2 could not tell.
"""
import os
import sys
import urllib.error
import urllib.request
import xml.dom.minidom

BASE = os.environ.get("SITEMAP_BASE", "https://echorune.net")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "runemap-selfcheck"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, len(r.read())


def main():
    try:
        status, _ = fetch(BASE + "/sitemap.xml")
        with urllib.request.urlopen(BASE + "/sitemap.xml", timeout=30) as r:
            doc = xml.dom.minidom.parseString(r.read())
    except (urllib.error.URLError, OSError) as e:
        print("NO-SITEMAP cannot fetch %s/sitemap.xml: %s" % (BASE, e))
        return 2
    except Exception as e:
        # Malformed XML is a failure of the sitemap, not an inability to judge.
        print("BAD-XML /sitemap.xml did not parse: %s" % e)
        return 1

    locs = [n.firstChild.data for n in doc.getElementsByTagName("loc")]
    if not locs:
        print("NO-URLS sitemap parsed but advertises nothing -- "
              "that is not the same as all URLs being fine")
        return 2

    print("%d URLs advertised by %s/sitemap.xml\n" % (len(locs), BASE))
    bad = []
    for loc in locs:
        try:
            code, size = fetch(loc)
        except urllib.error.HTTPError as e:
            code, size = e.code, -1
        except (urllib.error.URLError, OSError) as e:
            print("  ??? %8s  %s  (%s)" % ("-", loc, e))
            bad.append(loc)
            continue
        ok = code == 200 and size > 50
        print("  %-3s %8dB  %s%s" % (code, size, loc, "" if ok else "   <-- broken promise"))
        if not ok:
            bad.append(loc)

    if bad:
        print("\nFAILED %d advertised URL(s) do not answer:" % len(bad))
        for b in bad:
            print("   ", b)
        return 1
    print("\nOK every advertised URL answers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
