"""Run the Swedish orientation check against the live composite.

Separate from `se_orient.py` on purpose: that module is the judgement and runs
without a network, this one is the download. It resolves the radar sites the
way the fleet settled on after NOAA's isd-history returned confident wrong
coordinates (3 of 12 for Norway, two off by 120 and 180 km): BALTRAD's
odim_source.xml for the WMO id of each ODIM node, WMO OSCAR/Surface for the
position, and the registry's place name asserted against OSCAR's station name,
refusing the row when they disagree. Losing a true site costs less than
accepting a wrong one -- Gotland's `sehem` is refused here for exactly that
reason, and it really is the Gotland radar.

    python3 ops/se_orient_run.py

Prints the verdict and exits non-zero on FLIPPED or INSUFFICIENT, so it can be
fired: a check that cannot fail is decoration.
"""
import json
import os
import re
import sys
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "ops"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import se_orient          # noqa: E402
import utm                # noqa: E402

UA = "runemap/1.0 (+https://echorune.net)"
ODIM = ("https://raw.githubusercontent.com/baltrad/rave/master/config/"
        "odim_source.xml")
OSCAR = ("https://oscar.wmo.int/surface/rest/api/search/station?wigosId="
         "0-20000-0-%s")


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def sites(log=print):
    """-> [(node, place, lat, lng)] for the SE nodes OSCAR confirms by name."""
    xml = _get(ODIM).decode()
    found = re.findall(r'(se[a-z]{3}) plc="([^"]+)" rad="SE\d+" wmo="(\d{5})"',
                       xml)
    out = []
    for node, plc, wmo in found:
        try:
            rows = json.loads(_get(OSCAR % wmo.lstrip("0"), 30))
        except Exception as e:                      # noqa: BLE001
            log("  %s %s: OSCAR error %s" % (node, plc, e))
            continue
        rows = rows if isinstance(rows, list) else rows.get(
            "stationSearchResults", [])
        if not rows:
            log("  %s %s: no OSCAR row -- skipped, not guessed" % (node, plc))
            continue
        r = rows[0]
        base = plc.split(" (")[0]
        if base.lower() not in (r.get("name") or "").lower():
            log("  %s %s: OSCAR says %r -- REFUSED on name mismatch"
                % (node, plc, r.get("name")))
            continue
        out.append((node, base, float(r["latitude"]), float(r["longitude"])))
        time.sleep(0.3)
    log("%d of %d SE nodes resolved" % (len(out), len(found)))
    return out


def mask_and_grid():
    """-> (seen[row][col], to_grid, cell_km) from the live SMHI composite."""
    from PIL import Image
    import radar_smhi as S
    import tempfile
    blob = _get(S.URL, 60)
    path = os.path.join(tempfile.mkdtemp(), "comp.tif")
    with open(path, "wb") as fh:
        fh.write(blob)
    im = Image.open(path)
    e0, n0, sc, w, h = S.georeference(im)
    px = im.load()
    seen = [[px[x, y] != S.NODATA for x in range(w)] for y in range(h)]

    def to_grid(lat, lng):
        e, n = utm.forward(lat, lng, 33)
        x, y = (e - e0) / sc, (n0 - n) / sc
        return (x, y) if 0 <= x < w and 0 <= y < h else None

    return seen, to_grid, sc / 1000.0


def main():
    resolved = sites()
    seen, to_grid, cell_km = mask_and_grid()
    pts = se_orient.sites_to_cells([(lat, lng) for _n, _p, lat, lng in resolved],
                                   to_grid)
    print("%d sites on the grid, %d x %d cells of %.2f km"
          % (len(pts), len(seen[0]), len(seen), cell_km))
    for name, f in sorted(se_orient.orientations(seen).items()):
        d = se_orient.blind_distance(seen, pts, cell_km, f)
        share = se_orient.seen_near_radars(seen, pts, cell_km, f)
        print("  %-16s blind n=%-6d p10 %6.1f km  median %6.1f  mean %6.1f "
              " | seen within %.0f km: %.1f%%"
              % (name, d[0], d[1], d[2], d[3], se_orient.NEAR_KM, share * 100))
    verdict, note = se_orient.judge(seen, pts, cell_km)
    print("%s: %s" % (verdict, note))
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
