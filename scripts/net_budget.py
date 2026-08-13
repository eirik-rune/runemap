#!/usr/bin/env python3
"""Network request budgeting with optional Tor egress support.

This module provides time-budgeted HTTP requests with optional Tor routing.
"""
import os
import socket
import ssl
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

class BudgetExceeded(TimeoutError, OSError):
    """Raised when a request exceeds its time budget."""
    def __init__(self, got, budget):
        super().__init__(f"Budget exceeded: got {got:.3f}s, budget {budget}s")
        self.got = got

def _get_with_tor(url, budget, timeout=10):
    """Make request through Tor network with budget enforcement."""
    from stem.control import Controller
    from stem.process import launch_tor_with_config

    config = {
        'SocksPort': '9050',
        'ControlPort': '9051',
        'DataDirectory': '/tmp/tor_egress',
        'HiddenServiceDir': '/tmp/tor_egress/hs',
        'HiddenServicePort': '80 127.0.0.1:8080',
    }

    try:
        tor_process = launch_tor_with_config(config=config, timeout=30)
        with Controller.from_port(port=9051) as controller:
            controller.authenticate()
            controller.signal(SIGNAL.NEWNYM)

            # Use Tor's SOCKS5 proxy
            proxy = 'socks5h://127.0.0.1:9050'
            return _get_with_proxy(url, budget, proxy, timeout)
    except Exception as e:
        raise BudgetExceeded(0, budget) from e
    finally:
        if 'tor_process' in locals():
            tor_process.kill()

def _get_with_proxy(url, budget, proxy, timeout):
    """Make request through proxy with budget enforcement."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Unsupported scheme: {parsed.scheme}")

    proxy_settings = {
        'http': proxy,
        'https': proxy,
    }

    opener = urlopen(Request(url), timeout=timeout)
    opener.addheaders = [('User-Agent', 'Echorune/1.0')]

    t0 = time.monotonic()
    try:
        with opener.open() as response:
            data = response.read()
            elapsed = time.monotonic() - t0
            if elapsed > budget:
                raise BudgetExceeded(elapsed, budget)
            return data
    except (URLError, HTTPError) as e:
        raise BudgetExceeded(time.monotonic() - t0, budget) from e

def get(url, budget, use_tor=False):
    """Fetch URL with time budget enforcement.

    Args:
        url: Target URL
        budget: Maximum allowed time in seconds
        use_tor: Whether to route through Tor network

    Returns:
        Response body as bytes

    Raises:
        BudgetExceeded: When request exceeds time budget
    """
    if use_tor:
        return _get_with_tor(url, budget)
    return _get_with_proxy(url, budget, None, 10)

class request_budget:
    """Context manager for request-level time budgeting."""
    def __init__(self, budget):
        self.budget = budget
        self.start = None

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            elapsed = time.monotonic() - self.start
            if elapsed > self.budget:
                raise BudgetExceeded(elapsed, self.budget)