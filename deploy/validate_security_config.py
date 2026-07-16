#!/usr/bin/env python3
"""Fail-closed проверка production-конфигурации перед запуском сервисов."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDER_PREFIXES = ("replace_", "change_me", "your_", "ваш_")
OFFICIAL_BINANCE_HOSTS = {
    "api.binance.com",
    "api1.binance.com",
    "api2.binance.com",
    "api3.binance.com",
    "api4.binance.com",
    "testnet.binance.vision",
}
HEX_SECRET = re.compile(r"^[0-9a-fA-F]{64,}$")


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    return values


def require_private(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing file: {path}")
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        errors.append(f"{path} must not be accessible by group/other (mode {mode:o})")


def main() -> int:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    bot_env_path = project / ".env"
    dashboard_path = project / ".env.dashboard"
    service_path = project / ".env.service"
    errors: list[str] = []
    for path in (bot_env_path, dashboard_path):
        require_private(path, errors)
    if not service_path.is_file():
        errors.append(f"missing file: {service_path}")
    if errors:
        print("\n".join(f"[SECURITY] {error}" for error in errors), file=sys.stderr)
        return 2

    bot = parse_env(bot_env_path)
    dashboard = parse_env(dashboard_path)
    service = parse_env(service_path)

    for name in ("DASHBOARD_AUTH_TOKEN", "DASHBOARD_PROXY_AUTH_SECRET"):
        value = dashboard.get(name, "")
        if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
            errors.append(f"{name} is missing or contains a placeholder")
        elif not HEX_SECRET.fullmatch(value):
            errors.append(f"{name} must be at least 32 random bytes encoded as hex")

    if dashboard.get("DASHBOARD_TRUST_PROXY_AUTH") != "1":
        errors.append("DASHBOARD_TRUST_PROXY_AUTH must be 1 for managed deployment")

    venue = service.get("BOT_SERVICE_VENUE", "testnet")
    execution = service.get("BOT_SERVICE_EXECUTION", "dry")
    if venue not in {"testnet", "mainnet"}:
        errors.append("BOT_SERVICE_VENUE must be testnet or mainnet")
    if execution not in {"dry", "live"}:
        errors.append("BOT_SERVICE_EXECUTION must be dry or live")
    if execution == "live" and bot.get("BOT_LIVE_CONFIRMED") != "YES":
        errors.append("LIVE service requires BOT_LIVE_CONFIRMED=YES")

    base = bot.get(
        "BINANCE_API_BASE",
        "https://testnet.binance.vision" if venue == "testnet" else "https://api.binance.com",
    )
    parsed = urlparse(base)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in OFFICIAL_BINANCE_HOSTS
        or parsed.username
        or parsed.password
    ):
        errors.append("BINANCE_API_BASE must be an official HTTPS Binance endpoint")

    if errors:
        print("\n".join(f"[SECURITY] {error}" for error in errors), file=sys.stderr)
        return 2
    print("[OK] security configuration validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
