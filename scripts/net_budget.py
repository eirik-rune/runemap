#!/usr/bin/env python3
"""Total wall-clock budget for upstream HTTP fetches.

Python 3.12 stdlib only. No new dependencies.

Problem: `urllib.request.urlopen(timeout=N)` sets a per-recv *gap* cap,
not a total wall-clock budget. An upstream that trickles one byte every
few seconds can hold a connection open indefinitely.

Solution: `budgeted_get()` runs the actual fetch in a daemon thread and
joins the thread with a total wall-clock deadline. If the deadline fires
before the read completes, a `TimeoutError` is raised. The caller's
caching layer (scene_at.py) already catches exceptions and serves stale
entries, so a budget exhaustion simply falls through to the stale path.

The per-recv gap cap is set to the smaller of (total_budget / 4, 5s) so
that a genuinely dead upstream is detected quickly inside the budget window.
"""

import threading
import urllib.request
import os

# Default total budget in seconds. Override with RUNEMAP_FETCH_BUDGET env var.
_DEFAULT_BUDGET = float(os.environ.get("RUNEMAP_FETCH_BUDGET", "20"))


def budgeted_get(url, total_budget=None, headers=None):
    """Fetch *url* with a total wall-clock budget.

    Args:
        url: The URL to fetch.
        total_budget: Total wall-clock seconds for dial + TTFB + full body.
                      Defaults to RUNEMAP_FETCH_BUDGET env var (20s).
        headers: Optional dict of HTTP headers.

    Returns:
        Response body as bytes.

    Raises:
        TimeoutError: If the total budget is exhausted before the full body
                      is received.
        urllib.error.URLError: On connection/DNS failures.
    """
    budget = total_budget if total_budget is not None else _DEFAULT_BUDGET
    per_recv = min(budget / 4.0, 5.0)

    result = [None, None]  # [data_bytes, exception]

    def _fetch():
        try:
            hdrs = dict(headers) if headers else {"User-Agent": "runemap/0.1"}
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=per_recv) as r:
                result[0] = r.read()
        except Exception as e:
            result[1] = e

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(budget)

    if t.is_alive():
        # The thread is still blocked on a trickling socket read.
        # We cannot forcibly kill a Python thread, but we can signal
        # the timeout. The daemon thread will eventually terminate
        # when the socket's per-recv gap cap fires or the upstream
        # closes. The cache layer above us handles this correctly:
        # it catches the exception and serves stale data.
        raise TimeoutError(
            f"Total fetch budget exhausted ({budget:.1f}s) for {url[:80]}"
        )

    if result[1] is not None:
        raise result[1]

    return result[0]
