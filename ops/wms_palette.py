"""Ask a WMS what its colours mean, then check whether it draws colours it never
declared.

Referenced from scripts/radar_wms.py, which is why it exists as a file rather
than as a sentence: a docstring that names a tool nobody wrote is the same kind
of lie as a comment that has fallen behind the code.

Adding a national radar is not one table row. Our renderer assumes a ramp that
runs cool to warm, and a service is free to disagree -- DWD's ends in BLUE at
>=150 mm/h, so the default heuristic reads its heaviest rain as nothing at all.
So before a service may draw for a reader, three questions have to be answered
from the server itself rather than from looking at a picture:

  1. what does each colour mean?          GetStyles -> ColorMapEntry rows
  2. does the legend agree with that?     GetLegendGraphic -> the swatches
  3. does the map contain colours that    a real GetMap over a real city, with
     appear in neither?                   every unexplained colour counted

Question 3 is the one that stopped Germany: 43% of the visible pixels over
Hamburg were a magenta that appears in neither its style document nor its
legend. An unexplained colour is not a rounding error -- it is a state of the
world nobody told us about, and drawing it as rain would look completely normal.

    python3 ops/wms_palette.py <service-key> [lat,lon ...]
"""
import collections
import io
import math
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
import radar_wms as W          # noqa: E402


def _get(url, timeout=30):
    return urllib.request.urlopen(url, timeout=timeout).read()


def styles(svc):
    """-> [(hex, opacity, quantity, label)] from the server's own SLD."""
    q = {"service": "WMS", "version": "1.1.1", "request": "GetStyles",
         "layers": svc["layers"]}
    raw = _get(svc["url"] + "?" + urllib.parse.urlencode(q)).decode("utf-8", "replace")
    return re.findall(r'ColorMapEntry\s+color="([^"]+)"(?:\s+opacity="([^"]*)")?'
                      r'\s+quantity="([^"]*)"\s+label="([^"]*)"', raw)


def legend(svc):
    """-> the swatch colours down the left edge of the legend image.

    Read from the picture because that is the only form this answer comes in;
    the point is agreement with the SLD, so a disagreement is the finding.
    """
    from PIL import Image
    import numpy as np
    q = {"service": "WMS", "version": "1.3.0", "request": "GetLegendGraphic",
         "layer": svc["layers"], "format": "image/png"}
    a = np.array(Image.open(io.BytesIO(_get(svc["url"] + "?" + urllib.parse.urlencode(q))))
                 .convert("RGBA"))
    out = []
    for y in range(a.shape[0]):
        row = [tuple(p) for p in a[y, 2:14, :3].tolist()]
        c = collections.Counter(row).most_common(1)[0][0]
        if c != (255, 255, 255) and (not out or out[-1] != c):
            out.append(c)
    return out


def unexplained(svc, lat, lng, declared):
    """-> (visible, [(colour, count)]) for colours in a real map that nobody
    declared. Runs after the service's own nodata colours are stripped, so what
    is left is genuinely unaccounted for."""
    from PIL import Image
    import numpy as np
    bbox = W.bbox_for(lat, lng)
    raw = W._strip_nodata(_get(W.url_for(svc, bbox)), svc)
    a = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    vis = a[..., 3] > 50
    counts = collections.Counter(map(tuple, a[vis][:, :3].tolist()))
    known = {tuple(W._rgb(h)) for h in declared}
    if not known:
        # No declaration to compare against. The honest return is "I cannot
        # tell", never an empty list of problems -- an empty list reads as a
        # clean bill of health, which is the one answer this must never invent.
        return int(vis.sum()), None
    far = [(c, n) for c, n in counts.items()
           if min((abs(c[0] - k[0]) + abs(c[1] - k[1]) + abs(c[2] - k[2]))
                  for k in known) > 24]
    return int(vis.sum()), sorted(far, key=lambda x: -x[1])


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    key = sys.argv[1]
    svc = next((s for s in W.SERVICES if s["key"] == key), None)
    if svc is None:
        sys.exit("no service %r; have: %s"
                 % (key, ", ".join(s["key"] for s in W.SERVICES)))
    rows = styles(svc)
    print("== %s  (%s)" % (svc["name"], svc["layers"]))
    print("-- GetStyles: %d colour map rows" % len(rows))
    for c, o, q, l in rows:
        print("   %-9s op=%-4s q=%-9s %s" % (c, o or "1", q, re.sub(r"\s+", " ", l)[:28]))
    try:
        leg = legend(svc)
        print("-- GetLegendGraphic: %d swatches" % len(leg))
        sld = {tuple(W._rgb(c)) for c, _o, _q, _l in rows}
        only_leg = [c for c in leg if c not in sld]
        if only_leg:
            print("   in the legend but not the SLD: %s" % (only_leg,))
    except Exception as e:
        print("-- GetLegendGraphic failed: %r" % (e,))
    declared = [c for c, _o, _q, _l in rows]
    for spec in sys.argv[2:]:
        lat, lng = [float(x) for x in spec.split(",")]
        vis, far = unexplained(svc, lat, lng, declared)
        if far is None:
            print("-- %s: %d visible px" % (spec, vis))
            print("   UNVERIFIABLE: this server publishes no machine-readable "
                  "colour map, so 'no unexplained colours' cannot be said. Read "
                  "its legend by hand before trusting the default ramp.")
            continue
        share = (sum(n for _c, n in far) / vis * 100.0) if vis else 0.0
        print("-- %s: %d visible px, %.0f%% unexplained %s"
              % (spec, vis, share, [c for c, _n in far[:4]]))
        # A verdict, not a table: this is the question that stopped Germany.
        print("   %s" % ("SAFE to map with the default ramp" if share < 1.0 else
                         "DO NOT SHIP: a colour nobody declared would be drawn as rain"))


if __name__ == "__main__":
    main()
