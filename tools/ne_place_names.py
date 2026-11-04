"""Give runemap/data/ne/places.json its Chinese and Japanese names.

    python3 -I tools/ne_place_names.py ne_10m_populated_places.zip \
        runemap/data/ne/places.json > places.new.json

Input rows are [lon, lat, name, rank] (or already [.., zh, ja]); output rows
are [lon, lat, name, rank, name_zh, name_ja], same order, same rank. The
names come from Natural Earth's own NAME_ZH / NAME_JA columns (public domain),
so the picture says 苏州 / 横浜市 where the text map's reader would.

Matched by English name AND nearest point within 1 degree, not by row index or
rank: the release these places were cut from orders its rows differently and
ranks them differently (Shanghai is 10 in one and 0 in the other), and there
are many Springfields. A row with no match keeps None and is drawn in English.

The DBF is read as one buffer. Streaming it record by record with
ZipExtFile.read(rlen) returned a short read somewhere and shifted every record
after it -- every name from then on belonged to a different town, and nothing
raised. Some NAME_ZH values are traditional (科洛尼亞·德爾·沙加緬度); that is
the source's choice and is kept, not converted."""
import json, math, struct, sys, zipfile


def ne_rows(zpath):
    z = zipfile.ZipFile(zpath)
    names = z.namelist()
    cpg = [n for n in names if n.lower().endswith(".cpg")]
    enc = z.read(cpg[0]).decode().strip() if cpg else "utf-8"
    raw = z.read([n for n in names if n.lower().endswith(".dbf")][0])
    nrec, hlen, rlen = struct.unpack("<IHH", raw[4:12])
    off, p, pos = {}, 32, 1
    while raw[p] != 0x0D:
        b = raw[p:p + 32]
        off[b[:11].split(b"\0")[0].decode()] = (pos, b[16]); pos += b[16]; p += 32
    assert pos == rlen, (pos, rlen)
    assert len(raw) >= hlen + nrec * rlen, "DBF shorter than its header says"
    g = lambda r, k: r[off[k][0]: off[k][0] + off[k][1]].decode(enc).strip()
    for i in range(nrec):
        r = raw[hlen + i * rlen: hlen + (i + 1) * rlen]
        yield (float(g(r, "LONGITUDE")), float(g(r, "LATITUDE")), g(r, "NAME"),
               g(r, "NAME_ZH") or None, g(r, "NAME_JA") or None)


def main(zpath, places):
    by_name = {}
    for lon, lat, nm, zh, ja in ne_rows(zpath):
        by_name.setdefault(nm, []).append((lon, lat, zh, ja))
    out, miss = [], 0
    for row in json.load(open(places)):
        lon, lat, nm, rank = row[:4]
        best = None
        for c in by_name.get(nm, ()):
            dd = math.hypot(c[0] - lon, c[1] - lat)
            if dd <= 1.0 and (best is None or dd < best[0]):
                best = (dd, c)
        zh, ja = (best[1][2], best[1][3]) if best else (None, None)
        miss += best is None
        out.append([lon, lat, nm, rank, zh, ja])
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    print("%d places, %d without a match" % (len(out), miss), file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:3])
