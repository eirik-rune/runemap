#!/usr/bin/env python3
"""Test: trickling upstream is aborted within the total budget."""
import sys, os, time, threading, http.server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_scene as R

BODY = b"x" * 1024

class TrickleHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        for byte in BODY:
            self.wfile.write(bytes([byte]))
            self.wfile.flush()
            time.sleep(0.15)   # 150 ms/byte => ~153s total
    def log_message(self, fmt, *a): pass

srv = http.server.HTTPServer(("127.0.0.1", 0), TrickleHandler)
thr = threading.Thread(target=srv.serve_forever, daemon=True)
thr.start()
port = srv.server_port
url = "http://127.0.0.1:%d/" % port

print("Trickle server on port %d, budget=5s, expect abort..." % port)
t0 = time.time()
try:
    R._get(url, timeout=30, budget=5)
    print("FAIL: should have raised RuntimeError")
    sys.exit(1)
except RuntimeError as e:
    elapsed = time.time() - t0
    print("PASS: trickle aborted in %.2fs (budget=5s): %s" % (elapsed, e))
    assert elapsed < 8.0, "took too long: %.2fs" % elapsed
srv.shutdown()
print("DONE")
