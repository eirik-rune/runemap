#!/usr/bin/env python3
"""Tests for Tor egress integration with net_budget."""
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import net_budget  # noqa: E402
import tor_egress  # noqa: E402

class TestTorEgress(unittest.TestCase):
    """Test Tor egress functionality."""

    def setUp(self):
        self.tor = tor_egress.TorEgress(config={
            'DataDirectory': '/tmp/tor_test',
            'ControlPort': '9052',
        })

    def test_tor_egress_lifecycle(self):
        """Test Tor process lifecycle management."""
        with patch('stem.process.launch_tor_with_config') as mock_launch:
            mock_launch.return_value = MagicMock()
            with self.tor:
                self.assertTrue(mock_launch.called)
                self.assertIsNotNone(self.tor.controller)
                self.assertIsNotNone(self.tor.process)

        self.assertIsNone(self.tor.controller)
        self.assertIsNone(self.tor.process)

    def test_tor_proxy_url(self):
        """Test proxy URL generation."""
        with patch('stem.process.launch_tor_with_config') as mock_launch:
            mock_launch.return_value = MagicMock()
            with self.tor:
                self.assertEqual(self.tor.proxy_url, 'socks5h://127.0.0.1:9050')

    @patch('stem.control.Controller