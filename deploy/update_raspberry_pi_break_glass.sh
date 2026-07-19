#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: create a one-use, journaled root authorization for an unsigned update.
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "[FAIL] run with sudo" >&2; exit 1; }
[[ "${1:-}" =~ ^[0-9a-fA-F]{40}$ ]] \
  || { echo "usage: sudo $0 40_CHAR_COMMIT_SHA" >&2; exit 2; }
[[ -t 0 ]] || { echo "[FAIL] break-glass requires an interactive terminal" >&2; exit 1; }

commit="${1,,}"
expected="AUTHORIZE UNSIGNED UPDATE ${commit}"
printf 'Type exactly: %s\n> ' "${expected}" >/dev/tty
IFS= read -r confirmation </dev/tty
[[ "${confirmation}" == "${expected}" ]] \
  || { echo "[FAIL] confirmation mismatch" >&2; exit 1; }

install -d -o root -g root -m 0700 /run/ladder-dragon
printf '%s\n' "${commit}" >/run/ladder-dragon/update-break-glass
chown root:root /run/ladder-dragon/update-break-glass
chmod 0600 /run/ladder-dragon/update-break-glass
logger --priority authpriv.warning --tag ladder-dragon-update \
  "BREAK_GLASS authorized unsigned update commit=${commit} uid=${SUDO_UID:-0}"
echo "[BREAK-GLASS] one-use authorization created for ${commit}"
