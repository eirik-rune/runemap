"""Ask a list of candidate national weather services what they publish.

Written after adding four WMS services one at a time, each by hand. The list is
the cheap part; what this exists for is the three questions that decide whether
a service can be shipped, asked in the order that fails fastest:

  1. is it a WMS at all?            (half of them are JSON APIs or a portal page)
  2. does it declare a radar layer? (name or title, not a guess about the host)
  3. what does it say about fees and access constraints?

It does NOT decide anything. A service that passes all three still needs a
colour-to-intensity mapping, a coverage rectangle that does not annex the
neighbours, and a GetMap that actually answers -- and this morning Belgium
proved those are separate questions: capabilities 200, GetMap 403, from the
same address in the same second.

That last part is why `--map` exists. Advertising a layer and serving it are
two different promises, and only one of them is in the capabilities document.

    python3 ops/wms_sweep.py             # capabilities only
    python3 ops/wms_sweep.py --map       # also try one small GetMap each

Anything that answers is a lead, not a result. The record of what each lead
turned into belongs in docs/second_radar_source.md, next to the ones we
refused, because "we looked at Norway" is only useful if the reason survives.
"""
import concurrent.futures as cf
import re
import sys
import urllib.parse
import urllib.request

UA = "runemap/1.0 (+https://echorune.net)"
RADAR = re.compile(r"radar|radr|refl|dbz|precip|rainfall|niederschlag|nedbor|srazk", re.I)

# Endpoint, and a sky inside the country for the optional GetMap probe.
CANDIDATES = [
    ("be-rmi", "https://opendata.meteo.be/service/radar/wms", (50.85, 4.35)),
    ("ch-swisstopo", "https://wms.geo.admin.ch/", (46.95, 7.45)),
    ("ee-maaamet", "https://kaart.maaamet.ee/wms/alus", (59.44, 24.75)),
    ("no-metno", "https://public-wms.met.no/verportal/verportal.map", (59.91, 10.75)),
    ("pl-imgw", "https://danepubliczne.imgw.pl/geoserver/wms", (52.23, 21.01)),
    ("si-arso", "https://gis.arso.gov.si/arcgis/services/meteo/MapServer/WMSServer", (46.06, 14.51)),
    ("uk-metoffice", "https://maps.consumer-digital.api.metoffice.gov.uk/wms", (51.51, -0.13)),
    ("au-bom", "http://www.bom.gov.au/cgi-bin/ws/gis/ows.pl", (-33.87, 151.21)),
]


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def _join(base, q):
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(q)


def caps(base):
    """-> (layers, radar layers, fees, access) or a sentence saying why not."""
    try:
        raw = _get(_join(base, {"service": "WMS", "request": "GetCapabilities"}))
    except Exception as e:
        return "no capabilities: %s" % (repr(e)[:60],)
    if b"WMS_Capabilities" not in raw and b"WMT_MS_Capabilities" not in raw:
        return "not a WMS (%d bytes)" % (len(raw),)
    t = raw.decode("utf-8", "replace")
    names = re.findall(r"<Name>([^<]+)</Name>", t)
    titles = dict(zip(names, re.findall(r"<Title>([^<]*)</Title>", t)[1:]))
    radar = [n for n in names if RADAR.search(n) or RADAR.search(titles.get(n, ""))]
    fees = re.search(r"<Fees>(.*?)</Fees>", t, re.S)
    acc = re.search(r"<AccessConstraints>(.*?)</AccessConstraints>", t, re.S)
    return {"layers": len(names), "radar": radar,
            "fees": fees.group(1).strip() if fees else None,
            "access": acc.group(1).strip() if acc else None}


def one_map(base, layer, lat, lng):
    """Advertising a layer and serving it are two different promises.

    The result names the layer it asked for, because the first run of this did
    not: Switzerland reported "GetMap ok (54527 bytes)" for
    ch.swisstopo.geologie-reflexionsseismik -- a seismic reflection survey that
    my radar regex matched on "refl". A green line about the wrong subject is
    the failure this whole directory keeps meeting.
    """
    q = {"service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": layer,
         "styles": "", "crs": "EPSG:4326",
         "bbox": "%.2f,%.2f,%.2f,%.2f" % (lat - 0.5, lng - 0.7, lat + 0.5, lng + 0.7),
         "width": 256, "height": 256, "format": "image/png", "transparent": "true"}
    try:
        raw = _get(_join(base, q), timeout=25)
    except Exception as e:
        return "GetMap %s %s" % (layer, repr(e)[:50])
    if raw[:4] == b"\x89PNG":
        return "GetMap %s ok (%d bytes)" % (layer, len(raw))
    return "GetMap %s answered %d bytes that are not a PNG" % (layer, len(raw))


def probe(row, want_map):
    key, base, sky = row
    c = caps(base)
    if isinstance(c, str):
        return key, c
    line = ("WMS layers=%d radar=%d %s | Fees=%r Access=%r"
            % (c["layers"], len(c["radar"]), c["radar"][:4], c["fees"], c["access"]))
    if want_map and c["radar"]:
        line += " | " + one_map(base, c["radar"][0], sky[0], sky[1])
    return key, line


def main():
    want_map = "--map" in sys.argv[1:]
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for key, line in ex.map(lambda r: probe(r, want_map), CANDIDATES):
            print("%-14s %s" % (key, line))


if __name__ == "__main__":
    main()
