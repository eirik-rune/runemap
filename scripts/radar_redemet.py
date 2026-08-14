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
# Who this source is added FOR, as opposed to what it can SEE.
# covers() answers the second question and must not be read as the
# first: a box that holds all of Brazil holds neighbours too.
SERVES = ("BR",)
ATTRIB = "REDEMET/DECEA redemet.decea.mil.br"
# Derived from THIS source's cycle, not copied from the global composite's.
# Measured 8/13 across all 18 mirrored radars in one pull: at the moment we
# fetched them the frames were already 13.4 / 19.6 / 23.2 min old (min /
# median / max) -- REDEMET publishes with about twenty minutes of latency of
# its own. Add the 10-minute mirror period and a frame is 23-33 min old by the
# time a reader asks, so the 30 min this used to be refused most of the cycle:
# Sao Paulo drew at "obs age: 28min" and would have gone dark two minutes
# later, with nothing wrong anywhere. 45 min accepts one whole cycle and still
# catches the failure this ceiling exists for -- a dead mirror timer, whose
# ages climb past it within one extra period and never come back.
MAX_AGE = 2700.0
DIR = os.environ.get("REDEMET_DIR",
                     os.path.join(os.environ.get("RUNEMAP_CACHE",
                                                 "/var/cache/runemap"), "redemet"))


def _mirror_status_note():
    """-> ' -- <why the mirror last refused>', or a word saying we cannot tell.

    Deliberately never returns an empty string on failure. "The mirror gave no
    reason" and "the mirror is fine" must not read the same, which is the whole
    family of bugs this file keeps meeting.
    """
    p = os.path.join(DIR, "status.json")
    try:
        with open(p) as fh:
            st = json.load(fh)
    except FileNotFoundError:
        return " -- no mirror status yet (mirror older than this check, or " \
               "never ran)"
    except Exception as e:                       # noqa: BLE001
        return " -- mirror status unreadable: %r" % (e,)
    if st.get("refusal"):
        age = (time.time() - float(st.get("at") or 0)) / 60.0
        return " -- mirror %.0f min ago: %s" % (age, st["refusal"])
    return " -- mirror last round published (with_path=%s mirrored=%s), so " \
           "this is about coverage, not supply" % (st.get("with_path"),
                                                   st.get("mirrored"))


def _index():
    p = os.path.join(DIR, "index.json")
    try:
        with open(p) as fh:
            return json.load(fh)
    except FileNotFoundError:
        # A fact about us, not about REDEMET: the mirror timer has never
        # written. Silent until 2026-08-14, when the health probe reported
        # "no reason given" and there was nothing to look at.
        sys.stderr.write("REDEMET-NO-INDEX %s never written by the mirror\n" % (p,))
        return None
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


def draw(code, lng, lat, small=False, cached_only=False):
    """-> (art, km_per_col, ts, motion, base_ts, source) or None.

    cached_only is accepted and ignored: this adapter never touches the
    network -- the frames arrive by ops/redemet_pull.py on a timer -- so it is
    always already "cached". Accepting the argument rather than special-casing
    the caller keeps the chain uniform.
    """
    idx = _index()
    r = pick(lng, lat, idx)
    if r is None:
        # Two different facts, and they must not share a word: with no index
        # this is our mirror having never run (already logged by _index), and
        # with one it is a sky no Brazilian radar covers, which is not a fault
        # at all. Reporting both as silence sent the last hour of this to
        # "no reason given".
        if idx is not None:
            # len(idx) counts the index's top-level KEYS, not its radars --
            # it printed a confident "5" hours after this line was written and
            # a whole wrong story got built on it. Count the thing being
            # counted, and report the upstream list too, because "we mirrored
            # none of the 29 they listed" and "they listed none" are different
            # failures that a single number hides.
            rs = (idx or {}).get("radars") or ()
            # The index is the switch and may only move on good data, so when
            # it is frozen it cannot say why. The mirror records that beside it.
            # Without this the bell said "none of 0 mirrored radars" every 30
            # minutes through a REDEMET outage -- true, and pointing at the
            # wrong system, which costs whoever reads it the first hour.
            why = _mirror_status_note()
            sys.stderr.write("REDEMET-NO-STATION none of %d mirrored radars "
                             "(upstream listed %s) covers %.2f,%.2f%s\n"
                             % (len(rs), (idx or {}).get("listed", "?"),
                                lng, lat, why))
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
