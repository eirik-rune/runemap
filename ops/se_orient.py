"""Is the SMHI composite laid out the way its GeoTIFF tags claim?

`utm.py` is checked against the four corner coordinates SMHI writes into the
companion HDF5 -- but those corners and my arithmetic come out of the same
product, so they agree whatever the pixel array does. An upside-down read
would still be scale-correct, still freshly stamped, and would put Kiruna's
weather over Skane.

**The control here is the blind mask against the radar sites**, the instrument
that settled Denmark. It has power in Sweden, which had to be measured rather
than assumed: Switzerland's mask was useless because MeteoSwiss centre the
composite on their own network, so flipping mapped it almost onto itself
(140.6 km against 142.0). Sweden's does not -- the composite is a tall box with
a large blind margin, and it disagrees with its own vertical flip on 38% of
cells.

**Which statistic, and why not the obvious one.** "Cells near a radar should be
seen" assumes the site list is complete, and Norway showed what that costs: two
of twelve nodes could not be resolved, and the statistic then *preferred* the
wrong orientation. Here the site list is also incomplete -- 10 of 12, because
Gotland's node is refused by the name guard and Balsta has no OSCAR row -- so
this module uses the direction that survives that:

    a BLIND cell must be FAR from every known radar

A missing site can only turn blind cells into seen ones, so it can never
manufacture the evidence; it can only weaken it. Both statistics are computed
anyway, because the near-radar one is what fails loudly if the projection is
wrong rather than the array.

Measured on the frame of 2026-08-13 23:0x, 10 OSCAR-resolved sites:

    orientation   seen within 50 km   blind-cell distance to nearest radar
                                        p10        median      mean
    as read           100.0%          253.7 km    349.0 km    365.6 km
    vertical flip      72.1%           88.3 km    241.3 km    257.4 km
    horizontal flip       --          111.1 km    241.0 km    265.3 km
    180 rotation      100.0%          209.0 km    334.0 km    346.5 km

**So the verdict is deliberately partial, and says so.** Row order -- the
realistic mistake, and the one every ODIM reader in this directory can make --
is excluded by a wide margin. A 180 degree rotation is not excluded: it needs
both axes reversed at once, which is not producible by a single convention
error, but this instrument cannot rule it out and must not pretend to. Norway
carries the same open corner for the same reason.

This module is the judgement, not the download: callers supply the mask and
the sites, so it runs without a network.
"""
import math

# A blind cell this far from every known radar is evidence; nearer than this it
# is noise. Derived from the products themselves, not chosen round: Swedish
# C-band composites are built to ~240 km range, so cells inside that of a radar
# have no business being blind.
NEAR_KM = 50.0
RANGE_KM = 240.0
# The margin the correct reading must beat every wrong one by. A judgement
# whose branches differ by a percent fires on noise -- Switzerland's mask
# offered exactly that and was discarded for it.
MIN_MARGIN_KM = 60.0
MIN_SITES = 6
MIN_BLIND_SHARE = 0.05


def _nearest_km(y, x, pts, cell_km):
    return min(math.hypot(x - px, y - py) for px, py in pts) * cell_km


def blind_distance(seen, pts, cell_km, index, step=3):
    """-> (n, p10_km, median_km, mean_km) over cells `index` says are blind.

    `seen[row][col]` is True where the composite looked. `index(y, x)` reads it
    through a candidate orientation. Returns None when there is nothing to
    measure, rather than a number that would read as a measurement.
    """
    h, w = len(seen), len(seen[0])
    ds = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if not index(y, x):
                ds.append(_nearest_km(y, x, pts, cell_km))
    if not ds:
        return None
    ds.sort()
    n = len(ds)
    return n, ds[n // 10], ds[n // 2], sum(ds) / n


def seen_near_radars(seen, pts, cell_km, index):
    """-> share of cells within NEAR_KM of a known radar that are seen."""
    h, w = len(seen), len(seen[0])
    r = int(NEAR_KM / cell_km)
    tot = hit = 0
    for px, py in pts:
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dy * dy + dx * dx > r * r:
                    continue
                y, x = int(py) + dy, int(px) + dx
                if not (0 <= x < w and 0 <= y < h):
                    continue
                tot += 1
                if index(y, x):
                    hit += 1
    return (hit / float(tot)) if tot else None


def orientations(seen):
    h, w = len(seen), len(seen[0])
    return {
        "as-read": lambda y, x: seen[y][x],
        "vertical-flip": lambda y, x: seen[h - 1 - y][x],
        "horizontal-flip": lambda y, x: seen[y][w - 1 - x],
        "180-rotation": lambda y, x: seen[h - 1 - y][w - 1 - x],
    }


def judge(seen, pts, cell_km):
    """-> (verdict, note). OK / FLIPPED / INSUFFICIENT.

    OK means: the row order is right, and every orientation reachable by a
    single convention error scores worse by MIN_MARGIN_KM. It does NOT mean
    every orientation is excluded -- see the module docstring on 180 degrees,
    which is reported in the note rather than swallowed.
    """
    if len(pts) < MIN_SITES:
        return "INSUFFICIENT", ("only %d radar sites resolved, need %d"
                                % (len(pts), MIN_SITES))
    h, w = len(seen), len(seen[0])
    blind = sum(1 for row in seen for v in row if not v) / float(h * w)
    if blind < MIN_BLIND_SHARE:
        # No blind margin, no instrument. Saying OK here would be reporting
        # "I cannot tell" in the word that means "I checked".
        return "INSUFFICIENT", ("only %.1f%% of the grid is blind, need %.0f%% "
                                "-- the mask has nothing to say"
                                % (blind * 100, MIN_BLIND_SHARE * 100))
    got = {}
    for name, f in orientations(seen).items():
        d = blind_distance(seen, pts, cell_km, f)
        if d is None:
            return "INSUFFICIENT", "no blind cells under %s" % name
        got[name] = d[1]          # p10: the tail is where a flip shows first
    note = ", ".join("%s p10 %.0fkm" % (k, v) for k, v in sorted(got.items()))
    best = max(got, key=got.get)
    single = ("vertical-flip", "horizontal-flip")
    margin = min(got["as-read"] - got[k] for k in single)
    if best != "as-read":
        # Direction is not enough on the failure branch either. A wrong
        # orientation that wins by a kilometre is a symmetric mask, not a
        # transposed array, and printing FLIPPED for it would send someone to
        # the code over noise. The test fixture with symmetrically placed
        # radars produced exactly that: 266 km against 265.
        if got[best] - got["as-read"] < MIN_MARGIN_KM:
            return "INSUFFICIENT", ("no orientation wins by the margin -- %s"
                                    % note)
        return "FLIPPED", "%s scores best, not as-read (%s)" % (best, note)
    if margin < MIN_MARGIN_KM:
        return "INSUFFICIENT", ("as-read wins by only %.0f km, need %.0f -- %s"
                                % (margin, MIN_MARGIN_KM, note))
    rot = got["as-read"] - got["180-rotation"]
    return "OK", ("row order confirmed by %.0f km; 180-rotation NOT excluded "
                  "(%.0f km, needs a different instrument); %s"
                  % (margin, rot, note))


def sites_to_cells(sites, to_grid):
    """-> [(col, row)] in fractional cells, skipping sites off the grid."""
    out = []
    for lat, lng in sites:
        p = to_grid(lat, lng)
        if p is not None:
            out.append(p)
    return out
