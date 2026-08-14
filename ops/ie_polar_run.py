"""Check the Irish compositor against the live volumes, and fail if it drifts.

`ie_polar.py` is the judgement and runs without a network or h5py; this is the
download, and it is separate for the same reason `se_orient_run.py` is.

The control it applies is the one Ireland gets for free and the composite-based
sources do not: **we build the grid, so wrong geometry shows up as coverage that
is not a disc centred on the radar.** Switzerland has no such control worth
having -- its composite is built around its own radar network, so a vertical
flip nearly maps onto itself (140.6 km vs 142.0). Here the site position is in
the file and can be checked against where the coverage actually lands.

    python3 ops/ie_polar_run.py
    rc 0  checked and passed      rc 1  failed      rc 2  could not be checked

**What it can and cannot catch, stated because the first version overstated it.**
Reach was originally asserted against `nbins * rscale` -- both sides of the
comparison came from the same two numbers, so it was a tautology. Forcing Dublin
to Shannon's 500 m rscale halved its reach to 125 km and the check still printed
OK. Firing it is the only reason that is known.

The replacement asks a genuinely different field: a radar cannot unambiguously
range past `c / (2 * PRF)`, and PRF is not derived from rscale or nbins. That
bounds reach **from above only**. An under-scaled reach is still undetectable
here, and the run says so on every pass rather than leaving the gap implied.

The obvious two-sided control -- agreement between the two radars where their
discs overlap -- was measured and rejected: on 2026-08-14 the two never both
reported rain in 21494 overlapping cells (Jaccard 0.000 correct, 0.000 with the
bug). A statistic that reads the same either way has no jurisdiction.
"""
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "ops"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ie_polar as P                      # noqa: E402

UA = "runemap/1.0 (+https://echorune.net)"
DIR = "https://opendata2.met.ie/radar/%Y/%m/%d/"

#: NOT `latest/`. Measured 2026-08-14: `latest/` carries the *previous* day's
#: frame range -- its newest file was 7.5 h old while the dated directory held
#: frames 20 minutes old. It does not error or thin out, so an adapter built on
#: it draws stale rain labelled current. See docs/ireland_meteireann_feasibility.md
PRODUCTS = (("T_PAGZ40", "Shannon"), ("T_PAGZ41", "Dublin"))

#: How far a coverage centroid may sit from the radar that produced it. This is
#: not a roundness test: a disc clipped by the sample box has a centroid pulled
#: toward the box, which is geometry rather than error, so the box below is
#: drawn wide enough to contain Shannon whole and the tolerance carries Dublin,
#: whose disc runs past the eastern edge.
MAX_CENTROID_KM = 12.0

#: Speed of light, for the unambiguous range implied by the pulse repetition
#: frequency: r_unamb = c / (2 * PRF).
C_M_S = 299792458.0

#: How far the measured reach may exceed the PRF's unambiguous range. A radar
#: cannot unambiguously range beyond c/(2*PRF), so a measured reach past it
#: means our geometry is stretching the data -- and crucially **PRF is a
#: different field from rscale and nbins**, so this is a real second opinion.
#:
#: The first version of this check compared the measured reach against
#: `nbins * rscale` and was a tautology: both sides came from the same two
#: numbers, so forcing Dublin to Shannon's 500 m rscale halved its reach to
#: 125 km and the check still printed OK. It was only caught by firing it.
#: Measured 2026-08-14: Shannon 248.5 km stored against 249.8 km unambiguous
#: (600 Hz); Dublin 250.0 against 299.8 (500 Hz).
REACH_OVER_UNAMBIGUOUS_TOL_KM = 5.0

BOX = (49.0, 57.0, -13.0, -3.0)


def _get(url, timeout=60):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def newest(prefix, log=print):
    """-> the newest file name for one radar, from the dated directory."""
    import re
    import time
    d = time.strftime(DIR, time.gmtime())
    body = _get(d).decode("utf8", "replace")
    names = sorted(set(re.findall(
        r'(%s_C_EIDB_\d{14}\.h5)' % prefix, body)))
    if not names:
        log("%s: no frames listed in %s" % (prefix, d))
        return None, d
    return names[-1], d


def load(blob):
    """-> the lowest sweep of one polar volume, as plain values."""
    import tempfile

    import h5py
    import numpy as np

    path = os.path.join(tempfile.mkdtemp(), "v.h5")
    with open(path, "wb") as fh:
        fh.write(blob)
    h = h5py.File(path, "r")
    dec = lambda v: v.decode() if isinstance(v, bytes) else v   # noqa: E731
    g = h["dataset1"]
    w = g["where"].attrs
    q = g["data1"]["what"].attrs
    site = h["where"].attrs
    out = dict(
        lat=float(site["lat"]), lon=float(site["lon"]),
        rscale=float(w["rscale"]), nbins=int(w["nbins"]),
        # rstart is in km in ODIM, and is 0 in these files; converting it here
        # rather than assuming zero, because "it is zero today" is how the
        # per-site rscale trap got set in the first place.
        rstart=float(w.get("rstart", 0.0)) * 1000.0,
        startaz=np.asarray(g["how"].attrs["startazA"][:]),
        gain=float(q["gain"]), offset=float(q["offset"]),
        nodata=float(q["nodata"]), undetect=float(q["undetect"]),
        data=g["data1"]["data"][:],
        # The observation time of the layer actually drawn. NOT the filename
        # (Shannon sweeps top-down: its 0.5 deg sweep runs ~4 minutes after the
        # stamp on its own file) and NOT /what/time (nominal end of volume).
        start=dec(g["what"].attrs["starttime"]),
        # An independent second opinion on range: PRF is not derived from
        # rscale or nbins, so it can contradict them.
        highprf=float(g["how"].attrs.get("highprf", 0.0) or 0.0),
        source=dec(h["what"].attrs["source"]))
    h.close()
    return out


