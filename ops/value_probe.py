"""Ask the service what a pixel means, instead of inferring it from the picture.

`ops/colour_order.py` recovers an ORDER from the shape of the echo (depth and
adjacency) because JMA publishes no mapping from colour to rain rate. That was
the right tool for JMA. It is the wrong tool wherever the service will simply
tell you, and two of ours will:

  KNMI   GetFeatureInfo returns `image1.image_data ... mm/hr`, with the unit
         declared by the server -- but see the warning below about what a
         "pixel" means to this request
  FMI    GetFeatureInfo returns `GRAY_INDEX`, the raster value behind the colour

So this asks. It fetches one map, finds the distinct visible colours, and for
each one queries a handful of pixels that carry it. What comes back is a
measured colour -> value table, not a derivation, and it can be checked: if a
colour spans values that another colour also spans, then colour is not a
function of value at this resolution and the table must not be shipped.

**What it cannot do on its own**: GetFeatureInfo answers about the grid CELL
under the query at the RESOLUTION OF THE REQUEST, while the colour is a
property of the rendered pixel. Measured on KNMI: a red pixel in a 384px window
over 10.85 degrees reads 3.6 mm/hr, and the same point in a 0.02 degree window
reads 27.3 mm/hr. Both are honest answers to different questions. So a table
built from this is only valid if one image pixel is one grid cell -- and even
then KNMI's "no echo" sentinel (0.000365 mm/hr) still appears under every
colour, so some queries are resolving to a cell that was not the one drawn.
That is why KNMI comes back REFUSED and why the verdict is left alone.

It is a calibration tool, run by hand when the sky has weather in it. It is not
on any reader's path and it must never be: it costs one request per sample.

    python3 ops/value_probe.py fi-fmi          # a service in radar_wms.SERVICES
    python3 ops/value_probe.py knmi            # the one this was written for

The verdicts are the same three the order tool learned to distinguish, for the
same reason -- "I cannot tell" and "these contradict each other" must not print
the same word:

  OK            every colour holds a tight, separable band of values
  REFUSED       two colours overlap: the picture is not carrying the value
  INSUFFICIENT  not enough colours or samples cleared the floor. A dry country
                returns this, and it is a measurement waiting for weather

FMI was meant to be the positive control, because we already know that
ordering independently from the quantities in their own SLD. It is not one,
and the reason is worth more than the control would have been: their default
style is INTERPOLATED -- 59 distinct colours over one small window. An
in-between shade has no declared rank, so matching it to the nearest declared
colour invents one, and the "77% concordant" that came back was a measurement
of my own matching, not of FMI. The tool now refuses interpolated styles
outright rather than judging through them.

So this ships without a positive control, and that is stated rather than
papered over: the OK verdict has never been fired against a live service. The
first discrete style with weather under it is the test.
"""
import collections
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))

UA = "runemap/1.0 (+https://echorune.net)"
MIN_COLOURS = 3          # fewer than three is not a scale; see colour_order.py
# Whether colour is a FUNCTION of value depends on the style, not on the
# service. An interpolated ramp assigns a slightly different colour to every
# value, so no two colours hold disjoint bands and no lookup table exists --
# that is what FMI's default style does, and the first run of this tool called
# it REFUSED, which was true about the table and useless about the service. A
# "/nearest" style is the same data drawn without interpolation, and there the
# table is exact. So the style is an input here.
MIN_PER_COLOUR = 3       # a single sample cannot show spread
# More distinct colours than this in one window is a ramp, not a set of
# classes. The first version of this guard read
# `len(by) > max(MAX_CLASSES, len(vis) // 8)`, and the second term made the
# threshold 245 for a window with 1962 visible pixels -- so it never fired on
# the very case it was written for. A guard whose threshold grows with the
# thing it is guarding against does not guard.
MAX_CLASSES = 24
MAX_REQUESTS = 60        # a hand-run tool still spends somebody else's cycles
PAUSE = 0.15

