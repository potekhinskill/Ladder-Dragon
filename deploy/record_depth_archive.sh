#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run continuous public capture without trading credentials.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
OUTPUT_DIR="${BOT_DEPTH_ARCHIVE_DIR:-/var/lib/ladder-dragon/depth-archives}"
PREDICTION_DB="${PREDICTION_SHADOW_DB:-${PROJECT_DIR}/db/prediction_shadow.sqlite3}"
SYMBOLS="${BOT_DEPTH_ARCHIVE_SYMBOLS:-SOLUSDT}"
DURATION_SEC="${BOT_DEPTH_ARCHIVE_DURATION_SEC:-3300}"
MAX_EVENTS="${BOT_DEPTH_ARCHIVE_MAX_EVENTS:-250000}"
CAPACITY_BYTES="${BOT_DEPTH_ARCHIVE_CAPACITY_BYTES:-8589934592}"
CONTINUOUS="${BOT_DEPTH_ARCHIVE_CONTINUOUS:-1}"

[[ "${CONTINUOUS}" =~ ^[01]$ ]] || { echo "invalid continuous mode" >&2; exit 2; }
# One process owns one stream. Sequential multi-symbol loops create blind spots.
[[ "${SYMBOLS}" =~ ^[A-Z0-9]{1,20}$ ]] || { echo "one capture symbol is required" >&2; exit 2; }
install -d -m 0750 "${OUTPUT_DIR}"
exec 9>"${OUTPUT_DIR}/.recorder.lock"
flock -n 9 || { echo "depth recorder already running"; exit 0; }

options=()
if [[ "${CONTINUOUS}" == 0 ]]; then options+=(--once); fi
# Age-only deletion cannot distinguish calibration sources from protected evidence.
# Capacity exhaustion requires verified encrypted archival, not silent deletion.
exec env -u BINANCE_API_KEY -u BINANCE_API_SECRET -u DEEPSEEK_API_KEY \
  PYTHONPATH="${PROJECT_DIR}" \
  "${PROJECT_DIR}/.venv/bin/python" -m bin.depth_archive_service \
  --symbol "${SYMBOLS}" --directory "${OUTPUT_DIR}" \
  --prediction-db "${PREDICTION_DB}" \
  --duration-sec "${DURATION_SEC}" --max-events "${MAX_EVENTS}" \
  --capacity-bytes "${CAPACITY_BYTES}" "${options[@]}"
