"""Mirror Brazilian radar frames onto this box, because this box cannot reach them.

Measured 8/13: `api-redemet` and `estatico-redemet` both time out from the
production machine while returning 200 from our Tokyo box, with `www.gov.br`
answering 301 here -- so it is that path, not Brazil, and not a dead host.

The shape is a PULL, not a push: production already holds the ssh key to Tokyo,
so nothing new is trusted and nothing new listens. Tokyo runs the fetch, streams
back a tar, and this writes it into the radar cache. The reader path never
touches Brazil, which also means it never waits on it -- the frames are on disk
before anyone asks.

What it deliberately does not do:

 · It does not decide whether a sky has radar. It mirrors what REDEMET listed
   and nothing more; an absent radar here means "we did not mirror one", which
   is a fact about us.
 · It does not write into the live directory until the whole tar is unpacked --
   a half-mirrored frame set must never be readable.
 · It reports what it did NOT get. A silent mirror and a working mirror look
   identical from the reader's side, which is the failure this project keeps
   meeting under different names.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

TOKYO = os.environ.get("REDEMET_TOKYO", "ubuntu@3.114.3.152")
KEY = os.environ.get("REDEMET_TOKYO_KEY",
                     os.path.expanduser("~/.ssh/id_ed25519_luoshu"))
DEST = os.environ.get("REDEMET_DIR",
                      os.path.join(os.environ.get("RUNEMAP_CACHE", "/var/cache/runemap"),
                                   "redemet"))
REMOTE = "/home/ubuntu/redemet_fetch.py"

# The remote half. Kept here rather than on Tokyo so that one file is the whole
# story: what runs there is versioned in this repo, not in somebody's home dir.
FETCH = r'''
import json, os, re, sys, time, urllib.request
K = open("/home/ubuntu/.redemet_key").read().strip()
OUT = "/tmp/redemet_out"
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    os.unlink(os.path.join(OUT, f))
D = time.strftime("%Y%m%d%H", time.gmtime())
req = urllib.request.Request(
    "https://api-redemet.decea.gov.br/produtos/radar/maxcappi?data=%s" % D,
    headers={"X-Api-Key": K})
d = json.loads(urllib.request.urlopen(req, timeout=30).read())
radars = d["data"]["radar"][0]
index = []
for r in radars:
    p = r.get("path")
    if not p:
        continue
    name = re.sub(r"[^a-z0-9]", "", (r.get("localidade") or "").lower()) or str(r.get("id"))
    try:
        b = urllib.request.urlopen(p, timeout=30).read()
    except Exception as e:
        sys.stderr.write("MIRROR-MISS %s %r\n" % (name, e))
        continue
    open(os.path.join(OUT, name + ".png"), "wb").write(b)
    index.append({"name": name, "nome": r.get("nome"), "png": name + ".png",
                  "data": r.get("data"), "raio": r.get("raio"),
                  "bbox": [float(r["lat_min"]), float(r["lon_min"]),
                           float(r["lat_max"]), float(r["lon_max"])]})
json.dump({"at": int(time.time()), "product": "maxcappi",
           "listed": len(radars), "mirrored": len(index), "radars": index},
          open(os.path.join(OUT, "index.json"), "w"))
sys.stderr.write("MIRROR listed=%d mirrored=%d\n" % (len(radars), len(index)))
os.system("cd %s && tar cf - ." % OUT)
'''


def _age_quantiles(idx):
    """min/median/p90/max frame age in minutes, or a word saying why not.

    "no ages" and "0 ages" must not print the same thing: the first means the
    index carried no parseable times, the second would mean every radar was
    current, and only one of those is good news.
    """
    now = time.time()
    ages = []
    for r in idx.get("radars", []):
        try:
            ts = time.mktime(time.strptime(r["data"], "%Y-%m-%d %H:%M:%S")) - time.timezone
        except Exception:
            continue
        ages.append((now - ts) / 60.0)
    if not ages:
        return "unparseable"
    ages.sort()
    return "%.0f/%.0f/%.0f/%.0f" % (ages[0], ages[len(ages) // 2],
                                    ages[int(len(ages) * 0.9)], ages[-1])


def main():
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tar = os.path.join(tmp, "m.tar")
        with open(tar, "wb") as fh:
            p = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-i", KEY, TOKYO,
                 "python3 - <<'PYEOF'\n" + FETCH + "\nPYEOF"],
                stdout=fh, stderr=subprocess.PIPE, timeout=180)
        err = p.stderr.decode()[-500:]
        if p.returncode != 0 or os.path.getsize(tar) == 0:
            sys.exit("mirror failed rc=%d bytes=%d: %s"
                     % (p.returncode, os.path.getsize(tar), err))
        stage = os.path.join(tmp, "stage")
        os.makedirs(stage)
        subprocess.run(["tar", "xf", tar, "-C", stage], check=True)
        idx = json.load(open(os.path.join(stage, "index.json")))
        os.makedirs(DEST, exist_ok=True)
        for f in os.listdir(stage):          # index.json last: it is the switch
            if f != "index.json":
                os.replace(os.path.join(stage, f), os.path.join(DEST, f))
        os.replace(os.path.join(stage, "index.json"), os.path.join(DEST, "index.json"))
    # listed vs mirrored, always both: "17 radars" alone cannot tell you whether
    # 12 were missing or there were only 17.
    #
    # The ages go in the same line because the frame ceiling in
    # scripts/radar_redemet.py was derived from ONE pull (13.4 / 19.6 / 23.2 min,
    # min/median/max) and set to 45 to clear it. Six hours later a single pull
    # showed 13.3 / 23.9 / 52.7 -- the median barely moved and the maximum more
    # than doubled, so the constant was set from a sample that could not show
    # its own tail. Recording the quantiles every ten minutes is what lets the
    # next version of that number come from a distribution instead of a
    # snapshot. Nothing reads this yet, and that is stated rather than implied.
    print("REDEMET-MIRROR listed=%d mirrored=%d dest=%s %.1fs ages=%s | %s"
          % (idx["listed"], idx["mirrored"], DEST, time.time() - t0,
             _age_quantiles(idx),
             err.strip().splitlines()[-1] if err.strip() else "-"))


if __name__ == "__main__":
    main()
