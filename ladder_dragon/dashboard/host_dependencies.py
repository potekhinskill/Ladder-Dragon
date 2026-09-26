# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live host-route dependencies.
"""A read-only interface to current dependencies, not a security sandbox."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

HOST_FIELDS = frozenset((
    "APP_TZ",
    "GiB",
    "HIST_FILE",
    "PRODUCT_NAME",
    "_OPS_CACHE",
    "_OPS_CACHE_LOCK",
    "_OPS_CACHE_TTL_SEC",
    "__version__",
    "_backup_snapshot",
    "_binance_latency_snapshot",
    "_github_update_snapshot",
    "_host_snapshot",
    "_load_ai_runtime_status",
    "_ntp_snapshot",
    "_open_db",
    "_runtime_heartbeat_snapshot",
    "_systemd_service_snapshot",
    "_usb_snapshot",
    "_user_stream_snapshot",
    "fail2ban_bans",
    "load_history_payload",
    "mounts_info",
    "network_ok",
    "now_str",
    "parse_throttled",
    "read_deployment_status",
    "read_temp_c",
    "rolling_trade_volume_24h_usdt",
    "service_active",
))


@dataclass(frozen=True)
class HostRouteState:
    """Keep current cache, lock, path, and reader bindings across requests."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in HOST_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
