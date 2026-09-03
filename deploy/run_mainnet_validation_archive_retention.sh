#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run reviewed Mainnet validation evidence archival.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
CONFIG=/etc/ladder-dragon/backup.env

[[ "${EUID}" -eq 0 ]] \
  || { echo '[VALIDATION-RETENTION] status=BLOCKED error=RootRequired' >&2; exit 2; }
[[ -r "${CONFIG}" ]] \
  || { echo '[VALIDATION-RETENTION] status=BLOCKED error=ConfigUnavailable' >&2; exit 2; }

set -a
# The file is root-owned and validated by the backup installer.
source "${CONFIG}"
set +a

: "${BACKUP_AGE_RECIPIENT:?encrypted backup recipient is required}"
: "${BACKUP_EXTERNAL_MOUNT:?external backup mount is required}"
: "${BACKUP_EXTERNAL_DIR:?external backup directory is required}"

mode="${1:-}"
manifest_name="${2:-}"
[[ "${mode}" == preview || "${mode}" == apply ]] \
  || { echo '[VALIDATION-RETENTION] status=BLOCKED error=ModeInvalid' >&2; exit 2; }
[[ "${manifest_name}" =~ ^mainnet-validation-batch-[0-9]+\.[0-9]+\.[0-9]+\.json$ ]] \
  || { echo '[VALIDATION-RETENTION] status=BLOCKED error=ManifestNameInvalid' >&2; exit 2; }

case "${BACKUP_EXTERNAL_DIR}" in
  "${BACKUP_EXTERNAL_MOUNT}"/*) ;;
  *) echo '[VALIDATION-RETENTION] status=BLOCKED error=ExternalPath' >&2; exit 2 ;;
esac
[[ "$(findmnt -T "${BACKUP_EXTERNAL_MOUNT}" -no TARGET 2>/dev/null || true)" == "${BACKUP_EXTERNAL_MOUNT}" ]] \
  || { echo '[VALIDATION-RETENTION] status=BLOCKED error=MountUnavailable' >&2; exit 2; }

external_directory="${BACKUP_EXTERNAL_DIR}/validation-evidence"
if [[ "${mode}" == apply ]]; then
  mkdir -p "${external_directory}"
fi

arguments=(
  --manifest "${PROJECT_DIR}/logs/${manifest_name}"
  --directory "${PROJECT_DIR}/logs/replay-validation-archives"
  --external-directory "${external_directory}"
  --backup-status /run/mybot/backup_status.json
)
if [[ "${mode}" == apply ]]; then
  arguments+=(--apply --confirm ARCHIVE_REJECTED_VALIDATION_BATCH)
fi

exec "${PROJECT_DIR}/.venv/bin/python" \
  -m bin.mainnet_validation_archive_retention "${arguments[@]}"
