#!/usr/bin/env python3
"""Total wall-clock budget for upstream fetches. Python 3.12 stdlib only.

The defect this closes
----------------------
`socket.settimeout(t)` / `urlopen(..., timeout=t)` caps the gap between recv()
calls, not the total time of a fetch. An upstream that trickles one byte every
t-epsilon seconds never trips the timeout and holds the request open forever.
Measured here before mitigation: read=13.59s on radar CDN fetches.

The fix
-------
One deadline for the whole fetch, re-derived before every blocking step:

    dial  -> settimeout(remaining)
    TTFB  -> settimeout(remaining) before getresponse()
    body  -> settimeout(remaining) before every read() chunk

Because each recv is given only the time that is actually left, a trickling
peer cannot outlast the budget: the last recv gets ~0s and raises. Total time
is bounded by `budget` plus one chunk of slack, with no threads and no timer
callbacks, so nothing leaks when a fetch is abandoned.

Redirects are followed inside the same budget -- three hops of 5s each is not
a 5s budget.

    get("https://example.com/x", budget=8.0)  -> bytes
"""
import contextlib
import http.client
import socket
import ssl
import threading
import time
import urllib.parse

__all__ = ["get", "BudgetExceeded", "request_budget", "current_deadline", "adopt"]

DEFAULT_BUDGET = 15.0
CHUNK = 65536
MAX_REDIRECTS = 4
MAX_BYTES = 32 * 1024 * 1024
MIN_BUDGET = 0.05      # below this there is no point dialling; see get()


class BudgetExceeded(TimeoutError):
    """The fetch ran out of total wall-clock time.

    Subclasses TimeoutError (and therefore OSError) so existing callers that
    already catch socket timeouts -- e.g. scene_at._cached_get falling back to
    a stale-but-good cache entry -- keep working unchanged.
    """

    def __init__(self, url, budget, phase, got=0):
        self.url, self.budget, self.phase, self.got = url, budget, phase, got
        super().__init__(
            "budget %.2fs exhausted during %s after %d bytes: %s"
            % (budget, phase, got, url)
        )


# --- request-scoped budget -------------------------------------------------
#
# A per-fetch budget cannot bound a request: a cold scene fetches weather,
# then the radar frame list, then the PNGs, each entitled to its own budget.
# Every one can finish just inside its own limit while the request as a whole
# runs 60s -- which is how a 20s probe records a timeout against a server that
# is still working. The request deadline is the ceiling all of them share.
#
# ThreadingHTTPServer gives each request its own thread, so this is thread
# local. Worker threads (echo_motion's pool) do NOT inherit it -- they must
# adopt() the deadline explicitly, or they will each start a fresh budget and
# quietly reopen the hole this closes.

_local = threading.local()


def current_deadline():
    return getattr(_local, "deadline", None)


@contextlib.contextmanager
def request_budget(seconds):
    """Cap one whole request. Nested use keeps the earlier (tighter) deadline."""
    prev = current_deadline()
    if prev is None:
        _local.deadline = _Deadline(seconds)
    try:
        yield current_deadline()
    finally:
        _local.deadline = prev


@contextlib.contextmanager
def adopt(deadline):
    """Run a worker thread under a deadline captured in the parent thread."""
    prev = current_deadline()
    _local.deadline = deadline
    try:
        yield
    finally:
        _local.deadline = prev


class _Deadline:
    def __init__(self, budget):
        self.budget = float(budget)
        self.end = time.monotonic() + self.budget

    def left(self, floor=0.0):
        return max(floor, self.end - time.monotonic())

    def expired(self):
        return time.monotonic() >= self.end


