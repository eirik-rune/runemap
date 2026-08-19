#!/usr/bin/env python3
"""Copy GitHub's repo traffic numbers to disk before GitHub deletes them.

GitHub keeps `/traffic/views`, `/traffic/clones` and `/traffic/popular/referrers`
for **14 days**. Nothing else we own can answer "did anyone arrive, and from
where": our nginx logs record a referrer field, but our readers are `curl` and
agents, which send none -- so a zero there has three possible mechanisms and no
power to tell them apart. This endpoint is the one place a referrer means
something, and it is on a timer.

So this is not another dashboard. It exists because **the measurement expires**,
and a month-over-month comparison is impossible to make later if nobody wrote
the days down while they existed.

What it refuses to do:

- **Print zeros when it could not ask.** No token, a 403, an empty payload: those
  are NO-DATA and exit 2, never a row of zeros that reads as "nobody came".
  Today's real answer -- 22 unique visitors in 14 days -- is small enough that a
  broken run would be indistinguishable from a true one.
- **Overwrite.** Rows are appended and keyed by date; re-running a day replaces
  only that day, so a bad run cannot erase history.
- **Call clones "installs".** `npx skills add` git-clones this repo, so does CI,
  so does our own install check. The number is recorded and deliberately not
  interpreted.

    python3 ops/gh_traffic_snapshot.py            # append today's window
    python3 ops/gh_traffic_snapshot.py --show     # what we have kept

Exit 0 wrote something, 2 could not ask.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.environ.get("GH_TRAFFIC_REPO", "eirik-rune/runemap")
TOKEN_FILE = os.environ.get(
    "GH_TOKEN_FILE", "/home/cc/beings/20260730_dev/nostr/.gh_token")
#: Deliberately OUTSIDE the repository. The first draft wrote to `live/` inside
#: the tree, and a daily cron writing there would make /opt/runemap dirty --
#: which is not a cosmetic problem, because deployment is `git merge --ff-only`
#: and a dirty tree refuses it. The measurement would have quietly broken the
#: thing it measures. Same family as keeping a backup next to the original.
OUT = os.environ.get("GH_TRAFFIC_OUT",
                     "/var/lib/runemap-listings/gh_traffic.jsonl")


def _get(path, token):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s%s" % (REPO, path),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def collect(token):
    """Return per-day rows plus today's referrer table, or raise."""
    views = _get("/traffic/views", token)
    clones = _get("/traffic/clones", token)
    refs = _get("/traffic/popular/referrers", token)
    by_day = {}
    for key, src in (("views", views.get("views") or []),
                     ("clones", clones.get("clones") or [])):
        for d in src:
            day = d["timestamp"][:10]
            row = by_day.setdefault(day, {"day": day})
            row[key] = d["count"]
            row[key + "_uniques"] = d["uniques"]
    # GitHub's own de-duplicated window totals. Summing the daily `uniques`
    # gives a DIFFERENT and larger number (26 vs 22 on 2026-08-19) because a
    # visitor who comes on two days is unique on both. Both are correct for
    # what they measure, and that is exactly how two numbers for "how many
    # people" start disagreeing in two different documents. Keep the
    # authoritative one, and label the other where it is printed.
    window = {"views": views.get("count"), "views_uniques": views.get("uniques"),
              "clones": clones.get("count"), "clones_uniques": clones.get("uniques")}
    return by_day, [{"referrer": r["referrer"], "count": r["count"],
                     "uniques": r["uniques"]} for r in refs], window


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    out = os.path.abspath(OUT)
    kept = {}
    if os.path.exists(out):
        for line in open(out, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "day" in r:
                kept[r["day"]] = r

    if a.show:
        if not kept:
            print("NO-DATA: nothing kept yet at %s" % out)
            return 2
        for day in sorted(kept):
            r = kept[day]
            print("  %s  views %-4s (%-3s uniq)   clones %-5s (%-3s uniq)"
                  % (day, r.get("views", "-"), r.get("views_uniques", "-"),
                     r.get("clones", "-"), r.get("clones_uniques", "-")))
        print("\n%d day(s) kept. GitHub itself only holds 14." % len(kept))
        return 0

    try:
        token = open(TOKEN_FILE).read().strip()
    except OSError as e:
        print("NO-DATA: cannot read %s (%s) -- refusing to write zeros, which "
              "would be indistinguishable from nobody arriving" % (TOKEN_FILE, e))
        return 2
    if not token:
        print("NO-DATA: token file is empty")
        return 2
    try:
        by_day, refs, window = collect(token)
    except urllib.error.HTTPError as e:
        print("NO-DATA: GitHub answered %s -- traffic needs push access" % e.code)
        return 2
    except Exception as e:                                  # noqa: BLE001
        print("NO-DATA: %r" % (e,))
        return 2
    if not by_day:
        print("NO-DATA: the API answered with no days at all")
        return 2

    kept.update(by_day)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for day in sorted(kept):
            f.write(json.dumps(kept[day], ensure_ascii=False) + "\n")
        f.write(json.dumps({"referrers_as_of": max(by_day), "referrers": refs,
                            "window_14d": window}, ensure_ascii=False) + "\n")
    os.replace(tmp, out)

    uniq_sum = sum(r.get("views_uniques", 0) for r in by_day.values())
    print("kept %d day(s) (%d new/updated this run) -> %s"
          % (len(kept), len(by_day), out))
    print("last 14 days: %s page views from %s unique visitors "
          "(GitHub's own de-duplicated window totals)"
          % (window.get("views"), window.get("views_uniques")))
    print("  for comparison, summing the daily uniques gives %d -- larger, "
          "because a visitor on two days is unique on both" % uniq_sum)
    print("referrers: %s" % (", ".join("%s %d/%d" % (r["referrer"], r["count"],
                                                     r["uniques"])
                                       for r in refs) or "none at all"))
    print("clones are recorded and NOT interpreted: `npx skills add` git-clones "
          "this repo, and so do CI and our own install check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
