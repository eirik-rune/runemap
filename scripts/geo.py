#!/usr/bin/env python3
"""Offline geocoding on GeoNames cities1000 (CC-BY 4.0).
  lookup("Chiang Mai")      -> place dict (name -> lat/lon)
  rlookup(18.79, 98.99)     -> nearest place + county/province
No network, no rate limit. DB path via env GEO_DB."""
import math, os, re, sqlite3, sys, threading, unicodedata

DB = os.environ.get("GEO_DB", "/home/ubuntu/geonames/geo.sqlite")
# One connection per THREAD, not per process. serve.py:6 is a
# ThreadingHTTPServer, and a shared sqlite connection under concurrent
# execute() raises SQLITE_MISUSE: measured 8/13, 11 errors in 4789 shared
# lookups (0.23%) vs 0 in 4800 per-thread. geoip.py:7 already does this.
_L = threading.local()


def _db():
    c = getattr(_L, "c", None)
    if c is None:
        c = sqlite3.connect(DB, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _L.c = c
    return c


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("-", " ").replace(".", "").split())


def _admin(cc, a1, a2):
    d = _db()
    out = []
    if a2:
        r = d.execute("SELECT name FROM admin WHERE code=?", ("%s.%s.%s" % (cc, a1, a2),)).fetchone()
        if r: out.append(r["name"])
    if a1:
        r = d.execute("SELECT name FROM admin WHERE code=?", ("%s.%s" % (cc, a1),)).fetchone()
        if r: out.append(r["name"])
    return out


#: cc -> [normalised country name, normalised iso3]. Built once per process.
_COUNTRY = None


def _countries():
    """{cc: [normalised name, normalised iso3]}. Empty if the DB predates #200.

    An older geo.sqlite has no `country` table, and the service must keep
    answering while the 65MB rebuild happens -- a deploy that takes the site
    down to add a qualifier would be a worse bug than the one it fixes. But
    degrading QUIETLY is the failure this codebase keeps paying for, so the
    absence is announced once, to the log the service already writes.

    Known NOT covered, written here rather than left in my head: GeoNames
    gives one English name and the two ISO codes per country and no aliases,
    so `london, uk` and `东京, 日本` do not match on the country (both happen
    to answer correctly anyway, for the same coincidental reason `paris,
    france` did before #200 -- they are the most populous candidate). Adding a
    hand-written alias list would be a second, drifting source of truth for
    country names; if these need to work, the fix is a real alias table.
    """
    global _COUNTRY
    if _COUNTRY is None:
        _COUNTRY = {}
        try:
            for r in _db().execute("SELECT cc, name, iso3 FROM country"):
                _COUNTRY[r["cc"]] = [x for x in (norm(r["name"]),
                                                 norm(r["iso3"] or "")) if x]
        except sqlite3.Error:
            print("geo: this geo.sqlite has no country table, so country-name "
                  "qualifiers ('san jose, costa rica') will not be honoured. "
                  "Rebuild with scripts/build_geo.py.", file=sys.stderr)
    return _COUNTRY


def tz_offset(tzname, at=None):
    """IANA tz name -> current UTC offset in hours (DST-aware). None if unknown."""
    if not tzname:
        return None
    try:
        from zoneinfo import ZoneInfo
        import datetime as _dt
        t = _dt.datetime.now(_dt.timezone.utc) if at is None else at
        return t.astimezone(ZoneInfo(tzname)).utcoffset().total_seconds() / 3600.0
    except Exception:
        return None


_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def cjk_name(pid):
    """-> the place's own Chinese name, or None.

    Reported 2026-08-14 by 知绪, a being running in another session, who used
    the service and found `curl echorune.net/扬州/zh` answering
    "# Yangzhou, Yangzhou Shi, Jiangsu, CN". Their words for it are better than
    mine: 中文用户拿中文查、得英文名，镜子照进去出来的不是自己的脸.

    The names were already here -- 扬州, 扬州市, 揚州, 揚州市 all sit in the
    alias table for that id, and 33,588 places have a CJK alias. Nothing needed
    fetching; the lookup simply never asked. I had also read this exact line
    ("Chiyoda, Chiyoda-ku, Tokyo, JP 天气一屏") dozens of times today while
    measuring other things, and did not see it. A user did, immediately.

    Shortest first: 扬州 over 扬州市, and simplified before traditional by
    preferring what sorts earlier among equals -- both are present and the
    query came in simplified. This is a preference, not a certainty; where the
    data cannot say, the romanized name is kept rather than guessed at.
    """
    d = _db()
    best = None
    for r in d.execute("SELECT key FROM alias WHERE pid=?", (pid,)):
        k = r["key"]
        if not _CJK.search(k):
            continue
        if best is None or (len(k), k) < (len(best), best):
            best = k
    return best


