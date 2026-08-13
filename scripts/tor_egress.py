#!/usr/bin/env python3
"""Tor egress integration for Echorune.

Provides controlled access to Tor network for outbound HTTPS requests.
"""
import os
import signal
import time
from stem import Signal
from stem.control import Controller
from stem.process import launch_tor_with_config

class TorEgress:
    """Managed Tor connection for egress traffic."""

    def __init__(self, config=None):
        self.config = config or {
            'SocksPort': '9050',
            'ControlPort': '9051',
            'DataDirectory': '/tmp/tor_egress',
            'HiddenServiceDir': '/tmp/tor_egress/hs',
            'HiddenServicePort': '80 127.0.0.1:8080',
            'SocksPolicy': 'reject *:*',
            'ExitPolicy': 'reject *:*',
        }
        self.process = None
        self.controller = None

    def start(self):
        """Launch Tor process with configured settings."""
        try:
            self.process = launch_tor_with_config(
                config=self.config,
                timeout=30,
                take_ownership=True
            )
            self.controller = Controller.from_port(port=9051)
            self.controller.authenticate()
            self.controller.signal(Signal.NEWNYM)
            return True
        except Exception as e:
            self.cleanup()
            raise RuntimeError(f"Failed to start Tor: {e}")

    def cleanup(self):
        """Stop Tor process and clean up resources."""
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
            self.process = None
        if self.controller:
            try:
                self.controller.close()
            except Exception:
                pass
            self.controller = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    @property
    def proxy_url(self):
        """Get current SOCKS5 proxy URL."""
        return 'socks5h://127.0.0.1:9050'

    def rotate_circuit(self):
        """Rotate Tor circuit for new identity."""
        if self.controller:
            self.controller.signal(Signal.NEWNYM)
            time.sleep(2)  # Wait for circuit to establish