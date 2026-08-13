"""IMD's radar stations, read from IMD's own server rather than guessed.

Why this file exists: on 8/13 I typed four station names at a national met
service to find out which one covers Mumbai, and hit once out of four. That
broke my own rule -- names come from the source, never from my fingers -- and
it cost somebody else four requests to find out something they publish.

They publish it. `reactjs.imd.gov.in` runs a GeoServer whose capabilities
declare Fees NONE and AccessConstraints NONE, and its WFS hands out
`imd:radar_station_status` as GeoJSON: 39 stations, each with a code, a name,
latitude and longitude, and -- this is the part worth more than the
coordinates -- a status flag with the time the image was last updated.

    python3 ops/imd_stations.py [lat,lon]

With a coordinate it names the nearest station and says whether that station
is currently producing images; with none it prints the whole table.

What this does NOT give us, and what still blocks India: the georeference of
the radar images themselves. The products are animated GIFs
(mausam.imd.gov.in/Radar/{caz,ppi,ppz,sri}_{code}.gif), IMD's own radar page
does not draw them on a map (Leaflet is loaded, but only to place the station
markers), and no GeoTIFF or PNG variant exists. So the extent of the picture
is genuinely unpublished, and turning one into our grid means registering it
against known geography -- real work, but work with a check that can fail,
which is the only kind worth starting.
"""
import json
import math
import sys
import urllib.request

URL = ("https://reactjs.imd.gov.in/geoserver/imd/ows?service=WFS&version=1.0.0"
       "&request=GetFeature&typeName=imd:radar_station_status"
       "&outputFormat=application/json")


def stations(get=None):
    raw = (get or (lambda u: urllib.request.urlopen(u, timeout=30).read()))(URL)
    out = []
    for f in json.loads(raw).get("features", []):
        p = f.get("properties") or {}
        if p.get("latitude") is None or p.get("longitude") is None:
            continue        # a station with no position is not a fallback,
        out.append(p)       # it is a row we cannot use, and saying so is free
    return out


def nearest(lat, lng, rows):
    """Nearest station by great-circle distance, with its distance in km.

    Nearest, not "first that matches", because a radar's usefulness falls off
    with range: a sky at the rim of a disc is where the beam is highest and
    the picture worst.
    """
    def km(p):
        dlat = math.radians(p["latitude"] - lat)
        dlng = math.radians(p["longitude"] - lng) * math.cos(math.radians(lat))
        return 6371.0 * math.hypot(dlat, dlng)
    return min(((km(p), p) for p in rows), key=lambda t: t[0])


def main():
    rows = stations()
    live = [p for p in rows if p.get("status") == 1]
    print("%d stations, %d currently updating" % (len(rows), len(live)))
    if len(sys.argv) > 1:
        lat, lng = [float(x) for x in sys.argv[1].split(",")]
        d, p = nearest(lat, lng, rows)
        print("nearest: %s (%s) %.0f km  status=%s  last image %s %s"
              % (p["station"], p["code"], d, p.get("status"),
                 p.get("last_updated_date"), p.get("last_updated_time")))
        print("         %s" % (p.get("remarks") or "",))
        return
    for p in sorted(rows, key=lambda x: x["station"]):
        print("  %-4s %-28s %8.4f %9.4f  status=%s  %s %s"
              % (p["code"], p["station"], p["latitude"], p["longitude"],
                 p.get("status"), p.get("last_updated_date") or "-",
                 p.get("last_updated_time") or "-"))


if __name__ == "__main__":
    main()
