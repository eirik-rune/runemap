#!/usr/bin/env python3
"""Acceptance tests for the total-read-budget fix. Stdlib only, no network.

Run:  python3 tests/test_net_budget.py
"""
import os
import resource
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import net_budget  # noqa: E402


class TrickleServer:
    """Serves a body one byte at a time, `gap` seconds apart, forever.

    This is the shape that defeats a per-recv timeout: every individual recv
    returns well inside the socket timeout, so the old code never trips it.
    """

    def __init__(self, gap=0.2, headers_delay=0.0, total=10_000):
        self.gap, self.headers_delay, self.total = gap, headers_delay, total
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(64)
        self.port = self.srv.getsockname()[1]
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d/trickle" % self.port

    def _serve(self):
        while not self.stop.is_set():
            try:
                self.srv.settimeout(0.3)
                c, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        try:
            c.recv(65536)
            time.sleep(self.headers_delay)
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % self.total)
            for _ in range(self.total):
                if self.stop.is_set():
                    break
                c.sendall(b"x")
                time.sleep(self.gap)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        try:
            self.srv.close()
        except OSError:
            pass


def fds():
    return len(os.listdir("/proc/self/fd"))


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (" — " + detail if detail else ""))
    if not cond:
        check.failed = True
check.failed = False


def main():
    print("1. body trickle must not outlive the budget")
    s = TrickleServer(gap=0.2, total=10_000)   # would take 2000s to finish
    try:
        t0 = time.monotonic()
        try:
            net_budget.get(s.url, budget=2.0)
            el, raised = time.monotonic() - t0, False
        except net_budget.BudgetExceeded as e:
            el, raised = time.monotonic() - t0, True
            got = e.got
        check("aborts rather than hanging", raised)
        check("within budget + slack", el < 3.0, "%.2fs elapsed, budget 2.0s" % el)
        check("read real bytes first (it is a trickle, not a stall)", raised and got > 0,
              "%d bytes" % (got if raised else -1))

        print("2. a stalled peer that never sends headers is bounded too")
        s2 = TrickleServer(gap=0.05, headers_delay=30.0)
        t0 = time.monotonic()
        try:
            net_budget.get(s2.url, budget=1.5)
            raised = False
        except net_budget.BudgetExceeded:
            raised = True
        el = time.monotonic() - t0
        check("TTFB bounded", raised and el < 2.5, "%.2fs elapsed, budget 1.5s" % el)
        s2.close()

        print("3. BudgetExceeded is a TimeoutError (existing except-clauses keep working)")
        check("isinstance TimeoutError", issubclass(net_budget.BudgetExceeded, TimeoutError))
        check("isinstance OSError", issubclass(net_budget.BudgetExceeded, OSError))

        print("4. no socket/fd leak over 100 abandoned fetches")
        net_budget.get.__doc__  # touch
        base = fds()
        for _ in range(100):
            try:
                net_budget.get(s.url, budget=0.15)
            except (net_budget.BudgetExceeded, OSError):
                pass
        time.sleep(0.3)
        grown = fds() - base
        check("fd count stable", grown <= 2, "grew by %d" % grown)
        check("thread count stable", threading.active_count() < 20,
              "%d threads" % threading.active_count())
    finally:
        s.close()

    print("5. a healthy server still returns the whole body")
    s3 = TrickleServer(gap=0.0, total=5000)
    try:
        b = net_budget.get(s3.url, budget=5.0)
        check("full body", len(b) == 5000, "%d bytes" % len(b))
    finally:
        s3.close()

    print()
    print("FAILED" if check.failed else "ALL PASS")
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
