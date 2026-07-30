#!/usr/bin/env python3
"""Quick validation of the total-budget wrapper: normal request + 100 iterations + budget enforcement."""
import sys, os, time, gc, threading, http.server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as R

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b'{"status":"ok"}')))
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def log_message(self, fmt, *a): pass

srv = http.server.HTTPServer(("127.0.0.1", 0), H)
thr = threading.Thread(target=srv.serve_forever, daemon=True)
thr.start()
port = srv.server_port
url = "http://127.0.0.1:%d/" % port

ok = 0

# 1) normal fast request
t0 = time.time()
data = R._get(url, timeout=5, budget=5)
assert data == b'{"status":"ok"}'
print("PASS: normal fetch %.3fs" % (time.time() - t0))
ok += 1

# 2) 100 iterations with thread count check
tb = threading.active_count()
for i in range(100):
    R._get(url, timeout=5, budget=5)
gc.collect()
ta = threading.active_count()
delta = ta - tb
if delta <= 10:
    print("PASS: 100 iters, threads %d -> %d (delta=%d)" % (tb, ta, delta))
    ok += 1
else:
    print("WARN: 100 iters, thread count grew %d -> %d (delta=%d)" % (tb, ta, delta))

# 3) custom budget enforcement — 1s budget should complete since the
#    server is local and fast, but verify the mechanism is wired up
t0 = time.time()
data = R._get(url, timeout=30, budget=1)
elapsed = time.time() - t0
assert elapsed < 3.0, "took %.2fs with budget=1s" % elapsed
print("PASS: budget=1s completed in %.3fs" % elapsed)
ok += 1

srv.shutdown()
print("\n%d/3 passed" % ok)
sys.exit(0 if ok == 3 else 1)
