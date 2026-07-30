import os
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from net_budget import TotalReadTimeout, urlopen_read_total


class _TrickleHandler(BaseHTTPRequestHandler):
    chunks = 5
    delay = 0.2

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(self.chunks))
        self.end_headers()
        for _ in range(self.chunks):
            try:
                self.wfile.write(b"x")
                self.wfile.flush()
            except BrokenPipeError:
                break
            time.sleep(self.delay)

    def log_message(self, *_args):
        pass


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _server(chunks=5, delay=0.2):
    handler = type("Handler", (_TrickleHandler,), {"chunks": chunks, "delay": delay})
    srv = _ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def test_total_budget_aborts_trickling_body():
    srv, url = _server(chunks=20, delay=0.05)
    start = time.monotonic()
    try:
        try:
            urlopen_read_total(url, timeout=0.2)
            raise AssertionError("expected TotalReadTimeout")
        except TotalReadTimeout:
            pass
        assert time.monotonic() - start < 0.7
    finally:
        srv.shutdown()
        srv.server_close()


def test_total_budget_allows_fast_body():
    srv, url = _server(chunks=3, delay=0.01)
    try:
        assert urlopen_read_total(url, timeout=1.0, chunk_size=1) == b"xxx"
    finally:
        srv.shutdown()
        srv.server_close()


def test_repeated_fast_fetches_do_not_leak_threads():
    srv, url = _server(chunks=1, delay=0.0)
    before = threading.active_count()
    try:
        for _ in range(100):
            assert urlopen_read_total(url, timeout=1.0, chunk_size=1) == b"x"
        # The client helper itself does not spawn threads; the daemon server may
        # briefly still be reaping request workers, so allow a tiny margin.
        assert threading.active_count() <= before + 3
    finally:
        srv.shutdown()
        srv.server_close()
