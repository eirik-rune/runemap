"""Network helpers with a total wall-clock budget.

urllib's timeout is a per-socket-operation idle timeout. A peer can keep a
request alive forever by trickling bytes before each idle timeout expires. The
scene path needs a total deadline for dial + first byte + body read instead.
"""
from __future__ import annotations

import socket
import time
import urllib.request


class TotalReadTimeout(TimeoutError):
    """Raised when an upstream response exceeds its total wall-clock budget."""


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TotalReadTimeout("upstream fetch exceeded total wall-clock budget")
    return remaining


def urlopen_read_total(url, timeout=15, *, headers=None, chunk_size=64 * 1024):
    """Fetch *url* and return bytes within one total wall-clock budget.

    The budget covers urllib's open/dial, time-to-first-byte, and every body
    read. Before each read we shrink the socket timeout to the remaining budget
    so a slow/trickling peer cannot extend the request indefinitely.
    """
    deadline = time.monotonic() + float(timeout)
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "runemap/0.1"})
    with urllib.request.urlopen(req, timeout=_remaining(deadline)) as response:
        chunks = []
        while True:
            remaining = _remaining(deadline)
            raw = getattr(getattr(response, "fp", None), "raw", None)
            sock = getattr(raw, "_sock", None)
            if sock is not None:
                try:
                    sock.settimeout(remaining)
                except OSError:
                    pass
            try:
                read_chunk = getattr(response, "read1", response.read)
                chunk = read_chunk(chunk_size)
            except (TimeoutError, socket.timeout) as exc:
                raise TotalReadTimeout("upstream fetch exceeded total wall-clock budget") from exc
            if time.monotonic() > deadline:
                raise TotalReadTimeout("upstream fetch exceeded total wall-clock budget")
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
