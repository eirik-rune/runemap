#!/usr/bin/env python3
"""DB-IP City Lite CSV -> compact SQLite of ip-range -> lat/lon ONLY.

We deliberately drop their city/region names: once we have a coordinate, the
existing geo.rlookup() gives a better label from GeoNames, in both languages.
So the table is 4 columns and the two capabilities compose instead of overlap.
IPv4 as integers, IPv6 as 16-byte blobs (both order-comparable in SQL)."""
import csv, gzip, ipaddress, sqlite3, os, sys, time

SRC = "/root/geoip/dbip-city.csv.gz"
DST = "/root/geoip/geoip.sqlite"
tmp = DST + ".part"
if os.path.exists(tmp):
    os.unlink(tmp)
db = sqlite3.connect(tmp)
db.executescript("""
PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
CREATE TABLE v4(s INTEGER PRIMARY KEY, e INTEGER, lat REAL, lon REAL);
CREATE TABLE v6(s BLOB PRIMARY KEY, e BLOB, lat REAL, lon REAL);
""")
n4 = n6 = skip = 0
t0 = time.time()
b4, b6 = [], []
with gzip.open(SRC, "rt", encoding="utf-8", errors="replace") as f:
    for row in csv.reader(f):
        if len(row) < 8:
            skip += 1; continue
        try:
            lat, lon = float(row[6]), float(row[7])
        except ValueError:
            skip += 1; continue
        if lat == 0.0 and lon == 0.0:
            skip += 1; continue          # ZZ / unallocated
        try:
            a = ipaddress.ip_address(row[0]); b = ipaddress.ip_address(row[1])
        except ValueError:
            skip += 1; continue
        if a.version == 4:
            b4.append((int(a), int(b), lat, lon)); n4 += 1
            if len(b4) >= 50000:
                db.executemany("INSERT OR REPLACE INTO v4 VALUES(?,?,?,?)", b4); b4.clear()
        else:
            b6.append((a.packed, b.packed, lat, lon)); n6 += 1
            if len(b6) >= 50000:
                db.executemany("INSERT OR REPLACE INTO v6 VALUES(?,?,?,?)", b6); b6.clear()
if b4: db.executemany("INSERT OR REPLACE INTO v4 VALUES(?,?,?,?)", b4)
if b6: db.executemany("INSERT OR REPLACE INTO v6 VALUES(?,?,?,?)", b6)
db.commit()
db.execute("VACUUM")
db.commit(); db.close()
os.replace(tmp, DST)
print("v4=%d v6=%d skipped=%d %.1fs size=%.1fMB" %
      (n4, n6, skip, time.time() - t0, os.path.getsize(DST) / 1e6))
