"""Tests for runemap egress proxy module."""

import os
import unittest
from unittest.mock import MagicMock, patch

from runemap.egress import (
    EgressClient,
    EgressConfig,
    get_egress_config,
    make_outbound_request,
    set_egress_proxy,
)


class TestEgressConfig(unittest.TestCase):

    def test_default_config_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            config = EgressConfig()
            self.assertIsNone(config.proxy_url)
            self.assertIsNone(config.get_proxy_handler())

    def test_config_explicit_proxy(self):
        config = EgressConfig(proxy_url="http://proxy.example.com:8080")
        self.assertEqual(config.proxy_url, "http://proxy.example.com:8080")
        handler = config.get_proxy_handler()
        self.assertIsNotNone(handler)

    def test_config_env_variable(self):
        with patch.dict(os.environ, {"RUNEMAP_EGRESS_PROXY": "http://1.2.3.4:3128"}):
            config = EgressConfig()
            self.assertEqual(config.proxy_url, "http://1.2.3.4:3128")

    def test_invalid_proxy_url_raises(self):
        config = EgressConfig(proxy_url="invalid_url_no_scheme")
        with self.assertRaises(ValueError):
            config.get_proxy_handler()


class TestEgressClient(unittest.TestCase):

    def test_set_and_get_global_proxy(self):
        set_egress_proxy("http://non-datacenter.egress.net:8080")
        cfg = get_egress_config()
        self.assertEqual(cfg.proxy_url, "http://non-datacenter.egress.net:8080")

    @patch("urllib.request.OpenerDirector.open")
    def test_make_outbound_request(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b"OK"
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_open.return_value.__enter__.return_value = mock_resp

        status, body, headers = make_outbound_request(
            "https://echo.echorune.net",
            proxy_url="http://residential.egress.net:8080",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"OK")
        self.assertIn("Content-Type", headers)


if __name__ == "__main__":
    unittest.main()
