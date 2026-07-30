"""Network helpers with a total wall-clock budget.

urllib's `timeout` parameter is a *per-socket-operation* idle cap, not a total
budget for the whole request. A peer that trickles one byte every few seconds
holds the fetch open forever, because every individual recv completes inside
its idle window. The scene path needs a single deadline that covers dial,
time-to-first-byte, and the full body read.

This module gives the caller one such wrapper, `urlopen_read_total`, plus a
typed exception `TotalReadTimeout` so the existing scene caller can convert a
budget breach to a bounded fallback without weakening the cache layer in
`scene_at.py`.

Design notes
------------
- The budget is enforced at three checkpoints: (1) before `urlopen` (dial +
  TTFB), (2) before every body read (chunk loop), (3) inside the loop when a
  per-recv timeout fires. Each checkpoint shrinks the socket timeout to the
  remaining wall-clock budget so a slow/trickling peer cannot extend the
  request indefinitely.
- The deadline is `time.monotonic()`, which does not jump with NTP or wall
  clock changes. Pass a wall-clock budget in seconds; the helper converts.
- No new dependencies. Stdlib only (Python 3.12). No global state mutation
  during a fetch (no counters, no module-level lock) so the helper is safe to
  use concurrently from many threads.
- The chunk loop yields empty bytes only at EOF; an aborted body surfaces as
  `TotalReadTimeout`. Callers that need partial data should treat the timeout
  as a hard stop, not a partial-success signal.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request


class TotalReadTimeout(TimeoutError):
    """Raised when an upstream response exceeds its total wall-clock budget.

    Subclasses `TimeoutError` (PEP 657 alias for the built-in `TimeoutError`)
    so existing handlers that catch `TimeoutError` continue to work; the typed
    subclass lets the scene caller convert the breach to a stale-cache
    fallback without losing the budget semantics.
    """


class _DeadlineExceeded(TotalReadTimeout):
    """Internal: budget ran out before the next I/O step could begin."""


def _remaining(deadline: float) -> float:
    """Return the remaining wall-clock budget in seconds, raising if it is gone."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _DeadlineExceeded("upstream fetch exceeded total wall-clock budget")
    return remaining


def _shrink_socket_timeout(response, remaining: float) -> None:
    """Shrink the underlying socket timeout to the remaining budget.

    urllib's HTTPResponse hides its socket behind `fp.raw._sock`. We touch it
    directly so a peer that pauses longer than the remaining budget trips a
    socket timeout inside `read()`, which we then convert to TotalReadTimeout.
    A socket that has no `_sock` (e.g. an already-closed response, or a
    non-HTTP handler) is silently ignored: the deadline check in the loop body
    is still authoritative.
    """
    try:
        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None)
        sock = getattr(raw, "_sock", None)
    except Exception:
        sock = None
    if sock is None:
        return
    try:
        sock.settimeout(remaining)
    except (OSError, ValueError):
        # Closed socket, non-blocking socket, or already-closed file:
        # the deadline check in the caller is still authoritative, so fall
        # through and let that decide.
        pass


def urlopen_read_total(url, timeout=15.0, *, headers=None, chunk_size=64 * 1024):
    """Fetch *url* and return the full body within one total wall-clock budget.

    The budget covers (1) urllib's open/dial, (2) time-to-first-byte, and
    (3) the full body read -- regardless of how the peer trickles bytes. On
    breach, raises `TotalReadTimeout` (a `TimeoutError` subclass).

    Args:
        url: absolute URL.
        timeout: total wall-clock budget in seconds (float, > 0).
        headers: optional dict of HTTP headers (User-Agent defaults to
            "runemap/0.1" if absent).
        chunk_size: body read granularity in bytes. Smaller values tighten the
            deadline enforcement at the cost of more syscalls; the default is
            fine for radar PNGs (~13 KB) and weather JSON (~50 KB).

    Returns:
        bytes: the complete response body.
    """
    budget = float(timeout)
    if budget <= 0:
        raise _DeadlineExceeded("total wall-clock budget must be > 0")

    deadline = time.monotonic() + budget
    hdrs = dict(headers) if headers else {}
    hdrs.setdefault("User-Agent", "runemap/0.1")
    req = urllib.request.Request(url, headers=hdrs)

    try:
        response = urllib.request.urlopen(req, timeout=_remaining(deadline))
    except _DeadlineExceeded:
        raise
    except TimeoutError as exc:
        raise TotalReadTimeout("upstream fetch exceeded total wall-clock budget") from exc
    except urllib.error.URLError as exc:
        # urllib wraps the underlying socket timeout in URLError on some
        # platforms. Promote it to the typed exception so callers see one
        # failure mode.
        if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
            raise TotalReadTimeout("upstream fetch exceeded total wall-clock budget") from exc
        raise

    chunks = []
    try:
        while True:
            remaining = _remaining(deadline)
            _shrink_socket_timeout(response, remaining)
            try:
                chunk = response.read(chunk_size)
            except (TimeoutError, socket.timeout) as exc:
                raise TotalReadTimeout(
                    "upstream fetch exceeded total wall-clock budget"
                ) from exc
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        try:
            response.close()
        except Exception:
            pass


__all__ = ["TotalReadTimeout", "urlopen_read_total"]