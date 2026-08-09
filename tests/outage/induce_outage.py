# -*- coding: utf-8 -*-
"""Induced-outage paired samples. The endpoint is the only thing scored.

The natural outage is 4.7% of the day, so waiting for one costs hours per
sample. iptables reproduces it exactly: an outage here IS the whole /24 going
silent, and a DROP rule on that /24 is that, with no packet leaving. Scoped by
cgroup so production (runemap.service, runemap@8789) never notices.

Both arms get the SAME rule in the same instant. An asymmetric block would
measure the rules, not the feature.

Every sample re-resolves first: DNS hands out a new pool about every minute, so
a rule written 60s ago may be pointing at nobody -- and both arms would sail
through, which reads as "no difference" while actually measuring nothing.

Scored: does the reader see a grid. PASS needs on-arm maps > 0 and off-arm
maps == 0 across >= 8 samples. Fixed here, before the data exists.
"""
import glob, os, subprocess, time

DEV, CTRL = "system.slice/runemap-dev.service", "system.slice/runemap-ctrl.service"
OUT = os.environ.get("OUTAGE_SAMPLES", "/root/tmp/arms/paired.txt")


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).returncode


def pool_now():
    import socket
    ips = sorted({a[4][0] for a in socket.getaddrinfo(
        "meteorology.caiyuncdn.com", 80, 0, socket.SOCK_STREAM)})
    return ".".join(ips[0].split(".")[:3]) + ".0/24", len(ips)


def rules(net, add):
    op = "-I" if add else "-D"
    for cg in (DEV, CTRL):
        sh("iptables", op, "OUTPUT", "-d", net, "-m", "cgroup", "--path", cg, "-j", "DROP")


def clear_all():
    """Remove every rule this script owns, and prove it.

    iptables -S prints the cgroup path QUOTED, and str.split() keeps the quotes,
    so feeding them back to -D matches nothing and every rule survives. The
    accumulation is not a harmless leak: the stale rules block exactly the pools
    the on-arm has REMEMBERED, so the arms converge on failure and the signal is
    ground away by the harness. shlex.split is what reads that line correctly."""
    import shlex
    for _ in range(40):
        out = subprocess.run(["iptables", "-S", "OUTPUT"],
                             capture_output=True, text=True).stdout
        mine = [ln for ln in out.splitlines()
                if "runemap-dev.service" in ln or "runemap-ctrl.service" in ln]
        if not mine:
            return True
        subprocess.run(["iptables"] + shlex.split(mine[0].replace("-A ", "-D ", 1)),
                       capture_output=True)
    return False


def ask(port, lng, lat):
    url = "http://127.0.0.1:%d/%.4f,%.4f/en" % (port, lng, lat)
    t0 = time.time()
    p = subprocess.run(["curl", "-s", "--max-time", "20", url], capture_output=True, text=True)
    el = time.time() - t0
    st, grid = "none", 0
    for ln in p.stdout.splitlines():
        if ln.startswith("radar:") and st == "none":
            st = (ln.split() + ["?"])[1]
        if len(ln) == 48:
            grid += 1
    return st, el, grid


CITIES = [(98.98, 18.79), (116.39, 39.93), (121.47, 31.23), (139.69, 35.69)]
f = open(OUT, "a", buffering=1)
try:
    for n in range(14):
        import random
        lng, lat = random.choice(CITIES)
        lng += random.uniform(-0.15, 0.15)
        lat += random.uniform(-0.15, 0.15)
        if not clear_all():
            f.write("# ABORT: could not clear rules; refusing to sample\n")
            break
        net, cnt = pool_now()
        rules(net, True)
        for d in ("/var/cache/runemap-dev", "/var/cache/runemap-ctrl"):
            for g in glob.glob(os.path.join(d, "*.png")):
                try:
                    os.unlink(g)
                except OSError:
                    pass
        order = [8790, 8791] if n % 2 else [8791, 8790]
        r = {}
        for port in order:
            r[port] = ask(port, lng, lat)
        # Re-resolve AFTER the asks. The rule names one /24, but DNS hands out a
        # new pool roughly every minute, so a sample can be labelled "outage"
        # while the arms were quietly talking to a pool no rule covers -- the
        # label would be false and the arms would agree for a reason that has
        # nothing to do with the feature. Run 1 ended FAIL on exactly one such
        # row (off-arm drew a map in 1.34s, which is what an unblocked pool
        # looks like). Dropping that row afterwards would have been widening the
        # gate to fit the data, so instead the check moves BEFORE scoring:
        # rotated samples are recorded and excluded by a rule written here, in
        # advance, for the run that follows.
        after, _ = pool_now()
        stable = "yes" if after == net else "no"
        f.write("%d blocked=%s after=%s stable=%s n=%d coord=%.3f,%.3f "
                "on=%s,%.2fs,g%d off=%s,%.2fs,g%d\n"
                % (int(time.time()), net, after, stable, cnt, lng, lat,
                   r[8790][0], r[8790][1], r[8790][2],
                   r[8791][0], r[8791][1], r[8791][2]))
        clear_all()
        time.sleep(20)
finally:
    clear_all()
    f.write("# rules cleared at exit\n")