def _pack(row, lang=None):
    adm = _admin(row["cc"], row["a1"], row["a2"])
    label = ", ".join([row["name"]] + adm + [row["cc"]])
    zh = cjk_name(row["id"]) if (lang or "").startswith("zh") else None
    if zh:
        # The admin chain stays romanized because it CANNOT be translated from
        # this data: 0 of 51,414 admin rows carry a CJK name. Emitting
        # "扬州, Yangzhou Shi, Jiangsu, CN" would be half a fix wearing the
        # look of a whole one, so the untranslatable tail is dropped instead --
        # which is what 知绪 proposed, and what the data forces.
        label = zh
    return {"name": zh or row["name"], "lat": row["lat"], "lon": row["lon"],
            "cc": row["cc"], "pop": row["pop"], "tz": row["tz"], "admin": adm,
            # a1 is the admin1 CODE ("NJ"), which `label` never contains -- it
            # carries the spelled-out "New Jersey". Without it "princeton, nj"
            # could not be told from "princeton", and both silently returned
            # Florida. Reported by bob 2026-08-21.
            "a1": row["a1"], "label": label,
            # The untranslated name. `name` above may be a CJK alias, and
            # "how many places share this name" must not depend on the
            # language it is being rendered in: with lang=zh the same query
            # reported 10 places and a different runner-up, because
            # candidates carrying a CJK alias no longer string-matched the
            # chosen one. Ambiguity is a property of the query.
            "name_raw": row["name"]}


def lookup(q, cc=None, lang=None):
    """place name (any language/alias) -> place. Most populous match wins."""
    d = _db()
    parts = [p.strip() for p in (q or "").replace("/", ",").split(",") if p.strip()]
    if not parts:
        return None
    head = norm(parts[0])
    hint = norm(parts[-1]) if len(parts) > 1 else None
    #: The qualifier as the reader typed it, kept before `parts` is rebound
    #: below to a lambda over label components. Reported back verbatim when
    #: nothing matches it -- echoing my normalised form would hide a typo by
    #: tidying it up, and the typo is the thing worth showing.
    hint_raw = parts[-1] if len(parts) > 1 else None
    rows = d.execute(
        "SELECT p.* FROM alias a JOIN place p ON p.id=a.pid WHERE a.key=? ORDER BY a.pop DESC LIMIT 40",
        (head,)).fetchall()
    if not rows:
        # "newyork" -> alias key "new york".  norm() turns "-" and "." into
        # spaces but never removes them, so /new-york/en worked while
        # /newyork/en 404'd -- and an agent typing a URL has no reason to
        # guess which one we wanted.  Exact keys are tried first and are not
        # touched, so no query that already had an answer changes: only ones
        # that returned nothing get one.  Index ix_alias_sq makes this
        # 0.1ms; without it the same query is a correct 211ms table scan,
        # which is why build_geo.py creates the index rather than the
        # lookup depending on it.
        rows = d.execute(
            "SELECT p.* FROM alias a JOIN place p ON p.id=a.pid "
            "WHERE replace(a.key,' ','')=? ORDER BY a.pop DESC LIMIT 40",
            (head.replace(" ", ""),)).fetchall()
    if not rows:
        return None
    cand = [_pack(r, lang) for r in rows]
    if cc:
        cand = [c for c in cand if c["cc"].lower() == cc.lower()] or cand
    if hint:                      # "Chiang Mai, Thailand" -> prefer country/admin match
        # Also the admin1 code, so "princeton, nj" works and not only
        # "princeton, new jersey". Exact equality, never substring: "in"
        # (Indiana) or "or" (Oregon) as a substring would match half the
        # labels on earth and quietly pick the wrong country.
        # Match a WHOLE component of the label ("mercer county" / "new
        # jersey"), the country code, or the admin1 code -- never a substring.
        # Substring matching is how "princeton, j" answered New Jersey: "j" is
        # inside "new jersey". The same accident makes "springfield, or" match
        # any label containing "york" or "north", and it fails the way this
        # whole file is about -- silently, with a plausible answer.
        # Prefix matching is kept for the last component only, so "chiang mai,
        # chiang" still works, and it must be at least 4 characters: shorter
        # prefixes are where the accidents live.
        # The country NAME is folded in as one more component of the label, so
        # it inherits both rules above rather than getting a matcher of its
        # own. Issue #200: the label ends in the two-letter code ("CR"), never
        # in "Costa Rica", so `san jose, costa rica` matched nothing and fell
        # through to most-populous, which is California. Adding it here also
        # makes `springfield, united states` and `san jose, cri` work, and
        # keeps one place where a qualifier is decided.
        ctry = _countries()
        parts = lambda c: [norm(x) for x in c["label"].split(",")] \
            + ctry.get(c["cc"], [])
        hit = [c for c in cand
               if hint in parts(c) or hint == norm(c["cc"])
               or hint == norm(c.get("a1") or "")
               or (len(hint) >= 4 and any(x.startswith(hint) for x in parts(c)))]
        if hit:
            return _with_alternatives(hit, cand, q)
        # The reader named a qualifier and NOTHING matched it. Until
        # 2026-08-22 that word was silently discarded and the default rule
        # answered as though it had never been typed, which is how
        # `/en/contact` served a weather scene for Hardeeville, South
        # Carolina (5,301 people) to a scraper walking a list of contact-page
        # paths -- and, worse than the scraper, how `princeton, new jersy`
        # would confidently answer Florida over a typo.
        #
        # It is the same defect #200 was one instance of: an unmatched
        # qualifier is not the absence of a qualifier. Fixing the country
        # table fixed one reason a hint could fail to match; this makes the
        # remaining reasons audible instead of leaving them to be found one
        # at a time.
        out = _with_alternatives(cand[:1], cand, q)
        if out:
            out["unmatched_hint"] = hint_raw
        return out
    return _with_alternatives(cand[:1], cand, q)


