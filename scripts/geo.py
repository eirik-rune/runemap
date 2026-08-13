#!/usr/bin/env python3
"""Offline geocoding on GeoNames cities1000 (CC-BY 4.0).
  lookup("Chiang Mai")      -> place dict (name -> lat/lon)
  rlookup(18.79, 98.99)     -> nearest place + county/province
No network, no rate limit. DB path via env GEO_DB."""
import math, os, sqlite3, threading, unicodedata

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


def _pack(row):
    adm = _admin(row["cc"], row["a1"], row["a2"])
    return {"name": row["name"], "lat": row["lat"], "lon": row["lon"], "cc": row["cc"],
            "pop": row["pop"], "tz": row["tz"], "admin": adm,
            "label": ", ".join([row["name"]] + adm + [row["cc"]])}


def lookup(q, cc=None):
    """place name (any language/alias) -> place. Most populous match wins."""
    d = _db()
    parts = [p.strip() for p in (q or "").replace("/", ",").split(",") if p.strip()]
    if not parts:
        return None
    head = norm(parts[0])
    hint = norm(parts[-1]) if len(parts) > 1 else None
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
    cand = [_pack(r) for r in rows]
    if cc:
        cand = [c for c in cand if c["cc"].lower() == cc.lower()] or cand
    if hint:                      # "Chiang Mai, Thailand" -> prefer country/admin match
        hit = [c for c in cand if hint in norm(c["label"]) or hint == norm(c["cc"])]
        if hit:
            return hit[0]
    return cand[0]


def rlookup(lat, lon, radius_km=60):
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
    o = _pack(best)
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