# Services this can ask. Two of ours answer GetFeatureInfo with a number; the
# rest are here so the tool says "that one does not answer" rather than
# inventing an endpoint.
TARGETS = {
    "knmi": {
        "url": "https://geoservices.knmi.nl/wms?dataset=RADAR",
        "layer": "RAD_NL25_PCP_CM",
        "bbox": (50.7, 3.2, 53.6, 7.3),
        "parse": "adaguc",
        # They publish "/nearest" variants of every style. Nearest means the
        # picture carries discrete classes, which is the only case where a
        # colour table can be exact rather than approximately right.
        "style": "precip-blue/nearest",
    },
    "fi-fmi": {
        "url": "https://openwms.fmi.fi/geoserver/Radar/wms",
        "layer": "suomi_dbz_eureffin",
        "bbox": (59.5, 20.0, 64.0, 29.0),
        "parse": "geoserver",
        "style": "",
        # The positive control. We already know this order independently, from
        # the quantities in FMI's own SLD, so if the probe cannot reproduce an
        # ordering we know, it has no business proposing one we do not.
        "known_order": [("#6cebf3", 1), ("#58c797", 1), ("#409857", 2),
                        ("#f1f35a", 2), ("#dfc40a", 3), ("#eb951a", 3),
                        ("#e85616", 4), ("#ce0202", 4), ("#830a46", 5),
                        ("#fa51a5", 5)],
    },
}


def _join(base, q):
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(q)


def _get(url, timeout=30):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read()


def _common(t, px):
    s, w, n, e = t["bbox"]
    return {"service": "WMS", "version": "1.3.0", "layers": t["layer"],
            "styles": t.get("style", ""),
            "crs": "EPSG:4326", "bbox": "%s,%s,%s,%s" % (s, w, n, e),
            "width": px, "height": px, "format": "image/png", "transparent": "true"}


def parse_value(body, how):
    """-> float, or None if the answer carries no number.

    None is a value here, not an error: "the server answered and said nothing
    numeric" is a different fact from "the request failed", and folding them
    together is how a calibration ends up built on silence.
    """
    if how == "geoserver":
        try:
            d = json.loads(body)
        except Exception:
            return None
        for f in d.get("features", []):
            for v in (f.get("properties") or {}).values():
                if isinstance(v, (int, float)):
                    return float(v)
        return None
    m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(mm/hr|mm/h|dBZ)", body.decode("utf-8", "replace"))
    return float(m.group(1)) if m else None


