"""Runemap package root."""

from runemap.egress import (
    EgressClient,
    EgressConfig,
    get_egress_config,
    make_outbound_request,
    set_egress_proxy,
)

__all__ = [
    "EgressConfig",
    "EgressClient",
    "make_outbound_request",
    "set_egress_proxy",
    "get_egress_config",
]
diff --git a/src/runemap/egress.py b/src/runemap/egress.py
