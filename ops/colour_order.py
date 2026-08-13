"""Derive a colour scale's ORDER from the data, when nobody publishes it.

Our grid needs to know which colour is heavier than which. It does not need
mm/h. So when a service ships discrete colours and no machine-readable legend
(JMA's nowcast tiles, KNMI's default style), there is a way out that is not
typing thresholds from memory: rain has structure. Heavier cores sit INSIDE
lighter surroundings, and lighter classes cover more ground than heavier ones.
Both facts are measurable, and either can refuse to hold.

Two independent signals, deliberately not one:

  depth      mean distance from a colour's pixels to the edge of the
             precipitation region. Cores are further inside.
  adjacency  which colours touch which. A scale is a gradient, so a class
             borders its neighbours in the scale far more than distant ones.

The first proposes an order; the second has to agree with it, and it is
computed from a different property, so agreeing is evidence and disagreeing is
a finding.

The first version of this used AREA as the second signal -- "lighter covers
more ground" -- and it refused JMA at exactly one place: the very lightest
class covers LESS ground than the next one up, because it is the thin fringe
around every echo rather than a region. That is a real defect in the signal,
visible before looking at the answer, so it was replaced rather than loosened.
Loosening a ruler until it agrees with you is how a derivation turns into the
guess it was supposed to replace.

    python3 ops/colour_order.py            # samples JMA over Japan

The distance transform is done by repeated erosion rather than scipy, which is
not a dependency here: an image this size needs a few dozen passes and the
whole point is to run where the service runs.
"""
import collections
import io
import sys
import urllib.request

import numpy as np
from PIL import Image


def depth_map(mask, cap=64):
    """-> per-pixel distance (in erosion steps) from outside the mask.

    A pixel of 1 means "on the edge", higher means deeper in. Capped because
    a fully-covered tile would otherwise erode for its whole width and tell us
    nothing we use.
    """
    d = np.zeros(mask.shape, dtype=np.int16)
    cur = mask.copy()
    for step in range(1, cap + 1):
        if not cur.any():
            break
        d[cur] = step
        p = np.zeros((cur.shape[0] + 2, cur.shape[1] + 2), dtype=bool)
        p[1:-1, 1:-1] = cur
        cur = (p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1]
               & p[1:-1, :-2] & p[1:-1, 2:])
    return d


def sample(images, min_px=200):
    """-> {colour: (mean depth, pixel count)} over a list of RGBA arrays."""
    depth = collections.defaultdict(float)
    count = collections.Counter()
    for a in images:
        vis = a[..., 3] > 50
        if not vis.any():
            continue
        d = depth_map(vis)
        flat = a[vis]
        dd = d[vis]
        for c in set(map(tuple, flat[:, :3].tolist())):
            hit = ((flat[:, 0] == c[0]) & (flat[:, 1] == c[1])
                   & (flat[:, 2] == c[2]))
            n = int(hit.sum())
            depth[c] += float(dd[hit].sum())
            count[c] += n
    return {c: (depth[c] / count[c], count[c])
            for c in count if count[c] >= min_px}


def order(stats):
    """-> colours ordered lightest first by mean depth."""
    return [c for c, _ in sorted(stats.items(), key=lambda kv: kv[1][0])]


def adjacency(images, colours):
    """-> {(a, b): touching pixel pairs} for the colours we are ordering."""
    idx = {c: i for i, c in enumerate(colours)}
    n = len(colours)
    m = np.zeros((n, n), dtype=np.int64)
    for a in images:
        lab = np.full(a.shape[:2], -1, dtype=np.int16)
        for c, i in idx.items():
            lab[(a[..., 0] == c[0]) & (a[..., 1] == c[1])
                & (a[..., 2] == c[2]) & (a[..., 3] > 50)] = i
        for u, v in ((lab[:, :-1], lab[:, 1:]), (lab[:-1, :], lab[1:, :])):
            keep = (u >= 0) & (v >= 0) & (u != v)
            for i, j in zip(u[keep].tolist(), v[keep].tolist()):
                m[i, j] += 1
                m[j, i] += 1
    return m


MIN_PAIRS = 20000        # touching pixel pairs needed before judging at all
MIN_CLASSES = 3          # below this, "the order is stable" cannot be wrong
FRAGILE = 0.25           # depth gap below which "A is lighter than B" is noise


