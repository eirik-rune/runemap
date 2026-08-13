"""Ask the Czech composite which way up it is, and fail if it answers wrongly.

`scripts/radar_chmi.py` reads row 0 as the NORTHERNMOST row. That is what ODIM
v2.4 says and what everyone does, and it is also exactly the kind of assumption
this repo keeps getting hurt by: a raster read upside down still draws a map,
still has the right scale, still reports a fresh frame, and puts the weather in
the wrong half of the country. Nothing in the file says "row 0 is north".

So this measures it instead of trusting it, using the one asymmetry the product
cannot fake -- where it is blind:

  the composite is built from two radars, Brdy-Praha (49.6583N 13.8178E) and
  Skalky (49.5011N 16.7885E), each with a stated 260 km range. So the corner
  farthest from both is the corner most likely to carry `nodata`, and the
  nearest is the least. Rank the four corners by distance, rank them by how
  much nodata each holds, and the two orders must agree.

Measured 2026-08-13 12:40 UTC:

    corner   min range   nodata pixels
    NE         296 km      1447
    NW         269 km        94
    SE         263 km         9
    SW         259 km         0

Perfect agreement across all four, and under the flipped reading the blind
corners would be the two NEAREST the radars, which is not how radars fail.

Two things this does NOT prove, said out loud because a check that oversells is
worse than none: it cannot see a pure left-right mirror if the longitude
asymmetry is small, and on a day when the composite has almost no nodata at all
it has nothing to rank -- which is why INSUFFICIENT is a verdict here and not a
pass. "I cannot tell" and "it is fine" must not print the same word.

    python3 ops/chmi_orient.py

Exit 0 only on OK. Needs h5py, which is the optional `runemap[hdf5]` extra.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))

RADARS = {"brdy": (49.6583, 13.8178), "skalky": (49.5011, 16.7885)}
MIN_NODATA = 200          # below this the ranking is noise, not evidence


def great_circle(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    d = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(d))


def corner_ranges(corners):
    pts = {"NE": (corners["UR_lat"], corners["UR_lon"]),
           "NW": (corners["UR_lat"], corners["LL_lon"]),
           "SE": (corners["LL_lat"], corners["UR_lon"]),
           "SW": (corners["LL_lat"], corners["LL_lon"])}
    return {k: min(great_circle(v, r) for r in RADARS.values())
            for k, v in pts.items()}


def corner_nodata(arr, nodata):
    """Nodata counts per quadrant, labelled as if row 0 were north."""
    import numpy as np
    h, w = arr.shape
    m = (arr == nodata)
    ys, xs = np.where(m)
    return {"NW": int(((ys < h / 2) & (xs < w / 2)).sum()),
            "NE": int(((ys < h / 2) & (xs >= w / 2)).sum()),
            "SW": int(((ys >= h / 2) & (xs < w / 2)).sum()),
            "SE": int(((ys >= h / 2) & (xs >= w / 2)).sum())}


def verdict(ranges, counts):
    """-> (state, sentence). States: OK, FLIPPED, DISAGREE, INSUFFICIENT."""
    total = sum(counts.values())
    if total < MIN_NODATA:
        return "INSUFFICIENT", ("only %d nodata pixels; the ranking would be"
                                " noise. This is not a pass." % total)
    by_range = [k for k, _ in sorted(ranges.items(), key=lambda kv: -kv[1])]
    by_blind = [k for k, _ in sorted(counts.items(), key=lambda kv: -counts[kv[0]])]
    if by_range == by_blind:
        return "OK", ("blind corners rank %s, range ranks %s -- north is up"
                      % ("/".join(by_blind), "/".join(by_range)))
    flip = {"N": "S", "S": "N"}
    flipped = [flip[k[0]] + k[1] for k in by_blind]
    if by_range == flipped:
        return "FLIPPED", ("blind corners rank %s, which matches the range order"
                           " ONLY if row 0 is south. The raster is upside down."
                           % "/".join(by_blind))
    return "DISAGREE", ("blind corners rank %s but range ranks %s; neither"
                        " reading explains it -- the geometry moved"
                        % ("/".join(by_blind), "/".join(by_range)))


def main():
    import radar_chmi as C
    if not C.have_h5py():
        sys.exit("needs h5py: pip install 'runemap[hdf5]'")
    path = None
    for stamp in C.stamps():
        path = C._fetch(stamp)
        if path:
            break
    if not path:
        sys.exit("no frame available upstream")
    arr, scale, corners, stamp = C.read(path)
    ranges = corner_ranges(corners)
    counts = corner_nodata(arr, scale["nodata"])
    state, why = verdict(ranges, counts)
    print("frame %s  %dx%d" % (stamp, arr.shape[1], arr.shape[0]))
    for k in ("NE", "NW", "SE", "SW"):
        print("  %-2s  %5.0f km  %6d nodata" % (k, ranges[k], counts[k]))
    print("%s: %s" % (state, why))
    sys.exit(0 if state == "OK" else 1)


if __name__ == "__main__":
    main()
