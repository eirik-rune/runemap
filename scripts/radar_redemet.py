"""Brazilian radars, read off local disk only.

The frames arrive by `ops/redemet_pull.py`, which runs elsewhere on a timer;
this half never speaks to Brazil. That is not tidiness -- the production box
cannot reach REDEMET at all (measured: timeouts here, 200 from Tokyo) -- but it
also means a reader never waits on a third party, which is the rule this whole
fallback lives under.

The API hands out `lat_min/lat_max/lon_min/lon_max` per radar, so nothing here
guesses geometry: the bbox is theirs, mirrored verbatim. That is the reason
Brazil was cheaper to add than India, whose product is a polar PPI plot with no
georeference at all.

Attribution: "REDEMET/DECEA", with the link their terms authorise -- to their
main page, not deep into their images, and their images are not redisplayed.
"""
import json
import math
import os
import sys
import time

NAME = "REDEMET/DECEA"
ATTRIB = "REDEMET/DECEA redemet.decea.mil.br"
MAX_AGE = 1800.0          # older than this and "now" would be a lie
DIR = os.environ.get("REDEMET_DIR",
                     os.path.join(os.environ.get("RUNEMAP_CACHE",
                                                 "/var/cache/runemap"), "redemet"))


def _index():
    p = os.path.join(DIR, "index.json")
    try:
        with open(p) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None                      # never mirrored: a fact about us
    except Exception as e:
        sys.stderr.write("REDEMET-INDEX-BAD %r\n" % (e,))
        return None


def _ts(rec):
    """Frame time from the string REDEMET puts in `data` (UTC, their clock)."""
    try:
        return time.mktime(time.strptime(rec["data"], "%Y-%m-%d %H:%M:%S")) - time.timezone
    except Exception:
        return None


def pick(lng, lat, idx=None):
    """-> the mirrored radar covering this sky, or None.

    When several cover it, the nearest centre wins: a sky at the rim of a
    400 km disc is the part of the picture most likely to be attenuated or
    simply outside the beam.
    """
    idx = idx or _index()
    if not idx:
        return None
    best = None
    for r in idx.get("radars", []):
        s, w, n, e = r["bbox"]
        if not (s <= lat <= n and w <= lng <= e):
            continue
        d = math.hypot(lat - (s + n) / 2.0, lng - (w + e) / 2.0)
        if best is None or d < best[0]:
            best = (d, r)
    return best[1] if best else None


def draw(code, lng, lat, small=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None."""
    idx = _index()
    r = pick(lng, lat, idx)
    if r is None:
        return None
    ts = _ts(r)
    if ts is None:
        sys.stderr.write("REDEMET-NO-TIME %s\n" % (r.get("name"),))
        return None
    age = time.time() - ts
    if age > MAX_AGE:
        # Say which one and how old. "no map" and "a map we refused to draw"
        # are different states and only one of them is anybody's fault.
        sys.stderr.write("REDEMET-TOO-OLD %s age=%.0fs\n" % (r.get("name"), age))
        return None
    png = os.path.join(DIR, r["png"])
    if not os.path.exists(png):
        sys.stderr.write("REDEMET-PNG-MISSING %s\n" % (r["png"],))
        return None
    from render_scene import ascii_radar
    art, kmcol = ascii_radar(png, tuple(r["bbox"]), lng, lat,
                             cols=(24 if small else 48),
                             rows=(12 if small else 24), marker=code)
    return art, kmcol, float(ts), None, float(ts), NAME
