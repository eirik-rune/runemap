#!/usr/bin/env python3
"""get_hedged: a stalled first connection must be beaten by the hedge."""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import net_budget

BODY = b"y" * 3000
state = {"n": 0}
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0)); srv.listen(8)
def one(c, idx):
    try:
        c.recv(65536)
        if idx == 1:
            time.sleep(6)          # first connection stalls (CDN tail)
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(BODY))
        c.sendall(BODY)
    except OSError:
        pass
    finally:
        try: c.close()
        except OSError: pass
def run():
    while True:
        try: c, _ = srv.accept()
        except OSError: return
        state["n"] += 1
        threading.Thread(target=one, args=(c, state["n"]), daemon=True).start()
threading.Thread(target=run, daemon=True).start()
url = "http://127.0.0.1:%d/x" % srv.getsockname()[1]

t0 = time.monotonic()
b = net_budget.get_hedged(url, budget=10.0, hedge_after=0.5)
el = time.monotonic() - t0
ok1 = len(b) == 3000 and el < 2.0
print(("  PASS" if ok1 else "  FAIL"), "hedge beats stalled first attempt: %.2fs, %d bytes, %d conns" % (el, len(b), state["n"]))

t0 = time.monotonic()
b = net_budget.get_hedged(url, budget=10.0, hedge_after=1.0)   # now idx>=3: fast path
el = time.monotonic() - t0
ok2 = len(b) == 3000 and state["n"] == 3
print(("  PASS" if ok2 else "  FAIL"), "fast path never hedges: %.2fs, conns total=%d (expect 3)" % (el, state["n"]))
srv.close()
sys.exit(0 if ok1 and ok2 else 1)
