# -*- coding: utf-8 -*-
"""Negative control: with NO rules at all, does the OFF arm draw maps?

Every scored sample so far was taken while a DROP rule was in place. If
runemap-ctrl were simply broken -- empty env killing something else, a cache
directory it cannot write, a token it never got -- then "off 0/N" would say
nothing about my patch and the whole result collapses. That possibility has to
be closed by measurement, not by reading the config.

Gate, fixed here before the run: the off arm must draw a map in at least 3 of 3
coordinates with no rules present. Anything less and the experiment is void.
"""
import glob, os, subprocess, sys, time

COORDS = [(98.99, 18.81), (116.41, 39.94), (139.70, 35.70)]


def rules_present():
    out = subprocess.run(["iptables", "-S", "OUTPUT"], capture_output=True, text=True).stdout
    return sum(1 for l in out.splitlines() if "runemap" in l)


def ask(port, lng, lat):
    url = "http://127.0.0.1:%d/%.4f,%.4f/en" % (port, lng, lat)
    t0 = time.time()
    p = subprocess.run(["curl", "-s", "--max-time", "20", url], capture_output=True, text=True)
    g = sum(1 for ln in p.stdout.splitlines() if len(ln) == 48)
    st = "none"
    for ln in p.stdout.splitlines():
        if ln.startswith("radar:"):
            st = (ln.split() + ["?"])[1]
            break
    return st, time.time() - t0, g


n = rules_present()
print("  rules present = %d (must be 0)" % n)
if n:
    print("  VOID: rules still installed; this control cannot run")
    sys.exit(3)

off_maps = on_maps = 0
for lng, lat in COORDS:
    for d in ("/var/cache/runemap-dev", "/var/cache/runemap-ctrl"):
        for f in glob.glob(os.path.join(d, "*.png")):
            try:
                os.unlink(f)
            except OSError:
                pass
    a = ask(8790, lng, lat)
    b = ask(8791, lng, lat)
    on_maps += a[2] >= 24
    off_maps += b[2] >= 24
    print("  %.2f,%.2f  on=%s,%.2fs,g%d   off=%s,%.2fs,g%d"
          % (lng, lat, a[0], a[1], a[2], b[0], b[1], b[2]))

print("  ON %d/3   OFF %d/3" % (on_maps, len(COORDS)))
if off_maps >= 3:
    print("  CONTROL PASS: the off arm is healthy, so its zeros under outage mean something")
    sys.exit(0)
print("  CONTROL FAIL: the off arm cannot draw even without an outage -- experiment void")
sys.exit(1)
