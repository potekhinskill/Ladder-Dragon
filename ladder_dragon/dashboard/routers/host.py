# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own host dashboard endpoint implementations.
"""Host routes consume explicit live dependencies without importing runtime."""

import os
import platform
import shutil
import sqlite3
import time

import psutil
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ladder_dragon.dashboard.host_dependencies import HostRouteState


def build_host_router(state: HostRouteState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/update/check")
    def update_check():
        return JSONResponse(state._github_update_snapshot())


    @router.get("/api/health")
    def health():
        """Return sanitized host and trading health without exposing credentials."""
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        temp = state.read_temp_c()
        disk = shutil.disk_usage("/")
        now_mono = time.monotonic()
        with state._OPS_CACHE_LOCK:
            ops = state._OPS_CACHE.get("payload")
            if ops is None or now_mono - float(state._OPS_CACHE.get("ts", 0.0)) >= state._OPS_CACHE_TTL_SEC:
                load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
                ops = {
                    "load_avg": {"1m": load[0], "5m": load[1], "15m": load[2]},
                    "services": {
                        "mybot": state._systemd_service_snapshot("mybot"),
                        "pi_healthd": state._systemd_service_snapshot("pi-healthd"),
                        "watchdog": state._systemd_service_snapshot("pi-watchdog-v3.timer"),
                    },
                    "heartbeat": state._runtime_heartbeat_snapshot(),
                    "ntp": state._ntp_snapshot(),
                    "binance": state._binance_latency_snapshot(),
                    "usb_backup": state._usb_snapshot(),
                    "backup": state._backup_snapshot(),
                    "user_stream": state._user_stream_snapshot(
                        state._load_ai_runtime_status()
                    ),
                }
                state._OPS_CACHE["ts"] = now_mono
                state._OPS_CACHE["payload"] = ops
        network_probe_ok = state.network_ok()
        effective_network_ok = network_probe_ok or bool((ops.get("binance") or {}).get("ok"))
        return JSONResponse({
            "product": {"name": state.PRODUCT_NAME, "version": state.__version__},
            "changelog_url": "/CHANGELOG.md",
            "time": state.now_str(),
            "kernel": platform.release() or None,
            "host": state._host_snapshot(),
            "temp_c": temp,
            "throttled": state.parse_throttled(),
            "mem_gib": {
                "total": round(vm.total/state.GiB,3),
                "used": round(vm.used/state.GiB,3),
                "percent": vm.percent
            },
            "swap_gib": {
                "total": round(sm.total/state.GiB,3),
                "used": round(sm.used/state.GiB,3),
                "percent": sm.percent
            },
            "disk_gib": {
                "total": round(disk.total/state.GiB,3),
                "used": round(disk.used/state.GiB,3),
                "percent": round(disk.used*100.0/disk.total,1)
            },
            "mounts": state.mounts_info(),
            "services": {
                "mybot": state.service_active("mybot"),
                "fail2ban_sshd_bans": state.fail2ban_bans("sshd")
            },
            "uptime_sec": int(time.time() - psutil.boot_time()),
            # DNS/53 may be blocked on a local network; a successful Binance probe
            # is the more relevant signal for the trading channel.
            "network_ok": effective_network_ok,
            "network_probe_ok": network_probe_ok,
            "operations": ops,
            "deployment": state.read_deployment_status(),
        })


    @router.get("/api/history")
    def history(hours: int = 24, points: int = 288):
        hours = max(1, min(hours, 168))
        payload = state.load_history_payload(
            state.HIST_FILE,
            cutoff_epoch=int(time.time()) - hours * 3600,
            points=points,
            timezone=state.APP_TZ,
        )
        epochs = payload.pop("_epochs")
        connection = None
        try:
            connection, _ = state._open_db()
            payload["trading_volume_24h_usdt"] = state.rolling_trade_volume_24h_usdt(
                connection, epochs
            )
            payload["trading_volume_24h_status"] = "exact"
        except (OSError, sqlite3.Error, RuntimeError, ValueError):
            payload["trading_volume_24h_usdt"] = [None] * len(epochs)
            payload["trading_volume_24h_status"] = "unavailable"
        finally:
            if connection is not None:
                connection.close()
        return JSONResponse(payload)

    return router
