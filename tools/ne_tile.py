"""Offline: cut a Natural Earth 10m layer into 10-degree tiles, simplified.
usage: ne_tile.py <geojson> <out.npz> poly|line
Run once; the service only reads the npz (one tile decompressed per key)."""
import json, sys, resource
import numpy as np
from shapely.geometry import shape, box
from shapely import make_valid
src, out, kind = sys.argv[1:4]
T, TOL = 10, 0.002
feats = json.load(open(src))["features"]
geoms = [make_valid(shape(f["geometry"])) for f in feats if f.get("geometry")]
del feats
tiles = {}
def add(key, coords, hole):
    a = np.round(np.asarray(coords)[:, :2] * 1000).astype(np.int32)
    if len(a) < 2: return
    t = tiles.setdefault(key, ([], [], []))
    t[0].append(a); t[1].append(len(a)); t[2].append(hole)
def emit(key, g):
    if g.is_empty: return
    gt = g.geom_type
    if gt in ("GeometryCollection", "MultiPolygon", "MultiLineString"):
        for s in g.geoms: emit(key, s)
    elif gt == "Polygon" and kind == "poly":
        add(key, g.exterior.coords, 0)
        for r in g.interiors: add(key, r.coords, 1)
    elif gt == "LineString" and kind == "line":
        add(key, g.coords, 0)
for g in geoms:
    x0, y0, x1, y1 = g.bounds
    for tx in range(int(np.floor(x0 / T)) * T, int(np.ceil(x1 / T)) * T, T):
        for ty in range(int(np.floor(y0 / T)) * T, int(np.ceil(y1 / T)) * T, T):
            c = g.intersection(box(tx, ty, tx + T, ty + T))
            emit("%d_%d" % (tx, ty), c.simplify(TOL, preserve_topology=True))
arrs = {}
for k, (cs, ns, hs) in tiles.items():
    arrs[k + "_xy"] = np.concatenate(cs)
    arrs[k + "_n"] = np.array(ns, np.int32)
    arrs[k + "_h"] = np.array(hs, np.int8)
np.savez_compressed(out, **arrs)
print(out, len(tiles), "tiles", sum(len(a) for k, a in arrs.items() if k.endswith("_xy")), "pts",
      "peakRSS=%dMB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024))