def sample(key, px=256, per_colour=5):
    t = TARGETS[key]
    import numpy as np
    from PIL import Image
    raw = _get(_join(t["url"], dict(_common(t, px), request="GetMap")))
    if raw[:4] != b"\x89PNG":
        return None, "GetMap did not answer with a PNG (%d bytes)" % (len(raw),)
    a = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    vis = np.argwhere(a[..., 3] > 50)
    if len(vis) == 0:
        return None, "nothing visible: the sky is empty, not the service"
    by = collections.defaultdict(list)
    for j, i in vis:
        by[tuple(int(v) for v in a[j, i, :3])].append((int(i), int(j)))
    # An interpolated ramp gives almost every pixel its own shade. There is no
    # table to recover from one, and -- the part that cost an hour -- matching
    # an in-between shade to the nearest DECLARED colour assigns it a rank that
    # is noise, so even the ordering check becomes a measurement of my own
    # approximation. Measured on FMI's default style: 60 distinct colours over
    # 1962 visible pixels, and a control that came back 77% concordant, which
    # says nothing about FMI. Refuse the style instead of judging through it.
    if len(by) > MAX_CLASSES:
        return None, ("this style is interpolated (%d distinct colours over %d"
                      " visible pixels) -- ask for a discrete style; there is no"
                      " table in a ramp and no honest rank for a blend"
                      % (len(by), len(vis)))
    fmt = "application/json" if t["parse"] == "geoserver" else "text/plain"
    out, spent = {}, 0
    for colour, pts in sorted(by.items(), key=lambda kv: -len(kv[1])):
        step = max(1, len(pts) // per_colour)
        for i, j in pts[::step][:per_colour]:
            if spent >= MAX_REQUESTS:
                break
            q = dict(_common(t, px), request="GetFeatureInfo", query_layers=t["layer"],
                     info_format=fmt, i=i, j=j, feature_count=1)
            try:
                v = parse_value(_get(_join(t["url"], q)), t["parse"])
            except Exception as e:
                sys.stderr.write("VALUE-PROBE-FAILED %s %r\n" % (colour, e))
                v = None
            spent += 1
            time.sleep(PAUSE)
            if v is not None:
                out.setdefault(colour, []).append(v)
        if spent >= MAX_REQUESTS:
            break
    return out, "%d requests, %d colours seen" % (spent, len(by))


def _rank_agreement(table, known):
    """Does the sampled ordering agree with an ordering we already know?

    This is the question that matters for our grid: we need to know which
    colour means more rain, not what the millimetres are. It is asked as
    concordant pairs, so a ramp with a hundred interpolated shades is judged
    on the same footing as eight discrete classes.

    Colours are matched to the known scale by nearest RGB. That is an
    approximation, and it is only allowed here because this function judges a
    control we can already check by hand -- never to build a shipped table.
    """
    def rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    # Rank by POSITION in the declared scale, not by the level we bucket it
    # into. The first run compared levels and got zero comparable pairs: every
    # colour visible in a light shower maps into level 1, so dl was 0
    # everywhere and the control could not say anything. The position is the
    # finer ordering, and it is the one being tested.
    ref = [(rgb(h), i) for i, (h, _lv) in enumerate(known)]
    pairs = []
    for colour, vs in table.items():
        near = min(ref, key=lambda r: sum((a - b) ** 2 for a, b in zip(r[0], colour)))
        pairs.append((sum(vs) / float(len(vs)), near[1]))
    con = dis = 0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            dv = pairs[i][0] - pairs[j][0]
            dl = pairs[i][1] - pairs[j][1]
            if dv == 0 or dl == 0:
                continue
            if (dv > 0) == (dl > 0):
                con += 1
            else:
                dis += 1
    return con, dis


def verdict(table, known=None):
    """-> (word, sentence).

    Two different questions, and the first run of this tool answered only the
    second and reported it as if it were the first:

      ORDER  does the picture tell us which colour means more? This is all our
             grid needs, and an interpolated ramp answers it perfectly well.
      TABLE  can each colour be mapped to a band of values nothing else holds?
             Only a discrete style can, and only that supports a lookup.

    FMI's default style is interpolated -- 60 shades over one small window --
    so it fails TABLE and passes ORDER. Calling that REFUSED was true about
    the table and useless about the service.
    """
    usable = {c: v for c, v in table.items() if len(v) >= MIN_PER_COLOUR}
    if len(usable) < MIN_COLOURS:
        return "INSUFFICIENT", ("only %d colour(s) reached %d samples -- not enough"
                                " to be a scale, and not a statement about the"
                                " service" % (len(usable), MIN_PER_COLOUR))
    if known:
        con, dis = _rank_agreement(usable, known)
        if con + dis < 10:
            return "INSUFFICIENT", "only %d comparable pairs against the known scale" % (con + dis,)
        share = con / float(con + dis)
        if share < 0.9:
            return "REFUSED", ("the sampled order agrees with the known scale on"
                               " only %.0f%% of %d pairs" % (share * 100, con + dis))
        return "OK", ("the sampled order reproduces the known scale on %.0f%% of"
                      " %d pairs" % (share * 100, con + dis))
    bands = {c: (min(v), max(v)) for c, v in usable.items()}
    order = sorted(bands, key=lambda c: sum(bands[c]) / 2.0)
    for a, b in zip(order, order[1:]):
        if bands[a][1] > bands[b][0]:
            return "REFUSED", ("%s spans %.4g-%.4g and %s spans %.4g-%.4g: they"
                               " overlap, so this style carries no lookup table."
                               " Ask for a discrete (\"/nearest\") style"
                               % (a, bands[a][0], bands[a][1], b, bands[b][0], bands[b][1]))
    return "OK", "%d colours, each holding a separable band" % (len(order),)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        sys.exit("usage: value_probe.py <%s>" % ("|".join(sorted(TARGETS)),))
    key = sys.argv[1]
    table, note = sample(key)
    if table is None:
        print("INSUFFICIENT %s: %s" % (key, note))
        sys.exit(2)
    print("-- %s: %s" % (key, note))
    for colour, vs in sorted(table.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print("   #%02x%02x%02x n=%d  %s" % (colour[0], colour[1], colour[2], len(vs),
                                             " ".join("%.4g" % v for v in vs)))
    word, why = verdict(table, TARGETS[key].get("known_order"))
    print("%s %s: %s" % (word, key, why))
    sys.exit(0 if word == "OK" else (1 if word == "REFUSED" else 2))


if __name__ == "__main__":
    main()