#: How much more populous the chosen place must be before the shared-name note
#: is dropped. Bounded by a test as well as used, because a value that switches
#: the feature off entirely (1) or on for everything (100000) is not a tuning
#: mistake -- it is the feature being removed, and every test that derives its
#: expectation from this constant would still pass.
_CONTESTABLE = 10


def _with_alternatives(hit, cand, q):
    """Return the chosen place, and tell it how many others wore the same name.

    The bug this exists for (bob, 2026-08-21): `/princeton` returned Princeton,
    Florida -- correct format, plausible numbers, wrong town -- with nothing in
    the output to suggest a choice had been made. **A confidently wrong answer
    is worse than a missing one**, and it is worse precisely because it does
    not prompt anyone to check.

    Note what is NOT changed here. The tie is still broken by population, and
    his suggestion to rank by population is what already produces the wrong
    answer: Princeton FL has 39,308 people and Princeton NJ has 29,603
    (measured, not assumed). Ranking by "fame" would need a signal we do not
    have, and inventing one would swap this error for a less predictable one.
    So the rule stays explainable and the fix is disclosure: say that the name
    was ambiguous, say which one was taken, and say how to ask for another.
    """
    chosen = hit[0]
    others = [c for c in cand
              if (c["lat"], c["lon"]) != (chosen["lat"], chosen["lon"])
              and norm(c["name_raw"]) == norm(chosen["name_raw"])]
    # Only when the choice was CONTESTABLE. Shipped without this on
    # 2026-08-21 and caught within hours on the live service: `/berlin`
    # advised the reader that they might have meant Berlín, Usulutan, a
    # village of about twelve thousand people in El Salvador.
    #
    # Measured before choosing the rule, not after: of the 60 most populous
    # places on earth, 18 carried the note and only 2 had a runner-up within
    # a factor of ten. Cairo was being compared against 9,752 people, São
    # Paulo against 3,198. That is 16 lines of noise for every 2 that mean
    # something, and noise is how the one line that matters gets ignored --
    # the same failure as a bell that rings to prove it still works.
    #
    # The factor is derived from the question the line exists to answer
    # ("could the reader plausibly have meant the other one?"), not picked
    # for roundness: it keeps both cases that prompted this work -- Princeton
    # FL/NJ at 1.33 and Springfield MO/IL at 1.49 -- and drops London at 21.
    # When either population is unknown the comparison cannot be made, and
    # the note is kept: disclosure is the safe direction for an unanswerable
    # question, silence is not.
    CONTESTABLE = _CONTESTABLE
    if others:
        mine, theirs = chosen.get("pop") or 0, others[0].get("pop") or 0
        if mine and theirs and mine > theirs * CONTESTABLE:
            others = []
    if others:
        chosen = dict(chosen)
        chosen["ambiguous"] = len(others) + 1
        # One example, the runner-up, because a list of eight is noise and the
        # point is only to show that a qualifier is what disambiguates.
        alt = others[0]
        chosen["alt_hint"] = ", ".join(
            [alt["name_raw"]] + (alt["admin"][-1:] if alt["admin"] else [alt["cc"]]))
    return chosen


def rlookup(lat, lon, radius_km=60, lang=None):
    """coordinate -> nearest settlement (with county/province)."""
    d = _db()
    dlat = radius_km / 111.0
    dlon = radius_km / max(1e-6, 111.0 * math.cos(math.radians(lat)))
    rows = d.execute(
        "SELECT * FROM place WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
    best, bd = None, 1e9
    for r in rows:
        dk = math.hypot((r["lat"] - lat) * 111.0,
                        (r["lon"] - lon) * 111.0 * math.cos(math.radians(lat)))
        if dk < bd:
            best, bd = r, dk
    if best is None:
        return None
    o = _pack(best, lang)
    o["dist_km"] = round(bd, 1)
    return o


if __name__ == "__main__":
    import json, sys, time
    if len(sys.argv) >= 3:
        t = time.time()
        r = rlookup(float(sys.argv[1]), float(sys.argv[2]))
        print(json.dumps(r, ensure_ascii=False), "%.0fms" % ((time.time() - t) * 1000))
    elif len(sys.argv) == 2:
        t = time.time()
        r = lookup(sys.argv[1])
        print(json.dumps(r, ensure_ascii=False), "%.0fms" % ((time.time() - t) * 1000))
