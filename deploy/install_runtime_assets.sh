#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: install root-owned runtime files from an already verified release.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "runtime assets must be installed as root"
[[ -d "${PROJECT_DIR}/deploy" ]] || fail "release deploy directory is missing"

install -d -o root -g root -m 0755 /usr/local/libexec/ladder-dragon
install -o root -g root -m 0644 \
  "${PROJECT_DIR}/deploy/export_sanitized_logs.py" \
  /usr/local/libexec/ladder-dragon/export_sanitized_logs.py
install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/pi-watchdog_v3.sh" \
  /usr/local/bin/pi-watchdog_v3.sh
install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/record_depth_archive.sh" \
  /usr/local/bin/ladder-dragon-depth-archive
install -o root -g root -m 0755 \
  "${PROJECT_DIR}/deploy/run_production_soak_audit.sh" \
  /usr/local/bin/ladder-dragon-soak-audit

echo "[OK] installed release runtime assets"
