#!/usr/bin/env python3
"""Build the offline geocoding DB from GeoNames (CC-BY 4.0).

  python3 scripts/build_geo.py [outdir]     # default ~/geonames

Downloads cities1000 + admin code tables, builds geo.sqlite (~65MB):
170k settlements, 890k aliases (incl. CJK), 51k admin1/admin2 names.
Then: GEO_DB=<outdir>/geo.sqlite python3 scripts/serve.py"""
import csv, os, sqlite3, sys, time, unicodedata, urllib.request, zipfile

BASE = "https://download.geonames.org/export/dump/"
FILES = ["cities1000.zip", "admin1CodesASCII.txt", "admin2Codes.txt",
         # 2026-08-21, issue #200: without this table `san jose, costa rica`
         # answered California. The country was never stored as a NAME -- only
         # as the two-letter code -- so the qualifier matched nothing and the
         # lookup fell back to "most populous", which is US. `paris, france`
         # looked like it worked, but only because Paris FR is the most
         # populous candidate anyway: the word "france" did no work at all.
         "countryInfo.txt"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("-", " ").replace(".", "").split())


def main():
    out = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/geonames")
    os.makedirs(out, exist_ok=True)
    os.chdir(out)
    for f in FILES:
        if not os.path.exists(f):
            print("fetching", f)
            req = urllib.request.Request(BASE + f, headers={"User-Agent": "runemap/0.1"})
            with urllib.request.urlopen(req, timeout=300) as r, open(f + ".part", "wb") as w:
                w.write(r.read())
            os.replace(f + ".part", f)
    if not os.path.exists("cities1000.txt"):
        zipfile.ZipFile("cities1000.zip").extractall(".")

    t0 = time.time()
    db = "geo.sqlite"
    if os.path.exists(db):
        os.remove(db)
    c = sqlite3.connect(db)
    c.executescript("""
    PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
    CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL,
                       cc TEXT, a1 TEXT, a2 TEXT, pop INTEGER, tz TEXT);
    CREATE TABLE alias(key TEXT, pid INTEGER, pop INTEGER);
    CREATE TABLE admin(code TEXT PRIMARY KEY, name TEXT);
    CREATE TABLE country(cc TEXT PRIMARY KEY, name TEXT, iso3 TEXT);
    """)
    ctry = []
    for row in csv.reader(open("countryInfo.txt", encoding="utf-8"),
                          delimiter="\t", quoting=csv.QUOTE_NONE):
        # The file carries ~50 leading comment lines and one header line, both
        # starting with "#". A row that survives has ISO2, ISO3 and the name.
        if row and not row[0].startswith("#") and len(row) > 4 and row[4]:
            ctry.append((row[0], row[4], row[1]))
    if len(ctry) < 200:
        # 252 rows today. A parser that silently kept 3 of them would leave the
        # feature switched off while every other number in this script looked
        # normal -- the shape this whole file keeps getting caught by.
        raise SystemExit("countryInfo.txt yielded only %d countries; refusing "
                         "to build a DB whose country table is quietly empty"
                         % len(ctry))
    c.executemany("INSERT OR REPLACE INTO country VALUES(?,?,?)", ctry)
    adm = []
    for fn in ("admin1CodesASCII.txt", "admin2Codes.txt"):
        for row in csv.reader(open(fn, encoding="utf-8"), delimiter="\t"):
            if len(row) >= 2:
                adm.append((row[0], row[1]))
    c.executemany("INSERT OR REPLACE INTO admin VALUES(?,?)", adm)

    places, aliases, n = [], [], 0
    for r in csv.reader(open("cities1000.txt", encoding="utf-8"), delimiter="\t",
                        quoting=csv.QUOTE_NONE):
        if len(r) < 19:
            continue
        pid, pop = int(r[0]), int(r[14] or 0)
        places.append((pid, r[1], float(r[4]), float(r[5]), r[8], r[10], r[11], pop, r[17]))
        keys = {norm(r[1]), norm(r[2])}
        for a in r[3].split(","):          # ALL aliases: capping this drops CJK names
            a = a.strip()
            if 1 < len(a) < 40:
                keys.add(norm(a))
        aliases += [(k, pid, pop) for k in keys if k]
        n += 1
        if len(aliases) > 400000:
            c.executemany("INSERT INTO alias VALUES(?,?,?)", aliases); aliases = []
    c.executemany("INSERT INTO place VALUES(?,?,?,?,?,?,?,?,?)", places)
    c.executemany("INSERT INTO alias VALUES(?,?,?)", aliases)
    c.executescript("CREATE INDEX ix_alias ON alias(key, pop DESC); CREATE INDEX ix_pop ON place(pop DESC); CREATE INDEX ix_alias_sq ON alias(replace(key,' ',''), pop DESC);  -- 8/5: /newyork; +22MB, 1.0s")
    c.commit()
    print("places=%d aliases=%d admin=%d country=%d  %.1fs  %.0fMB  ->  %s/%s"
          % (n, c.execute("SELECT count(*) FROM alias").fetchone()[0], len(adm),
             len(ctry),
             time.time() - t0, os.path.getsize(db) / 1e6, out, db))


if __name__ == "__main__":
    main()
