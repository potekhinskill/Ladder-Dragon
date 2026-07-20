#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record and retain public depth archives without loading trading secrets.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
OUTPUT_DIR="${BOT_DEPTH_ARCHIVE_DIR:-/var/lib/ladder-dragon/depth-archives}"
SYMBOLS="${BOT_DEPTH_ARCHIVE_SYMBOLS:-SOLUSDT}"
DURATION_SEC="${BOT_DEPTH_ARCHIVE_DURATION_SEC:-840}"
MAX_EVENTS="${BOT_DEPTH_ARCHIVE_MAX_EVENTS:-250000}"
RETENTION_DAYS="${BOT_DEPTH_ARCHIVE_RETENTION_DAYS:-7}"

[[ "${DURATION_SEC}" =~ ^[0-9]+$ ]] || { echo "invalid duration" >&2; exit 2; }
[[ "${MAX_EVENTS}" =~ ^[0-9]+$ ]] || { echo "invalid max events" >&2; exit 2; }
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || { echo "invalid retention" >&2; exit 2; }
(( DURATION_SEC >= 60 && DURATION_SEC <= 3500 )) || { echo "duration out of range" >&2; exit 2; }
(( MAX_EVENTS >= 1000 && MAX_EVENTS <= 1000000 )) || { echo "max events out of range" >&2; exit 2; }
(( RETENTION_DAYS >= 3 && RETENTION_DAYS <= 90 )) || { echo "retention out of range" >&2; exit 2; }

install -d -m 0750 "${OUTPUT_DIR}"
exec 9>"${OUTPUT_DIR}/.recorder.lock"
flock -n 9 || { echo "depth recorder already running"; exit 0; }

IFS=',' read -r -a requested <<<"${SYMBOLS}"
for raw_symbol in "${requested[@]}"; do
  symbol="${raw_symbol//[[:space:]]/}"
  symbol="${symbol^^}"
  [[ "${symbol}" =~ ^[A-Z0-9]{1,20}$ ]] || { echo "invalid symbol" >&2; exit 2; }
  stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
  output="${OUTPUT_DIR}/${symbol}-${stamp}.jsonl"
  env -u BINANCE_API_KEY -u BINANCE_API_SECRET -u DEEPSEEK_API_KEY \
    PYTHONPATH="${PROJECT_DIR}" \
    "${PROJECT_DIR}/.venv/bin/python" -m bin.record_depth_archive \
    --symbol "${symbol}" \
    --output "${output}" \
    --duration-sec "${DURATION_SEC}" \
    --max-events "${MAX_EVENTS}"
done

find "${OUTPUT_DIR}" -xdev -type f \
  \( -name '*.jsonl' -o -name '*.metadata.json' \) \
  -mtime "+${RETENTION_DAYS}" -delete
