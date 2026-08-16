#!/usr/bin/env python3
"""Freeze one COMPLETE day of traffic, so the number bob judges by can be read
over time.

`ops/who_is_using.py` answers "who is calling us" honestly, and then the answer
evaporates: it globs `/var/log/nginx/access.log*`, which rotates daily. On
2026-08-16 I reported `program-like = 176` against `244` recorded a few days
earlier, over what looked like the same window -- a count over a fixed window
cannot fall, so one of them had to be wrong. Neither was. The oldest file had
simply rotated out from under the glob, and the window slid while its printed
start date stayed the same.

That makes the single measurement this company is judged on impossible to read
as a series. "Did the number move after we shipped a channel?" is the question,
and the instrument could not answer it, because yesterday's answer no longer
exists anywhere.

So one row per day, appended to a file that nothing rotates.

Two rules the rows obey, both learned the hard way here:

* **Only complete days.** Today is partial, and a partial day compared against
  a full one reads as a collapse in traffic. A half-written measurement that
  looks finished is the same failure as reading a log block before its
  terminator: the shape of "less" and the shape of "not yet" are identical.
* **A missing day stays missing.** No interpolation, no carrying forward. If
  the machine was off, the honest series has a hole in it, and a hole is
  information -- a smoothed line would quietly assert traffic we never saw.

Rows are never rewritten. Re-running is a no-op for days already recorded,
because a snapshot that silently updates itself is not a record of what was
true, it is a record of the last time I asked.

    python3 ops/traffic_snapshot.py           # yesterday, if not already stored
    python3 ops/traffic_snapshot.py --series  # what has been recorded

Exit 0 wrote or already had it, 2 could not tell (no logs, nothing complete).
Never 1: a quiet day is not a failure.
"""
import argparse
import datetime
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Imported, never re-implemented. A second copy of the classification would
# agree today and drift silently, and then the series would be measuring two
# different things with one name -- which is exactly the bug this file exists
# to prevent, one level up.
from who_is_using import (AGENTISH_UA, LOG_RE, classify,  # noqa: E402
                          read_lines)

SERIES = os.environ.get(
    "RUNEMAP_TRAFFIC_SERIES",
    os.path.join(os.environ.get("RUNEMAP_CACHE", "/tmp"), "traffic_daily.jsonl"))

MONTHS = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def day_of(stamp):
    """'02/Aug/2026:00:00:05 +0000' -> '2026-08-02', or None if unparseable."""
    try:
        d, mon, rest = stamp.split("/", 2)
        return "%s-%02d-%02d" % (rest[:4], MONTHS[mon], int(d))
    except Exception:
        return None


def load():
    rows = {}
    try:
        with open(SERIES, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows[r["day"]] = r
    except OSError:
        pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="/var/log/nginx/access.log*")
    ap.add_argument("--day", default=None,
                    help="YYYY-MM-DD; default is yesterday (the newest COMPLETE day)")
    ap.add_argument("--series", action="store_true")
    a = ap.parse_args()

    have = load()

    if a.series:
        if not have:
            print("NO-SERIES nothing recorded yet at %s -- that is 'I have not "
                  "started counting', not 'no traffic'" % SERIES)
            return 2
        print("%-12s %10s %10s %12s" % ("day", "served", "program", "outside-ips"))
        prev = None
        for day in sorted(have):
            r = have[day]
            if prev and (datetime.date.fromisoformat(day)
                         - datetime.date.fromisoformat(prev)).days > 1:
                # Say it out loud. A gap drawn as a straight line is an
                # assertion about traffic nobody measured.
                print("%-12s %s" % ("...", "(no rows between %s and %s)" % (prev, day)))
            print("%-12s %10d %10d %12d"
                  % (day, r["served"], r["program_like"], r["outside_ips"]))
            prev = day
        return 0

    day = a.day or str(datetime.date.today() - datetime.timedelta(days=1))
    if day == str(datetime.date.today()):
        print("REFUSING today is not over. A partial day next to a full one "
              "reads as a collapse in traffic, and 'less' and 'not yet' have "
              "the same shape.")
        return 2
    if day in have:
        return 0                      # already recorded; never rewritten

    paths = sorted(glob.glob(a.logs))
    if not paths:
        print("NO-LOGS %s matched nothing -- 'I cannot tell', not 'nobody came'"
              % a.logs)
        return 2

    buckets, agentish, ips = Counter(), Counter(), set()
    seen_day = False
    for line in read_lines(paths):
        m = LOG_RE.match(line)
        if not m:
            continue
        if day_of(m.group("t")) != day:
            continue
        seen_day = True
        ip, ua = m.group("ip"), m.group("ua")
        b = classify(ip, ua, m.group("path"), m.group("status"))
        buckets[b] += 1
        if b == "ASKED-FOR-WEATHER":
            ips.add(ip)
            low = ua.lower()
            agentish["program-like" if any(x in low for x in AGENTISH_UA)
                     else "browser"] += 1

    if not seen_day:
        # The log for that day has rotated away, or the day predates us. Either
        # way this is not "a day with no traffic" and must not be stored as one:
        # a zero row would become a permanent false measurement, and unlike a
        # gap it would look like evidence.
        print("NO-DATA no log lines for %s -- probably rotated out. Recording "
              "nothing: a zero row here would be indistinguishable from a real "
              "quiet day, forever." % day)
        return 2

    row = {"day": day,
           "served": buckets["ASKED-FOR-WEATHER"],
           "program_like": agentish["program-like"],
           "browser_like": agentish["browser"],
           "outside_ips": len(ips),
           "scanner": buckets["SCANNER"],
           "unclassified": buckets["UNCLASSIFIED"],
           # What produced this row, so a later reader can tell whether the
           # series changed because traffic changed or because I changed the
           # classifier.
           "recorded_at": datetime.datetime.now(datetime.timezone.utc)
                                   .strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        with open(SERIES, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        print("SERIES-UNWRITABLE %s: %s" % (SERIES, e))
        return 2
    print("%s served=%d program-like=%d outside-ips=%d"
          % (day, row["served"], row["program_like"], row["outside_ips"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
