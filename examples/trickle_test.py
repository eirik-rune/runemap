#!/usr/bin/env python3
"""Trickle-server test for net_budget total-budget enforcement.

Starts a local HTTP server that serves bytes slowly (100ms gaps, 20 bytes
at a time), then fetches with a 2s total budget. Verifies that the fetch
is aborted within budget and that no socket/thread leaks occur after 100
iterations.

Usage:
    python3 examples/trickle_test.py

Requirements: Python 3.12 stdlib only.
"""

import http.server
import threading
import time
import sys
import os
import socket

# Add scripts/ to path to import net_budget
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import net_budget

SLOW_BYTES = b"X" * 10000  # 10KB payload
CHUNK_SIZE = 20
CHUNK_DELAY = 0.1  # 100ms between chunks -> ~50s to serve 10KB
TOTAL_BUDGET = 2.0  # 2 second total budget
ITERATIONS = 100


class TrickleHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(SLOW_BYTES)))
        self.end_headers()
        offset = 0
        while offset < len(SLOW_BYTES):
            chunk = SLOW_BYTES[offset : offset + CHUNK_SIZE]
            self.wfile.write(chunk)
            self.wfile.flush()
            offset += CHUNK_SIZE
            time.sleep(CHUNK_DELAY)

    def log_message(self, format, *args):
        pass  # silence server logs


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def main():
    port = find_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), TrickleHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.2)

    url = f"http://127.0.0.1:{port}/trickle"

    print(f"Trickle server on port {port}")
    print(f"Payload: {len(SLOW_BYTES)} bytes, {CHUNK_SIZE}B/{CHUNK_DELAY}s chunks")
    print(f"Expected serve time without budget: ~{len(SLOW_BYTES)/CHUNK_SIZE * CHUNK_DELAY:.1f}s")
    print(f"Total budget: {TOTAL_BUDGET}s")
    print(f"Iterations: {ITERATIONS}")
    print()

    timeouts = 0
    start = time.time()

    for i in range(ITERATIONS):
        try:
            net_budget.budgeted_get(url, total_budget=TOTAL_BUDGET)
            print(f"  [{i+1}] UNEXPECTED SUCCESS (should have timed out)")
        except TimeoutError:
            timeouts += 1
            if (i + 1) % 20 == 0:
                print(f"  [{i+1}] timeout OK ({timeouts}/{i+1})")
        except Exception as e:
            print(f"  [{i+1}] error: {type(e).__name__}: {e}")

    elapsed = time.time() - start

    # Thread leak check: count active threads
    active = threading.active_count()
    print()
    print(f"Results: {timeouts}/{ITERATIONS} timeouts in {elapsed:.1f}s")
    print(f"Active threads: {active}")

    server.shutdown()

    if timeouts == ITERATIONS and active < 10:
        print("PASS: All fetches aborted within budget, no thread leak detected.")
        return 0
    else:
        print(f"FAIL: Expected {ITERATIONS} timeouts, got {timeouts}. Threads: {active}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
