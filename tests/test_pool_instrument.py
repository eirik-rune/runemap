# -*- coding: utf-8 -*-
"""The remembered-pool race has been default-on since 8/9 and never said a word:
this file had zero log lines, so "a reader was served by a pool DNS had stopped
handing out" was structurally unobservable. Instrumentation that is never
summoned is the 8/8 failure again (the good version and its telemetry both sat
on a dead path, so the counter read 0 and looked fine).

So summon it. Today's DNS hands out one address in a /24 that refuses; memory
holds a live address in a DIFFERENT /24. If the memory is load-bearing the
connection still succeeds AND says so.

Negative control: when today's address answers, POOL-EXTRA-WIN must not appear --
otherwise a line that always prints would pass this test.

Run: /usr/bin/python3 tests/test_pool_instrument.py   (rc=0 pass)
"""
import io, os, socket, sys, threading

os.environ["RUNEMAP_POOL_MEMORY_HOSTS"] = "testhost"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import happy_eyeballs as HE

LIVE = ("127.0.0.1", 0)          # pool 127.0.0
DEAD = ("127.1.0.1", 9)          # pool 127.1.0 -- different /24, nothing listening


def _listener():
    s = socket.socket()
    s.bind(LIVE)
    s.listen(8)
    port = s.getsockname()[1]
    threading.Thread(target=lambda: [s.accept() for _ in range(64)],
                     daemon=True).start()
    return s, port


def _entry(ip, port):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))


def run(today, memory):
    """Run the patched create_connection with a forged DNS answer + memory."""
    HE._MEM.clear()
    if memory:
        HE._MEM["testhost"] = list(memory)
    real_gai = socket.getaddrinfo
    socket.getaddrinfo = lambda h, p, *a, **k: list(today)
    cap, old = io.StringIO(), sys.stderr
    sys.stderr = cap
    err = None
    try:
        c = HE._bounded(("testhost", 80), timeout=3.0)
        c.close()
        ok = True
    except Exception as e:                      # noqa: BLE001 - any failure is data
        ok, err = False, repr(e)[:80]
    finally:
        sys.stderr = old
        socket.getaddrinfo = real_gai
    return ok, cap.getvalue(), err


def main():
    HE.install()
    lst, port = _listener()
    fails = []

    # A: today's pool is dark, memory holds a live pool in another /24.
    ok, log, err = run([_entry(*DEAD)], [_entry("127.0.0.1", port)])
    dial, win = "POOL-EXTRA-DIAL" in log, "POOL-EXTRA-WIN" in log
    good = ok and dial and win
    print("  A rescue        connected=%-5s DIAL=%-5s WIN=%-5s %s"
          % (ok, dial, win, "ok" if good else "FAIL"))
    if not good:
        fails.append("A: connected=%s dial=%s win=%s err=%s" % (ok, dial, win, err))

    # B negative control: today's address answers, nothing remembered elsewhere.
    ok, log, err = run([_entry("127.0.0.1", port)], [])
    dial, win = "POOL-EXTRA-DIAL" in log, "POOL-EXTRA-WIN" in log
    good = ok and not dial and not win
    print("  B normal        connected=%-5s DIAL=%-5s WIN=%-5s %s"
          % (ok, dial, win, "ok" if good else "FAIL"))
    if not good:
        fails.append("B: connected=%s dial=%s win=%s err=%s" % (ok, dial, win, err))

    # C: memory exists but is in the SAME pool as today -> _extras filters it out,
    #    so no extra dial and no rescue claim. Guards against pool-bucketing rot.
    ok, log, err = run([_entry("127.0.0.1", port)], [_entry("127.0.0.1", port)])
    dial, win = "POOL-EXTRA-DIAL" in log, "POOL-EXTRA-WIN" in log
    good = ok and not dial and not win
    print("  C same-pool     connected=%-5s DIAL=%-5s WIN=%-5s %s"
          % (ok, dial, win, "ok" if good else "FAIL"))
    if not good:
        fails.append("C: connected=%s dial=%s win=%s err=%s" % (ok, dial, win, err))

    lst.close()
    if fails:
        print("POOL-INSTRUMENT FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("POOL-INSTRUMENT OK 1 rescue + 2 negative controls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
