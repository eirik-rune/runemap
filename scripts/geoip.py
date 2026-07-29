"""ip -> (lat, lon) from the DB-IP City Lite ranges. No city names on purpose:
once we have a coordinate the existing geo.rlookup() labels it better, in both
languages. Read-only SQLite, one B-tree descent per lookup."""
import ipaddress, os, sqlite3, threading

DB = os.environ.get("GEOIP_DB", "/root/geoip/geoip.sqlite")
_L = threading.local()

def _conn():
    c = getattr(_L, "c", None)
    if c is None:
        c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, check_same_thread=False)
        _L.c = c
    return c

def locate(ip):
    """-> (lat, lon) or None. Private/reserved addresses return None."""
    try:
        a = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if a.is_private or a.is_loopback or a.is_reserved or a.is_link_local:
        return None
    if a.version == 4:
        q, k = "SELECT lat,lon,e FROM v4 WHERE s<=? ORDER BY s DESC LIMIT 1", int(a)
    else:
        q, k = "SELECT lat,lon,e FROM v6 WHERE s<=? ORDER BY s DESC LIMIT 1", a.packed
    r = _conn().execute(q, (k,)).fetchone()
    if not r:
        return None
    lat, lon, e = r
    if (int(a) if a.version == 4 else a.packed) > e:
        return None                      # gap between ranges
    return round(lat, 4), round(lon, 4)

if __name__ == "__main__":
    import sys, time
    for ip in (sys.argv[1:] or ["139.162.58.212", "8.8.8.8", "1.1.1.1",
                                "223.5.5.5", "192.168.1.1", "2606:4700:4700::1111"]):
        t = time.time(); r = locate(ip)
        print("  %-24s -> %-22s %.2fms" % (ip, r, (time.time() - t) * 1000))