def main():
    try:
        import numpy as np
    except ImportError:
        sys.exit("NO-NUMPY: cannot run the compositor at all")
    try:
        import h5py            # noqa: F401
    except ImportError:
        # Distinct from every other refusal on purpose: a missing reader and a
        # dead upstream send you to different places, and printing one word for
        # both wastes the next hour on a service that is answering fine.
        sys.exit("NO-READER: h5py is not installed (pip install '.[hdf5]')")

    lats = np.linspace(BOX[0], BOX[1], 161)
    lons = np.linspace(BOX[2], BOX[3], 201)
    la, lo = np.meshgrid(lats, lons, indexing="ij")

    sweeps, bad, unchecked = [], [], []
    for prefix, name in PRODUCTS:
        fn, d = newest(prefix)
        if not fn:
            bad.append("%s: no frame listed" % name)
            continue
        st = load(_get(d + fn))
        dbz, seen = P.sample_sweep(
            st["data"], st["startaz"], st["rscale"], st["nbins"], st["rstart"],
            st["gain"], st["offset"], st["nodata"], st["undetect"],
            st["lat"], st["lon"], la, lo)
        sweeps.append((dbz, seen))

        if not seen.any():
            bad.append("%s: no coverage inside the sample box" % name)
            continue
        clat, clon = la[seen].mean(), lo[seen].mean()
        off = P.ground_range_and_azimuth(
            st["lat"], st["lon"], [clat], [clon])[0][0] / 1000.0
        rng, _az = P.ground_range_and_azimuth(
            st["lat"], st["lon"], la[seen], lo[seen])
        reach = rng.max() / 1000.0
        unamb = (C_M_S / (2.0 * st["highprf"]) / 1000.0) if st["highprf"] else None

        print("  %-8s %-32s sweep %s  seen %5.1f%%  centroid off %5.1f km  "
              "reach %6.1f km  unambiguous %s"
              % (name, st["source"], st["start"], 100 * seen.mean(), off, reach,
                 ("%6.1f km (PRF %.0f Hz)" % (unamb, st["highprf"]))
                 if unamb else "UNKNOWN -- no PRF in file"))
        if off > MAX_CENTROID_KM:
            bad.append("%s: coverage centroid %.1f km from the radar (max %.1f)"
                       % (name, off, MAX_CENTROID_KM))
        if unamb is None:
            # Not a pass. The one independent opinion on range is missing, and
            # saying so is the whole point of having the word.
            unchecked.append("%s: no PRF, so reach is unverified" % name)
        elif reach - unamb > REACH_OVER_UNAMBIGUOUS_TOL_KM:
            bad.append("%s: reach %.1f km exceeds the PRF's unambiguous range "
                       "%.1f km -- the geometry is stretching the data"
                       % (name, reach, unamb))

    if not sweeps:
        sys.exit("INSUFFICIENT: no sweeps loaded, so nothing was checked -- "
                 "which is not the same as a passing check")

    dbz, seen = P.composite(sweeps)
    wet = int(np.sum(~np.isnan(dbz)))
    print("composite: seen %.1f%% of the box, %d cells at or above the 7 dBZ "
          "floor (%.2f%% of seen)"
          % (100 * seen.mean(), wet, 100.0 * wet / max(1, int(seen.sum()))))

    # Stated every run, pass or fail. This runner can catch a reach that is too
    # LARGE (the PRF bounds it from above) and cannot catch one that is too
    # SMALL: forcing Dublin to Shannon's 500 m rscale halves its reach to
    # 125 km, which is still comfortably inside its 299.8 km unambiguous range,
    # and every check here passes. The obvious two-sided control -- agreement
    # between the two radars where their discs overlap -- was measured on
    # 2026-08-14 and is not usable: Shannon's echo lies west, Dublin's east,
    # and in 21494 overlapping cells the two never both report rain (Jaccard
    # 0.000 with correct geometry, and 0.000 with the bug too). A statistic
    # that reads the same either way has no jurisdiction, so it is not shipped
    # as one.
    print("LIMIT: an under-scaled reach is NOT detectable here; the PRF bounds "
          "reach from above only, and cross-radar overlap has no margin today")
    for u in unchecked:
        print("UNVERIFIED %s" % u)

    if bad:
        for b in bad:
            print("FAIL %s" % b)
        return 1
    if unchecked:
        return 2
    print("OK: both discs centred on their own radar, and neither reach "
          "exceeds the range its own PRF allows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