def _connect(url, dl, headers):
    """Open a connection and send the request, all inside the deadline."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("unsupported scheme: %r" % u.scheme)
    if dl.expired():
        raise BudgetExceeded(url, dl.budget, "dial")

    port = u.port or (443 if u.scheme == "https" else 80)
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(
            u.hostname, port, timeout=max(dl.left(), MIN_BUDGET),
            context=ssl.create_default_context()
        )
    else:
        conn = http.client.HTTPConnection(u.hostname, port,
                                          timeout=max(dl.left(), MIN_BUDGET))

    try:
        conn.connect()                       # dial
        conn.sock.settimeout(max(dl.left(), MIN_BUDGET))   # send + TTFB
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        conn.request("GET", path, headers=headers)
        # Capture the socket BEFORE getresponse(). When the response says
        # Connection: close, http.client hands the socket to the response and
        # sets conn.sock = None ("this effectively passes the connection to the
        # response"). Reading conn.sock afterwards is an AttributeError against
        # every upstream that closes -- which is most of them.
        sock = conn.sock
        resp = conn.getresponse()
    except (socket.timeout, TimeoutError):
        conn.close()
        raise BudgetExceeded(url, dl.budget, "dial/ttfb")
    except Exception:
        conn.close()
        raise
    return conn, resp, sock


def _set_timeout(sock, resp, t):
    """Apply the remaining budget to whichever socket object is still live.

    After a Connection: close response the socket has been handed to `resp`;
    the captured object still works because socket.makefile() holds an io-ref
    that keeps the fd open. Fall back to the response's own raw socket, and
    tolerate a socket that has already gone away.
    """
    t = max(t, MIN_BUDGET)      # never 0 -- that is non-blocking, not "expired"
    for s in (sock, getattr(getattr(resp, "fp", None), "raw", None)):
        target = getattr(s, "_sock", s)
        if target is None:
            continue
        try:
            target.settimeout(t)
            return True
        except (OSError, AttributeError):
            continue
    return False


def get(url, budget=DEFAULT_BUDGET, headers=None, _redirects=MAX_REDIRECTS):
    """Fetch `url`, returning the body as bytes, in at most `budget` seconds total.

    Raises BudgetExceeded (a TimeoutError) if the budget runs out at any phase,
    and http.client.HTTPException / OSError for the usual transport failures.
    """
    if isinstance(budget, _Deadline):
        dl = budget                       # redirect hops share the caller's clock
    else:
        req = current_deadline()
        if req is None:
            dl = _Deadline(budget)
        else:
            # never more than the request has left, never more than this fetch
            # was allowed: whichever runs out first ends the fetch
            left = req.left()
            # A budget of 0 must not reach socket.settimeout(): 0 means
            # NON-BLOCKING there, not "give up", and the failure mode changes
            # shape entirely. Anything at or under the floor is simply out of
            # time.
            if req.expired() or left <= MIN_BUDGET:
                raise BudgetExceeded(url, req.budget, "request budget", 0)
            dl = _Deadline(min(float(budget), left))
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "runemap/0.1")
    headers.setdefault("Connection", "close")

    conn, resp, sock = _connect(url, dl, headers)
    try:
        if resp.status in (301, 302, 303, 307, 308) and _redirects > 0:
            loc = resp.getheader("Location")
            if not loc:
                raise http.client.HTTPException("redirect without Location: %s" % url)
            resp.read()  # drain what is there; body of a redirect is tiny
            nxt = urllib.parse.urljoin(url, loc)
            conn.close()
            # same deadline object: the hops share one budget, they do not reset it
            return get(nxt, dl, headers, _redirects - 1)

        if resp.status != 200:
            raise http.client.HTTPException("HTTP %d %s: %s" % (resp.status, resp.reason, url))

        buf = bytearray()
        while True:
            if dl.expired():
                raise BudgetExceeded(url, dl.budget, "body", len(buf))
            # the shrinking timeout is the whole trick: a trickling peer gets
            # less time on every pass and cannot outlast the deadline
            _set_timeout(sock, resp, dl.left())
            try:
                # read1, NOT read: read(n) is buffered and loops internally until
                # it has n bytes, so a peer dripping one byte per recv never
                # trips the socket timeout and never gives control back -- the
                # deadline would only be consulted after the fetch already hung.
                # read1 returns after a single underlying recv, so the loop below
                # gets to check the clock on every drip.
                chunk = resp.read1(CHUNK)
            except (socket.timeout, TimeoutError):
                raise BudgetExceeded(url, dl.budget, "body", len(buf))
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise http.client.HTTPException("response over %d bytes: %s" % (MAX_BYTES, url))
        return bytes(buf)
    finally:
        # close the response before the connection: an abandoned fetch must not
        # leave the socket to the garbage collector
        try:
            resp.close()
        except Exception:
            pass
        conn.close()
