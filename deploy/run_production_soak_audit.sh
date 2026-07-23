#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: generate and sign a sanitized production soak evidence artifact.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/bot/apps/binance_bot}"
SOAK_DIR="${SOAK_DIR:-/var/lib/ladder-dragon/soak}"
KEY_FILE="${SOAK_SIGNING_KEY:-/etc/ladder-dragon/soak-report-signing.pem}"
PUBLIC_KEY_FILE="${SOAK_PUBLIC_KEY:-/etc/ladder-dragon/soak-report-signing.pub.pem}"
REPORT="${SOAK_DIR}/production-soak-report.json"
SIGNATURE="${REPORT}.sig"
STATUS_STATE="${SOAK_DIR}/notification-state.json"

[[ "${EUID}" -eq 0 ]] || {
  echo "[FAIL] soak audit wrapper must run as root" >&2
  exit 1
}
[[ -x "${PROJECT_DIR}/.venv/bin/python" ]] || {
  echo "[FAIL] project Python is unavailable" >&2
  exit 1
}

install -d -o root -g root -m 0750 "${SOAK_DIR}"
install -d -o root -g root -m 0700 "$(dirname "${KEY_FILE}")"
if [[ ! -s "${KEY_FILE}" ]]; then
  key_tmp="${KEY_FILE}.tmp.$$"
  openssl genpkey -algorithm ED25519 -out "${key_tmp}"
  chmod 0600 "${key_tmp}"
  mv -f "${key_tmp}" "${KEY_FILE}"
fi
if [[ ! -s "${PUBLIC_KEY_FILE}" ]]; then
  pub_tmp="${PUBLIC_KEY_FILE}.tmp.$$"
  openssl pkey -in "${KEY_FILE}" -pubout -out "${pub_tmp}"
  chmod 0644 "${pub_tmp}"
  mv -f "${pub_tmp}" "${PUBLIC_KEY_FILE}"
fi

report_tmp="${SOAK_DIR}/.production-soak-report.json.$$"
signature_tmp="${SOAK_DIR}/.production-soak-report.json.sig.$$"
set +e
PYTHONPATH="${PROJECT_DIR}" "${PROJECT_DIR}/.venv/bin/python" \
  -m bin.production_soak_report \
  --runtime /run/mybot/ai_status.json \
  --journal "${PROJECT_DIR}/db/order_intents.sqlite3" \
  --required-hours 24 \
  --required-lifecycles 3 \
  --required-predictions 100 \
  --output "${report_tmp}" \
  --status-state "${STATUS_STATE}" \
  --notify-on-change >/dev/null
report_rc=$?
set -e
[[ "${report_rc}" == 0 || "${report_rc}" == 2 ]] || exit "${report_rc}"

openssl pkeyutl -sign -rawin -inkey "${KEY_FILE}" \
  -in "${report_tmp}" -out "${signature_tmp}"
chmod 0640 "${report_tmp}" "${signature_tmp}"
mv -f "${report_tmp}" "${REPORT}"
mv -f "${signature_tmp}" "${SIGNATURE}"
echo "[OK] signed soak report generated approved=$([[ "${report_rc}" == 0 ]] && echo true || echo false)"
