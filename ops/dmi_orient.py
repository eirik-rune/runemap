"""Is DMI's composite read the right way up? Measured against their own radars.

The assumption under `scripts/radar_dmi.py` is that row 0 is the north edge and
column 0 the west one. That is what ODIM says and what everyone does -- and a
grid read upside down does not fail. It draws a scale-correct, fresh-stamped
map with the weather on the wrong half of the country, and no field in the file
says otherwise. So it has to be measured against something the product cannot
forge.

**What it cannot forge is where it is blind.** A composite sees only within
range of its radars, so the nodata mask is the union of four circles, and those
circles are somewhere very specific. This tool asks:

  * every radar site's own pixel must be SEEN -- a radar covers its own mast;
  * a point far from every radar must be NODATA;

and then re-runs both checks against the vertically flipped array. If the flip
also passes, the check cannot tell the two apart and the verdict is DISAGREE
rather than OK -- a check that passes both ways is decoration (8/01).

**The site coordinates are not typed in here.** DMI publishes each radar's own
volume file, and `/where` in it carries that radar's lat/lon and its name. This
tool reads them from those files, so the control is the source describing
itself rather than me describing the source from memory.

    ./ops/dmi_orient.py            fetches the newest composite and volumes

Verdicts: OK / FLIPPED / DISAGREE / INSUFFICIENT. "I cannot tell" gets its own
word, because printing OK for it is how a ruler starts lying.
"""
import json
import math
import os
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(os.path.dirname(_HERE), "scripts"),
           os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VOLUMES = ("https://dmigw.govcloud.dk/v1/radardata/collections/volume/items"
           "?limit=12&sortorder=datetime,DESC")
DOWNLOAD = "https://dmigw.govcloud.dk/v1/radardata/download/%s"
UA = "runemap/1.0 (+https://echorune.net)"

# Far from every Danish radar, still inside the grid: the middle of the North
# Sea and a point in Poland. Both must be blind in a correctly-read file.
FAR = ((56.9, 4.2), (53.3, 17.4))
MIN_FAR_KM = 300.0

# A radar's usable range here is about 240 km, so the union of the four circles
# is centred on the mean of the sites give or take which of them are running.
# A quarter of that range is the slack that asymmetry can buy; anything further
# is not a lopsided day, it is the wrong geometry. Measured on 2026-08-13
# 15:45: 6 km as read, 113 km flipped.
RANGE_KM = 240.0
CENTROID_TOL_KM = RANGE_KM / 4.0


def _get(url, timeout=30):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}),
        timeout=timeout).read()


def sites(get=None):
    """-> [(name, lat, lon)] read out of DMI's own volume files."""
    get = get or _get
    feats = json.loads(get(VOLUMES).decode()).get("features") or []
    seen, out = set(), []
    import h5py
    import tempfile
    for f in feats:
        name = f["id"]
        stn = name.split("_")[0]
        if stn in seen:
            continue
        seen.add(stn)
        raw = get(DOWNLOAD % name)
        p = os.path.join(tempfile.gettempdir(), "dmi-vol-%s.h5" % stn)
        with open(p, "wb") as fh:
            fh.write(raw)
        with h5py.File(p, "r") as h:
            w = h["/where"].attrs
            out.append((stn, float(w["lat"]), float(w["lon"])))
        os.unlink(p)
    return out


def _cell(corners, cell_m, shape, lat, lng):
    import stereo_oblique as SO
    ax, ay = SO.forward(corners["UL_lat"], corners["UL_lon"])
    x, y = SO.forward(lat, lng)
    px = int(round((x - ax) / cell_m))
    py = int(round((ay - y) / cell_m))
    h, w = shape
    return (py, px) if (0 <= px < w and 0 <= py < h) else None


def centroid_km(arr, scale, corners, cell_m, site_list):
    """-> km between the centre of the SEEN area and the centre of the radars.

    The binary site checks alone are thin: flipping this frame still lit 3 of 5
    sites, because four of the five Danish radars sit within half a degree of
    each other and a flip lands them back inside the coverage. This is
    continuous and does not depend on any single radar.
    """
    import numpy as np
    import stereo_oblique as SO
    ax, ay = SO.forward(corners["UL_lat"], corners["UL_lon"])
    ys, xs = np.nonzero(arr != scale["nodata"])
    if not len(ys):
        return None
    cx, cy = ax + xs.mean() * cell_m, ay - ys.mean() * cell_m
    sx = np.mean([SO.forward(la, lo)[0] for _n, la, lo in site_list])
    sy = np.mean([SO.forward(la, lo)[1] for _n, la, lo in site_list])
    return math.hypot(cx - sx, cy - sy) / 1000.0


def judge(arr, scale, corners, cell_m, site_list):
    """-> (verdict, notes). Runs the same checks on the array and its flip."""
    import numpy as np

    def score(a):
        hits = miss = 0
        for _n, lat, lng in site_list:
            rc = _cell(corners, cell_m, a.shape, lat, lng)
            if rc is None:
                continue
            hits += 1 if a[rc] != scale["nodata"] else 0
            miss += 1
        blind = 0
        for lat, lng in FAR:
            rc = _cell(corners, cell_m, a.shape, lat, lng)
            if rc is None:
                continue
            blind += 1 if a[rc] == scale["nodata"] else 0
        return hits, miss, blind

    if len(site_list) < 2:
        return "INSUFFICIENT", "only %d radar sites readable" % len(site_list)
    up = score(arr)
    down = score(np.flipud(arr))
    c_up = centroid_km(arr, scale, corners, cell_m, site_list)
    c_down = centroid_km(np.flipud(arr), scale, corners, cell_m, site_list)
    if c_up is None or c_down is None:
        return "INSUFFICIENT", "the frame has no seen area at all"
    ok_up = (up[0] == up[1] and up[2] == len(FAR) and c_up < CENTROID_TOL_KM)
    ok_down = (down[0] == down[1] and down[2] == len(FAR)
               and c_down < CENTROID_TOL_KM)
    note = ("as-read sites %d/%d far-blind %d/%d centroid %.0fkm | "
            "flipped sites %d/%d far-blind %d/%d centroid %.0fkm" % (
                up[0], up[1], up[2], len(FAR), c_up,
                down[0], down[1], down[2], len(FAR), c_down))
    if ok_up and ok_down:
        # The measurement cannot separate the two hypotheses -- which is a fact
        # about this frame (a wet, wide day can make both look plausible), not
        # a licence to report the one I hoped for.
        return "DISAGREE", note
    if ok_up:
        return "OK", note
    if ok_down:
        return "FLIPPED", note
    return "DISAGREE", note


def main():
    import radar_dmi as D
    name = D.newest_frame()
    if not name:
        print("INSUFFICIENT  no frame published")
        return 1
    path = D.download(name)
    if not path:
        print("INSUFFICIENT  frame did not download")
        return 1
    arr, scale, corners, cell_m = D.read(path)
    st = sites()
    verdict, note = judge(arr, scale, corners, cell_m, st)
    print("%-12s %s" % (verdict, name))
    print("  sites: %s" % ", ".join("%s %.3f,%.3f" % s for s in st))
    print("  %s" % note)
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
