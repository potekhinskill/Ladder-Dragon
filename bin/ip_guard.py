#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: inspect or explicitly accept a sanitized public-IP fingerprint.
"""Operate the public-IP guard without printing or persisting the IP itself."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

import requests

from ladder_dragon.execution.auth_resilience import (
    AuthResilienceState,
    accept_public_ip_fingerprint,
    load_auth_state,
    public_ip_fingerprint,
    save_auth_state,
)


def _state_path() -> Path:
    configured = os.getenv("BINANCE_AUTH_STATE_FILE", "").strip()
    if configured:
        return Path(configured)
    stats = os.getenv("BOT_STATS_DB", "").strip()
    if stats:
        return Path(stats).with_name("auth_resilience.json")
    return Path(".runtime/auth_resilience.json")


def _current_fingerprint() -> str:
    configured = os.getenv("BINANCE_PUBLIC_IP_ENDPOINTS", "").strip()
    if not configured:
        configured = os.getenv("BINANCE_PUBLIC_IP_ENDPOINT", "").strip()
    endpoints = [
        item.strip() for item in configured.split(",") if item.strip()
    ]
    fingerprints = []
    hosts = set()
    for endpoint in endpoints[:3]:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname in hosts
            or parsed.username
            or parsed.password
        ):
            continue
        hosts.add(parsed.hostname)
        response = requests.get(endpoint, timeout=5)
        response.raise_for_status()
        fingerprints.append(public_ip_fingerprint(response.text))
    if len(fingerprints) < 2 or len(set(fingerprints)) != 1:
        raise RuntimeError(
            "two independent public IP sources did not reach consensus"
        )
    return fingerprints[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "accept-current"))
    args = parser.parse_args(argv)
    path = _state_path()
    try:
        state = load_auth_state(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        if args.command != "accept-current":
            raise
        state = AuthResilienceState()
    if args.command == "status":
        print(
            "IP_GUARD "
            f"configured={bool(state.public_ip_sha256)} "
            f"changed={state.public_ip_changed} "
            f"fingerprint={state.public_ip_sha256[:12] or 'none'}"
        )
        return 2 if state.public_ip_changed else 0
    fingerprint = _current_fingerprint()
    save_auth_state(
        path,
        accept_public_ip_fingerprint(state, fingerprint),
    )
    print(
        "IP_GUARD accepted=true "
        f"fingerprint={fingerprint[:12]} "
        "next_step=restart_supervisor_after_whitelist_update"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"IP_GUARD error_type={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
