#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run encrypted L2 retention with validated root-owned settings.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
: "${BACKUP_AGE_RECIPIENT:?encrypted backup recipient is required}"
: "${BACKUP_EXTERNAL_MOUNT:?external backup mount is required}"
: "${BACKUP_EXTERNAL_DIR:?external backup directory is required}"

case "${BACKUP_EXTERNAL_DIR}" in
  "${BACKUP_EXTERNAL_MOUNT}"/*) ;;
  *) echo "[DEPTH-RETENTION] status=BLOCKED error=ExternalPath" >&2; exit 2 ;;
esac
[[ "$(findmnt -T "${BACKUP_EXTERNAL_MOUNT}" -no TARGET 2>/dev/null || true)" == "${BACKUP_EXTERNAL_MOUNT}" ]] \
  || { echo "[DEPTH-RETENTION] status=BLOCKED error=MountUnavailable" >&2; exit 2; }

# exFAT does not implement chmod. The mount options define external permissions.
mkdir -p "${BACKUP_EXTERNAL_DIR}/depth-evidence"
install -d -m 0700 /var/lib/ladder-dragon/depth-retention
exec "${PROJECT_DIR}/.venv/bin/python" -m bin.depth_archive_retention \
  --directory /var/lib/ladder-dragon/depth-archives \
  --external-directory "${BACKUP_EXTERNAL_DIR}/depth-evidence" \
  --prediction-db "${PROJECT_DIR}/db/prediction_shadow.sqlite3" \
  --backup-status /run/mybot/backup_status.json \
  --report /var/lib/ladder-dragon/depth-retention/report.json \
  --retention-days 14
