"""Outbound HTTPS egress proxy support for runemap.

Provides configurable egress routing for outbound requests, allowing routing
through non-datacenter endpoints or custom proxy services.
"""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple


class EgressConfig:
    """Configuration for outbound HTTPS egress routing."""

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        timeout: float = 30.0,
        verify_ssl: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.proxy_url = (
            proxy_url
            or os.environ.get("RUNEMAP_EGRESS_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
        )
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.headers = headers or {}

    def get_proxy_handler(self) -> Optional[urllib.request.ProxyHandler]:
        """Returns a ProxyHandler configured with the egress proxy URL if specified."""
        if not self.proxy_url:
            return None

        parsed = urllib.parse.urlparse(self.proxy_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid egress proxy URL: {self.proxy_url}")

        proxies = {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }
        return urllib.request.ProxyHandler(proxies)


_global_egress_config: Optional[EgressConfig] = None


def set_egress_proxy(proxy_url: Optional[str], **kwargs: Any) -> EgressConfig:
    """Set the global egress proxy URL for all outbound runemap requests."""
    global _global_egress_config
    _global_egress_config = EgressConfig(proxy_url=proxy_url, **kwargs)
    return _global_egress_config


def get_egress_config() -> EgressConfig:
    """Retrieve current global egress configuration or default."""
    global _global_egress_config
    if _global_egress_config is None:
        _global_egress_config = EgressConfig()
    return _global_egress_config


class EgressClient:
    """Client for performing outbound HTTPS requests using configured egress proxies."""

    def __init__(self, config: Optional[EgressConfig] = None) -> None:
        self.config = config or get_egress_config()

    def _build_opener(self) -> urllib.request.OpenerDirector:
        handlers = []
        proxy_handler = self.config.get_proxy_handler()
        if proxy_handler:
            handlers.append(proxy_handler)

        if not self.config.verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=context))

        return urllib.request.build_opener(*handlers)

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
    ) -> Tuple[int, bytes, Dict[str, str]]:
        """Executes an outbound HTTPS request through the configured egress proxy.

        Returns:
            Tuple of (status_code, body_bytes, headers_dict)
        """
        opener = self._build_opener()
        req_headers = dict(self.config.headers)
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(
            url,
            data=data,
            headers=req_headers,
            method=method.upper(),
        )

        try:
            with opener.open(req, timeout=self.config.timeout) as resp:
                status = resp.getcode()
                body = resp.read()
                resp_headers = dict(resp.headers)
                return status, body, resp_headers
        except urllib.error.HTTPError as err:
            body = err.read()
            return err.code, body, dict(err.headers)


def make_outbound_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    proxy_url: Optional[str] = None,
) -> Tuple[int, bytes, Dict[str, str]]:
    """Helper function to execute an outbound request with optional proxy override."""
    config = EgressConfig(proxy_url=proxy_url) if proxy_url else get_egress_config()
    client = EgressClient(config=config)
    return client.request(url=url, method=method, headers=headers, data=data)
diff --git a/tests/test_egress.py b/tests/test_egress.py
