#!/usr/bin/env python3
"""Regression: servers that echo "Connection: close" made conn.sock None."""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import net_budget

def serve_close(body, gap):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(8)
    def one(c):
        try:
            c.recv(65536)
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body))
            if gap:
                for i in range(len(body)):
                    c.sendall(body[i:i+1]); time.sleep(gap)
            else:
                c.sendall(body)
        except OSError:
            pass
        finally:
            try: c.close()
            except OSError: pass
    def run():
        while True:
            try: c, _ = srv.accept()
            except OSError: return
            threading.Thread(target=one, args=(c,), daemon=True).start()
    threading.Thread(target=run, daemon=True).start()
    return srv, srv.getsockname()[1]

fails = 0
srv, port = serve_close(b"x" * 5000, 0.0)
b = net_budget.get("http://127.0.0.1:%d/x" % port, budget=5.0)
ok = len(b) == 5000
print(("  PASS" if ok else "  FAIL"), "close-header healthy body: %d bytes" % len(b)); fails += 0 if ok else 1
srv.close()

srv, port = serve_close(b"x" * 10000, 0.2)
t0 = time.monotonic(); raised = False
try:
    net_budget.get("http://127.0.0.1:%d/x" % port, budget=2.0)
except net_budget.BudgetExceeded:
    raised = True
el = time.monotonic() - t0
ok = raised and el < 3.0
print(("  PASS" if ok else "  FAIL"), "close-header trickle bounded: %.2fs" % el); fails += 0 if ok else 1
srv.close()
sys.exit(1 if fails else 0)
