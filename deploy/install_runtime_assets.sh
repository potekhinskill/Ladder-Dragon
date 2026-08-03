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

retire_legacy_stats_sync() {
  local unit_dir="${1:-/etc/systemd/system}"
  local service="${unit_dir}/bot-stats-sync.service"
  local timer="${unit_dir}/bot-stats-sync.timer"

  if [[ ! -e "${service}" && ! -e "${timer}" ]]; then
    systemctl reset-failed bot-stats-sync.service 2>/dev/null || true
    return 0
  fi

  # Remove only the known legacy units. A conflicting operator unit must fail closed.
  if [[ -e "${service}" ]]; then
    grep -Fqx "ExecStart=${PROJECT_DIR}/stats_sync.sh" "${service}" \
      || fail "bot-stats-sync.service is not the known legacy unit"
  fi
  if [[ -e "${timer}" ]]; then
    grep -Fqx "Unit=bot-stats-sync.service" "${timer}" \
      || fail "bot-stats-sync.timer is not the known legacy unit"
  fi

  if [[ -e "${timer}" ]]; then
    systemctl disable --now bot-stats-sync.timer 2>/dev/null \
      || fail "could not stop legacy bot-stats-sync.timer"
  fi
  if [[ -e "${service}" ]]; then
    systemctl stop bot-stats-sync.service 2>/dev/null \
      || fail "could not stop legacy bot-stats-sync.service"
    systemctl disable bot-stats-sync.service 2>/dev/null || true
  fi
  rm -f -- "${service}" "${timer}"
  systemctl daemon-reload
  systemctl reset-failed bot-stats-sync.service 2>/dev/null || true
  echo "[OK] retired legacy bot-stats-sync units"
}

remove_idle_interface_watchdog_check() {
  local config="${1:-/etc/watchdog.conf}"
  local temporary

  [[ -f "${config}" ]] || return 0
  grep -Eq \
    '^[[:space:]]*interface[[:space:]]*=[[:space:]]*wlan0[[:space:]]*(#.*)?$' \
    "${config}" || return 0

  temporary="$(mktemp "${config}.tmp.XXXXXX")"
  awk \
    '!/^[[:space:]]*interface[[:space:]]*=[[:space:]]*wlan0[[:space:]]*(#.*)?$/' \
    "${config}" >"${temporary}"
  chown --reference="${config}" "${temporary}"
  chmod --reference="${config}" "${temporary}"
  mv -f -- "${temporary}" "${config}"

  # Keep the hardware watchdog active. Network health has a separate hysteresis check.
  if systemctl is-active --quiet watchdog.service; then
    systemctl restart watchdog.service \
      || fail "hardware watchdog could not restart"
    systemctl is-active --quiet watchdog.service \
      || fail "hardware watchdog did not restart"
  fi
  echo "[OK] removed idle wlan0 check from hardware watchdog"
}

repair_failed_atop_service() {
  local unit="${1:-/lib/systemd/system/atop.service}"
  local log_dir="${2:-/var/log/atop}"

  [[ -f "${unit}" ]] || return 0
  systemctl is-failed --quiet atop.service || return 0

  # Repair only the packaged service that writes its daily files to /var/log/atop.
  grep -Fqx 'Environment="LOGPATH=/var/log/atop"' "${unit}" || return 0
  grep -Fq '/usr/bin/atop ${LOGOPTS} -w "${LOGPATH}/atop_' "${unit}" \
    || return 0
  if [[ -e "${log_dir}" && ! -d "${log_dir}" ]]; then
    fail "atop log path exists but is not a directory"
  fi
  install -d -m 0755 "${log_dir}"
  systemctl reset-failed atop.service 2>/dev/null || true
  systemctl start atop.service || fail "repaired atop.service could not start"
  systemctl is-active --quiet atop.service \
    || fail "repaired atop.service is not active"
  echo "[OK] repaired failed atop.service log directory"
}

disable_failed_rtl_tcp_without_device() {
  local unit="${1:-/etc/systemd/system/rtl_tcp.service}"
  local usb_root="${2:-/sys/bus/usb/devices}"
  local vendor_file vendor

  [[ -f "${unit}" ]] || return 0
  systemctl is-failed --quiet rtl_tcp.service || return 0

  # Disable only the observed local unit. Preserve every modified operator unit.
  grep -Fqx 'Description=RTL-SDR TCP server' "${unit}" || return 0
  grep -Fqx \
    'ExecStart=/usr/bin/rtl_tcp -a 0.0.0.0 -p 1234 -s 2048000 -g 35' \
    "${unit}" || return 0
  for vendor_file in "${usb_root}"/*/idVendor; do
    [[ -f "${vendor_file}" ]] || continue
    vendor="$(tr '[:upper:]' '[:lower:]' <"${vendor_file}")"
    [[ "${vendor}" == "0bda" ]] && return 0
  done
  systemctl disable --now rtl_tcp.service 2>/dev/null \
    || fail "failed rtl_tcp.service could not be disabled"
  systemctl reset-failed rtl_tcp.service 2>/dev/null || true
  echo "[OK] disabled failed rtl_tcp.service without an RTL-SDR device"
}

[[ "${EUID}" -eq 0 ]] || fail "runtime assets must be installed as root"
[[ -d "${PROJECT_DIR}/deploy" ]] || fail "release deploy directory is missing"

install -d -o root -g root -m 0755 /usr/local/libexec/ladder-dragon
install -d -o bot -g bot -m 0700 /var/lib/ladder-dragon/digests
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

retire_legacy_stats_sync
remove_idle_interface_watchdog_check
repair_failed_atop_service
disable_failed_rtl_tcp_without_device

echo "[OK] installed release runtime assets"
