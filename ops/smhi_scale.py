"""Re-read SMHI's own reflectivity scale and fail if it has moved.

`scripts/radar_smhi.py` converts pixel values with dBZ = 0.4 * DN - 30, and
treats 0 as "no echo" and 255 as "no data". Those four numbers are not ours:
they are attributes SMHI writes into the ODIM HDF5 of every composite frame,

    /dataset1/data1/what: quantity=DBZH, gain, offset, undetect, nodata

and a constant copied out of a file is a constant that can rot silently. If the
gain ever changes, nothing breaks: the map still draws, in the wrong intensity,
and it looks entirely normal. So this asks the source again.

It is not on any reader's path and it needs h5py, which production does not
have. Run it by hand, or from a machine that does:

    python3 ops/smhi_scale.py

Exit code 0 only if every constant still matches. That matters more than the
text: this file exists because a wrong scale is invisible.
"""
import os
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))

URL = ("https://opendata-download-radar.smhi.se/api/version/latest"
       "/area/sweden/product/comp/latest.h5")
WHAT = "/dataset1/data1/what"


def read_attrs(path):
    import h5py
    with h5py.File(path, "r") as f:
        a = f[WHAT].attrs
        q = a["quantity"]
        return {"quantity": q.decode() if isinstance(q, bytes) else str(q),
                "gain": float(a["gain"]), "offset": float(a["offset"]),
                "undetect": float(a["undetect"]), "nodata": float(a["nodata"])}


def compare(attrs, mod):
    """-> list of sentences, empty when everything still agrees."""
    bad = []
    if attrs["quantity"] != "DBZH":
        bad.append("quantity is %r, not DBZH: this is no longer reflectivity"
                   % (attrs["quantity"],))
    for name, ours in (("gain", mod.GAIN), ("offset", mod.OFFSET),
                       ("undetect", float(mod.UNDETECT)), ("nodata", float(mod.NODATA))):
        theirs = attrs[name]
        if abs(theirs - ours) > 1e-9:
            bad.append("%s is %r upstream, %r in radar_smhi.py" % (name, theirs, ours))
    return bad


def main():
    try:
        import h5py       # noqa: F401
    except ImportError:
        sys.exit("h5py is not installed here. That is the whole reason this check\n"
                 "is a hand-run tool and not a production import: pip install h5py\n"
                 "in a scratch environment and run it there.")
    import radar_smhi
    tmp = os.path.join(tempfile.gettempdir(), "smhi-scale-check.h5")
    raw = urllib.request.urlopen(
        urllib.request.Request(URL, headers={"User-Agent": radar_smhi.UA}),
        timeout=60).read()
    with open(tmp, "wb") as fh:
        fh.write(raw)
    attrs = read_attrs(tmp)
    print("upstream %s: %s" % (WHAT, attrs))
    bad = compare(attrs, radar_smhi)
    for line in bad:
        print("CHANGED  " + line)
    print("OK  the scale in radar_smhi.py still matches the source"
          if not bad else "-- %d constant(s) moved" % (len(bad),))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