def fragile_pairs(by_depth, stats, gap=FRAGILE):
    """Which neighbouring distinctions this derivation did NOT really make.

    Measured on JMA: (33,140,255) and (0,65,255) sit 0.01 apart in mean depth
    over 192 tiles. That is not a separation, it is two numbers that happen to
    have an order, and a stable sample will keep reproducing it without ever
    earning it. Naming these is the difference between a derived scale and a
    scale that merely printed without complaining -- and a caller can then put
    a fragile pair in the same level, so nothing downstream depends on a
    distinction nobody made.
    """
    out = []
    for i in range(len(by_depth) - 1):
        a, b = by_depth[i], by_depth[i + 1]
        d = stats[b][0] - stats[a][0]
        if d < gap:
            out.append((a, b, round(d, 3)))
    return out


def stability(images, halves=2, min_px=200):
    """-> (orders, agree) from disjoint halves of the sample.

    Added after the tool refused an order it had just confirmed, on a smaller
    sample. That refusal was correct as "I cannot tell" and wrong as "these
    disagree", and the two must not print the same word -- the same thing
    Eirik hit this morning when a leak judge compared counters across
    different processes and reported LEAK instead of INSUFFICIENT.
    """
    n = max(1, len(images) // halves)
    orders = [order(sample(images[i:i + n], min_px=min_px))
              for i in range(0, len(images), n)][:halves]
    # A stability check over one or two classes is not a check: it can only
    # print STABLE. Measured on KNMI over a dry Netherlands -- one colour
    # survived the pixel floor and the tool cheerfully called the order stable.
    if len(orders) < halves or min(len(o) for o in orders) < MIN_CLASSES:
        return orders, None
    return orders, all(o == orders[0] for o in orders)


def verdict(by_depth, m, min_pairs=MIN_PAIRS):
    """Does every class border its proposed neighbours more than the rest?

    Checked per class rather than in total, so one dominant pair cannot carry
    a wrong order: for each colour, the strongest border it has must be one of
    the two the depth order puts next to it.
    """
    # min_pairs is a sample-size floor, not a strictness dial: a caller with a
    # smaller scene (a synthetic one, say) may state a smaller floor, but the
    # production default is never lowered to make a service pass.
    if int(m.sum()) < min_pairs:
        return None, ("INSUFFICIENT: %d touching pixel pairs, under %d -- this "
                      "is 'I cannot tell yet', not 'the scale disagrees'"
                      % (int(m.sum()), min_pairs))
    bad = []
    for i, c in enumerate(by_depth):
        row = m[i].copy()
        row[i] = -1
        strongest = int(np.argmax(row))
        if strongest not in (i - 1, i + 1):
            bad.append((c, by_depth[strongest]))
    if not bad:
        return True, ("AGREE: every class borders a depth-neighbour more than "
                      "anything else (%d classes)" % len(by_depth))
    return False, ("REFUSED: %d of %d classes border a non-neighbour most: %s"
                   % (len(bad), len(by_depth), bad[:3]))


def jma_tiles(basetime, tiles, get=None):
    fetch = get or (lambda u: urllib.request.urlopen(u, timeout=20).read())
    out = []
    for z, x, y in tiles:
        u = ("https://www.jma.go.jp/bosai/jmatile/data/nowc/%s/none/%s/surf/"
             "hrpns/%d/%d/%d.png" % (basetime, basetime, z, x, y))
        try:
            out.append(np.array(Image.open(io.BytesIO(fetch(u))).convert("RGBA")))
        except Exception as e:
            sys.stderr.write("TILE-FAILED %s %r\n" % (u, e))
    return out


def main():
    import json
    times = json.loads(urllib.request.urlopen(
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json",
        timeout=20).read())
    # Only frames the radar observed. A nowcast file also carries forecast
    # steps, and asking a forecast where its cores are would be measuring the
    # model's habits, not the sky's shape.
    obs = [t for t in times if t["basetime"] == t["validtime"]][:4]
    z = 6
    tiles = [(z, x, y) for x in range(54, 60) for y in range(23, 27)]
    imgs = []
    for t in obs:
        imgs += jma_tiles(t["basetime"], tiles)
    print("%d frames, %d tiles" % (len(obs), len(imgs)))
    stats = sample(imgs)
    by_depth = order(stats)
    for c in by_depth:
        d, n = stats[c]
        print("   %-16s depth %5.2f  px %7d" % (str(c), d, n))
    ok, msg = verdict(by_depth, adjacency(imgs, by_depth))
    print("-- %s" % msg)
    orders, stable = stability(imgs)
    print("-- %s" % ("STABLE: disjoint halves of the sample give the same order"
                     if stable else
                     "UNSTABLE: halves disagree -- %s" % (orders,)))
    frag = fragile_pairs(by_depth, stats)
    if frag:
        print("-- FRAGILE, do not depend on these orderings: %s" % (frag,))
    if ok and stable:
        print("-- derived order, lightest first: %s" % (by_depth,))


if __name__ == "__main__":
    main()
