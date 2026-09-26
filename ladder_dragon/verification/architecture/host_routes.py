# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: require host route ownership and live dependency wiring.
"""Source-only dashboard contracts; no runtime initialization."""

from ladder_dragon.verification.architecture.route_contracts import audit_route_group
import time
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

HOST_PATHS = {"update_check": "/api/update/check", "health": "/api/health", "history": "/api/history"}
HOST_FIELDS = frozenset(["APP_TZ","GiB","HIST_FILE","PRODUCT_NAME","_OPS_CACHE","_OPS_CACHE_LOCK","_OPS_CACHE_TTL_SEC","__version__","_backup_snapshot","_binance_latency_snapshot","_github_update_snapshot","_host_snapshot","_load_ai_runtime_status","_ntp_snapshot","_open_db","_runtime_heartbeat_snapshot","_systemd_service_snapshot","_usb_snapshot","_user_stream_snapshot","fail2ban_bans","load_history_payload","mounts_info","network_ok","now_str","parse_throttled","read_deployment_status","read_temp_c","rolling_trade_volume_24h_usdt","service_active"])
RUNTIME = "ladder_dragon/dashboard/runtime.py"
ROUTER = "ladder_dragon/dashboard/routers/host.py"
STATE = "ladder_dragon/dashboard/host_dependencies.py"


def audit_host_routes(root):
    return audit_route_group(root, group="host", paths=HOST_PATHS, fields=HOST_FIELDS,
                             bodies={"health": 5, "history": 5,
                                     "update_check": "return JSONResponse(state._github_update_snapshot())"})


def check_host_routes(context):
    started = time.monotonic()
    try:
        violations = audit_host_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name="architecture_host_routes", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Concrete host routes and current dependency bindings",
                       exit_code=EXIT_CODES[status], metrics={"violations": violations})
