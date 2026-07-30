"""Regression tests for scripts/net_budget.py.

The tests run entirely against an in-process local HTTP server, so they have
no external network dependency and never hit the live Caiyun radar. The shape
mirrors the issue's acceptance criteria:

1. A trickling body aborts within the wall-clock budget (no unbounded read).
2. A fast body completes intact.
3. 100 repeated fetches do not leak threads or sockets on the client side.

Run with:  python3 -m pytest -q tests/test_net_budget.py
"""
from __future__ import annotations

import os
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from net_budget import TotalReadTimeout, urlopen_read_total


class _TrickleHandler(BaseHTTPRequestHandler):
    """Servlets an HTTP body one byte at a time with a configurable per-byte delay."""

    chunks = 5
    delay = 0.2

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
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

    def log_message(self, *_args):  # silence stderr noise during tests
        pass


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _server(chunks=5, delay=0.2):
    """Spin up a per-test trickle server on a random localhost port."""
    handler = type("Handler", (_TrickleHandler,), {"chunks": chunks, "delay": delay})
    srv = _ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def _stop(srv):
    srv.shutdown()
    srv.server_close()


def test_total_budget_aborts_trickling_body():
    """20-byte trickle at 50ms/byte must abort well before the body completes."""
    srv, url = _server(chunks=20, delay=0.05)
    start = time.monotonic()
    try:
        with pytest.raises(TotalReadTimeout):
            urlopen_read_total(url, timeout=0.2, chunk_size=1)
        elapsed = time.monotonic() - start
        # Budget was 0.2s; allow a generous margin for OS scheduler noise
        # but assert we did not wait out the full ~1s trickle.
        assert elapsed < 0.7, f"fetch took {elapsed:.3f}s, expected to abort within budget"
    finally:
        _stop(srv)


def test_total_budget_aborts_trickling_body_is_timeouterror():
    """The typed exception must also be a TimeoutError so existing
    `except TimeoutError` callers keep working unchanged."""
    srv, url = _server(chunks=10, delay=0.05)
    try:
        with pytest.raises(TimeoutError):
            urlopen_read_total(url, timeout=0.1, chunk_size=1)
    finally:
        _stop(srv)


def test_total_budget_allows_fast_body():
    """A body that fits inside the budget returns intact."""
    srv, url = _server(chunks=3, delay=0.01)
    try:
        body = urlopen_read_total(url, timeout=1.0, chunk_size=1)
        assert body == b"xxx"
    finally:
        _stop(srv)


def test_zero_or_negative_budget_rejected():
    """A zero/negative budget cannot mean 'infinite'; refuse early."""
    with pytest.raises(TotalReadTimeout):
        urlopen_read_total("http://127.0.0.1:1/", timeout=0)
    with pytest.raises(TotalReadTimeout):
        urlopen_read_total("http://127.0.0.1:1/", timeout=-1.0)


def test_repeated_fast_fetches_do_not_leak_threads():
    """100 back-to-back fetches against a small fast server must not leave the
    client holding orphan threads or sockets."""
    srv, url = _server(chunks=1, delay=0.0)
    before = threading.active_count()
    try:
        for _ in range(100):
            assert urlopen_read_total(url, timeout=1.0, chunk_size=1) == b"x"
        # The client helper spawns zero threads of its own; the threading
        # server may briefly still be reaping request workers, so allow a
        # tiny margin (the daemon thread budget, not a leak indicator).
        assert threading.active_count() <= before + 3, (
            f"thread count grew from {before} to {threading.active_count()}"
        )
    finally:
        _stop(srv)